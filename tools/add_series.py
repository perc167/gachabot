"""Adds one series to data/characters.json, however niche it is.

    python tools/add_series.py "MILGRAM"
    python tools/add_series.py "MILGRAM" --dry-run

fetch_roster.py walks anime by popularity and stops once it has enough
characters, so anything below that line never appears - MILGRAM sits at
popularity 6,870 against a cutoff around 2,200 shows. This fetches a named
series directly and merges its cast in.

Everyone in the pool carries their AniList favourites count, so a new arrival
can be ranked against the people already there rather than guessed at: the
whole roster is re-sorted by favourites afterwards and ranks and values are
recomputed. Existing claims are unaffected because $import matches on name
and series, not on rank.
"""
import argparse
import hashlib
import io
import json
import math
import os
import sys
import urllib.error
import urllib.request

API = "https://graphql.anilist.co"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")

KARUDA_MIN, KARUDA_MAX = 20, 1300
PREMIUM_RANK, PREMIUM_VALUE = 300, 300

QUERY = """
query ($search: String, $castSize: Int) {
  Page(page: 1, perPage: 8) {
    media(search: $search, sort: POPULARITY_DESC) {
      type format isAdult popularity
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


def request(search: str, cast_size: int):
    body = json.dumps(
        {"query": QUERY, "variables": {"search": search, "castSize": cast_size}}
    ).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "gachabot-add-series/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=40) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if "errors" in payload and not payload.get("data"):
        raise RuntimeError(payload["errors"])
    return payload["data"]["Page"]["media"]


def karuda_for_rank(rank: int, total: int) -> int:
    if total <= 1:
        return KARUDA_MAX
    t = math.log(rank) / math.log(total)
    pin = math.log(PREMIUM_RANK) / math.log(total)
    share = (PREMIUM_VALUE - KARUDA_MIN) / (KARUDA_MAX - KARUDA_MIN)
    exponent = math.log(share) / math.log(1 - pin) if 0 < pin < 1 else 2.0
    return max(
        KARUDA_MIN,
        round(KARUDA_MIN + (KARUDA_MAX - KARUDA_MIN) * (1 - t) ** exponent),
    )


def claim_rank_for(like_rank: int, name: str, total: int) -> int:
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    offset = (digest[0] / 255 - 0.5) * 0.30
    return max(1, min(total, round(like_rank * (1 + offset))))


def rerank(rows):
    """Sort the whole pool and recompute ranks and values.

    Delegates to utils so this tool, the bulk fetcher and the bot can never
    disagree about what a character is worth.
    """
    sys.path.insert(0, ROOT)
    import utils

    return utils.rerank_roster(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("search", help="series name to look up on AniList")
    parser.add_argument("--cast", type=int, default=30,
                        help="how many characters to take (default 30)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-adult", action="store_true")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    media = request(args.search, args.cast)
    if not media:
        print(f"AniList has nothing called {args.search!r}.")
        return 1

    # Several entries often share a cast - MILGRAM has one per trial. Take the
    # most popular and use its title, so the series reads as one thing.
    best = None
    for entry in media:
        if entry.get("isAdult") and not args.allow_adult:
            continue
        cast = (entry.get("characters") or {}).get("nodes") or []
        if not cast:
            continue
        if best is None or (entry.get("popularity") or 0) > (best.get("popularity") or 0):
            best = entry
    if best is None:
        print("Found the series but it has no characters listed.")
        return 1

    title = (best["title"].get("english") or best["title"].get("romaji"))
    cast = (best.get("characters") or {}).get("nodes") or []
    print(f"{title}  [{best['type']}/{best['format']}]  "
          f"popularity {best['popularity']}  {len(cast)} characters\n")

    with io.open(DATA, encoding="utf-8") as handle:
        rows = json.load(handle)
    existing = {(r["name"], r["series"]) for r in rows}
    if any(r.get("favourites") is None for r in rows):
        print("The roster has no favourites counts yet - re-run"
              " tools/fetch_roster.py first, or new entries cannot be ranked.")
        return 1

    added, skipped = [], []
    for entry in cast:
        name = (entry.get("name") or {}).get("full")
        image = (entry.get("image") or {}).get("large") or ""
        if not name:
            continue
        if not image or "default.jpg" in image:
            skipped.append(f"{name} (no portrait)")
            continue
        if (name, title) in existing:
            skipped.append(f"{name} (already in)")
            continue
        added.append({
            "name": name,
            "series": title,
            "image_url": image,
            "likes": 0,
            "favourites": entry.get("favourites") or 0,
            "anilist_id": entry["id"],
            "source": "AniList",
        })

    for row in added:
        print(f"  + {row['name']:<24} {row['favourites']:>5} favourites")
    for note in skipped:
        print(f"  - {note}")
    if not added:
        print("\nNothing new to add.")
        return 0

    rows.extend(added)
    rerank(rows)
    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0

    with io.open(DATA, "w", encoding="utf-8") as handle:
        handle.write("[\n")
        handle.write(
            ",\n".join(
                json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                for row in rows
            )
        )
        handle.write("\n]\n")

    placed = {r["name"]: r for r in rows if r["series"] == title}
    print(f"\nAdded {len(added)}; the pool is now {len(rows)}.")
    print("Where they landed:")
    for row in sorted(placed.values(), key=lambda r: r["like_rank"])[:10]:
        print(f"  #{row['like_rank']:>6}  {row['base_karuda']:>5} karuda"
              f"  {row['name']}")
    print("\nRun $import in Discord to load them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
