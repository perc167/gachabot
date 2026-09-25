"""A web dashboard for level settings, like Arcane's, served by the bot.

It runs inside the bot because the settings live in the bot's database. The
public site on Cloudflare is static and can't reach it.

There is no Discord login. `$dashboard` DMs an admin a private link, good
for one server and LINK_LIFETIME seconds; the token is in the part of the
URL after #, which browsers never send to a server or leak in a Referer.
Every request checks again that the person still has Manage Server, so a
link stops working the moment they lose it.

The web server starts only when PORT is set, which Railway does. The link
it hands out uses PUBLIC_URL, or the domain Railway gives the service
(RAILWAY_PUBLIC_DOMAIN), so the bot needs a public domain in Railway:
the service's Settings > Networking > Generate Domain.

Everything saved here goes through the same checks as the $levels commands:
Levels.save_settings() and the limits in cogs/levels.py.
"""
import os
import secrets
import time

import discord
from aiohttp import web
from discord.ext import commands

from cogs.levels import (DEFAULT_MESSAGE, KARUDA_EVERY, MAX_LEVEL,
                         MESSAGE_LIMIT, MESSAGE_VARIABLES, SETTINGS, level_for,
                         total_for, validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "dashboard", "index.html")
LINK_LIFETIME = 3600
MAX_LEVEL_ROLES = 100

HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}


def public_url() -> str:
    url = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    if url:
        return url
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
    return f"https://{domain}" if domain else ""


def problem(status: int, message: str):
    return web.json_response({"problems": [message]}, status=status,
                             headers=HEADERS)


