"""Builds data/characters.json from AniList.

    python tools/fetch_roster.py --count 100000

AniList will not paginate past 5000 entries of ANY sorted list - characters,
anime, manga alike. Asking for "the most popular anime" therefore hands back
at most 5000 shows and stops, which is nowhere near enough casts to reach a
six-figure roster.

The way through is that the cap is per query, not per database: a query
narrowed to one year is its own 5000-entry budget. So this walks release-date
windows, newest first, and splits a window into months if it ever holds more
than 5000 entries. Between them the windows tile the whole calendar, which
means every anime AniList knows about is reachable. Manga is then swept the
same way, for the many characters who never got an adaptation.

A character who appears in several shows is filed under the most popular one,
since that is the show people know them from - tracked as we go rather than
taken from whichever window happened to come first.

Every character carries their own favourites count, so ranks are real
popularity data: the set is sorted by favourites once collecting finishes,
and rank 1 is the most-favourited character found.

Value is mapped from rank on a LOG scale, not a linear one. With a pool this
size a linear curve leaves the middle of the pack worth hundreds; on a log
curve only genuinely famous characters clear 300 and the long tail settles
near the floor.

Adult media is skipped, as are characters AniList has no portrait for.

Only stdlib. Paced for AniList's live 30 requests/minute limit, so a full
sweep takes about two hours. That is long enough that losing it would hurt,
so the roster is checkpointed as it goes, Ctrl-C still writes out what has
been collected, and a phase that falls over is reported rather than throwing
the rest away. To carry on from an earlier run instead of repeating it:

    python tools/fetch_roster.py --resume data/characters.json --skip-anime
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://graphql.anilist.co"

QUERY = """
query ($page: Int, $perPage: Int, $castSize: Int, $type: MediaType,
       $after: FuzzyDateInt, $before: FuzzyDateInt) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { total hasNextPage }
    media(type: $type, sort: POPULARITY_DESC, isAdult: false,
          startDate_greater: $after, startDate_lesser: $before) {
      popularity
      title { romaji english }
      characters(sort: FAVOURITES_DESC, perPage: $castSize) {
        nodes {
          id
          name { full }
          favourites
          image { large }
        }
      }
    }
  }
}
"""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")

KARUDA_MIN, KARUDA_MAX = 20, 1300

# Where the value curve crosses 300: only characters inside this rank are
# worth more than that. Everything below settles towards KARUDA_MIN.
PREMIUM_RANK = 300
PREMIUM_VALUE = 300

# AniList's hard ceiling on how deep any one sorted list can be paged.
PAGE_DEPTH_LIMIT = 5000

# Anime predating this is vanishingly rare and almost never has portraits.
EARLIEST_YEAR = 1940


class Client:
    """One AniList connection, with the rate limit respected rather than
    discovered. The server allows 30 requests a minute; going faster just
    earns 429s and the Retry-After sleep costs more than the pacing does."""

    def __init__(self, delay: float):
        self.delay = delay
        self.last = 0.0
        self.requests = 0

    def post(self, variables: dict, attempt: int = 0):
        wait = self.delay - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        body = json.dumps({"query": QUERY, "variables": variables}).encode()
        request = urllib.request.Request(
            API,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "gachabot-roster/2.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.last = time.time()
            self.requests += 1
            if "errors" in payload and not payload.get("data"):
                raise RuntimeError(payload["errors"])
            return payload["data"]["Page"]
        except urllib.error.HTTPError as error:
            self.last = time.time()
            if error.code in (429, 500, 502, 503, 504) and attempt < 6:
                pause = int(error.headers.get("Retry-After") or 0) or (
                    5 * (attempt + 1)
                )
                print(f"    rate limited, waiting {pause}s", flush=True)
                time.sleep(pause)
                return self.post(variables, attempt + 1)
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            self.last = time.time()
            if attempt < 5:
                time.sleep(3 * (attempt + 1))
                return self.post(variables, attempt + 1)
            raise RuntimeError(f"network: {error}")


def karuda_for_rank(rank: int, total: int) -> int:
    """Rank to value on a log scale.

    A linear curve over a hundred thousand characters leaves rank 1000 worth
    several hundred, which makes nothing feel scarce. Taking the log of the
    rank compresses the long tail and keeps the money at the very top.
    """
    import math

    if total <= 1:
        return KARUDA_MAX
    t = math.log(rank) / math.log(total)
    # Exponent chosen so the curve passes through (PREMIUM_RANK, PREMIUM_VALUE).
    pin = math.log(PREMIUM_RANK) / math.log(total)
    share = (PREMIUM_VALUE - KARUDA_MIN) / (KARUDA_MAX - KARUDA_MIN)
    exponent = math.log(share) / math.log(1 - pin) if 0 < pin < 1 else 2.0
    return max(
        KARUDA_MIN,
        round(KARUDA_MIN + (KARUDA_MAX - KARUDA_MIN) * (1 - t) ** exponent),
    )


def claim_rank_for(like_rank: int, name: str, total: int) -> int:
    """Claim rank sits near like rank but not on top of it. Derived from the
    name so it is stable between runs rather than reshuffling every time."""
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    offset = (digest[0] / 255 - 0.5) * 0.30  # +/- 15%
    return max(1, min(total, round(like_rank * (1 + offset))))


def should_split(total: int, after, before, splittable: bool = True) -> bool:
    """Whether this window has to be cut into months to be read in full.

    The test is "reached the cap", not "past it". AniList clamps
    pageInfo.total at the 5000-entry page-depth limit, so a year holding
    twenty thousand titles reports exactly five thousand - the same number as
    a year that really has five thousand. Reading it as "past it" means the
    split never fires at all and everything below a year's 5000th title is
    quietly lost.

    Whether a window can be cut again is passed in rather than guessed from
    how wide it is. Months are not all the same width - the first one carries
    the titles filed with no month at all - so measuring the span to decide
    made January look like a year and split it into itself forever.
    """
    return (
        splittable
        and total >= PAGE_DEPTH_LIMIT
        and bool(after)
        and bool(before)
    )


def window_variables(after, before) -> dict:
    """The date arguments for one window.

    A bound that is not set is left out rather than sent as null: AniList
    rejects an explicit null with "Illegal operator and value combination"
    instead of reading it as "no filter", which takes the whole sweep down.
    """
    variables = {}
    if after:
        variables["after"] = after - 1
    if before:
        variables["before"] = before
    return variables


def months(year: int) -> list:
    """One window per month of a year, for when a whole year is too big.

    The first window opens at YYYY0000 rather than YYYY0100. AniList dates
    are fuzzy, and plenty of older titles are filed with a year and no month
    at all - starting at January would step straight over every one of them.
    """
    edges = [year * 10000]
    edges += [year * 10000 + month * 100 for month in range(2, 13)]
    edges.append((year + 1) * 10000)
    return list(zip(edges, edges[1:]))


class Collector:
    """Sweeps windows and keeps the best record of each character found."""

    def __init__(self, client: Client, cast_size: int, checkpoint=None,
                 every: int = 150):
        self.client = client
        self.cast_size = cast_size
        # An hour of fetching is too much to lose to one bad night on the
        # network, so the roster is written out periodically as well as at
        # the end.
        self.checkpoint = checkpoint
        self.every = every
        # character id -> (popularity of the show they were found in, record).
        # Keeping the popularity lets a later, bigger show take over the entry,
        # so ordering of the sweep does not decide which series they are filed
        # under.
        self.best = {}
        self.blank = set()  # no portrait: remembered so we stop reconsidering
        self.media_seen = 0

    def count(self) -> int:
        return len(self.best)

    def resume(self, rows) -> int:
        """Seed from a roster already on disk and carry on.

        Records are re-admitted at infinite popularity, so a later phase can
        add characters but never re-file an existing one. That is what we
        want between phases: every anime has already been swept, and the show
        someone appeared in is the name people know them by.
        """
        for row in rows:
            cid = row.get("anilist_id")
            if cid is None:
                continue
            self.best[cid] = (float("inf"), {
                "name": row["name"],
                "series": row["series"],
                "image_url": row["image_url"],
                "likes": row.get("likes", 0),
                "favourites": row.get("favourites") or 0,
                "anilist_id": cid,
                "source": row.get("source", "AniList"),
            })
        return len(self.best)

    def absorb(self, media_list) -> None:
        for media in media_list:
            title = (media.get("title") or {}).get("english") or (
                media.get("title") or {}
            ).get("romaji")
            if not title:
                continue
            self.media_seen += 1
            popularity = media.get("popularity") or 0
            for entry in (media.get("characters") or {}).get("nodes") or []:
                cid = entry["id"]
                if cid in self.blank:
                    continue
                known = self.best.get(cid)
                if known and known[0] >= popularity:
                    continue  # already filed under a show people know better
                name = (entry.get("name") or {}).get("full")
                image = (entry.get("image") or {}).get("large") or ""
                if not name:
                    continue
                if not image or "default.jpg" in image:
                    self.blank.add(cid)
                    continue
                self.best[cid] = (
                    popularity,
                    {
                        "name": name,
                        "series": title,
                        "image_url": image,
                        "likes": 0,
                        "favourites": entry.get("favourites") or 0,
                        "anilist_id": cid,
                        "source": "AniList",
                    },
                )

    def sweep(self, media_type: str, after: int, before: int, label: str,
              target: int, per_page: int, splittable: bool = True) -> None:
        """Walk one date window, splitting it up if AniList caps us out.

        A window that is already the result of a split is not split again.
        """
        page = 1
        while self.count() < target:
            variables = {
                "page": page,
                "perPage": per_page,
                "castSize": self.cast_size,
                "type": media_type,
            }
            variables.update(window_variables(after, before))
            data = self.client.post(variables)
            total = data["pageInfo"]["total"] or 0

            # Too big to page through: cut it into months and do those instead.
            if page == 1 and should_split(total, after, before, splittable):
                year = after // 10000
                print(f"  {label}: at least {total} entries, splitting by month",
                      flush=True)
                for start, end in months(year):
                    if self.count() >= target:
                        return
                    self.sweep(media_type, start, end,
                               f"{year}-{(start // 100) % 100:02d}",
                               target, per_page, splittable=False)
                return

            self.absorb(data["media"])
            print(
                f"  {label:>9}  page {page:>3}/{min(total, PAGE_DEPTH_LIMIT) // per_page + 1:<3}"
                f"  {self.media_seen:>6} titles  {self.count():>6} characters",
                flush=True,
            )
            if self.checkpoint and self.client.requests % self.every == 0:
                self.checkpoint(self)

            if not data["pageInfo"]["hasNextPage"]:
                return
            if (page + 1) * per_page > PAGE_DEPTH_LIMIT:
                print(f"  {label}: hit the 5000 cap", flush=True)
                return
            page += 1


def finish(collector: Collector, count: int) -> list:
    """Rank everything collected and cut to size."""
    rows = [record for _, record in collector.best.values()]
    rows.sort(key=lambda r: (-r["favourites"], r["name"]))

    # The database keys characters on name + series, and AniList sometimes
    # lists two entries with the same name in one show. Keep the more
    # favourited of each pair, or the import silently drops the rest.
    unique, pairs = [], set()
    for row in rows:
        pair = (row["name"], row["series"])
        if pair in pairs:
            continue
        pairs.add(pair)
        unique.append(row)
    rows = unique[:count]

    return rows


def write(rows: list, path: str) -> None:
    # One compact record per line: a third the size of indented JSON, and it
    # still diffs line by line when the roster changes.
    tmp = path + ".writing"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write("[\n")
        handle.write(
            ",\n".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                for row in rows
            )
        )
        handle.write("\n]\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=100000)
    parser.add_argument("--delay", type=float, default=2.1,
                        help="seconds between requests (30/min is the limit)")
    parser.add_argument("--cast", type=int, default=25,
                        help="characters per title; AniList caps this at 25")
    parser.add_argument("--per-page", type=int, default=50,
                        help="titles per request")
    parser.add_argument("--from-year", type=int, default=None,
                        help="newest year to sweep (default: next year)")
    parser.add_argument("--resume", default=None,
                        help="carry on from a roster file already written")
    parser.add_argument("--skip-anime", action="store_true",
                        help="go straight to manga (use with --resume)")
    parser.add_argument("--skip-manga-top", action="store_true",
                        help="skip the manga popularity pass, which a resumed"
                             " run has usually already done")
    parser.add_argument("--manga-years", action="store_true",
                        help="sweep manga year by year as well as by "
                             "popularity, for the deepest possible pool")
    parser.add_argument("--out", default=DATA)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    newest = args.from_year or (time.gmtime().tm_year + 1)
    client = Client(args.delay)

    def checkpoint(current):
        write(finish(current, args.count), args.out)
        print(f"    checkpoint: {current.count():,} characters saved",
              flush=True)

    collector = Collector(client, args.cast, checkpoint)

    if args.resume:
        with open(args.resume, "r", encoding="utf-8") as handle:
            existing = json.load(handle)
        print(f"Resuming from {collector.resume(existing):,} characters",
              flush=True)

    print(f"Collecting up to {args.count:,} characters", flush=True)
    print(f"  {newest} back to {EARLIEST_YEAR}, anime then manga\n", flush=True)
    started = time.time()

    try:
        # Anime first: every year gets swept, so the whole catalogue is
        # reachable rather than just the 5000 most popular shows.
        for year in range(newest, EARLIEST_YEAR - 1, -1):
            if args.skip_anime or collector.count() >= args.count:
                break
            collector.sweep("ANIME", year * 10000, (year + 1) * 10000,
                            str(year), args.count, args.per_page)

        # Then manga, for everyone who never got an adaptation. Popularity
        # order first, so the best-known manga-only characters arrive even if
        # the target is met part way through.
        if not args.skip_manga_top and collector.count() < args.count:
            print("\n  switching to manga\n", flush=True)
            collector.sweep("MANGA", None, None, "manga",
                            args.count, args.per_page)

        if args.manga_years and collector.count() < args.count:
            print("\n  manga, year by year\n", flush=True)
            for year in range(newest, EARLIEST_YEAR - 1, -1):
                if collector.count() >= args.count:
                    break
                collector.sweep("MANGA", year * 10000, (year + 1) * 10000,
                                f"m{year}", args.count, args.per_page)
    except KeyboardInterrupt:
        print("\n  stopped early - writing what we have", flush=True)
    except Exception as error:  # noqa: BLE001 - a partial roster beats none
        print(f"\n  sweep failed ({error!r}) - writing what we have",
              flush=True)

    rows = finish(collector, args.count)
    # Ranked by utils so the sweep, tools/add_series.py and the bot cannot
    # drift apart about what a character is worth. It also applies the claim
    # weighting, which the sweep has no business deciding on its own.
    sys.path.insert(0, ROOT)
    import utils  # noqa: E402

    utils.rerank_roster(rows)
    total = len(rows)
    write(rows, args.out)

    series = len({r["series"] for r in rows})
    over_300 = sum(1 for r in rows if r["base_karuda"] > 300)
    minutes = (time.time() - started) / 60
    print(f"\nWrote {total:,} characters from {series:,} series to {args.out}")
    print(f"  {client.requests:,} requests over {minutes:.0f} minutes")
    print(f"  worth over 300: {over_300}  ({100 * over_300 / total:.2f}% of the pool)")
    print("\n  rank     value  character")
    for rank in (1, 10, 100, 300, 1000, 5000, 25000, 60000, total):
        if rank <= total:
            row = rows[rank - 1]
            print(f"  {rank:>6}  {row['base_karuda']:>6}  "
                  f"{row['name']} ({row['series']})"[:70])


if __name__ == "__main__":
    main()
