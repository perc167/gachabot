"""Fills in each character's gender, so $w and $h can mean what they say.

    python tools/fetch_gender.py

Mudae's whole roll vocabulary rests on it: $w rolls a waifu, $h a husbando,
$m either. Without gender those are three names for the same command, which
is what they were here - the help page claimed "$h roll a guy" and rolled
anybody.

AniList carries it, fifty characters per request via id_in, so the whole
roster costs about two thousand requests. Paced to the same 30/minute limit
as the roster fetch and checkpointed the same way, because an hour is too
long to lose to one bad response.

Characters with no gender on AniList - and everyone not from AniList - are
left blank and roll under $m only.
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

API = "https://graphql.anilist.co"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")

QUERY = """
query ($ids: [Int]) {
  Page(page: 1, perPage: 50) {
    characters(id_in: $ids) { id gender }
  }
}
"""

BATCH = 50


def post(ids, delay: float, attempt: int = 0):
    body = json.dumps({"query": QUERY, "variables": {"ids": ids}}).encode()
    request = urllib.request.Request(API, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "gachabot-gender/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return (payload.get("data") or {}).get("Page", {}).get("characters") or []
    except urllib.error.HTTPError as error:
        if error.code in (429, 500, 502, 503, 504) and attempt < 6:
            pause = int(error.headers.get("Retry-After") or 0) or (5 * (attempt + 1))
            print(f"    rate limited, waiting {pause}s", flush=True)
            time.sleep(pause)
            return post(ids, delay, attempt + 1)
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        if attempt < 5:
            time.sleep(3 * (attempt + 1))
            return post(ids, delay, attempt + 1)
        raise RuntimeError(f"network: {error}")


def write(rows, path):
    tmp = path + ".writing"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("[\n")
        handle.write(",\n".join(
            json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in rows))
        handle.write("\n]\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delay", type=float, default=2.1)
    parser.add_argument("--data", default=DATA)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    sys.path.insert(0, ROOT)
    import utils  # noqa: E402

    rows = list(utils.iter_roster(args.data))
    by_id = {r["anilist_id"]: r for r in rows
             if r.get("anilist_id") and not r.get("gender")}
    ids = sorted(by_id)
    print(f"{len(rows):,} characters, {len(ids):,} need a gender\n", flush=True)
    if not ids:
        return 0

    started, done, found = time.time(), 0, 0
    last = 0.0
    try:
        for start in range(0, len(ids), BATCH):
            chunk = ids[start:start + BATCH]
            wait = args.delay - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.time()
            for entry in post(chunk, args.delay):
                row = by_id.get(entry["id"])
                if row is None:
                    continue
                # "Non-binary" and the rest are kept verbatim; only Male and
                # Female steer $w and $h, and everything else rolls under $m.
                row["gender"] = entry.get("gender") or ""
                if row["gender"]:
                    found += 1
            done += len(chunk)
            if (start // BATCH) % 20 == 0:
                rate = done / max(1e-9, time.time() - started) * 60
                left = (len(ids) - done) / max(1e-9, rate)
                print(f"  {done:>7,}/{len(ids):,}  {found:>7,} with a gender"
                      f"  ~{left:.0f} min left", flush=True)
            if (start // BATCH) % 200 == 0 and start:
                write(rows, args.data)
                print("    checkpoint saved", flush=True)
    except KeyboardInterrupt:
        print("\n  stopped early - writing what we have", flush=True)
    except Exception as error:  # noqa: BLE001 - partial beats nothing
        print(f"\n  failed ({error!r}) - writing what we have", flush=True)

    write(rows, args.data)
    counts = {}
    for row in rows:
        counts[row.get("gender") or "(unknown)"] = \
            counts.get(row.get("gender") or "(unknown)", 0) + 1
    print(f"\nWrote {len(rows):,} characters in"
          f" {(time.time() - started) / 60:.0f} minutes")
    for gender, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {count:>7,}  {gender}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
