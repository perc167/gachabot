"""Draws the badge icons: a shape per material, a treatment per tier, her face on every one.

    python tools/make_badges.py

Writes 128x128 transparent PNGs to assets/badges/, one per badge per level -
paper1.png through diamond4.png - for the bot to upload to itself as
application emoji. Discord's limit is 256KB each; these land near 20.

Three things carry the meaning, so a badge reads at the 32 pixels Discord
actually shows an emoji at:

  The shape says which badge. A sheet for Paper, a nut for Iron, a star for
  Gold, and a stone each for the gems. Colour alone was not enough: at emoji
  size seven coloured discs are seven coloured discs.

  The treatment says which level. I is the bare shape, II adds an inner line,
  III adds studs at its points, IV adds a spiked halo behind it, and the
  metal brightens a little as it climbs.

  The face says whose bot it is. assets/avatar.png is cropped to her head,
  washed towards the badge's own metal and set inside the shape. A grey
  relief was tried first and lost her: at 32 pixels a monochrome stamp of a
  face is a smear, while a tinted picture is still recognisably her.

Everything is drawn at 4x and scaled down, because Pillow's polygon fill has
no antialiasing.

Needs Pillow, which the bot itself does not:  pip install Pillow
"""
import colorsys
import math
import os
import re
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import perks  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "assets", "badges")
AVATAR = os.path.join(ROOT, "assets", "avatar.png")

SIZE = 128
SCALE = 4

# Where her face is in the avatar, as fractions of its width and height, and
# how wide a square to take around it. Measured from the art rather than
# guessed: centring on the head instead put her eyes at the edge of the
# shape and filled the middle with hair.
FACE_CENTRE = (0.55, 0.42)
# Wider than the head, because a shape only shows the middle of the square:
# a crop sized to the head alone ends up as one eye and a lot of hair.
FACE_WIDTH = 0.92

COLOURS = {
    "paper": "#E8E2D4",
    "iron": "#8C96A3",
    "gold": "#E8B54A",
    "emerald": "#3FB984",
    "opal": "#8FD5E8",
    "amethyst": "#A46BE0",
    "diamond": "#BFE6F5",
}


