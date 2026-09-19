"""Harem browsing, character lookup, divorces, notes, leaderboards."""
import discord
from discord.ext import commands

import config
import utils
from views import Paginator

ORDERS = ("likes", "name", "recent", "karuda")


class Harem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="harem", aliases=["mm", "hl"])
    @commands.guild_only()
    async def harem(self, ctx, member: discord.Member = None, order: str = "likes"):
        """List a harem. `$mm @user recent` sorts by claim time."""
        member = member or ctx.author
        if order not in ORDERS:
            order = "likes"

        db = self.bot.db
        gid = ctx.guild.id
        rows = db.harem(gid, member.id, order)
        if not rows:
            await ctx.send(f"{member.display_name} has not claimed anyone yet.")
            return

        rate = db.get_setting(gid, "karuda_rate")
        total_likes = sum(r["likes"] for r in rows)
        total_karuda = sum(utils.karuda_value(r, rate) for r in rows)

        lines = []
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])
        for i, row in enumerate(rows, 1):
            note = f" — _{row['note']}_" if row["note"] else ""
            lines.append(
                f"`{i:>3}.` **{row['name']}** · {row['series']}\n"
                f"       {icon} {utils.karuda_value(row, rate):,}"
                f" · #{row['like_rank']:,}{note}"
            )

        embeds = []
        pages = utils.paginate(lines, 8)
        for page_no, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{member.display_name}'s harem — {len(rows)} characters",
                description="\n".join(page),
                colour=config.CARD_COLOUR,
            )
            embed.set_footer(
                text=f"Page {page_no}/{len(pages)} • {total_likes} likes"
                f" • {total_karuda} karuda • sorted by {order}"
            )
            embeds.append(embed)

        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="info", aliases=["im", "char"])
    @commands.guild_only()
    async def info(self, ctx, *, name: str):
        """Look up a character by name."""
        character = self.bot.db.find_character_by_name(name)
        if not character:
            await ctx.send(f"No character matching `{name}`.")
            return
        embed = utils.character_embed(
            self.bot.db, ctx.guild.id, character, footer=f"ID {character['id']}"
        )
        await ctx.send(embed=embed)

    @commands.command(name="search", aliases=["sc"])
    @commands.guild_only()
    async def search(self, ctx, *, query: str):
        """Search the pool by character or series name."""
        rows = self.bot.db.search_characters(query, limit=25)
        if not rows:
            await ctx.send(f"Nothing matches `{query}`.")
            return
        lines = []
        for row in rows:
            owner = self.bot.db.owner_of(ctx.guild.id, row["id"])
            tag = f" — <@{owner}>" if owner else ""
            lines.append(
                f"`{row['id']:>4}` **{row['name']}** · {row['series']}"
                f" · #{row['like_rank']:,}{tag}"
            )
        embed = discord.Embed(
            title=f"Results for {query}",
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        await ctx.send(embed=embed)

    @commands.command(name="divorce", aliases=["dv"])
    @commands.guild_only()
    async def divorce(self, ctx, *, name: str):
        """Release a character back into the pool. Refunds half their karuda."""
        db = self.bot.db
        gid = ctx.guild.id
        character = db.find_character_by_name(name)
        if not character:
            await ctx.send(f"No character matching `{name}`.")
            return
        if not db.divorce(gid, character["id"], ctx.author.id):
            await ctx.send(f"You do not own **{character['name']}**.")
            return
        rate = db.get_setting(gid, "karuda_rate")
        refund = max(1, utils.karuda_value(character, rate) // 2)
        total = db.add_karuda(gid, ctx.author.id, refund)
        await ctx.send(
            f"Divorced **{character['name']}**. +{refund} karuda (total: {total})."
        )

    @commands.command(name="note")
    @commands.guild_only()
    async def note(self, ctx, *, args: str):
        """`$note <name> | <text>` — annotate one of your characters."""
        if "|" not in args:
            await ctx.send(f"Usage: `{ctx.prefix}note <name> | <text>`")
            return
        name, _, text = args.partition("|")
        character = self.bot.db.find_character_by_name(name.strip())
        if not character:
            await ctx.send(f"No character matching `{name.strip()}`.")
            return
        text = text.strip()[:200]
        if self.bot.db.set_note(
            ctx.guild.id, character["id"], ctx.author.id, text or None
        ):
            await ctx.send(f"Note set on **{character['name']}**.")
        else:
            await ctx.send(f"You do not own **{character['name']}**.")

    @commands.command(name="top", aliases=["lb", "leaderboard"])
    @commands.guild_only()
    async def top(self, ctx):
        """Biggest harems in this server."""
        rows = self.bot.db.top_harems(ctx.guild.id, limit=10)
        if not rows:
            await ctx.send("Nobody has claimed anyone yet.")
            return
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        lines = []
        for i, row in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(
                f"{prefix} <@{row['user_id']}> — **{row['owned']}**"
                f" characters • {row['likes']} ♥"
            )
        embed = discord.Embed(
            title=f"Top harems in {ctx.guild.name}",
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Harem(bot))
