"""Re-cuts the frames whose crop lost the character, trying other crops.

    python tools/recrop_frames.py

A frame that passed the strict checks at 1920x1080 can fail them at 3:4,
because the crop keeps what is visually interesting and that is not always
the person: Makima ended up as sky with a shoulder in it. tools/audit_albums
drops those, which threw away 102 good frames for a bad cut.

So each one is cut again, several ways, and the first cut that still shows
them alone is kept:

    attention  the default, libvips' idea of the interesting part
    entropy    the busiest part, which is usually the character
    centre     dead centre, which is where a director usually puts them
    4:5        a squarer window, keeping more of the frame

Anything that fails all four really has no crop that works, and stays out.
"""
import argparse
import io
import json
import os
import sys
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = os.path.join(ROOT, "data", "character_frames.json")
SOURCES = os.path.join(ROOT, "data", "frame_sources.json")
TAGS = os.path.join(ROOT, "data", "character_art_tags.json")
ART_DIR = os.path.join(ROOT, "assets", "characters")

sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

PROXY = "https://images.weserv.nl/"
QUALITY = 82

# Tried in order, and the first that keeps the character wins.
CUTS = (
    ("attention", 640, 854, "&a=attention"),
    ("entropy", 640, 854, "&a=entropy"),
    ("centre", 640, 854, ""),
    ("wide", 680, 850, "&a=attention"),
)


def load(path: str) -> dict:
    with io.open(path, encoding="utf-8") as handle:
        return json.load(handle)


def cut_url(source: str, width: int, height: int, extra: str) -> str:
    return (PROXY + "?url=" + urllib.parse.quote(source, safe="")
            + f"&w={width}&h={height}&fit=cover&q={QUALITY}" + extra)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    import fetch_episode_frames as frames_tool
    from PIL import Image

    frames = load(FRAMES)
    sources = load(SOURCES)
    tags = load(TAGS)

    # Which crops the audit threw out, and who they belonged to.
    alive = {url for urls in frames.values() for url in urls}
    owner = {}
    for key, urls in load(os.path.join(ROOT, "data", "character_frames.json")).items():
        for url in urls:
            owner[url] = key
    # The frames file no longer names the dropped ones, so their owner comes
    # from the source map plus whoever else shares that source's series.
    dropped = []
    for name, source in sources.items():
        entry = "local:" + name
        if entry in alive:
            continue
        dropped.append((name, source))

    print(f"{len(dropped):,} crops to try again")
    if args.dry_run:
        return 0

    tagger = frames_tool.Tagger()

    # Who each dropped crop was for: the character whose album held it before
    # the audit, read back from the backup the audit wrote over.
    before = {}
    backup = os.path.join(os.environ.get("TEMP", "."), "frames_before_audit.json")
    if os.path.exists(backup):
        for key, urls in load(backup).items():
            for url in urls:
                before[url] = key

    recovered, hopeless = 0, 0
    by_cut = {}
    for number, (name, source) in enumerate(dropped, 1):
        key = before.get("local:" + name)
        tag = tags.get(key or "", "")
        if not tag:
            hopeless += 1
            continue

        won = None
        for label, width, height, extra in CUTS:
            data = frames_tool.fetch(cut_url(source, width, height, extra),
                                     tries=2)
            if not data:
                continue
            try:
                image = Image.open(io.BytesIO(data))
                image.load()
            except Exception:  # noqa: BLE001 - try the next cut
                continue
            if tagger.alone(image, tag):
                won = (label, data)
                break

        if won:
            label, data = won
            with open(os.path.join(ART_DIR, name), "wb") as handle:
                handle.write(data)
            frames.setdefault(key, [])
            if "local:" + name not in frames[key]:
                frames[key].append("local:" + name)
            by_cut[label] = by_cut.get(label, 0) + 1
            recovered += 1
        else:
            hopeless += 1
            path = os.path.join(ART_DIR, name)
            if os.path.exists(path):
                os.remove(path)

        if number % 25 == 0 or number == len(dropped):
            print(f"  {number:,}/{len(dropped):,} · {recovered:,} recovered",
                  flush=True)

    with io.open(FRAMES, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(frames, handle, ensure_ascii=False)

    print(f"\nrecovered {recovered:,} by cutting differently: "
          + ", ".join(f"{label} {count}" for label, count in by_cut.items()))
    print(f"{hopeless:,} have no crop that keeps them alone, and are gone")
    print("Now run: python tools/merge_art.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
