"""Draws the badge icons as struck medals with a stone set in them.

    python tools/make_badges.py

Writes 128x128 transparent PNGs to assets/badges/, one per badge in
perks.BADGES, ready to upload to a Discord server as custom emoji. Discord's
limit is 256KB per emoji and these come out far under it.

A medal, not a crystal: the shards are already faceted stones, and two sets of
loose gems in one bot would be indistinguishable at emoji size. So each badge
is a struck disc - a rim, a dished face, and the bot's own portrait pressed
into it - and what separates them is the material. Paper is pale, iron is cold
grey, gold is warm, and the gems carry their own colour.

Everything is drawn at 4x and scaled down, because Pillow's polygon fill has
no antialiasing.

Needs Pillow, which the bot itself does not:  pip install Pillow
"""
import colorsys
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import perks  # noqa: E402

SIZE = 128
SCALE = 4
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "badges"
)

# Base colour per badge. The rim, face and stone are all derived from it, so
# one number per material keeps the set consistent.
COLOURS = {
    "paper": "#E8E2D4",
    "iron": "#8C96A3",
    "gold": "#E8B54A",
    "emerald": "#3FB984",
    "opal": "#8FD5E8",
    "amethyst": "#A46BE0",
    "diamond": "#BFE6F5",
}

# Light comes from up and to the left, as it does on the shards.
LIGHT = (-0.55, -0.7)


def shade(hex_colour: str, lightness: float = 0.0, saturation: float = 0.0):
    """Nudge a colour's lightness and saturation, staying in gamut."""
    raw = hex_colour.lstrip("#")
    red, green, blue = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    light = max(0.0, min(1.0, light + lightness))
    sat = max(0.0, min(1.0, sat + saturation))
    red, green, blue = colorsys.hls_to_rgb(hue, light, sat)
    return tuple(round(channel * 255) for channel in (red, green, blue))


def ring(draw, centre, radius, fill, outline=None, width=0):
    x, y = centre
    box = [x - radius, y - radius, x + radius, y + radius]
    draw.ellipse(box, fill=fill, outline=outline, width=width)


def face(image, centre, radius, colour):
    """The bot's portrait struck into the face of the medal.

    Two tones, not one: a single-colour silhouette at this size reads as a
    helmet, because the hair swallows the head. So the hair is darker than
    the metal, the face lighter, and a fringe and side locks cut back across
    the face to put a shape between them.

    The whole portrait is drawn once in shadow a pixel down and right before
    the tones go on top, which is what gives it the struck look, and it stays
    slightly transparent so it sits in the metal rather than on it.
    """
    hair = shade(colour, -0.24, 0.02)
    skin = shade(colour, 0.30, -0.18)
    cloth = shade(colour, -0.10)
    dark = shade(colour, -0.42)
    x, y = centre

    def portrait(draw, shift, mono=None):
        dx, dy = shift

        def ellipse(left, top, right, bottom, fill):
            draw.ellipse([x + radius * left + dx, y + radius * top + dy,
                          x + radius * right + dx, y + radius * bottom + dy],
                         fill=mono or fill)

        ellipse(-1.00, 0.72, 1.00, 2.24, mono or cloth)        # shoulders
        ellipse(-0.84, -1.00, 0.84, 0.70, mono or hair)        # hair, behind
        ellipse(-0.58, -0.62, 0.58, 0.80, mono or skin)        # face
        ellipse(-0.64, -1.00, 0.64, -0.22, mono or hair)       # fringe
        for side in (-1, 1):                                    # side locks
            ellipse(side * 0.60 - 0.22, -0.26, side * 0.60 + 0.22, 1.02,
                    mono or hair)
        # The ahoge: the one line that is not a circle, so the portrait does
        # not read as a thumbprint.
        draw.polygon([(x - radius * 0.12 + dx, y - radius * 0.86 + dy),
                      (x + radius * 0.04 + dx, y - radius * 1.44 + dy),
                      (x + radius * 0.22 + dx, y - radius * 0.82 + dy)],
                     fill=mono or hair)

    size = image.size[0]
    stamp = Image.new("RGBA", image.size, (0, 0, 0, 0))

    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    portrait(ImageDraw.Draw(shadow), (size * 0.008, size * 0.008), mono=dark)
    stamp = Image.alpha_composite(stamp, shadow)

    tones = Image.new("RGBA", image.size, (0, 0, 0, 0))
    portrait(ImageDraw.Draw(tones), (0, 0))
    stamp = Image.alpha_composite(stamp, tones)

    marks = ImageDraw.Draw(stamp)
    for side in (-1, 1):                                        # eyes
        marks.ellipse([x + side * radius * 0.27 - radius * 0.085,
                       y + radius * 0.06,
                       x + side * radius * 0.27 + radius * 0.085,
                       y + radius * 0.28], fill=dark)

    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).ellipse(
        [centre[0] - radius * 1.55, centre[1] - radius * 1.55,
         centre[0] + radius * 1.55, centre[1] + radius * 1.55], fill=225)
    stamp.putalpha(Image.composite(
        stamp.split()[-1], Image.new("L", image.size, 0), mask))
    return Image.alpha_composite(image, stamp)


