"""Badges and tower floors, and the perks they add up to.

Both are karuda sinks that buy small permanent advantages. Everything a
player has earned is folded into one perks dict here, and the places that
care - rolls, claims, grabs, wishes, dailies - ask this module rather than
each knowing about badges and towers separately.

Perks are deliberately small. A stacked-out player rolls about half again as
often as a new one, not ten times.
"""

import premium

# Badges are seven materials of four levels each, climbed one level at a
# time. A level replaces the one below it rather than stacking on it, so
# Gold III is 9% and not 3+6+9 - which is what the numbers below say, and
# what keeps a maxed player about half again as strong as a new one rather
# than ten times.
#
# Order is the order they are worth buying in, and the price of a level is
# the base times the level, so a material costs ten times its base to max.
LEVELS = 4
ROMAN = ("I", "II", "III", "IV")


class Badge:
    """One material: its levels, its price, and the perk it grants."""

    __slots__ = ("key", "name", "fallback", "base", "perk", "amounts", "blurb")

    def __init__(self, key, name, fallback, base, perk, amounts, blurb):
        self.key = key
        self.name = name
        self.fallback = fallback      # emoji used until the PNG is uploaded
        self.base = base
        self.perk = perk
        self.amounts = amounts        # what each level grants, I to IV
        self.blurb = blurb

    def amount(self, level: int) -> int:
        return self.amounts[max(1, min(level, LEVELS)) - 1]

    def perk_at(self, level: int) -> dict:
        return {self.perk: self.amount(level)} if level else {}

    def price(self, level: int):
        """What the next level costs, or None past the top."""
        if 1 <= level <= LEVELS:
            return self.base * level
        return None

    def total(self) -> int:
        return sum(self.base * n for n in range(1, LEVELS + 1))

    def describe(self, level: int) -> str:
        return f"+{self.amount(level)}{self.blurb}"


BADGES = [
    Badge("paper", "Paper", "\U0001f4c4", 800, "wish_slots",
          (1, 2, 3, 5), " wishlist slots"),
    Badge("iron", "Iron", "\u2699\ufe0f", 1200, "rolls",
          (1, 2, 3, 4), " rolls per window"),
    Badge("gold", "Gold", "\U0001f947", 1800, "grab_percent",
          (3, 6, 9, 12), "% from every karuda grab"),
    Badge("emerald", "Emerald", "\U0001f49a", 2600, "daily_percent",
          (5, 10, 18, 25), "% on your daily drops"),
    Badge("opal", "Opal", "\U0001f52e", 3600, "claim_percent",
          (5, 10, 15, 20), "% off the claim wait"),
    Badge("amethyst", "Amethyst", "\U0001f49c", 5000, "wish_chance",
          (4, 8, 12, 18), "% chance a roll is someone you wished for"),
    Badge("diamond", "Diamond", "\U0001f48e", 7000, "badge_discount",
          (5, 10, 15, 25), "% off every other badge"),
]

BADGES_BY_KEY = {badge.key: badge for badge in BADGES}

# Tower floors, climbed in order. Each is (cost, what it adds).
# Costs rise faster than income does, so the top floors are a long project
# rather than a weekend.
TOWER_FLOORS = [
    (2500, {"rolls": 1}),
    (4000, {"grab_percent": 2}),
    (6500, {"claim_percent": 5}),
    (10000, {"rolls": 1}),
    (16000, {"grab_percent": 3}),
    (25000, {"wish_slots": 3}),
    (40000, {"claim_percent": 7}),
    (65000, {"rolls": 2}),
    (100000, {"grab_percent": 5}),
    (160000, {"daily_percent": 25}),
]

MAX_FLOOR = len(TOWER_FLOORS)

# Naming one character your soulmate is free and reversible, so the perk is
# small - it is a statement, not a build.
SOULMATE_PERK = {"grab_percent": 5, "daily_percent": 5}

# What each key level adds to a character's worth, for whoever owns them.
KEY_STEP_PERCENT = 15
MAX_KEY_LEVEL = 5

