"""Puts the episode frames in front of the official art, into one file.

    python tools/merge_art.py

The bot reads one art file, data/character_art.json. This builds it from two:
the frames tagged out of the episodes themselves, which go first because they
are what was actually asked for, and the official art behind them, which is
all that exists for most of the roster.

Nobody loses an album. A character with frames gets their frames and then
their art; a character with neither keeps the single picture the roster
carries for them, which lives elsewhere and is not touched here.
"""
import argparse
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "character_art.json")
FRAMES = os.path.join(ROOT, "data", "character_frames.json")
# Which full-size frame each cropped file was cut from, written by
# tools/crop_frames.py.
SOURCES = os.path.join(ROOT, "data", "frame_sources.json")

# What an album holds at most. Past this it is a chore to flip through.
LIMIT = 8


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--art", default=ART)
    parser.add_argument("--frames", default=FRAMES)
    parser.add_argument("--out", default=ART)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    art = load(args.art)
    frames = load(args.frames)
    # A cropped frame and the 1920x1080 it came from are the same picture, so
    # an album that carries both shows it twice - which is exactly what
    # happened the first time these were merged.
    sources = set(load(SOURCES).values())

    merged = dict(art)
    gained = replaced = superseded = 0
    for key, shots in frames.items():
        if not shots:
            continue
        existing = []
        for url in merged.get(key, []):
            if url in shots:
                continue
            if url in sources:
                superseded += 1
                continue
            existing.append(url)
        if key not in merged or not merged[key]:
            gained += 1
        else:
            replaced += 1
        merged[key] = (list(shots) + existing)[:LIMIT]

    # Anywhere else in the file that still points at a frame we have cropped.
    for key, urls in merged.items():
        if key in frames:
            continue
        kept = [url for url in urls if url not in sources]
        if len(kept) != len(urls):
            superseded += len(urls) - len(kept)
            merged[key] = kept

    total = sum(len(v) for v in merged.values())
    with_album = sum(1 for v in merged.values() if v)
    print(f"{len(frames):,} characters have frames:"
          f" {gained:,} had nothing before, {replaced:,} now lead with them")
    if superseded:
        print(f"dropped {superseded:,} uncropped copies of frames already"
              f" in the album")
    print(f"the art file holds {with_album:,} characters and {total:,} images")

    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0

    with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(merged, handle, ensure_ascii=False)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
