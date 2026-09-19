"""Shared helpers: cooldown bookkeeping, karuda math, embed building."""
import json
import time

import discord

import config
import perks


def now() -> int:
    return int(time.time())


def fmt_duration(seconds: int) -> str:
    """'2h 15m' / '45s' — used for every cooldown message."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if secs and minutes < 5:
        return f"{minutes}m {secs}s"
    return f"{minutes}m"


# Set once at startup so icon lookups can see the server's custom emoji.
# A module-level binding rather than a parameter threaded through every embed
# helper: which icon to draw is presentation, not something callers decide.
_bot = None


def use_emoji_from(bot):
    """Remember the bot, so shard icons can resolve uploaded emoji."""
    global _bot
    _bot = bot


def shard_icon(key: str) -> str:
    """The uploaded crystal for this shard, or the Unicode fallback.

    If any server the bot is in has an emoji named after the shard - dust,
    verdite, prism and so on - that emoji is used. Upload the files from
    assets/shards/ and they appear on their own, with nothing to configure.
    """
    fallback = config.shard(key)[2]
    if _bot is None:
        return fallback
    emoji = discord.utils.get(_bot.emojis, name=key)
    return str(emoji) if emoji else fallback


def value_with_keys(db, guild_id: int, character, rate_percent: int) -> int:
    """A character's worth including any keys spent on them here."""
    level = db.key_level(guild_id, character["id"])
    return max(1, int(karuda_value(character, rate_percent)
                      * perks.key_multiplier(level)))


def value_for_rank(rank: int, total: int) -> int:
    """Rank to base value, matching tools/fetch_roster.py.

    Kept here as well so a series added at runtime is priced on the same
    curve as everything that arrived in the bulk fetch.
    """
    import math

    low, high, premium_rank, premium_value = 20, 1300, 300, 300
    if total <= 1:
        return high
    rank = max(1, min(rank, total))
    t = math.log(rank) / math.log(total)
    pin = math.log(premium_rank) / math.log(total)
    share = (premium_value - low) / (high - low)
    exponent = math.log(share) / math.log(1 - pin) if 0 < pin < 1 else 2.0
    return max(low, round(low + (high - low) * (1 - t) ** exponent))


def karuda_value(character, rate_percent: int) -> int:
    """base_karuda already encodes how famous the character is, so the only
    adjustment is the server's own rate."""
    return max(1, int(character["base_karuda"] * rate_percent / 100))


class Cooldowns:
    """Reads and writes the four timers every player has.

    Rolls refill in blocks: when the reset time passes, the counter goes back
    to zero and the next window starts. Claims and karuda are simple
    ready-at timestamps.
    """

    def __init__(self, db):
        self.db = db

    def rolls_left(self, guild_id: int, user_id: int) -> tuple:
        """Returns (rolls_left, seconds_until_reset)."""
        player = self.db.get_player(guild_id, user_id)
        earned = perks.effective(self.db, guild_id, user_id)
        limit = self.db.get_setting(guild_id, "roll_limit") + earned["rolls"]
        window = self.db.get_setting(guild_id, "roll_reset_minutes") * 60
        current = now()

        # Bought rolls sit on top of the allowance and expire with the window,
        # so buying is a top-up rather than a permanent raise.
        if current >= player["rolls_reset_at"]:
            self.db.update_player(
                guild_id,
                user_id,
                rolls_used=0,
                rolls_bought=0,
                rolls_reset_at=current + window,
            )
            return limit, window

        allowance = limit + player["rolls_bought"]
        return (
            max(0, allowance - player["rolls_used"]),
            player["rolls_reset_at"] - current,
        )

    def spend_roll(self, guild_id: int, user_id: int):
        player = self.db.get_player(guild_id, user_id)
        self.db.update_player(guild_id, user_id, rolls_used=player["rolls_used"] + 1)

    def claim_ready(self, guild_id: int, user_id: int) -> tuple:
        """Returns (is_ready, seconds_remaining)."""
        player = self.db.get_player(guild_id, user_id)
        remaining = player["claim_ready_at"] - now()
        return remaining <= 0, max(0, remaining)

    def start_claim_cooldown(self, guild_id: int, user_id: int):
        minutes = self.db.get_setting(guild_id, "claim_interval_minutes")
        # Badges and tower floors shorten the wait.
        reduction = perks.effective(self.db, guild_id, user_id)["claim_percent"]
        seconds = int(minutes * 60 * (100 - reduction) / 100)
        self.db.update_player(guild_id, user_id, claim_ready_at=now() + seconds)

    def karuda_ready(self, guild_id: int, user_id: int) -> tuple:
        player = self.db.get_player(guild_id, user_id)
        remaining = player["karuda_ready_at"] - now()
        return remaining <= 0, max(0, remaining)

    def start_karuda_cooldown(self, guild_id: int, user_id: int):
        minutes = self.db.get_setting(guild_id, "karuda_interval_minutes")
        self.db.update_player(guild_id, user_id, karuda_ready_at=now() + minutes * 60)


