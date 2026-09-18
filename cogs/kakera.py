"""Kakera: the currency. Balance, daily, transfers, leaderboard."""
import random

import discord
from discord.ext import commands

import utils
from utils import fmt_duration

DAILY_COOLDOWN = 20 * 60 * 60  # 20 hours, so it drifts earlier each day
DAILY_MIN, DAILY_MAX = 150, 400


class Kakera(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="balance", aliases=["k", "kakera", "bal"])
    @commands.guild_only()
    async def balance(self, ctx, member: discord.Member = None):
        """Check a kakera balance."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, member.id)
        rows = db.harem(gid, member.id)
        rate = db.get_setting(gid, "kakera_rate")
        harem_worth = sum(utils.kakera_value(r, rate) for r in rows)

        embed = discord.Embed(
            title=f"{member.display_name}'s kakera", colour=0xB388EB
        )
        embed.add_field(name="Balance", value=f"**{player['kakera']}**", inline=True)
        embed.add_field(name="Harem worth", value=f"{harem_worth}", inline=True)
        embed.add_field(
            name="Characters", value=f"{len(rows)}", inline=True
        )
        await ctx.send(embed=embed)

    @commands.command(name="daily")
    @commands.guild_only()
    async def daily(self, ctx):
        """Free kakera, once every 20 hours."""
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, ctx.author.id)
        remaining = player["daily_ready_at"] - utils.now()
        if remaining > 0:
            await ctx.send(f"Next daily in {fmt_duration(remaining)}.")
            return
        amount = random.randint(DAILY_MIN, DAILY_MAX)
        total = db.add_kakera(gid, ctx.author.id, amount)
        db.update_player(
            gid, ctx.author.id, daily_ready_at=utils.now() + DAILY_COOLDOWN
        )
        await ctx.send(
            f"{ctx.author.mention} claimed **{amount}** kakera. Total: {total}."
        )

    @commands.command(name="pay", aliases=["sendkakera"])
    @commands.guild_only()
    async def pay(self, ctx, member: discord.Member, amount: int):
        """Send kakera to someone."""
        if member.bot or member.id == ctx.author.id:
            await ctx.send("Pick a different person.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, ctx.author.id)
        if player["kakera"] < amount:
            await ctx.send(f"You only have {player['kakera']} kakera.")
            return
        db.add_kakera(gid, ctx.author.id, -amount)
        total = db.add_kakera(gid, member.id, amount)
        await ctx.send(
            f"{ctx.author.mention} sent **{amount}** kakera to {member.mention}"
            f" (their total: {total})."
        )

    @commands.command(name="richest", aliases=["klb", "kakeratop"])
    @commands.guild_only()
    async def richest(self, ctx):
        """Kakera leaderboard for this server."""
        rows = self.bot.db.top_kakera(ctx.guild.id, limit=10)
        if not rows:
            await ctx.send("Nobody has any kakera yet.")
            return
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        lines = []
        for i, row in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(f"{prefix} <@{row['user_id']}> — **{row['kakera']}**")
        embed = discord.Embed(
            title=f"Richest in {ctx.guild.name}",
            description="\n".join(lines),
            colour=0xF4A261,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Kakera(bot))
