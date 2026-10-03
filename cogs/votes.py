"""top.gg votes: a karuda reward for voting, and a weekly giveaway drawn from votes.

How a vote gets here: top.gg calls POST /topgg/webhook on the bot's web server
(cogs/dashboard.py routes it to handle_webhook) with the secret from
TOPGG_WEBHOOK_SECRET in the Authorization header.

$vote          the vote link; collects any banked rewards in this server
$votes         (owner) this week's votes, top voters and the last winner
$votegiveaway  (owner) where the weekly winner is announced:
               $votegiveaway #channel [@role] · off · draw

A vote isn't tied to a server and karuda is per server, so a vote banks its
reward and $vote pays it out wherever it's used. Weekend votes count double
on top.gg, so they bank double here too.

Every vote is one entry in that week's draw: someone who votes every 12 hours
has more chances than someone who voted once. Weeks run Monday to Monday,
Queensland time, and the draw happens just after a week ends.
"""
import hmac
import logging
import os
import random
import time

import discord
from discord.ext import commands, tasks

log = logging.getLogger("votes")

REWARD = 300          # karuda per vote, doubled on weekends
BANK_LIMIT = 10       # unclaimed votes kept; older ones lapse
WEEK = 7 * 86400
OFFSET = 10 * 3600    # Queensland, UTC+10 with no daylight saving
MONDAY = 4 * 86400    # 1970-01-01 was a Thursday; the 5th a Monday
GOLD = 0xE5C55A
TOPGG_BOT_ID = 1550497695582519418
VOTE_URL = f"https://top.gg/bot/{TOPGG_BOT_ID}/vote"
DUPLICATE_WINDOW = 60  # top.gg retries; the same voter within this is one vote

SCHEMA = """
CREATE TABLE IF NOT EXISTS votes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    voted_at      INTEGER NOT NULL,
    weekend       INTEGER NOT NULL DEFAULT 0,
    claimed_guild INTEGER NOT NULL DEFAULT 0,
    claimed_at    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS votes_by_time ON votes (voted_at);
CREATE INDEX IF NOT EXISTS votes_by_user ON votes (user_id, claimed_at);
CREATE TABLE IF NOT EXISTS vote_draws (
    week      INTEGER PRIMARY KEY,
    user_id   INTEGER NOT NULL,
    vote_id   INTEGER NOT NULL,
    entries   INTEGER NOT NULL,
    voters    INTEGER NOT NULL,
    drawn_at  INTEGER NOT NULL
);
"""


