"""Help: every command on one page, sent by DM.

The old version put each section behind a dropdown, which meant knowing which
section a command lived in before you could find it - exactly backwards for
somebody who does not know the command yet. So it is one page now: every
command visible at once, grouped, three columns, one short line each.

Each line is a command and what it does in two or three words. Anything
longer belongs in `$help <command>`, which prints the full description, the
arguments and the aliases.
"""
import discord
from discord.ext import commands

import config

# (icon, section, [(command, what it does), ...])
#
# The command shown is the one people actually type - `w` rather than `roll` -
# and every one of them resolves, aliases included. Keep the descriptions to
# two or three words: the point of this page is scanning, not reading.
CATEGORIES = [
    ("\U0001f3b2", "Rolling", [
        ("w", "roll someone"),
        ("h", "roll a guy"),
        ("m", "roll anyone"),
        ("rolls", "what you have left"),
    ]),
    ("\U0001f48d", "Your harem", [
        ("harem", "everyone you own"),
        ("info", "one character's card"),
        ("album", "all of their art"),
        ("search", "find by name"),
        ("series", "a whole series"),
        ("note", "scribble on one"),
        ("divorce", "let one go"),
        ("top", "biggest harems here"),
    ]),
    ("\U0001f9f9", "Clearing out", [
        ("divorceall", "let everyone go"),
        ("divorceseries", "one series, gone"),
        ("divorceallbut", "keep only your best"),
        ("wishremoveall", "empty your wishlist"),
        ("likeclear", "empty your likes"),
    ]),
    ("\U0001f48e", "Karuda", [
        ("dk", "your daily shards"),
        ("shards", "payouts and odds"),
        ("balance", "what you have"),
        ("pay", "send some over"),
        ("richest", "who has the most"),
    ]),
    ("\U0001f6d2", "Shop", [
        ("shop", "what karuda buys"),
        ("buyrolls", "more rolls now"),
        ("resetclaim", "claim again now"),
        ("wishslot", "one more wish"),
    ]),
    ("\U0001f3c5", "Badges & tower", [
        ("badges", "perks you can buy"),
        ("buybadge", "buy one"),
        ("tower", "your tower"),
        ("ktup", "climb a floor"),
        ("toptower", "who climbed highest"),
        ("perks", "everything you have earned"),
    ]),
    ("\U0001f496", "Bonds", [
        ("setsoulmate", "choose your soulmate"),
        ("soulmate", "see a soulmate"),
        ("soulmates", "everyone's choices"),
        ("unsoulmate", "break the bond"),
        ("keys", "keys you hold"),
        ("key", "spend one"),
        ("keyed", "who you have keyed"),
    ]),
    ("⭐", "Wishes", [
        ("wish", "get pinged for them"),
        ("wishseries", "wish a whole series"),
        ("wishlist", "see a wishlist"),
        ("unwish", "drop one"),
        ("wishedby", "who is waiting"),
    ]),
    ("❤️", "Likes", [
        ("like", "vote for someone"),
        ("unlike", "take it back"),
        ("likelist", "everyone you like"),
        ("mostliked", "this server's favourites"),
        ("likepos", "where they rank"),
    ]),
    ("\U0001f91d", "Trading", [
        ("trade", "swap one for one"),
        ("gift", "hand one over"),
    ]),
    ("\U0001f3ae", "Games", [
        ("quiz", "name the character"),
        ("slots", "gamble your karuda"),
        ("duel", "fight someone"),
    ]),
    ("\U0001f464", "You", [
        ("profile", "your whole standing"),
        ("access", "what you can use"),
        ("redeem", "use a premium key"),
        ("stats", "pool and server totals"),
        ("myid", "your Discord id"),
        ("invite", "add the bot elsewhere"),
        ("ping", "is it awake"),
        ("uptime", "how long it has run"),
        ("alea", "roll a dice"),
        ("jankenpon", "rock paper scissors"),
    ]),
    ("✨", "Your own characters", [
        ("addcustom", "invent one"),
        ("customlist", "see them all"),
        ("imgcustom", "give it art"),
        ("namecustom", "rename it"),
        ("seriescustom", "refile it"),
        ("valuecustom", "price it"),
        ("deletecustom", "remove it"),
    ]),
    ("⚙️", "Server admin", [
        ("settings", "every dial"),
        ("set", "change one"),
        ("resetsettings", "back to defaults"),
        ("setrolls", "rolls per window"),
        ("prefix", "change the prefix"),
        ("disable", "switch a command off"),
        ("enable", "switch it back on"),
        ("enableall", "switch them all on"),
        ("disablelist", "what is switched off"),
        ("channelallow", "allow a channel"),
        ("channeldeny", "block a channel"),
        ("channellist", "which channels"),
        ("channelclear", "allow everywhere"),
    ]),
    ("\U0001f527", "Bot owner", [
        ("import", "load the roster"),
        ("export", "dump the roster"),
        ("pool", "what is loaded"),
        ("addseries", "pull in a series"),
        ("addchar", "add one by hand"),
        ("editchar", "edit one"),
        ("delchar", "delete one"),
        ("setimage", "set the art"),
        ("addimage", "add to the album"),
        ("delimage", "remove an image"),
        ("missingart", "who has no picture"),
        ("genkey", "mint premium keys"),
        ("keystats", "keys made and spent"),
    ]),
]