EMPTY = {
    "rolls": 0,
    "grab_percent": 0,
    "claim_percent": 0,
    "wish_slots": 0,
    "daily_percent": 0,
    "karuda_percent": 0,
    # How often a roll is pulled from your own wishlist, and what comes off
    # the price of every other badge. Both arrived with the levelled badges.
    "wish_chance": 0,
    "badge_discount": 0,
}


def floor_cost(floor: int):
    """What it costs to climb to `floor`. None if there is no such floor."""
    if 1 <= floor <= MAX_FLOOR:
        return TOWER_FLOORS[floor - 1][0]
    return None


def floor_perk(floor: int) -> dict:
    if 1 <= floor <= MAX_FLOOR:
        return TOWER_FLOORS[floor - 1][1]
    return {}


def describe(perks: dict) -> str:
    """Perks as a short readable line."""
    parts = []
    if perks.get("rolls"):
        parts.append(f"+{perks['rolls']} rolls")
    if perks.get("grab_percent"):
        parts.append(f"+{perks['grab_percent']}% grab")
    if perks.get("claim_percent"):
        parts.append(f"-{perks['claim_percent']}% claim wait")
    if perks.get("wish_slots"):
        parts.append(f"+{perks['wish_slots']} wishes")
    if perks.get("daily_percent"):
        parts.append(f"+{perks['daily_percent']}% daily")
    if perks.get("karuda_percent"):
        parts.append(f"+{perks['karuda_percent']}% karuda")
    if perks.get("wish_chance"):
        parts.append(f"+{perks['wish_chance']}% wish rolls")
    if perks.get("badge_discount"):
        parts.append(f"-{perks['badge_discount']}% badge prices")
    return " · ".join(parts) or "nothing yet"


def combine(*sources) -> dict:
    total = dict(EMPTY)
    for source in sources:
        for key, value in (source or {}).items():
            if key in total:
                total[key] += value
    return total


def tower_perks(floor: int) -> dict:
    """Everything the climb so far has granted, cumulatively."""
    return combine(*(floor_perk(n) for n in range(1, min(floor, MAX_FLOOR) + 1)))


def effective(db, guild_id: int, user_id: int) -> dict:
    """Every perk a player currently has, from badges, their tower, and
    the server's Premium."""
    owned = db.badge_levels(guild_id, user_id)
    badge_perks = [BADGES_BY_KEY[key].perk_at(level)
                   for key, level in owned.items() if key in BADGES_BY_KEY]
    player = db.get_player(guild_id, user_id)
    sources = [*badge_perks, tower_perks(player["tower_floor"])]
    if player["soulmate_id"]:
        sources.append(SOULMATE_PERK)
    if db.is_premium(guild_id):
        sources.append(premium.GACHA_PERK)
    result = combine(*sources)
    # A claim that costs nothing to wait for would break the claim economy.
    result["claim_percent"] = min(result["claim_percent"], 60)
    # Nor should every roll be a wish, or badges end up free.
    result["wish_chance"] = min(result["wish_chance"], 40)
    result["badge_discount"] = min(result["badge_discount"], 40)
    return result


def badge_price(db, guild_id: int, user_id: int, badge, level: int):
    """What the next level of a badge costs this player, discount included."""
    full = badge.price(level)
    if full is None:
        return None
    # Diamond pays for itself by making everything else cheaper - and it
    # never discounts its own next level, which would compound.
    discount = effective(db, guild_id, user_id)["badge_discount"]
    if badge.key == "diamond":
        discount = 0
    return max(1, round(full * (100 - discount) / 100))


def key_multiplier(level: int) -> float:
    """How much a keyed character is worth, as a multiplier."""
    return 1 + KEY_STEP_PERCENT * max(0, min(level, MAX_KEY_LEVEL)) / 100


def bar(done: int, total: int, width: int = 10) -> str:
    """A small progress bar. Kept to blocks so it reads at a glance."""
    filled = 0 if total <= 0 else round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)
