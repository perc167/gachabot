"""Wishlists. A wish pings you when the character rolls and buys you a head
start on the claim button (see wish_protect_seconds)."""
import discord
from discord.ext import commands

import utils
from views import Paginator


class Wishlist(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="wish", aliases=["wl"])
    @commands.guild_only()
    async def wish(self, ctx, *, name: str):
        """Add a character to your wishlist."""
        db = self.bot.db
        gid = ctx.guild.id
        character = db.find_character_by_name(name)
        if not character:
            await ctx.send(f"No character matching `{name}`.")
            return

        limit = db.get_setting(gid, "wish_limit")
        if db.wish_count(gid, ctx.author.id) >= limit:
            await ctx.send(
                f"Your wishlist is full ({limit})."
                f" Drop one with `{ctx.prefix}unwish <name>`."
            )
            return

        owner_id = db.owner_of(gid, character["id"])
        if owner_id == ctx.author.id:
            await ctx.send(f"You already own **{character['name']}**.")
            return

        if not db.add_wish(gid, ctx.author.id, character["id"]):
            await ctx.send(f"**{character['name']}** is already on your wishlist.")
            return

        note = ""
        if owner_id:
            note = f" (currently owned by <@{owner_id}>)"
        await ctx.send(f"Wished for **{character['name']}**{note}.")

    @commands.command(name="unwish", aliases=["uw"])
    @commands.guild_only()
    async def unwish(self, ctx, *, name: str):
        """Remove a character from your wishlist."""
        db = self.bot.db
        character = db.find_character_by_name(name)
        if not character:
            await ctx.send(f"No character matching `{name}`.")
            return
        if db.remove_wish(ctx.guild.id, ctx.author.id, character["id"]):
            await ctx.send(f"Removed **{character['name']}** from your wishlist.")
        else:
            await ctx.send(f"**{character['name']}** is not on your wishlist.")

    @commands.command(name="wishlist", aliases=["wishes", "wls"])
    @commands.guild_only()
    async def wishlist(self, ctx, member: discord.Member = None):
        """Show a wishlist."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.wishes_of(gid, member.id)
        if not rows:
            await ctx.send(f"{member.display_name} has no wishes.")
            return

        limit = db.get_setting(gid, "wish_limit")
        lines = []
        for i, row in enumerate(rows, 1):
            owner_id = db.owner_of(gid, row["id"])
            state = f"owned by <@{owner_id}>" if owner_id else "free"
            lines.append(
                f"`{i:>2}.` **{row['name']}** • {row['series']}"
                f" • {row['likes']} ♥ • {state}"
            )

        pages = utils.paginate(lines, 10)
        embeds = []
        for page_no, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{member.display_name}'s wishlist",
                description="\n".join(page),
                colour=0x4EA8DE,
            )
            embed.set_footer(
                text=f"Page {page_no}/{len(pages)} • {len(rows)}/{limit} wishes"
            )
            embeds.append(embed)

        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="wishedby", aliases=["wb"])
    @commands.guild_only()
    async def wishedby(self, ctx, *, name: str):
        """See who is waiting on a character."""
        db = self.bot.db
        character = db.find_character_by_name(name)
        if not character:
            await ctx.send(f"No character matching `{name}`.")
            return
        wishers = db.wishers_of(ctx.guild.id, character["id"])
        if not wishers:
            await ctx.send(f"Nobody has wished for **{character['name']}**.")
            return
        await ctx.send(
            f"**{character['name']}** is wished by: "
            + ", ".join(f"<@{w}>" for w in wishers)
        )


async def setup(bot):
    await bot.add_cog(Wishlist(bot))
