"""How old each character is, as far as AniList will say.

    python tools/fetch_ages.py

Somebody asked for a pool of characters who are all legally adults. That
needs an age per character, which the roster has never carried, so this
fetches it.

Two things it is important to be honest about, both measured rather than
assumed:

  Most characters have no age at all. On a sample of fifty, seven did. A
  switch built on this cannot mean "everybody in the pool is an adult" - it
  can only mean "everybody in the pool is confirmed to be an adult", which
  is a much smaller pool and a different promise.

  The field is free text, written by whoever edited the entry: "17", "14
  (I), 17 (II)", "Over 1000", "Unknown". So it is read conservatively - the
  lowest number anywhere in the string wins, because a character who is 14
  in one season and 17 in another is a child in that show, and anything
  with no number in it is unknown rather than old.

Written to data/character_ages.json as {anilist id: age}, ids only, so it
survives the roster being rebuilt.
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER = os.path.join(ROOT, "data", "characters.json")
OUT = os.path.join(ROOT, "data", "character_ages.json")

API = "https://graphql.anilist.co"
QUERY = """query($ids:[Int]){ Page(page:1,perPage:50){
  characters(id_in:$ids){ id age } } }"""
PER_CALL = 50
REST = 1.4               # AniList asks for 90 a minute; this sits under it

sys.path.insert(0, ROOT)
from utils import youngest_age as youngest  # noqa: E402


def _unused_youngest(age: str):
    """The lowest age a string mentions, or None if it names none.

    Conservative on purpose. "14 (I), 17 (II)" is a character who is
    fourteen for part of their story, and a pool that promises adults
    should not contain them. "Over 1000" gives 1000, which is fine. A
    string with no digits at all - "Unknown", "?" - is not an age.
    """
    found = [int(n) for n in NUMBER.findall(age or "")]
    if not found:
        return None
    # A stray year - "born 1998" - is not an age, and falling back to it
    # would hand a pool that promises adults a character whose age nobody
    # actually recorded. Unknown is the safe answer, because unknown is
    # what gets excluded.
    sensible = [n for n in found if n <= 500]
    return min(sensible) if sensible else None


def ask(ids, tries: int = 3):
    body = json.dumps({"query": QUERY, "variables": {"ids": list(ids)}})
    for attempt in range(tries):
        request = urllib.request.Request(
            API, data=body.encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "User-Agent": "PaperBot/1.0 (character ages)"})
        try:
            with urllib.request.urlopen(request, timeout=40) as response:
                data = json.load(response)
            return (data.get("data") or {}).get("Page", {}).get(
                "characters") or []
        except urllib.error.HTTPError as error:
            # 429 is the rate limit; it says how long to wait.
            wait = int(error.headers.get("Retry-After") or 0) or 20 * (attempt + 1)
            if error.code not in (429, 500, 502, 503, 504):
                return []
            print(f"    rate limited, waiting {wait}s", flush=True)
            time.sleep(wait)
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(5 * (attempt + 1))
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0,
                        help="only the first N characters, for a trial")
    args = parser.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    roster = json.load(io.open(ROSTER, encoding="utf-8"))
    ids = []
    for row in roster:
        anilist_id = row.get("anilist_id")
        if anilist_id:
            ids.append(int(anilist_id))
    ids = sorted(set(ids))
    if args.limit:
        ids = ids[:args.limit]

    ages = {}
    if os.path.exists(OUT):
        ages = json.load(io.open(OUT, encoding="utf-8"))
        print(f"carrying on from {len(ages):,} already asked about")
    todo = [i for i in ids if str(i) not in ages]
    print(f"{len(todo):,} characters to ask about,"
          f" {len(todo) // PER_CALL + 1:,} calls, about"
          f" {len(todo) / PER_CALL * REST / 60:.0f} minutes")

    asked = 0
    for start in range(0, len(todo), PER_CALL):
        batch = todo[start:start + PER_CALL]
        for entry in ask(batch):
            ages[str(entry["id"])] = entry.get("age") or ""
        # Anybody the API did not answer for is recorded as unknown, so the
        # next run does not ask again and again about the same gaps.
        for one in batch:
            ages.setdefault(str(one), "")
        asked += len(batch)
        if (start // PER_CALL) % 20 == 0 or start + PER_CALL >= len(todo):
            known = sum(1 for v in ages.values() if youngest(v) is not None)
            print(f"  {asked:,}/{len(todo):,} · {known:,} with an age",
                  flush=True)
            with io.open(OUT, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(ages, handle, ensure_ascii=False)
        time.sleep(REST)

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(ages, handle, ensure_ascii=False)

    known = [youngest(v) for v in ages.values()]
    known = [a for a in known if a is not None]
    adults = sum(1 for a in known if a >= 18)
    print(f"\n{len(ages):,} asked about")
    print(f"  {len(known):,} have an age ({len(known)/max(len(ages),1):.0%})")
    print(f"  {adults:,} are 18 or over")
    print(f"  {len(known) - adults:,} are under 18")
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
