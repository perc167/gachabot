"""Static bot configuration and per-guild setting definitions."""
import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip().strip("\"'")
PREFIX = os.getenv("PREFIX", "$").strip() or "$"
def _database_path() -> tuple:
    """Where the database lives, and whether it survives a redeploy.

    A host like Railway rebuilds the container on every deploy, so anything
    written beside the code is thrown away - claims, balances, tutorials, the
    lot. The only thing that survives is a mounted volume.

    Railway sets RAILWAY_VOLUME_MOUNT_PATH when one is attached, so attaching
    a volume is all it takes: nothing to configure here, and nothing to
    remember. DB_PATH still wins if it is set, for anyone hosting elsewhere.
    """
    explicit = os.getenv("DB_PATH", "").strip()
    if explicit:
        return explicit, True

    mount = (os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
             or os.getenv("VOLUME_PATH") or "").strip()
    if mount and os.path.isdir(mount):
        return os.path.join(mount, "gacha.db"), True

    # No volume. The bot still runs - it just forgets everything next deploy,
    # and says so loudly at startup rather than letting it be a surprise.
    return "gacha.db", False


DB_PATH, DB_PERSISTS = _database_path()

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
    # 170 minutes - two hours fifty. Rolls and claims share the number so
    # they share a boundary: the claim window is rounded up to whole roll
    # windows, and any two different numbers would only meet occasionally.
    "roll_reset_minutes": (170, 5, 1440, "Minutes between roll refills"),
    "claim_interval_minutes": (
        170, 1, 10080,
        "Minutes between claims, rounded up to whole roll windows",
    ),
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
    "roll_rank_limit": (
        0, 0, 200000,
        "Deepest claim rank a roll can reach; 0 rolls the whole roster",
    ),
    "roll_bias": (
        35, 0, 100,
        "How strongly rolls favour well-known characters (0 = flat pool)",
    ),
    "wish_limit": (20, 1, 200, "How many characters a user may wish for"),
    "custom_limit": (50, 0, 2000, "Custom characters a server may add"),
    "dk_snipe": (1, 0, 1, "Let others take the shard you leave behind (0/1)"),
    "dk_protect_seconds": (
        20, 0, 600,
        "How long a daily drop is yours alone before others may snipe it",
    ),
    "dk_snipe_percent": (
        50, 1, 100,
        "Percent of a shard a sniper receives",
    ),
    # --- economy ---
    "karuda_grab_percent": (
        8, 1, 100,
        "Percent of a character's value a karuda grab pays out",
    ),
    "divorce_refund_percent": (
        0, 0, 100,
        "Percent of value refunded on divorce (0 stops claim-divorce farming)",
    ),
    "price_rolls": (400, 10, 1000000, "Cost of a bundle of extra rolls"),
    "rolls_per_purchase": (5, 1, 50, "Rolls you get per bundle bought"),
    "price_claim_reset": (900, 10, 1000000, "Cost to clear your claim cooldown"),
    "price_wish_slot": (1200, 10, 1000000, "Cost of one extra wishlist slot"),
}

# Everyone who started playing before this unix timestamp counts as an early
# player, and keeps whatever becomes paid later. 0 means "everyone so far",
# which is the right answer until there is something to charge for: set it to
# the moment you start gating, not before.
FOUNDER_CUTOFF = 0

# How much more a character is wanted than merely liked.
#
# Two rankings, because they answer different questions. like_rank is raw
# AniList favourites - honest popularity, and it skews male: nine of the top
# ten are men. claim_rank is how much people want to *own* somebody, which is
# what a gacha is actually about and what Mudae ranks on, and that skews the
# other way.
#
# One number produces the difference. At 2.2 the top of the pool is Makima,
# Marin Kitagawa, Rem and Zero Two, while Gojou and Levi stay near it at
# eleven and thirteen rather than owning it. At 1.0 the two rankings are the
# same and the men are back on top; above 3 the men vanish from the top
# twenty entirely.
FEMALE_CLAIM_WEIGHT = 2.2

# The currency. Karuda are shards; every payout is measured in them.
CURRENCY = "karuda"
CURRENCY_TITLE = "Karuda"

# Card accent. One colour for every character - there are no rarity tiers,
# a character's worth is its karuda value and its ranks.
CARD_COLOUR = 0x7C6BF0
CLAIMED_COLOUR = 0x43B581

# The eight kinds of shard a $daily can turn up.
#   key, display name, fallback icon, payout multiplier, weight, embed colour
# Weights are relative out of 1000: Dust lands half the time, Lumen 1 in 500.
#
# The icon here is only a fallback. To use the crystal art:
#   1. python tools/make_shards.py     -> writes assets/shards/*.png
#   2. Discord: Server Settings -> Emoji -> Upload Emoji, one per file,
#      named exactly as the key below: dust, verdite, aurum, ember, azure,
#      obsidian, prism, lumen.
# That is all. The bot finds emoji by name at runtime, so there are no ids to
# copy; $shards reports how many it can see. It needs Use External Emoji in
# any server where it posts them.
SHARD_TYPES = [
    ("dust",     "Karuda Dust", "\U0001f7e3",  1.0, 620, 0x9B8AFB),
    ("verdite",  "Verdite",     "\U0001f7e2",  1.6, 200, 0x43B581),
    ("aurum",    "Aurum",       "\U0001f7e1",  2.4,  95, 0xF1C40F),
    ("ember",    "Ember",       "\U0001f7e0",  3.6,  45, 0xE67E22),
    ("azure",    "Azure",       "\U0001f535",  5.5,  25, 0x3498DB),
    ("obsidian", "Obsidian",    "⚫",      9.0,  10, 0x2E2E38),
    ("prism",    "Prism",       "\U0001f308", 14.0,   4, 0xFF4D6D),
    ("lumen",    "Lumen",       "⚪",     25.0,   1, 0xEDEFF5),
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
