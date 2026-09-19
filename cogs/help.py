"""Help, sent by DM.

Seventy-nine commands in one message is a wall nobody reads. This sends an
overview privately, with a menu to open one section at a time, so the channel
stays clean and so does the page.
"""
import discord
from discord.ext import commands

import config

# (icon, name, blurb, [(usage, description), ...])
# An empty entry is a spacer. Those blank lines are most of what stops a list
# of twenty commands reading as a wall of text.
CATEGORIES = [
    ("\U0001f3b4", "Rolling", "Finding characters", [
        ("w", "Roll a character"),
        ("h", "Roll a husbando"),
        ("m", "Roll anything"),
        ("", ""),
        ("rolls", "Rolls left and every cooldown"),
    ]),
    ("\U0001f495", "Your characters", "Everyone you have claimed", [
        ("mm [@user]", "Browse a harem"),
        ("mm @user recent", "…or sort by likes, name, recent, karuda"),
        ("", ""),
        ("im <name>", "Character card"),
        ("album <name>", "Every image a character has"),
        ("search <text>", "Search by name or series"),
        ("series <name>", "A series and everyone in it"),
        ("", ""),
        ("note", "Annotate one of yours"),
        ("divorce", "Let one go"),
        ("top", "Biggest harems here"),
    ]),
    ("\U0001f9f9", "Clearing out", "Letting go in bulk", [
        ("divorceall", "Your whole harem"),
        ("divorceseries <name>", "Everyone from one series"),
        ("divorceallbut <n>", "Keep your best n by value"),
        ("", ""),
        ("wishremoveall", "Empty your wishlist"),
    ]),
    ("\U0001f48e", "Karuda", "The currency", [
        ("dk", "Two shards: keep one, others may snipe the rest"),
        ("shards", "What each shard pays, and the odds"),
        ("", ""),
        ("k [@user]", "Balance and shard collection"),
        ("pay @user <amount>", "Send karuda"),
        ("richest", "Who has the most"),
    ]),
    ("\U0001f6d2", "Shop", "Somewhere for karuda to go", [
        ("shop", "What karuda buys"),
        ("", ""),
        ("buyrolls [n]", "More rolls this window"),
        ("resetclaim", "Claim again now"),
        ("wishslot", "A permanent wishlist slot"),
    ]),
    ("🏅", "Badges & tower", "Long-term perks", [
        ("badges", "What you can buy, and what you own"),
        ("buybadge <name>", "Buy one"),
        ("", ""),
        ("kt", "Your tower, and the next floor"),
        ("ktup", "Climb a floor"),
        ("toptower", "Who has climbed highest"),
        ("", ""),
        ("perks", "What it all adds up to"),
    ]),
    ("💖", "Bonds", "Soulmates and keys", [
        ("setsoulmate", "Name one character your soulmate"),
        ("soulmate [@user]", "See a soulmate"),
        ("soulmates", "Who everyone here has chosen"),
        ("", ""),
        ("keys", "Keys you hold and have spent"),
        ("key", "Spend one to raise a character's value"),
        ("keyed [@user]", "Everyone you have keyed"),
    ]),
    ("⭐", "Wishes", "Get pinged when they roll", [
        ("wish <name>", "Add a wish"),
        ("wishseries <name>", "Wish a whole series"),
        ("", ""),
        ("wishlist [@user]", "See a wishlist"),
        ("unwish", "Drop one"),
        ("wishedby <name>", "Who is waiting on someone"),
    ]),
    ("❤️", "Likes", "Vote for characters", [
        ("like <name>", "Like a character"),
        ("unlike <name>", "Take it back"),
        ("", ""),
        ("likelist [@user]", "Everyone you like"),
        ("mostliked", "This server's favourites"),
        ("likepos <name>", "Where someone ranks here"),
    ]),
    ("\U0001f91d", "Trading", "Both sides pick from a menu", [
        ("trade @user", "Swap one for one"),
        ("gift @user", "Hand one over"),
    ]),
    ("\U0001f464", "You", "Your standing, and odds and ends", [
        ("profile [@user]", "Balance, best claim, cooldowns"),
        ("access", "What you have access to"),
        ("", ""),
        ("stats", "Pool size and what this server has claimed"),
        ("myid", "Your Discord id"),
        ("invite", "Add the bot elsewhere"),
        ("ping", "Latency"),
    ]),
    ("✨", "Custom characters", "Your own · Manage Server", [
        ("addcustom Name | Series | url", "One only this server rolls"),
        ("customlist", "Everything this server made"),
        ("", ""),
        ("imgcustom Name | url", "Add an image"),
        ("namecustom Old | New", "Rename"),
        ("seriescustom Name | Series", "Refile"),
        ("valuecustom <n> <name>", "Set what one is worth"),
        ("deletecustom <name>", "Remove one"),
    ]),
    ("⚙️", "Server admin", "Manage Server", [
        ("settings", "Every tunable and its value"),
        ("set <key> <value>", "Change one"),
        ("", ""),
        ("setrolls / setclaim / setinterval", "Friendlier setters"),
        ("setrate / setgrab / setrefund", "Economy dials"),
        ("", ""),
        ("prefix <char>", "Change the prefix here"),
        ("disable / enable <command>", "Switch a command off or on"),
        ("channelallow / channeldeny", "Limit the bot to channels"),
    ]),
    ("\U0001f527", "Bot owner", "Pool management", [
        ("import [path]", "Bulk load characters"),
        ("export", "Dump the pool"),
        ("", ""),
        ("addchar / editchar / delchar", "One at a time"),
        ("setimage / addimage / delimage", "Artwork"),
        ("missingart [series]", "What still needs art"),
        ("", ""),
        ("genkey [n] [note]", "Mint keys"),
        ("keystats", "How many premium keys exist and are spent"),
    ]),
]

