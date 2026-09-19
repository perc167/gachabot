"""Rolling and claiming — the core loop."""
import random

import discord
from discord.ext import commands

import utils
from utils import fmt_duration, kakera_value


class ClaimView(discord.ui.View):
    """Attached to an unclaimed roll. First valid click wins the character."""

    def __init__(self, cog, guild_id: int, character, roller_id: int, wishers: list):
        timeout = cog.bot.db.get_setting(guild_id, "claim_window_seconds")
        super().__init__(timeout=timeout)
        self.cog = cog
        self.guild_id = guild_id
        self.character = character
        self.roller_id = roller_id
        self.wishers = set(wishers)
        self.protect_until = utils.now() + (
            cog.bot.db.get_setting(guild_id, "wish_protect_seconds") if wishers else 0
        )
        self.message = None
        self.claimed_by = None

    async def on_timeout(self):
        if self.message and not self.claimed_by:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="\U0001f48d")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = self.cog.bot.db
        cooldowns = self.cog.bot.cooldowns
        user = interaction.user

        if self.claimed_by:
            await interaction.response.send_message(
                "Already claimed.", ephemeral=True
            )
            return

        # Wishers get a head start before anyone else may click.
        remaining_protection = self.protect_until - utils.now()
        if remaining_protection > 0 and user.id not in self.wishers:
            await interaction.response.send_message(
                f"Someone wished for this one — you can claim in"
                f" {fmt_duration(remaining_protection)} if they don't.",
                ephemeral=True,
            )
            return

        ready, remaining = cooldowns.claim_ready(self.guild_id, user.id)
        if not ready:
            await interaction.response.send_message(
                f"Your next claim is in {fmt_duration(remaining)}.", ephemeral=True
            )
            return

        cap = db.get_setting(self.guild_id, "max_marriages")
        if cap and db.harem_size(self.guild_id, user.id) >= cap:
            await interaction.response.send_message(
                f"Your harem is full ({cap}). Divorce someone first.", ephemeral=True
            )
            return

        if not db.claim(self.guild_id, self.character["id"], user.id):
            await interaction.response.send_message(
                "Someone beat you to it.", ephemeral=True
            )
            return

        cooldowns.start_claim_cooldown(self.guild_id, user.id)
        self.claimed_by = user.id

        # Wishes are consumed once granted, for everyone who wanted them.
        for wisher in self.wishers:
            db.remove_wish(self.guild_id, wisher, self.character["id"])

        for child in self.children:
            child.disabled = True
        embed = interaction.message.embeds[0]
        embed.colour = discord.Colour.green()
        embed.add_field(
            name="Claimed", value=f"{user.mention} \U0001f48d", inline=False
        )
        await interaction.response.edit_message(embed=embed, view=self)
        await interaction.followup.send(
            f"{user.mention} married **{self.character['name']}**!"
        )
        self.stop()


class KakeraView(discord.ui.View):
    """Attached to a roll of an already-claimed character: free kakera."""

    def __init__(self, cog, guild_id: int, character):
        super().__init__(timeout=cog.bot.db.get_setting(guild_id, "claim_window_seconds"))
        self.cog = cog
        self.guild_id = guild_id
        self.character = character
        self.message = None
        self.taken = False

    async def on_timeout(self):
        if self.message and not self.taken:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(
        label="Kakera", style=discord.ButtonStyle.primary, emoji="\U0001f48e"
    )
    async def grab(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = self.cog.bot.db
        cooldowns = self.cog.bot.cooldowns
        user = interaction.user

        if self.taken:
            await interaction.response.send_message("Already taken.", ephemeral=True)
            return

        ready, remaining = cooldowns.kakera_ready(self.guild_id, user.id)
        if not ready:
            await interaction.response.send_message(
                f"Your next kakera grab is in {fmt_duration(remaining)}.",
                ephemeral=True,
            )
            return

        rate = db.get_setting(self.guild_id, "kakera_rate")
        # Grabbing someone else's character pays less than grabbing your own.
        owner_id = db.owner_of(self.guild_id, self.character["id"])
        base = kakera_value(self.character, rate)
        amount = base if owner_id == user.id else max(1, int(base * 0.6))
        amount = int(amount * random.uniform(0.8, 1.2))

        total = db.add_kakera(self.guild_id, user.id, amount)
        cooldowns.start_kakera_cooldown(self.guild_id, user.id)
        self.taken = True

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"{user.mention} collected **{amount}** kakera (total: {total})."
        )
        self.stop()


class Rolling(commands.Cog):
    """$w and friends."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="roll", aliases=["w", "wa", "wg", "ha", "hg", "m", "mx", "rolla"]
    )
    @commands.guild_only()
    async def roll(self, ctx):
        """Roll a random character."""
        db = self.bot.db
        gid = ctx.guild.id

        if db.character_count() == 0:
            await ctx.send(
                "The character pool is empty. An admin can run"
                f" `{ctx.prefix}import` or `{ctx.prefix}addchar` first."
            )
            return

        left, reset_in = self.bot.cooldowns.rolls_left(gid, ctx.author.id)
        if left <= 0:
            await ctx.send(
                f"{ctx.author.mention} you are out of rolls."
                f" More in {fmt_duration(reset_in)}."
            )
            return

        include_claimed = bool(db.get_setting(gid, "show_claimed"))
        character = db.random_character(gid, include_claimed)
        if character is None:
            await ctx.send(
                "Every character in the pool is already claimed here."
                " Add more, or turn on `show_claimed`."
            )
            return

        self.bot.cooldowns.spend_roll(gid, ctx.author.id)
        left -= 1

        owner_id = db.owner_of(gid, character["id"])
        wishers = db.wishers_of(gid, character["id"])
        embed = utils.character_embed(
            db, gid, character, random_art=True,
            footer=f"{left} rolls left • rolled by {ctx.author.display_name}",
        )

        content = None
        if wishers and owner_id is None:
            content = " ".join(f"<@{w}>" for w in wishers) + " — wished!"

        if owner_id is None:
            view = ClaimView(self, gid, character, ctx.author.id, wishers)
        else:
            view = KakeraView(self, gid, character)

        message = await ctx.send(content=content, embed=embed, view=view)
        view.message = message

    @commands.command(name="rolls", aliases=["ru", "cooldowns", "cd"])
    @commands.guild_only()
    async def rolls(self, ctx):
        """Show your rolls left and every cooldown."""
        gid = ctx.guild.id
        uid = ctx.author.id
        left, reset_in = self.bot.cooldowns.rolls_left(gid, uid)
        claim_ready, claim_in = self.bot.cooldowns.claim_ready(gid, uid)
        kak_ready, kak_in = self.bot.cooldowns.kakera_ready(gid, uid)
        player = self.bot.db.get_player(gid, uid)

        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s status", colour=0x4EA8DE
        )
        embed.add_field(
            name="Rolls",
            value=f"**{left}** left • resets in {fmt_duration(reset_in)}",
            inline=False,
        )
        embed.add_field(
            name="Claim",
            value="ready now" if claim_ready else f"in {fmt_duration(claim_in)}",
            inline=True,
        )
        embed.add_field(
            name="Kakera",
            value="ready now" if kak_ready else f"in {fmt_duration(kak_in)}",
            inline=True,
        )
        embed.add_field(name="Balance", value=f"{player['kakera']} kakera", inline=True)
        embed.add_field(
            name="Harem",
            value=f"{self.bot.db.harem_size(gid, uid)} characters",
            inline=True,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Rolling(bot))
