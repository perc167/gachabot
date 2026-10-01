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

        # The tower's key perks: a chance of a key for claiming one of your
        # own wishes, or anyone at all.
        earned = perks.effective(db, self.guild_id, user.id)
        chance = max(earned["key_on_claim"],
                     earned["key_on_wish"] if user.id in self.wishers else 0)
        key_note = ""
        if chance and random.random() * 100 < chance:
            got, held = perks.earn_keys(db, self.guild_id, user.id, 1)
            key_note = f" \U0001f511 +{got} key{'s' if got > 1 else ''} (you hold {held})"

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
            f" **{self.character['name']}**!{key_note}"
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


def timer_lines(bot, guild_id: int, member, prefix: str, only=None) -> list:
    """Mudae's $tu, a line per timer. `only` picks some of them, in order."""
    db, cooldowns = bot.db, bot.cooldowns
    uid = member.id
    name = f"**{member.display_name}**"
    parts = {}

    ready, wait = cooldowns.claim_ready(guild_id, uid)
    reset_at, _ = cooldowns.claim_window(guild_id)
    next_reset = fmt_duration(reset_at - utils.now())
    parts["claim"] = (
        f"{name}, you __can__ claim right now! The next claim reset is in"
        f" **{next_reset}**." if ready else
        f"{name}, you can't claim for another **{fmt_duration(wait)}**.")

    left, reset_in = cooldowns.rolls_left(guild_id, uid)
    parts["rolls"] = (f"You have **{left}** roll{'s' if left != 1 else ''} left."
                      f" Next rolls reset in **{fmt_duration(reset_in)}**.")

    ready, wait = cooldowns.daily_ready(guild_id, uid)
    parts["daily"] = (f"`{prefix}daily` is available!" if ready else
                      f"Next `{prefix}daily` reset in **{fmt_duration(wait)}**.")

    ready, wait = cooldowns.karuda_ready(guild_id, uid)
    parts["grab"] = ("You __can__ grab karuda right now!" if ready else
                     f"You can't grab karuda for another"
                     f" **{fmt_duration(wait)}**.")

    wait = db.get_player(guild_id, uid)["daily_ready_at"] - utils.now()
    parts["dk"] = (f"`{prefix}dk` is ready!" if wait <= 0 else
                   f"Next `{prefix}dk` in **{fmt_duration(wait)}**.")

    if cooldowns.rt_unlocked(guild_id, uid):
        ready, wait = cooldowns.rt_ready(guild_id, uid)
        parts["rt"] = (f"`{prefix}rt` is available!" if ready else
                       f"Time left before `{prefix}rt`: **{fmt_duration(wait)}**.")

    player = db.get_player(guild_id, uid)
    if player["roll_resets"]:
        count = player["roll_resets"]
        parts["stock"] = (f"You have **{count}** rolls reset{'s' if count != 1 else ''}"
                          f" in stock (`{prefix}us`).")
    parts["balance"] = f"Karuda: **{player['karuda']:,}**"

    order = only or ("claim", "rolls", "daily", "grab", "dk", "rt", "stock",
                     "balance")
    return [parts[key] for key in order if key in parts]


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
            # Point at a reset they already have before making them wait.
            hint = ""
            if self.bot.cooldowns.daily_ready(gid, ctx.author.id)[0]:
                hint = f" `{ctx.prefix}daily` is ready and resets them now."
            elif db.get_player(gid, ctx.author.id)["roll_resets"]:
                hint = f" You have a rolls reset in stock: `{ctx.prefix}us`."
            await ctx.send(
                f"{ctx.author.mention} you are out of rolls."
                f" More in {fmt_duration(reset_in)}.{hint}"
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

    # ---- timers, the way Mudae's $tu words them --------------------

    @commands.command(name="tu", aliases=["rolls", "timers", "timersup",
                                          "cooldowns", "cd"])
    @commands.guild_only()
    async def tu(self, ctx):
        """Every timer you have: claim, rolls, $daily, $dk, $rt."""
        await ctx.send("\n".join(timer_lines(self.bot, ctx.guild.id,
                                              ctx.author, ctx.prefix)))

    @commands.command(name="mu", aliases=["marryup", "claimup"])
    @commands.guild_only()
    async def mu(self, ctx):
        """When you can claim next."""
        await ctx.send(timer_lines(self.bot, ctx.guild.id, ctx.author,
                                   ctx.prefix, only=("claim",))[0])

    @commands.command(name="ru", aliases=["rollsleft"])
    @commands.guild_only()
    async def ru(self, ctx):
        """How many rolls you have, and when they come back."""
        await ctx.send("\n".join(timer_lines(
            self.bot, ctx.guild.id, ctx.author, ctx.prefix,
            only=("rolls", "stock"))))

    @commands.command(name="daily", aliases=["dailyrolls", "dailyreset"])
    @commands.guild_only()
    async def daily(self, ctx):
        """A free rolls reset, every 20 hours."""
        cooldowns = self.bot.cooldowns
        gid, uid = ctx.guild.id, ctx.author.id
        result = cooldowns.take_daily(gid, uid)
        if not result:
            _ready, wait = cooldowns.daily_ready(gid, uid)
            await ctx.send(f"**{ctx.author.display_name}**, next {ctx.prefix}daily"
                           f" reset in **{fmt_duration(wait)}**.")
            return
        if result == "reset":
            left, _ = cooldowns.rolls_left(gid, uid)
            await ctx.send(f"✅ **{ctx.author.display_name}**, your rolls are"
                           f" reset: **{left}** rolls to go.")
            return
        stock = self.bot.db.get_player(gid, uid)["roll_resets"]
        await ctx.send(
            f"✅ **{ctx.author.display_name}**, your rolls are already full,"
            f" so the reset went in the bank ({stock} in stock)."
            f" `{ctx.prefix}us` uses it once you've rolled.")

    @commands.command(name="us", aliases=["userolls", "rollreset", "rollsreset"])
    @commands.guild_only()
    async def us(self, ctx):
        """Use a banked rolls reset from $daily."""
        gid, uid = ctx.guild.id, ctx.author.id
        result = self.bot.cooldowns.use_reset(gid, uid)
        if result == "none":
            await ctx.send(f"You have no rolls resets in stock."
                           f" `{ctx.prefix}daily` gives one every 20 hours.")
        elif result == "full":
            await ctx.send("Your rolls are already full. Roll first,"
                           " then use the reset.")
        else:
            left, _ = self.bot.cooldowns.rolls_left(gid, uid)
            stock = self.bot.db.get_player(gid, uid)["roll_resets"]
            await ctx.send(f"✅ Rolls reset: **{left}** to go"
                           f" ({stock} left in stock).")

    @commands.command(name="rt", aliases=["resetclaimtimer", "freeclaim"])
    @commands.guild_only()
    async def rt(self, ctx):
        """Reset your claim timer for free, every 20 hours (Opal IV, Premium
        Plus or Player Premium)."""
        cooldowns = self.bot.cooldowns
        gid, uid = ctx.guild.id, ctx.author.id
        if not cooldowns.rt_unlocked(gid, uid):
            await ctx.send(
                f"`{ctx.prefix}rt` comes with **Opal IV** (`{ctx.prefix}badges`),"
                f" a Premium Plus server, or your own Player Premium"
                f" (`{ctx.prefix}playerpremium`). Until then, `{ctx.prefix}resetclaim`"
                f" buys a claim reset with karuda.")
            return
        ready, wait = cooldowns.rt_ready(gid, uid)
        if not ready:
            await ctx.send(f"Time left before `{ctx.prefix}rt`:"
                           f" **{fmt_duration(wait)}**.")
            return
        if cooldowns.claim_ready(gid, uid)[0]:
            await ctx.send("You can already claim. Save the reset for when"
                           " you can't.")
            return
        cooldowns.use_rt(gid, uid)
        await ctx.send(f"✅ **{ctx.author.display_name}**, your claim is"
                       f" reset. Go get someone.")

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
