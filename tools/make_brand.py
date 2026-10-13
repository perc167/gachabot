"""Cuts Paper's look out of her source picture.

    python tools/make_brand.py

assets/brand/source-avatar.jpg is her, as drawn: a pink cat. Every pink in
her is turned baby blue here, and the avatar, the favicons, the dashboard's
logo and the website's hero art all come from the blue result. Discord's
profile banner and the sky behind the website and the dashboard are drawn
here: soft baby-blue clouds on near white, with a scatter of little hearts
like the two over her head.

Writes:
  assets/brand/avatar.png      512x512, for the Developer Portal
  assets/brand/banner.png      1360x480, Discord's banner shape (17:6)
  site/img/favicon.png         64x64
  site/img/paper-180.png       180x180 (the nav and the home-screen icon)
  site/img/paper-512.png       512x512 (link previews)
  site/img/paper-art.webp      the hero's artwork
  site/img/sky.webp            the page background
  dashboard/paper.png          256x256

The source is small (510 pixels across), so the bigger outputs are scaled
up.
"""
import os

import math
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "assets", "brand")
SITE_IMG = os.path.join(ROOT, "site", "img")

# Where her face sits in the source, as fractions of its width and height,
# and how much of the picture a square crop takes around it.
FACE = (0.50, 0.50)
FACE_SPAN = 1.0

# Hues counted as pink, in degrees (it wraps through red), and the baby blue
# they become. Each pink keeps half its distance from the middle of the
# range, so the lighter and deeper pinks stay apart once they are blue.
PINK_FROM, PINK_TO, PINK_MID = 280, 25, 340
BLUE = 205
# Greys and whites have a hue too, a meaningless one: below this saturation
# (out of 255) a pixel is left alone.
MIN_SATURATION = 12


def blue(img: Image.Image) -> Image.Image:
    hsv = np.array(img.convert("HSV")).astype(np.float32)
    deg = hsv[..., 0] * 360 / 255
    pink = ((deg > PINK_FROM) | (deg < PINK_TO)) & (hsv[..., 1] > MIN_SATURATION)
    off = ((deg - PINK_MID + 180) % 360) - 180
    deg = np.where(pink, BLUE + off * 0.5, deg)
    hsv[..., 0] = (deg % 360) * 255 / 360
    return Image.fromarray(hsv.clip(0, 255).astype(np.uint8), "HSV").convert("RGB")


def square(img: Image.Image, centre, span: float) -> Image.Image:
    w, h = img.size
    side = int(min(w, h) * span)
    x = int(w * centre[0] - side / 2)
    y = int(h * centre[1] - side / 2)
    x = max(0, min(x, w - side))
    y = max(0, min(y, h - side))
    return img.crop((x, y, x + side, y + side))


def sized(img: Image.Image, size: int) -> Image.Image:
    return img.resize((size, size), Image.LANCZOS)


# The sky's colours: the paper it is drawn on, and the clouds.
PAPER = (244, 249, 255)
CLOUDS = ((176, 218, 248), (204, 230, 252), (160, 206, 244), (222, 236, 255))
HEART = (140, 200, 245)


def heart(draw: ImageDraw.ImageDraw, cx: float, cy: float, size: float, fill):
    points = []
    for i in range(48):
        t = i / 48 * 2 * math.pi
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        points.append((cx + x * size / 32, cy - y * size / 32))
    draw.polygon(points, fill=fill)


def sky(width: int, height: int, seed: int, hearts: int) -> Image.Image:
    """Soft blue clouds on near-white paper, and a few faint hearts."""
    rng = random.Random(seed)
    img = Image.new("RGB", (width, height), PAPER)
    clouds = Image.new("RGB", (width, height), PAPER)
    draw = ImageDraw.Draw(clouds)
    for _ in range(9):
        r = rng.uniform(0.18, 0.38) * width
        x, y = rng.uniform(-0.1, 1.1) * width, rng.uniform(-0.2, 1.2) * height
        draw.ellipse((x - r, y - r * 0.7, x + r, y + r * 0.7), fill=rng.choice(CLOUDS))
    img = Image.blend(img, clouds.filter(ImageFilter.GaussianBlur(width / 14)), 0.85)
    marks = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(marks)
    for _ in range(hearts):
        size = rng.uniform(0.012, 0.03) * width
        heart(draw, rng.uniform(0, width), rng.uniform(0, height), size,
              HEART + (rng.randint(50, 110),))
    img.paste(marks, (0, 0), marks)
    return img


def main():
    her = blue(Image.open(os.path.join(BRAND, "source-avatar.jpg")).convert("RGB"))

    face = square(her, FACE, FACE_SPAN)
    sized(face, 512).save(os.path.join(BRAND, "avatar.png"), optimize=True)
    sized(face, 64).save(os.path.join(SITE_IMG, "favicon.png"), optimize=True)
    sized(face, 180).save(os.path.join(SITE_IMG, "paper-180.png"), optimize=True)
    sized(face, 512).save(os.path.join(SITE_IMG, "paper-512.png"), optimize=True)
    sized(face, 256).save(os.path.join(ROOT, "dashboard", "paper.png"), optimize=True)
    her.resize((560, 560), Image.LANCZOS).save(
        os.path.join(SITE_IMG, "paper-art.webp"), quality=90, method=6)

    sky(1360, 480, 7, 14).save(os.path.join(BRAND, "banner.png"), optimize=True)
    # The page's sky has no hearts: the website floats its own over it.
    sky(1600, 1000, 3, 0).save(os.path.join(SITE_IMG, "sky.webp"), quality=80, method=6)

    print("wrote the avatar, banner, favicons, hero art and background")


if __name__ == "__main__":
    main()
