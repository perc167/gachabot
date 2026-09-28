"""The $level card: someone's level, and how they spend their time here.

Wide like the leaderboard (boardcard.py), so Discord shows it big, and drawn
with the same pieces so the two look like a set:

    header   avatar, name, level, place on the server, and the level bar
    tiles    messages (all time, 7 days, today), voice the same, and their
             rank on the server for XP, messages and voice
    bottom   their top text channels and top voice channels, and a chart
             of the last 14 days

The per-day and per-channel numbers come from the activity table, which
started filling in when this card arrived; the all-time totals are older.
"""
import io
import time

from PIL import ImageDraw

from boardcard import (DIM, FAINT, INK, MARGIN, WHITE, _backdrop, _bar, _fit, _glass,
                       _ringed, _shrink, hours)
from rankcard import _font, _rgb, drawable

WIDTH, HEIGHT = 1280, 800
PINK = (238, 127, 168)
SKY = (110, 196, 255)


def _voice_colour(accent) -> tuple:
    """Pink for voice, unless the server's own colour is pink already."""
    close = sum(abs(a - b) for a, b in zip(accent, PINK)) < 150
    return SKY if close else PINK


def _day_label(day: int) -> str:
    return str(time.gmtime(day * 86400).tm_mday)


def render(p: dict, accent_hex: int, background: bytes = None) -> bytes:
    """p: name, username, avatar, level, into, needed, xp, xp_rank,
    msg_total, msg_7d, msg_1d, msg_rank, voice_total, voice_7d, voice_1d,
    voice_rank, text_top [(name, messages)], voice_top [(name, seconds)],
    days [(day, messages, seconds)] oldest first."""
    accent = _rgb(accent_hex)
    voice = _voice_colour(accent)
    size = (WIDTH, HEIGHT)
    card = _backdrop(size, accent, background)
    _header(card, p, accent)
    _tiles(card, p, accent, voice)
    _channels(card, (MARGIN, 438, 628, 596), "TOP TEXT CHANNELS",
              [("#" + n, f"{c:,}", c) for n, c in p["text_top"]], accent,
              "Nothing yet. This fills in as they chat.")
    _channels(card, (MARGIN, 606, 628, HEIGHT - MARGIN), "TOP VOICE CHANNELS",
              [(n, hours(s), s) for n, s in p["voice_top"]], voice,
              "Nothing yet. This fills in as they talk.")
    _chart(card, (648, 438, WIDTH - MARGIN, HEIGHT - MARGIN), p["days"], accent, voice)
    out = io.BytesIO()
    card.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _header(card, p, accent):
    # Glass behind the header too, so it reads on a bright picture.
    _glass(card, (MARGIN, 20, WIDTH - MARGIN, 222), 26, (14, 11, 26, 130),
           (255, 255, 255, 22))
    size = 162
    cx, cy = MARGIN + 22 + size // 2, 121
    _ringed(card, p["avatar"], (cx, cy), size, accent, 6)
    draw = ImageDraw.Draw(card)
    tx = cx + size // 2 + 32
    right = WIDTH - MARGIN - 26

    # Right: the level, big, and their place on the server.
    level = str(p["level"])
    f_big = _font(78)
    lw = draw.textlength(level, font=f_big)
    draw.text((right, 26), "LEVEL", font=_font(22), fill=accent, anchor="ra")
    draw.text((right, 50), level, font=f_big, fill=WHITE, anchor="ra",
              stroke_width=2, stroke_fill=WHITE)
    place = f"#{p['xp_rank']} on the server" if p["xp_rank"] else "not ranked yet"
    draw.text((right, 134), place, font=_font(22), fill=DIM, anchor="ra")

    room = int(right - max(lw, draw.textlength(place, font=_font(22))) - 40 - tx)
    name = drawable(p["name"]) or drawable(p["username"]) or "member"
    f_name, shown = _shrink(draw, name, (56, 50, 44, 38), room)
    draw.text((tx, 44 + (56 - f_name.size) // 2), shown, font=f_name, fill=WHITE,
              stroke_width=1, stroke_fill=WHITE)
    if p["username"] and drawable(p["username"]):
        draw.text((tx, 112), "@" + _fit(draw, drawable(p["username"]), _font(24), room),
                  font=_font(24), fill=DIM)

    # The bar to the next level, with what it means either side.
    share = max(0.0, min(1.0, p["into"] / p["needed"] if p["needed"] else 1))
    draw.text((tx, 160), f"{p['xp']:,} XP", font=_font(23), fill=WHITE)
    draw.text((right, 166), f"{p['into']:,} / {p['needed']:,} to level {p['level'] + 1}",
              font=_font(21), fill=DIM, anchor="ra")
    _bar(card, (tx, 194, right, 212), share, accent)


def _tile(card, box, label, colour):
    _glass(card, box, 22, (14, 11, 26, 176), (255, 255, 255, 26))
    draw = ImageDraw.Draw(card)
    draw.text((box[0] + 24, box[1] + 18), label, font=_font(20), fill=colour)
    return draw


def _tiles(card, p, accent, voice):
    top, bottom = 238, 420
    gap = 16
    w = (WIDTH - MARGIN * 2 - gap * 2) // 3
    boxes = [(MARGIN + n * (w + gap), top, MARGIN + n * (w + gap) + w, bottom)
             for n in range(3)]

    x0, y0, x1, _y1 = boxes[0]
    draw = _tile(card, boxes[0], "MESSAGES", accent)
    draw.text((x0 + 24, y0 + 50), f"{p['msg_total']:,}", font=_font(58), fill=WHITE,
              stroke_width=1, stroke_fill=WHITE)
    _split(draw, x0 + 24, y0 + 130, x1 - 24,
           [("7 days", f"{p['msg_7d']:,}"), ("today", f"{p['msg_1d']:,}")])

    x0, y0, x1, _y1 = boxes[1]
    draw = _tile(card, boxes[1], "VOICE", voice)
    draw.text((x0 + 24, y0 + 50), hours(p["voice_total"]), font=_font(58), fill=WHITE,
              stroke_width=1, stroke_fill=WHITE)
    _split(draw, x0 + 24, y0 + 130, x1 - 24,
           [("7 days", hours(p["voice_7d"])), ("today", hours(p["voice_1d"]))])

    x0, y0, x1, _y1 = boxes[2]
    draw = _tile(card, boxes[2], "SERVER RANK", (255, 204, 77))
    cols = [("XP", p["xp_rank"]), ("MESSAGES", p["msg_rank"]), ("VOICE", p["voice_rank"])]
    cw = (x1 - x0 - 48) / 3
    for n, (label, rank) in enumerate(cols):
        cx = int(x0 + 24 + cw * n + cw / 2)
        draw.text((cx, y0 + 62), f"#{rank}" if rank else "-", font=_font(48),
                  fill=WHITE, anchor="ma", stroke_width=1, stroke_fill=WHITE)
        draw.text((cx, y0 + 124), label, font=_font(18), fill=FAINT, anchor="ma")


def _split(draw, x0, y, x1, pairs):
    """Two small figures side by side under a tile's big number."""
    half = (x1 - x0) // 2
    for n, (label, value) in enumerate(pairs):
        x = x0 + n * half
        draw.text((x, y), value, font=_font(26), fill=WHITE)
        vw = draw.textlength(value, font=_font(26))
        draw.text((x + vw + 10, y + 5), label, font=_font(19), fill=FAINT)


def _channels(card, box, title, rows, colour, empty):
    """A panel listing up to three channels, each with a bar for its share
    of the busiest one."""
    x0, y0, x1, y1 = box
    _glass(card, box, 22, (14, 11, 26, 176), (255, 255, 255, 26))
    draw = ImageDraw.Draw(card)
    draw.text((x0 + 22, y0 + 14), title, font=_font(19), fill=colour)
    draw.text((x1 - 22, y0 + 15), "LAST 30 DAYS", font=_font(16), fill=FAINT, anchor="ra")
    if not rows:
        draw.text(((x0 + x1) // 2, (y0 + y1) // 2 + 14), empty, font=_font(20),
                  fill=FAINT, anchor="mm")
        return
    most = max(amount for _n, _t, amount in rows) or 1
    row_h = (y1 - y0 - 48) // 3
    for n, (name, text, amount) in enumerate(rows[:3]):
        top = y0 + 44 + n * row_h
        bar_right = x0 + 16 + int((x1 - x0 - 32) * amount / most)
        _glass(card, (x0 + 16, top, max(x0 + 40, bar_right), top + row_h - 6), 10,
               tuple(colour) + (46 if n else 70,))
        draw = ImageDraw.Draw(card)
        mid = top + (row_h - 6) // 2
        f = _font(22)
        vw = draw.textlength(text, font=f)
        draw.text((x0 + 30, mid), _fit(draw, drawable(name) or name, f,
                                        int(x1 - x0 - 90 - vw)),
                  font=f, fill=WHITE, anchor="lm")
        draw.text((x1 - 30, mid), text, font=f, fill=DIM, anchor="rm")


def _chart(card, box, days, accent, voice):
    """Messages and voice for each of the last 14 days, as paired bars,
    each scaled to its own busiest day."""
    x0, y0, x1, y1 = box
    _glass(card, box, 22, (14, 11, 26, 176), (255, 255, 255, 26))
    draw = ImageDraw.Draw(card)
    draw.text((x0 + 22, y0 + 14), "LAST 14 DAYS", font=_font(19), fill=WHITE)
    msgs = sum(m for _d, m, _v in days)
    secs = sum(v for _d, _m, v in days)
    legend = [(accent, f"{msgs:,} msgs"), (voice, f"{hours(secs)} voice")]
    lx = x1 - 22
    f = _font(18)
    for colour, text in reversed(legend):
        tw = draw.textlength(text, font=f)
        draw.text((lx, y0 + 16), text, font=f, fill=DIM, anchor="ra")
        draw.rounded_rectangle((lx - tw - 22, y0 + 18, lx - tw - 8, y0 + 32), 4, fill=colour)
        lx -= tw + 40

    left, right = x0 + 22, x1 - 22
    top, bottom = y0 + 58, y1 - 40
    for n in range(4):                                 # faint guide lines
        gy = top + (bottom - top) * n // 3
        _glass(card, (left, gy, right, gy + 1), 0, (255, 255, 255, 18))
    draw = ImageDraw.Draw(card)
    if not msgs and not secs:
        draw.text(((left + right) // 2, (top + bottom) // 2),
                  "The chart starts filling in from today.", font=_font(20),
                  fill=FAINT, anchor="mm")
    most_m = max((m for _d, m, _v in days), default=0) or 1
    most_v = max((v for _d, _m, v in days), default=0) or 1
    slot = (right - left) / max(1, len(days))
    bar = max(4, int(slot * 0.3))
    for n, (day, m, v) in enumerate(days):
        cx = left + slot * n + slot / 2
        for value, most, colour, dx in ((m, most_m, accent, -bar - 1), (v, most_v, voice, 1)):
            if value:
                h = max(4, int((bottom - top) * value / most))
                draw.rounded_rectangle((int(cx + dx), bottom - h, int(cx + dx + bar), bottom),
                                       min(4, bar // 2), fill=colour)
        if n % 2 == len(days) % 2 or n == len(days) - 1:
            draw.text((int(cx), bottom + 10), "today" if n == len(days) - 1 else _day_label(day),
                      font=_font(15), fill=FAINT, anchor="ma")