def draw_badge(colour: str) -> Image.Image:
    size = SIZE * SCALE
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    centre = (size / 2, size / 2)

    rim_outer = size * 0.46
    rim_inner = size * 0.37
    stone = size * 0.21

    # The struck disc: a dark contour, a rim, then a dished face.
    ring(draw, centre, rim_outer, shade(colour, -0.38, -0.1))
    ring(draw, centre, rim_outer * 0.97, shade(colour, 0.02))
    # A lit crescent on the rim, drawn as a second disc pushed towards the
    # light and clipped by the face drawn over it.
    lit = (centre[0] + LIGHT[0] * size * 0.02, centre[1] + LIGHT[1] * size * 0.02)
    ring(draw, lit, rim_outer * 0.97, shade(colour, 0.16))
    ring(draw, centre, rim_inner, shade(colour, -0.10, -0.05),
         outline=shade(colour, -0.30), width=int(size * 0.012))

    # Notches around the rim, so the disc reads as struck rather than printed.
    for step in range(12):
        angle = math.radians(step * 30 + 15)
        nx = centre[0] + math.cos(angle) * (rim_outer + rim_inner) / 2
        ny = centre[1] + math.sin(angle) * (rim_outer + rim_inner) / 2
        notch = size * 0.018
        draw.ellipse([nx - notch, ny - notch, nx + notch, ny + notch],
                     fill=shade(colour, -0.22))

    image = face(image, centre, stone * 1.15, colour)

    # One soft highlight across the upper left, for the struck-metal sheen.
    gloss = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(gloss)
    gdraw.ellipse([size * 0.16, size * 0.10, size * 0.62, size * 0.40],
                  fill=(255, 255, 255, 70))
    gloss = gloss.filter(ImageFilter.GaussianBlur(size * 0.03))
    image = Image.alpha_composite(image, gloss)

    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    sheet = Image.new("RGBA", (SIZE * len(perks.BADGES), SIZE), (0, 0, 0, 0))

    for index, badge in enumerate(perks.BADGES):
        key = badge.key
        colour = COLOURS.get(key, "#9AA0A6")
        icon = draw_badge(colour)
        path = os.path.join(OUT_DIR, f"{key}.png")
        icon.save(path)
        sheet.paste(icon, (index * SIZE, 0), icon)
        print(f"  {key:10} {os.path.getsize(path) // 1024:>3} KB  {path}")

    preview = os.path.join(OUT_DIR, "_preview.png")
    Image.alpha_composite(
        Image.new("RGBA", sheet.size, (24, 20, 32, 255)), sheet
    ).save(preview)
    print(f"\n{len(perks.BADGES)} badges, preview at {preview}")
    print("Upload assets/badges/*.png as server emoji named after each badge"
          " and the bot uses them on its own.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