class Dashboard(commands.Cog):
    works_everywhere = True  # an admin command; see cogs/modtools.py

    def __init__(self, bot):
        self.bot = bot
        self.links = {}  # token -> {"guild", "user", "expires"}
        self.runner = None

    async def cog_load(self):
        port = os.getenv("PORT")
        if not port:
            return
        app = web.Application(client_max_size=256 * 1024)
        app.router.add_get("/", self.home)
        app.router.add_get("/dashboard", self.page)
        app.router.add_get("/api/levels", self.api_get)
        app.router.add_post("/api/levels", self.api_save)
        app.router.add_post("/api/levels/sync", self.api_sync)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, "0.0.0.0", int(port)).start()

    async def cog_unload(self):
        if self.runner:
            await self.runner.cleanup()

    # ------------------------------------------------------------ the link

    def issue(self, guild_id: int, user_id: int) -> str:
        now = time.time()
        self.links = {t: e for t, e in self.links.items() if e["expires"] > now}
        token = secrets.token_urlsafe(32)
        self.links[token] = {"guild": guild_id, "user": user_id,
                             "expires": now + LINK_LIFETIME}
        return token

    @commands.command(name="dashboard", aliases=["dash"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def dashboard(self, ctx):
        """DMs you a private link to change level settings on the web."""
        base = public_url()
        if not self.runner or not base:
            await ctx.send(
                "The dashboard isn't switched on yet. Whoever runs the bot"
                " needs to give it a public domain in Railway (the service's"
                " Settings > Networking > Generate Domain). Until then, every"
                f" setting works with `{ctx.prefix}levels`: try"
                f" `{ctx.prefix}levels settings`.")
            return
        token = self.issue(ctx.guild.id, ctx.author.id)
        embed = discord.Embed(
            title=f"{ctx.guild.name}: levels dashboard",
            url=f"{base}/dashboard#{token}",
            description=(f"[Open the dashboard]({base}/dashboard#{token})\n\n"
                         "This link is only for you and only for this server."
                         " It stops working in an hour, or if you lose Manage"
                         " Server. Don't share it."),
            colour=self.bot.db.get_pref(ctx.guild.id, "cardcolour", 0x7C6BF0))
        try:
            await ctx.author.send(embed=embed)
        except discord.HTTPException:
            await ctx.send("I couldn't DM you. Allow DMs from server members"
                           " (right-click the server > Privacy Settings) and"
                           " try again.")
            return
        await ctx.send("Sent you the link in DMs.")

    def who(self, request):
        """(guild, member, Levels cog) for a request's link, or an error."""
        header = request.headers.get("Authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        entry = self.links.get(token)
        if not entry or entry["expires"] < time.time():
            return None, problem(401, "This link has expired. Run $dashboard"
                                      " in Discord for a new one.")
        guild = self.bot.get_guild(entry["guild"])
        member = guild.get_member(entry["user"]) if guild else None
        if not member or not member.guild_permissions.manage_guild:
            return None, problem(403, "You need Manage Server on this server.")
        levels = self.bot.get_cog("Levels")
        if not levels:
            return None, problem(503, "Levels are switched off on this bot.")
        return (guild, member, levels), None

    # --------------------------------------------------------------- pages

    async def home(self, request):
        return web.Response(text="Yuri is running. Run $dashboard in Discord"
                                 " for a link to your server's dashboard.",
                            headers=HEADERS)

    async def page(self, request):
        return web.FileResponse(PAGE, headers={**HEADERS,
                                               "Content-Type": "text/html"})

    # ----------------------------------------------------------------- API

    def usable(self, guild, role) -> bool:
        return (not role.is_default() and not role.managed
                and role < guild.me.top_role)

    def state(self, guild, levels) -> dict:
        settings = levels.settings_of(guild.id)
        # Ids go out as strings: they're bigger than a JavaScript number
        # can hold exactly.
        settings["channel"] = str(settings["channel"])
        return {
            "guild": {"name": guild.name,
                      "icon": guild.icon.url if guild.icon else None},
            "settings": settings,
            "message": levels.message_of(guild.id),
            "default_message": DEFAULT_MESSAGE,
            "level_roles": [{"level": r["level"], "role": str(r["role_id"])}
                            for r in self.bot.db.level_roles_of(guild.id)],
            "ignored": [str(c) for c in self.bot.db.level_ignored_in(guild.id)],
            "roles": [{"id": str(r.id), "name": r.name,
                       "color": f"#{r.colour.value:06x}" if r.colour.value else None,
                       "usable": self.usable(guild, r)}
                      for r in sorted(guild.roles, key=lambda r: -r.position)
                      if not r.is_default()],
            "channels": [{"id": str(c.id), "name": c.name,
                          "category": c.category.name if c.category else ""}
                         for c in guild.text_channels],
            "limits": {key: {"min": low, "max": high, "label": label}
                       for key, (_d, low, high, label) in SETTINGS.items()
                       if key != "channel"},
            "max_level": MAX_LEVEL,
            "message_limit": MESSAGE_LIMIT,
            "variables": list(MESSAGE_VARIABLES),
            "karuda_every": KARUDA_EVERY,
            "curve": [total_for(n) for n in range(101)],
        }

    async def api_get(self, request):
        found, error = self.who(request)
        if error:
            return error
        guild, _member, levels = found
        return web.json_response(self.state(guild, levels), headers=HEADERS)

    async def api_save(self, request):
        found, error = self.who(request)
        if error:
            return error
        guild, _member, levels = found
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "That wasn't valid JSON.")
        if not isinstance(body, dict):
            return problem(400, "That wasn't valid JSON.")

        problems = []
        settings = dict(body.get("settings") or {})
        if "channel" in settings:
            try:
                channel = int(settings["channel"])
            except (TypeError, ValueError):
                channel = None
            if channel not in (0, -1) and not (
                    channel and isinstance(guild.get_channel(channel),
                                           discord.TextChannel)):
                problems.append("Pick a text channel in this server for"
                                " level-ups.")
            settings["channel"] = channel

        message = body.get("message")
        if message is not None:
            if not isinstance(message, str):
                problems.append("The level-up message has to be text.")
            elif len(message) > MESSAGE_LIMIT:
                problems.append(f"Keep the level-up message under"
                                f" {MESSAGE_LIMIT} characters.")

        pairs = []
        rows = body.get("level_roles")
        if rows is not None:
            if not isinstance(rows, list) or len(rows) > MAX_LEVEL_ROLES:
                problems.append(f"Up to {MAX_LEVEL_ROLES} level roles.")
                rows = []
            seen = set()
            for row in rows:
                try:
                    level, role_id = int(row["level"]), int(row["role"])
                except (TypeError, ValueError, KeyError):
                    problems.append("Every level role needs a level and a role.")
                    continue
                role = guild.get_role(role_id)
                if not 1 <= level <= MAX_LEVEL:
                    problems.append(f"Levels go from 1 to {MAX_LEVEL}.")
                elif level in seen:
                    problems.append(f"Level {level} has two roles. Pick one.")
                elif not role or not self.usable(guild, role):
                    problems.append(
                        f"I can't give {role.name if role else 'that role'}."
                        " It has to be below my own role and not managed by"
                        " another bot.")
                else:
                    seen.add(level)
                    pairs.append((level, role_id))

        ignored = body.get("ignored")
        channel_ids = []
        if ignored is not None:
            for value in ignored if isinstance(ignored, list) else []:
                try:
                    channel = guild.get_channel(int(value))
                except (TypeError, ValueError):
                    channel = None
                if isinstance(channel, discord.TextChannel):
                    channel_ids.append(channel.id)

        # Every problem at once, so fixing one doesn't just reveal the next.
        problems += [p for key, value in settings.items()
                     if key != "channel" and (p := validate(key, value))]
        if problems:
            return web.json_response({"problems": problems}, status=400,
                                     headers=HEADERS)
        # Numbers last-checked and saved in one go by the same code the
        # commands use; nothing else is written if they're refused.
        problems = levels.save_settings(guild.id, settings)
        if problems:
            return web.json_response({"problems": problems}, status=400,
                                     headers=HEADERS)
        if message is not None:
            text = message.strip()
            self.bot.db.set_level_text(
                guild.id, "message",
                None if not text or text == DEFAULT_MESSAGE else text)
        if rows is not None:
            self.bot.db.replace_level_roles(guild.id, sorted(pairs))
        if ignored is not None:
            self.bot.db.replace_level_ignored(guild.id, channel_ids)
        return web.json_response(self.state(guild, levels), headers=HEADERS)

    async def api_sync(self, request):
        """Bring every member's level roles up to date, like $levels sync."""
        found, error = self.who(request)
        if error:
            return error
        guild, _member, levels = found
        checked = 0
        for row in self.bot.db.top_levels(guild.id, limit=100_000):
            member = guild.get_member(row["user_id"])
            if member:
                await levels.sync_roles(member, level_for(row["xp"])[0])
                checked += 1
        return web.json_response({"checked": checked}, headers=HEADERS)


async def setup(bot):
    await bot.add_cog(Dashboard(bot))
