"""Badges and tower floors, and the perks they add up to.

Both are karuda sinks that buy small permanent advantages. Everything a
player has earned is folded into one perks dict here, and the places that
care - rolls, claims, grabs, wishes, dailies - ask this module rather than
each knowing about badges and towers separately.

Perks are deliberately small. A stacked-out player rolls about half again as
often as a new one, not ten times.
"""

# key, icon, name, price, description, perks
BADGES = [
    ("collector", "\U0001f4d6", "Collector", 3000,
     "+2 rolls per window", {"rolls": 2}),
    ("prospector", "⛏️", "Prospector", 4000,
     "+4% from every karuda grab", {"grab_percent": 4}),
    ("devoted", "\U0001f496", "Devoted", 3500,
     "+2 wishlist slots", {"wish_slots": 2}),
    ("swift", "⚡", "Swift", 6000,
     "Claim cooldown 15% shorter", {"claim_percent": 15}),
    ("lucky", "\U0001f340", "Lucky", 5000,
     "+15% on your daily drops", {"daily_percent": 15}),
    ("archivist", "\U0001f5c3️", "Archivist", 7500,
     "+1 roll and +2% grab", {"rolls": 1, "grab_percent": 2}),
]

BADGES_BY_KEY = {entry[0]: entry for entry in BADGES}

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
    """Every perk a player currently has, from badges and their tower."""
    owned = db.badges_of(guild_id, user_id)
    badge_perks = [BADGES_BY_KEY[key][5] for key in owned if key in BADGES_BY_KEY]
    player = db.get_player(guild_id, user_id)
    sources = [*badge_perks, tower_perks(player["tower_floor"])]
    if player["soulmate_id"]:
        sources.append(SOULMATE_PERK)
    result = combine(*sources)
    # A claim that costs nothing to wait for would break the claim economy.
    result["claim_percent"] = min(result["claim_percent"], 60)
    return result


def key_multiplier(level: int) -> float:
    """How much a keyed character is worth, as a multiplier."""
    return 1 + KEY_STEP_PERCENT * max(0, min(level, MAX_KEY_LEVEL)) / 100


def bar(done: int, total: int, width: int = 10) -> str:
    """A small progress bar. Kept to blocks so it reads at a glance."""
    filled = 0 if total <= 0 else round(width * done / total)
    return "▰" * filled + "▱" * (width - filled)
