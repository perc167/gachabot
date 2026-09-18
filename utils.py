"""Shared helpers: cooldown bookkeeping, kakera math, embed building."""
import time

import discord

import config


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


def kakera_value(character, rate_percent: int) -> int:
    """Base value scaled by rarity tier and the guild's kakera_rate."""
    _, _, mult = config.rarity_for(character["likes"])
    return max(1, int(character["base_kakera"] * mult * rate_percent / 100))


def rarity_of(character):
    return config.rarity_for(character["likes"])


class Cooldowns:
    """Reads and writes the four timers every player has.

    Rolls refill in blocks: when the reset time passes, the counter goes back
    to zero and the next window starts. Claims and kakera are simple
    ready-at timestamps.
    """

    def __init__(self, db):
        self.db = db

    def rolls_left(self, guild_id: int, user_id: int) -> tuple:
        """Returns (rolls_left, seconds_until_reset)."""
        player = self.db.get_player(guild_id, user_id)
        limit = self.db.get_setting(guild_id, "roll_limit")
        window = self.db.get_setting(guild_id, "roll_reset_minutes") * 60
        current = now()

        if current >= player["rolls_reset_at"]:
            self.db.update_player(
                guild_id, user_id, rolls_used=0, rolls_reset_at=current + window
            )
            return limit, window

        return max(0, limit - player["rolls_used"]), player["rolls_reset_at"] - current

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
        self.db.update_player(guild_id, user_id, claim_ready_at=now() + minutes * 60)

    def kakera_ready(self, guild_id: int, user_id: int) -> tuple:
        player = self.db.get_player(guild_id, user_id)
        remaining = player["kakera_ready_at"] - now()
        return remaining <= 0, max(0, remaining)

    def start_kakera_cooldown(self, guild_id: int, user_id: int):
        minutes = self.db.get_setting(guild_id, "kakera_interval_minutes")
        self.db.update_player(guild_id, user_id, kakera_ready_at=now() + minutes * 60)


def character_embed(
    db, guild_id: int, character, *, footer: str = None, show_owner: bool = True
) -> discord.Embed:
    """The card shown for a roll, a `$im` lookup, or a harem page."""
    tier, colour, _ = rarity_of(character)
    rate = db.get_setting(guild_id, "kakera_rate")

    embed = discord.Embed(title=character["name"], colour=colour)
    embed.description = character["series"]
    embed.set_image(url=character["image_url"])

    lines = [
        f"{character['likes']} likes",
        f"{kakera_value(character, rate)} kakera",
        tier,
    ]
    embed.add_field(name="​", value=" • ".join(lines), inline=False)

    if show_owner:
        owner_id = db.owner_of(guild_id, character["id"])
        if owner_id:
            embed.add_field(name="Belongs to", value=f"<@{owner_id}>", inline=False)

    wishers = db.wishers_of(guild_id, character["id"])
    if wishers:
        embed.set_footer(text=f"{footer + ' • ' if footer else ''}Wished by {len(wishers)}")
    elif footer:
        embed.set_footer(text=footer)

    return embed


def paginate(lines, per_page: int = 10) -> list:
    """Chop a list of strings into pages."""
    return [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]