TOTAL = sum(len(entries) for *_, entries in CATEGORIES)


def help_embed(prefix: str) -> discord.Embed:
    """Every command, on one page.

    Sections are inline fields so Discord lays them out three across instead
    of as one long column - the whole thing fits in about a screen, which is
    the entire point.
    """
    embed = discord.Embed(
        title="Every command",
        description=(
            f"Type the command after `{prefix}` — so `{prefix}w` to roll.\n"
            f"**New here?** `{prefix}w`, press **Claim**, then `{prefix}dk`"
            f" for your daily.\n"
            f"Want detail on one? `{prefix}help <command>`."
        ),
        colour=config.CARD_COLOUR,
    )
    for icon, name, entries in CATEGORIES:
        embed.add_field(
            name=f"{icon}  {name}",
            value="\n".join(
                f"`{prefix}{command}` {description}"
                for command, description in entries
            ),
            inline=True,
        )
    embed.set_footer(text=f"{TOTAL} commands")
    return embed


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help", aliases=["commands", "channelhelp", "helpme"])
    async def help(self, ctx, *, command: str = None):
        """Sends the command list to your DMs. `$help <command>` for one."""
        prefix = ctx.prefix if ctx.prefix and len(ctx.prefix) < 6 else config.PREFIX

        if command:
            await self._one_command(ctx, command.strip().lstrip(prefix), prefix)
            return

        embed = help_embed(prefix)
        try:
            await ctx.author.send(embed=embed)
        except discord.Forbidden:
            # DMs closed. Post it here rather than failing silently, which
            # would look like the command is broken.
            await ctx.send(
                content=f"{ctx.author.mention} your DMs are closed, so here it is.",
                embed=embed,
            )
            return
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention} sent you a DM \U0001f4ec")

    async def _one_command(self, ctx, name: str, prefix: str):
        found = self.bot.get_command(name.lower())
        if not found:
            await ctx.send(
                f"No command called `{name}`. Try `{prefix}help` for the list."
            )
            return
        embed = discord.Embed(
            title=f"{prefix}{found.qualified_name}",
            description=(found.help or "No description.").strip(),
            colour=config.CARD_COLOUR,
        )
        if found.signature:
            embed.add_field(
                name="Usage",
                value=f"`{prefix}{found.qualified_name} {found.signature}`",
                inline=False,
            )
        if found.aliases:
            embed.add_field(
                name="Also answers to",
                value=" ".join(f"`{prefix}{alias}`" for alias in sorted(found.aliases)),
                inline=False,
            )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
