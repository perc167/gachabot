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
    "karuda_interval_minutes": (20, 1, 1440, "Minutes between karuda collects"),
    "max_marriages": (0, 0, 5000, "Harem size cap (0 = unlimited)"),
    "claim_window_seconds": (45, 5, 600, "How long a roll stays claimable"),
    "karuda_rate": (100, 10, 500, "Karuda payout multiplier, as a percent"),
    "wish_protect_seconds": (
        15,
        0,
        300,
        "Head start a wisher gets before others may claim",
    ),
    "show_claimed": (1, 0, 1, "Roll characters that are already claimed (0/1)"),
    "wish_limit": (20, 1, 200, "How many characters a user may wish for"),
}

# The currency. Karuda are shards; every payout is measured in them.
CURRENCY = "karuda"
CURRENCY_TITLE = "Karuda"

# Card accent. One colour for every character - there are no rarity tiers,
# a character's worth is its karuda value and its ranks.
CARD_COLOUR = 0x7C6BF0
CLAIMED_COLOUR = 0x43B581

# The six kinds of shard a $daily can turn up.
#   key, display name, icon, payout multiplier, weight, embed colour
# Weights are relative: Dust lands about half the time, Prism about 1 in 100.
# Icons are plain Unicode so the bot works with no setup.
#
# To use the crystal art instead:
#   1. python tools/make_shards.py          -> writes assets/shards/*.png
#   2. Discord: Server Settings -> Emoji -> Upload Emoji, one per file.
#      Name them to match the keys below: dust, verdite, aurum, ember,
#      azure, prism.
#   3. Type \:dust: in a channel, send it, then copy what Discord expands it
#      to - "<:dust:1234567890123>" - and paste that in place of the Unicode
#      icon below.
# The bot needs Use External Emoji in any server where it posts them.
SHARD_TYPES = [
    ("dust",    "Karuda Dust", "\U0001f7e3",  1.0, 50, 0x9B8AFB),
    ("verdite", "Verdite",     "\U0001f7e2",  1.6, 22, 0x43B581),
    ("aurum",   "Aurum",       "\U0001f7e1",  2.4, 14, 0xF1C40F),
    ("ember",   "Ember",       "\U0001f7e0",  3.6,  8, 0xE67E22),
    ("azure",   "Azure",       "\U0001f535",  5.5,  5, 0x3498DB),
    ("prism",   "Prism",       "\U0001f308", 12.0,  1, 0xFF4D6D),
]

SHARDS_BY_KEY = {key: (key, name, icon, mult, weight, colour)
                 for key, name, icon, mult, weight, colour in SHARD_TYPES}


def shard(key: str):
    """Look up one shard type, falling back to the basic one."""
    return SHARDS_BY_KEY.get(key, SHARD_TYPES[0])


def roll_shard(random_module):
    """Pick a shard type by weight. Returns the whole tuple."""
    weights = [entry[4] for entry in SHARD_TYPES]
    return random_module.choices(SHARD_TYPES, weights=weights, k=1)[0]
