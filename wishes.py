"""Wish slots, starwishes, and how wishes tilt your rolls, Mudae style.

Slots
    Everyone has the server's wish_limit (8 by default), plus slots bought in
    the shop, from badges and from Premium. A wish uses one. Starwishes cost
    more each time, like Mudae's: the first uses 2 slots, the second 4 more,
    the third 6 more (star_cost). A starwish doesn't need the character
    wished first; if they were, the plain wish is folded into it.

Rolls
    Each roll first has a chance of landing on one of your own unclaimed
    wishes that fit the roll ($w only turns up women you wished for). The
    chance is your tickets over WISH_POOL: a wish is one ticket and a
    starwish STAR_WEIGHT, so 8 wishes land about 1 roll in 250 and a
    starwish is five times as likely as any one wish. Which one it lands on
    is picked by the same weights. Otherwise the roll is an ordinary one.

    Mudae's own formula divides by the whole roster, which on a hundred
    thousand characters makes a wish land once in tens of thousands of
    rolls; WISH_POOL keeps the shape and makes it something people notice.
"""
import random

import perks

STAR_WEIGHT = 5          # a starwish is this many wishes' worth of tickets
WISH_POOL = 2000         # tickets over this is the chance a roll is a wish
MOST_OFTEN = 0.25        # never more than one roll in four, however many


def star_cost(count: int) -> int:
    """Slots used by this many starwishes: 2, then 4 more, then 6 more..."""
    return count * (count + 1)


def next_star_cost(count: int) -> int:
    """Slots the next starwish would take, with `count` already."""
    return 2 * (count + 1)


def capacity(db, guild_id: int, user_id: int) -> int:
    return (db.get_setting(guild_id, "wish_limit")
            + db.get_player(guild_id, user_id)["extra_wish_slots"]
            + perks.effective(db, guild_id, user_id)["wish_slots"])


def used(db, guild_id: int, user_id: int) -> int:
    return (db.wish_count(guild_id, user_id)
            + star_cost(db.starwish_count(guild_id, user_id)))


def room(db, guild_id: int, user_id: int) -> int:
    """Free slots right now (can be below 0 after the limit is lowered)."""
    return capacity(db, guild_id, user_id) - used(db, guild_id, user_id)


def chance(tickets: float) -> float:
    return min(MOST_OFTEN, tickets / WISH_POOL)


def boosted_roll(db, guild_id: int, user_id: int, gender: str = None,
                 kind: str = None, rng=random):
    """One of your own wishes, if this roll lands on one; else None."""
    candidates = db.wish_candidates(guild_id, user_id, gender=gender, kind=kind)
    if not candidates:
        return None
    star = STAR_WEIGHT * (100 + perks.effective(db, guild_id, user_id)["star_boost"]) / 100
    weights = [star if starred else 1 for _row, starred in candidates]
    if rng.random() >= chance(sum(weights)):
        return None
    return rng.choices([row for row, _starred in candidates], weights=weights, k=1)[0]
