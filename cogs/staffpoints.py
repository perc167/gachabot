"""Staff points, for keeping track of who is ready for a promotion.

A trial mod can't ban, so when they report someone and a Mod bans them, the
Mod gives the trial mod their point here by hand.

Jails and mutes done with this bot's own $jail, $timeout, $imute and $rmute
give their point automatically; see cogs/modtools.py.

Giving and removing points needs Ban Members, the line between a Mod and a
trial mod. Anybody can look, so a trial mod can see where they stand.
"""
import discord
from discord.ext import commands

import config
from views import Confirm, Paginator

REASON_LIMIT = 200


def colour_for(db, guild_id: int) -> int:
    return db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR)


class StaffPoints(commands.Cog):
    # Staff commands work in every channel; see cogs/modtools.py.
    works_everywhere = True

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="point", aliases=["givepoint", "addpoint"])
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def point(self, ctx, member: discord.Member, *, reason: str = ""):
        """Give someone a point, e.g. for a report that ended in a ban."""
        if member.bot:
            await ctx.send("Bots can't earn points.")
            return
        if member == ctx.author:
            await ctx.send("You can't give yourself a point.")
            return
        reason = reason.strip()[:REASON_LIMIT]
        db = self.bot.db
        point_id = db.add_staff_point(ctx.guild.id, member.id, ctx.author.id,
                                      reason)
        total = len(db.staff_points_of(ctx.guild.id, member.id))
        await ctx.send(
            f"+1 point to **{member.display_name}**"
            + (f" for {reason}" if reason else "")
            + f". They now have **{total}**. (point #{point_id})",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="points", aliases=["mypoints", "pointlist"])
    @commands.guild_only()
    async def points(self, ctx, member: discord.Member = None):
        """How many points someone has, and what each one was for."""
        member = member or ctx.author
        db = self.bot.db
        rows = db.staff_points_of(ctx.guild.id, member.id)
        colour = colour_for(db, ctx.guild.id)
        if not rows:
            await ctx.send(embed=discord.Embed(
                title=f"{member.display_name}: 0 points",
                description="No points yet.",
                colour=colour,
            ))
            return

        lines = [
            f"`#{row['id']}` <t:{row['given_at']}:d> from <@{row['given_by']}>"
            + (f"\n　{row['reason']}" if row["reason"] else "")
            for row in rows
        ]
        per_page = 10
        pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
        embeds = []
        for number, page in enumerate(pages):
            embed = discord.Embed(
                title=f"{member.display_name}: {len(rows)} points",
                description="\n".join(page),
                colour=colour,
            )
            embed.set_footer(
                text=f"Page {number + 1}/{len(pages)}"
            )
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="toppoints", aliases=["pointsboard", "pointslb"])
    @commands.guild_only()
    async def toppoints(self, ctx):
        """Everyone with points, most first."""
        db = self.bot.db
        rows = db.top_staff_points(ctx.guild.id)
        lines = [
            f"`{i + 1:>2}.` <@{row['user_id']}> · **{row['points']}**"
            for i, row in enumerate(rows)
        ]
        await ctx.send(embed=discord.Embed(
            title=f"Staff points in {ctx.guild.name}",
            description="\n".join(lines) if lines else "Nobody has any points yet.",
            colour=colour_for(db, ctx.guild.id),
        ))

    @commands.command(name="removepoint", aliases=["unpoint", "delpoint"])
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    async def removepoint(self, ctx, point_id: int):
        """Take back one point by its number, shown in $points."""
        row = self.bot.db.remove_staff_point(ctx.guild.id, point_id)
        if not row:
            await ctx.send(f"There's no point #{point_id} here.")
            return
        await ctx.send(
            f"Removed point #{point_id} from <@{row['user_id']}>.",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="clearpoints", aliases=["resetpoints"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def clearpoints(self, ctx, member: discord.Member):
        """Wipe all of someone's points, e.g. after a promotion."""
        db = self.bot.db
        count = len(db.staff_points_of(ctx.guild.id, member.id))
        if not count:
            await ctx.send(f"{member.display_name} has no points.")
            return
        view = Confirm([ctx.author.id])
        view.message = await ctx.send(
            f"Clear all **{count}** of {member.display_name}'s points?",
            view=view,
        )
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Left alone.")
            return
        gone = db.clear_staff_points(ctx.guild.id, member.id)
        await ctx.send(f"Cleared **{gone}** points from {member.display_name}.")


async def setup(bot):
    await bot.add_cog(StaffPoints(bot))
