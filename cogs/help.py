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
            ("mm [@user] [likes|name|recent|kakera]", "Browse a harem"),
            ("im <name>", "Character card"),
            ("search <text>", "Search the pool by name or series"),
            ("divorce <name>", "Release a character, refunds half its kakera"),
            ("note <name> | <text>", "Annotate one of your characters"),
            ("top", "Biggest harems in the server"),
        ],
    ),
    (
        "Kakera",
        [
            ("k [@user]", "Balance and harem worth"),
            ("daily", "Free kakera every 20h"),
            ("pay @user <amount>", "Send kakera"),
            ("richest", "Kakera leaderboard"),
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
            ("gift @user <name>", "Give a character away"),
            ("trade @user <yours> | <theirs>", "Swap two characters"),
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
            ("setimage <id> <url>", "Give a character its art"),
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
