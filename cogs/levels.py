"""Levels: XP for chatting and for time in voice.

Chatting pays 15-25 XP, at most once a minute, so a wall of spam earns the
same as one message. Commands don't count; nobody should level up by rolling.

Voice pays 10 XP a minute, but only with someone else in the channel, not
deafened, and not in the AFK channel, and at most VOICE_DAILY_CAP a day, so
sitting in a call all day can't outrun the people talking.

Each level needs a bit more than the last, on MEE6's curve: level 5 is about
an hour of steady chat, level 50 is months.

Karuda is deliberately scarce: a flat amount every KARUDA_EVERY levels and
nothing in between, paid once per milestone for good. A daily already pays
more than a milestone does, so levels are a thank-you, not an income.
"""
import random
import time
from typing import Optional

import discord
from discord.ext import commands, tasks

import config
import utils
from views import Paginator

MESSAGE_XP = (15, 25)
MESSAGE_COOLDOWN = 60
VOICE_XP = 10               # per minute
VOICE_DAILY_CAP = 600       # an hour's worth
KARUDA_EVERY = 5            # levels between karuda payouts
DEFAULT_KARUDA = 100
MAX_KARUDA = 250
MAX_LEVEL = 500


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


class Levels(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_counted = {}  # (guild, user) -> when a message last paid

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

    def setting(self, guild_id: int, key: str, default: int) -> int:
        return self.db.get_level_setting(guild_id, key, default)

    # ------------------------------------------------------------ earning

    async def give_xp(self, member, amount: int, channel=None):
        """Add XP, and if that's a level up, pay out and announce it."""
        guild = member.guild
        row = self.db.level_row(guild.id, member.id)
        xp = row["xp"] + amount
        level = level_for(xp)[0]
        self.db.update_level_row(guild.id, member.id, xp=xp, level=level)
        if level > row["level"]:
            await self.levelled_up(member, row["level"], level,
                                   row["paid_through"], channel)

    async def levelled_up(self, member, old: int, new: int, paid_through: int,
                          channel=None):
        guild = member.guild
        await self.sync_roles(member, new)

        # Karuda for each milestone crossed that has never been paid before.
        reward = self.setting(guild.id, "karuda", DEFAULT_KARUDA)
        milestones = [n for n in range(max(old, paid_through) + 1, new + 1)
                      if n % KARUDA_EVERY == 0]
        paid = reward * len(milestones) if reward else 0
        if paid:
            self.db.add_karuda(guild.id, member.id, paid)
        if milestones:
            self.db.update_level_row(guild.id, member.id,
                                     paid_through=max(milestones[-1], paid_through))

        where = self.setting(guild.id, "channel", 0)
        if where == -1:          # announcements off
            return
        target = guild.get_channel(where) if where else channel
        if not target:
            return
        text = f"\U0001f389 {member.mention} reached **level {new}**!"
        if paid:
            text += f" +{paid:,} {config.CURRENCY}"
        try:
            await target.send(text, allowed_mentions=discord.AllowedMentions(
                users=[member]))
        except discord.HTTPException:
            pass

    async def sync_roles(self, member, level: int):
        """Give every level role at or below their level that they lack."""
        due = [member.guild.get_role(row["role_id"])
               for row in self.db.level_roles_of(member.guild.id)
               if row["level"] <= level]
        top = member.guild.me.top_role
        missing = [r for r in due if r and r not in member.roles
                   and r < top and not r.managed]
        if missing:
            try:
                await member.add_roles(*missing, reason=f"Reached level {level}")
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
        if now - self.last_counted.get(key, 0) < MESSAGE_COOLDOWN:
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        self.last_counted[key] = now
        await self.give_xp(message.author, random.randint(*MESSAGE_XP),
                           message.channel)

    @tasks.loop(minutes=1)
    async def voice_xp(self):
        day = today()
        for guild in self.bot.guilds:
            if not self.setting(guild.id, "voice", 1):
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
                    await self.give_voice_xp(member, day)

    async def give_voice_xp(self, member, day: int):
        row = self.db.level_row(member.guild.id, member.id)
        spent = row["voice_today"] if row["voice_day"] == day else 0
        amount = min(VOICE_XP, VOICE_DAILY_CAP - spent)
        if amount <= 0:
            return
        self.db.update_level_row(member.guild.id, member.id, voice_day=day,
                                 voice_today=spent + amount)
        await self.give_xp(member, amount)

    @voice_xp.before_loop
    async def before_voice_xp(self):
        await self.bot.wait_until_ready()

    # ----------------------------------------------------------- viewing

    @commands.command(name="rank", aliases=["xp", "level", "lvl"])
    @commands.guild_only()
    async def rank(self, ctx, member: discord.Member = None):
        """Your level, how close the next one is, and your place here."""
        member = member or ctx.author
        row = self.db.level_row(ctx.guild.id, member.id)
        level, into, needed = level_for(row["xp"])
        place = self.db.level_rank(ctx.guild.id, member.id)
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

    # ---------------------------------------------------------- settings

    @levels.command(name="settings", aliases=["config"])
    async def levels_settings(self, ctx):
        """How levelling is set up here."""
        gid = ctx.guild.id
        where = self.setting(gid, "channel", 0)
        karuda = self.setting(gid, "karuda", DEFAULT_KARUDA)
        ignored = self.db.level_ignored_in(gid)
        roles = self.db.level_roles_of(gid)
        lines = [
            "**Level-up messages:** "
            + ("off" if where == -1 else f"<#{where}>" if where
               else "where they levelled up"),
            f"**Karuda:** {karuda:,} every {KARUDA_EVERY} levels" if karuda
            else "**Karuda:** off",
            "**Voice XP:** " + ("on" if self.setting(gid, "voice", 1) else "off")
            + f" ({VOICE_XP} a minute, up to {VOICE_DAILY_CAP} a day)",
            "**No XP in:** " + (" ".join(f"<#{c}>" for c in ignored) or "nowhere"),
            "**Roles:** " + (", ".join(f"{r['level']} → <@&{r['role_id']}>"
                                       for r in roles) or "none"),
        ]
        await ctx.send(embed=discord.Embed(
            title="Level settings", description="\n".join(lines),
            colour=self.colour(gid)))

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
        """Give everyone the level roles they've already earned."""
        given = 0
        for row in self.db.top_levels(ctx.guild.id, limit=100_000):
            member = ctx.guild.get_member(row["user_id"])
            if member:
                before = len(member.roles)
                await self.sync_roles(member, level_for(row["xp"])[0])
                given += len(member.roles) - before
        await ctx.send(f"Handed out **{given}** level roles.")

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
        self.db.set_level_setting(ctx.guild.id, "channel", value)
        await ctx.send(f"Level-ups will be announced {said}.")

    @levels.command(name="karuda", aliases=["reward"])
    @commands.has_permissions(manage_guild=True)
    async def levels_karuda(self, ctx, amount: int):
        """Karuda paid every 5 levels. 0 turns it off."""
        if not 0 <= amount <= MAX_KARUDA:
            await ctx.send(f"Pick from 0 (off) to {MAX_KARUDA}. It's kept small"
                           f" on purpose, so levels don't outpace {ctx.prefix}daily.")
            return
        self.db.set_level_setting(ctx.guild.id, "karuda", amount)
        await ctx.send(f"Every {KARUDA_EVERY} levels pays **{amount:,}**"
                       f" {config.CURRENCY}." if amount
                       else "Levels no longer pay karuda.")

    @levels.command(name="voice")
    @commands.has_permissions(manage_guild=True)
    async def levels_voice(self, ctx, state: str):
        """Turn XP for time in voice `on` or `off`."""
        state = state.lower()
        if state not in ("on", "off"):
            await ctx.send("Say `on` or `off`.")
            return
        self.db.set_level_setting(ctx.guild.id, "voice", 1 if state == "on" else 0)
        await ctx.send(f"Voice XP is **{state}**.")

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

    @levels.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def levels_reset(self, ctx, member: discord.Member):
        """Take someone back to level 0. Their roles stay."""
        self.db.update_level_row(ctx.guild.id, member.id, xp=0, level=0)
        await ctx.send(f"**{member.display_name}** is back to level 0.",
                       allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Levels(bot))
