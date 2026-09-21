"""Recomputes every rank and value in the roster.

    python tools/rebalance.py --dry-run
    python tools/rebalance.py

Run this after changing config.FEMALE_CLAIM_WEIGHT, or after any change to
the value curve. It touches no names, no art and no series - only like_rank,
claim_rank and base_karuda - so nobody loses a character they claimed:
$import matches on name and series, never on rank.

There are two rankings and they answer different questions. like_rank is raw
AniList favourites, which is honest and skews male. claim_rank is how much
people want to own somebody, which is what a gacha is about and what a
character is worth.
"""
import argparse
import collections
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")


def write(rows, path):
    tmp = path + ".writing"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("[\n")
        handle.write(",\n".join(
            json.dumps(r, ensure_ascii=False, separators=(",", ":"))
            for r in rows))
        handle.write("\n]\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data", default=DATA)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    sys.path.insert(0, ROOT)
    import config  # noqa: E402
    import utils  # noqa: E402

    rows = list(utils.iter_roster(args.data))
    before = {(r["name"], r["series"]): r["base_karuda"] for r in rows}
    print(f"{len(rows):,} characters")
    print(f"female claim weight: x{config.FEMALE_CLAIM_WEIGHT}\n")

    utils.rerank_roster(rows)
    by_claim = sorted(rows, key=lambda r: r["claim_rank"])

    print("most valuable now:")
    for row in by_claim[:12]:
        print(f"  {row['claim_rank']:>3}. {row['base_karuda']:>5}k "
              f"{row.get('gender') or '-':<7} {row['name']} — {row['series']}"[:78])

    for size in (10, 50, 300, 1000):
        counts = collections.Counter(
            (r.get("gender") or "unknown") for r in by_claim[:size])
        print(f"\n  top {size:>4}: {counts.get('Female', 0)} female,"
              f" {counts.get('Male', 0)} male,"
              f" {counts.get('unknown', 0)} unrecorded")

    moved = sum(1 for r in rows
                if before.get((r["name"], r["series"])) != r["base_karuda"])
    over = sum(1 for r in rows if r["base_karuda"] > 300)
    print(f"\n  {moved:,} values changed · {over} characters over 300 karuda")

    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0
    write(rows, args.data)
    print(f"\nWrote {args.data}")
    print("  $import again to pick it up; claims are matched on name and"
          " series, so nobody loses anybody.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
