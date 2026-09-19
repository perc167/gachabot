"""Draws the shard icons as faceted crystal PNGs.

    python tools/make_shards.py

Writes 128x128 transparent PNGs to assets/shards/, one per shard type in
config.SHARD_TYPES, ready to upload to a Discord server as custom emoji.
Discord's limit is 256KB per emoji; these come out well under it.

The cut is a marquise: a narrow bipyramid with a girdle round the middle, so
each stone is a row of upper triangles, a band of belt facets, and a row of
lower triangles - fifteen facets rather than five. That is what reads as a
faceted stone instead of a shaded lozenge, while flat fills and a heavy
contour keep it cartoonish rather than photographic.

Lighting is one source up and to the left. Brightness falls off across the
width, and the upper row catches more than the belt, which catches more than
the lower row.

Everything is drawn at 4x and scaled down, because Pillow's polygon fill has
no antialiasing.

Needs Pillow, which the bot itself does not:  pip install Pillow
"""
import colorsys
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

SIZE = 128
SCALE = 4  # supersampling factor
OUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "shards"
)

# Outline of the stone in a 128x128 box. Narrow: a slim crystal looks cut, a
# wide one looks like a pebble. Very slightly asymmetric so it does not read
# as a machine-perfect vector shape.
T = (64, 4)       # top point
B = (64, 125)     # bottom point
UL = (41, 44)     # left end of the upper girdle
UR = (88, 40)     # right end of the upper girdle
LL = (43, 84)     # left end of the lower girdle
LR = (86, 80)     # right end of the lower girdle

SILHOUETTE = [T, UR, LR, B, LL, UL]

COLUMNS = 5  # facets across the stone

# Brightness across the width, left (lit) to right (shadowed), and per row.
ACROSS = (1.50, 1.26, 1.04, 0.80, 0.58)
ROW_UPPER, ROW_BELT, ROW_LOWER = 1.10, 1.00, 0.84

# Where the glint sits, as a fraction of the icon. Narrow and tapered: a fat
# white shape reads as a sticker rather than a reflection.
GLINT = [(0.345, 0.26), (0.40, 0.33), (0.375, 0.56), (0.345, 0.47)]


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def shade(rgb, factor):
    """Lighten or darken a facet, keeping its hue.

    Lightness moves by an offset rather than a multiplier, so the black and
    white stones still show their facets - multiplying a near-zero lightness
    leaves an unreadable silhouette.
    """
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.02, min(0.99, l + (factor - 1.0) * 0.46))
    if factor < 1:
        s *= 0.9  # shadows drift a touch grey
    r, g, b = colorsys.hls_to_rgb(h, l, max(0.0, min(1.0, s)))
    return (round(r * 255), round(g * 255), round(b * 255))


def with_hue(rgb, hue):
    """Same lightness and saturation, different hue. Used for Prism."""
    r, g, b = (c / 255 for c in rgb)
    _, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(hue % 1.0, l, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def scaled(points):
    return [(x * SCALE, y * SCALE) for x, y in points]


def facets():
    """Every facet as (polygon, brightness factor, column index)."""
    upper = [lerp(UL, UR, i / COLUMNS) for i in range(COLUMNS + 1)]
    lower = [lerp(LL, LR, i / COLUMNS) for i in range(COLUMNS + 1)]
    out = []
    for i in range(COLUMNS):
        across = ACROSS[min(i, len(ACROSS) - 1)]
        out.append(([T, upper[i], upper[i + 1]], across * ROW_UPPER, i))
        out.append(
            ([upper[i], upper[i + 1], lower[i + 1], lower[i]], across * ROW_BELT, i)
        )
        out.append(([B, lower[i], lower[i + 1]], across * ROW_LOWER, i))
    return out


def facet_colour(base_rgb, column, rainbow):
    if not rainbow:
        return base_rgb
    # A spectrum in order across the stone, so it reads as a rainbow rather
    # than as random colours sitting next to each other.
    tinted = with_hue(base_rgb, 0.02 + 0.76 * column / (COLUMNS - 1))
    r, g, b = (c / 255 for c in tinted)
    h, l, sat = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, min(0.95, l * 1.06), sat * 0.72)
    return (round(r * 255), round(g * 255), round(b * 255))


def draw_crystal(base_rgb, rainbow=False) -> Image.Image:
    canvas = SIZE * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))

    # A rainbow stone has no single colour, so its contour and bloom take a
    # neutral - otherwise the base hue rings the whole thing in magenta.
    frame_rgb = (126, 126, 138) if rainbow else base_rgb

    # A soft bloom behind the stone so it sits on the page rather than on top
    # of it. Subtle: Discord renders emoji small.
    glow = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(
        scaled(SILHOUETTE), fill=(*shade(frame_rgb, 1.3), 95)
    )
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=6 * SCALE)))

    draw = ImageDraw.Draw(image)
    all_facets = facets()

    for points, factor, column in all_facets:
        draw.polygon(
            scaled(points), fill=shade(facet_colour(base_rgb, column, rainbow), factor)
        )

    # Facet seams: thin, and only a little darker than the faces they divide,
    # otherwise the stone turns into a wireframe.
    for points, factor, column in all_facets:
        draw.line(
            scaled(points + [points[0]]),
            fill=shade(facet_colour(base_rgb, column, rainbow), factor * 0.82),
            width=max(2, SCALE // 2),
        )

    # The girdle: the belt edges read as a band round the middle rather than
    # as two coincidental rows of seams.
    for edge in ([UL, UR], [LL, LR]):
        draw.line(scaled(edge), fill=shade(frame_rgb, 0.62), width=max(2, SCALE // 2))

    # Outer contour, dark and solid: the cartoon part of the look.
    draw.line(
        scaled(SILHOUETTE + [SILHOUETTE[0]]),
        fill=shade(frame_rgb, 0.34),
        width=2 * SCALE,
        joint="curve",
    )

    glint = [(SIZE * x, SIZE * y) for x, y in GLINT]
    draw.polygon(scaled(glint), fill=(255, 255, 255, 165))

    return image.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    written = []
    for key, name, _icon, _mult, _weight, colour in config.SHARD_TYPES:
        base = ((colour >> 16) & 255, (colour >> 8) & 255, colour & 255)
        image = draw_crystal(base, rainbow=(key == "prism"))
        path = os.path.join(OUT_DIR, f"{key}.png")
        image.save(path, "PNG", optimize=True)
        written.append((key, name, path, os.path.getsize(path)))

    # Contact sheet on Discord's own dark grey, so the white and the black
    # stone are both visible - on transparency one of them always vanishes.
    sheet = Image.new("RGBA", (SIZE * len(written), SIZE), (54, 57, 63, 255))
    for index, (key, *_rest) in enumerate(written):
        sheet.alpha_composite(
            Image.open(os.path.join(OUT_DIR, f"{key}.png")), (index * SIZE, 0)
        )
    sheet_path = os.path.join(OUT_DIR, "_preview.png")
    sheet.save(sheet_path, "PNG", optimize=True)

    print(f"Wrote {len(written)} shard icons to {OUT_DIR}\n")
    for key, name, path, size in written:
        print(f"  {name:<12} {os.path.basename(path):<14} {size / 1024:5.1f} KB")
    print(f"\n  preview      {os.path.basename(sheet_path)}")
    print("\nUpload these in Discord: Server Settings -> Emoji -> Upload Emoji.")
    print("Then put the <:name:id> form into SHARD_TYPES in config.py.")


if __name__ == "__main__":
    main()
