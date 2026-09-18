"""Static bot configuration and per-guild setting definitions."""
import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip().strip("\"'")
PREFIX = os.getenv("PREFIX", "$").strip() or "$"
DB_PATH = os.getenv("DB_PATH", "gacha.db")

# Anything that is not a plain number is ignored, so leaving the placeholder
# in .env warns instead of crashing on startup.
OWNERS = {
    int(part)
    for part in os.getenv("BOT_OWNERS", "").replace(" ", "").split(",")
    if part.isdigit()
}

# Every per-guild setting lives here: name -> (default, min, max, description).
# `$settings` reads this table, `$setconfig` writes to it, so adding a knob is
# a one-line change.
GUILD_SETTINGS = {
    "roll_limit": (10, 1, 100, "Rolls each user gets per reset period"),
    "roll_reset_minutes": (60, 5, 1440, "Minutes between roll refills"),
    "claim_interval_minutes": (180, 1, 10080, "Minutes between character claims"),
    "kakera_interval_minutes": (20, 1, 1440, "Minutes between kakera collects"),
    "max_marriages": (0, 0, 5000, "Harem size cap (0 = unlimited)"),
    "claim_window_seconds": (45, 5, 600, "How long a roll stays claimable"),
    "kakera_rate": (100, 10, 500, "Kakera payout multiplier, as a percent"),
    "wish_protect_seconds": (
        15,
        0,
        300,
        "Head start a wisher gets before others may claim",
    ),
    "show_claimed": (1, 0, 1, "Roll characters that are already claimed (0/1)"),
    "wish_limit": (20, 1, 200, "How many characters a user may wish for"),
}

# Likes thresholds -> (tier name, embed colour, kakera multiplier).
# Ordered high to low; the first threshold a character clears wins.
RARITY_TIERS = [
    (1500, "Mythic", 0xFF4D6D, 3.0),
    (700, "Legendary", 0xF4A261, 2.2),
    (300, "Epic", 0xB388EB, 1.6),
    (100, "Rare", 0x4EA8DE, 1.25),
    (0, "Common", 0x8D99AE, 1.0),
]


def rarity_for(likes: int):
    """Return (name, colour, multiplier) for a character's like count."""
    for threshold, name, colour, mult in RARITY_TIERS:
        if likes >= threshold:
            return name, colour, mult
    return RARITY_TIERS[-1][1], RARITY_TIERS[-1][2], RARITY_TIERS[-1][3]
