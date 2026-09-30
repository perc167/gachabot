"""Your standing at a glance, plus the small utility commands."""
import random
import time

import discord
from discord.ext import commands

import config
import perks
import wishes as wish_slots
import utils
from utils import fmt_duration

RPS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
RPS_ICON = {"rock": "\U0001faa8", "paper": "\U0001f4c4", "scissors": "✂️"}


# What the invite link asks for, here and on the website (tools/build_site.py
# reads it), so the two can't drift apart. A server owner can untick whatever
# part of the bot they won't use.
INVITE_PERMISSIONS = discord.Permissions(
    # The gacha. view_channel because the setup guide tells servers to give
    # the bot its own channel, and a locked one is invisible without it.
    view_channel=True,
    send_messages=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    use_external_emojis=True,
    # Moderation: jail and mute roles, kicks, bans, timeouts, purge, lockdown.
    manage_roles=True,
    manage_channels=True,
    kick_members=True,
    ban_members=True,
    moderate_members=True,
    manage_messages=True,
    manage_nicknames=True,
    view_audit_log=True,
    # Antinuke: deleting webhooks a nuke made.
    manage_webhooks=True,
    # Voice: Join To Create makes channels and moves people into them.
    connect=True,
    move_members=True,
)


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="profile", aliases=["me", "pr", "p", "overview"])
    @commands.guild_only()
    async def profile(self, ctx, member: discord.Member = None):
        """Everything about someone in one card."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, member.id)
        harem = db.harem(gid, member.id, "karuda")
        rate = db.get_setting(gid, "karuda_rate")
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])
        worth = sum(utils.karuda_value(r, rate) for r in harem)

        embed = discord.Embed(title=member.display_name, colour=config.CARD_COLOUR)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Balance", value=f"{icon} **{player['karuda']:,}**", inline=True
        )
        embed.add_field(name="Characters", value=f"{len(harem):,}", inline=True)
        embed.add_field(name="Harem worth", value=f"{worth:,}", inline=True)

        if harem:
            best = harem[0]
            embed.add_field(
                name="Best claim",
                value=f"**{best['name']}** · {best['series']}\n"
                      f"{icon} {utils.karuda_value(best, rate):,}"
                      f" · #{best['like_rank']:,}",
                inline=False,
            )
            if best["image_url"]:
                embed.set_image(url=best["image_url"])

        earned = perks.effective(db, gid, member.id)
        owned_badges = db.badges_of(gid, member.id)
        wished = wish_slots.used(db, gid, member.id)
        slots = wish_slots.capacity(db, gid, member.id)
        likes = len(db.likes_of(gid, member.id))
        shards = db.shards_of(gid, member.id)
        embed.add_field(
            name="Also",
            value=f"{wished}/{slots} wish slots · {likes} likes ·"
                  f" {len(shards)}/{len(config.SHARD_TYPES)} shard types",
            inline=False,
        )

        if owned_badges or player["tower_floor"]:
            marks = " ".join(
                perks.BADGES_BY_KEY[key][1]
                for key in owned_badges
                if key in perks.BADGES_BY_KEY
            )
            embed.add_field(
                name="Progress",
                value=f"Tower level **{player['tower_floor']}**  "
                      f"{perks.bar(player['tower_floor'] % perks.MAX_FLOOR or (perks.MAX_FLOOR if player['tower_floor'] else 0), perks.MAX_FLOOR)}"
                      + (f"\n{marks}" if marks else "")
                      + f"\n_{perks.describe(earned)}_",
                inline=False,
            )

        left, reset_in = self.bot.cooldowns.rolls_left(gid, member.id)
        claim_ready, claim_in = self.bot.cooldowns.claim_ready(gid, member.id)
        embed.set_footer(
            text=f"{left} rolls left, resets in {fmt_duration(reset_in)} · "
                 + ("claim ready" if claim_ready else f"claim in {fmt_duration(claim_in)}")
        )
        # The one character they chose with $fm, if they still own them.
        showcase = self.bot.db.showcase_of(ctx.guild.id, member.id)
        if showcase:
            embed.add_field(
                name="Showcase",
                value=f"**{showcase['name']}** · {showcase['series']}",
                inline=False,
            )
            if showcase["image_url"] and not str(
                    showcase["image_url"]).startswith(utils.LOCAL_ART):
                embed.set_thumbnail(url=showcase["image_url"])
        await ctx.send(embed=embed)

    @commands.command(name="myid", aliases=["id"])
    async def myid(self, ctx, member: discord.Member = None):
        """Your Discord user id, for BOT_OWNERS and the like."""
        member = member or ctx.author
        await ctx.send(f"`{member.id}`")

    @commands.command(name="invite")
    async def invite(self, ctx):
        """A link to add this bot to another server."""
        if not ctx.bot.user:
            await ctx.send("Not logged in yet.")
            return
        url = discord.utils.oauth_url(
            ctx.bot.user.id, permissions=INVITE_PERMISSIONS, scopes=("bot",)
        )
        await ctx.send(f"<{url}>")

    @commands.command(name="ping")
    async def ping(self, ctx):
        """Round trip time to Discord."""
        await ctx.send(f"Pong — {round(ctx.bot.latency * 1000)}ms.")

    @commands.command(name="stats", aliases=["botinfo", "mudainfo", "poolinfo"])
    @commands.guild_only()
    async def stats(self, ctx):
        """How big the pool is and how much of it this server has claimed."""
        db = self.bot.db
        gid = ctx.guild.id
        total = db.character_count(gid)
        claimed = db.conn.execute(
            "SELECT COUNT(*) AS c FROM marriages WHERE guild_id = ?", (gid,)
        ).fetchone()["c"]
        players = db.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE guild_id = ?", (gid,)
        ).fetchone()["c"]
        series = db.conn.execute(
            "SELECT COUNT(DISTINCT series) AS c FROM characters"
        ).fetchone()["c"]
        with_art, images = db.album_totals()

        embed = discord.Embed(title="Pool", colour=config.CARD_COLOUR)
        embed.add_field(name="Characters", value=f"{total:,}", inline=True)
        embed.add_field(name="Series", value=f"{series:,}", inline=True)
        embed.add_field(name="Images", value=f"{images:,}", inline=True)
        embed.add_field(
            name="Claimed here",
            value=f"{claimed:,} ({100 * claimed / max(1, total):.1f}%)",
            inline=True,
        )
        embed.add_field(name="Players here", value=f"{players:,}", inline=True)
        embed.add_field(
            name="With art", value=f"{100 * with_art / max(1, total):.0f}%", inline=True
        )
        await ctx.send(embed=embed)

    @commands.command(name="alea", aliases=["roll_dice", "rng"])
    async def alea(self, ctx, low: int = 1, high: int = 100):
        """A random number, for settling arguments."""
        if low > high:
            low, high = high, low
        if high - low > 10_000_000:
            await ctx.send("Keep the range under ten million.")
            return
        await ctx.send(f"**{random.randint(low, high):,}**  ({low:,}–{high:,})")

    @commands.command(name="jankenpon", aliases=["rps"])
    async def jankenpon(self, ctx, throw: str = None):
        """Rock, paper, scissors."""
        throw = (throw or "").lower()
        if throw not in RPS:
            await ctx.send(f"Pick one: {', '.join(RPS)}.")
            return
        mine = random.choice(list(RPS))
        if mine == throw:
            verdict = "A draw."
        elif RPS[throw] == mine:
            verdict = "You win."
        else:
            verdict = "I win."
        await ctx.send(
            f"{RPS_ICON[throw]} vs {RPS_ICON[mine]} — {verdict}"
        )

    @commands.command(name="uptime")
    async def uptime(self, ctx):
        """How long the bot has been running."""
        started = getattr(ctx.bot, "started_at", None)
        if not started:
            await ctx.send("Not recorded.")
            return
        await ctx.send(f"Up for {fmt_duration(int(time.time() - started))}.")


async def setup(bot):
    await bot.add_cog(Profile(bot))
