"""What Paper Premium and Premium Plus give a server, in one place.

The dashboard, `$upgrade` and the website all list the perks from here, so
they can't drift apart. The numbers live here too: perks.py, the $dk
cooldown, the gates on each feature and the ranges of the gacha settings
read them rather than keeping their own.

Two plans for a server. Premium is the small one: a few more rolls and
wishes, the level and moderation extras most servers want first, and
Paper's own look. Plus (and Lifetime, which is Plus for good) is the big
one: the whole gacha set the way the server wants it, like Mudae's server
premium and then some, and everything else Paper has.

Nothing a server already set is taken away: a gacha number set before the
ranges came in stays that server's (Database._grandfather_ranges).
"""

# Plans in order. Lifetime is Plus, paid once.
RANK = {"free": 0, "premium": 1, "plus": 2, "lifetime": 2}
PLAN_NAME = {"premium": "Paper Premium", "plus": "Premium Plus"}

# Every gated feature, and the cheapest plan it comes with.
FEATURES = {
    "xp_boosts": "premium",
    "rank_cards": "premium",
    "automod": "premium",
    "profile": "premium",
    "events": "plus",
    "monthly_board": "plus",
    "champions": "plus",
    "staff_report": "plus",
    "warn_punishments": "plus",
    "case_export": "plus",
    "fast_daily": "plus",
    "server_rt": "plus",
    "builder": "plus",
}


def needs(feature: str) -> str:
    """The plan a feature comes with, by name: "Paper Premium" or "Premium Plus"."""
    return PLAN_NAME[FEATURES[feature]]


# Everyone on the server gets these, on top of their own badges and tower
# floors (perks.effective adds them in). Plus replaces Premium's, not adds.
GACHA_PERK = {
    "premium": {"rolls": 2, "wish_slots": 3},
    "plus": {"rolls": 5, "wish_slots": 10, "karuda_percent": 10},
}

# How far each gacha number can be set: (low, high) free, Premium, Plus.
# Plus is the whole range Paper allows, so a Plus server sets its gacha
# exactly how it likes.
SETTING_RANGES = {
    "roll_limit": ((1, 12), (1, 15), (1, 25)),
    "roll_reset_minutes": ((60, 1440), (45, 1440), (15, 1440)),
    "claim_interval_minutes": ((60, 10080), (60, 10080), (15, 10080)),
    "karuda_interval_minutes": ((10, 1440), (5, 1440), (1, 1440)),
    "wish_limit": ((1, 10), (1, 15), (1, 25)),
    "karuda_rate": ((50, 150), (25, 250), (10, 500)),
    "karuda_grab_percent": ((1, 15), (1, 25), (1, 100)),
    "custom_limit": ((0, 50), (0, 200), (0, 2000)),
}


def more_room(key: str, rank: int) -> str:
    """What the plans above this one allow for a setting, or '' if nothing
    more: e.g. "Premium Plus: 1 to 25"."""
    ranges = SETTING_RANGES.get(key)
    if not ranges:
        return ""
    have = ranges[min(rank, 2)]
    better = [f"{PLAN_NAME[plan]}: {low:,} to {high:,}"
              for plan, (low, high) in (("premium", ranges[1]), ("plus", ranges[2]))
              if RANK[plan] > rank and (low, high) != have]
    return "; ".join(better)

# Player Premium: one person's own plan, on every server Paper is in. It
# stacks with a server's Premium. Servers that want everyone on equal terms
# can switch the boosts off (the player_boosts setting); the badge stays.
PLAYER_PERK = {"rolls": 5, "wish_slots": 4, "karuda_percent": 10}
PLAYER_BADGE = "\U0001f48e"
PLAYER_PERKS = [
    f"+{PLAYER_PERK['rolls']} rolls every reset",
    f"+{PLAYER_PERK['wish_slots']} wishlist slots",
    f"+{PLAYER_PERK['karuda_percent']}% karuda from every grab and $dk",
    "$rt: a free claim reset every 20 hours",
    f"A {PLAYER_BADGE} by your name on your profile and harem",
    "Yours on every server with Paper, on top of the server's own Premium",
]

def badge(db, user_id: int) -> str:
    """The Player Premium badge and a space, for in front of a name, or ''.
    Shown on every server, even where the boosts are switched off."""
    return f"{PLAYER_BADGE} " if db.is_player_premium(user_id) else ""


# $dk comes round this often on a Premium server, instead of every 20 hours.
DAILY_COOLDOWN = 10 * 60 * 60

# What a server can set Paper's own profile to (Discord's limits).
NICK_LIMIT = 32
BIO_LIMIT = 190
PICTURE_LIMIT = 8 * 1024 * 1024

# (icon, heading, plan, [perks]) - shown in this order everywhere. Plus has
# everything Premium has, so its groups say only what it adds.
PERK_GROUPS = [
    ("🎲", "Gacha", "premium", [
        f"+{GACHA_PERK['premium']['rolls']} rolls every reset and"
        f" +{GACHA_PERK['premium']['wish_slots']} wishlist slots, for everyone",
        "Set up to 15 rolls and 15 wishes (free servers: 12 and 10)",
    ]),
    ("⭐", "Levels", "premium", [
        "XP boosts for roles and channels, like 1.5x for Boosters",
        "Rank cards with your server's own background, and members' own",
    ]),
    ("🛡️", "Moderation", "premium", [
        "Smarter automod: spam, blocked words, links and shouting",
    ]),
    ("🎨", "Make Paper yours", "premium", [
        "Give Paper its own name, picture, banner and bio on your server",
    ]),
    ("🎲", "Your gacha, your rules", "plus", [
        "Set every gacha number how you like: 1 to 25 rolls, rolls and claims"
        " back as often as every 15 minutes, up to 25 wishes, karuda x0.1 to x5",
        f"+{GACHA_PERK['plus']['rolls']} rolls and +{GACHA_PERK['plus']['wish_slots']}"
        f" wishlist slots for everyone, and +{GACHA_PERK['plus']['karuda_percent']}%"
        " karuda from every grab and $dk",
        "$rt for everyone: a free claim reset every 20 hours",
        f"$dk every {DAILY_COOLDOWN // 3600} hours instead of 20",
        "Server events: bonus rolls, karuda rushes and double XP",
        "Up to 2,000 custom characters",
    ]),
    ("⭐", "Levels and staff", "plus", [
        "A monthly leaderboard alongside the all-time one",
        "Weekly champions: a role for the top chatter and top voice member",
        "A weekly staff report, up to 50 warn punishments, and every case as"
        " a spreadsheet",
    ]),
    ("🏗️", "Server builder", "plus", [
        "Set your whole server up step by step: roles, channels, a staff area,"
        " logs, a how-to-mod forum, and every part of Paper switched on",
    ]),
]


# Premium groups that Plus's own bigger version replaces, so a Plus card
# doesn't list "+2 rolls" beside "+5 rolls".
REPLACED_BY_PLUS = {"Gacha"}


def perk_groups() -> list:
    """The perks as plain data, for the dashboard."""
    return [{"icon": icon, "title": title, "perks": list(lines), "tier": plan,
             "replaced": plan == "premium" and title in REPLACED_BY_PLUS}
            for icon, title, plan, lines in PERK_GROUPS]


def perk_lines(plan: str = None) -> str:
    """The perks as Discord text, one short line per group; one plan's only
    when a plan is named."""
    return "\n".join(f"{icon} **{title}:** " + "; ".join(lines)
                     for icon, title, tier, lines in PERK_GROUPS
                     if plan is None or tier == plan)
