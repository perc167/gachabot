"""Weeks, for the Premium weekly extras (cogs/champions.py).

A week starts Monday 00:00 UTC. Weeks are numbered from the first Monday
after 1970, so "last week" is just week_now() - 1.
"""
import time

FIRST_MONDAY = 4 * 86400          # 1970-01-05 00:00 UTC
WEEK = 7 * 86400


def week_now(now: float = None) -> int:
    return int(((now if now is not None else time.time()) - FIRST_MONDAY) // WEEK)


def bounds(week: int) -> tuple:
    """(start, end) of a week, as timestamps."""
    start = FIRST_MONDAY + week * WEEK
    return start, start + WEEK


def champions_on(db, guild_id: int) -> bool:
    return bool(db.get_premium_setting(guild_id, "champ_chat_role")
                or db.get_premium_setting(guild_id, "champ_voice_role")
                or db.get_premium_setting(guild_id, "champ_channel"))


def tracking(db, guild_id: int) -> bool:
    """Whether this server's week is being counted: Premium, with champions
    switched on. Nobody else's messages are recorded."""
    return champions_on(db, guild_id) and db.is_premium(guild_id)