TOTAL = sum(sum(1 for usage, _ in entries if usage) for *_, entries in CATEGORIES)


def overview_embed(prefix: str) -> discord.Embed:
    embed = discord.Embed(
        title="Commands",
        description=(
            f"Prefix is `{prefix}` — start with `{prefix}w` to roll,"
            f" then `{prefix}dk` for your daily.\n\n"
            "Pick a section below, or page through with the arrows."
        ),
        colour=config.CARD_COLOUR,
    )
    # Inline fields lay the sections out in columns rather than one long list.
    for icon, name, blurb, entries in CATEGORIES:
        count = sum(1 for usage, _ in entries if usage)
        embed.add_field(
            name=f"{icon}  {name}", value=f"{blurb}\n`{count} commands`", inline=True
        )
    embed.set_footer(text=f"{TOTAL} commands · {prefix}help <command> for detail")
    return embed


def category_embed(index: int, prefix: str) -> discord.Embed:
    icon, name, blurb, entries = CATEGORIES[index]
    lines = []
    for usage, description in entries:
        if not usage:
            lines.append("")  # breathing room between groups
            continue
        # Command on one line, what it does indented under it: far easier to
        # scan than name and description fighting on the same line.
        lines.append(f"`{prefix}{usage}`\n　{description}")
    embed = discord.Embed(
        title=f"{icon}  {name}",
        description="\n".join(lines),
        colour=config.CARD_COLOUR,
    )
    embed.set_footer(text=f"{blurb} · section {index + 1} of {len(CATEGORIES)}")
    return embed


class HelpView(discord.ui.View):
    """Overview, a jump menu and arrows, living in the reader's DMs."""

    def __init__(self, prefix: str, owner_id: int, timeout: float = 600):
        super().__init__(timeout=timeout)
        self.prefix = prefix
        self.owner_id = owner_id
        self.index = None  # None is the overview
        self.message = None

        select = discord.ui.Select(
            placeholder="Jump to a section…",
            options=[
                discord.SelectOption(
                    label=name, value=str(i), emoji=icon, description=blurb[:100]
                )
                for i, (icon, name, blurb, _entries) in enumerate(CATEGORIES)
            ],
            row=0,
        )
        select.callback = self._on_select
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    def render(self) -> discord.Embed:
        if self.index is None:
            return overview_embed(self.prefix)
        return category_embed(self.index, self.prefix)

    async def _refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.render(), view=self)

    async def _on_select(self, interaction: discord.Interaction):
        self.index = int(interaction.data["values"][0])
        await self._refresh(interaction)

    @discord.ui.button(label="◀", row=1)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = len(CATEGORIES) - 1 if self.index in (None, 0) else self.index - 1
        await self._refresh(interaction)

    @discord.ui.button(label="Overview", style=discord.ButtonStyle.primary, row=1)
    async def overview(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = None
        await self._refresh(interaction)

    @discord.ui.button(label="▶", row=1)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = 0 if self.index is None else (self.index + 1) % len(CATEGORIES)
        await self._refresh(interaction)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


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

        view = HelpView(prefix, ctx.author.id)
        try:
            view.message = await ctx.author.send(
                embed=overview_embed(prefix), view=view
            )
        except discord.Forbidden:
            # DMs closed. Post it here rather than failing silently, which
            # would look like the command is broken.
            view.message = await ctx.send(
                content=f"{ctx.author.mention} your DMs are closed, so here it is.",
                embed=overview_embed(prefix),
                view=view,
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
