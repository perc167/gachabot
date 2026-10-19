"""Mudae's toggle family: two dozen on/off switches for one server.

They are generated from the table below rather than written out one at a
time. Twenty-seven near-identical command bodies would be twenty-seven places
for a typo to hide, and the table doubles as the thing `$toggles` prints.

Each entry carries whether it is actually wired to behaviour yet. A switch
that silently does nothing is worse than no switch at all, so the ones that
only record a preference say so when you flip them.
"""
import discord
from discord.ext import commands

import config

# key: (default, group, what it does, wired to behaviour yet)
TOGGLES = {
    # ---- what can roll -------------------------------------------------
    "western": (1, "Pool", "Roll Western cartoons and comics", True),
    "games": (1, "Pool", "Roll characters from video games", True),
    # "Adult" here has never meant grown-up characters - the key is the
    # giveaway - and two people in a server spent a while arguing about
    # which it was, which is the label's fault. It is also not wired to
    # anything: nothing filters on it at roll time, and nothing could,
    # because adult series are dropped at import (anilist.py) and so are
    # not in the roster to be switched off. Marked honestly rather than
    # left claiming to work.
    "hentai": (0, "Pool", "Roll characters from 18+ series (none are"
                          " imported, so this changes nothing)", False),
    "horror": (1, "Pool", "Roll horror series", False),
    "disturbing": (1, "Pool", "Roll disturbing series", False),
    "irl": (0, "Pool", "Roll real people", True),
    "freeonleave": (0, "Pool", "Free a leaver's characters back into the pool",
                    True),

    # ---- what a card shows ---------------------------------------------
    "rank": (1, "Cards", "Show ranks on cards", True),
    "likerank": (1, "Cards", "Show the like rank", True),
    "claimrank": (1, "Cards", "Show the claim rank", True),
    "rolls": (1, "Cards", "Show rolls left under a roll", True),
    "likerolls": (1, "Cards", "Show like rank on a roll", True),
    "claimrolls": (1, "Cards", "Show claim rank on a roll", True),
    "button": (1, "Cards", "Claim with a button", False),
    "react": (0, "Cards", "Claim with a reaction", False),
    "silent": (0, "Cards", "Keep the bot's chatter short", True),
    "slash": (0, "Cards", "Offer slash commands", False),

    # ---- where karuda comes from ---------------------------------------
    "kakera": (1, "Karuda", "Karuda at all", True),
    "kakeraclaim": (1, "Karuda", "Karuda for claiming", True),
    "kakeradaily": (1, "Karuda", "The daily shard drop", True),
    "kakeradivorce": (1, "Karuda", "Karuda back on divorce", True),
    "kakeralike": (1, "Karuda", "Karuda from likes", False),
    "kakerareact": (1, "Karuda", "Karuda from reacting", False),
    "kakerarolls": (1, "Karuda", "Karuda grabs off rolls", True),
    "kakeraserver": (1, "Karuda", "Server-wide karuda events", False),
    "kakerasnipe": (1, "Karuda", "Let others snipe a drop", True),
    "kakeratrade": (1, "Karuda", "Karuda in trades", False),
    "snipe": (1, "Karuda", "Sniping in general", True),
}

GROUPS = ("Pool", "Cards", "Karuda")

# Sources that count as Western rather than anime or manga, for $togglewestern.
WESTERN_SOURCES = ("last-airbender-api",)
GAME_SOURCES = ("fortnite-api", "overfast-api", "undertale.fandom",
                "deltarune.fandom", "ddlc.fandom")


def state(db, guild_id: int, key: str) -> bool:
    default = TOGGLES[key][0]
    return bool(db.get_toggle(guild_id, key, default))


class Toggles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="toggles", aliases=["togglelist", "switches"])
    @commands.guild_only()
    async def toggles(self, ctx):
        """Every switch and where it stands."""
        db = self.bot.db
        embed = discord.Embed(
            title=f"Switches for {ctx.guild.name}",
            description=f"Flip one with `{ctx.prefix}toggle<name>` —"
                        f" for example `{ctx.prefix}togglewestern`.",
            colour=config.CARD_COLOUR,
        )
        for group in GROUPS:
            lines = []
            for key, (default, section, description, live) in TOGGLES.items():
                if section != group:
                    continue
                mark = "✅" if state(db, ctx.guild.id, key) else "❌"
                note = "" if live else "  *(recorded only)*"
                lines.append(f"{mark} `{key}` {description}{note}")
            embed.add_field(name=group, value="\n".join(lines), inline=False)
        embed.set_footer(
            text="recorded only = the switch is remembered, but this bot has"
                 " nothing for it to change yet"
        )
        await ctx.send(embed=embed)

    @commands.command(name="resettoggles", aliases=["togglereset"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def resettoggles(self, ctx):
        """Put every switch back to its default."""
        self.bot.db.clear_toggles(ctx.guild.id)
        await ctx.send("Every switch is back to its default.")


def _make(bot, key: str, default: int, description: str, live: bool):
    """One toggle command, built from its table entry.

    Registered straight onto the bot rather than hung off the cog: discord.py
    collects a cog's commands when the class is created, so anything attached
    afterwards is simply never seen.
    """

    async def toggle(ctx):
        now = bot.db.flip_toggle(ctx.guild.id, key, default)
        word = "on" if now else "off"
        message = f"**{description}** is now **{word}**."
        if not live:
            message += ("\nRecorded, but nothing reads it yet — it will not"
                        " change how anything behaves.")
        await ctx.send(message)

    toggle.__name__ = f"toggle{key}"
    # What $help <command> prints, so every one of them says something real.
    toggle.__doc__ = (f"{description}. On by default." if default
                      else f"{description}. Off by default.")
    command = commands.command(name=f"toggle{key}")(toggle)
    command = commands.guild_only()(command)
    return commands.has_permissions(manage_guild=True)(command)


async def setup(bot):
    await bot.add_cog(Toggles(bot))
    for key, (default, _group, description, live) in TOGGLES.items():
        if bot.get_command(f"toggle{key}") is None:
            bot.add_command(_make(bot, key, default, description, live))
