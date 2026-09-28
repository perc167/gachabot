"""The level leaderboard as a picture: the image $leaderboard sends.

Built in layers, back to front:

1. The backdrop. The server's rank card background (or the free night sky)
   runs the full height, blurred and darkened so the rows read on top, and
   the same picture sits sharp across the top, fading into it.
2. The header: the server's icon in a ring of its colour, its name, and
   which page this is.
3. On the first page, a podium for the top three: first in the middle and
   raised, with a crown and a gold glow; silver and bronze either side.
4. Glass rows for everyone else: place, avatar, name, a bar showing how
   far they are into their level, and their level.
5. A footer saying where the person who asked stands.

Plain Pillow with the font Pillow carries, the same as rankcard.py, so it
looks like it belongs next to the $level card.
"""
import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from rankcard import _font, _rgb, drawable

WIDTH = 934
HEADER = 150
PODIUM = 330
ROW, GAP = 64, 10
FOOTER = 64
MARGIN = 30

GOLD = (255, 204, 77)
SILVER = (206, 214, 232)
BRONZE = (222, 142, 92)
MEDALS = {1: GOLD, 2: SILVER, 3: BRONZE}
WHITE, DIM, FAINT = (242, 238, 252), (172, 164, 198), (118, 110, 146)


def height_for(rows: int, podium: bool) -> int:
    listed = max(0, rows - 3) if podium else rows
    return (HEADER + (PODIUM if podium else 0) + listed * (ROW + GAP)
            + FOOTER + (10 if listed else 0))


# ------------------------------------------------------------ the backdrop

