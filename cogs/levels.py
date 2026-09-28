"""Levels: XP for chatting and for time in voice.

By default chatting pays 15-25 XP, at most once a minute, so a wall of spam
earns the same as one message. Commands don't count; nobody should level up
by rolling.

Voice pays 10 XP a minute by default, but only with someone else in the
channel, not deafened, and not in the AFK channel, and only up to a daily
cap, so sitting in a call all day can't outrun the people talking.

Every one of those numbers is a server setting, within the limits in
SETTINGS. The $levels commands and the web dashboard (cogs/dashboard.py) both
save through save_settings(), so neither can store something the other
would reject.

Each level needs a bit more than the last, on MEE6's curve: level 5 is about
an hour of steady chat, level 50 is months.

Karuda is deliberately scarce: a flat amount every KARUDA_EVERY levels and
nothing in between, paid once per milestone for good. A daily already pays
more than a milestone does, so levels are a thank-you, not an income.
"""
import asyncio
import difflib
import io
import logging
import random
import re
import time
import typing

import discord
from discord.ext import commands, tasks

import config
import rankcard
import utils
import weekly
from views import Confirm, Paginator

KARUDA_EVERY = 5            # levels between karuda payouts
MAX_LEVEL = 500
BOOST_RANGE = (105, 300)    # Premium XP boosts, as a percent
# What an XP boost can be on. Roles first, so a bare name finds the role.
BOOST_PLACES = (discord.TextChannel, discord.VoiceChannel, discord.StageChannel,
                discord.ForumChannel, discord.CategoryChannel)
BoostTarget = typing.Union[discord.Role, discord.TextChannel, discord.VoiceChannel,
                           discord.StageChannel, discord.ForumChannel,
                           discord.CategoryChannel]

# key: (default, lowest, highest, what it is)
SETTINGS = {
    "msg_min": (15, 0, 100, "Least XP a message gives"),
    "msg_max": (25, 0, 100, "Most XP a message gives"),
    "cooldown": (60, 0, 3600, "Seconds before someone's next message counts"),
    "voice": (1, 0, 1, "XP for time in voice"),
    "voice_xp": (10, 0, 100, "Voice XP per minute"),
    "voice_cap": (600, 0, 10_000, "Most voice XP a day"),
    # Kept small on purpose: a daily pays more than a milestone does.
    "karuda": (100, 0, 250, f"Karuda every {KARUDA_EVERY} levels"),
    "stack": (1, 0, 1, "Keep lower level roles"),
    "levelup_card": (1, 0, 1, "Show the rank card with level-ups"),
    # A channel id, 0 for wherever they levelled up, -1 for nowhere.
    "channel": (0, -1, 2 ** 63 - 1, "Where level-ups are announced"),
}
DEFAULT_MESSAGE = "\U0001f389 {user} reached **level {level}**!"
MESSAGE_VARIABLES = ("{user}", "{user.name}", "{level}", "{server}")
MESSAGE_LIMIT = 500


def validate(key: str, value) -> str:
    """Why this value can't be saved for this setting, or ''."""
    if key not in SETTINGS:
        return f"There's no level setting called `{key}`."
    try:
        value = int(value)
    except (TypeError, ValueError):
        return f"{SETTINGS[key][3]} has to be a whole number."
    _default, low, high, label = SETTINGS[key]
    if not low <= value <= high:
        return f"{label} has to be from {low:,} to {high:,}."
    return ""


def render_message(template: str, member, level: int) -> str:
    return (template.replace("{user.name}", member.display_name)
            .replace("{user}", member.mention)
            .replace("{level}", str(level))
            .replace("{server}", member.guild.name))[:1800]


def xp_to_next(level: int) -> int:
    """XP needed to go from this level to the next one."""
    return 5 * level * level + 50 * level + 100


def level_for(xp: int) -> tuple:
    """(level, XP into that level, XP the level needs) for a total."""
    level = 0
    while level < MAX_LEVEL and xp >= xp_to_next(level):
        xp -= xp_to_next(level)
        level += 1
    return level, xp, xp_to_next(level)


def total_for(level: int) -> int:
    """The total XP that reaching a level takes."""
    return sum(xp_to_next(n) for n in range(level))


def bar(done: int, whole: int, width: int = 14) -> str:
    filled = round(width * done / whole) if whole else width
    return "▰" * filled + "▱" * (width - filled)


