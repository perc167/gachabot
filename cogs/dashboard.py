"""A web dashboard for level settings, like Arcane's, served by the bot.

It runs inside the bot because the settings live in the bot's database. The
public site on Cloudflare is static and can't reach it.

Two ways in, and every request checks again, live, that the person has
Manage Server on the server they're changing:

- Log in with Discord (oauth.py). A session cookie, HttpOnly and SameSite,
  lasts SESSION_DAYS; only its hash is stored. Changes made with it must
  carry an X-Paper header, which another site can't add without a CORS
  preflight this server never grants, so a forged form can't save
  anything.
- `$dashboard`, which DMs a private link for one server, good for
  LINK_LIFETIME seconds. The token is in the part of the URL after #,
  which browsers never send to a server or leak in a Referer.

The web server starts only when PORT is set, which Railway does. The link
it hands out uses PUBLIC_URL, or the domain Railway gives the service
(RAILWAY_PUBLIC_DOMAIN), so the bot needs a public domain in Railway:
the service's Settings > Networking > Generate Domain.

Everything saved here goes through the same checks as the $levels commands:
Levels.save_settings() and the limits in cogs/levels.py.

Paper Premium is sold here too (billing.py): Upgrade opens a Stripe
Checkout page, and Stripe reports back to /stripe/webhook, which is checked
against Stripe's signature before anything is believed.

It also serves /api/servers, the public list of servers the bot is in, for
the scrolling strip on the website. Only a server's name, icon and member
count go out, and any server can leave the list with `$sitelist off`.
"""
import asyncio
import base64
import json
import logging
import os
import secrets
import time

import discord
from aiohttp import web
from discord.ext import commands

import billing
import botprofile
import oauth
import webparts
import premium
from cogs.admin import is_bot_owner
from cogs.levels import BOOST_PLACES, BOOST_RANGE

from cogs.levels import (DEFAULT_MESSAGE, KARUDA_EVERY, MAX_LEVEL,
                         MESSAGE_LIMIT, MESSAGE_VARIABLES, SETTINGS, level_for,
                         total_for, validate)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "dashboard", "index.html")
LOGO = os.path.join(ROOT, "dashboard", "paper.png")
LINK_LIFETIME = 3600
MAX_LEVEL_ROLES = 100
SHOWCASE_CACHE = 300        # seconds the public server list is reused for
SHOWCASE_LIMIT = 60
SESSION_COOKIE = "yuri_session"
STATE_COOKIE = "yuri_state"
NEXT_COOKIE = "paper_next"
SESSION_DAYS = 7
# Where the dashboard's Home link goes: the public website.
SITE_URL = os.getenv("SITE_URL", "https://gachabot.perc-1fc.workers.dev").rstrip("/")
log = logging.getLogger("dashboard")

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


def handover(person: dict) -> str:
    """A display name and picture for the website's nav, in its link. Shown
    there, never trusted: see the chip in tools/build_site.py."""
    raw = json.dumps({"n": person["name"], "a": person.get("avatar") or ""})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def redirect(location: str):
    """A 302 as an ordinary response, so cookies can be set on it."""
    return web.Response(status=302, headers={**HEADERS, "Location": location})


def problem(status: int, message: str):
    return web.json_response({"problems": [message]}, status=status,
                             headers=HEADERS)


