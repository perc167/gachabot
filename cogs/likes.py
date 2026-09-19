"""Likes: a vote for a character, separate from owning them.

Characters carried a `likes` number from the start but nothing ever set it.
This is what sets it: anyone can like anyone, whether or not they own them,
and the server's own tally is what shows on the card.
"""
import discord
from discord.ext import commands

import config
import utils
from views import Paginator, choose_character


class Likes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _resolve(self, ctx, name: str):
        matches = self.bot.db.find_characters_by_name(name)
        if not matches:
            await ctx.send(f"No character matching `{name}`.")
            return None
        return await choose_character(
            ctx, matches, "Which character?", config.CARD_COLOUR
        )

    @commands.command(name="like", aliases=["lk"])
    @commands.guild_only()
    async def like(self, ctx, *, name: str):
        """Like a character. One vote each, take it back with $unlike."""
        character = await self._resolve(ctx, name)
        if not character:
            return
        db = self.bot.db
        gid = ctx.guild.id
        if not db.add_like(gid, ctx.author.id, character["id"]):
            await ctx.send(f"You already like **{character['name']}**.")
            return
        votes = db.like_count(gid, character["id"])
        position = db.like_position(gid, character["id"])
        await ctx.send(
            f"{ctx.author.mention} likes **{character['name']}** ·"
            f" {character['series']} — now **{votes}** like(s) here,"
            f" #{position} on this server."
        )

    @commands.command(name="unlike", aliases=["likeremove"])
    @commands.guild_only()
    async def unlike(self, ctx, *, name: str):
        """Take back a like."""
        character = await self._resolve(ctx, name)
        if not character:
            return
        if self.bot.db.remove_like(ctx.guild.id, ctx.author.id, character["id"]):
            await ctx.send(f"Unliked **{character['name']}**.")
        else:
            await ctx.send(f"You did not like **{character['name']}**.")

    @commands.command(name="likelist", aliases=["ll", "likes"])
    @commands.guild_only()
    async def likelist(self, ctx, member: discord.Member = None):
        """Everyone you have liked."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.likes_of(gid, member.id)
        if not rows:
            await ctx.send(f"{member.display_name} has not liked anyone yet.")
            return

        lines = [
            f"`{i:>3}.` **{row['name']}** · {row['series']}"
            f" · {db.like_count(gid, row['id'])} ♥"
            for i, row in enumerate(rows, 1)
        ]
        pages = utils.paginate(lines, 10)
        embeds = []
        for number, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{member.display_name}'s likes — {len(rows)}",
                description="\n".join(page),
                colour=config.CARD_COLOUR,
            )
            embed.set_footer(text=f"Page {number}/{len(pages)}")
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="likeclear")
    @commands.guild_only()
    async def likeclear(self, ctx):
        """Drop every like you have given on this server."""
        removed = self.bot.db.clear_likes(ctx.guild.id, ctx.author.id)
        if removed:
            await ctx.send(f"Cleared **{removed}** like(s).")
        else:
            await ctx.send("You had no likes to clear.")

    @commands.command(name="mostliked", aliases=["topliked", "tl"])
    @commands.guild_only()
    async def mostliked(self, ctx):
        """The server's favourite characters."""
        rows = self.bot.db.most_liked(ctx.guild.id, limit=10)
        if not rows:
            await ctx.send(f"Nobody has liked anyone yet. Try `{ctx.prefix}like`.")
            return
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} **{row['name']}**"
            f" · {row['series']} — {row['votes']} ♥"
            for i, row in enumerate(rows)
        ]
        await ctx.send(
            embed=discord.Embed(
                title=f"Most liked in {ctx.guild.name}",
                description="\n".join(lines),
                colour=config.CARD_COLOUR,
            )
        )

    @commands.command(name="likepos", aliases=["lp"])
    @commands.guild_only()
    async def likepos(self, ctx, *, name: str):
        """Where a character sits on this server's liked list."""
        character = await self._resolve(ctx, name)
        if not character:
            return
        gid = ctx.guild.id
        votes = self.bot.db.like_count(gid, character["id"])
        if not votes:
            await ctx.send(f"Nobody here likes **{character['name']}** yet.")
            return
        position = self.bot.db.like_position(gid, character["id"])
        await ctx.send(
            f"**{character['name']}** is **#{position}** on this server"
            f" with {votes} like(s), and #{character['like_rank']:,} globally."
        )


async def setup(bot):
    await bot.add_cog(Likes(bot))
