"""Paper's own face: the avatar and the profile banner.

    python tools/make_brand.py

The old one was baby blue with hearts on it, which said nothing about the
name. These start from the name instead. Paper is not blue - it is a pale
sheet with ink on it - so the ground is ink and the sheets are the light
thing on top of it. That way round reads better on Discord, which most
people look at in the dark, and it keeps the warm off-white from turning
the whole thing into a stationery advert.

Three ideas, drawn the same way so they can be compared:

  fold    one sheet with its corner turned down. The plainest thing that
          can only be paper, and the only one that still reads at the 32
          pixels Discord shows an avatar at in a member list.
  crease  one sheet folded down the middle, the two halves catching
          different light.
  deck    three sheets offset. A gacha bot is a deck of cards, and a card
          is a piece of paper, so this is the name and the game at once.

No lettering on the avatar: at 32 pixels a word is a smudge.
"""
import argparse
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "brand")

AVATAR = 1024
BANNER_W, BANNER_H = 1360, 480          # twice what Discord shows, for crispness

INK = (18, 20, 25)
INK_SOFT = (26, 29, 35)
SHEET = (242, 240, 235)
SHEET_MID = (214, 211, 203)
SHEET_DEEP = (176, 172, 163)
THREAD = (196, 86, 78)                   # one warm line, used sparingly

FONTS = "C:/Windows/Fonts/"


def font(name: str, size: int):
    from PIL import ImageFont

    for candidate in (name, "segoeuil.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(FONTS + candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def ground(width: int, height: int):
    """The ink background, with a breath of light in one corner."""
    from PIL import Image, ImageDraw, ImageFilter

    base = Image.new("RGB", (width, height), INK)
    glow = Image.new("L", (width, height), 0)
    ImageDraw.Draw(glow).ellipse(
        (-width * 0.25, -height * 0.55, width * 0.75, height * 0.75), fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(width * 0.18))
    base.paste(Image.new("RGB", (width, height), INK_SOFT), (0, 0), glow)
    return base


def shadow(size, polygon, blur, offset, strength=150):
    """A soft shadow under a shape, so a flat sheet sits above the ink."""
    from PIL import Image, ImageDraw, ImageFilter

    layer = Image.new("L", size, 0)
    ImageDraw.Draw(layer).polygon(
        [(x + offset[0], y + offset[1]) for x, y in polygon], fill=strength)
    return layer.filter(ImageFilter.GaussianBlur(blur))


def turned(centre, width, height, angle):
    """The four corners of a sheet, rotated about its middle."""
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    corners = [(-width / 2, -height / 2), (width / 2, -height / 2),
               (width / 2, height / 2), (-width / 2, height / 2)]
    return [(centre[0] + x * cos - y * sin, centre[1] + x * sin + y * cos)
            for x, y in corners]


def between(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def draw_fold(image, centre, size, angle=-7, ear=0.3):
    """A sheet with its top-right corner turned down."""
    from PIL import Image, ImageDraw

    width = size
    height = size * 1.32
    tl, tr, br, bl = turned(centre, width, height, angle)
    cut_top = between(tl, tr, 1 - ear)
    cut_side = between(tr, br, ear)

    image.paste(Image.new("RGB", image.size, (0, 0, 0)), (0, 0),
                shadow(image.size, [tl, cut_top, cut_side, br, bl],
                       size * 0.06, (0, size * 0.035)))
    draw = ImageDraw.Draw(image)
    draw.polygon([tl, cut_top, cut_side, br, bl], fill=SHEET)
    # The flap: the back of the corner, folded forward and down.
    draw.polygon([cut_top, cut_side, between(cut_top, cut_side, 0.5)],
                 fill=SHEET_MID)
    draw.polygon([cut_top, cut_side,
                  between(between(cut_top, cut_side, 0.5), tr, -0.85)],
                 fill=SHEET_DEEP)
    return image


def draw_crease(image, centre, size, angle=-7):
    """A sheet folded down its middle, each half taking its own light."""
    from PIL import Image, ImageDraw

    width = size
    height = size * 1.32
    tl, tr, br, bl = turned(centre, width, height, angle)
    top = between(tl, tr, 0.5)
    bottom = between(bl, br, 0.5)

    image.paste(Image.new("RGB", image.size, (0, 0, 0)), (0, 0),
                shadow(image.size, [tl, tr, br, bl], size * 0.06,
                       (0, size * 0.035)))
    draw = ImageDraw.Draw(image)
    draw.polygon([tl, top, bottom, bl], fill=SHEET)
    draw.polygon([top, tr, br, bottom], fill=SHEET_MID)
    draw.line([top, bottom], fill=SHEET_DEEP, width=max(2, int(size // 150)))
    return image


def draw_deck(image, centre, size, angle=-7):
    """Three sheets offset: a deck of cards, which is what the game is."""
    from PIL import Image, ImageDraw

    width = size * 0.84
    height = size * 1.18
    steps = ((-size * 0.17, size * 0.10, angle - 12, SHEET_DEEP),
             (-size * 0.02, size * 0.02, angle - 5, SHEET_MID),
             (size * 0.13, -size * 0.06, angle + 2, SHEET))
    for dx, dy, turn, colour in steps:
        spot = (centre[0] + dx, centre[1] + dy)
        corners = turned(spot, width, height, turn)
        image.paste(Image.new("RGB", image.size, (0, 0, 0)), (0, 0),
                    shadow(image.size, corners, size * 0.045,
                           (0, size * 0.028), 130))
        ImageDraw.Draw(image).polygon(corners, fill=colour)
    return image


SHAPES = {"fold": draw_fold, "crease": draw_crease, "deck": draw_deck}


def avatar(kind: str):
    image = ground(AVATAR, AVATAR)
    SHAPES[kind](image, (AVATAR / 2, AVATAR / 2), AVATAR * 0.46)
    return image


def banner(kind: str):
    """The wordmark on the left, the mark on the right."""
    from PIL import ImageDraw

    image = ground(BANNER_W, BANNER_H)
    SHAPES[kind](image, (BANNER_W * 0.78, BANNER_H * 0.52), BANNER_H * 0.52)
    draw = ImageDraw.Draw(image)

    name = font("segoeuil.ttf", 132)
    word, spacing = "PAPER", 22
    x = int(BANNER_W * 0.085)
    middle = int(BANNER_H * 0.40)
    for letter in word:
        draw.text((x, middle), letter, font=name, fill=SHEET, anchor="lm")
        x += int(draw.textlength(letter, font=name)) + spacing

    line_y = int(BANNER_H * 0.655)
    draw.line([(BANNER_W * 0.088, line_y), (x - spacing, line_y)],
              fill=SHEET_DEEP, width=2)
    draw.line([(BANNER_W * 0.088, line_y), (BANNER_W * 0.088 + 54, line_y)],
              fill=THREAD, width=2)

    small = font("segoeuisl.ttf", 31)
    draw.text((BANNER_W * 0.088, line_y + 34),
              "gacha · moderation · voice · levels", font=small,
              fill=(150, 147, 140))
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", default="all", choices=[*SHAPES, "all"])
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    kinds = list(SHAPES) if args.kind == "all" else [args.kind]
    for kind in kinds:
        avatar(kind).save(os.path.join(args.out, f"avatar-{kind}.png"))
        banner(kind).save(os.path.join(args.out, f"banner-{kind}.png"))
        print(f"  {kind}: avatar-{kind}.png and banner-{kind}.png")
    print(f"\nin {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