def today() -> int:
    return int(time.time() // 86400)


def month_now(when: float = None) -> int:
    """This calendar month in UTC, as YYYYMM."""
    t = time.gmtime(time.time() if when is None else when)
    return t.tm_year * 100 + t.tm_mon


def month_before(month: int) -> int:
    year, mon = divmod(month, 100)
    return (year - 1) * 100 + 12 if mon == 1 else month - 1


def month_name(month: int) -> str:
    return time.strftime("%B %Y", time.strptime(str(month), "%Y%m"))


IMPORT_LINE = re.compile(r"^\s*(?:#?\d+[.)]?\s+)?@?(\S+?)[\s,;:|]+(?:level\s*)?(\d+)\b",
                         re.IGNORECASE)


def parse_import(text: str) -> list:
    """[(username, level), ...] from lines like `1. @name 32` or `name,32`.

    Order is kept: it's the old bot's ranking, best first.
    """
    rows, seen = [], set()
    for line in (text or "").splitlines():
        match = IMPORT_LINE.match(line)
        if not match:
            continue
        name, level = match.group(1).lower(), int(match.group(2))
        if name in seen or not 0 <= level <= MAX_LEVEL:
            continue
        seen.add(name)
        rows.append((name, level))
    return rows


def rows_index(rows: list, name: str) -> int:
    return next(i for i, (n, _level) in enumerate(rows) if n == name)


def match_members(rows: list, members) -> tuple:
    """Pair imported usernames with members.

    Returns (exact, guessed, missing): exact and guessed are lists of
    (name, member, level). A guess is a close spelling that points at one
    member only, for names read off a screenshot a letter wrong; they're
    shown to whoever is importing before anything changes.
    """
    people = [m for m in members if not m.bot]
    by_name = {m.name.lower(): m for m in people}
    exact, guessed, missing, taken = [], [], [], set()
    for name, level in rows:
        member = by_name.get(name)
        if member and member.id not in taken:
            exact.append((name, member, level))
            taken.add(member.id)
    for name, level in rows:
        if name in by_name:
            continue
        free = [n for n, m in by_name.items() if m.id not in taken]
        close = difflib.get_close_matches(name, free, n=2, cutoff=0.85)
        if len(close) == 1:
            member = by_name[close[0]]
            guessed.append((name, member, level))
            taken.add(member.id)
        else:
            missing.append(name)
    return exact, guessed, missing


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_counted = {}  # (guild, user) -> when a message last paid
        self.pruned_for = 0     # the month old monthly XP was last cleared in

    @property
    def db(self):
        return self.bot.db

    async def cog_load(self):
        self.voice_xp.start()

    async def cog_unload(self):
        self.voice_xp.cancel()

    async def cog_check(self, ctx):
        # A group's own checks don't run for its subcommands, and every one
        # of these needs a server.
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    def colour(self, guild_id: int) -> int:
        return self.db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR)

    def setting(self, guild_id: int, key: str) -> int:
        return self.db.get_level_setting(guild_id, key, SETTINGS[key][0])

    def settings_of(self, guild_id: int) -> dict:
        return {key: self.setting(guild_id, key) for key in SETTINGS}

    def message_of(self, guild_id: int) -> str:
        return self.db.get_level_text(guild_id, "message", DEFAULT_MESSAGE)

    def save_settings(self, guild_id: int, changes: dict) -> list:
        """Check every change, then save them all or none. Returns problems."""
        problems = [p for key, value in changes.items()
                    if (p := validate(key, value))]
        if not problems:
            merged = {**self.settings_of(guild_id), **changes}
            if int(merged["msg_min"]) > int(merged["msg_max"]):
                problems.append("The least XP a message gives can't be more"
                                " than the most.")
        if not problems:
            for key, value in changes.items():
                self.db.set_level_setting(guild_id, key, int(value))
        return problems

    # ------------------------------------------------------------ earning

    def boosted(self, member, amount: int, channel=None) -> int:
        """Premium servers: the best boost role a member has, times the
        boost of the channel they earned it in (or its category), times any
        XP event running now.

        Role and channel boosts share one table: a Discord id is never both
        a role and a channel, so the ids can't collide."""
        guild_id = member.guild.id
        if not self.db.is_premium(guild_id):
            return amount
        boosts = {row["role_id"]: row["percent"]
                  for row in self.db.level_boosts_of(guild_id)}
        role = max((boosts[r.id] for r in getattr(member, "roles", [])
                    if r.id in boosts), default=100)
        place = 100
        if channel is not None:
            # A thread counts as the channel it's in.
            parent = getattr(channel, "parent", None) or channel
            place = boosts.get(parent.id) or boosts.get(
                getattr(parent, "category_id", None)) or 100
        event = self.db.event_strength(guild_id, "xp") or 100
        return round(amount * role / 100 * place / 100 * event / 100)

    async def give_xp(self, member, amount: int, channel=None):
        """Add XP, and if that's a level up, pay out and announce it."""
        guild = member.guild
        if amount > 0:
            self.db.add_monthly_xp(guild.id, member.id, month_now(), amount)
        row = self.db.level_row(guild.id, member.id)
        xp = row["xp"] + amount
        level = level_for(xp)[0]
        self.db.update_level_row(guild.id, member.id, xp=xp, level=level)
        if level > row["level"]:
            await self.levelled_up(member, row["level"], level,
                                   row["paid_through"], channel)

    async def card_file(self, member):
        """A member's rank card as a file to send, or None if it can't be
        drawn. Used by $rank and under level-up messages."""
        gid = member.guild.id
        try:
            row = self.db.level_row(gid, member.id)
            level, into, needed = level_for(row["xp"])
            place = self.db.level_rank(gid, member.id)
            background = None
            if self.db.is_premium(gid):
                background = (self.db.rank_background(gid, member.id)
                              or self.db.rank_background(gid, 0))
            avatar = await member.display_avatar.replace(size=256, format="png").read()
            # Drawing takes a moment; keep it off the bot's main loop.
            png = await asyncio.to_thread(
                rankcard.render, member.display_name, avatar, level, into, needed,
                place, row["xp"], self.colour(gid), background, member.name)
        except Exception:  # noqa: BLE001 - a card must never cost the message
            logging.getLogger("levels").exception("rank card failed")
            return None
        return discord.File(io.BytesIO(png), filename="rank.png")

    async def levelled_up(self, member, old: int, new: int, paid_through: int,
                          channel=None):
        guild = member.guild
        await self.sync_roles(member, new)

        # Karuda for each milestone crossed that has never been paid before.
        reward = self.setting(guild.id, "karuda")
        milestones = [n for n in range(max(old, paid_through) + 1, new + 1)
                      if n % KARUDA_EVERY == 0]
        paid = reward * len(milestones) if reward else 0
        if paid:
            self.db.add_karuda(guild.id, member.id, paid)
        if milestones:
            self.db.update_level_row(guild.id, member.id,
                                     paid_through=max(milestones[-1], paid_through))

        where = self.setting(guild.id, "channel")
        if where == -1:          # announcements off
            return
        target = guild.get_channel(where) if where else channel
        if not target:
            return
        text = render_message(self.message_of(guild.id), member, new)
        if paid:
            text += f" +{paid:,} {config.CURRENCY}"
        # The rank card goes under the message, showing the new level.
        card = await self.card_file(member) if self.setting(guild.id, "levelup_card") else None
        try:
            await target.send(text, allowed_mentions=discord.AllowedMentions(
                users=[member]), **({"file": card} if card else {}))
        except discord.HTTPException:
            pass

    async def sync_roles(self, member, level: int):
        """Give the level roles they've earned. With stacking off, only the
        highest one they've reached is kept."""
        guild = member.guild
        top = guild.me.top_role
        usable = {row["level"]: guild.get_role(row["role_id"])
                  for row in self.db.level_roles_of(guild.id)}
        usable = {n: r for n, r in usable.items()
                  if r and r < top and not r.managed}
        earned = [r for n, r in sorted(usable.items()) if n <= level]
        extra = []
        if earned and not self.setting(guild.id, "stack"):
            keep = earned[-1]
            extra = [r for r in usable.values() if r != keep and r in member.roles]
            earned = [keep]
        missing = [r for r in earned if r not in member.roles]
        try:
            if missing:
                await member.add_roles(*missing, reason=f"Reached level {level}")
            if extra:
                await member.remove_roles(
                    *extra, reason="Only the highest level role is kept")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        guild = message.guild
        if message.channel.id in self.db.level_ignored_in(guild.id):
            return
        key = (guild.id, message.author.id)
        now = time.time()
        if now - self.last_counted.get(key, 0) < self.setting(guild.id, "cooldown"):
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        self.last_counted[key] = now
        low = self.setting(guild.id, "msg_min")
        high = self.setting(guild.id, "msg_max")
        amount = random.randint(min(low, high), max(low, high))
        if amount:
            gained = self.boosted(message.author, amount, message.channel)
            if weekly.tracking(self.db, guild.id):
                self.db.add_weekly(guild.id, message.author.id, weekly.week_now(),
                                   chat=gained)
            await self.give_xp(message.author, gained, message.channel)

    @tasks.loop(minutes=1)
    async def voice_xp(self):
        day = today()
        week = weekly.week_now()
        month = month_now()
        if self.pruned_for != month:
            # Last month stays viewable; anything older goes.
            self.db.prune_monthly(month_before(month))
            self.pruned_for = month
        for guild in self.bot.guilds:
            xp_on = bool(self.setting(guild.id, "voice") and self.setting(guild.id, "voice_xp"))
            # Weekly champions count voice minutes by the same rules, even
            # where voice XP itself is switched off.
            track = weekly.tracking(self.db, guild.id)
            if not (xp_on or track):
                continue
            for channel in guild.voice_channels:
                if channel == guild.afk_channel:
                    continue
                people = [m for m in channel.members if not m.bot]
                # Alone in a call doesn't count: it's too easy to leave on.
                if len(people) < 2:
                    continue
                for member in people:
                    state = member.voice
                    if state and (state.self_deaf or state.deaf):
                        continue
                    if track:
                        self.db.add_weekly(guild.id, member.id, week, voice=60)
                    if xp_on:
                        await self.give_voice_xp(member, day)

    async def give_voice_xp(self, member, day: int):
        row = self.db.level_row(member.guild.id, member.id)
        spent = row["voice_today"] if row["voice_day"] == day else 0
        amount = min(self.setting(member.guild.id, "voice_xp"),
                     self.setting(member.guild.id, "voice_cap") - spent)
        if amount <= 0:
            return
        self.db.update_level_row(member.guild.id, member.id, voice_day=day,
                                 voice_today=spent + amount)
        # The daily cap counts plain XP, so a boost can't reach it sooner.
        where = member.voice.channel if member.voice else None
        await self.give_xp(member, self.boosted(member, amount, where))

    @voice_xp.before_loop
    async def before_voice_xp(self):
        await self.bot.wait_until_ready()

    # ----------------------------------------------------------- viewing

    @commands.group(name="rank", aliases=["xp", "level", "lvl"],
                    invoke_without_command=True)
    @commands.guild_only()
    async def rank(self, ctx, member: discord.Member = None):
        """Your rank card: level, how close the next one is, and your place."""
        member = member or ctx.author
        row = self.db.level_row(ctx.guild.id, member.id)
        level, into, needed = level_for(row["xp"])
        place = self.db.level_rank(ctx.guild.id, member.id)
        card = await self.card_file(member)
        if card:
            await ctx.send(file=card)
            return
        # The card is a nicety: if it can't be drawn, the numbers still go out.
        embed = discord.Embed(title=member.display_name,
                              colour=self.colour(ctx.guild.id))
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Level", value=f"**{level}**")
        embed.add_field(name="Rank", value=f"**#{place}**" if place else "—")
        embed.add_field(name="Total XP", value=f"{row['xp']:,}")
        embed.add_field(
            name=f"Level {level + 1}",
            value=f"{bar(into, needed)}\n{into:,} / {needed:,} XP", inline=False)
        upcoming = next((r for r in self.db.level_roles_of(ctx.guild.id)
                         if r["level"] > level), None)
        if upcoming:
            embed.set_footer(text=f"Next role at level {upcoming['level']}")
        await ctx.send(embed=embed)

    async def picture(self, ctx):
        """The picture attached to the command, made card-sized, or None."""
        if not ctx.message.attachments:
            return None
        attachment = ctx.message.attachments[0]
        if attachment.size > rankcard.MAX_UPLOAD:
            raise rankcard.BadImage("That picture is over 8 MB.")
        raw = await attachment.read()
        return await asyncio.to_thread(rankcard.prepare_background, raw)

    @rank.command(name="background", aliases=["bg"])
    async def rank_background(self, ctx, reset: str = None):
        """Premium: your own rank card background. Attach a picture, or say
        `reset` to go back to the server's."""
        gid = ctx.guild.id
        if reset and reset.lower() in ("reset", "remove", "off"):
            self.db.set_rank_background(gid, ctx.author.id, None)
            await ctx.send("Your rank card uses the server's background again.")
            return
        if not self.db.is_premium(gid):
            await ctx.send("Custom rank cards come with Paper Premium."
                           f" `{ctx.prefix}upgrade` to see how to get it.")
            return
        try:
            image = await self.picture(ctx)
        except rankcard.BadImage as e:
            await ctx.send(str(e))
            return
        if not image:
            await ctx.send(f"Attach a picture to `{ctx.prefix}rank background`.")
            return
        self.db.set_rank_background(gid, ctx.author.id, image)
        await ctx.send(f"Saved. Try `{ctx.prefix}rank`.")

    @commands.group(name="levels", aliases=["levelboard", "toplevels"],
                    invoke_without_command=True)
    @commands.guild_only()
    async def levels(self, ctx):
        """The server's level leaderboard."""
        rows = self.db.top_levels(ctx.guild.id, limit=100)
        medals = ("\U0001f947", "\U0001f948", "\U0001f949")
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1:>2}.`'} <@{row['user_id']}>"
            f" · level **{level_for(row['xp'])[0]}** · {row['xp']:,} XP"
            for i, row in enumerate(rows)
        ]
        pages = utils.paginate(lines, 10)
        embeds = []
        for number, page in enumerate(pages):
            embed = discord.Embed(
                title=f"Levels in {ctx.guild.name}",
                description="\n".join(page) or "Nobody has any XP yet.",
                colour=self.colour(ctx.guild.id))
            if len(pages) > 1:
                embed.set_footer(text=f"Page {number + 1}/{len(pages)}")
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    @levels.command(name="month", aliases=["monthly", "thismonth"])
    async def levels_month(self, ctx, which: str = None):
        """Premium: who earned the most XP this month. `last` for last month."""
        if not self.db.is_premium(ctx.guild.id):
            await ctx.send("The monthly leaderboard comes with Paper Premium."
                           f" `{ctx.prefix}upgrade` to see how to get it.")
            return
        month = month_now()
        if which and which.lower() in ("last", "previous", "prev"):
            month = month_before(month)
        rows = self.db.monthly_top(ctx.guild.id, month)
        medals = ("\U0001f947", "\U0001f948", "\U0001f949")
        lines = [f"{medals[i] if i < 3 else f'`{i + 1:>2}.`'} <@{row['user_id']}>"
                 f" · {row['xp']:,} XP" for i, row in enumerate(rows)]
        pages = utils.paginate(lines, 10)
        embeds = []
        for number, page in enumerate(pages):
            embed = discord.Embed(
                title=f"Top XP in {month_name(month)}",
                description="\n".join(page) or "Nobody has earned XP this month yet.",
                colour=self.colour(ctx.guild.id))
            footer = "Resets on the 1st (UTC)"
            if len(pages) > 1:
                footer = f"Page {number + 1}/{len(pages)} · " + footer
            embed.set_footer(text=footer)
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    # ---------------------------------------------------------- settings

    @levels.command(name="settings", aliases=["config"])
    async def levels_settings(self, ctx):
        """How levelling is set up here."""
        gid = ctx.guild.id
        c = self.settings_of(gid)
        where = c["channel"]
        ignored = self.db.level_ignored_in(gid)
        roles = self.db.level_roles_of(gid)
        lines = [
            f"**Messages:** {c['msg_min']}-{c['msg_max']} XP, one every"
            f" {c['cooldown']}s",
            "**Voice:** " + (f"{c['voice_xp']} XP a minute, up to"
                             f" {c['voice_cap']:,} a day" if c["voice"] else "off"),
            f"**Karuda:** {c['karuda']:,} every {KARUDA_EVERY} levels"
            if c["karuda"] else "**Karuda:** off",
            "**Level-ups announced:** "
            + ("nowhere" if where == -1 else f"<#{where}>" if where
               else "where they levelled up"),
            f"**Message:** {self.message_of(gid)[:200]}",
            "**No XP in:** " + (" ".join(f"<#{cid}>" for cid in ignored)
                                or "nowhere"),
            "**Roles** (" + ("all kept" if c["stack"] else "highest only") + "): "
            + (", ".join(f"{r['level']} → <@&{r['role_id']}>" for r in roles)
               or "none"),
        ]
        embed = discord.Embed(title="Level settings", description="\n".join(lines),
                              colour=self.colour(gid))
        embed.set_footer(text=f"Change them here, or on the web with {ctx.prefix}dashboard")
        await ctx.send(embed=embed)

    async def save_one(self, ctx, changes: dict, done: str):
        """Save through save_settings() and say what happened."""
        problems = self.save_settings(ctx.guild.id, changes)
        await ctx.send("\n".join(problems) if problems else done)

    @levels.group(name="role", aliases=["roles"], invoke_without_command=True)
    async def levels_role(self, ctx):
        """The roles handed out at each level."""
        rows = self.db.level_roles_of(ctx.guild.id)
        await ctx.send(embed=discord.Embed(
            title="Level roles",
            description="\n".join(f"Level **{r['level']}** → <@&{r['role_id']}>"
                                  for r in rows)
            or f"None yet. e.g. `{ctx.prefix}levels role add 10 @Active`",
            colour=self.colour(ctx.guild.id)))

    @levels_role.command(name="add", aliases=["set"])
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def levels_role_add(self, ctx, level: int, role: discord.Role):
        """Give a role at a level. Members already past it get it next time
        they level up, or straight away with $levels sync."""
        if not 1 <= level <= MAX_LEVEL:
            await ctx.send(f"Pick a level from 1 to {MAX_LEVEL}.")
            return
        if role >= ctx.guild.me.top_role or role.managed:
            await ctx.send(f"I can't give **{role.name}**. It needs to be below"
                           " my role.", allowed_mentions=discord.AllowedMentions.none())
            return
        self.db.set_level_role(ctx.guild.id, level, role.id)
        await ctx.send(f"At level **{level}**, people get **{role.name}**.",
                       allowed_mentions=discord.AllowedMentions.none())

    @levels_role.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def levels_role_remove(self, ctx, level: int):
        """Stop giving a role at a level. Nobody loses it."""
        gone = self.db.remove_level_role(ctx.guild.id, level)
        await ctx.send(f"No role at level **{level}** any more." if gone
                       else f"There was no role at level {level}.")

    @levels.command(name="sync")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def levels_sync(self, ctx):
        """Bring everyone's level roles up to date."""
        checked = 0
        for row in self.db.top_levels(ctx.guild.id, limit=100_000):
            member = ctx.guild.get_member(row["user_id"])
            if member:
                await self.sync_roles(member, level_for(row["xp"])[0])
                checked += 1
        await ctx.send(f"Level roles are up to date for **{checked}** members.")

    @levels.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def levels_channel(self, ctx, *, where: str = None):
        """Where level-ups are announced: a channel, `here` for wherever they
        levelled up, or `off`."""
        if not where or where.lower() == "here":
            value, said = 0, "wherever someone levels up"
        elif where.lower() == "off":
            value, said = -1, "nowhere. Level-ups happen quietly"
        else:
            try:
                channel = await commands.TextChannelConverter().convert(ctx, where)
            except commands.BadArgument:
                await ctx.send("Name a channel, or say `here` or `off`.")
                return
            value, said = channel.id, channel.mention
        await self.save_one(ctx, {"channel": value},
                            f"Level-ups will be announced {said}.")

    @levels.command(name="karuda", aliases=["reward"])
    @commands.has_permissions(manage_guild=True)
    async def levels_karuda(self, ctx, amount: int):
        """Karuda paid every 5 levels, up to 250. 0 turns it off."""
        await self.save_one(
            ctx, {"karuda": amount},
            f"Every {KARUDA_EVERY} levels pays **{amount:,}** {config.CURRENCY}."
            if amount else "Levels no longer pay karuda.")

    @levels.command(name="xp")
    @commands.has_permissions(manage_guild=True)
    async def levels_xp(self, ctx, least: int, most: int = None):
        """XP a message gives: a range, e.g. `15 25`, or one number."""
        most = least if most is None else most
        await self.save_one(ctx, {"msg_min": least, "msg_max": most},
                            f"Messages give **{least}-{most}** XP."
                            if least != most else f"Messages give **{least}** XP.")

    @levels.command(name="cooldown")
    @commands.has_permissions(manage_guild=True)
    async def levels_cooldown(self, ctx, seconds: int):
        """Seconds before someone's next message earns XP again."""
        await self.save_one(ctx, {"cooldown": seconds},
                            f"One message every **{seconds}s** earns XP.")

    @levels.command(name="voice")
    @commands.has_permissions(manage_guild=True)
    async def levels_voice(self, ctx, state: str):
        """Turn XP for time in voice `on` or `off`."""
        state = state.lower()
        if state not in ("on", "off"):
            await ctx.send("Say `on` or `off`.")
            return
        await self.save_one(ctx, {"voice": 1 if state == "on" else 0},
                            f"Voice XP is **{state}**.")

    @levels.command(name="voicexp")
    @commands.has_permissions(manage_guild=True)
    async def levels_voicexp(self, ctx, per_minute: int):
        """Voice XP per minute."""
        await self.save_one(ctx, {"voice_xp": per_minute},
                            f"Voice gives **{per_minute}** XP a minute.")

    @levels.command(name="voicecap")
    @commands.has_permissions(manage_guild=True)
    async def levels_voicecap(self, ctx, per_day: int):
        """The most voice XP anyone can earn in a day."""
        await self.save_one(ctx, {"voice_cap": per_day},
                            f"Voice XP stops at **{per_day:,}** a day.")

    @levels.command(name="stack")
    @commands.has_permissions(manage_guild=True)
    async def levels_stack(self, ctx, state: str):
        """`on` keeps every level role earned; `off` keeps only the highest."""
        state = state.lower()
        if state not in ("on", "off"):
            await ctx.send("Say `on` or `off`.")
            return
        await self.save_one(
            ctx, {"stack": 1 if state == "on" else 0},
            "People keep every level role they earn." if state == "on" else
            "People keep only their highest level role. Run"
            f" `{ctx.prefix}levels sync` to tidy up existing ones.")

    @levels.command(name="levelcard", aliases=["upcard"])
    @commands.has_permissions(manage_guild=True)
    async def levels_levelcard(self, ctx, state: str):
        """`on` or `off`: the rank card under each level-up message."""
        state = state.lower()
        if state not in ("on", "off"):
            await ctx.send("Say `on` or `off`.")
            return
        await self.save_one(ctx, {"levelup_card": 1 if state == "on" else 0},
                            "Level-ups show the rank card." if state == "on"
                            else "Level-ups are text only now.")

    @levels.command(name="message")
    @commands.has_permissions(manage_guild=True)
    async def levels_message(self, ctx, *, text: str = None):
        """The level-up message. Use {user}, {user.name}, {level} and
        {server}. `reset` goes back to the default."""
        gid = ctx.guild.id
        if not text:
            await ctx.send(f"Now: {self.message_of(gid)}\nVariables: "
                           + " ".join(f"`{v}`" for v in MESSAGE_VARIABLES),
                           allowed_mentions=discord.AllowedMentions.none())
            return
        if text.lower() == "reset":
            self.db.set_level_text(gid, "message", None)
            await ctx.send("The level-up message is back to the default.")
            return
        if len(text) > MESSAGE_LIMIT:
            await ctx.send(f"Keep it under {MESSAGE_LIMIT} characters.")
            return
        self.db.set_level_text(gid, "message", text)
        await ctx.send("Saved. It'll look like this:\n"
                       + render_message(text, ctx.author, 10),
                       allowed_mentions=discord.AllowedMentions.none())

    @levels.group(name="ignore", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def levels_ignore(self, ctx, channel: discord.TextChannel):
        """No XP for messages in a channel, like a spam or bot channel."""
        self.db.ignore_level_channel(ctx.guild.id, channel.id)
        await ctx.send(f"Messages in {channel.mention} won't earn XP.")

    @levels_ignore.command(name="list")
    async def levels_ignore_list(self, ctx):
        """Channels that don't earn XP."""
        ids = self.db.level_ignored_in(ctx.guild.id)
        await ctx.send("No XP in: " + (" ".join(f"<#{c}>" for c in ids)
                                        or "nowhere, every channel counts."))

    @levels_ignore.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def levels_ignore_remove(self, ctx, channel: discord.TextChannel):
        """Let a channel earn XP again."""
        gone = self.db.unignore_level_channel(ctx.guild.id, channel.id)
        await ctx.send(f"{channel.mention} earns XP again." if gone
                       else f"{channel.mention} wasn't ignored.")

    @levels.command(name="set")
    @commands.has_permissions(manage_guild=True)
    async def levels_set(self, ctx, member: discord.Member, level: int):
        """Put someone at a level, e.g. to carry levels over from another
        bot. Pays no karuda."""
        if not 0 <= level <= MAX_LEVEL:
            await ctx.send(f"Pick a level from 0 to {MAX_LEVEL}.")
            return
        row = self.db.level_row(ctx.guild.id, member.id)
        # Counts as paid, so a carried-over level can't be cashed in.
        self.db.update_level_row(ctx.guild.id, member.id, xp=total_for(level),
                                 level=level,
                                 paid_through=max(row["paid_through"], level))
        await self.sync_roles(member, level)
        await ctx.send(f"**{member.display_name}** is level **{level}** now.",
                       allowed_mentions=discord.AllowedMentions.none())

    def boost_label(self, guild, target_id: int) -> str:
        """How a boost's role or channel reads in a message."""
        if guild.get_role(target_id):
            return f"<@&{target_id}>"
        place = guild.get_channel(target_id)
        if isinstance(place, discord.CategoryChannel):
            return f"the **{place.name}** category"
        return f"<#{target_id}>" if place else "a deleted role or channel"

    @levels.group(name="boost", aliases=["boosts"], invoke_without_command=True)
    async def levels_boost(self, ctx):
        """Premium: roles and channels that earn extra XP."""
        rows = self.db.level_boosts_of(ctx.guild.id)
        lines = [f"{self.boost_label(ctx.guild, r['role_id'])} earns"
                 f" **{r['percent'] / 100:g}x** XP" for r in rows]
        note = "" if self.db.is_premium(ctx.guild.id) else (
            "\n\n*XP boosts are a Paper Premium feature, so they're paused on"
            f" this server. `{ctx.prefix}upgrade` to see how to get it.*")
        await ctx.send(embed=discord.Embed(
            title="XP boosts",
            description=("\n".join(lines) or
                         f"None yet. e.g. `{ctx.prefix}levels boost add @Booster 150`"
                         f" or `{ctx.prefix}levels boost add #general 200`")
            + ("\n\nThe best role boost someone has counts, times the boost of"
               " the channel they're in." if lines else "")
            + note, colour=self.colour(ctx.guild.id)))

    @levels_boost.command(name="add", aliases=["set"])
    @commands.has_permissions(manage_guild=True)
    async def levels_boost_add(self, ctx, target: BoostTarget, percent: int):
        """Premium: a role, channel or category earns this percent of normal
        XP, e.g. 150 for 1.5x."""
        if not self.db.is_premium(ctx.guild.id):
            await ctx.send("XP boosts are a Paper Premium feature."
                           f" `{ctx.prefix}upgrade` to see how to get it.")
            return
        low, high = BOOST_RANGE
        if not low <= percent <= high:
            await ctx.send(f"Pick from {low} (1.05x) to {high} (3x).")
            return
        if isinstance(target, discord.Role) and target.is_default():
            await ctx.send("Pick a role other than @everyone.")
            return
        self.db.set_level_boost(ctx.guild.id, target.id, percent)
        await ctx.send(f"{self.boost_label(ctx.guild, target.id)} earns"
                       f" **{percent / 100:g}x** XP now.",
                       allowed_mentions=discord.AllowedMentions.none())

    @levels_boost.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def levels_boost_remove(self, ctx, target: BoostTarget):
        """Stop a role's or channel's XP boost."""
        label = self.boost_label(ctx.guild, target.id)
        gone = self.db.remove_level_boost(ctx.guild.id, target.id)
        await ctx.send(f"{label} earns normal XP again." if gone
                       else f"{label} had no boost.",
                       allowed_mentions=discord.AllowedMentions.none())

    @levels.command(name="card")
    @commands.has_permissions(manage_guild=True)
    async def levels_card(self, ctx, reset: str = None):
        """Premium: the server's rank card background. Attach a picture, or
        say `reset`."""
        gid = ctx.guild.id
        if reset and reset.lower() in ("reset", "remove", "off"):
            self.db.set_rank_background(gid, 0, None)
            await ctx.send("Rank cards are back to the starry default.")
            return
        if not self.db.is_premium(gid):
            await ctx.send("Custom rank cards come with Paper Premium."
                           f" `{ctx.prefix}upgrade` to see how to get it.")
            return
        try:
            image = await self.picture(ctx)
        except rankcard.BadImage as e:
            await ctx.send(str(e))
            return
        if not image:
            await ctx.send(f"Attach a picture to `{ctx.prefix}levels card`.")
            return
        self.db.set_rank_background(gid, 0, image)
        await ctx.send(f"Saved. Everyone's `{ctx.prefix}rank` uses it now, unless"
                       " they've set their own.")

    @levels.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def levels_reset(self, ctx, member: discord.Member):
        """Take someone back to level 0. Their roles stay."""
        self.db.update_level_row(ctx.guild.id, member.id, xp=0, level=0)
        await ctx.send(f"**{member.display_name}** is back to level 0.",
                       allowed_mentions=discord.AllowedMentions.none())

    @levels.command(name="import")
    @commands.has_permissions(manage_guild=True)
    async def levels_import(self, ctx, *, text: str = ""):
        """Carry levels over from another bot. Attach a text file with one
        `username level` per line, best first. Shows who matched before it
        changes anything, and pays no karuda."""
        if ctx.message.attachments:
            raw = await ctx.message.attachments[0].read()
            text = raw.decode("utf-8", errors="replace")
        rows = parse_import(text)
        if not rows:
            await ctx.send("Attach a text file with one `username level` per"
                           " line, e.g. `kingnoaglazer 32`.")
            return

        exact, guessed, missing = match_members(rows, ctx.guild.members)
        matched = exact + guessed
        lines = [f"**{len(exact)}** matched by username."]
        if guessed:
            lines.append(f"**{len(guessed)}** matched by a close spelling,"
                         " check these:")
            lines += [f"　`{name}` → {member.mention}"
                      for name, member, _level in guessed[:15]]
        if missing:
            shown = ", ".join(f"`{name}`" for name in missing[:30])
            more = f" and {len(missing) - 30} more" if len(missing) > 30 else ""
            lines.append(f"**{len(missing)}** not found (left the server, or"
                         f" renamed): {shown}{more}")
        lines.append("\nNobody who already has more XP here is lowered, and"
                     " imported levels pay no karuda.")
        if not matched:
            await ctx.send("\n".join(lines))
            return

        view = Confirm([ctx.author.id])
        view.message = await ctx.send(
            "\n".join(lines) + f"\n**Import {len(matched)} levels?**",
            view=view, allowed_mentions=discord.AllowedMentions.none())
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Left alone.")
            return

        # Rows come best first. Inside one level, a few XP of lead keeps them
        # in that order on $levels, without ever tipping into the next level.
        raised = 0
        for position, (_name, member, level) in enumerate(
                sorted(matched, key=lambda m: rows_index(rows, m[0]))):
            lead = min(len(rows) - position, xp_to_next(level) - 1)
            xp = total_for(level) + max(lead, 0)
            row = self.db.level_row(ctx.guild.id, member.id)
            if row["xp"] >= xp:
                continue
            self.db.update_level_row(
                ctx.guild.id, member.id, xp=xp, level=level_for(xp)[0],
                paid_through=max(row["paid_through"], level))
            await self.sync_roles(member, level)
            raised += 1
        await ctx.send(f"Imported **{raised}** levels."
                       + (f" {len(matched) - raised} already had more XP here."
                          if len(matched) > raised else ""))


async def setup(bot):
    await bot.add_cog(Levels(bot))
