"""Log in with Discord, for the web dashboard (cogs/dashboard.py).

The standard OAuth2 code flow. The browser is sent to Discord, the person
approves, Discord sends them back to /callback with a one-time code, and the
bot swaps that code for their username and the servers they're in, using the
app's client secret, which never leaves the server.

It asks for `identify guilds` only: who they are and which servers they're
in. Not their email, not their messages.

Needs DISCORD_CLIENT_SECRET (Developer Portal > the app > OAuth2), and
the callback URL, `<public url>/callback`, added as a redirect there.
DISCORD_API_BASE and DISCORD_AUTHORIZE_URL exist only so tests can stand in
for Discord.
"""
import hashlib
import json
import os
import urllib.parse

import aiohttp

API = os.getenv("DISCORD_API_BASE", "https://discord.com/api/v10").rstrip("/")
AUTHORIZE = os.getenv("DISCORD_AUTHORIZE_URL", "https://discord.com/oauth2/authorize")
SCOPES = "identify guilds"
TIMEOUT = aiohttp.ClientTimeout(total=15)

# Permission bits Discord reports per server.
ADMINISTRATOR = 0x8
MANAGE_GUILD = 0x20


class LoginFailed(Exception):
    """Discord refused the code or couldn't be reached."""


def secret() -> str:
    return os.getenv("DISCORD_CLIENT_SECRET", "").strip()


def configured() -> bool:
    return bool(secret())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authorize_url(client_id: int, redirect: str, state: str) -> str:
    return AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "scope": SCOPES,
        "redirect_uri": redirect,
        "state": state,
        "prompt": "none",   # skip the consent screen once it's been given
    })


def can_manage(guild: dict) -> bool:
    if guild.get("owner"):
        return True
    permissions = int(guild.get("permissions", 0))
    return bool(permissions & (ADMINISTRATOR | MANAGE_GUILD))


async def log_in(client_id: int, redirect: str, code: str) -> dict:
    """Swap a code for {"id", "name", "avatar", "guilds"}; guilds holds only
    the servers they can manage."""
    async with aiohttp.ClientSession(timeout=TIMEOUT) as http:
        async with http.post(f"{API}/oauth2/token", data={
            "client_id": str(client_id),
            "client_secret": secret(),
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
        }) as response:
            if response.status != 200:
                raise LoginFailed(f"token exchange: {response.status}")
            token = (await response.json())["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        async with http.get(f"{API}/users/@me", headers=headers) as response:
            if response.status != 200:
                raise LoginFailed(f"user: {response.status}")
            user = await response.json()
        async with http.get(f"{API}/users/@me/guilds", headers=headers) as response:
            if response.status != 200:
                raise LoginFailed(f"guilds: {response.status}")
            guilds = await response.json()

    avatar = None
    if user.get("avatar"):
        avatar = (f"https://cdn.discordapp.com/avatars/{user['id']}/"
                  f"{user['avatar']}.png?size=64")
    return {
        "id": int(user["id"]),
        "name": user.get("global_name") or user.get("username") or "you",
        "avatar": avatar,
        "guilds": [{"id": g["id"], "name": g.get("name", ""),
                    "icon": g.get("icon")}
                   for g in guilds if can_manage(g)],
    }


def dump_guilds(guilds: list) -> str:
    return json.dumps(guilds, separators=(",", ":"))
