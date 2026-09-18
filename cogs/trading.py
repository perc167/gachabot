"""Gifts and one-for-one trades, both behind a confirmation button."""
import discord
from discord.ext import commands

from views import Confirm


class Trading(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _owned_by(self, gid: int, name: str, user_id: int):
        """Resolve a name to a character the user actually owns.

        Returns (character, error_message).
        """
        character = self.bot.db.find_character_by_name(name)
        if not character:
            return None, f"No character matching `{name}`."
        if self.bot.db.owner_of(gid, character["id"]) != user_id:
            return None, f"**{character['name']}** is not owned by <@{user_id}>."
        return character, None

    @commands.command(name="gift", aliases=["give"])
    @commands.guild_only()
    async def gift(self, ctx, member: discord.Member, *, name: str):
        """Hand one of your characters to someone else."""
        db = self.bot.db
        gid = ctx.guild.id
        if member.bot or member.id == ctx.author.id:
            await ctx.send("Pick a different person.")
            return

        character, error = self._owned_by(gid, name, ctx.author.id)
        if error:
            await ctx.send(error)
            return

        cap = db.get_setting(gid, "max_marriages")
        if cap and db.harem_size(gid, member.id) >= cap:
            await ctx.send(f"{member.display_name}'s harem is full ({cap}).")
            return

        view = Confirm({member.id})
        view.message = await ctx.send(
            f"{member.mention} — {ctx.author.display_name} wants to give you"
            f" **{character['name']}** ({character['series']}). Accept?",
            view=view,
        )
        await view.wait()

        if view.declined_by:
            await ctx.send("Gift declined.")
            return
        if not view.accepted:
            return  # timed out; the view already said so

        # Re-check: they could have divorced or traded it away while we waited.
        if db.owner_of(gid, character["id"]) != ctx.author.id:
            await ctx.send(f"**{character['name']}** changed hands. Gift cancelled.")
            return

        db.transfer(gid, character["id"], member.id)
        db.remove_wish(gid, member.id, character["id"])
        await ctx.send(
            f"**{character['name']}** now belongs to {member.mention}."
        )

    @commands.command(name="trade", aliases=["tr"])
    @commands.guild_only()
    async def trade(self, ctx, member: discord.Member, *, args: str):
        """`$trade @user <your character> | <their character>`"""
        if member.bot or member.id == ctx.author.id:
            await ctx.send("Pick a different person.")
            return
        if "|" not in args:
            await ctx.send(
                f"Usage: `{ctx.prefix}trade @user <your character>"
                " | <their character>`"
            )
            return

        db = self.bot.db
        gid = ctx.guild.id
        mine_name, _, theirs_name = args.partition("|")

        mine, error = self._owned_by(gid, mine_name.strip(), ctx.author.id)
        if error:
            await ctx.send(error)
            return
        theirs, error = self._owned_by(gid, theirs_name.strip(), member.id)
        if error:
            await ctx.send(error)
            return

        embed = discord.Embed(title="Trade offer", colour=0xB388EB)
        embed.add_field(
            name=f"{ctx.author.display_name} gives",
            value=f"**{mine['name']}**\n{mine['series']}\n{mine['likes']} ♥",
            inline=True,
        )
        embed.add_field(
            name=f"{member.display_name} gives",
            value=f"**{theirs['name']}**\n{theirs['series']}\n{theirs['likes']} ♥",
            inline=True,
        )
        embed.set_footer(text="Both of you must accept.")

        view = Confirm({ctx.author.id, member.id})
        view.message = await ctx.send(
            f"{ctx.author.mention} {member.mention}", embed=embed, view=view
        )
        await view.wait()

        if view.declined_by:
            await ctx.send(f"Trade declined by <@{view.declined_by}>.")
            return
        if view.accepted != {ctx.author.id, member.id}:
            return  # timed out

        if (
            db.owner_of(gid, mine["id"]) != ctx.author.id
            or db.owner_of(gid, theirs["id"]) != member.id
        ):
            await ctx.send("One of those characters changed hands. Trade cancelled.")
            return

        db.transfer(gid, mine["id"], member.id)
        db.transfer(gid, theirs["id"], ctx.author.id)
        db.remove_wish(gid, member.id, mine["id"])
        db.remove_wish(gid, ctx.author.id, theirs["id"])
        await ctx.send(
            f"Traded: {member.mention} gets **{mine['name']}**,"
            f" {ctx.author.mention} gets **{theirs['name']}**."
        )


async def setup(bot):
    await bot.add_cog(Trading(bot))
