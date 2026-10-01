"""Karuda: the currency. Balance, daily, transfers, leaderboard."""
import random

import discord
from discord.ext import commands

import config
import perks
import premium
import utils
from cogs import tea
from utils import fmt_duration

DAILY_COOLDOWN = 20 * 60 * 60  # 20 hours, so it drifts earlier each day
DAILY_OFFERS = 2  # two shards appear, one is yours
DAILY_MIN, DAILY_MAX = 100, 240


class ShardDrops(discord.ui.View):
    """Two shards. You keep one — the other is up for grabs.

    Both are rolled and shown with their icon and payout, so the choice is
    made with full information. You get first refusal for a short window;
    after that, or the moment you take yours, anyone else in the channel can
    snipe what is left. Snipers take a reduced cut, so a busy server does not
    quietly double everyone's daily income.
    """

    def __init__(self, bot, guild_id: int, author, drops, protect: int,
                 snipe: bool, snipe_percent: int, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self.author = author
        self.drops = drops
        self.protect = protect
        self.snipe = snipe
        self.snipe_percent = snipe_percent
        self.opened_at = utils.now()
        self.claimed = [None] * len(drops)  # user id per shard
        self.takers = set()  # nobody takes two from one drop
        self.message = None

        for index, (key, name, _mult, _colour, amount) in enumerate(drops):
            button = discord.ui.Button(
                label=f"{name} · {amount:,}",
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(utils.shard_icon(key)),
            )
            button.callback = self._collector(index)
            self.add_item(button)

    # ---- who may press what, and when -------------------------------

    @property
    def owner_took_one(self) -> bool:
        return self.author.id in self.takers

    def protection_left(self) -> int:
        if self.owner_took_one:
            return 0  # they have had their pick; the rest is fair game
        return max(0, self.protect - (utils.now() - self.opened_at))

    def snipe_amount(self, amount: int) -> int:
        return max(1, amount * self.snipe_percent // 100)

    def render(self) -> discord.Embed:
        lines = []
        for index, (key, name, mult, _colour, amount) in enumerate(self.drops):
            icon = utils.shard_icon(key)
            holder = self.claimed[index]
            if holder is None:
                lines.append(f"{icon} **{name}** ×{mult:g} — **{amount:,}**")
            elif holder == self.author.id:
                lines.append(f"{icon} **{name}** ×{mult:g} — kept, **{amount:,}**")
            else:
                lines.append(
                    f"{icon} ~~{name} ×{mult:g}~~ — sniped by <@{holder}>"
                )

        left = [i for i, holder in enumerate(self.claimed) if holder is None]
        if not left:
            colour = config.CARD_COLOUR
            footer = "All gone · next in 20h"
        else:
            colour = max((self.drops[i] for i in left), key=lambda d: d[2])[3]
            if not self.snipe:
                footer = "Pick one — the other is lost"
            elif self.protection_left():
                footer = (
                    f"Yours alone for {self.protection_left()}s,"
                    f" then anyone may take what is left"
                )
            else:
                footer = f"Open to anyone · snipers take {self.snipe_percent}%"

        embed = discord.Embed(
            title=f"{self.author.display_name}'s daily karuda",
            description="\n".join(lines),
            colour=colour,
        )
        embed.set_footer(text=footer)
        return embed

    def _collector(self, index: int):
        async def callback(interaction: discord.Interaction):
            user = interaction.user
            if self.claimed[index] is not None:
                await interaction.response.send_message(
                    "That one is gone.", ephemeral=True
                )
                return
            if user.id in self.takers:
                await interaction.response.send_message(
                    "One each from a drop.", ephemeral=True
                )
                return

            is_owner = user.id == self.author.id
            if not is_owner:
                if not self.snipe:
                    await interaction.response.send_message(
                        "Sniping is off on this server.", ephemeral=True
                    )
                    return
                waiting = self.protection_left()
                if waiting:
                    await interaction.response.send_message(
                        f"{self.author.display_name} has first refusal for"
                        f" another {waiting}s.",
                        ephemeral=True,
                    )
                    return

            key, name, _mult, _colour, amount = self.drops[index]
            payout = amount if is_owner else self.snipe_amount(amount)
            self.claimed[index] = user.id
            self.takers.add(user.id)
            total = self.bot.db.add_karuda(self.guild_id, user.id, payout)
            self.bot.db.record_shard(self.guild_id, user.id, key)

            # Sometimes the drop has a tea in it as well. Only for whoever
            # the drop belongs to - sniping somebody's shard should not also
            # hand you their tea.
            brewed = None
            if is_owner and random.random() < tea.DAILY_TEA_CHANCE:
                brewed = random.choice(list(tea.TEAS))
                self.bot.db.add_item(self.guild_id, user.id, brewed, 1)

            self.children[index].disabled = True
            self.children[index].style = discord.ButtonStyle.success
            # The owner taking one opens the rest immediately.
            if all(holder is not None for holder in self.claimed):
                for child in self.children:
                    child.disabled = True
                self.stop()

            embed = self.render()
            if brewed:
                name, icon, what, _price = tea.TEAS[brewed]
                embed.add_field(
                    name="And a tea",
                    value=f"{icon} **{name}** — {what}\n"
                          f"`{config.PREFIX}{brewed}` drinks it.",
                    inline=False,
                )
            embed.add_field(
                name="Kept" if is_owner else "Sniped",
                value=f"{user.mention} +{payout:,} → {total:,}",
                inline=False,
            )
            await interaction.response.edit_message(embed=embed, view=self)

        return callback

    async def on_timeout(self):
        if self.message and any(holder is None for holder in self.claimed):
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

    @commands.command(name="dk", aliases=["dailykaruda", "dailyk"])
    @commands.guild_only()
    async def dk(self, ctx):
        """Two shards appear: you keep one, the other can be sniped."""
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
        offers = DAILY_OFFERS + perks.effective(db, gid, ctx.author.id)["daily_offers"]
        for _ in range(offers):
            key, name, _fallback, multiplier, _weight, colour = config.roll_shard(
                random
            )
            earned = perks.effective(db, gid, ctx.author.id)
            bonus = earned["daily_percent"] + earned["karuda_percent"]
            rush = db.event_strength(gid, "karuda") or 100  # a Premium event
            amount = round(
                random.randint(DAILY_MIN, DAILY_MAX)
                * multiplier
                * (100 + bonus)
                / 100
                * rush / 100
            )
            drops.append((key, name, multiplier, colour, amount))
        db.update_player(
            gid, ctx.author.id, daily_ready_at=utils.now() + (
                premium.DAILY_COOLDOWN if db.has_feature(gid, "fast_daily")
                else DAILY_COOLDOWN)
        )

        view = ShardDrops(
            self.bot,
            gid,
            ctx.author,
            drops,
            protect=db.get_setting(gid, "dk_protect_seconds"),
            snipe=bool(db.get_setting(gid, "dk_snipe")),
            snipe_percent=db.get_setting(gid, "dk_snipe_percent"),
        )
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
            text=f"One pull per {ctx.prefix}dk, every 20 hours • {art}"
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
