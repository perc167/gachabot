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
]


def perk_groups() -> list:
    """The perks as plain data, for the dashboard."""
    return [{"icon": icon, "title": title, "perks": list(lines)}
            for icon, title, lines in PERK_GROUPS]


def perk_lines() -> str:
    """The perks as Discord text, one short line per group."""
    return "\n".join(f"{icon} **{title}:** " + "; ".join(lines)
                     for icon, title, lines in PERK_GROUPS)
