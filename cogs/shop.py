"""Somewhere for karuda to go.

Without a sink, karuda only ever piles up and the currency stops meaning
anything. Everything here converts karuda into more play: more rolls now, an
earlier claim, a wider wishlist.
"""
import discord
from discord.ext import commands

import config
import utils
from utils import fmt_duration


class Shop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _prices(self, gid: int) -> dict:
        get = self.bot.db.get_setting
        return {
            "rolls": get(gid, "price_rolls"),
            "bundle": get(gid, "rolls_per_purchase"),
            "claim": get(gid, "price_claim_reset"),
            "wish": get(gid, "price_wish_slot"),
        }

    def _afford(self, gid: int, user_id: int, cost: int):
        """Returns (ok, balance)."""
        balance = self.bot.db.get_player(gid, user_id)["karuda"]
        return balance >= cost, balance

    @commands.command(name="shop", aliases=["store"])
    @commands.guild_only()
    async def shop(self, ctx):
        """What karuda buys."""
        gid = ctx.guild.id
        price = self._prices(gid)
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])
        balance = self.bot.db.get_player(gid, ctx.author.id)["karuda"]

        embed = discord.Embed(
            title="Shop",
            description=f"You have {icon} **{balance:,}** {config.CURRENCY}.",
            colour=config.CARD_COLOUR,
        )
        embed.add_field(
            name=f"{ctx.prefix}buyrolls",
            value=f"{icon} {price['rolls']:,} — **+{price['bundle']} rolls**"
                  "\nexpires with your current roll window",
            inline=False,
        )
        embed.add_field(
            name=f"{ctx.prefix}resetclaim",
            value=f"{icon} {price['claim']:,} — **claim again now**",
            inline=False,
        )
        embed.add_field(
            name=f"{ctx.prefix}wishslot",
            value=f"{icon} {price['wish']:,} — **+1 wishlist slot**, permanent"
                  "\nprice rises by half for each slot you already bought",
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="buyrolls", aliases=["br"])
    @commands.guild_only()
    async def buyrolls(self, ctx, bundles: int = 1):
        """Buy extra rolls for the rest of this window."""
        if not 1 <= bundles <= 10:
            await ctx.send("Between 1 and 10 bundles at a time.")
            return
        db = self.bot.db
        gid = ctx.guild.id
        price = self._prices(gid)
        cost = price["rolls"] * bundles
        rolls = price["bundle"] * bundles

        ok, balance = self._afford(gid, ctx.author.id, cost)
        if not ok:
            await ctx.send(
                f"That costs {cost:,} {config.CURRENCY};"
                f" you have {balance:,}."
            )
            return

        player = db.get_player(gid, ctx.author.id)
        db.add_karuda(gid, ctx.author.id, -cost)
        db.update_player(
            gid, ctx.author.id, rolls_bought=player["rolls_bought"] + rolls
        )
        left, reset_in = self.bot.cooldowns.rolls_left(gid, ctx.author.id)
        await ctx.send(
            f"{ctx.author.mention} bought **{rolls}** rolls for {cost:,}"
            f" {config.CURRENCY}. You now have **{left}** left,"
            f" until the window resets in {fmt_duration(reset_in)}."
        )

    @commands.command(name="resetclaim", aliases=["rc"])
    @commands.guild_only()
    async def resetclaim(self, ctx):
        """Clear your claim cooldown."""
        db = self.bot.db
        gid = ctx.guild.id
        ready, remaining = self.bot.cooldowns.claim_ready(gid, ctx.author.id)
        if ready:
            await ctx.send("Your claim is already available.")
            return

        cost = self._prices(gid)["claim"]
        ok, balance = self._afford(gid, ctx.author.id, cost)
        if not ok:
            await ctx.send(
                f"Clearing it costs {cost:,} {config.CURRENCY};"
                f" you have {balance:,}. It clears on its own in"
                f" {fmt_duration(remaining)}."
            )
            return

        db.add_karuda(gid, ctx.author.id, -cost)
        db.update_player(gid, ctx.author.id, claim_ready_at=0)
        await ctx.send(
            f"{ctx.author.mention} paid {cost:,} {config.CURRENCY}."
            " You can claim again now."
        )

    @commands.command(name="wishslot", aliases=["ws"])
    @commands.guild_only()
    async def wishslot(self, ctx):
        """Buy one more wishlist slot, permanently."""
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, ctx.author.id)
        owned = player["extra_wish_slots"]

        # Each slot costs half again as much as the last, so the wishlist
        # cannot simply be bought out to cover the whole pool.
        cost = int(self._prices(gid)["wish"] * (1.5**owned))
        ok, balance = self._afford(gid, ctx.author.id, cost)
        if not ok:
            await ctx.send(
                f"Your next slot costs {cost:,} {config.CURRENCY};"
                f" you have {balance:,}."
            )
            return

        db.add_karuda(gid, ctx.author.id, -cost)
        db.update_player(gid, ctx.author.id, extra_wish_slots=owned + 1)
        total = db.get_setting(gid, "wish_limit") + owned + 1
        await ctx.send(
            f"{ctx.author.mention} bought a wishlist slot for {cost:,}"
            f" {config.CURRENCY}. You can now wish for **{total}** characters."
        )


async def setup(bot):
    await bot.add_cog(Shop(bot))
