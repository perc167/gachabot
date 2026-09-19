"""Karuda: the currency. Balance, daily, transfers, leaderboard."""
import random

import discord
from discord.ext import commands

import config
import perks
import utils
from utils import fmt_duration

DAILY_COOLDOWN = 20 * 60 * 60  # 20 hours, so it drifts earlier each day
DAILY_OFFERS = 2  # two shards appear, one is yours
DAILY_MIN, DAILY_MAX = 100, 240


class ShardDrops(discord.ui.View):
    """Two shards, one choice.

    Both are rolled and both are shown with their icon and payout, so the
    decision is made with full information - the interesting case is an
    Aurum next to an Azure, not a mystery box. Taking one forfeits the other.
    """

    def __init__(self, bot, guild_id: int, author, drops, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self.author = author
        self.drops = drops
        self.taken = None  # index of the one they chose
        self.message = None

        for index, (key, name, _mult, _colour, amount) in enumerate(drops):
            button = discord.ui.Button(
                label=f"{name} · {amount:,}",
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(utils.shard_icon(key)),
            )
            button.callback = self._collector(index)
            self.add_item(button)

    def render(self) -> discord.Embed:
        lines = []
        for index, (key, name, mult, _colour, amount) in enumerate(self.drops):
            icon = utils.shard_icon(key)
            if self.taken is None:
                lines.append(f"{icon} **{name}** ×{mult:g} — **{amount:,}**")
            elif index == self.taken:
                lines.append(f"{icon} **{name}** ×{mult:g} — taken, **{amount:,}**")
            else:
                lines.append(f"~~{icon} {name} ×{mult:g} — {amount:,}~~")

        if self.taken is None:
            colour = max(self.drops, key=lambda d: d[2])[3]
            footer = "Pick one — the other is lost"
        else:
            colour = self.drops[self.taken][3]
            footer = "Chosen · next in 20h"

        embed = discord.Embed(
            title=f"{self.author.display_name}'s daily karuda",
            description="\n".join(lines),
            colour=colour,
        )
        embed.set_footer(text=footer)
        return embed

    def _collector(self, index: int):
        async def callback(interaction: discord.Interaction):
            if self.taken is not None:
                await interaction.response.send_message(
                    "You already chose.", ephemeral=True
                )
                return
            key, _name, _mult, _colour, amount = self.drops[index]
            self.taken = index
            total = self.bot.db.add_karuda(self.guild_id, self.author.id, amount)
            self.bot.db.record_shard(self.guild_id, self.author.id, key)

            # Both close: one because it is spent, the other because it is gone.
            for position, child in enumerate(self.children):
                child.disabled = True
                child.style = (
                    discord.ButtonStyle.success
                    if position == index
                    else discord.ButtonStyle.secondary
                )
            embed = self.render()
            embed.add_field(name="Balance", value=f"{total:,}", inline=True)
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()

        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Not your drop. Run `$dk` for your own.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self):
        if self.message and self.taken is None:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Karuda(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="balance", aliases=["k", "karuda", "kakera", "bal", "wallet"])
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
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])
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
            for key, name, _fallback, _, _, _ in config.SHARD_TYPES:
                count = pulled.get(key, 0)
                if count:
                    lines.append(f"{utils.shard_icon(key)} {name} ×{count}")
                else:
                    lines.append(f"— *{name}*")
            embed.add_field(name="Shards pulled", value="\n".join(lines), inline=False)
            found = sum(1 for k, *_ in config.SHARD_TYPES if pulled.get(k))
            embed.set_footer(text=f"{found}/{len(config.SHARD_TYPES)} shard types found")
        await ctx.send(embed=embed)

    @commands.command(name="dk", aliases=["daily", "dailykaruda"])
    @commands.guild_only()
    async def dk(self, ctx):
        """Two shards appear, you keep one. Once every 20 hours."""
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, ctx.author.id)
        remaining = player["daily_ready_at"] - utils.now()
        if remaining > 0:
            await ctx.send(
                f"{ctx.author.mention} your next {ctx.prefix}dk is in"
                f" {fmt_duration(remaining)}."
            )
            return

        # The cooldown starts now rather than on choosing, so walking away
        # from the decision costs you the day.
        drops = []
        for _ in range(DAILY_OFFERS):
            key, name, _fallback, multiplier, _weight, colour = config.roll_shard(
                random
            )
            bonus = perks.effective(db, gid, ctx.author.id)["daily_percent"]
            amount = round(
                random.randint(DAILY_MIN, DAILY_MAX)
                * multiplier
                * (100 + bonus)
                / 100
            )
            drops.append((key, name, multiplier, colour, amount))
        db.update_player(
            gid, ctx.author.id, daily_ready_at=utils.now() + DAILY_COOLDOWN
        )

        view = ShardDrops(self.bot, gid, ctx.author, drops)
        view.message = await ctx.send(
            content=ctx.author.mention, embed=view.render(), view=view
        )

    @commands.command(name="shards", aliases=["types", "kakeravalues", "shardlist"])
    async def shards(self, ctx):
        """What each shard type is worth, and how often it turns up."""
        total_weight = sum(s[4] for s in config.SHARD_TYPES)
        lines = []
        custom = 0
        for key, name, fallback, multiplier, weight, _ in config.SHARD_TYPES:
            icon = utils.shard_icon(key)
            custom += icon != fallback
            chance = 100 * weight / total_weight
            shown = f"{chance:.0f}%" if chance >= 1 else f"{chance:.1f}%"
            lines.append(f"{icon} **{name}** — ×{multiplier:g} payout, {shown}")
        embed = discord.Embed(
            title=f"{config.CURRENCY_TITLE} shards",
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        art = (f"{custom}/{len(config.SHARD_TYPES)} crystal emoji found"
               if custom else "using fallback icons - upload assets/shards/")
        embed.set_footer(
            text=f"One pull per {ctx.prefix}daily, every 20 hours • {art}"
        )
        await ctx.send(embed=embed)

    @commands.command(name="pay", aliases=["sendkaruda", "givek", "givekaruda", "givekakera"])
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

    @commands.command(name="richest", aliases=["klb", "karudatop", "topk", "topservk"])
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