def _sky(size, accent) -> Image.Image:
    """The free background, as tall as the board: the rank card's night sky
    with its two glows, and a third lower down so the length isn't flat."""
    w, h = size
    base = Image.new("RGB", size, (13, 11, 20))
    # Glows are soft, so they're drawn small and blown up: far quicker than
    # blurring the full-size picture.
    small = Image.new("RGB", (w // 4, h // 4), (13, 11, 20))
    d = ImageDraw.Draw(small)
    d.ellipse((-40, -55, 130, 90), fill=accent)
    d.ellipse((155, 20, 275, 130), fill=(238, 127, 168))
    d.ellipse((-30, h // 4 - 90, 110, h // 4 + 40), fill=(238, 127, 168))
    d.ellipse((140, h // 8, 290, h // 8 + 150), fill=accent)
    glow = small.filter(ImageFilter.GaussianBlur(26)).resize(size, Image.BICUBIC)
    base = Image.blend(base, glow, 0.33)
    stars = ImageDraw.Draw(base)
    rng = random.Random(7)
    for _ in range(int(90 * h / 282)):
        x, y = rng.randrange(w), rng.randrange(h)
        shade = rng.randrange(110, 255)
        r = rng.choice((0, 0, 0, 1))
        stars.ellipse((x - r, y - r, x + r, y + r), fill=(shade, shade, shade))
    return base


def _backdrop(size, accent, background: bytes = None) -> Image.Image:
    w, h = size
    if not background:
        card = _sky(size, accent).convert("RGBA")
    else:
        picture = Image.open(io.BytesIO(background)).convert("RGB")
        # The whole length: the picture stretched to cover, blurred (it's
        # being blown up anyway, and the rows need a calm surface) and dimmed.
        back = ImageOps.fit(picture, (w // 3, h // 3), Image.LANCZOS)
        back = back.filter(ImageFilter.GaussianBlur(5)).resize(size, Image.BICUBIC)
        back = Image.blend(back, Image.new("RGB", size, (10, 8, 18)), 0.45)
        # The top: the same picture sharp, fading out into the blur.
        band = ImageOps.fit(picture, (w, 300), Image.LANCZOS)
        fade = Image.linear_gradient("L").rotate(180).resize((w, 300))
        back.paste(band, (0, 0), fade)
        card = back.convert("RGBA")
    # A shade over everything, deepest at the bottom, so every row reads.
    shade = Image.linear_gradient("L").resize(size).point(lambda v: 40 + v * 70 // 255)
    dark = Image.new("RGBA", size, (8, 6, 14, 0))
    dark.putalpha(shade)
    card = Image.alpha_composite(card, dark)
    # And a soft shade behind the header, so its text reads on a bright picture.
    scrim = Image.linear_gradient("L").rotate(180).resize((w, 170)).point(lambda v: v * 150 // 255)
    top = Image.new("RGBA", (w, 170), (8, 6, 14, 0))
    top.putalpha(scrim)
    card.alpha_composite(top)
    return card


# ------------------------------------------------------------ pieces

def _layer(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _circle(image: bytes, size: int) -> Image.Image:
    try:
        face = Image.open(io.BytesIO(image)).convert("RGB")
        face = ImageOps.fit(face, (size, size), Image.LANCZOS)
    except Exception:
        face = Image.new("RGB", (size, size), (44, 38, 66))
    out = face.convert("RGBA")
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4, size * 4), fill=255)
    out.putalpha(mask.resize((size, size), Image.LANCZOS))
    return out


def _ringed(card, image: bytes, centre, size: int, ring, width: int = 5):
    """An avatar in a ring, anti-aliased by drawing the ring big and
    shrinking it."""
    x, y = centre
    outer = size + width * 2
    big = Image.new("RGBA", (outer * 4, outer * 4), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, outer * 4, outer * 4), fill=ring + (255,))
    ring_img = big.resize((outer, outer), Image.LANCZOS)
    card.alpha_composite(ring_img, (x - outer // 2, y - outer // 2))
    card.alpha_composite(_circle(image, size), (x - size // 2, y - size // 2))


def _fit(draw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def hours(seconds: int) -> str:
    """Time in voice, short: 45h, 3.5h, 20m."""
    if seconds >= 36000:
        return f"{seconds // 3600:,}h"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h".replace(".0h", "h")
    return f"{seconds // 60}m"


def stats(entry) -> str:
    """Messages and voice time, for under the XP."""
    return f"{entry.get('messages', 0):,} msgs · {hours(entry.get('voice', 0))} voice"


def _name(entry) -> str:
    return drawable(entry["name"]) or drawable(entry.get("fallback", "")) or "member"


def _glow(card, centre, radius: int, colour, strength: int = 120):
    w, h = card.size
    layer = Image.new("RGBA", (w // 4, h // 4), colour + (0,))
    x, y, r = centre[0] // 4, centre[1] // 4, radius // 4
    ImageDraw.Draw(layer).ellipse((x - r, y - r, x + r, y + r), fill=colour + (strength,))
    layer = layer.filter(ImageFilter.GaussianBlur(max(2, r // 2))).resize(card.size, Image.BICUBIC)
    card.alpha_composite(layer)


def _crown(draw, cx: int, base_y: int, colour):
    """A little crown sitting on the top of the first place avatar."""
    w, h = 46, 28
    left, right, top = cx - w // 2, cx + w // 2, base_y - h
    points = [(left, base_y), (left, top + 10), (left + 11, top + 18), (cx, top),
              (right - 11, top + 18), (right, top + 10), (right, base_y)]
    draw.polygon(points, fill=colour)
    for px in (left, cx, right):
        py = top + 10 if px != cx else top
        draw.ellipse((px - 4, py - 4, px + 4, py + 4), fill=colour)
    draw.rectangle((left, base_y - 5, right, base_y), fill=tuple(int(c * 0.8) for c in colour))


# ------------------------------------------------------------ the board

def render(title: str, entries: list, accent_hex: int, background: bytes = None,
           icon: bytes = None, page: int = 1, pages: int = 1, footer: str = "",
           subtitle: str = "LEVEL LEADERBOARD") -> bytes:
    """entries: dicts of place, name, fallback, avatar (bytes), level,
    into, needed, xp. The first page puts places 1-3 on the podium."""
    accent = _rgb(accent_hex)
    podium = page == 1 and bool(entries) and entries[0]["place"] == 1
    size = (WIDTH, height_for(len(entries), podium))
    card = _backdrop(size, accent, background)

    # ---- header
    icon_size = 84
    icx, icy = MARGIN + 14 + icon_size // 2, 30 + icon_size // 2
    if icon:
        _ringed(card, icon, (icx, icy), icon_size, accent, 4)
    else:
        _ringed(card, b"", (icx, icy), icon_size, accent, 4)
        d = ImageDraw.Draw(card)
        d.text((icx, icy), (drawable(title)[:1] or "P").upper(), font=_font(40),
               fill=WHITE, anchor="mm")
    draw = ImageDraw.Draw(card)
    tx = icx + icon_size // 2 + 26
    draw.text((tx, 38), subtitle, font=_font(17), fill=accent)
    shown = drawable(title) or "this server"
    draw.text((tx, 60), _fit(draw, shown, _font(40), WIDTH - tx - 190), font=_font(40),
              fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    if pages > 1:
        label = f"PAGE {page} / {pages}"
        lw = draw.textlength(label, font=_font(17))
        pill = _layer(size)
        ImageDraw.Draw(pill).rounded_rectangle(
            (WIDTH - MARGIN - lw - 36, 44, WIDTH - MARGIN - 6, 78), 17,
            fill=(255, 255, 255, 26), outline=(255, 255, 255, 46), width=1)
        card.alpha_composite(pill)
        draw = ImageDraw.Draw(card)
        draw.text((WIDTH - MARGIN - 21, 61), label, font=_font(17), fill=DIM, anchor="rm")
    # A hairline under the header, brightest in the middle.
    line = Image.linear_gradient("L").resize((WIDTH - MARGIN * 2, 1))
    line = line.point(lambda v: int(90 * (1 - abs(v - 127.5) / 127.5)))
    hair = Image.new("RGBA", line.size, accent + (0,))
    hair.putalpha(line)
    card.alpha_composite(hair, (MARGIN, HEADER - 20))

    y = HEADER
    listed = entries
    if podium:
        _podium(card, entries[:3], accent, y)
        y += PODIUM
        listed = entries[3:]

    # ---- rows
    panels, tracks = _layer(size), _layer(size)
    pd, td = ImageDraw.Draw(panels), ImageDraw.Draw(tracks)
    bar_x, bar_w = 172, 270
    for n, entry in enumerate(listed):
        top = y + n * (ROW + GAP)
        pd.rounded_rectangle((MARGIN, top, WIDTH - MARGIN, top + ROW), 18,
                             fill=(14, 11, 26, 168), outline=(255, 255, 255, 22), width=1)
        pd.rounded_rectangle((MARGIN + 10, top + 10, MARGIN + 62, top + ROW - 10), 12,
                             fill=(255, 255, 255, 20))
        td.rounded_rectangle((bar_x, top + 42, bar_x + bar_w, top + 50), 4,
                             fill=(255, 255, 255, 30))
    card.alpha_composite(panels)
    card.alpha_composite(tracks)
    draw = ImageDraw.Draw(card)
    for n, entry in enumerate(listed):
        top = y + n * (ROW + GAP)
        mid = top + ROW // 2
        draw.text((MARGIN + 36, mid), f"{entry['place']}", font=_font(24),
                  fill=WHITE, anchor="mm")
        _ringed(card, entry["avatar"], (MARGIN + 104, mid), 44, (54, 48, 80), 2)
        draw = ImageDraw.Draw(card)
        draw.text((bar_x, top + 12), _fit(draw, _name(entry), _font(24), 300),
                  font=_font(24), fill=WHITE)
        share = max(0.0, min(1.0, entry["into"] / entry["needed"] if entry["needed"] else 1))
        if share > 0:
            draw.rounded_rectangle((bar_x, top + 42, bar_x + max(8, int(bar_w * share)), top + 50),
                                   4, fill=accent)
        draw.text((bar_x + bar_w + 14, top + 46), f"{int(share * 100)}%", font=_font(15),
                  fill=FAINT, anchor="lm")
        # Right side: total XP, then the level in a pill of the server's colour.
        level = f"LVL {entry['level']}"
        lw = draw.textlength(level, font=_font(20))
        pill_r = WIDTH - MARGIN - 14
        pill_l = pill_r - lw - 30
        draw.rounded_rectangle((pill_l, mid - 17, pill_r, mid + 17), 17, fill=accent)
        draw.text(((pill_l + pill_r) // 2, mid), level, font=_font(20), fill=(16, 12, 26),
                  anchor="mm", stroke_width=1, stroke_fill=(16, 12, 26))
        draw.text((pill_l - 18, mid - 11), f"{entry['xp']:,} XP", font=_font(20), fill=WHITE,
                  anchor="rm")
        draw.text((pill_l - 18, mid + 13), stats(entry), font=_font(16), fill=FAINT,
                  anchor="rm")

    # ---- footer
    if footer:
        fy = size[1] - FOOTER // 2 - 4
        draw.text((WIDTH // 2, fy), footer, font=_font(19), fill=DIM, anchor="mm")

    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _podium(card, top3: list, accent, y: int):
    """First in the middle and raised, second on the left, third on the
    right, each on a glass plinth lit in its medal's colour."""
    slots = {1: (WIDTH // 2, 0, 272, 132), 2: (WIDTH // 2 - 290, 40, 250, 104),
             3: (WIDTH // 2 + 290, 40, 250, 104)}
    for entry in top3:
        place = entry["place"]
        if place not in slots:
            continue
        cx, lift, width, face = slots[place]
        metal = MEDALS[place]
        top = y + 8 + lift
        bottom = y + PODIUM - 24
        left, right = cx - width // 2, cx + width // 2
        if place == 1:
            _glow(card, (cx, top + 86), 150, GOLD, 90)
        # The plinth: glass, with the medal's colour rising from the bottom.
        plinth = _layer(card.size)
        ImageDraw.Draw(plinth).rounded_rectangle(
            (left, top + face // 2, right, bottom), 24,
            fill=(14, 11, 26, 178), outline=metal + (90,), width=2)
        card.alpha_composite(plinth)
        tint = Image.linear_gradient("L").resize((width - 4, bottom - top - face // 2 - 4))
        tint = tint.point(lambda v: v * 60 // 255)
        wash = Image.new("RGBA", tint.size, metal + (0,))
        wash.putalpha(tint)
        mask = Image.new("L", tint.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, tint.size[0] - 1, tint.size[1] - 1),
                                               22, fill=255)
        wash.putalpha(Image.composite(tint, Image.new("L", tint.size, 0), mask))
        card.alpha_composite(wash, (left + 2, top + face // 2 + 2))

        # The avatar, half over the top of its plinth.
        acy = top + face // 2
        _ringed(card, entry["avatar"], (cx, acy), face, metal, 6 if place == 1 else 5)
        draw = ImageDraw.Draw(card)
        if place == 1:
            _crown(draw, cx, acy - face // 2 - 6, GOLD)
        # The place, in a medal on the ring.
        badge = 38 if place == 1 else 32
        by = acy + face // 2 - 4
        draw.ellipse((cx - badge // 2 - 3, by - badge // 2 - 3, cx + badge // 2 + 3,
                      by + badge // 2 + 3), fill=(14, 11, 26))
        draw.ellipse((cx - badge // 2, by - badge // 2, cx + badge // 2, by + badge // 2),
                     fill=metal)
        draw.text((cx, by), str(place), font=_font(22 if place == 1 else 19),
                  fill=(20, 16, 30), anchor="mm", stroke_width=1, stroke_fill=(20, 16, 30))

        ny = by + badge // 2 + 14
        big = _font(28 if place == 1 else 24)
        draw.text((cx, ny), _fit(draw, _name(entry), big, width - 30), font=big,
                  fill=WHITE, anchor="ma", stroke_width=1 if place == 1 else 0,
                  stroke_fill=WHITE)
        draw.text((cx, ny + (38 if place == 1 else 34)), f"LEVEL {entry['level']}",
                  font=_font(21), fill=metal, anchor="ma")
        draw.text((cx, ny + (66 if place == 1 else 60)), f"{entry['xp']:,} XP",
                  font=_font(17), fill=DIM, anchor="ma")
        draw.text((cx, ny + (90 if place == 1 else 83)), stats(entry),
                  font=_font(15), fill=FAINT, anchor="ma")