def character_embed(
    db,
    guild_id: int,
    character,
    *,
    footer: str = None,
    show_owner: bool = True,
    random_art: bool = False,
    image_url: str = None,
) -> discord.Embed:
    """The card shown for a roll, a `$im` lookup, or a harem page.

    `random_art` picks one image at random from the character's album, which
    is what a roll does: the same character can show up wearing a different
    picture each time.
    """
    rate = db.get_setting(guild_id, "karuda_rate")
    owner_id = db.owner_of(guild_id, character["id"]) if show_owner else None
    wishers = db.wishers_of(guild_id, character["id"])

    # One accent colour for everyone; a claimed character goes green so you
    # can tell at a glance whether the button is worth racing for.
    colour = config.CLAIMED_COLOUR if owner_id else config.CARD_COLOUR
    embed = discord.Embed(title=character["name"], colour=colour)

    # Series on its own line, quoted, so the name is what your eye lands on.
    embed.description = f"> {character['series']}"

    if image_url is None:
        image_url = (
            db.random_image(character["id"]) if random_art else character["image_url"]
        )
    if image_url:
        embed.set_image(url=image_url)
    else:
        embed.description += (
            f"\n\n*no image yet — `$setimage {character['id']} <url>`*"
        )

    # Three short inline fields read as columns rather than a wall of bullets.
    icon = shard_icon(config.SHARD_TYPES[0][0])
    level = db.key_level(guild_id, character["id"])
    worth = value_with_keys(db, guild_id, character, rate)
    embed.add_field(
        name="Value",
        value=f"{icon} **{worth:,}**"
              + (f"\n\U0001f511 ×{level}" if level else ""),
        inline=True,
    )
    if character["claim_rank"] or character["like_rank"]:
        embed.add_field(
            name="Rank",
            value=(
                f"claim **#{character['claim_rank']:,}**\n"
                f"like **#{character['like_rank']:,}**"
            ),
            inline=True,
        )

    extras = []
    album = db.image_count(character["id"])
    if album > 1:
        extras.append(f"{album} images")
    liked = db.like_count(guild_id, character["id"])
    if liked:
        extras.append(f"{liked} ♥ here")
    if wishers:
        extras.append(f"wished by {len(wishers)}")
    if extras:
        embed.add_field(name="​", value="\n".join(extras), inline=True)

    if owner_id:
        hearts = db.soulmate_holders(guild_id, character["id"])
        mark = " \U0001f496" if owner_id in hearts else ""
        embed.add_field(
            name="Belongs to", value=f"<@{owner_id}>{mark}", inline=False
        )

    if footer:
        embed.set_footer(text=footer)

    return embed


def paginate(lines, per_page: int = 10) -> list:
    """Chop a list of strings into pages."""
    return [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]


def iter_roster(path: str):
    """Yield character records from a roster file without holding all of it.

    data/characters.json is written one record per line inside a JSON array,
    so it can be read a line at a time. That shape is worth using: a hundred
    thousand characters parsed in one go is around 140MB of Python objects,
    which is real money on a small container and happens on every deploy.

    Anything not in that shape - a hand-written file, a prettified one - is
    loaded whole instead, so nothing stops working for the sake of the
    optimisation.
    """
    with open(path, "r", encoding="utf-8") as handle:
        first = handle.readline().strip()
        second = handle.readline()
        record = None
        streamable = first == "["
        if streamable:
            try:
                record = json.loads(second.strip().rstrip(","))
            except json.JSONDecodeError:
                streamable = False

        if not streamable:
            handle.seek(0)
            payload = json.load(handle)
            if not isinstance(payload, list):
                raise ValueError("expected a JSON list of character objects")
            yield from payload
            return

        yield record
        for line in handle:
            line = line.strip().rstrip(",")
            if not line or line == "]":
                continue
            yield json.loads(line)
