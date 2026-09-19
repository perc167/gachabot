"""Builds data/characters.json from AniList.

    python tools/fetch_roster.py --count 30000

Walks anime in popularity order and takes each show's cast, mainstream first
and on down into the niche. That is the only way to reach a pool this size:
AniList's global character list refuses to paginate past 5000 results, so
asking it for the most-favourited characters directly tops out there.

Every character carries its own favourites count, so ranks are still real
popularity data - the whole set is sorted by favourites once collecting
finishes, and rank 1 is the most-favourited character found.

Value is mapped from rank on a LOG scale, not a linear one. With tens of
thousands of characters a linear curve leaves the middle of the pack worth
hundreds; on a log curve only genuinely famous characters clear 300 and the
long tail settles near the floor.

Adult media is skipped, as are characters AniList has no portrait for. A
character appearing in several shows is filed under the most popular one,
since that is the show people know them from.

Only stdlib. About 45 requests a minute against AniList's 90/min limit.
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
query ($page: Int, $perPage: Int, $castSize: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: false) {
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


def request(page: int, per_page: int, cast_size: int, attempt: int = 0):
    body = json.dumps(
        {
            "query": QUERY,
            "variables": {"page": page, "perPage": per_page, "castSize": cast_size},
        }
    ).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "gachabot-roster/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if "errors" in payload and not payload.get("data"):
            raise RuntimeError(payload["errors"])
        return payload["data"]["Page"]
    except urllib.error.HTTPError as error:
        if error.code in (429, 500, 502, 503, 504) and attempt < 5:
            wait = int(error.headers.get("Retry-After") or 0) or (5 * (attempt + 1))
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)
            return request(page, per_page, cast_size, attempt + 1)
        raise
    except (urllib.error.URLError, TimeoutError) as error:
        if attempt < 4:
            time.sleep(3 * (attempt + 1))
            return request(page, per_page, cast_size, attempt + 1)
        raise RuntimeError(f"network: {error}")


def karuda_for_rank(rank: int, total: int) -> int:
    """Rank to value on a log scale.

    A linear curve over 30000 characters leaves rank 1000 worth several
    hundred, which makes nothing feel scarce. Taking the log of the rank
    compresses the long tail and keeps the money at the very top.
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


def collect(count: int, delay: float, cast_size: int):
    per_page = 25
    rows, seen = [], set()
    page = 1
    shows = 0

    while len(rows) < count:
        data = request(page, per_page, cast_size)
        for media in data["media"]:
            title = (media.get("title") or {}).get("english") or (
                media.get("title") or {}
            ).get("romaji")
            if not title:
                continue
            shows += 1
            for entry in ((media.get("characters") or {}).get("nodes") or []):
                if entry["id"] in seen:
                    continue  # already filed under a more popular show
                name = (entry.get("name") or {}).get("full")
                image = (entry.get("image") or {}).get("large") or ""
                if not name:
                    continue
                if not image or "default.jpg" in image:
                    seen.add(entry["id"])  # remember, so we do not retry them
                    continue
                seen.add(entry["id"])
                rows.append(
                    {
                        "name": name,
                        "series": title,
                        "image_url": image,
                        "likes": 0,
                        "favourites": entry.get("favourites") or 0,
                        "anilist_id": entry["id"],
                        "source": "AniList",
                    }
                )

        print(f"  page {page:>3}  {shows:>5} shows  {len(rows):>6} characters")
        if not data["pageInfo"]["hasNextPage"]:
            print("  AniList ran out of anime")
            break
        page += 1
        time.sleep(delay)

    # Real popularity order, across everything collected.
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
    return unique[:count]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=30000)
    parser.add_argument("--delay", type=float, default=1.3)
    parser.add_argument("--cast", type=int, default=25,
                        help="how many characters to take from each show")
    parser.add_argument("--out", default=DATA)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    print(f"Collecting up to {args.count} characters, popular shows first\n")
    rows = collect(args.count, args.delay, args.cast)
    total = len(rows)

    for position, row in enumerate(rows, 1):
        row["like_rank"] = position
        row["claim_rank"] = claim_rank_for(position, row["name"], total)
        row["base_karuda"] = karuda_for_rank(
            max(1, (row["like_rank"] + row["claim_rank"]) // 2), total
        )

    # One compact record per line: a third the size of indented JSON, and it
    # still diffs line by line when the roster changes.
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("[\n")
        handle.write(
            ",\n".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                for row in rows
            )
        )
        handle.write("\n]\n")

    series = len({r["series"] for r in rows})
    with_art = sum(1 for r in rows if r["image_url"])
    over_300 = sum(1 for r in rows if r["base_karuda"] > 300)
    print(f"\nWrote {total} characters from {series} series to {args.out}")
    print(f"  with art: {with_art}   without: {total - with_art}")
    print(f"  worth over 300: {over_300}  ({100 * over_300 / total:.1f}% of the pool)")
    print("\n  rank     value  character")
    for rank in (1, 10, 100, 300, 1000, 5000, 15000, total):
        if rank <= total:
            row = rows[rank - 1]
            print(f"  {rank:>6}  {row['base_karuda']:>6}  "
                  f"{row['name']} ({row['series']})"[:70])


if __name__ == "__main__":
    main()
