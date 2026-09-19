"""Karuda: the currency. Balance, daily, transfers, leaderboard."""
import random

import discord
from discord.ext import commands

import config
import utils
from utils import fmt_duration

DAILY_COOLDOWN = 20 * 60 * 60  # 20 hours, so it drifts earlier each day
DAILY_MIN, DAILY_MAX = 150, 400


class Karuda(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="balance", aliases=["k", "karuda", "bal"])
    @commands.guild_only()
    async def balance(self, ctx, member: discord.Member = None):
        """Check a karuda balance."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, member.id)
        rows = db.harem(gid, member.id)
        rate = db.get_setting(gid, "karuda_rate")
        harem_worth = sum(utils.karuda_value(r, rate) for r in rows)

        embed = discord.Embed(
            title=f"{member.display_name}", colour=config.CARD_COLOUR
        )
        icon = config.SHARD_TYPES[0][2]
        embed.add_field(
            name="Balance", value=f"{icon} **{player['karuda']:,}**", inline=True
        )
        embed.add_field(
            name="Harem worth", value=f"{harem_worth:,}", inline=True
        )
        embed.add_field(name="Characters", value=f"{len(rows):,}", inline=True)

        # Which shards they have pulled, in the order they get rarer.
        pulled = db.shards_of(gid, member.id)
        if pulled:
            lines = []
            for key, name, shard_icon, _, _, _ in config.SHARD_TYPES:
                count = pulled.get(key, 0)
                if count:
                    lines.append(f"{shard_icon} {name} ×{count}")
                else:
                    lines.append(f"— *{name}*")
            embed.add_field(name="Shards pulled", value="\n".join(lines), inline=False)
            found = sum(1 for k, *_ in config.SHARD_TYPES if pulled.get(k))
            embed.set_footer(text=f"{found}/{len(config.SHARD_TYPES)} shard types found")
        await ctx.send(embed=embed)

    @commands.command(name="daily")
    @commands.guild_only()
    async def daily(self, ctx):
        """Free karuda, once every 20 hours."""
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, ctx.author.id)
        remaining = player["daily_ready_at"] - utils.now()
        if remaining > 0:
            await ctx.send(f"Next daily in {fmt_duration(remaining)}.")
            return
        # The pull is the point: which shard you get decides the payout.
        key, name, icon, multiplier, _, colour = config.roll_shard(random)
        base = random.randint(DAILY_MIN, DAILY_MAX)
        amount = round(base * multiplier)

        total = db.add_karuda(gid, ctx.author.id, amount)
        pulled = db.record_shard(gid, ctx.author.id, key)
        db.update_player(
            gid, ctx.author.id, daily_ready_at=utils.now() + DAILY_COOLDOWN
        )

        odds = 100 * config.shard(key)[4] / sum(s[4] for s in config.SHARD_TYPES)
        embed = discord.Embed(
            title=f"{icon}  {name}",
            description=f"{ctx.author.mention} pulled **{amount:,}** {config.CURRENCY}.",
            colour=colour,
        )
        embed.add_field(name="Multiplier", value=f"×{multiplier:g}", inline=True)
        embed.add_field(name="Balance", value=f"{total:,}", inline=True)
        embed.add_field(name="Pulled before", value=f"{pulled - 1}", inline=True)
        rarity_note = f"{odds:.0f}% chance" if odds >= 1 else f"{odds:.1f}% chance"
        embed.set_footer(text=f"{rarity_note} • next daily in 20h")
        await ctx.send(embed=embed)

    @commands.command(name="shards", aliases=["types"])
    async def shards(self, ctx):
        """What each shard type is worth, and how often it turns up."""
        total_weight = sum(s[4] for s in config.SHARD_TYPES)
        lines = []
        for _, name, icon, multiplier, weight, _ in config.SHARD_TYPES:
            chance = 100 * weight / total_weight
            shown = f"{chance:.0f}%" if chance >= 1 else f"{chance:.1f}%"
            lines.append(f"{icon} **{name}** — ×{multiplier:g} payout, {shown}")
        embed = discord.Embed(
            title=f"{config.CURRENCY_TITLE} shards",
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        embed.set_footer(text=f"One pull per {ctx.prefix}daily, every 20 hours.")
        await ctx.send(embed=embed)

    @commands.command(name="pay", aliases=["sendkaruda"])
    @commands.guild_only()
    async def pay(self, ctx, member: discord.Member, amount: int):
        """Send karuda to someone."""
        if member.bot or member.id == ctx.author.id:
            await ctx.send("Pick a different person.")
            return
        if amount <= 0:
            await ctx.send("Amount must be positive.")
            return
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, ctx.author.id)
        if player["karuda"] < amount:
            await ctx.send(f"You only have {player['karuda']} karuda.")
            return
        db.add_karuda(gid, ctx.author.id, -amount)
        total = db.add_karuda(gid, member.id, amount)
        await ctx.send(
            f"{ctx.author.mention} sent **{amount}** karuda to {member.mention}"
            f" (their total: {total})."
        )

    @commands.command(name="richest", aliases=["klb", "karudatop"])
    @commands.guild_only()
    async def richest(self, ctx):
        """Karuda leaderboard for this server."""
        rows = self.bot.db.top_karuda(ctx.guild.id, limit=10)
        if not rows:
            await ctx.send("Nobody has any karuda yet.")
            return
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        lines = []
        for i, row in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(f"{prefix} <@{row['user_id']}> — **{row['karuda']}**")
        embed = discord.Embed(
            title=f"Richest in {ctx.guild.name}",
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Karuda(bot))
