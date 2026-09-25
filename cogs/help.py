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
        ("w", "roll a girl"),
        ("h", "roll a guy"),
        ("m", "roll anyone"),
        ("wa", "girl, anime only"),
        ("wg", "girl, games only"),
        ("ha", "guy, anime only"),
        ("hg", "guy, games only"),
        ("ma", "anyone, anime only"),
        ("mg", "anyone, games only"),
        ("rolls", "what you have left"),
    ]),
    ("\U0001f48d", "Your harem", [
        ("harem", "flip through yours"),
        ("haremlist", "the same as a list"),
        ("info", "one character's card"),
        ("album", "all of their art"),
        ("search", "find by name"),
        ("series", "a whole series"),
        ("note", "scribble on one"),
        ("divorce", "let one go"),
    ]),
    ("\U0001f5c3\ufe0f", "Harem tools", [
        ("mmw", "just the women"),
        ("mmh", "just the men"),
        ("mmr", "most valuable first"),
        ("sortmarry", "your default order"),
        ("smpos", "where one sits"),
        ("firstmarry", "your showcase"),
        ("infomarry", "who owns one"),
        ("haremcopy", "as plain text"),
        ("divorcepage", "let a page go"),
        ("haremlimit", "cap harem size"),
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
    ("\U0001f3c6", "Leaderboards", [
        ("top", "biggest harems"),
        ("topchars", "best in the pool"),
        ("topclaims", "most claimed"),
        ("topvalue", "richest harems"),
        ("topseries", "this server's taste"),
        ("topwished", "most wished for"),
        ("topshards", "shard collectors"),
        ("richest", "biggest balances"),
        ("mostliked", "most liked here"),
        ("toptower", "highest climbers"),
        ("serveroverview", "the server at a glance"),
    ]),
    ("\U0001f4d6", "About", [
        ("tuto", "the tutorial"),
        ("tutoprogress", "how far you are"),
        ("skipsubstep", "skip a blocked one"),
        ("silentstep", "quieten the ticks"),
        ("skiptuto", "jump to challenges"),
        ("resettuto", "start it again"),
        ("about", "what this bot is"),
        ("support", "what it costs"),
        ("preset", "set several dials"),
        ("lang", "which languages"),
    ]),
    ("🗣️", "Your words", [
        ("renameharem", "rename your collection"),
        ("renameclaim", "rename claiming"),
        ("renamedivorce", "rename letting go"),
        ("renamelikelist", "rename your likes"),
        ("renames", "every word you changed"),
    ]),
    ("🌟", "Wish settings", [
        ("starwish", "your one favourite"),
        ("wishdm", "pings by DM"),
        ("wishsort", "how it sorts"),
        ("wishprotect", "how long it holds"),
    ]),
    ("\U0001f375", "Tea", [
        ("tea", "what you are holding"),
        ("greentea", "three more rolls"),
        ("blacktea", "clear your claim wait"),
        ("redtea", "a little karuda"),
        ("yellowtea", "a character key"),
        ("mixtea", "one of them at random"),
        ("buytea", "buy one"),
        ("givetea", "hand one over"),
    ]),
    ("\U0001f3f7\ufe0f", "Nicknames", [
        ("alias", "teach one for everyone"),
        ("myalias", "one only you see"),
        ("alist", "the server's nicknames"),
        ("myalist", "yours"),
        ("aliasdel", "forget one"),
        ("myaliasdel", "forget one of yours"),
        ("resetalias", "forget them all"),
        ("selfresetalias", "forget all of yours"),
    ]),
    ("\U0001f5bc\ufe0f", "Artwork", [
        ("imglist", "every picture, as links"),
        ("imglink", "link to the main one"),
        ("randomimg", "one at random"),
        ("addimg", "add one to the pool"),
        ("changeimg", "pick which one leads"),
    ]),
    ("🔎", "Finding things", [
        ("findharem", "search your own"),
        ("findwish", "search your wishes"),
        ("findlike", "search your likes"),
        ("unowned", "who is still free"),
        ("castof", "a series at a glance"),
        ("imagecount", "how much art"),
        ("quietly", "a card by DM"),
        ("random", "a free random card"),
    ]),
    ("\U0001f4dd", "Notes", [
        ("note", "scribble on one"),
        ("notelist", "everything you wrote"),
        ("notesearch", "find a note"),
        ("noteseries", "note a whole series"),
        ("noteimg", "pin a picture"),
        ("noteimglist", "notes with pictures"),
        ("clearnotes", "wipe your notes"),
        ("divorcenote", "divorce by note"),
    ]),
    ("\U0001f9ef", "Resets \u2014 yours", [
        ("selfreset", "wipe your own everything"),
        ("selfresetwishes", "your wishlist"),
        ("selfresetlikes", "your likes"),
        ("selfresetnotes", "your notes"),
        ("cleanself", "same as selfreset"),
    ]),
    ("\U0001f6e1\ufe0f", "Resets \u2014 server", [
        ("fullreset", "wipe the whole server"),
        ("fullresetwishes", "every wishlist"),
        ("fullresetkeys", "every spent key"),
        ("fullresetnotes", "every note"),
        ("fullresetnoteimg", "every pinned picture"),
        ("fullresetdisable", "re-enable everything"),
        ("fullresetchannelperms", "unblock every channel"),
        ("fullresetcustom", "delete invented characters"),
        ("fullresettoggles", "switches and colour"),
    ]),
    ("\u2696\ufe0f", "Moderation", [
        ("modclean", "wipe one player"),
        ("forcedivorce", "take one off somebody"),
        ("kakeraadm", "give or take karuda"),
        ("kakerareward", "pay several people"),
        ("kakeraremoveall", "zero every balance"),
        ("embedcolor", "colour of the cards"),
        ("resetembedcolor", "back to the default"),
    ]),
    ("\U0001f512", "Jail & mutes", [
        ("jail", "lock in the jail"),
        ("jail list", "who's in jail"),
        ("unjail", "let them out"),
        ("timeout", "silence for a while"),
        ("timeout list", "who's timed out"),
        ("untimeout", "end it early"),
        ("imute", "no images"),
        ("unimute", "images back"),
        ("rmute", "no reactions"),
        ("unrmute", "reactions back"),
    ]),
    ("\u26a0\ufe0f", "Warnings", [
        ("warn", "warn someone"),
        ("warnings", "their warnings"),
        ("warn list", "the same"),
        ("warn remove", "drop one"),
        ("warn clear", "drop them all"),
        ("warnpunish", "auto punishments"),
        ("warnpunish add", "punish at N warns"),
        ("warnpunish list", "see them"),
        ("warnpunish remove", "stop one"),
    ]),
    ("\U0001f528", "Kicks & bans", [
        ("kick", "remove someone"),
        ("ban", "ban someone"),
        ("softban", "kick + wipe messages"),
        ("hardban", "ban that sticks"),
        ("hardban list", "who's hardbanned"),
        ("hardban remove", "lift a hardban"),
        ("unban", "lift a ban"),
        ("strip", "take dangerous roles"),
        ("staffstrip", "take staff roles"),
    ]),
    ("\U0001f9f9", "Cleaning up", [
        ("purge", "delete messages"),
        ("cleanup", "this bot's clutter"),
        ("botclear", "all bot messages"),
        ("selfpurge", "your own messages"),
        ("lockdown", "freeze a channel"),
        ("lockdown all", "freeze everything"),
        ("lockdown ignore", "skip a channel"),
        ("lockdown ignore list", "skipped channels"),
        ("lockdown ignore remove", "stop skipping"),
        ("lockdown role", "role to freeze"),
        ("unlockdown", "unfreeze a channel"),
        ("unlockdown all", "unfreeze everything"),
    ]),
    ("\U0001f4dc", "Records & names", [
        ("history", "someone's record"),
        ("modhistory", "a mod's actions"),
        ("audit", "the audit log"),
        ("nickname", "change a nickname"),
        ("nickname remove", "reset it"),
        ("nickname force", "pin a nickname"),
        ("nickname force cancel", "unpin it"),
        ("forcenick", "pin or unpin"),
    ]),
    ("\U0001f6e1\ufe0f", "Mod setup", [
        ("setupmod", "jail, roles, log"),
        ("setupmod reset", "start over"),
        ("modlog", "pick the log channel"),
        ("staffroles", "staff roles"),
        ("staffroles add", "make a role staff"),
        ("staffroles list", "see them"),
        ("staffroles remove", "unmake one"),
        ("invoke", "custom messages"),
        ("invoke set", "write one"),
        ("invoke view", "read one"),
        ("invoke list", "see them all"),
        ("invoke reset", "back to default"),
        ("invoke test", "preview one"),
    ]),
    ("\U0001f4c8", "Levels", [
        ("rank", "your level"),
        ("levels", "level leaderboard"),
        ("levels settings", "how it's set up"),
        ("levels role", "level roles"),
        ("levels ignore list", "no-XP channels"),
    ]),
    ("\U0001f527", "Level setup", [
        ("levels role add", "role at a level"),
        ("levels role remove", "drop one"),
        ("levels sync", "hand out earned roles"),
        ("levels channel", "where level-ups go"),
        ("levels karuda", "karuda per 5 levels"),
        ("levels voice", "voice XP on or off"),
        ("levels ignore", "no XP in a channel"),
        ("levels ignore remove", "count it again"),
        ("levels set", "set someone's level"),
        ("levels import", "bring levels over"),
        ("levels reset", "back to level 0"),
    ]),
    ("\U0001f50a", "Voice rooms", [
        ("vc", "every vc command"),
        ("vc lock", "lock your call"),
        ("vc unlock", "open it"),
        ("vc hide", "hide it"),
        ("vc unhide", "show it"),
        ("vc rename", "rename it"),
        ("vc limit", "cap who joins"),
        ("vc permit", "let someone in"),
        ("vc reject", "take access away"),
        ("vc ban", "block someone"),
        ("vc unban", "unblock them"),
        ("vc claim", "take over"),
        ("vc transfer", "hand it over"),
    ]),
    ("\U0001f4ca", "Voice hours", [
        ("vc stats", "your vc time"),
        ("vc lb", "hour leaderboard"),
        ("vc hours", "hour roles"),
        ("vc hours add", "add an hour role"),
        ("vc hours remove", "drop one"),
        ("vc setup", "make Join To Create"),
        ("vc panel", "post the commands"),
        ("vc reset", "turn it off"),
    ]),
    ("\U0001f3c5", "Staff points", [
        ("point", "give a point"),
        ("points", "see someone's points"),
        ("toppoints", "who has the most"),
        ("removepoint", "take one back"),
        ("clearpoints", "wipe someone's points"),
    ]),
    ("\U0001f3ad", "Toy box", [
        ("lol", "laugh"),
        ("lmfao", "laugh harder"),
        ("omg", "be appalled"),
        ("pervert", "judge someone"),
        ("beam", "beam away"),
        ("bear", "a bear hug"),
        ("bitesthedust", "another one gone"),
        ("chocoshark", "chocolate shark"),
        ("kirby", "poyo"),
        ("kirchoco", "kirby, with chocolate"),
        ("nanachi", "nanaa~"),
        ("takach", "taka"),
        ("takawai", "too cute"),
        ("eater", "eat it"),
        ("destroy", "destroy something"),
    ]),
    ("\u270d\ufe0f", "Word games", [
        ("noun", "a random noun"),
        ("adject", "a random adjective"),
        ("adverb", "a random adverb"),
        ("vrb", "a random verb"),
        ("phrase", "a random sentence"),
        ("poem", "four lines"),
        ("quote", "fake wisdom"),
        ("invent", "invent something"),
        ("build", "build something"),
        ("date", "how the date goes"),
        ("fate", "ask fate"),
        ("say", "repeat it back"),
        ("secret", "told by DM"),
        ("rdmcountry", "a random country"),
        ("avatar", "someone's avatar"),
    ]),
    ("\U0001f39a\ufe0f", "Switches \u2014 pool", [
        ("toggles", "every switch"),
        ("resettoggles", "back to defaults"),
        ("togglewestern", "western cartoons"),
        ("togglegames", "game characters"),
        ("togglehentai", "adult characters"),
        ("togglehorror", "horror series"),
        ("toggledisturbing", "disturbing series"),
        ("toggleirl", "real people"),
    ]),
    ("\U0001f5bc\ufe0f", "Switches \u2014 cards", [
        ("togglerank", "ranks on cards"),
        ("togglelikerank", "the like rank"),
        ("toggleclaimrank", "the claim rank"),
        ("togglerolls", "rolls left"),
        ("togglelikerolls", "like rank on rolls"),
        ("toggleclaimrolls", "claim rank on rolls"),
        ("togglebutton", "claim by button"),
        ("togglereact", "claim by reaction"),
        ("togglesilent", "less chatter"),
        ("toggleslash", "slash commands"),
    ]),
    ("\U0001f4b0", "Switches \u2014 karuda", [
        ("togglekakera", "karuda at all"),
        ("togglekakeraclaim", "karuda for claiming"),
        ("togglekakeradaily", "the daily drop"),
        ("togglekakeradivorce", "karuda on divorce"),
        ("togglekakeralike", "karuda from likes"),
        ("togglekakerareact", "karuda from reacting"),
        ("togglekakerarolls", "grabs off rolls"),
        ("togglekakeraserver", "server events"),
        ("togglekakerasnipe", "sniping a drop"),
        ("togglekakeratrade", "karuda in trades"),
        ("togglesnipe", "sniping in general"),
    ]),
    ("\U0001f527", "Bot owner", [
        ("dbinfo", "is the data safe"),
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


# Discord refuses an embed over 6000 characters and more than 25 fields, and
# caps a whole message at 6000 across its embeds. Rather than thin the list
# out when it outgrows that, help sends a second message. The budget is set
# below the true limit so a long section can never straddle it.
PAGE_BUDGET = 5200
PAGE_FIELDS = 24


def _section(prefix: str, icon: str, name: str, entries) -> tuple:
    """One rendered section: (field name, field value)."""
    return (
        f"{icon}  {name}",
        "\n".join(f"`{prefix}{command}` {description}"
                   for command, description in entries),
    )


def help_pages(prefix: str) -> list:
    """Every command, across as few messages as it fits in.

    Sections are inline fields, so Discord lays them out three across rather
    than as one long column. Sections are packed greedily and a new page
    starts before the limit rather than after it, which means adding commands
    never silently truncates the list - it just spills onto another message.
    """
    pages, fields, size = [], [], 0
    for icon, name, entries in CATEGORIES:
        field = _section(prefix, icon, name, entries)
        cost = len(field[0]) + len(field[1])
        if fields and (size + cost > PAGE_BUDGET or len(fields) >= PAGE_FIELDS):
            pages.append(fields)
            fields, size = [], 0
        fields.append(field)
        size += cost
    if fields:
        pages.append(fields)

    embeds = []
    for number, page in enumerate(pages, 1):
        embed = discord.Embed(
            title="Every command" + (f"  ·  {number}/{len(pages)}"
                                     if len(pages) > 1 else ""),
            colour=config.CARD_COLOUR,
        )
        if number == 1:
            embed.description = (
                f"Type the command after `{prefix}` — so `{prefix}w` to roll.\n"
                f"**New here?** `{prefix}w`, press **Claim**, then `{prefix}dk`"
                f" for your daily.\n"
                f"Want detail on one? `{prefix}help <command>`."
            )
        for field_name, value in page:
            embed.add_field(name=field_name, value=value, inline=True)
        if number == len(pages):
            embed.set_footer(text=f"{TOTAL} commands")
        embeds.append(embed)
    return embeds


def help_embed(prefix: str) -> discord.Embed:
    """The first page. Kept for callers that only want one."""
    return help_pages(prefix)[0]


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

        pages = help_pages(prefix)
        try:
            for embed in pages:
                await ctx.author.send(embed=embed)
        except discord.Forbidden:
            # DMs closed. Post it here rather than failing silently, which
            # would look like the command is broken.
            await ctx.send(
                content=f"{ctx.author.mention} your DMs are closed, so here it is.",
                embed=pages[0],
            )
            for embed in pages[1:]:
                await ctx.send(embed=embed)
            return
        if ctx.guild:
            note = "sent you a DM \U0001f4ec"
            if len(pages) > 1:
                note = f"sent you {len(pages)} DMs \U0001f4ec"
            await ctx.send(f"{ctx.author.mention} {note}")

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
