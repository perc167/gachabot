"""Leaderboards, and the state of the server at a glance.

Mudae has a long row of $topserv variants sliced by year. Years mean nothing
here yet - the bot has not been running for one - so these slice by the
things that actually exist: who owns the most, whose harem is worth the most,
which series this server has taken to, and who everybody is waiting for.

Every one of them is a real query against this server's own data, never a
global number dressed up as a local one.
"""
import discord
from discord.ext import commands

import config
import utils


def board(db, guild_id: int, title: str, lines, note: str = None):
    embed = discord.Embed(
        title=title,
        description="\n".join(lines) if lines else "Nothing here yet.",
        colour=db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR),
    )
    if note:
        embed.set_footer(text=note)
    return embed


MEDALS = ("\U0001f947", "\U0001f948", "\U0001f949")


def place(index: int) -> str:
    return MEDALS[index] if index < len(MEDALS) else f"`{index + 1:>2}.`"


class Leaderboards(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="topvalue", aliases=["topservv", "tsv", "richestharem"])
    @commands.guild_only()
    async def topvalue(self, ctx):
        """Whose characters are worth the most, added up."""
        db = self.bot.db
        rate = db.get_setting(ctx.guild.id, "karuda_rate")
        rows = db.top_harem_value(ctx.guild.id)
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])
        lines = [
            f"{place(i)} <@{row['user_id']}> — {icon} **"
            f"{int(row['worth'] * rate / 100):,}** across {row['owned']} characters"
            for i, row in enumerate(rows)
        ]
        await ctx.send(embed=board(
            db, ctx.guild.id, f"\U0001f4b0  Richest harems in {ctx.guild.name}",
            lines))

    @commands.command(name="topclaims", aliases=["topowners", "topclaimers"])
    @commands.guild_only()
    async def topclaims(self, ctx):
        """Who has claimed the most characters here."""
        db = self.bot.db
        rows = db.top_claimers(ctx.guild.id)
        lines = [
            f"{place(i)} <@{row['user_id']}> — **{row['owned']:,}** characters"
            for i, row in enumerate(rows)
        ]
        await ctx.send(embed=board(
            db, ctx.guild.id, f"\U0001f48d  Biggest harems in {ctx.guild.name}",
            lines))

    @commands.command(name="topseries", aliases=["seriestop", "topfandom"])
    @commands.guild_only()
    async def topseries(self, ctx):
        """Which series this server has claimed the most of."""
        db = self.bot.db
        rows = db.top_series(ctx.guild.id)
        lines = [
            f"{place(i)} **{row['series']}** — {row['claimed']:,} claimed"
            for i, row in enumerate(rows)
        ]
        await ctx.send(embed=board(
            db, ctx.guild.id, f"\U0001f4fa  This server's taste", lines,
            "what people here actually claim, not what is popular globally"))

    @commands.command(name="topwished", aliases=["topservy", "tsy", "mostwished"])
    @commands.guild_only()
    async def topwished(self, ctx):
        """Who the most people here are waiting for."""
        db = self.bot.db
        rows = db.top_wished(ctx.guild.id)
        lines = [
            f"{place(i)} **{row['name']}** · {row['series']} — "
            f"{row['wishers']} waiting"
            for i, row in enumerate(rows)
        ]
        await ctx.send(embed=board(
            db, ctx.guild.id, f"⭐  Most wished for here", lines))

    @commands.command(name="topshards", aliases=["tsk", "topcollectors"])
    @commands.guild_only()
    async def topshards(self, ctx):
        """Who has pulled the most shards."""
        db = self.bot.db
        rows = db.top_shards(ctx.guild.id)
        lines = [
            f"{place(i)} <@{row['user_id']}> — **{row['pulled']:,}** shards"
            for i, row in enumerate(rows)
        ]
        await ctx.send(embed=board(
            db, ctx.guild.id, f"\U0001f48e  Shard collectors", lines))

    @commands.command(name="serveroverview", aliases=["serverstats", "tu", "tus"])
    @commands.guild_only()
    async def overview(self, ctx):
        """How far along this server is, in one card."""
        db = self.bot.db
        gid = ctx.guild.id
        counts = db.guild_overview(gid)
        pool = db.character_count()
        share = 100 * counts["claimed"] / pool if pool else 0

        embed = discord.Embed(
            title=f"\U0001f4ca  {ctx.guild.name}",
            colour=db.get_pref(gid, "cardcolour", config.CARD_COLOUR),
        )
        embed.add_field(
            name="Claimed",
            value=f"**{counts['claimed']:,}** characters\n"
                  f"from **{counts['series']:,}** series\n"
                  f"*{share:.3f}% of the pool*",
            inline=True,
        )
        embed.add_field(
            name="People",
            value=f"**{counts['players']:,}** playing\n"
                  f"**{counts['karuda']:,}** {config.CURRENCY} held",
            inline=True,
        )
        embed.add_field(
            name="Elsewhere",
            value=f"**{counts['wishes']:,}** wishes\n"
                  f"**{counts['likes']:,}** likes\n"
                  f"**{counts['customs']:,}** invented here",
            inline=True,
        )
        embed.set_footer(
            text=f"{pool:,} characters in the pool · "
                 f"{counts['aliases']:,} nicknames taught"
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Leaderboards(bot))