def shade(hex_colour: str, lightness: float = 0.0, saturation: float = 0.0):
    raw = hex_colour.lstrip("#")
    red, green, blue = (int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(red, green, blue)
    light = max(0.0, min(1.0, light + lightness))
    sat = max(0.0, min(1.0, sat + saturation))
    red, green, blue = colorsys.hls_to_rgb(hue, light, sat)
    return tuple(round(channel * 255) for channel in (red, green, blue))


# --------------------------------------------------------------------------
# The shapes. Each returns points in a box of `radius` about `centre`, and
# each is recognisable in silhouette alone.
# --------------------------------------------------------------------------
def regular(centre, radius, sides, turn=-90.0):
    x, y = centre
    step = 360.0 / sides
    return [(x + radius * math.cos(math.radians(turn + step * n)),
             y + radius * math.sin(math.radians(turn + step * n)))
            for n in range(sides)]


def star(centre, radius, points=5, inner=0.46, turn=-90.0):
    x, y = centre
    step = 180.0 / points
    out = []
    for n in range(points * 2):
        length = radius if n % 2 == 0 else radius * inner
        angle = math.radians(turn + step * n)
        out.append((x + length * math.cos(angle), y + length * math.sin(angle)))
    return out


def sheet(centre, radius):
    """A page with its corner turned down."""
    x, y = centre
    wide, tall = radius * 0.82, radius * 1.02
    return [(x - wide, y - tall), (x + wide * 0.42, y - tall),
            (x + wide, y - tall * 0.40), (x + wide, y + tall),
            (x - wide, y + tall)]


def teardrop(centre, radius):
    x, y = centre
    points = [(x, y - radius * 1.14)]
    for degree in range(-36, 217, 8):
        angle = math.radians(degree)
        points.append((x + radius * 0.94 * math.cos(angle),
                       y + radius * 0.94 * math.sin(angle) + radius * 0.16))
    return points


def brilliant(centre, radius):
    """A cut stone seen face on: a wide table over a tapering pavilion."""
    x, y = centre
    return [(x - radius * 0.64, y - radius * 0.74),
            (x + radius * 0.64, y - radius * 0.74),
            (x + radius * 1.00, y - radius * 0.14),
            (x, y + radius * 1.12),
            (x - radius * 1.00, y - radius * 0.14)]


SHAPES = {
    "paper": lambda c, r: sheet(c, r),
    "iron": lambda c, r: regular(c, r, 6),
    "gold": lambda c, r: star(c, r * 1.14, points=5),
    "emerald": lambda c, r: regular(c, r * 1.08, 3),
    "opal": lambda c, r: teardrop(c, r),
    "amethyst": lambda c, r: regular(c, r * 1.06, 4),
    "diamond": lambda c, r: brilliant(c, r),
}


def head_art(size: int):
    """Her head, cropped square from the avatar. Cached per size."""
    if not os.path.exists(AVATAR):
        return None
    if size in head_art.cache:
        return head_art.cache[size]

    avatar = Image.open(AVATAR).convert("RGB")
    width, height = avatar.size
    half = width * FACE_WIDTH / 2
    x, y = width * FACE_CENTRE[0], height * FACE_CENTRE[1]
    # Clamped, so a differently framed avatar cannot crop off the edge.
    x = min(max(x, half), width - half)
    y = min(max(y, half), height - half)
    head = avatar.crop((round(x - half), round(y - half),
                        round(x + half), round(y + half)))
    head = head.resize((size, size), Image.LANCZOS)
    # A little more contrast and colour than the original: the picture ends
    # up 32 pixels across, tinted, behind a rim.
    head = ImageEnhance.Contrast(head).enhance(1.15)
    head = ImageEnhance.Color(head).enhance(1.20)
    head_art.cache[size] = head
    return head


head_art.cache = {}


def tinted(art, colour, level: int):
    """Her face pulled towards this badge's metal, more so at low levels.

    Not a grey relief: a monochrome stamp of her at emoji size is a smear.
    Keeping the picture and washing it towards the material keeps her a
    face while the badge stays obviously paper, gold or emerald.
    """
    wash = Image.new("RGB", art.size, shade(colour, 0.06 - 0.015 * level))
    return Image.blend(art, wash, 0.46 - 0.03 * level)


def inset(points, centre, factor):
    return [(centre[0] + (x - centre[0]) * factor,
             centre[1] + (y - centre[1]) * factor) for x, y in points]


def draw_badge(key: str, level: int) -> Image.Image:
    size = SIZE * SCALE
    colour = COLOURS.get(key, "#9AA0A6")
    centre = (size / 2, size / 2)
    radius = size * 0.40

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    points = SHAPES[key](centre, radius)

    # IV wears a halo, which is what makes a maxed badge obvious in a list.
    if level >= perks.LEVELS:
        draw.polygon(star(centre, radius * 1.32, points=12, inner=0.76),
                     fill=shade(colour, 0.10, -0.22))

    draw.polygon(points, fill=shade(colour, 0.035 * (level - 1)),
                 outline=shade(colour, -0.42), width=max(2, int(size * 0.016)))

    art = head_art(size)
    if art is not None:
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).polygon(inset(points, centre, 0.86), fill=255)
        image.paste(tinted(art, colour, level), (0, 0), mask)

    if level >= 2:
        ImageDraw.Draw(image).polygon(
            inset(points, centre, 0.91), outline=shade(colour, 0.32, -0.12),
            width=max(1, int(size * 0.008)))
    if level >= 3:
        studs = ImageDraw.Draw(image)
        for x, y in points[:8]:
            spot = size * 0.021
            sx, sy = inset([(x, y)], centre, 0.99)[0]
            studs.ellipse([sx - spot, sy - spot, sx + spot, sy + spot],
                          fill=shade(colour, 0.36, -0.16))

    gloss = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse(
        [size * 0.18, size * 0.10, size * 0.60, size * 0.36],
        fill=(255, 255, 255, 44))
    image = Image.alpha_composite(
        image, gloss.filter(ImageFilter.GaussianBlur(size * 0.03)))

    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(AVATAR):
        print(f"no avatar at {AVATAR}; the badges will be bare shapes")

    # The single-icon run left paper.png beside paper1.png, and the bot
    # uploads whatever it finds.
    for stale in os.listdir(OUT_DIR):
        if (stale.endswith(".png") and not stale.startswith("_")
                and not re.fullmatch(r"[a-z]+[1-9]\\d*\\.png", stale)):
            os.remove(os.path.join(OUT_DIR, stale))
            print(f"  removed {stale}, left over from the one-icon badges")

    grid = Image.new("RGBA", (SIZE * perks.LEVELS, SIZE * len(perks.BADGES)),
                     (0, 0, 0, 0))
    written = 0
    for row, badge in enumerate(perks.BADGES):
        for level in range(1, perks.LEVELS + 1):
            icon = draw_badge(badge.key, level)
            path = os.path.join(OUT_DIR, f"{badge.key}{level}.png")
            icon.save(path)
            grid.paste(icon, ((level - 1) * SIZE, row * SIZE), icon)
            written += 1
        print(f"  {badge.key:10} I-IV  {os.path.getsize(path) // 1024:>3} KB each")

    preview = os.path.join(OUT_DIR, "_preview.png")
    Image.alpha_composite(
        Image.new("RGBA", grid.size, (24, 20, 32, 255)), grid).save(preview)
    print(f"\\n{written} icons, preview at {preview}")
    print("The bot uploads these to itself on its next start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
