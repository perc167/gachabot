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
            "roll_reset_minutes": 60,
            "claim_interval_minutes": 180,
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

TUTORIAL = [
    ("1. Roll", "`$w` shows a character with a **Claim** button."),
    ("2. Claim", "Press it. They are yours on this server, and nobody else"
                 " here can have them."),
    ("3. Collect", "`$dk` is your daily shards. `$k` is what you have."),
    ("4. Look after them",
     "`$mm` flips through your harem, `$note` scribbles on one,"
     " `$wish` gets you pinged when somebody you want turns up."),
    ("5. Spend it",
     "`$shop` sells rolls and resets, `$kt` climbs the tower,"
     " `$badges` buys perks that last."),
]


class About(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="tuto", aliases=["tutorial", "howto", "start"])
    async def tuto(self, ctx):
        """How to play, in five steps."""
        prefix = ctx.prefix or config.PREFIX
        embed = discord.Embed(
            title="How to play",
            description=f"Everything starts with `{prefix}w`.",
            colour=config.CARD_COLOUR,
        )
        for name, value in TUTORIAL:
            embed.add_field(name=name, value=value.replace("$", prefix),
                            inline=False)
        embed.set_footer(text=f"{prefix}help lists everything")
        await ctx.send(embed=embed)

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
        """Whether any of this costs anything. It does not."""
        prefix = ctx.prefix or config.PREFIX
        await ctx.send(
            embed=discord.Embed(
                title="Free, and staying that way for you",
                description=(
                    "There is nothing to vote on and nothing to subscribe to."
                    " This bot is self-hosted and free.\n\n"
                    "Some features are meant to be premium later. Anyone"
                    " playing before that happens keeps them — that is what"
                    f" `{prefix}redeem` and the keys are for, and"
                    f" `{prefix}access` shows what you already have."
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
        for setting, value in values.items():
            db.set_setting(ctx.guild.id, setting, value)
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
