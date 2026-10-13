"""Rank cards: the picture $level sends.

Every server gets the card. Paper Premium lets a server set its own
background, and its members their own. Backgrounds are stored as the
finished card-sized JPEG, not as a link: Discord's attachment links stop
working after a day or so.

Drawing is plain Pillow. The font is the one Pillow carries itself
(10.1 and later), so no font files ship with the bot.
"""
import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

WIDTH, HEIGHT = 934, 282
MAX_UPLOAD = 8 * 1024 * 1024        # bytes
MAX_SIDE = 8000                     # pixels, either way


class BadImage(Exception):
    """Not a picture we can use."""


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:               # Pillow older than 10.1
        return ImageFont.load_default()


def drawable(name: str) -> str:
    """The part of a name Pillow's font can draw: Latin letters, digits and
    punctuation. Discord names are often decorated with symbols it would
    show as empty boxes; the card leaves those out."""
    kept = "".join(c for c in name if 32 <= ord(c) < 0x250)
    return " ".join(kept.split())


def _rgb(hex_colour: int):
    return ((hex_colour >> 16) & 255, (hex_colour >> 8) & 255, hex_colour & 255)


def prepare_background(raw: bytes) -> bytes:
    """An uploaded picture, cropped to fill the card and saved small."""
    if len(raw) > MAX_UPLOAD:
        raise BadImage("That picture is over 8 MB.")
    try:
        probe = Image.open(io.BytesIO(raw))
        if max(probe.size) > MAX_SIDE:
            raise BadImage("That picture is too big. Try one under 8000 pixels a side.")
        probe.verify()
        image = Image.open(io.BytesIO(raw))
        image.seek(0)               # the first frame of a GIF
        image = image.convert("RGB")
    except BadImage:
        raise
    except Exception:
        raise BadImage("That doesn't look like a picture. Try a PNG, JPG or GIF.")
    image = ImageOps.fit(image, (WIDTH, HEIGHT), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=86, optimize=True)
    return out.getvalue()


def _default_background(accent) -> Image.Image:
    """The free card: a night sky tinted with the server's colour."""
    base = Image.new("RGB", (WIDTH, HEIGHT), (8, 11, 13))
    glow = Image.new("RGB", (WIDTH, HEIGHT), (8, 11, 13))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-160, -220, 520, 360), fill=accent)
    draw.ellipse((620, 80, 1100, 520), fill=(110, 175, 235))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    base = Image.blend(base, glow, 0.35)
    stars = ImageDraw.Draw(base)
    rng = random.Random(7)          # the same sky every time
    for _ in range(90):
        x, y = rng.randrange(WIDTH), rng.randrange(HEIGHT)
        shade = rng.randrange(120, 255)
        r = rng.choice((0, 0, 0, 1))
        stars.ellipse((x - r, y - r, x + r, y + r), fill=(shade, shade, shade))
    return base


def render(name: str, avatar: bytes, level: int, into: int, needed: int,
           rank: int, total_xp: int, accent_hex: int, background: bytes = None,
           fallback: str = "") -> bytes:
    accent = _rgb(accent_hex)
    if background:
        card = Image.open(io.BytesIO(background)).convert("RGB").resize((WIDTH, HEIGHT))
    else:
        card = _default_background(accent)
    card = card.convert("RGBA")

    # A dark glass panel so the text reads on any picture.
    panel = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle((18, 18, WIDTH - 18, HEIGHT - 18), 26,
                                            fill=(10, 8, 18, 150))
    card = Image.alpha_composite(card, panel)
    draw = ImageDraw.Draw(card)

    # Avatar in a ring of the server's colour.
    size = 170
    try:
        face = Image.open(io.BytesIO(avatar)).convert("RGB").resize((size, size))
    except Exception:
        face = Image.new("RGB", (size, size), (24, 34, 38))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    left, top = 52, (HEIGHT - size) // 2
    draw.ellipse((left - 6, top - 6, left + size + 6, top + size + 6), fill=accent)
    card.paste(face, (left, top), mask)

    text_x = left + size + 40
    white, dim = (234, 242, 244), (150, 172, 178)
    big, mid, small = _font(40), _font(26), _font(22)

    shown = drawable(name) or drawable(fallback) or "member"
    shown = shown if len(shown) <= 22 else shown[:21] + "…"
    draw.text((text_x, 62), shown, font=big, fill=white, stroke_width=1, stroke_fill=white)
    right = WIDTH - 52
    level_text = f"LEVEL {level}"
    draw.text((right, 64), level_text, font=mid, fill=accent, anchor="ra")
    rank_text = f"#{rank}" if rank else "unranked"
    lw = draw.textlength(level_text, font=mid)
    draw.text((right - lw - 26, 64), rank_text, font=mid, fill=white, anchor="ra")

    # The bar.
    bar_top, bar_h = 168, 34
    bar_right = right
    # The empty track is see-through, so it goes on its own layer: drawn
    # straight onto the card, its transparency would be lost.
    track = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(track).rounded_rectangle(
        (text_x, bar_top, bar_right, bar_top + bar_h), bar_h // 2,
        fill=(255, 255, 255, 38))
    card = Image.alpha_composite(card, track)
    draw = ImageDraw.Draw(card)
    share = max(0.0, min(1.0, into / needed if needed else 1))
    if share > 0:
        end = text_x + max(bar_h, int((bar_right - text_x) * share))
        draw.rounded_rectangle((text_x, bar_top, end, bar_top + bar_h), bar_h // 2,
                               fill=accent)
    draw.text((text_x, bar_top - 36), f"{into:,} / {needed:,} XP", font=small, fill=dim)
    draw.text((bar_right, bar_top - 36), f"{total_xp:,} total", font=small, fill=dim,
              anchor="ra")

    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()
