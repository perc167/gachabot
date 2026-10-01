"""What Paper Premium gives a server, in one place.

The dashboard, `$upgrade` and the website all list the perks from here, so
they can't drift apart. The numbers live here too: perks.py, the $dk
cooldown and the level boosts read them rather than keeping their own.

The rule for Premium: nothing that's free today is ever taken away. It only
adds, and it's what other bots charge more for (Mudae's premium for the
gacha, Arcane's for levels), for less, and for everyone on the server at
once rather than per player.
"""

# Everyone on a Premium server gets these, on top of their own badges and
# tower floors (perks.effective adds them in).
GACHA_PERK = {"rolls": 5, "wish_slots": 10, "karuda_percent": 10}

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

# (icon, heading, [perks]) - shown in this order everywhere.
PERK_GROUPS = [
    ("\U0001f3b2", "Gacha", [
        f"+{GACHA_PERK['rolls']} rolls every reset, for everyone",
        f"+{GACHA_PERK['wish_slots']} wishlist slots each",
        f"+{GACHA_PERK['karuda_percent']}% karuda from every grab and $dk",
        f"$dk every {DAILY_COOLDOWN // 3600} hours instead of 20",
        "Server events: bonus rolls and karuda rushes",
    ]),
    ("⭐", "Levels", [
        "XP boosts for roles and channels, like 1.5x for Boosters",
        "A monthly leaderboard alongside the all-time one",
        "Rank cards with your server's own background, and members' own",
        "Double XP events",
        "Weekly champions: a role for the top chatter and top voice member",
    ]),
    ("\U0001f6e1️", "Moderation", [
        "Smarter automod: spam, blocked words, links and shouting",
        "A weekly staff report",
        "Up to 50 warn punishments",
        "Every case as a spreadsheet",
    ]),
    ("\U0001f3a8", "Make Paper yours", [
        "Give Paper its own name, picture, banner and bio on your server",
    ]),
    ("\U0001f3d7\ufe0f", "With Plus or Lifetime", [
        "Set your whole server up step by step: roles, channels, a staff area,"
        " logs, a how-to-mod forum, and every part of Paper switched on",
    ]),
]


# The cheapest plan each group comes with; a group not named here comes with
# Premium. Each plan has everything from the plans below it.
GROUP_TIER = {"With Plus or Lifetime": "plus"}


def perk_groups() -> list:
    """The perks as plain data, for the dashboard."""
    return [{"icon": icon, "title": title, "perks": list(lines),
             "tier": GROUP_TIER.get(title, "premium")}
            for icon, title, lines in PERK_GROUPS]


def perk_lines() -> str:
    """The perks as Discord text, one short line per group."""
    return "\n".join(f"{icon} **{title}:** " + "; ".join(lines)
                     for icon, title, lines in PERK_GROUPS)
