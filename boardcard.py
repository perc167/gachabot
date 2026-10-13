"""The level leaderboard as a picture: the image $leaderboard sends.

Wide rather than tall, on purpose: Discord shrinks a picture until it fits
a box about 550 by 350 in the chat, so a tall one comes out tiny and a wide
one fills the width. Every page is WIDTH by HEIGHT, with the text sized to
read at that scale.

Built in layers, back to front:

1. The backdrop. The server's rank card background (or the free night sky),
   sharp across the top and fading into a blurred, darkened copy below, so
   the text reads on any picture.
2. The header: the server's icon in a ring of its colour, its name, the page,
   and where the person who asked stands.
3. Page one: the top three as medal cards down the left (gold with a crown
   and a glow, then silver and bronze), and places 4-10 down the right.
   Later pages: two columns of five.
4. Every row: place, avatar, name, XP, messages, hours in voice, a bar for
   how far into their level they are, and their level.

Plain Pillow with the font Pillow carries, like rankcard.py, so it sits
well next to the $level card.
"""
import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from rankcard import _font, _rgb, drawable

WIDTH, HEIGHT = 1280, 800
MARGIN = 36
HEADER = 126
TOP = HEADER + 4                    # where the medal cards and rows start
BOTTOM = HEIGHT - MARGIN

GOLD = (255, 204, 77)
SILVER = (206, 214, 232)
BRONZE = (222, 142, 92)
MEDALS = {1: GOLD, 2: SILVER, 3: BRONZE}
PLACES = {1: "1ST PLACE", 2: "2ND PLACE", 3: "3RD PLACE"}
WHITE, DIM, FAINT = (236, 243, 245), (160, 182, 188), (104, 124, 130)
INK = (10, 15, 18)


def hours(seconds: int) -> str:
    """Time in voice, short: 45h, 3.5h, 20m."""
    if seconds >= 36000:
        return f"{seconds // 3600:,}h"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h".replace(".0h", "h")
    return f"{seconds // 60}m"


def stats(entry, short: bool = False) -> str:
    """Messages and voice time."""
    return (f"{entry.get('messages', 0):,} msgs · {hours(entry.get('voice', 0))}"
            + (" vc" if short else " voice"))


# ------------------------------------------------------------ the backdrop

