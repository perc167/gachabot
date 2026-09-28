"""Paper's own profile on one server, a Paper Premium perk.

Discord lets a bot have a different name, picture, banner and bio in each
server (Modify Current Member, since September 2025), the way a person can
have a server profile. A Premium server can set Paper's here, from
`$botprofile` or the dashboard; both come through update().

The name is a plain nickname, which any admin could set in Discord anyway,
so it isn't Premium. The picture, banner and bio are. If Premium ends they
go back to Paper's own (cogs/customizer.py checks hourly); the name stays.

What was set is kept in bot_profiles: Discord doesn't hand a bot's server
bio back, and the picture hashes make the dashboard's preview.
"""
import base64

import discord
from discord.http import Route

import premium


class ProfileError(Exception):
    """Something that can't be set, in words for whoever tried."""


# First bytes -> the picture type Discord needs to be told.
MAGIC = ((b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"),
         (b"GIF87a", "image/gif"), (b"GIF89a", "image/gif"))


def image_data(raw: bytes) -> str:
    """A picture as the data URI Discord wants, or ProfileError."""
    if len(raw) > premium.PICTURE_LIMIT:
        raise ProfileError(f"That picture is over {premium.PICTURE_LIMIT // 1024 // 1024} MB.")
    mime = next((m for head, m in MAGIC if raw.startswith(head)), None)
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        mime = "image/webp"
    if not mime:
        raise ProfileError("That has to be a PNG, JPEG, GIF or WebP picture.")
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def picture_url(guild_id: int, user_id: int, kind: str, hash_: str) -> str:
    """Where Discord serves a server avatar or banner."""
    if not hash_:
        return ""
    folder = "avatars" if kind == "avatar" else "banners"
    ext = "gif" if hash_.startswith("a_") else "png"
    return (f"https://cdn.discordapp.com/guilds/{guild_id}/users/{user_id}"
            f"/{folder}/{hash_}.{ext}?size=256")


def state(bot, guild) -> dict:
    """What's set now, for the dashboard and $botprofile."""
    row = bot.db.bot_profile(guild.id)
    me = guild.me
    return {
        "nick": (me.nick if me else "") or "",
        "name": bot.user.name if bot.user else "Paper",
        "bio": row["bio"] if row else "",
        "avatar": picture_url(guild.id, bot.user.id, "avatar", row["avatar"]) if row else "",
        "banner": picture_url(guild.id, bot.user.id, "banner", row["banner"]) if row else "",
        "default_avatar": str(bot.user.display_avatar.replace(size=256)) if bot.user else "",
        "nick_limit": premium.NICK_LIMIT,
        "bio_limit": premium.BIO_LIMIT,
    }


async def update(bot, guild, reason: str, **fields):
    """Change Paper's profile on this server.

    fields: nick, bio (text; "" or None puts it back), avatar, banner (raw
    picture bytes; None puts it back). Only the name is free."""
    payload = {}
    if "nick" in fields:
        nick = (fields["nick"] or "").strip()
        if len(nick) > premium.NICK_LIMIT:
            raise ProfileError(f"Keep the name to {premium.NICK_LIMIT} characters.")
        payload["nick"] = nick or None
    paid = {k for k in ("bio", "avatar", "banner") if k in fields}
    if paid and any(fields[k] for k in paid) and not bot.db.is_premium(guild.id):
        raise ProfileError("Paper's own picture, banner and bio on your server come"
                           " with Paper Premium.")
    if "bio" in fields:
        bio = (fields["bio"] or "").strip()
        if len(bio) > premium.BIO_LIMIT:
            raise ProfileError(f"Keep the bio to {premium.BIO_LIMIT} characters.")
        payload["bio"] = bio or None
    for kind in ("avatar", "banner"):
        if kind in fields:
            payload[kind] = image_data(fields[kind]) if fields[kind] else None
    if not payload:
        return
    try:
        member = await bot.http.request(
            Route("PATCH", "/guilds/{guild_id}/members/@me", guild_id=guild.id),
            json=payload, reason=reason[:500])
    except discord.Forbidden:
        raise ProfileError("Discord didn't let me change that. Changing my name needs"
                           " the Change Nickname permission.")
    except discord.HTTPException as e:
        raise ProfileError(f"Discord turned that down: {e.text or e.status}")
    row = bot.db.bot_profile(guild.id)
    kept = {"bio": row["bio"] if row else "", "avatar": row["avatar"] if row else "",
            "banner": row["banner"] if row else ""}
    if "bio" in payload:
        kept["bio"] = payload["bio"] or ""
    for kind in ("avatar", "banner"):
        if kind in payload:
            # Discord answers with the new picture's hash.
            kept[kind] = ((member or {}).get(kind) or "") if payload[kind] else ""
    bot.db.save_bot_profile(guild.id, **kept)


async def reset(bot, guild, reason: str, name_too: bool = True):
    """Back to Paper's own picture, banner and bio (and name)."""
    fields = {"bio": None, "avatar": None, "banner": None}
    if name_too:
        fields["nick"] = None
    await update(bot, guild, reason, **fields)
