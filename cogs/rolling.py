"""Rolling and claiming — the core loop."""
import random

import discord
from discord.ext import commands

import config
import perks
import wishes
import utils
from cogs.personalise import word
from utils import fmt_duration, karuda_value


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
            f"{user.mention} "
            f"{word(db, self.guild_id, user.id, 'claim_word')}"
            f" **{self.character['name']}**!"
        )
        self.stop()


class KarudaView(discord.ui.View):
    """Attached to a roll of an already-claimed character: free karuda."""

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
        label="Karuda", style=discord.ButtonStyle.primary, emoji="\U0001f48e"
    )
    async def grab(self, interaction: discord.Interaction, button: discord.ui.Button):
        db = self.cog.bot.db
        cooldowns = self.cog.bot.cooldowns
        user = interaction.user

        if self.taken:
            await interaction.response.send_message("Already taken.", ephemeral=True)
            return

        ready, remaining = cooldowns.karuda_ready(self.guild_id, user.id)
        if not ready:
            await interaction.response.send_message(
                f"Your next karuda grab is in {fmt_duration(remaining)}.",
                ephemeral=True,
            )
            return

        rate = db.get_setting(self.guild_id, "karuda_rate")
        percent = db.get_setting(self.guild_id, "karuda_grab_percent")
        earned = perks.effective(db, self.guild_id, user.id)
        percent += earned["grab_percent"]
        # A grab is a cut of the character's worth, not the whole thing -
        # paying full value made grinding the only sensible way to play.
        owner_id = db.owner_of(self.guild_id, self.character["id"])
        worth = utils.value_with_keys(db, self.guild_id, self.character, rate)
        base = max(1, worth * percent // 100)
        amount = base if owner_id == user.id else max(1, int(base * 0.6))
        amount = max(1, int(amount * random.uniform(0.8, 1.2)
                            * (100 + earned["karuda_percent"]) / 100))

        total = db.add_karuda(self.guild_id, user.id, amount)
        cooldowns.start_karuda_cooldown(self.guild_id, user.id)
        self.taken = True

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(
            f"{user.mention} collected **{amount}** karuda (total: {total})."
        )
        self.stop()


class Rolling(commands.Cog):
    """$w and friends."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="roll", aliases=["m", "mx", "a", "mudae", "rolla"])
    @commands.guild_only()
    async def roll(self, ctx):
        """Roll anybody at all."""
        await self._do_roll(ctx)

    @commands.command(name="waifu", aliases=["w"])
    @commands.guild_only()
    async def waifu(self, ctx):
        """Roll a female character."""
        await self._do_roll(ctx, gender="Female")

    @commands.command(name="husbando", aliases=["h"])
    @commands.guild_only()
    async def husbando(self, ctx):
        """Roll a male character."""
        await self._do_roll(ctx, gender="Male")

    @commands.command(name="wa")
    @commands.guild_only()
    async def wa(self, ctx):
        """Roll a female character from anime or manga."""
        await self._do_roll(ctx, gender="Female", kind="anime")

    @commands.command(name="wg")
    @commands.guild_only()
    async def wg(self, ctx):
        """Roll a female character from a game or a cartoon."""
        await self._do_roll(ctx, gender="Female", kind="game")

    @commands.command(name="ha")
    @commands.guild_only()
    async def ha(self, ctx):
        """Roll a male character from anime or manga."""
        await self._do_roll(ctx, gender="Male", kind="anime")

    @commands.command(name="hg")
    @commands.guild_only()
    async def hg(self, ctx):
        """Roll a male character from a game or a cartoon."""
        await self._do_roll(ctx, gender="Male", kind="game")

    @commands.command(name="ma")
    @commands.guild_only()
    async def ma(self, ctx):
        """Roll anybody from anime or manga."""
        await self._do_roll(ctx, kind="anime")

    @commands.command(name="mg")
    @commands.guild_only()
    async def mg(self, ctx):
        """Roll anybody from a game or a cartoon."""
        await self._do_roll(ctx, kind="game")

    async def _do_roll(self, ctx, gender: str = None, kind: str = None):
        """Every roll goes through here.

        `gender` and `kind` are what separate $w from $h from $mg. AniList
        records no gender for roughly half the roster, so a narrowed roll
        draws from a smaller pool than $m does - which is why an empty result
        says so rather than looking broken.
        """
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
        # Amethyst: some of your rolls come off your own wishlist. Checked
        # before the pool, and it falls through to an ordinary roll when the
        # wishlist is empty or everyone on it is taken.
        character = None
        wish_chance = perks.effective(db, gid, ctx.author.id)["wish_chance"]
        if wish_chance and random.random() * 100 < wish_chance:
            character = db.random_wish(gid, ctx.author.id, include_claimed)
        if character is None:
            # Wishes and starwishes tilt your own rolls towards them.
            character = wishes.boosted_roll(db, gid, ctx.author.id,
                                            gender=gender, kind=kind)
        if character is None:
            character = db.random_character(
                gid, include_claimed, db.get_setting(gid, "roll_bias"),
                gender=gender, kind=kind, secret=True,
            )
        if character is None:
            narrowed = " matching that" if (gender or kind) else ""
            await ctx.send(
                f"Nobody{narrowed} is left to roll here."
                + ("\nTry `" + ctx.prefix + "m` — about half the roster has no"
                   " gender recorded, so it only rolls under the plain one."
                   if gender else
                   " Add more, or turn on `show_claimed`.")
            )
            return

        self.bot.cooldowns.spend_roll(gid, ctx.author.id)
        left -= 1

        owner_id = db.owner_of(gid, character["id"])
        wishers = db.wishers_of(gid, character["id"])
        embed, art = utils.character_card(
            db, gid, character, random_art=True,
            footer=f"{left} rolls left • rolled by {ctx.author.display_name}",
        )

        content = None
        if wishers and owner_id is None:
            # Anyone who asked for their wishes privately gets a DM instead of
            # a mention. The channel ping still happens for everyone else, so
            # a shut DM never means a missed wish.
            quiet, loud = [], []
            for wisher in wishers:
                target = quiet if db.get_player_pref(
                    gid, wisher, "wish_dm") else loud
                target.append(wisher)
            if loud:
                content = " ".join(f"<@{w}>" for w in loud) + " — wished!"
            for wisher in quiet:
                member = ctx.guild.get_member(wisher)
                if member is None:
                    continue
                try:
                    await member.send(
                        f"\u2b50 **{character['name']}** ·"
                        f" {character['series']} just rolled in"
                        f" #{ctx.channel.name} — you wished for them."
                    )
                except discord.HTTPException:
                    # DMs shut: fall back to the channel rather than losing it.
                    content = ((content + " ") if content else "") \
                        + f"<@{wisher}> — wished!"

        if owner_id is None:
            view = ClaimView(self, gid, character, ctx.author.id, wishers)
        else:
            view = KarudaView(self, gid, character)

        message = await ctx.send(content=content, embed=embed, view=view, **art)
        view.message = message

    @commands.command(name="rolls", aliases=["ru", "rollsleft", "cooldowns", "cd", "timers"])
    @commands.guild_only()
    async def rolls(self, ctx):
        """Show your rolls left and every cooldown."""
        gid = ctx.guild.id
        uid = ctx.author.id
        left, reset_in = self.bot.cooldowns.rolls_left(gid, uid)
        claim_ready, claim_in = self.bot.cooldowns.claim_ready(gid, uid)
        kak_ready, kak_in = self.bot.cooldowns.karuda_ready(gid, uid)
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
            name="Karuda",
            value="ready now" if kak_ready else f"in {fmt_duration(kak_in)}",
            inline=True,
        )
        embed.add_field(name="Balance", value=f"{player['karuda']} karuda", inline=True)
        embed.add_field(
            name="Harem",
            value=f"{self.bot.db.harem_size(gid, uid)} characters",
            inline=True,
        )
        await ctx.send(embed=embed)

    @commands.command(name="limroul", aliases=["limitroulette", "rollcap"])
    @commands.guild_only()
    async def limroul(self, ctx, value: str = None):
        """How deep the rolls go. `$limroul` to see, `$limroul 20000` to set."""
        db = self.bot.db
        gid = ctx.guild.id
        pool = db.count_characters_in(gid)

        if value is not None:
            # Reading is for everybody; changing the server is not.
            if not ctx.author.guild_permissions.manage_guild:
                raise commands.MissingPermissions(["manage_guild"])
            wanted = value.strip().lower()
            if wanted in ("off", "none", "all", "0"):
                limit = 0
            else:
                try:
                    limit = int(wanted.replace(",", "").replace("#", ""))
                except ValueError:
                    await ctx.send(
                        f"Give a rank, or `off`. `{ctx.prefix}limroul 20000`"
                    )
                    return
            _default, low, high, _text = config.GUILD_SETTINGS["roll_rank_limit"]
            if not low <= limit <= high:
                await ctx.send(f"Pick a rank between {low} and {high:,}, or `off`.")
                return
            db.set_setting(gid, "roll_rank_limit", limit)

        limit = db.get_setting(gid, "roll_rank_limit")
        if limit <= 0:
            await ctx.send(
                f"Rolls reach the whole roster — all {pool:,} characters."
                f" `{ctx.prefix}limroul 20000` would cut it to the top 20,000."
            )
            return

        # The deepest character actually reachable, which is not the same as
        # the limit: a server can set 20,000 on a roster that stops at 12,000.
        deepest = db.deepest_rollable(gid)
        await ctx.send(
            f"Rolls stop at claim rank **#{limit:,}**"
            + (f", and the lowest anyone here can roll is **#{deepest:,}**."
               if deepest else ".")
            + f" The other {max(0, pool - deepest):,} of {pool:,} are switched"
            f" off. `{ctx.prefix}limroul off` rolls everybody again."
        )


async def setup(bot):
    await bot.add_cog(Rolling(bot))