def _sky(size, accent) -> Image.Image:
    """The free background: the rank card's night sky, stretched to fit."""
    w, h = size
    fx, fy = w / 934, h / 800
    base = Image.new("RGB", size, (8, 11, 13))
    # Glows are soft, so they're drawn small and blown up: far quicker than
    # blurring the full-size picture.
    small = Image.new("RGB", (w // 4, h // 4), (8, 11, 13))
    d = ImageDraw.Draw(small)

    def oval(box, fill):
        x0, y0, x1, y1 = box
        d.ellipse((x0 * fx, y0 * fy, x1 * fx, y1 * fy), fill=fill)
    oval((-40, -55, 130, 90), accent)
    oval((155, 20, 275, 130), (110, 175, 235))
    oval((-30, 110, 110, 240), (110, 175, 235))
    oval((140, 100, 290, 250), accent)
    glow = small.filter(ImageFilter.GaussianBlur(26)).resize(size, Image.BICUBIC)
    base = Image.blend(base, glow, 0.33)
    stars = ImageDraw.Draw(base)
    rng = random.Random(7)
    for _ in range(int(90 * w * h / (934 * 282))):
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
        back = ImageOps.fit(picture, (w // 3, h // 3), Image.LANCZOS)
        back = back.filter(ImageFilter.GaussianBlur(5)).resize(size, Image.BICUBIC)
        back = Image.blend(back, Image.new("RGB", size, (10, 8, 18)), 0.45)
        band = ImageOps.fit(picture, (w, 320), Image.LANCZOS)
        fade = Image.linear_gradient("L").rotate(180).resize((w, 320))
        back.paste(band, (0, 0), fade)
        card = back.convert("RGBA")
    shade = Image.linear_gradient("L").resize(size).point(lambda v: 40 + v * 70 // 255)
    dark = Image.new("RGBA", size, (8, 6, 14, 0))
    dark.putalpha(shade)
    card = Image.alpha_composite(card, dark)
    # A soft shade behind the header, so its text reads on a bright picture.
    scrim = Image.linear_gradient("L").rotate(180).resize((w, 180)).point(lambda v: v * 150 // 255)
    top = Image.new("RGBA", (w, 180), (8, 6, 14, 0))
    top.putalpha(scrim)
    card.alpha_composite(top)
    return card


# ------------------------------------------------------------ pieces

def _layer(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def _glass(card, box, radius: int, fill, outline=None, width: int = 1):
    """A see-through panel. Drawn on its own layer: straight onto the
    card, its transparency would be lost."""
    layer = _layer(card.size)
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=fill, outline=outline,
                                            width=width)
    card.alpha_composite(layer)


def _circle(image: bytes, size: int) -> Image.Image:
    try:
        face = Image.open(io.BytesIO(image)).convert("RGB")
        face = ImageOps.fit(face, (size, size), Image.LANCZOS)
    except Exception:
        face = Image.new("RGB", (size, size), (26, 37, 42))
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
    ImageDraw.Draw(big).ellipse((0, 0, outer * 4, outer * 4), fill=tuple(ring) + (255,))
    card.alpha_composite(big.resize((outer, outer), Image.LANCZOS),
                         (int(x - outer / 2), int(y - outer / 2)))
    card.alpha_composite(_circle(image, size), (int(x - size / 2), int(y - size / 2)))


def _fit(draw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def _shrink(draw, text: str, sizes, width: int):
    """(font, text): the biggest of sizes the text fits in, or the smallest
    with the text cut short."""
    for size in sizes:
        font = _font(size)
        if draw.textlength(text, font=font) <= width:
            return font, text
    font = _font(sizes[-1])
    return font, _fit(draw, text, font, width)


def _name(entry) -> str:
    return drawable(entry["name"]) or drawable(entry.get("fallback", "")) or "member"


def _share(entry) -> float:
    return max(0.0, min(1.0, entry["into"] / entry["needed"] if entry["needed"] else 1))


def _bar(card, box, share: float, colour):
    x0, y0, x1, y1 = box
    r = (y1 - y0) // 2
    _glass(card, box, r, (255, 255, 255, 34))
    if share > 0:
        end = x0 + max(y1 - y0, int((x1 - x0) * share))
        ImageDraw.Draw(card).rounded_rectangle((x0, y0, end, y1), r, fill=colour)


def _glow(card, centre, radius: int, colour, strength: int = 120):
    w, h = card.size
    layer = Image.new("RGBA", (w // 4, h // 4), tuple(colour) + (0,))
    x, y, r = centre[0] // 4, centre[1] // 4, radius // 4
    ImageDraw.Draw(layer).ellipse((x - r, y - r, x + r, y + r),
                                  fill=tuple(colour) + (strength,))
    layer = layer.filter(ImageFilter.GaussianBlur(max(2, r // 2))).resize(card.size, Image.BICUBIC)
    card.alpha_composite(layer)


def _crown(draw, cx: int, base_y: int, colour):
    """A little crown sitting on top of the first place avatar."""
    w, h = 56, 32
    left, right, top = cx - w // 2, cx + w // 2, base_y - h
    draw.polygon([(left, base_y), (left, top + 11), (left + 14, top + 20), (cx, top),
                  (right - 14, top + 20), (right, top + 11), (right, base_y)], fill=colour)
    for px, py in ((left, top + 11), (cx, top), (right, top + 11)):
        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=colour)
    draw.rectangle((left, base_y - 6, right, base_y), fill=tuple(int(c * 0.8) for c in colour))


# ------------------------------------------------------------ the board

def render(title: str, entries: list, accent_hex: int, background: bytes = None,
           icon: bytes = None, page: int = 1, pages: int = 1, footer: str = "",
           subtitle: str = "LEVEL LEADERBOARD") -> bytes:
    """entries: dicts of place, name, fallback, avatar (bytes), level, into,
    needed, xp, messages, voice (seconds). Ten to a page; the first page
    puts places 1-3 on medal cards."""
    accent = _rgb(accent_hex)
    size = (WIDTH, HEIGHT)
    card = _backdrop(size, accent, background)
    _header(card, title, accent, icon, page, pages, footer, subtitle)

    podium = page == 1 and bool(entries) and entries[0]["place"] == 1
    if podium:
        medals = entries[:3]
        heights = {1: 250, 2: 182, 3: 182}
        y = TOP
        for entry in medals:
            h = heights[entry["place"]]
            _medal_card(card, (MARGIN, y, MARGIN + 520, y + h), entry)
            y += h + 10
        rest = entries[3:]
        left = MARGIN + 520 + 26
        _rows(card, rest, (left, TOP, WIDTH - MARGIN, BOTTOM), 7, accent)
        if not rest:
            ImageDraw.Draw(card).text(((left + WIDTH - MARGIN) // 2, (TOP + BOTTOM) // 2),
                                      "More people show up here as they earn XP",
                                      font=_font(24), fill=FAINT, anchor="mm")
    else:
        mid = WIDTH // 2
        _rows(card, entries[:5], (MARGIN, TOP, mid - 8, BOTTOM), 5, accent)
        _rows(card, entries[5:10], (mid + 8, TOP, WIDTH - MARGIN, BOTTOM), 5, accent)

    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _header(card, title, accent, icon, page, pages, footer, subtitle):
    icon_size = 80
    icx, icy = MARGIN + 6 + icon_size // 2, 22 + icon_size // 2
    _ringed(card, icon or b"", (icx, icy), icon_size, accent, 4)
    draw = ImageDraw.Draw(card)
    if not icon:
        draw.text((icx, icy), (drawable(title)[:1] or "P").upper(), font=_font(40),
                  fill=WHITE, anchor="mm")
    tx = icx + icon_size // 2 + 24
    draw.text((tx, 26), subtitle, font=_font(21), fill=accent)
    right_room = 0
    if pages > 1:
        label = f"PAGE {page} / {pages}"
        lw = draw.textlength(label, font=_font(21))
        box = (WIDTH - MARGIN - lw - 40, 24, WIDTH - MARGIN, 62)
        _glass(card, box, 19, (255, 255, 255, 26), (255, 255, 255, 50))
        draw = ImageDraw.Draw(card)
        draw.text((WIDTH - MARGIN - 20, 43), label, font=_font(21), fill=DIM, anchor="rm")
        right_room = lw + 60
    if footer:
        draw.text((WIDTH - MARGIN - 2, 92), footer, font=_font(22), fill=DIM, anchor="rm")
        right_room = max(right_room, draw.textlength(footer, font=_font(22)) + 40)
    big = _font(46)
    draw.text((tx, 52), _fit(draw, drawable(title) or "this server", big,
                             int(WIDTH - MARGIN - right_room - tx)),
              font=big, fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    # A hairline under the header, brightest in the middle.
    line = Image.linear_gradient("L").resize((WIDTH - MARGIN * 2, 1))
    line = line.point(lambda v: int(100 * (1 - abs(v - 127.5) / 127.5)))
    hair = Image.new("RGBA", line.size, accent + (0,))
    hair.putalpha(line)
    card.alpha_composite(hair, (MARGIN, HEADER - 10))


def _medal_card(card, box, entry):
    """One of the top three: avatar in a medal ring, name, level and stats,
    on glass washed with the medal's colour."""
    x0, y0, x1, y1 = box
    place = entry["place"]
    metal = MEDALS[place]
    first = place == 1
    mid = (y0 + y1) // 2 + (8 if first else 0)
    size = 164 if first else 120
    cx = x0 + 30 + size // 2
    if first:
        _glow(card, (cx, mid), 190, GOLD, 90)
    _glass(card, box, 26, (9, 14, 17, 176), tuple(metal) + (110,), 2)
    # The medal's colour washing in from the left.
    wash = Image.linear_gradient("L").rotate(90).resize((x1 - x0 - 4, y1 - y0 - 4))
    wash = wash.point(lambda v: v * 64 // 255)
    mask = Image.new("L", wash.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, wash.size[0] - 1, wash.size[1] - 1), 24,
                                           fill=255)
    tint = Image.new("RGBA", wash.size, tuple(metal) + (0,))
    tint.putalpha(Image.composite(wash, Image.new("L", wash.size, 0), mask))
    card.alpha_composite(tint, (x0 + 2, y0 + 2))

    _ringed(card, entry["avatar"], (cx, mid), size, metal, 7 if first else 5)
    draw = ImageDraw.Draw(card)
    if first:
        _crown(draw, cx, mid - size // 2 - 8, GOLD)
    badge = 46 if first else 38
    bx, by = cx + int(size * 0.36), mid + int(size * 0.36)
    draw.ellipse((bx - badge // 2 - 4, by - badge // 2 - 4, bx + badge // 2 + 4,
                  by + badge // 2 + 4), fill=INK)
    draw.ellipse((bx - badge // 2, by - badge // 2, bx + badge // 2, by + badge // 2),
                 fill=metal)
    draw.text((bx, by), str(place), font=_font(26 if first else 22), fill=INK,
              anchor="mm", stroke_width=1, stroke_fill=INK)

    tx = cx + size // 2 + 30
    room = x1 - 24 - tx
    s = 1.0 if first else 0.84
    f_label, f_name, f_level, f_stats = (_font(int(20 * s)), _font(int(46 * s)),
                                         _font(int(30 * s)), _font(int(23 * s)))
    top = mid - int(80 * s)
    draw.text((tx, top), PLACES[place], font=f_label, fill=metal)
    f_name, shown = _shrink(draw, _name(entry), [int(n * s) for n in (46, 42, 38, 34, 30)], room)
    draw.text((tx, top + int(24 * s) + (int(46 * s) - f_name.size) // 2), shown, font=f_name,
              fill=WHITE, stroke_width=1, stroke_fill=WHITE)
    level = f"LEVEL {entry['level']}"
    ly = top + int(80 * s)
    draw.text((tx, ly), level, font=f_level, fill=metal, stroke_width=1 if first else 0,
              stroke_fill=metal)
    lw = draw.textlength(level, font=f_level)
    draw.text((tx + lw + 14, ly + int(4 * s)), f"{entry['xp']:,} XP", font=f_stats, fill=WHITE)
    draw.text((tx, ly + int(42 * s)), _fit(draw, stats(entry), f_stats, room), font=f_stats,
              fill=DIM)
    by0 = ly + int(78 * s)
    _bar(card, (tx, by0, x1 - 24, by0 + int(10 * s)), _share(entry), metal)


def _rows(card, entries: list, area, slots: int, accent):
    """entries as rows filling `area`, which has room for `slots` of them."""
    x0, y0, x1, y1 = area
    gap = 10 if slots > 5 else 12
    h = (y1 - y0 - gap * (slots - 1)) // slots
    for n, entry in enumerate(entries[:slots]):
        top = y0 + n * (h + gap)
        _row(card, (x0, top, x1, top + h), entry, accent)


def _row(card, box, entry, accent):
    """One row. A short, wide row (page one's right side) puts XP and the
    stats on one line; a tall, narrower one (later pages, two columns) gives
    them a line each, rather than blowing the text up until it won't fit."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    tall = h >= 105
    s = 1.12 if tall else h / 82        # text and pieces scale by this
    mid = (y0 + y1) // 2
    _glass(card, box, int(18 * s), (9, 14, 17, 172), (255, 255, 255, 24))
    # The place, in a little glass square.
    sq = int(54 * s)
    _glass(card, (x0 + 12, mid - sq // 2, x0 + 12 + sq, mid + sq // 2), int(12 * s),
           (255, 255, 255, 22))
    draw = ImageDraw.Draw(card)
    draw.text((x0 + 12 + sq // 2, mid), str(entry["place"]), font=_font(int(30 * s)),
              fill=WHITE, anchor="mm")
    av = int((66 if tall else 58) * s)
    acx = x0 + 12 + sq + 16 + av // 2
    _ringed(card, entry["avatar"], (acx, mid), av, (40, 56, 62), 3)
    draw = ImageDraw.Draw(card)

    # Right: the level, in a pill of the server's colour.
    f_pill = _font(int(27 * s))
    level = f"LVL {entry['level']}"
    pw = draw.textlength(level, font=f_pill) + int(30 * s)
    pr = x1 - int(16 * s)
    pl = pr - pw
    ph = int(40 * s)
    draw.rounded_rectangle((pl, mid - ph // 2, pr, mid + ph // 2), ph // 2, fill=accent)
    draw.text(((pl + pr) // 2, mid), level, font=f_pill, fill=INK, anchor="mm",
              stroke_width=1, stroke_fill=INK)

    # Middle: name, XP, the stats, and how far into the level.
    tx = acx + av // 2 + int(18 * s)
    room = int(pl - int(18 * s) - tx)
    f_xp, f_stats = _font(int(23 * s)), _font(int(21 * s))
    xp = f"{entry['xp']:,} XP"
    f_name, shown = _shrink(draw, _name(entry), [int(n * s) for n in (31, 28, 25)], room)
    if tall:
        # name / XP / stats / bar, centred in the row.
        top = mid - int(50 * s)
        draw.text((tx, top + (int(31 * s) - f_name.size) // 2), shown, font=f_name, fill=WHITE)
        draw.text((tx, top + int(36 * s)), xp, font=f_xp, fill=WHITE)
        draw.text((tx, top + int(63 * s)), _fit(draw, stats(entry, short=True), f_stats, room),
                  font=f_stats, fill=DIM)
        bar_y = top + int(92 * s)
        _bar(card, (tx, bar_y, pl - int(18 * s), bar_y + int(5 * s)), _share(entry), accent)
        return
    draw.text((tx, y0 + int(7 * s) + (int(31 * s) - f_name.size) // 2), shown, font=f_name,
              fill=WHITE)
    line_y = y0 + int(41 * s)
    draw.text((tx, line_y), xp, font=f_xp, fill=WHITE)
    xw = draw.textlength(xp, font=f_xp)
    draw.text((tx + xw + int(12 * s), line_y + int(2 * s)),
              _fit(draw, "· " + stats(entry, short=True), f_stats, int(room - xw - 12 * s)),
              font=f_stats, fill=DIM)
    _bar(card, (tx, y1 - int(12 * s), pl - int(18 * s), y1 - int(7 * s)), _share(entry), accent)
