"""Adds an original character to the website's Secret category.

    python tools/add_secret.py "asparagus ᧔࿔᧓" "C:/path/to/folder"
    python tools/add_secret.py "Name" folder --first cover.png --last sketch.png
    python tools/add_secret.py "Name" folder --roll --value 2000 --odds 20000

With --roll the character also joins the gacha: worth --value karuda, and
turning up once in --odds rolls, outside the ordinary pool entirely. Their
images are copied into assets/characters/ so the bot carries them itself
rather than depending on the website staying where it is.

Every image in the folder becomes part of that character's album, shrunk to a
sensible size and saved under site/secret/<slug>/, and the character is
recorded in data/secret_characters.json. Rebuild the site afterwards:

    python tools/build_site.py

Running it again with the same name replaces that character, so a friend who
sends more art is a re-run, not a cleanup.

Originals are never touched. Artists' files are often huge - a 4000x5000 PNG
is five megabytes - and a page of them would take a phone a minute to load,
so what ships is a copy at most LONG_SIDE pixels on its long edge.
"""
import argparse
import hashlib
import io
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "secret_characters.json")
SITE = os.path.join(ROOT, "site", "secret")
# The bot's bundled-art folder; utils.local_art_path only reads from here.
BOT_ART = os.path.join(ROOT, "assets", "characters")

IMAGE_TYPES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
LONG_SIDE = 1400
QUALITY = 86


def slug_for(name: str) -> str:
    """A folder name from the character's name.

    OC names are often decorated - asparagus ᧔࿔᧓ - and the decoration is not
    something a URL should carry, so the slug keeps the plain letters and,
    when there are none at all, falls back to a short hash of the name.
    """
    plain = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return plain or "oc-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def ordered(files, first, last):
    """The album order: the chosen cover(s), everything else, then the tail."""
    first = [f for f in first if f in files]
    last = [f for f in last if f in files and f not in first]
    middle = [f for f in sorted(files) if f not in first and f not in last]
    return first + middle + last


def shrink(source: str, target: str):
    """Save a web-sized JPEG copy of one image."""
    from PIL import Image

    image = Image.open(source)
    image.load()
    # Transparent PNGs go onto white: JPEG has no alpha, and a transparent
    # background saved without one turns black.
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        ground = Image.new("RGB", image.size, (255, 255, 255))
        ground.paste(image, mask=image.split()[-1])
        image = ground
    elif image.mode != "RGB":
        image = image.convert("RGB")
    image.thumbnail((LONG_SIDE, LONG_SIDE), Image.LANCZOS)
    image.save(target, format="JPEG", quality=QUALITY, optimize=True,
               progressive=True)
    return image.size


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("name", help="the character's name, exactly as shown")
    parser.add_argument("folder", help="folder holding their images")
    parser.add_argument("--first", nargs="*", default=[],
                        help="file names to put first; the first is the cover")
    parser.add_argument("--last", nargs="*", default=[],
                        help="file names to put last, such as rough sketches")
    parser.add_argument("--only", nargs="*", default=[],
                        help="use exactly these files, in this order, and"
                             " leave the rest of the folder out")
    parser.add_argument("--by", default="",
                        help="who made them, shown under the name")
    parser.add_argument("--roll", action="store_true",
                        help="also make them rollable in the bot")
    parser.add_argument("--value", type=int, default=2000,
                        help="karuda they are worth, with --roll")
    parser.add_argument("--odds", type=int, default=20000,
                        help="one roll in this many finds them, with --roll")
    parser.add_argument("--gender", default="", choices=["", "Female", "Male"],
                        help="blank answers to every roll command")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if not os.path.isdir(args.folder):
        print(f"no folder at {args.folder}")
        return 1
    files = [f for f in os.listdir(args.folder)
             if f.lower().endswith(IMAGE_TYPES)]
    if not files:
        print(f"no images in {args.folder}")
        return 1
    if args.only:
        missing = [f for f in args.only if f not in files]
        if missing:
            print("not in the folder: " + ", ".join(missing))
            return 1

    slug = slug_for(args.name)
    out_dir = os.path.join(SITE, slug)
    # A re-run replaces the album rather than adding to it, so an image the
    # friend asked to take down actually comes down.
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir)

    # The bot's copies go too, so a re-run leaves no stale image behind.
    os.makedirs(BOT_ART, exist_ok=True)
    stem = f"secret-{slug}-"
    for old_file in os.listdir(BOT_ART):
        if old_file.startswith(stem):
            os.remove(os.path.join(BOT_ART, old_file))

    images, bot_images = [], []
    # --only is a curated album: the artist's folder can hold drafts and
    # rejects without them ever reaching the site or the bot.
    chosen = args.only or ordered(files, args.first, args.last)
    for number, name in enumerate(chosen, 1):
        target = os.path.join(out_dir, f"{number:02d}.jpg")
        width, height = shrink(os.path.join(args.folder, name), target)
        images.append(f"secret/{slug}/{number:02d}.jpg")
        if args.roll:
            bundled = f"{stem}{number:02d}.jpg"
            shutil.copyfile(target, os.path.join(BOT_ART, bundled))
            bot_images.append("local:" + bundled)
        print(f"  {number:02d}. {name}  ->  {width}x{height},"
              f" {os.path.getsize(target) // 1024} KB")

    roster = []
    if os.path.exists(DATA):
        with io.open(DATA, encoding="utf-8") as handle:
            roster = json.load(handle).get("characters", [])
    roster = [c for c in roster if c.get("slug") != slug]
    entry = {
        "name": args.name,
        "slug": slug,
        "by": args.by,
        "images": images,
        "added": int(time.time()),
        "rollable": bool(args.roll),
    }
    if args.roll:
        entry.update({
            "value": args.value,
            "odds": max(1, args.odds),
            "gender": args.gender,
            "bot_images": bot_images,
        })
    roster.append(entry)

    with io.open(DATA, "w", encoding="utf-8", newline="\n") as handle:
        json.dump({"characters": roster}, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    total = sum(os.path.getsize(os.path.join(out_dir, f))
                for f in os.listdir(out_dir))
    print(f"\n{args.name}: {len(images)} images, {total / 1024:.0f} KB,"
          f" in site/secret/{slug}/")
    if args.roll:
        print(f"Rollable: worth {args.value:,} karuda, 1 in {args.odds:,}"
              " rolls. The bot picks this up on its next boot.")
    print(f"{len(roster)} secret character(s) in total."
          " Now run: python tools/build_site.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
