"""Lays out albums side by side, to be looked at rather than counted.

    python tools/album_sheet.py Emilia Rem "Marin Kitagawa"
    python tools/album_sheet.py --frames-only --count 12

A number in a report does not say whether a picture is any good. This draws
one row per character - their name, then every picture in their album in
order - so a sheet can be opened and judged at a glance.

Only the bundled files are drawn. The remote official art is fine and was
never the complaint; the point of the sheet is the episode frames.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(ROOT, "data", "character_art.json")
FRAMES = os.path.join(ROOT, "data", "character_frames.json")
ART_DIR = os.path.join(ROOT, "assets", "characters")

THUMB_W, THUMB_H = 150, 200
LABEL = 230
PAD = 8


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="characters to draw")
    parser.add_argument("--count", type=int, default=10,
                        help="how many characters, when none are named")
    parser.add_argument("--frames-only", action="store_true",
                        help="skip anyone whose album has no episode frames")
    parser.add_argument("--out", default=os.path.join(
        ROOT, "data", "album_sheet.png"))
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    from PIL import Image, ImageDraw, ImageFont

    art = json.load(io.open(ART, encoding="utf-8"))
    frames = json.load(io.open(FRAMES, encoding="utf-8"))

    if args.names:
        wanted = []
        for name in args.names:
            hit = [key for key in art
                   if key.split("\x1f")[0].lower() == name.lower()]
            if hit:
                wanted.append(hit[0])
            else:
                print(f"no album for {name!r}")
    else:
        pool = sorted(frames) if args.frames_only else sorted(art)
        wanted = pool[:args.count]

    rows = []
    for key in wanted:
        local = [url for url in (art.get(key) or []) if url.startswith("local:")]
        if args.frames_only and not any("frame-" in url for url in local):
            continue
        pictures = []
        for url in local:
            path = os.path.join(ART_DIR, url[len("local:"):])
            if not os.path.exists(path):
                continue
            try:
                image = Image.open(path)
                image.load()
            except Exception:  # noqa: BLE001 - a sheet is not worth a crash
                continue
            pictures.append(image.convert("RGB").resize(
                (THUMB_W, THUMB_H), Image.LANCZOS))
        if pictures:
            rows.append((key.split("\x1f")[0], key.split("\x1f")[1], pictures))

    if not rows:
        print("nothing to draw")
        return 1

    widest = max(len(pictures) for _, _, pictures in rows)
    width = LABEL + widest * (THUMB_W + PAD) + PAD
    height = PAD + len(rows) * (THUMB_H + PAD)
    sheet = Image.new("RGB", (width, height), (24, 24, 28))
    draw = ImageDraw.Draw(sheet)
    try:
        name_font = ImageFont.truetype("arialbd.ttf", 17)
        small_font = ImageFont.truetype("arial.ttf", 13)
    except OSError:
        name_font = small_font = ImageFont.load_default()

    for number, (name, series, pictures) in enumerate(rows):
        top = PAD + number * (THUMB_H + PAD)
        draw.text((PAD, top + 4), name, font=name_font, fill=(240, 240, 245))
        draw.text((PAD, top + 26), series[:30], font=small_font,
                  fill=(150, 150, 160))
        draw.text((PAD, top + 46), f"{len(pictures)} pictures",
                  font=small_font, fill=(150, 150, 160))
        for column, picture in enumerate(pictures):
            sheet.paste(picture, (LABEL + column * (THUMB_W + PAD), top))

    sheet.save(args.out, optimize=True)
    print(f"{len(rows)} albums, {sum(len(p) for _, _, p in rows)} pictures"
          f" -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