class Dashboard(commands.Cog):
    works_everywhere = True  # an admin command; see cogs/modtools.py

    def __init__(self, bot):
        self.bot = bot
        self.links = {}  # token -> {"guild", "user", "expires"}
        self.runner = None
        self.showcase_cache = (0, None)  # (when, response body)

    async def cog_load(self):
        self.price_task = asyncio.create_task(self.load_price())
        port = os.getenv("PORT")
        if not port:
            return
        # Room for an 8 MB rank card picture, which grows by a third when
        # the browser encodes it to send.
        app = web.Application(client_max_size=12 * 1024 * 1024)
        app.router.add_get("/", self.home)
        app.router.add_get("/dashboard", self.page)
        app.router.add_get("/paper.png", self.logo)
        app.router.add_get("/login", self.login)
        app.router.add_get("/callback", self.callback)
        app.router.add_post("/logout", self.logout)
        app.router.add_get("/api/me", self.api_me)
        app.router.add_get("/api/overview", self.api_overview)
        app.router.add_post("/api/premium/checkout", self.api_checkout)
        app.router.add_post("/api/premium/portal", self.api_portal)
        app.router.add_get("/api/cases.csv", self.api_cases)
        app.router.add_post("/api/events", self.api_event_add)
        app.router.add_post("/api/events/{event}/stop", self.api_event_stop)
        app.router.add_post("/api/rankbg", self.api_rankbg)
        app.router.add_get("/api/rankbg.jpg", self.api_rankbg_get)
        app.router.add_post("/api/botprofile", self.api_botprofile)
        app.router.add_post("/stripe/webhook", self.stripe_webhook)
        app.router.add_get("/api/part/{part}", self.api_part_get)
        app.router.add_post("/api/part/{part}", self.api_part_save)
        app.router.add_get("/api/levels", self.api_get)
        app.router.add_post("/api/levels", self.api_save)
        app.router.add_post("/api/levels/sync", self.api_sync)
        app.router.add_get("/api/servers", self.api_servers)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, "0.0.0.0", int(port)).start()

    async def cog_unload(self):
        self.price_task.cancel()
        if self.runner:
            await self.runner.cleanup()

    async def load_price(self):
        """The plans' prices from Stripe, for buttons and $upgrade. Doesn't
        hold up the bot starting. Read again every few minutes while any
        plan on sale has no price yet (Stripe was briefly unreachable, or
        the variables were being changed), and hourly after, so a price
        changed in Stripe shows up without a restart."""
        while True:
            try:
                await billing.load_price_label()
            except (billing.BillingError, OSError, asyncio.TimeoutError):
                log.warning("couldn't read the plans' prices from Stripe")
            missing = [p for p in billing.PLANS
                       if billing.plan_on_sale(p) and not billing.plan_label(p)]
            await asyncio.sleep(300 if missing else 3600)

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

    @commands.command(name="upgrade", aliases=["serverpremium", "papergold"])
    @commands.guild_only()
    async def upgrade(self, ctx):
        """Whether this server has Paper Premium, and how to get it."""
        db = self.bot.db
        base = public_url()
        link = f"{base}/dashboard?guild={ctx.guild.id}" if base else ""
        tier = db.premium_tier(ctx.guild.id)
        plans = "\n".join(
            f"**{name}**" + (f" ({billing.plan_label(key)})" if billing.plan_label(key) else "")
            + f": {line}"
            for key, (_env, _mode, _tier, name, line) in billing.PLANS.items()
            if billing.plan_on_sale(key) and billing.RANK[key] > billing.RANK.get(tier, 0))
        if tier:
            row = db.premium_of(ctx.guild.id)
            name = billing.PLANS[tier][3]
            text = (f"\u2728 **{ctx.guild.name}** has {name} for good. Thank you!"
                    if tier == "lifetime" else
                    f"\u2728 **{ctx.guild.name}** has {name} until <t:{row['until']}:D>.")
            if plans:
                text += "\n\nGo further:\n" + plans + f"\n-# {billing.PRICE_NOTE}"
            if link:
                text += f"\nManage it on the dashboard: <{link}>"
        else:
            text = ("\u2728 **Paper Premium** for this server. Everything in Paper"
                    " stays free; Premium adds these for everyone here:\n\n"
                    + premium.perk_lines())
            if billing.configured():
                text += (f"\n\n{plans}\n-# {billing.PRICE_NOTE}\n\nTry Premium free for {billing.TRIAL_DAYS} days."
                         + (f" An admin can pick a plan on the dashboard: <{link}>" if link else ""))
            else:
                text += "\n\nIt isn't on sale just yet."
        await ctx.send(text[:2000], allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="giveplan", aliases=["grantpremium"])
    @is_bot_owner()
    async def giveplan(self, ctx, guild_id: int, plan: str, days: int = 30):
        """Owner only: give a server premium, plus or lifetime (days for the
        first two, 30 by default), or `off` to take it away."""
        db = self.bot.db
        plan = plan.lower()
        if plan == "off":
            db.set_premium(guild_id, status="canceled", until=int(time.time()),
                           customer="", subscription="")
            await ctx.send(f"Server {guild_id} has no plan now.")
            return
        if plan not in billing.PLANS:
            await ctx.send("Say premium, plus, lifetime or off.")
            return
        lifetime = plan == "lifetime"
        until = billing.FOREVER if lifetime else int(time.time()) + days * 86400
        db.set_premium(guild_id, status="lifetime" if lifetime else "active", until=until,
                       customer="", subscription="", tier=plan)
        guild = self.bot.get_guild(guild_id)
        await ctx.send(f"**{guild.name if guild else guild_id}** has"
                       f" {billing.PLANS[plan][3]}"
                       + (" for good." if lifetime else f" until <t:{until}:D>."))

    # ------------------------------------------------------------- promo

    def promo_embed(self, prefix: str) -> discord.Embed:
        """The advert: what Paper does and how to add it, in one box."""
        me = self.bot.user
        name = me.display_name if me else "Paper"
        total = self.bot.db.character_count()
        embed = discord.Embed(
            colour=0xF47FFF,
            description=(
                f"**Add {name} to your server** \u2014 a gacha, moderation, voice"
                f" rooms and levels, in one bot.\n\n"
                f"\U0001f3b2 **Gacha:** roll and claim from {total:,} characters,"
                " Mudae style, with wishes, trades, badges and a karuda tower\n"
                "\U0001f6e1\ufe0f **Moderation:** jail, mutes, warnings, bans, automod,"
                " an antinuke and staff points\n"
                "\U0001f50a **Voice:** Join To Create rooms people run themselves,"
                " and voice hours\n"
                "\U0001f4c8 **Levels:** XP for chat and voice, level roles, and"
                " stats cards\n"
                "\U0001f44b **Server tools:** autoroles, welcomes, reaction roles,"
                " snipes, reminders\n\n"
                "**How to add it**\n"
                "1. Press **Free** below and pick your server\n"
                f"2. Type `{prefix}help` there to see everything\n"
                f"3. Set it up on the web with `{prefix}dashboard`\n\n"
                "Everything above is free. Premium adds extras for your whole server,"
                " and Lifetime is paid once, never again."))
        if me:
            embed.set_author(name=name, icon_url=me.display_avatar.url)
            embed.set_thumbnail(url=me.display_avatar.with_size(256).url)
        embed.set_footer(text=f"{name} \u00b7 {SITE_URL.split('//')[-1]}",
                         icon_url=me.display_avatar.url if me else None)
        return embed

    def promo_buttons(self) -> discord.ui.View:
        """Link buttons: Free is the invite, the rest open the Premium page."""
        from cogs.profile import INVITE_PERMISSIONS
        view = discord.ui.View(timeout=None)
        if self.bot.user:
            view.add_item(discord.ui.Button(
                label="Free", emoji="\u2728", style=discord.ButtonStyle.link,
                url=discord.utils.oauth_url(self.bot.user.id, permissions=INVITE_PERMISSIONS,
                                            scopes=("bot",))))
        base = public_url()
        if base:
            for plan, fallback in (("premium", "$3.50/mo"), ("plus", "$10.50/mo"),
                                   ("lifetime", "$35 once")):
                price = (billing.plan_label(plan).replace(" a month", "/mo")
                         .replace(".00", "") or fallback)
                name = {"premium": "Premium", "plus": "Plus", "lifetime": "Lifetime"}[plan]
                view.add_item(discord.ui.Button(
                    label=f"{name} \u00b7 {price}", style=discord.ButtonStyle.link,
                    url=f"{base}/dashboard?premium=1&plan={plan}"))
        return view

    @commands.command(name="promo", aliases=["addpanel", "invitepanel", "advert"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def promo(self, ctx, channel: discord.TextChannel = None):
        """Post a panel about Paper with buttons to add it or buy Premium,
        here or in the channel you name."""
        channel = channel or ctx.channel
        try:
            await channel.send(embed=self.promo_embed(ctx.prefix), view=self.promo_buttons())
        except discord.HTTPException:
            await ctx.send(f"I can't post in {channel.mention}. Give me Send Messages and"
                           " Embed Links there.")
            return
        if channel != ctx.channel:
            await ctx.send(f"Posted in {channel.mention}.")

    # ---------------------------------------------------------- showcase

    def shown(self, guild) -> bool:
        return bool(self.bot.db.get_pref(guild.id, "showcase", 1))

    @commands.command(name="sitelist", aliases=["website"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def sitelist(self, ctx, state: str = None):
        """Whether this server appears in the list on the bot's website."""
        if state is None:
            await ctx.send("This server is "
                           + ("shown" if self.shown(ctx.guild) else "hidden")
                           + f" on the bot's website. `{ctx.prefix}sitelist off`"
                           f" hides it, `{ctx.prefix}sitelist on` shows it.")
            return
        state = state.lower()
        if state not in ("on", "off"):
            await ctx.send("Say `on` or `off`.")
            return
        self.bot.db.set_pref(ctx.guild.id, "showcase", 1 if state == "on" else 0)
        self.showcase_cache = (0, None)
        await ctx.send("This server is " + ("back on" if state == "on" else "off")
                       + " the bot's website. It updates within a few minutes.")

    def showcase_body(self) -> dict:
        guilds = [g for g in self.bot.guilds if self.shown(g)]
        guilds.sort(key=lambda g: g.member_count or 0, reverse=True)
        return {
            # Totals cover every server, listed or not: they say nothing
            # about any one of them.
            "users": sum(g.member_count or 0 for g in self.bot.guilds),
            "servers": len(self.bot.guilds),
            "list": [{"name": g.name,
                      "icon": g.icon.with_size(128).url if g.icon else None,
                      "members": g.member_count or 0}
                     for g in guilds[:SHOWCASE_LIMIT]],
        }

    async def api_servers(self, request):
        """Public, read-only, and the same for everyone, so any site may read
        it and it's rebuilt at most every few minutes."""
        when, body = self.showcase_cache
        if body is None or time.time() - when > SHOWCASE_CACHE:
            body = self.showcase_body()
            self.showcase_cache = (time.time(), body)
        return web.json_response(body, headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": f"public, max-age={SHOWCASE_CACHE}",
            "X-Content-Type-Options": "nosniff",
        })

    # ------------------------------------------------------------- login

    def client_id(self) -> int:
        return int(os.getenv("DISCORD_CLIENT_ID") or self.bot.application_id
                   or (self.bot.user.id if self.bot.user else 0))

    def redirect_url(self) -> str:
        return f"{public_url()}/callback"

    def cookie_options(self, max_age: int) -> dict:
        return {"max_age": max_age, "httponly": True, "samesite": "Lax",
                "secure": public_url().startswith("https://"), "path": "/"}

    def session_of(self, request):
        token = request.cookies.get(SESSION_COOKIE, "")
        return self.bot.db.web_session(oauth.hash_token(token)) if token else None

    async def login(self, request):
        if not oauth.configured() or not public_url():
            return redirect("/dashboard?login=off")
        state = secrets.token_urlsafe(24)
        response = redirect(oauth.authorize_url(
            self.client_id(), self.redirect_url(), state))
        response.set_cookie(STATE_COOKIE, state, **self.cookie_options(600))
        # Logging in from the website goes back to the website afterwards.
        # Only ever to SITE_URL: where to go is a word, not an address.
        if request.query.get("next") in ("site", "premium"):
            response.set_cookie(NEXT_COOKIE, request.query["next"],
                                **self.cookie_options(600))
        return response

    async def callback(self, request):
        state = request.cookies.get(STATE_COOKIE, "")
        # Checked before anything else: a callback this browser didn't ask
        # for is someone trying to log it in as them.
        if not state or not secrets.compare_digest(
                state, request.query.get("state", "")):
            return redirect("/dashboard?login=failed")
        code = request.query.get("code")
        if not code:  # they pressed Cancel on Discord's page
            return redirect("/dashboard")
        try:
            person = await oauth.log_in(self.client_id(), self.redirect_url(), code)
        except (oauth.LoginFailed, OSError, ValueError, KeyError):
            return redirect("/dashboard?login=failed")
        token = secrets.token_urlsafe(32)
        self.bot.db.add_web_session(
            oauth.hash_token(token), person["id"], person["name"],
            person["avatar"], oauth.dump_guilds(person["guilds"]),
            int(time.time()) + SESSION_DAYS * 86400)
        going = "/dashboard"
        if request.cookies.get(NEXT_COOKIE) == "site":
            going = SITE_URL + "#me=" + handover(person)
        elif request.cookies.get(NEXT_COOKIE) == "premium":
            going = "/dashboard?premium=1"
        response = redirect(going)
        response.set_cookie(SESSION_COOKIE, token,
                            **self.cookie_options(SESSION_DAYS * 86400))
        response.del_cookie(STATE_COOKIE, path="/")
        response.del_cookie(NEXT_COOKIE, path="/")
        return response

    async def logout(self, request):
        if request.headers.get("X-Paper") != "1":
            return problem(403, "Log out from the dashboard page.")
        token = request.cookies.get(SESSION_COOKIE, "")
        if token:
            self.bot.db.end_web_session(oauth.hash_token(token))
        response = web.json_response({"ok": True}, headers=HEADERS)
        response.del_cookie(SESSION_COOKIE, path="/")
        return response

    async def api_me(self, request):
        """Who's logged in and the servers they can manage."""
        session = self.session_of(request)
        if not session:
            return web.json_response(
                {"user": None, "login": oauth.configured() and bool(public_url()),
                 "site": SITE_URL},
                headers=HEADERS)
        servers = []
        for g in json.loads(session["guilds"]):
            guild = self.bot.get_guild(int(g["id"]))
            # What Discord said at login goes stale when a server changes its
            # icon (the old link stops working), so where Paper is in the
            # server, its own up-to-date copy wins.
            if guild is not None:
                name = guild.name
                icon = guild.icon.replace(size=128).url if guild.icon else None
            else:
                name = g["name"]
                icon = (f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=96"
                        if g.get("icon") else None)
            servers.append({"id": g["id"], "name": name, "icon": icon,
                            "has_bot": guild is not None,
                            "premium": bool(guild) and self.bot.db.is_premium(guild.id),
                            "trial": bool(guild) and self.bot.db.trial_available(guild.id)})
        servers.sort(key=lambda s: (not s["has_bot"], s["name"].lower()))
        invite = discord.utils.oauth_url(self.client_id(), scopes=("bot",),
                                         permissions=self.invite_permissions())
        return web.json_response({
            "user": {"name": session["name"], "avatar": session["avatar"]},
            "servers": servers,
            "invite": invite,
            "site": SITE_URL,
            "premium_sale": {"for_sale": billing.configured(),
                             "price": billing.price_label(),
                             "plans": self.plans(),
                             "price_note": billing.PRICE_NOTE,
                             "trial_days": billing.TRIAL_DAYS,
                             "perks": premium.perk_groups()},
        }, headers=HEADERS)

    def invite_permissions(self):
        try:
            from cogs.profile import INVITE_PERMISSIONS
            return INVITE_PERMISSIONS
        except ImportError:
            return discord.Permissions.none()

    def who(self, request):
        """(guild, member, Levels cog) for a request, or an error response.

        A private link names its own server. A logged-in session names it
        with ?guild=, and must send X-Paper with anything that changes."""
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            entry = self.links.get(header[7:])
            if not entry or entry["expires"] < time.time():
                return None, problem(401, "This link has expired. Run"
                                          " $dashboard in Discord for a new"
                                          " one, or log in instead.")
            guild_id, user_id = entry["guild"], entry["user"]
        else:
            session = self.session_of(request)
            if not session:
                return None, problem(401, "You're logged out. Log in again.")
            if request.method != "GET" and request.headers.get("X-Paper") != "1":
                return None, problem(403, "Save from the dashboard page.")
            try:
                guild_id = int(request.query.get("guild", ""))
            except ValueError:
                return None, problem(400, "Pick a server first.")
            user_id = session["user_id"]
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(user_id) if guild else None
        if not member or not member.guild_permissions.manage_guild:
            return None, problem(403, "You need Manage Server on this server.")
        levels = self.bot.get_cog("Levels")
        if not levels:
            return None, problem(503, "Levels are switched off on this bot.")
        return (guild, member, levels), None

    # --------------------------------------------------------------- pages

    async def home(self, request):
        return redirect("/dashboard")

    async def logo(self, request):
        return web.FileResponse(LOGO, headers={"Cache-Control": "public, max-age=86400"})

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
            "premium": self.bot.db.is_premium(guild.id),
            "boosts": [{"role": str(r["role_id"]), "percent": r["percent"]}
                       for r in self.bot.db.level_boosts_of(guild.id)],
            "boost_range": list(BOOST_RANGE),
            # Channels and categories a boost can be on, beside the roles.
            "boost_places": [{"id": str(c.id), "name": c.name,
                              "category": isinstance(c, discord.CategoryChannel),
                              "voice": isinstance(c, (discord.VoiceChannel,
                                                      discord.StageChannel))}
                             for c in sorted(guild.channels, key=lambda c: (
                                 not isinstance(c, discord.CategoryChannel),
                                 c.position))
                             if isinstance(c, BOOST_PLACES)],
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

        boosts = body.get("boosts")
        boost_pairs = []
        if boosts is not None:
            if boosts and not self.bot.db.is_premium(guild.id):
                problems.append("XP boosts are a Premium feature.")
            low, high = BOOST_RANGE
            seen_roles = set()
            for row in boosts if isinstance(boosts, list) else []:
                try:
                    role_id, percent = int(row["role"]), int(row["percent"])
                except (TypeError, ValueError, KeyError):
                    problems.append("Every XP boost needs a role or channel,"
                                    " and a percent.")
                    continue
                # A role, or a channel or category: ids never clash.
                role = guild.get_role(role_id)
                place = guild.get_channel(role_id)
                if not isinstance(place, BOOST_PLACES):
                    place = None
                if not (role or place) or (role and role.is_default()):
                    problems.append("XP boosts need a role or channel from this server.")
                elif role_id in seen_roles:
                    problems.append(f"{(role or place).name} has two boosts. Pick one.")
                elif not low <= percent <= high:
                    problems.append(f"Boosts go from {low}% to {high}%.")
                else:
                    seen_roles.add(role_id)
                    boost_pairs.append((role_id, percent))

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
        if boosts is not None:
            self.bot.db.replace_level_boosts(guild.id, boost_pairs)
        return web.json_response(self.state(guild, levels), headers=HEADERS)

    async def api_overview(self, request):
        """The server's name and a line or two about each part."""
        found, error = self.who(request)
        if error:
            return error
        guild = found[0]
        return web.json_response({
            "guild": {"name": guild.name,
                      "icon": guild.icon.url if guild.icon else None},
            "parts": webparts.overview(self.bot, guild),
            "premium": self.premium_state(guild),
            "site": SITE_URL,
        }, headers=HEADERS)

    # ------------------------------------------------------------ premium

    def plans(self, guild=None) -> list:
        """The plans, cheapest first, and which this server has already."""
        tier = self.bot.db.premium_tier(guild.id) if guild else None
        have = billing.RANK.get(tier, 0)
        return [{"key": key, "name": name, "line": line, "price": billing.plan_label(key),
                 "on_sale": billing.plan_on_sale(key), "once": mode == "payment",
                 "owned": billing.RANK[key] <= have}
                for key, (_env, mode, _tier, name, line) in billing.PLANS.items()]

    def premium_state(self, guild) -> dict:
        row = self.bot.db.premium_of(guild.id)
        active = self.bot.db.is_premium(guild.id)
        tier = self.bot.db.premium_tier(guild.id)
        return {
            "active": active,
            "tier": tier,
            "tier_name": billing.PLANS[tier][3] if tier else "",
            "plans": self.plans(guild),
            "until": row["until"] if row and active else 0,
            # A cancelled subscription still runs to the end of the month.
            "ending": bool(row and active and row["status"] not in
                           ("active", "trialing", "lifetime")),
            "billing": bool(row and row["customer"]),
            "for_sale": billing.configured(),
            "price": billing.price_label(),
            "price_note": billing.PRICE_NOTE,
            "trial": billing.configured() and self.bot.db.trial_available(guild.id),
            "trial_days": billing.TRIAL_DAYS,
            "trialing": bool(row and active and row["status"] == "trialing"),
            "perks": premium.perk_groups(),
        }

    async def api_checkout(self, request):
        found, error = self.who(request)
        if error:
            return error
        guild, member = found[0], found[1]
        try:
            body = await request.json()
        except ValueError:
            body = {}
        plan = (body or {}).get("plan") or "premium"
        if plan not in billing.PLANS:
            return problem(400, "There's no such plan.")
        if not billing.plan_on_sale(plan):
            return problem(503, f"{billing.PLANS[plan][3]} isn't on sale yet.")
        tier = self.bot.db.premium_tier(guild.id)
        if billing.RANK.get(tier, 0) >= billing.RANK[plan]:
            return problem(409, f"This server has {billing.PLANS[tier][3]} already.")
        back = f"{public_url()}/dashboard?guild={guild.id}"
        row = self.bot.db.premium_of(guild.id)
        try:
            url = await billing.checkout(
                guild.id, guild.name, member.id,
                success_url=back + "&premium=thanks", cancel_url=back,
                customer=row["customer"] if row else "",
                trial=plan == "premium" and self.bot.db.trial_available(guild.id),
                plan=plan)
        except (billing.BillingError, OSError) as e:
            return problem(502, f"Couldn't start the payment: {e}")
        return web.json_response({"url": url}, headers=HEADERS)

    async def api_portal(self, request):
        found, error = self.who(request)
        if error:
            return error
        guild = found[0]
        row = self.bot.db.premium_of(guild.id)
        if not row or not row["customer"]:
            return problem(404, "This server has no billing to manage.")
        try:
            url = await billing.portal(row["customer"],
                                       f"{public_url()}/dashboard?guild={guild.id}")
        except (billing.BillingError, OSError) as e:
            return problem(502, f"Couldn't open billing: {e}")
        return web.json_response({"url": url}, headers=HEADERS)

    async def stripe_webhook(self, request):
        payload = await request.read()
        try:
            event = billing.verify(payload, request.headers.get("Stripe-Signature", ""))
        except (billing.BadSignature, ValueError):
            return web.Response(status=400, text="bad signature")
        try:
            await billing.handle(self.bot.db, event)
        except (billing.BillingError, OSError, ValueError, KeyError):
            # A 500 makes Stripe send it again later, which is what we want.
            return web.Response(status=500, text="try again")
        return web.Response(text="ok")

    async def api_cases(self, request):
        """Premium: every moderation case, as a spreadsheet."""
        found, error = self.who(request)
        if error:
            return error
        guild = found[0]
        if not self.bot.db.is_premium(guild.id):
            return problem(402, "Case history export is a Premium feature.")
        import csv
        import io
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["case", "when (UTC)", "action", "member id", "moderator id",
                         "reason", "duration (seconds)"])
        rows = self.bot.db.conn.execute(
            "SELECT * FROM mod_cases WHERE guild_id = ? ORDER BY id",
            (guild.id,)).fetchall()
        for row in rows:
            writer.writerow([row["id"], time.strftime("%Y-%m-%d %H:%M:%S",
                                                      time.gmtime(row["created_at"])),
                             row["action"], str(row["user_id"]), str(row["mod_id"]),
                             row["reason"], row["duration"]])
        return web.Response(
            text=out.getvalue(), content_type="text/csv",
            headers={**HEADERS, "Content-Disposition":
                     f'attachment; filename="paper-cases-{guild.id}.csv"'})

    async def api_event_add(self, request):
        found, error = self.who(request)
        if error:
            return error
        guild, member = found[0], found[1]
        events = self.bot.get_cog("Events")
        try:
            body = await request.json()
            kind = str(body["kind"])
            strength = int(body["strength"])
            starts_at = int(body.get("starts_at") or time.time())
            length = int(float(body["hours"]) * 3600)
            channel = int(body.get("channel") or 0)
        except (ValueError, KeyError, TypeError):
            return problem(400, "Fill in every part of the event.")
        if channel and not isinstance(guild.get_channel(channel), discord.TextChannel):
            return problem(400, "Pick a text channel in this server to announce it in.")
        if not events:
            return problem(503, "Events are switched off on this bot.")
        why = events.schedule(guild.id, kind, strength, starts_at, length, channel, member.id)
        if why:
            return problem(400, why)
        return web.json_response(webparts.extras_state(self.bot, guild), headers=HEADERS)

    async def api_event_stop(self, request):
        found, error = self.who(request)
        if error:
            return error
        guild = found[0]
        try:
            event_id = int(request.match_info["event"])
        except ValueError:
            return problem(404, "There's no such event.")
        if not self.bot.db.end_event(guild.id, event_id):
            return problem(404, "That event has already ended.")
        return web.json_response(webparts.extras_state(self.bot, guild), headers=HEADERS)

    async def api_rankbg(self, request):
        """Premium: set or clear the server's rank card background."""
        found, error = self.who(request)
        if error:
            return error
        guild = found[0]
        import asyncio
        import base64
        import rankcard
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "That wasn't valid JSON.")
        if body.get("image") is None:
            self.bot.db.set_rank_background(guild.id, 0, None)
        else:
            if not self.bot.db.is_premium(guild.id):
                return problem(402, "Custom rank cards come with Premium.")
            try:
                raw = base64.b64decode(str(body["image"]).split(",")[-1], validate=True)
                image = await asyncio.to_thread(rankcard.prepare_background, raw)
            except (ValueError, rankcard.BadImage) as e:
                return problem(400, str(e) if isinstance(e, rankcard.BadImage)
                               else "That picture didn't come through. Try again.")
            self.bot.db.set_rank_background(guild.id, 0, image)
        return web.json_response(webparts.extras_state(self.bot, guild), headers=HEADERS)

    async def api_botprofile(self, request):
        """Paper's own name, picture, banner and bio on this server. Acts at
        once, like the rank card background. The name is free; the rest is
        Premium (botprofile.update checks)."""
        found, error = self.who(request)
        if error:
            return error
        guild, member = found[0], found[1]
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "That wasn't valid JSON.")
        if not isinstance(body, dict):
            return problem(400, "That wasn't valid JSON.")
        reason = f"Dashboard, by {member} ({member.id})"
        try:
            if body.get("reset"):
                await botprofile.reset(self.bot, guild, reason)
            else:
                fields = {}
                for key in ("nick", "bio"):
                    if key in body:
                        if body[key] is not None and not isinstance(body[key], str):
                            return problem(400, "That has to be text.")
                        fields[key] = body[key]
                for key in ("avatar", "banner"):
                    if key in body:
                        if body[key] is None:
                            fields[key] = None
                            continue
                        try:
                            fields[key] = base64.b64decode(
                                str(body[key]).split(",")[-1], validate=True)
                        except ValueError:
                            return problem(400, "That picture didn't come through. Try again.")
                await botprofile.update(self.bot, guild, reason, **fields)
        except botprofile.ProfileError as e:
            return problem(402 if "Premium" in str(e) else 400, str(e))
        return web.json_response(webparts.extras_state(self.bot, guild), headers=HEADERS)

    async def api_rankbg_get(self, request):
        found, error = self.who(request)
        if error:
            return error
        image = self.bot.db.rank_background(found[0].id, 0)
        if not image:
            return problem(404, "No background set.")
        return web.Response(body=image, content_type="image/jpeg",
                            headers={"Cache-Control": "no-store"})

    async def api_part_get(self, request):
        part = webparts.PARTS.get(request.match_info["part"])
        if not part:
            return problem(404, "There's no such page.")
        found, error = self.who(request)
        if error:
            return error
        return web.json_response(part[0](self.bot, found[0]), headers=HEADERS)

    async def api_part_save(self, request):
        name = request.match_info["part"]
        part = webparts.PARTS.get(name)
        if not part:
            return problem(404, "There's no such page.")
        found, error = self.who(request)
        if error:
            return error
        guild = found[0]
        try:
            body = await request.json()
        except ValueError:
            return problem(400, "That wasn't valid JSON.")
        if not isinstance(body, dict):
            return problem(400, "That wasn't valid JSON.")
        problems = part[1](self.bot, guild, body)
        if problems:
            return web.json_response({"problems": problems}, status=400,
                                     headers=HEADERS)
        if name == "mod" and body.get("staff_roles") is not None:
            # New staff roles get into the jail and the mod log, as they do
            # when they're added with $staffroles.
            modtools = self.bot.get_cog("ModTools")
            if modtools:
                try:
                    await modtools.show_staff_the_rooms(guild)
                except discord.HTTPException:
                    pass
        return web.json_response(part[0](self.bot, guild), headers=HEADERS)

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
