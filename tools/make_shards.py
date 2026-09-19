"""Draws the shard icons as faceted crystal PNGs.

    python tools/make_shards.py

Writes 128x128 transparent PNGs to assets/shards/, one per shard type in
config.SHARD_TYPES, ready to upload to a Discord server as custom emoji.
Discord's limit is 256KB per emoji; these come out a few KB each.

The crystal is one silhouette cut into five facets. A light source up and to
the left makes the left faces bright and the right faces dark, which is what
sells it as a solid object rather than a coloured blob. Everything is drawn
at 4x and scaled down, because Pillow's polygon fill has no antialiasing.

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

# Crystal outline in a 128x128 box: a tall bipyramid, pointed top and bottom,
# slightly off-centre so it reads as hand cut rather than a vector shape.
T = (60, 4)      # top point
UL = (24, 42)    # left shoulder
UR = (102, 36)   # right shoulder
L = (32, 96)     # left corner
R = (96, 90)     # right corner
B = (66, 125)    # bottom point

SILHOUETTE = [T, UR, R, B, L, UL]

# Internal ridges all run from the top point down to the bottom point, which
# is what gives a cut gem its long vertical facets. Each is the waist of one
# ridge line; the facets between them are the planes of the crystal.
RIDGES = [(38, 46), (52, 52), (70, 54), (86, 48)]

# Left to right, each facet with how much to lighten (>1) or darken (<1) the
# base colour. The light sits up and to the left.
FACETS = [
    ([T, UL, L, B, RIDGES[0]], 1.52),
    ([T, RIDGES[0], B, RIDGES[1]], 1.18),
    ([T, RIDGES[1], B, RIDGES[2]], 0.96),
    ([T, RIDGES[2], B, RIDGES[3]], 0.72),
    ([T, RIDGES[3], B, R, UR], 0.46),
]

# A narrow sliver down the second facet, so the surface looks glassy rather
# than matte. Kept thin - a fat white blob reads as a sticker.
HIGHLIGHT = [(39, 40), (47, 47), (44, 74), (40, 66)]


def shade(rgb, factor):
    """Lighten or darken while keeping the hue, so it stays the same gem."""
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.05, min(0.97, l * factor))
    # Deep shadows drift slightly desaturated, highlights slightly less so.
    s = max(0.0, min(1.0, s * (0.88 if factor < 1 else 1.0)))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def hue_shift(rgb, degrees):
    r, g, b = (c / 255 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h = (h + degrees / 360.0) % 1.0
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return (round(r * 255), round(g * 255), round(b * 255))


def scaled(points):
    return [(x * SCALE, y * SCALE) for x, y in points]


def draw_crystal(base_rgb, rainbow=False) -> Image.Image:
    canvas = SIZE * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Soft glow under the crystal so it does not look pasted on.
    glow = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(
        scaled(SILHOUETTE), fill=(*shade(base_rgb, 1.25), 110)
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=7 * SCALE))
    image.alpha_composite(glow)

    for index, (points, factor) in enumerate(FACETS):
        colour = base_rgb
        if rainbow:
            # Prism: each facet is a different hue, so it reads as spectrum
            # rather than as one muddy colour.
            colour = hue_shift(base_rgb, index * 58)
        draw.polygon(scaled(points), fill=shade(colour, factor))

    # Facet edges, a shade darker than their face, then the outer contour.
    edge = shade(base_rgb, 0.42)
    for points, _ in FACETS:
        draw.line(scaled(points + [points[0]]), fill=edge, width=2)
    draw.line(
        scaled(SILHOUETTE + [SILHOUETTE[0]]),
        fill=shade(base_rgb, 0.26),
        width=2 * SCALE,
        joint="curve",
    )

    draw.polygon(scaled(HIGHLIGHT), fill=(255, 255, 255, 120))

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

    # A contact sheet, so you can see them all at once before uploading.
    sheet = Image.new("RGBA", (SIZE * len(written), SIZE), (0, 0, 0, 0))
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
