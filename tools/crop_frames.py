"""Crops the episode frames to the shape of a character card.

    python tools/crop_frames.py

An episode frame is 1920x1080. A card is tall, so a frame sits in it as a
letterboxed strip a third of the height, while the roster's own art fills it.
This cuts each frame to 3:4 around whatever is worth looking at and stores it
with the bot.

The crop itself is done by images.weserv.nl, whose "attention" mode is
libvips' - it keeps the faces and drops the empty corridor beside them. It is
used once here, to produce the files; the bot never calls it, so the pictures
do not stop working if that service does.

Kept with the bot rather than linked, for the same reason the secret
characters' art is: a link is a thing that can rot, and thirty megabytes is
cheaper than a broken album.
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = os.path.join(ROOT, "data", "character_frames.json")
SOURCES = os.path.join(ROOT, "data", "frame_sources.json")
ART_DIR = os.path.join(ROOT, "assets", "characters")

PROXY = "https://images.weserv.nl/"
UA = {"User-Agent": "gachabot-frames/1.0 (character art for a Discord bot)"}

# 3:4, which is what the roster's own portraits are, at a size Discord will
# not have to scale up.
WIDTH, HEIGHT = 640, 854
QUALITY = 82
DELAY = 0.25

# Cuts are tried in order and the first that still shows the character alone
# is kept. Entropy leads because it wins: of 109 frames whose attention crop
# had lost the character, entropy recovered 56 and attention 7. The busiest
# part of an animation cel is the character; the most salient part is often
# a light source or a bright sky.
CUTS = (
    ("entropy", WIDTH, HEIGHT, "&a=entropy"),
    ("attention", WIDTH, HEIGHT, "&a=attention"),
    ("centre", WIDTH, HEIGHT, ""),
    ("wide", 680, 850, "&a=entropy"),
)


def cropped_url(source: str, width: int = WIDTH, height: int = HEIGHT,
                extra: str = "&a=entropy") -> str:
    return (PROXY + "?url=" + urllib.parse.quote(source, safe="")
            + f"&w={width}&h={height}&fit=cover&q={QUALITY}" + extra)


def local_name(source: str) -> str:
    return "frame-" + hashlib.sha1(source.encode("utf-8")).hexdigest()[:16] + ".jpg"


def fetch(url: str, tries: int = 3):
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == tries - 1:
                return b""
            time.sleep(2 * (attempt + 1))
        finally:
            time.sleep(DELAY)
    return b""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", default=FRAMES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    with io.open(args.frames, encoding="utf-8") as handle:
        frames = json.load(handle)
    sources = {}
    if os.path.exists(SOURCES):
        with io.open(SOURCES, encoding="utf-8") as handle:
            sources = json.load(handle)
    os.makedirs(ART_DIR, exist_ok=True)

    todo = sorted({url for urls in frames.values() for url in urls
                   if url.startswith("http")})
    print(f"{len(todo):,} frames to crop")
    if args.dry_run:
        return 0

    from PIL import Image

    sys.path.insert(0, os.path.join(ROOT, "tools"))
    sys.path.insert(0, ROOT)
    import fetch_episode_frames as frames_tool

    tags = {}
    tag_path = os.path.join(ROOT, "data", "character_art_tags.json")
    if os.path.exists(tag_path):
        with io.open(tag_path, encoding="utf-8") as handle:
            tags = json.load(handle)
    owner = {url: key for key, urls in frames.items() for url in urls}
    tagger = frames_tool.Tagger()

    done, failed, bytes_written = 0, 0, 0
    by_cut = {}
    for number, source in enumerate(todo, 1):
        name = local_name(source)
        path = os.path.join(ART_DIR, name)
        if not os.path.exists(path):
            tag = tags.get(owner.get(source, ""), "")
            won = None
            for label, width, height, extra in CUTS:
                data = fetch(cropped_url(source, width, height, extra))
                try:
                    image = Image.open(io.BytesIO(data))
                    image.load()
                except Exception:  # noqa: BLE001 - try the next cut
                    continue
                # A crop that cut the character out, or left somebody else
                # in, is not worth keeping - and finding that out now saves
                # an audit pass later.
                if tag and not tagger.alone(image, tag):
                    continue
                won = (label, data)
                break
            if not won:
                failed += 1
                continue
            label, data = won
            by_cut[label] = by_cut.get(label, 0) + 1
            with open(path, "wb") as handle:
                handle.write(data)
        sources[name] = source
        bytes_written += os.path.getsize(path)
        done += 1
        if number % 50 == 0 or number == len(todo):
            print(f"  {number:,}/{len(todo):,} · {done:,} cropped ·"
                  f" {failed:,} failed · {bytes_written / 1e6:.0f} MB",
                  flush=True)

    # The album now points at the bot's own files; the originals stay
    # recorded, so a better crop later does not need the whole sweep again.
    swapped = {}
    for key, urls in frames.items():
        kept = []
        for url in urls:
            name = local_name(url) if url.startswith("http") else url
            if url.startswith("http") and not os.path.exists(
                    os.path.join(ART_DIR, name)):
                continue
            kept.append("local:" + name if url.startswith("http") else url)
        if kept:
            swapped[key] = kept

    with io.open(args.frames, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(swapped, handle, ensure_ascii=False)
    with io.open(SOURCES, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(sources, handle, ensure_ascii=False, indent=0)

    print(f"\n{done:,} frames cropped to {WIDTH}x{HEIGHT},"
          f" {bytes_written / 1e6:.0f} MB in assets/characters/")
    if by_cut:
        print("cuts that worked: "
              + ", ".join(f"{label} {count}" for label, count in by_cut.items()))
    if failed:
        print(f"{failed:,} had no cut that keeps the character alone")
    print("Now run: python tools/merge_art.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