def week_of(timestamp: float) -> int:
    """Which Monday-to-Monday week (Queensland time) a moment falls in."""
    return int((timestamp + OFFSET - MONDAY) // WEEK)


def week_start(week: int) -> int:
    return week * WEEK + MONDAY - OFFSET


class Votes(commands.Cog):
    works_everywhere = True  # not part of the gacha channels; see bot.check_allowed

    def __init__(self, bot):
        self.bot = bot
        self.rng = random.SystemRandom()

    @property
    def conn(self):
        return self.bot.db.conn

    async def cog_load(self):
        with self.conn:
            self.conn.executescript(SCHEMA)
        self.weekly.start()

    async def cog_unload(self):
        self.weekly.cancel()

    # ---------------------------------------------------------- recording

    def record(self, user_id: int, weekend: bool, now: float = None) -> bool:
        """Save a vote. False if it's top.gg retrying one already saved."""
        now = int(now or time.time())
        recent = self.conn.execute(
            "SELECT 1 FROM votes WHERE user_id = ? AND voted_at > ?",
            (user_id, now - DUPLICATE_WINDOW)).fetchone()
        if recent:
            return False
        with self.conn:
            self.conn.execute("INSERT INTO votes (user_id, voted_at, weekend) VALUES (?, ?, ?)",
                              (user_id, now, int(bool(weekend))))
        return True

    def banked(self, user_id: int) -> list:
        """Unclaimed votes, newest first, up to BANK_LIMIT."""
        return self.conn.execute(
            "SELECT id, weekend FROM votes WHERE user_id = ? AND claimed_at = 0"
            " ORDER BY voted_at DESC LIMIT ?", (user_id, BANK_LIMIT)).fetchall()

    def claim(self, guild_id: int, user_id: int, now: float = None) -> int:
        """Pay banked votes into this server's karuda. Returns the karuda paid."""
        now = int(now or time.time())
        rows = self.banked(user_id)
        if not rows:
            return 0
        amount = sum(REWARD * (2 if r["weekend"] else 1) for r in rows)
        with self.conn:
            # Older unclaimed votes past the bank limit lapse with this claim.
            self.conn.execute(
                "UPDATE votes SET claimed_guild = ?, claimed_at = ?"
                " WHERE user_id = ? AND claimed_at = 0", (guild_id, now, user_id))
        self.bot.db.add_karuda(guild_id, user_id, amount)
        return amount

    def week_votes(self, week: int) -> list:
        start = week_start(week)
        return self.conn.execute(
            "SELECT id, user_id, voted_at FROM votes WHERE voted_at >= ? AND voted_at < ?"
            " ORDER BY id", (start, start + WEEK)).fetchall()

    def entries_of(self, user_id: int, week: int) -> int:
        return sum(1 for v in self.week_votes(week) if v["user_id"] == user_id)

    # ------------------------------------------------------------ webhook

    async def handle_webhook(self, authorization: str, payload: dict) -> int:
        """top.gg's POST. Returns the HTTP status to answer with."""
        secret = os.getenv("TOPGG_WEBHOOK_SECRET", "")
        if not secret or not hmac.compare_digest(authorization or "", secret):
            return 401
        try:
            user_id = int(payload["user"])
        except (KeyError, TypeError, ValueError):
            return 400
        if payload.get("type") == "test":
            log.info("top.gg test vote from %s", user_id)
            return 200
        weekend = bool(payload.get("isWeekend"))
        if self.record(user_id, weekend):
            await self.thank(user_id, weekend)
        return 200

    async def thank(self, user_id: int, weekend: bool):
        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except discord.HTTPException:
                return
        entries = self.entries_of(user_id, week_of(time.time()))
        reward = REWARD * (2 if weekend else 1)
        embed = discord.Embed(
            title="Thanks for voting for Paper! \U0001f49c",
            colour=GOLD,
            description=(
                f"**{reward:,} karuda** is waiting for you"
                + (" (doubled for the weekend)" if weekend else "")
                + ". Use `/vote` in any server to collect it there.\n\n"
                f"\U0001f39f️ You have **{entries}** "
                + ("entry" if entries == 1 else "entries")
                + " in this week's giveaway. Vote again in 12 hours for another."))
        try:
            await user.send(embed=embed)
        except discord.HTTPException:
            pass  # closed DMs: the reward is still banked

    # --------------------------------------------------------------- draw

    def draw(self, week: int, now: float = None):
        """Pick that week's winner: one random vote. None if nobody voted
        or it was drawn already."""
        if self.conn.execute("SELECT 1 FROM vote_draws WHERE week = ?", (week,)).fetchone():
            return None
        votes = self.week_votes(week)
        if not votes:
            return None
        winner = self.rng.choice(votes)
        result = {"week": week, "user_id": winner["user_id"], "vote_id": winner["id"],
                  "voted_at": winner["voted_at"], "entries": len(votes),
                  "voters": len({v["user_id"] for v in votes}),
                  "theirs": sum(1 for v in votes if v["user_id"] == winner["user_id"])}
        with self.conn:
            self.conn.execute(
                "INSERT INTO vote_draws (week, user_id, vote_id, entries, voters, drawn_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (week, result["user_id"], result["vote_id"], result["entries"],
                 result["voters"], int(now or time.time())))
        return result

    def announcement(self, result: dict, winner) -> tuple:
        """(content, embed, view) for the winner's post."""
        start = week_start(result["week"])
        next_draw = week_start(result["week"] + 2)
        odds = result["theirs"] / result["entries"] * 100
        embed = discord.Embed(
            title="\U0001f389  Weekly Vote Giveaway  \U0001f389",
            colour=GOLD,
            description=(
                f"## Congratulations {winner.mention}!\n"
                "You've won this week's vote giveaway. \U0001f3c6\n\n"
                f"\U0001f5f3️ **{result['entries']:,}** votes from"
                f" **{result['voters']:,}** "
                + ("person" if result["voters"] == 1 else "people")
                + f" were in the draw, <t:{start}:d> to <t:{start + WEEK}:d>."))
        embed.add_field(name="\U0001f39f️ Their entries", value=f"{result['theirs']}")
        embed.add_field(name="\U0001f3b2 Their odds", value=f"{odds:.1f}%")
        embed.add_field(name="\U0001f552 Winning vote", value=f"<t:{result['voted_at']}:f>")
        embed.add_field(name="​", inline=False, value=(
            "**Want to win next week?** Every vote is an entry, and you can vote"
            f" every 12 hours. Next draw <t:{next_draw}:R>."))
        embed.set_thumbnail(url=winner.display_avatar.url)
        if self.bot.user:
            embed.set_author(name="Paper", icon_url=self.bot.user.display_avatar.url)
        embed.set_footer(text="Drawn at random from every vote on top.gg")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Vote for Paper", emoji="\U0001f5f3️",
                                        url=VOTE_URL))
        role_id = self.bot.db.get_pref(0, "vote_role", 0)
        content = (f"<@&{role_id}> " if role_id else "") + f"\U0001f389 {winner.mention}"
        return content, embed, view

    async def announce(self, result: dict) -> bool:
        channel = self.bot.get_channel(self.bot.db.get_pref(0, "vote_channel", 0))
        winner = self.bot.get_user(result["user_id"])
        if winner is None:
            try:
                winner = await self.bot.fetch_user(result["user_id"])
            except discord.HTTPException:
                return False
        if channel is not None:
            content, embed, view = self.announcement(result, winner)
            try:
                await channel.send(content, embed=embed, view=view,
                                   allowed_mentions=discord.AllowedMentions(users=True, roles=True))
            except discord.HTTPException:
                log.exception("couldn't post the vote giveaway winner")
        try:
            await winner.send(embed=discord.Embed(
                title="\U0001f389 You won Paper's weekly vote giveaway!", colour=GOLD,
                description="Keep an eye on your DMs and the announcement for your prize."))
        except discord.HTTPException:
            pass
        return channel is not None

    @tasks.loop(minutes=10)
    async def weekly(self):
        last_week = week_of(time.time()) - 1
        result = self.draw(last_week)
        if result:
            await self.announce(result)

    @weekly.before_loop
    async def before_weekly(self):
        await self.bot.wait_until_ready()

    # ----------------------------------------------------------- commands

    @commands.command(name="vote", aliases=["topgg"])
    async def vote(self, ctx):
        """Vote for Paper on top.gg: karuda for you, and an entry in the weekly giveaway."""
        paid = self.claim(ctx.guild.id, ctx.author.id) if ctx.guild else 0
        week = week_of(time.time())
        entries = self.entries_of(ctx.author.id, week)
        lines = []
        if paid:
            lines.append(f"\U0001f4b0 Collected **{paid:,} karuda** from your votes, here in"
                         f" **{discord.utils.escape_markdown(ctx.guild.name)}**.")
        elif self.banked(ctx.author.id):
            lines.append("You have votes waiting: use this in a server to collect the karuda.")
        lines.append(f"Each vote gives **{REWARD:,} karuda** (double on weekends) and an"
                     " entry in the weekly giveaway. You can vote every 12 hours.")
        lines.append(f"\U0001f39f️ Your entries this week: **{entries}** · draw"
                     f" <t:{week_start(week + 1)}:R>")
        embed = discord.Embed(title="Vote for Paper", colour=GOLD, description="\n\n".join(lines))
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Vote on top.gg", emoji="\U0001f5f3️", url=VOTE_URL))
        await ctx.send(embed=embed, view=view)

    @commands.command(name="votes")
    @commands.is_owner()
    async def votes(self, ctx):
        """This week's votes, the top voters, and the last winner."""
        week = week_of(time.time())
        votes = self.week_votes(week)
        counts = {}
        for v in votes:
            counts[v["user_id"]] = counts.get(v["user_id"], 0) + 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:10]
        last = self.conn.execute(
            "SELECT * FROM vote_draws ORDER BY week DESC LIMIT 1").fetchone()
        channel = self.bot.get_channel(self.bot.db.get_pref(0, "vote_channel", 0))
        lines = [f"**{len(votes)}** votes from **{len(counts)}** people this week."
                 f" Draw <t:{week_start(week + 1)}:R>."]
        if top:
            lines.append("\n".join(f"`{n:>3}` <@{uid}>" for uid, n in top))
        lines.append(f"Last winner: <@{last['user_id']}> ({last['entries']} entries)"
                     if last else "No draws yet.")
        lines.append(f"Announced in: {channel.mention}" if channel else
                     f"No announcement channel: `{ctx.prefix}votegiveaway #channel`.")
        if not os.getenv("TOPGG_WEBHOOK_SECRET"):
            lines.append("⚠️ TOPGG_WEBHOOK_SECRET isn't set, so top.gg votes can't arrive.")
        await ctx.send(embed=discord.Embed(title="Votes", colour=GOLD,
                                           description="\n\n".join(lines)),
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="votegiveaway")
    @commands.is_owner()
    async def votegiveaway(self, ctx, channel: discord.TextChannel = None,
                           role: discord.Role = None, *, word: str = ""):
        """Where the weekly vote winner is announced, or `draw` to draw last week now."""
        word = word.lower()
        if channel is None and word == "off":
            self.bot.db.set_pref(0, "vote_channel", 0)
            return await ctx.send("Winners won't be announced (they're still drawn and DMed).")
        if channel is None and word == "draw":
            result = self.draw(week_of(time.time()) - 1)
            if not result:
                return await ctx.send("Nothing to draw: last week had no votes or was drawn already.")
            await self.announce(result)
            return await ctx.send(f"Drew <@{result['user_id']}> from {result['entries']} votes.",
                                  allowed_mentions=discord.AllowedMentions.none())
        if channel is None:
            current = self.bot.get_channel(self.bot.db.get_pref(0, "vote_channel", 0))
            return await ctx.send(
                (f"Winners are announced in {current.mention}." if current else
                 "No announcement channel yet.")
                + f" `{ctx.prefix}votegiveaway #channel [@role]` sets it, `off` stops it,"
                  " `draw` draws last week now.")
        self.bot.db.set_pref(0, "vote_channel", channel.id)
        self.bot.db.set_pref(0, "vote_role", role.id if role else 0)
        await ctx.send(f"Each week's winner will be announced in {channel.mention}"
                       + (f", pinging {role.mention}." if role else "."),
                       allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Votes(bot))
