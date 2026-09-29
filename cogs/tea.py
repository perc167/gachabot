"""Tea: Mudae's small boosts, and the commands that drink them.

A tea is something you hold and spend, not a cooldown that ticks. Each kind
does one thing, all of them useful and none of them enough to break the
economy - the point is a small nudge when you want one rather than a way to
farm.

They turn up in the daily drop, and the shop sells them. Nothing here mints
karuda out of nothing: the red tea pays out less than the shop charges for
the tea itself, so buying tea to sell tea loses money on purpose.
"""
import random

import discord
from discord.ext import commands

import config
import perks
import utils

# key: (display name, icon, what it does, price in karuda)
TEAS = {
    "greentea": ("Green tea", "\U0001f375", "three extra rolls this window", 350),
    "blacktea": ("Black tea", "☕", "clears your claim cooldown", 900),
    "redtea": ("Red tea", "\U0001f9c9", "a small pile of karuda", 300),
    "yellowtea": ("Yellow tea", "\U0001f9cb", "one character key", 1200),
    "mixtea": ("Mixed tea", "\U0001f9ea", "one of the others, at random", 500),
}

# What a red tea pays. Deliberately under its own shop price.
RED_TEA_KARUDA = (120, 260)
GREEN_TEA_ROLLS = 3

# How often a daily drop also hands you a tea.
DAILY_TEA_CHANCE = 0.18


def brew(key: str) -> str:
    name, icon, _what, _price = TEAS[key]
    return f"{icon} **{name}**"


class Tea(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="tea", aliases=["teas", "ta"])
    @commands.guild_only()
    async def tea(self, ctx, member: discord.Member = None):
        """What tea you are holding, and what each one does."""
        member = member or ctx.author
        db = self.bot.db
        held = db.items_of(ctx.guild.id, member.id)

        lines = []
        for key, (name, icon, what, price) in TEAS.items():
            count = held.get(key, 0)
            mark = f"**×{count}**" if count else "—"
            lines.append(f"{icon} `{ctx.prefix}{key}` {mark}\n　{what}")

        total = sum(held.get(key, 0) for key in TEAS)
        embed = discord.Embed(
            title=f"\U0001f375  {member.display_name}'s tea",
            description="\n".join(lines),
            colour=db.get_pref(ctx.guild.id, "cardcolour", config.CARD_COLOUR),
        )
        embed.set_footer(
            text=(f"{total} in the cupboard · the daily drop sometimes has one,"
                  f" and {ctx.prefix}shop sells them")
            if total else
            f"The cupboard is bare · {ctx.prefix}dk and {ctx.prefix}shop"
        )
        await ctx.send(embed=embed)

    async def _drink(self, ctx, key: str):
        """Spend one tea, if they have one, and apply what it does."""
        db = self.bot.db
        gid = ctx.guild.id
        user = ctx.author.id
        if not db.spend_item(gid, user, key):
            await ctx.send(
                f"You have no {brew(key)}. `{ctx.prefix}tea` shows the cupboard."
            )
            return

        chosen = key
        if key == "mixtea":
            chosen = random.choice([k for k in TEAS if k != "mixtea"])

        if chosen == "greentea":
            left = self.bot.cooldowns.grant_rolls(gid, user, GREEN_TEA_ROLLS)
            outcome = (f"**+{GREEN_TEA_ROLLS} rolls** — you have **{left}**"
                       f" this window.")
        elif chosen == "blacktea":
            db.update_player(gid, user, claim_ready_at=0)
            outcome = "Your claim cooldown is **gone**."
        elif chosen == "redtea":
            amount = random.randint(*RED_TEA_KARUDA)
            now = db.add_karuda(gid, user, amount)
            outcome = (f"**+{amount:,}** {config.CURRENCY} —"
                       f" you have **{now:,}**.")
        else:  # yellowtea
            got, held = perks.earn_keys(db, gid, user, 1)
            outcome = f"**+{got} key{'s' if got > 1 else ''}** — you hold **{held}**."

        note = ""
        if key == "mixtea":
            note = f"It turned out to be {brew(chosen)}.\n"
        left = db.item_count(gid, user, key)
        await ctx.send(
            f"{brew(key)} drunk.\n{note}{outcome}"
            + (f"\n_{left} left._" if left else "")
        )

    @commands.command(name="greentea")
    @commands.guild_only()
    async def greentea(self, ctx):
        """Drink a green tea: three extra rolls this window."""
        await self._drink(ctx, "greentea")

    @commands.command(name="blacktea")
    @commands.guild_only()
    async def blacktea(self, ctx):
        """Drink a black tea: your claim cooldown goes."""
        await self._drink(ctx, "blacktea")

    @commands.command(name="redtea")
    @commands.guild_only()
    async def redtea(self, ctx):
        """Drink a red tea: a small pile of karuda."""
        await self._drink(ctx, "redtea")

    @commands.command(name="yellowtea")
    @commands.guild_only()
    async def yellowtea(self, ctx):
        """Drink a yellow tea: one character key."""
        await self._drink(ctx, "yellowtea")

    @commands.command(name="mixtea", aliases=["mixedtea"])
    @commands.guild_only()
    async def mixtea(self, ctx):
        """Drink a mixed tea: whatever it turns out to be."""
        await self._drink(ctx, "mixtea")

    @commands.command(name="buytea")
    @commands.guild_only()
    async def buytea(self, ctx, kind: str = None):
        """Buy one tea. `$buytea green`, `$buytea black`, and so on."""
        db = self.bot.db
        gid = ctx.guild.id
        key = (kind or "").lower().strip()
        if not key.endswith("tea"):
            key += "tea"
        if key not in TEAS:
            await ctx.send(
                "Which tea? " + ", ".join(f"`{k[:-3]}`" for k in TEAS)
            )
            return

        name, icon, what, price = TEAS[key]
        balance = db.get_player(gid, ctx.author.id)["karuda"]
        if balance < price:
            await ctx.send(
                f"{icon} **{name}** costs **{price:,}** {config.CURRENCY}."
                f" You have **{balance:,}**."
            )
            return
        db.add_karuda(gid, ctx.author.id, -price)
        held = db.add_item(gid, ctx.author.id, key, 1)
        await ctx.send(
            f"Bought {brew(key)} for **{price:,}** {config.CURRENCY}."
            f" You hold **{held}**. `{ctx.prefix}{key}` drinks it."
        )

    @commands.command(name="givetea")
    @commands.guild_only()
    async def givetea(self, ctx, member: discord.Member, kind: str = None):
        """Hand one of your teas to somebody else."""
        key = (kind or "").lower().strip()
        if not key.endswith("tea"):
            key += "tea"
        if key not in TEAS:
            await ctx.send("Which tea? " + ", ".join(f"`{k[:-3]}`" for k in TEAS))
            return
        if member.id == ctx.author.id:
            await ctx.send("You already have it.")
            return
        db = self.bot.db
        if not db.spend_item(ctx.guild.id, ctx.author.id, key):
            await ctx.send(f"You have no {brew(key)} to give.")
            return
        db.add_item(ctx.guild.id, member.id, key, 1)
        await ctx.send(
            f"{ctx.author.display_name} gave {member.mention} {brew(key)}."
        )


async def setup(bot):
    await bot.add_cog(Tea(bot))
