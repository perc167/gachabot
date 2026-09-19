"""Builds data/characters.json from AniList's most-favourited characters.

    python tools/fetch_roster.py --count 5000

The hand-written roster in build_roster.py could not scale: past a few hundred
characters I would be inventing casts from memory, and one invented character
already made it in. This takes the names, series, portraits and popularity
from AniList instead, so every entry is real and the ranks are actual data
rather than my guess at who is famous.

Ranks come straight from the favourites ordering: rank 1 is the single most
favourited character on the site. Value is derived from rank on a
front-loaded curve, so the top of the list is worth far more than the middle.

Characters from adult-only media are skipped, as are ones AniList has no
portrait for.

Only stdlib. Polite by default: about 45 requests a minute against AniList's
90/min limit, with backoff when asked to wait.
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
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    characters(sort: FAVOURITES_DESC) {
      id
      name { full }
      favourites
      image { large }
      media(sort: POPULARITY_DESC, perPage: 1) {
        nodes { title { romaji english } isAdult }
      }
    }
  }
}
"""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")

KARUDA_MIN, KARUDA_MAX = 20, 1300
KARUDA_CURVE = 3.5


def request(page: int, per_page: int, attempt: int = 0):
    body = json.dumps(
        {"query": QUERY, "variables": {"page": page, "perPage": per_page}}
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
        with urllib.request.urlopen(req, timeout=40) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if "errors" in payload and not payload.get("data"):
            raise RuntimeError(payload["errors"])
        return payload["data"]["Page"]
    except urllib.error.HTTPError as error:
        if error.code in (429, 500, 502, 503, 504) and attempt < 5:
            wait = int(error.headers.get("Retry-After") or 0) or (5 * (attempt + 1))
            print(f"    rate limited, waiting {wait}s")
            time.sleep(wait)
            return request(page, per_page, attempt + 1)
        raise
    except (urllib.error.URLError, TimeoutError) as error:
        if attempt < 4:
            time.sleep(3 * (attempt + 1))
            return request(page, per_page, attempt + 1)
        raise RuntimeError(f"network: {error}")


def karuda_for_rank(rank: int, total: int) -> int:
    share = 1 - (rank - 1) / max(1, total - 1)
    return round(KARUDA_MIN + (KARUDA_MAX - KARUDA_MIN) * share**KARUDA_CURVE)


def claim_rank_for(like_rank: int, name: str, total: int) -> int:
    """Claim rank sits near like rank but not on top of it: some characters
    are admired and rarely claimed, some the reverse. Derived from the name so
    it is stable between runs rather than reshuffling every time."""
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    offset = (digest[0] / 255 - 0.5) * 0.30  # +/- 15%
    return max(1, min(total, round(like_rank * (1 + offset))))


def collect(count: int, delay: float):
    per_page = 50
    wanted_pages = -(-count // per_page)
    rows, seen = [], set()

    for page in range(1, wanted_pages + 1):
        data = request(page, per_page)
        for entry in data["characters"]:
            nodes = (entry.get("media") or {}).get("nodes") or []
            if not nodes:
                continue
            media = nodes[0]
            if media.get("isAdult"):
                continue  # keep the pool safe for a general server
            title = (media.get("title") or {}).get("english") or (
                media.get("title") or {}
            ).get("romaji")
            name = (entry.get("name") or {}).get("full")
            image = (entry.get("image") or {}).get("large") or ""
            if not (name and title):
                continue
            if "default.jpg" in image:
                image = ""  # AniList's grey placeholder is worse than nothing
            key = (name, title)
            if key in seen:
                continue
            seen.add(key)
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

        print(f"  page {page:>3}/{wanted_pages}  kept {len(rows):>5}")
        if not data["pageInfo"]["hasNextPage"]:
            print("  AniList ran out of characters")
            break
        if len(rows) >= count:
            break
        time.sleep(delay)

    return rows[:count]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--delay", type=float, default=1.3)
    parser.add_argument("--out", default=DATA)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    print(f"Fetching the top {args.count} characters by favourites\n")
    rows = collect(args.count, args.delay)
    total = len(rows)

    for position, row in enumerate(rows, 1):
        row["like_rank"] = position
        row["claim_rank"] = claim_rank_for(position, row["name"], total)
        row["base_karuda"] = karuda_for_rank(
            (row["like_rank"] + row["claim_rank"]) // 2, total
        )
        row.pop("favourites", None)

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    series = len({r["series"] for r in rows})
    with_art = sum(1 for r in rows if r["image_url"])
    print(f"\nWrote {total} characters from {series} series to {args.out}")
    print(f"  with art: {with_art}   without: {total - with_art}")
    print(f"  karuda: {rows[-1]['base_karuda']} to {rows[0]['base_karuda']}")
    print("\nTop of the list:")
    for row in rows[:5]:
        print(f"  #{row['like_rank']:<5} {row['base_karuda']:>5} kk"
              f"  {row['name']} ({row['series']})")


if __name__ == "__main__":
    main()
