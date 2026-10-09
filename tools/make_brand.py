"""Cuts Paper's look out of its two source pictures.

    python tools/make_brand.py

assets/brand/source-avatar.webp is her: the avatar, the favicons, the
dashboard's logo and the website's hero art all come from it.
assets/brand/source-glacier.webp is the glacier waterfall: Discord's profile
banner, and the background behind the website and the dashboard.

Writes:
  assets/brand/avatar.png      512x512, for the Developer Portal
  assets/brand/banner.png      1360x480, Discord's banner shape (17:6)
  site/img/favicon.png         64x64
  site/img/paper-180.png       180x180 (the nav and the home-screen icon)
  site/img/paper-512.png       512x512 (link previews)
  site/img/paper-art.webp      the hero's artwork
  site/img/glacier.webp        the page background
  dashboard/paper.png          256x256

The sources are small (500 pixels across), so the bigger outputs are scaled
up. The banner and the background are seen soft anyway: the background sits
blurred and darkened behind the page, and Discord shows a banner at about
600 pixels wide.
"""
import os

from PIL import Image, ImageEnhance, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "assets", "brand")
SITE_IMG = os.path.join(ROOT, "site", "img")

# Where her face sits in the avatar source, as fractions of its width and
# height, and how much of the picture a square crop takes around it.
FACE = (0.50, 0.50)
FACE_SPAN = 1.0

# The banner's slice of the waterfall: from this far down, 17:6.
BANNER_TOP = 0.2
# How much of the waterfall to keep, from the top: below it is a watermark.
WATERMARK_FREE = 0.9


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


def main():
    her = Image.open(os.path.join(BRAND, "source-avatar.webp")).convert("RGB")
    glacier = Image.open(os.path.join(BRAND, "source-glacier.webp")).convert("RGB")
    # The bottom strip carries a watermark in its corner.
    glacier = glacier.crop((0, 0, glacier.width, int(glacier.height * WATERMARK_FREE)))

    face = square(her, FACE, FACE_SPAN)
    sized(face, 512).save(os.path.join(BRAND, "avatar.png"), optimize=True)
    sized(face, 64).save(os.path.join(SITE_IMG, "favicon.png"), optimize=True)
    sized(face, 180).save(os.path.join(SITE_IMG, "paper-180.png"), optimize=True)
    sized(face, 512).save(os.path.join(SITE_IMG, "paper-512.png"), optimize=True)
    sized(face, 256).save(os.path.join(ROOT, "dashboard", "paper.png"), optimize=True)
    her.resize((560, 560), Image.LANCZOS).save(
        os.path.join(SITE_IMG, "paper-art.webp"), quality=90, method=6)

    w, h = glacier.size
    band = int(w * 6 / 17)
    top = min(int(h * BANNER_TOP), h - band)
    banner = glacier.crop((0, top, w, top + band)).resize((1360, 480), Image.LANCZOS)
    banner.filter(ImageFilter.UnsharpMask(2, 40, 2)).save(
        os.path.join(BRAND, "banner.png"), optimize=True)

    # The page background: wide, soft and dark, so text over it stays easy
    # to read and the low resolution never shows.
    back = glacier.resize((1600, int(1600 * h / w)), Image.LANCZOS)
    back = back.filter(ImageFilter.GaussianBlur(3))
    back = ImageEnhance.Brightness(back).enhance(0.8)
    back.save(os.path.join(SITE_IMG, "glacier.webp"), quality=78, method=6)

    print("wrote the avatar, banner, favicons, hero art and background")


if __name__ == "__main__":
    main()
