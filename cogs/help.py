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
            ("series <name>", "A series and everyone in it"),
            ("divorceall", "Let go of your whole harem"),
            ("divorceseries <name>", "Let go of one series"),
            ("divorceallbut [n]", "Keep your top n by value"),
        ],
    ),
    (
        "Karuda",
        [
            ("k [@user]", "Balance and harem worth"),
            ("dk", "Two karuda drops to collect, every 20h"),
            ("shards", "What each shard type pays, and its odds"),
            ("pay @user <amount>", "Send karuda"),
            ("richest", "Karuda leaderboard"),
            ("shop", "What karuda buys"),
            ("buyrolls [n]", "Buy extra rolls for this window"),
            ("resetclaim", "Clear your claim cooldown"),
            ("wishslot", "Buy a permanent wishlist slot"),
        ],
    ),
    (
        "Wishes",
        [
            ("wish <name>", "Get pinged and a head start when it rolls"),
            ("unwish <name>", "Remove a wish"),
            ("wishlist [@user]", "Show a wishlist"),
            ("wishedby <name>", "Who is waiting on a character"),
            ("wishseries <name>", "Wish for a whole series"),
            ("wishremoveall", "Empty your wishlist"),
        ],
    ),
    (
        "Likes",
        [
            ("like <name>", "Vote for a character"),
            ("unlike <name>", "Take the vote back"),
            ("likelist [@user]", "Everyone you have liked"),
            ("mostliked", "The server's favourites"),
            ("likepos <name>", "Where a character ranks here"),
            ("likeclear", "Drop all your likes"),
        ],
    ),
    (
        "You",
        [
            ("profile [@user]", "Balance, best claim, cooldowns"),
            ("stats", "Pool size and what this server has claimed"),
            ("myid", "Your Discord user id"),
            ("invite", "Add the bot to another server"),
            ("ping", "Latency"),
            ("uptime", "How long the bot has been up"),
            ("access", "What you have access to, and since when"),
            ("redeem <key>", "Redeem a key"),
            ("alea [low] [high]", "Random number"),
            ("jankenpon <rock|paper|scissors>", "Rock paper scissors"),
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
            ("setrolls / setclaim / setinterval …", "Friendly setters"),
            ("prefix <char>", "Change the prefix here"),
            ("disable / enable <command>", "Switch a command off or on"),
            ("disablelist", "What is switched off"),
            ("channelallow / channeldeny / channellist", "Limit the bot to channels"),
            ("pool", "Pool size and most-liked characters"),
            ("missingart [series]", "Characters that still need an image"),
        ],
    ),
    (
        "Custom characters (Manage Server)",
        [
            ("addcustom Name | Series | url", "Add a character only this server rolls"),
            ("customlist", "Every custom this server has made"),
            ("imgcustom Name | url", "Add an image to one"),
            ("namecustom Old | New", "Rename one"),
            ("seriescustom Name | Series", "Refile one"),
            ("valuecustom <n> <name>", "Set what one is worth"),
            ("deletecustom <name>", "Remove one"),
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

    @commands.command(name="help", aliases=["commands", "channelhelp", "helpme"])
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
