"""Server events, a Paper Premium feature: Double XP, a Karuda rush, Bonus rolls.

An admin schedules one, from `$event start` or the dashboard, and for its
length everyone in the server gets the lift. The effects live where the
numbers are read: XP in cogs/levels.py, rolls and karuda grabs in
Database.get_setting, daily drops in cogs/karuda.py. So an event reaches
everything and stops by itself when its time is up.

A karuda rush lifts what's earned (daily drops, karuda grabs off rolls),
never what characters are worth or what can be traded, so it can't be
turned into free karuda.
"""
import time

import discord
from discord.ext import commands, tasks

import config
import premium
from cogs.modtools import describe_duration, parse_duration

# kind: (name, emoji, default strength, lowest, highest, how strength reads)
KINDS = {
    "xp": ("Double XP", "\U0001f4c8", 200, 125, 300, "percent"),
    "karuda": ("Karuda rush", "\U0001f48e", 200, 125, 300, "percent"),
    "rolls": ("Bonus rolls", "\U0001f3b2", 5, 1, 20, "rolls"),
}
ALIASES = {"doublexp": "xp", "exp": "xp", "kakera": "karuda", "money": "karuda",
           "roll": "rolls", "bonusrolls": "rolls"}
MIN_LENGTH, MAX_LENGTH = 10 * 60, 7 * 86400
MAX_UPCOMING = 10


def kind_of(word: str):
    word = (word or "").lower()
    return word if word in KINDS else ALIASES.get(word)


def describe(kind: str, strength: int) -> str:
    name, emoji, *_rest, unit = KINDS[kind]
    if unit == "rolls":
        return f"{emoji} {name}: +{strength} rolls every window"
    effect = {"xp": "XP", "karuda": "karuda from dailies and grabs"}[kind]
    return f"{emoji} {name}: {strength / 100:g}x {effect}"


def check(kind: str, strength: int, length: int) -> str:
    """Why this event can't be made, or ''."""
    if kind not in KINDS:
        return "Pick an event: xp, karuda or rolls."
    _n, _e, _d, low, high, unit = KINDS[kind]
    if not low <= strength <= high:
        return (f"{KINDS[kind][0]} goes from {low} to {high}"
                + (" extra rolls." if unit == "rolls" else "%."))
    if not MIN_LENGTH <= length <= MAX_LENGTH:
        return "Events last from 10 minutes to 7 days."
    return ""


class Events(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    async def cog_load(self):
        self.announcer.start()

    async def cog_unload(self):
        self.announcer.cancel()

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    def schedule(self, guild_id, kind, strength, starts_at, length, channel_id,
                 by) -> str:
        """Make an event, or say why not. Shared with the dashboard."""
        if not self.db.has_feature(guild_id, "events"):
            return f"Server events come with {premium.needs('events')}."
        if problem := check(kind, strength, length):
            return problem
        if len(self.db.events_of(guild_id)) >= MAX_UPCOMING:
            return f"Up to {MAX_UPCOMING} events can be running or coming up."
        now = int(time.time())
        starts_at = max(now, int(starts_at))
        if starts_at > now + 60 * 86400:
            return "Schedule events up to 60 days ahead."
        self.db.add_event(guild_id, kind, strength, starts_at, starts_at + length,
                          channel_id, by)
        return ""

    # ------------------------------------------------------------ commands

    @commands.group(name="event", aliases=["events"], invoke_without_command=True)
    async def event(self, ctx):
        """Server events running now or coming up."""
        rows = self.db.events_of(ctx.guild.id)
        now = time.time()
        lines = []
        for row in rows:
            when = ("**now**, ends <t:%d:R>" % row["ends_at"] if row["starts_at"] <= now
                    else "<t:%d:f> for %s" % (row["starts_at"],
                                              describe_duration(row["ends_at"] - row["starts_at"])))
            lines.append(f"`#{row['id']}` {describe(row['kind'], row['strength'])} · {when}")
        note = "" if self.db.has_feature(ctx.guild.id, "events") else (
            f"\n\n*Server events come with {premium.needs('events')}."
            f" `{ctx.prefix}upgrade` to see how to get it.*")
        await ctx.send(embed=discord.Embed(
            title="Server events",
            description=("\n".join(lines) or
                         f"Nothing on. e.g. `{ctx.prefix}event start xp 2h`") + note,
            colour=self.db.get_pref(ctx.guild.id, "cardcolour", config.CARD_COLOUR)))

    @event.command(name="start")
    @commands.has_permissions(manage_guild=True)
    async def event_start(self, ctx, kind: str, length: str, strength: int = None):
        """Start one now: `xp`, `karuda` or `rolls`, a length like 2h, and
        optionally a strength (a percent, or a number of rolls)."""
        key = kind_of(kind)
        if not key:
            await ctx.send("Pick an event: `xp`, `karuda` or `rolls`.")
            return
        seconds = parse_duration(length)
        strength = KINDS[key][2] if strength is None else strength
        problem = self.schedule(ctx.guild.id, key, strength, time.time(), seconds,
                                ctx.channel.id, ctx.author.id)
        if problem:
            await ctx.send(problem + (f" `{ctx.prefix}upgrade` to see how to get it."
                                      if "Premium" in problem else ""))
            return
        # The announcer posts the start in this channel within a few seconds.
        await ctx.message.add_reaction("✅")

    @event.command(name="stop", aliases=["end", "cancel"])
    @commands.has_permissions(manage_guild=True)
    async def event_stop(self, ctx, event_id: int):
        """Stop an event now, or cancel one that hasn't started."""
        if self.db.end_event(ctx.guild.id, event_id):
            await ctx.message.add_reaction("✅")
        else:
            await ctx.send(f"There's no running or upcoming event #{event_id}.")

    # ----------------------------------------------------------- announcer

    @tasks.loop(seconds=20)
    async def announcer(self):
        for row in self.db.events_to_announce():
            guild = self.bot.get_guild(row["guild_id"])
            ended = row["ends_at"] <= time.time()
            if ended and row["announced"] == 0 and row["ends_at"] - row["starts_at"] <= 60:
                # Cancelled before it began: nothing to say.
                self.db.mark_event(row["id"], 2)
                continue
            self.db.mark_event(row["id"], 2 if ended else 1)
            channel = guild.get_channel(row["channel_id"]) if guild else None
            if not channel:
                continue
            name, emoji = KINDS[row["kind"]][:2]
            if ended:
                text = f"{emoji} **{name}** is over. Thanks for playing!"
            else:
                text = (f"{emoji} **{name} has started!** {describe(row['kind'], row['strength'])}"
                        f" for everyone, until <t:{row['ends_at']}:t>.")
            try:
                await channel.send(text)
            except discord.HTTPException:
                pass

    @announcer.before_loop
    async def before_announcer(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Events(bot))
