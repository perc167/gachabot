"""A hand-written help command, grouped the way players think about the game."""
import discord
from discord.ext import commands

SECTIONS = [
    (
        "Rolling",
        [
            ("w", "Roll a character (also $wa, $m, $roll)"),
            ("rolls", "Rolls left and all your cooldowns"),
        ],
    ),
    (
        "Your characters",
        [
            ("mm [@user] [likes|name|recent|karuda]", "Browse a harem"),
            ("im <name>", "Character card"),
            ("search <text>", "Search the pool by name or series"),
            ("album <name>", "Flip through every image a character has"),
            ("divorce <name>", "Release a character, refunds half its karuda"),
            ("note <name> | <text>", "Annotate one of your characters"),
            ("top", "Biggest harems in the server"),
        ],
    ),
    (
        "Karuda",
        [
            ("k [@user]", "Balance and harem worth"),
            ("daily", "Pull a karuda shard, every 20h"),
            ("shards", "What each shard type pays, and its odds"),
            ("pay @user <amount>", "Send karuda"),
            ("richest", "Karuda leaderboard"),
        ],
    ),
    (
        "Wishes",
        [
            ("wish <name>", "Get pinged and a head start when it rolls"),
            ("unwish <name>", "Remove a wish"),
            ("wishlist [@user]", "Show a wishlist"),
            ("wishedby <name>", "Who is waiting on a character"),
        ],
    ),
    (
        "Trading",
        [
            ("gift @user", "Give a character away, pick from a menu"),
            ("trade @user", "Swap characters, you both pick from a menu"),
        ],
    ),
    (
        "Server admin",
        [
            ("settings", "Show every tunable"),
            ("set <key> <value>", "Change one (needs Manage Server)"),
            ("resetsettings", "Back to defaults"),
            ("pool", "Pool size and most-liked characters"),
            ("missingart [series]", "Characters that still need an image"),
        ],
    ),
    (
        "Bot owner",
        [
            ("addchar Name | Series", "Add a character (art and stats optional)"),
            ("setimage <id> <url>", "Set a character's main art"),
            ("addimage <id> <url...>", "Add images to a character's album"),
            ("delimage <id> <n>", "Remove image n from an album"),
            ("editchar <id> <field> <value>", "Edit a character"),
            ("delchar <id>", "Delete a character"),
            ("import [path]", "Bulk import JSON (or attach a file)"),
            ("export", "Dump the pool as JSON"),
        ],
    ),
]


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["commands", "h"])
    async def help(self, ctx):
        prefix = ctx.prefix
        embed = discord.Embed(
            title="Commands",
            description=f"Prefix: `{prefix}` — start with `{prefix}w`",
            colour=0xB388EB,
        )
        for title, entries in SECTIONS:
            embed.add_field(
                name=title,
                value="\n".join(f"`{prefix}{cmd}` — {desc}" for cmd, desc in entries),
                inline=False,
            )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
