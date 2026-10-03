"""What the bot is, how to start, and presets for setting it up quickly.

Mudae points several of these at its own website, its Patreon and its voting
pages. This bot has none of those, so rather than dead links these say the
true thing: it is free, it runs wherever you put it, and the premium features
are unlocked with a key.

`$preset` is the one that earns its place - a server should not have to learn
eight settings to make rolling feel faster or slower.
"""
import discord
from discord.ext import commands

import config

SUPPORT_EMAIL = "paperbot.support@gmail.com"

# name: (blurb, {setting: value})
#
# Only settings that exist are listed, so a preset can never quietly write a
# key nothing reads.
PRESETS = {
    "relaxed": (
        "Generous. Rolls come back quickly and claims are cheap.",
        {
            "roll_limit": 20,
            "roll_reset_minutes": 30,
            "claim_interval_minutes": 60,
            "karuda_interval_minutes": 10,
            "karuda_grab_percent": 12,
        },
    ),
    "normal": (
        "The defaults, as shipped.",
        {
            "roll_limit": 10,
            "roll_reset_minutes": 170,
            "claim_interval_minutes": 170,
            "karuda_interval_minutes": 20,
            "karuda_grab_percent": 8,
        },
    ),
    "slow": (
        "Scarce. Fewer rolls, long claims, characters worth fighting over.",
        {
            "roll_limit": 6,
            "roll_reset_minutes": 90,
            "claim_interval_minutes": 360,
            "karuda_interval_minutes": 30,
            "karuda_grab_percent": 5,
        },
    ),
}

class About(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="about", aliases=["wiki", "aboutbot", "miscellaneous"])
    async def about(self, ctx):
        """What this bot is."""
        prefix = ctx.prefix or config.PREFIX
        db = self.bot.db
        embed = discord.Embed(
            title="About",
            description=(
                "A gacha bot in the shape of Mudae, with its own roster and"
                " its own currency.\n\n"
                f"**{db.character_count():,} characters** are loaded, ranked by"
                " how many people on AniList have actually favourited them —"
                " so what a character is worth is measured, not guessed."
            ),
            colour=config.CARD_COLOUR,
        )
        embed.add_field(
            name="Currency",
            value=f"{config.CURRENCY_TITLE}, in eight kinds of shard."
                  f" `{prefix}shards` explains them.",
            inline=True,
        )
        embed.add_field(
            name="Per server",
            value="Claims, balances and settings are yours alone."
                  " The character pool is shared.",
            inline=True,
        )
        embed.set_footer(text=f"{prefix}tuto to start · {prefix}help for everything")
        await ctx.send(embed=embed)

    @commands.command(name="support", aliases=["vote", "patreon", "join", "donate"])
    async def support(self, ctx):
        """Getting help, what's free, and Paper's policies."""
        prefix = ctx.prefix or config.PREFIX
        site = "https://gachabot.perc-1fc.workers.dev"
        await ctx.send(
            embed=discord.Embed(
                title="Help with Paper",
                description=(
                    f"Questions, bugs or data requests: **{SUPPORT_EMAIL}**\n\n"
                    "Every part of Paper is free to use. Premium is optional"
                    f" and adds extras on top: `{prefix}upgrade` shows them."
                    " Nothing free today gets taken away.\n\n"
                    f"[Privacy Policy]({site}/privacy.html) ·"
                    f" [Terms of Service]({site}/terms.html)"
                ),
                colour=config.CARD_COLOUR,
            )
        )

    @commands.command(name="lang", aliases=["language"])
    async def lang(self, ctx):
        """Which languages the bot speaks."""
        await ctx.send(
            "English only for now. Character names come from AniList and keep"
            " their usual romanisation, so `Souma` and `Sohma` both find the"
            " Sohmas."
        )

    @commands.command(name="preset", aliases=["gamemode", "presets"])
    @commands.guild_only()
    async def preset(self, ctx, name: str = None):
        """Set several dials at once. `$preset relaxed`, `normal` or `slow`."""
        prefix = ctx.prefix or config.PREFIX
        db = self.bot.db

        if not name:
            embed = discord.Embed(
                title="Presets",
                description=f"`{prefix}preset <name>` sets them all at once.",
                colour=db.get_pref(ctx.guild.id, "cardcolour",
                                   config.CARD_COLOUR),
            )
            for key, (blurb, values) in PRESETS.items():
                embed.add_field(
                    name=key,
                    value=blurb + "\n" + ", ".join(
                        f"`{setting} {value}`" for setting, value in values.items()
                    ),
                    inline=False,
                )
            await ctx.send(embed=embed)
            return

        key = name.lower().strip()
        if key not in PRESETS:
            await ctx.send(
                "Which one? " + ", ".join(f"`{k}`" for k in PRESETS)
            )
            return
        if not ctx.author.guild_permissions.manage_guild:
            await ctx.send("Changing a preset needs Manage Server.")
            return

        blurb, values = PRESETS[key]
        trimmed = False
        values = dict(values)
        for setting, value in values.items():
            low, high = db.setting_range(ctx.guild.id, setting)
            fitted = max(low, min(high, value))
            trimmed = trimmed or fitted != value
            values[setting] = fitted
            db.set_setting(ctx.guild.id, setting, fitted)
        if trimmed:
            blurb += ("\n\n*Some numbers were brought into this server's range;"
                      f" Premium Plus sets them all. `{prefix}upgrade`*")
        await ctx.send(
            embed=discord.Embed(
                title=f"Preset: {key}",
                description=blurb + "\n\n" + "\n".join(
                    f"`{setting}` → **{value}**"
                    for setting, value in values.items()
                ),
                colour=db.get_pref(ctx.guild.id, "cardcolour",
                                   config.CARD_COLOUR),
            )
        )


async def setup(bot):
    await bot.add_cog(About(bot))
