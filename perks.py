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

    __slots__ = ("key", "name", "fallback", "base", "perk", "amounts",
                 "blurb", "unlock")

    def __init__(self, key, name, fallback, base, perk, amounts, blurb,
                 unlock=0):
        self.key = key
        self.name = name
        self.fallback = fallback      # emoji used until the PNG is uploaded
        self.base = base
        self.perk = perk
        self.amounts = amounts        # what each level grants, I to IV
        self.blurb = blurb
        # 0 is on the shelf from the start. 1, 2 and 3 need the three
        # starters at that level first, so the later materials are something
        # to work towards rather than a wall of prices on day one.
        self.unlock = unlock

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
        amount = self.amount(level)
        # "+1 rolls" reads like a typo, so the blurbs carry a {s} the count
        # fills in. Blurbs without one are unaffected.
        return f"+{amount}{self.blurb.format(s='' if amount == 1 else 's')}"


BADGES = [
    Badge("paper", "Paper", "\U0001f4c4", 800, "wish_slots",
          (1, 2, 3, 5), " wishlist slot{s}"),
    Badge("iron", "Iron", "\u2699\ufe0f", 1200, "rolls",
          (1, 2, 3, 4), " roll{s} per window"),
    Badge("gold", "Gold", "\U0001f947", 1800, "grab_percent",
          (3, 6, 9, 12), "% from every karuda grab"),
    Badge("emerald", "Emerald", "\U0001f49a", 2600, "daily_percent",
          (5, 10, 18, 25), "% on your daily drops", unlock=1),
    Badge("opal", "Opal", "\U0001f52e", 3600, "claim_percent",
          (5, 10, 15, 20), "% off the claim wait", unlock=2),
    Badge("amethyst", "Amethyst", "\U0001f49c", 5000, "wish_chance",
          (4, 8, 12, 18), "% chance a roll is someone you wished for",
          unlock=3),
    Badge("diamond", "Diamond", "\U0001f48e", 7000, "badge_discount",
          (5, 10, 15, 25), "% off every other badge"),
]

BADGES_BY_KEY = {badge.key: badge for badge in BADGES}

# The three anybody can buy from the start, which the locked ones are
# measured against.
STARTERS = [badge.key for badge in BADGES if badge.unlock == 0][:3]


def unlocked(levels: dict, badge) -> bool:
    """Is this badge on the shelf for a player at these levels?

    Two ways in, as in Mudae: the three starters at the badge's own tier, or
    any two badges already maxed - so a player who went deep on two things
    is not shut out for having skipped a third.
    """
    if not badge.unlock:
        return True
    if all(levels.get(key, 0) >= badge.unlock for key in STARTERS):
        return True
    return sum(1 for level in levels.values() if level >= LEVELS) >= 2


def requirement(badge) -> str:
    """What it would take, written the way the badge list shows it."""
    if not badge.unlock:
        return ""
    tier = ROMAN[badge.unlock - 1]
    needed = " + ".join(f"{BADGES_BY_KEY[k].name} {tier}" for k in STARTERS)
    return f"{needed} or 2 badges {ROMAN[-1]}"

# The karuda tower, as Mudae builds it ($kt): twelve floors, and each floor
# is a perk you choose, a different one each time. Every floor costs
# FLOOR_STEP more than the last, whichever tower it's in. Build all twelve
# and a new tower starts on top, with every bonus halved again; the cost
# keeps climbing. $destroy pulls the lot down and refunds every karuda.
#
# Mudae's perks are for Mudae's systems. Where Paper has the same thing
# (wish slots, the starwish, rolls) the perk is the same; where it doesn't
# (disable lists, kakera power, reactions) it's the nearest thing Paper has.
#
# number: (what it does at full strength, {perk: amount})
TOWER_PERKS = {
    1: ("+{wish_slots} wishlist slots", {"wish_slots": 2}),
    2: ("Increased spawn chance for your $starwish: +{star_boost}%", {"star_boost": 50}),
    3: ("Claim cooldown -{claim_percent}%", {"claim_percent": 10}),
    4: ("{key_on_wish}% chance to earn a key when you claim one of your wishes",
        {"key_on_wish": 30}),
    5: ("{key_on_claim}% chance to earn a key when you claim anyone", {"key_on_claim": 20}),
    6: ("{extra_key}% chance to earn a 2nd key whenever you earn one", {"extra_key": 10}),
    7: ("Karuda from grabs and $dk increased to {karuda_power}%", {"karuda_percent": 10}),
    8: ("Karuda grabs come back {grab_cooldown}% sooner", {"grab_cooldown": 20}),
    9: ("$dk shards are worth +{daily_percent}%", {"daily_percent": 25}),
    10: ("$dk shows +{daily_offers} extra shard to choose from", {"daily_offers": 1}),
    11: ("+{rolls} roll per window", {"rolls": 1}),
    12: ("$haremcolor unlocked: your own colour on $harem", {"harem_colour": 1}),
}
PER_TOWER = len(TOWER_PERKS)
FLOOR_STEP = 5000


def floor_cost(built: int) -> int:
    """What the next floor costs, with `built` floors up already."""
    return FLOOR_STEP * (built + 1)


def tower_scale(tower: int) -> float:
    """Tower 1 gives the full bonus, tower 2 half, tower 3 a quarter..."""
    return 0.5 ** (max(1, tower) - 1)


def floor_perk(perk: int, tower: int = 1) -> dict:
    """What one floor gives in a given tower. Never rounds a perk to
    nothing: a halved +1 roll is still +1."""
    scale = tower_scale(tower)
    return {key: max(1, round(amount * scale))
            for key, amount in TOWER_PERKS[perk][1].items()}


def perk_text(perk: int, tower: int = 1) -> str:
    template, _base = TOWER_PERKS[perk]
    values = floor_perk(perk, tower)
    values["karuda_power"] = 100 + values.get("karuda_percent", 0)
    return template.format(**values)


def tower_layout(rows) -> tuple:
    """(the tower being built now, perks already in it, floors in total)
    from a player's tower_floors rows."""
    total = len(rows)
    tower = total // PER_TOWER + 1
    built = {r["perk"] for r in rows if r["tower"] == tower}
    return tower, built, total


def tower_perks(rows) -> dict:
    """Everything every floor of every tower adds up to."""
    return combine(*(floor_perk(r["perk"], r["tower"]) for r in rows))


# Floors per tower, for progress bars.
MAX_FLOOR = PER_TOWER


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
    # From the tower's chosen floors.
    "star_boost": 0,
    "key_on_wish": 0,
    "key_on_claim": 0,
    "extra_key": 0,
    "grab_cooldown": 0,
    "daily_offers": 0,
    "harem_colour": 0,
}


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
    if perks.get("star_boost"):
        parts.append(f"+{perks['star_boost']}% starwish")
    if perks.get("key_on_wish") or perks.get("key_on_claim"):
        parts.append("keys from claims")
    if perks.get("extra_key"):
        parts.append(f"{perks['extra_key']}% double keys")
    if perks.get("grab_cooldown"):
        parts.append(f"-{perks['grab_cooldown']}% grab wait")
    if perks.get("daily_offers"):
        parts.append(f"+{perks['daily_offers']} $dk shard")
    if perks.get("harem_colour"):
        parts.append("harem colour")
    return " · ".join(parts) or "nothing yet"


def combine(*sources) -> dict:
    total = dict(EMPTY)
    for source in sources:
        for key, value in (source or {}).items():
            if key in total:
                total[key] += value
    return total


def player_boosts(db, guild_id: int, user_id: int) -> bool:
    """Does this player's own Player Premium count on this server?"""
    return (db.is_player_premium(user_id)
            and bool(db.get_setting(guild_id, "player_boosts")))


def effective(db, guild_id: int, user_id: int) -> dict:
    """Every perk a player currently has, from badges, their tower, the
    server's Premium and their own Player Premium."""
    owned = db.badge_levels(guild_id, user_id)
    badge_perks = [BADGES_BY_KEY[key].perk_at(level)
                   for key, level in owned.items() if key in BADGES_BY_KEY]
    player = db.get_player(guild_id, user_id)
    sources = [*badge_perks, tower_perks(db.tower_floors_of(guild_id, user_id))]
    if player["soulmate_id"]:
        sources.append(SOULMATE_PERK)
    plan = db.plan_rank(guild_id)
    if plan:
        sources.append(premium.GACHA_PERK["plus" if plan >= 2 else "premium"])
    if player_boosts(db, guild_id, user_id):
        sources.append(premium.PLAYER_PERK)
    result = combine(*sources)
    # A claim that costs nothing to wait for would break the claim economy.
    result["claim_percent"] = min(result["claim_percent"], 60)
    # Nor should every roll be a wish, or badges end up free.
    result["wish_chance"] = min(result["wish_chance"], 40)
    result["badge_discount"] = min(result["badge_discount"], 40)
    result["grab_cooldown"] = min(result["grab_cooldown"], 60)
    for key in ("key_on_wish", "key_on_claim", "extra_key"):
        result[key] = min(result[key], 100)
    result["daily_offers"] = min(result["daily_offers"], 3)
    return result


def earn_keys(db, guild_id: int, user_id: int, amount: int = 1, rng=None) -> tuple:
    """Give keys, with the tower's chance of a 2nd. Returns (given, held)."""
    import random
    rng = rng or random
    if amount > 0 and rng.random() * 100 < effective(db, guild_id, user_id)["extra_key"]:
        amount += 1
    return amount, db.add_keys(guild_id, user_id, amount)


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
