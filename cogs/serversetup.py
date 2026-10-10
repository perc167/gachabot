"""Setting a server up: roles on join, welcome and goodbye messages, reaction
roles, and automatic replies. The bleed features people turn on first, made
as easy as they can be:

Autoroles       $autorole opens a menu: tick the roles new members get.
Server tag      $tagrole @role for everybody repping the server's tag.
Welcome         $welcome #channel turns it on with a friendly default;
Goodbye         $welcome message <text> to change what it says.
Reaction roles  $reactionrole add <message link> <emoji> @role
Auto replies    $autoresponder add hello, hi there!
Auto reactions  $autoreact add paper 📄

Autoroles and welcome/goodbye are on the web dashboard too (webparts.py).
"""
import re
import time
import typing

import discord
from discord.ext import commands

import config
from converters import FuzzyRole

KINDS = ("welcome", "goodbye")
DEFAULTS = {
    "welcome": "Welcome to **{server}**, {user}! You're member #{count}.",
    "goodbye": "**{user.name}** left **{server}**. We're {count} now.",
}
VARIABLES = ("{user}", "{user.name}", "{server}", "{count}")
MESSAGE_LIMIT = 1500
MAX_AUTOROLES = 10
MAX_RESPONDERS = 100
MAX_REACTS = 50
REPLY_COOLDOWN = 4          # seconds between the same auto reply in a channel


def fill(template: str, member, guild) -> str:
    return (template.replace("{user.name}", member.display_name)
            .replace("{user}", member.mention)
            .replace("{server}", guild.name)
            .replace("{count}", f"{guild.member_count or 0:,}"))[:2000]


def emoji_key(emoji) -> str:
    """How a reaction role's emoji is stored: a custom emoji by its id (its
    name can change), a standard one by itself, without the invisible
    variation mark that some keyboards add and some don't."""
    if not isinstance(emoji, discord.PartialEmoji):
        emoji = discord.PartialEmoji.from_str(str(emoji).strip())
    if emoji.id:
        return str(emoji.id)
    return (emoji.name or "").replace("️", "")


def matches(trigger: str, text: str) -> bool:
    """The trigger as a whole word or phrase in the message, any case."""
    return re.search(r"(?<!\w)" + re.escape(trigger) + r"(?!\w)", text, re.IGNORECASE) is not None


def tag_state(user) -> tuple:
    """Which tag they are showing, as something that can be compared.

    Reading `primary_guild` builds a fresh object every time and the class
    defines no equality, so two reads of an unchanged tag never compare
    equal to one another. The fields have to be compared instead.
    """
    shown = getattr(user, "primary_guild", None)
    if shown is None:
        return (None, None)
    return (shown.id, shown.identity_enabled)


def usable_role(guild, role) -> str:
    """Why this role can't be handed out automatically, or ''."""
    if role.is_default():
        return "@everyone is everyone's already."
    if role.managed:
        return f"**{role.name}** belongs to a bot or integration."
    if role >= guild.me.top_role:
        return f"**{role.name}** is above my highest role, so I can't give it."
    return ""


class AutoroleMenu(discord.ui.View):
    """$autorole: a role picker. Whatever's ticked is what new members get."""

    def __init__(self, cog, ctx):
        super().__init__(timeout=300)
        self.cog, self.ctx = cog, ctx
        current = [ctx.guild.get_role(r) for r in cog.db.autoroles_of(ctx.guild.id)]
        self.picker = discord.ui.RoleSelect(
            placeholder="Pick the roles new members get", min_values=0,
            max_values=MAX_AUTOROLES, default_values=[r for r in current if r])
        self.picker.callback = self.picked
        self.add_item(self.picker)
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Run `$autorole` yourself to change these.",
                                                    ephemeral=True)
            return False
        return True

    async def picked(self, interaction: discord.Interaction):
        guild = self.ctx.guild
        good, problems = [], []
        for role in self.picker.values:
            role = guild.get_role(role.id)
            why = usable_role(guild, role) if role else "That role is gone."
            (problems.append(why) if why else good.append(role))
        self.cog.db.replace_autoroles(guild.id, [r.id for r in good])
        await interaction.response.edit_message(embed=self.cog.autorole_embed(guild, problems),
                                                view=self)

    @discord.ui.button(label="None", style=discord.ButtonStyle.secondary)
    async def none(self, interaction: discord.Interaction, button):
        self.cog.db.replace_autoroles(self.ctx.guild.id, [])
        self.picker.default_values = []
        await interaction.response.edit_message(
            embed=self.cog.autorole_embed(self.ctx.guild, []), view=self)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class ServerSetup(commands.Cog):
    works_everywhere = True  # admin setup; see bot.check_allowed

    def __init__(self, bot):
        self.bot = bot
        self.replies = {}        # guild -> (autoresponders, autoreacts), cached
        self.last_reply = {}     # (channel, trigger) -> when it last fired

    @property
    def db(self):
        return self.bot.db

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    # ----------------------------------------------------------- autoroles

    def autorole_embed(self, guild, problems=()) -> discord.Embed:
        roles = [guild.get_role(r) for r in self.db.autoroles_of(guild.id)]
        roles = [r for r in roles if r]
        embed = discord.Embed(
            title="Autoroles",
            description=("New members get " + " ".join(r.mention for r in roles) + "."
                         if roles else "New members don't get any roles yet.")
            + "\n\nPick roles from the menu below. Bots never get them.",
            colour=config.CARD_COLOUR)
        if problems:
            embed.add_field(name="Left out", value="\n".join(problems)[:1024], inline=False)
        return embed

    @commands.group(name="autorole", aliases=["autoroles", "joinrole"],
                    invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def autorole(self, ctx):
        """Pick the roles new members get, from a menu."""
        view = AutoroleMenu(self, ctx)
        view.message = await ctx.send(embed=self.autorole_embed(ctx.guild), view=view)

    @autorole.command(name="add")
    @commands.has_permissions(manage_roles=True)
    async def autorole_add(self, ctx, *, role: FuzzyRole):
        """Give new members this role too."""
        why = usable_role(ctx.guild, role)
        roles = self.db.autoroles_of(ctx.guild.id)
        if not why and len(roles) >= MAX_AUTOROLES and role.id not in roles:
            why = f"That's {MAX_AUTOROLES} autoroles already."
        if why:
            await ctx.send(why, allowed_mentions=discord.AllowedMentions.none())
            return
        self.db.replace_autoroles(ctx.guild.id, [*roles, role.id])
        await ctx.send(f"New members get **{role.name}** now.",
                       allowed_mentions=discord.AllowedMentions.none())

    @autorole.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def autorole_remove(self, ctx, *, role: FuzzyRole):
        """Stop giving new members this role."""
        roles = self.db.autoroles_of(ctx.guild.id)
        self.db.replace_autoroles(ctx.guild.id, [r for r in roles if r != role.id])
        await ctx.send(f"New members don't get **{role.name}** any more."
                       if role.id in roles else f"**{role.name}** wasn't an autorole.",
                       allowed_mentions=discord.AllowedMentions.none())

    @autorole.command(name="list")
    async def autorole_list(self, ctx):
        """The roles new members get."""
        await ctx.send(embed=self.autorole_embed(ctx.guild))

    @autorole.command(name="clear", aliases=["off", "reset"])
    @commands.has_permissions(manage_roles=True)
    async def autorole_clear(self, ctx):
        """New members get no roles."""
        self.db.replace_autoroles(ctx.guild.id, [])
        await ctx.send("New members won't get any roles.")

    async def give_autoroles(self, member):
        guild = member.guild
        roles = [guild.get_role(r) for r in self.db.autoroles_of(guild.id)]
        roles = [r for r in roles if r and not usable_role(guild, r) and r not in member.roles]
        if roles and guild.me.guild_permissions.manage_roles:
            try:
                await member.add_roles(*roles, reason="Autorole")
            except discord.HTTPException:
                pass

    # ------------------------------------------------------- the server tag

    def tag_role(self, guild):
        """The role this server hands out for repping its tag, or None."""
        role_id = self.db.get_pref(guild.id, "tag_role", 0)
        return guild.get_role(role_id) if role_id else None

    @staticmethod
    def reps_tag(user, guild) -> bool:
        """Is this server's tag the one shown beside their name?

        Discord's own warning: somebody can have the tag switched on while
        the guild id reads None, when the tag changed and they have not
        reaffirmed it. So the id has to match, not merely the switch.
        """
        shown = getattr(user, "primary_guild", None)
        return bool(shown and shown.id == guild.id and shown.identity_enabled)

    async def sync_tag_role(self, member) -> bool:
        """Hand the role over, or take it back. True if anything changed."""
        guild = member.guild
        role = self.tag_role(guild)
        if role is None or member.bot:
            return False
        if usable_role(guild, role):
            return False
        if not guild.me.guild_permissions.manage_roles:
            return False
        wanted = self.reps_tag(member, guild)
        if wanted == (role in member.roles):
            return False
        try:
            if wanted:
                await member.add_roles(role, reason="Reps the server tag")
            else:
                await member.remove_roles(role, reason="Dropped the server tag")
        except discord.HTTPException:
            return False
        return True

    async def catch_up_tag_role(self, guild) -> int:
        """Put every member right in one pass, and say how many moved."""
        changed = 0
        for member in guild.members:
            if await self.sync_tag_role(member):
                changed += 1
        return changed

    def tagrole_embed(self, guild, prefix: str) -> discord.Embed:
        role = self.tag_role(guild)
        repping = sum(1 for m in guild.members
                      if not m.bot and self.reps_tag(m, guild))
        embed = discord.Embed(title="Server tag role",
                              colour=config.CARD_COLOUR)
        embed.add_field(name="Role", value=role.mention if role else "Off")
        embed.add_field(name="Repping the tag", value=f"{repping:,}")
        if role:
            problem = usable_role(guild, role)
            if problem:
                embed.add_field(name="But", value=problem, inline=False)
        embed.add_field(name="Change it", value=(
            f"`{prefix}tagrole @role` to set it\n"
            f"`{prefix}tagrole sync` to catch up everyone already repping\n"
            f"`{prefix}tagrole off` to stop"), inline=False)
        return embed

    @commands.group(name="tagrole", aliases=["servertag", "tagroles"],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def tagrole(self, ctx, *, role: FuzzyRole = None):
        """Give a role to everybody who reps this server's tag."""
        if role is None:
            await ctx.send(embed=self.tagrole_embed(ctx.guild, ctx.prefix))
            return
        problem = usable_role(ctx.guild, role)
        if problem:
            await ctx.send(problem)
            return
        self.db.set_pref(ctx.guild.id, "tag_role", role.id)
        async with ctx.typing():
            changed = await self.catch_up_tag_role(ctx.guild)
        await ctx.send(
            f"Anyone repping this server's tag now gets **{role.name}**."
            f" {changed:,} sorted out just now.",
            allowed_mentions=discord.AllowedMentions.none())

    @tagrole.command(name="off", aliases=["clear", "stop", "disable"])
    @commands.has_permissions(manage_roles=True)
    async def tagrole_off(self, ctx):
        """Stop giving a role for the tag."""
        self.db.set_pref(ctx.guild.id, "tag_role", 0)
        await ctx.send("No role for the server tag any more. Nobody has lost"
                       " the one they already have.")

    @tagrole.command(name="sync", aliases=["refresh", "catchup"])
    @commands.has_permissions(manage_roles=True)
    async def tagrole_sync(self, ctx):
        """Catch up everyone who already reps the tag, or has stopped."""
        if self.tag_role(ctx.guild) is None:
            await ctx.send("No tag role set yet."
                           f" `{ctx.prefix}tagrole @role` picks one.")
            return
        async with ctx.typing():
            changed = await self.catch_up_tag_role(ctx.guild)
        await ctx.send(f"Sorted {changed:,} out.")

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        """Somebody put the tag on, or took it off.

        It has to be this event rather than on_member_update: the tag lives
        on the user, and the member copy that on_member_update is handed
        shares that same user object, so its before and after would always
        read alike.
        """
        if tag_state(before) == tag_state(after):
            return
        for guild in self.bot.guilds:
            if not self.db.get_pref(guild.id, "tag_role", 0):
                continue
            member = guild.get_member(after.id)
            if member is not None:
                await self.sync_tag_role(member)

    # --------------------------------------------------- welcome & goodbye

    def greeting_embed(self, guild, kind: str, p: str = "$") -> discord.Embed:
        row = self.db.greeting(guild.id, kind)
        channel = guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        state = f"On, in {channel.mention}" if channel else "Off"
        embed = discord.Embed(title=f"{kind.capitalize()} messages", colour=config.CARD_COLOUR)
        embed.add_field(name="Status", value=state)
        embed.add_field(name="Style", value="embed" if row["embed"] else "plain text")
        embed.add_field(name="Message", value=(row["message"] or DEFAULTS[kind])[:1024],
                        inline=False)
        embed.add_field(name="Change it", value=(
            f"`{p}{kind} #channel` to turn it on there\n"
            f"`{p}{kind} message <text>` to change what it says\n"
            f"`{p}{kind} test` to see it · `{p}{kind} embed off` for plain text\n"
            f"`{p}{kind} off` to stop\n"
            f"Fill-ins: {' '.join(f'`{v}`' for v in VARIABLES)}"), inline=False)
        return embed

    async def greet(self, member, kind: str, channel=None) -> bool:
        """Send the welcome or goodbye for this member. False if it's off or
        can't be sent."""
        guild = member.guild
        row = self.db.greeting(guild.id, kind)
        channel = channel or (guild.get_channel(row["channel_id"]) if row["channel_id"] else None)
        if channel is None:
            return False
        text = fill(row["message"] or DEFAULTS[kind], member, guild)
        # A welcome pings the new member; a goodbye pings nobody.
        mentions = discord.AllowedMentions(users=[member] if kind == "welcome" else [],
                                           roles=False, everyone=False)
        try:
            if row["embed"]:
                embed = discord.Embed(description=text, colour=config.CARD_COLOUR)
                embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
                embed.set_thumbnail(url=member.display_avatar.url)
                embed.set_footer(text=guild.name, icon_url=guild.icon.url if guild.icon else None)
                await channel.send(member.mention if kind == "welcome" else None,
                                   embed=embed, allowed_mentions=mentions)
            else:
                await channel.send(text, allowed_mentions=mentions)
        except discord.HTTPException:
            return False
        return True

    async def greeting_command(self, ctx, kind: str, channel, message):
        if channel is None and message is None:
            await ctx.send(embed=self.greeting_embed(ctx.guild, kind, ctx.prefix))
            return
        fields = {}
        if channel is not None:
            rights = channel.permissions_for(ctx.guild.me)
            if not (rights.send_messages and rights.embed_links):
                await ctx.send(f"I can't send messages with embeds in {channel.mention}."
                               " Give me Send Messages and Embed Links there first.")
                return
            fields["channel_id"] = channel.id
        if message is not None:
            if len(message) > MESSAGE_LIMIT:
                await ctx.send(f"Keep it under {MESSAGE_LIMIT} characters.")
                return
            fields["message"] = message
        self.db.set_greeting(ctx.guild.id, kind, **fields)
        row = self.db.greeting(ctx.guild.id, kind)
        where = ctx.guild.get_channel(row["channel_id"]) if row["channel_id"] else None
        await ctx.send((f"{kind.capitalize()} messages go in {where.mention}."
                        if where else f"Saved. Turn them on with `{ctx.prefix}{kind} #channel`.")
                       + f" `{ctx.prefix}{kind} test` to see one.")

    @commands.group(name="welcome", aliases=["welc", "greet"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def welcome(self, ctx, channel: typing.Optional[discord.TextChannel] = None, *,
                      message: str = None):
        """Welcome new members: `$welcome #channel`, optionally with a message."""
        await self.greeting_command(ctx, "welcome", channel, message)

    @commands.group(name="goodbye", aliases=["bye", "leave"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def goodbye(self, ctx, channel: typing.Optional[discord.TextChannel] = None, *,
                      message: str = None):
        """Say goodbye when someone leaves: `$goodbye #channel`."""
        await self.greeting_command(ctx, "goodbye", channel, message)

    async def set_message(self, ctx, kind, text):
        if text.lower() in ("reset", "default"):
            text = ""
        if len(text) > MESSAGE_LIMIT:
            await ctx.send(f"Keep it under {MESSAGE_LIMIT} characters.")
            return
        self.db.set_greeting(ctx.guild.id, kind, message=text)
        await ctx.send(f"Saved. `{ctx.prefix}{kind} test` to see it.")

    async def set_embed(self, ctx, kind, state):
        on = state.lower() in ("on", "yes", "true")
        self.db.set_greeting(ctx.guild.id, kind, embed=1 if on else 0)
        await ctx.send(f"{kind.capitalize()} messages are {'embeds' if on else 'plain text'} now.")

    async def test(self, ctx, kind):
        row = self.db.greeting(ctx.guild.id, kind)
        where = ctx.guild.get_channel(row["channel_id"]) if row["channel_id"] else ctx.channel
        if not await self.greet(ctx.author, kind, where):
            await ctx.send("I couldn't send it. Check I can send messages and embeds there.")
        elif where != ctx.channel:
            await ctx.send(f"Sent a test to {where.mention}.")

    async def off(self, ctx, kind):
        self.db.set_greeting(ctx.guild.id, kind, channel_id=0)
        await ctx.send(f"{kind.capitalize()} messages are off.")

    @welcome.command(name="message", aliases=["msg", "text"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_message(self, ctx, *, text: str):
        """What the welcome says. `reset` for the default."""
        await self.set_message(ctx, "welcome", text)

    @goodbye.command(name="message", aliases=["msg", "text"])
    @commands.has_permissions(manage_guild=True)
    async def goodbye_message(self, ctx, *, text: str):
        """What the goodbye says. `reset` for the default."""
        await self.set_message(ctx, "goodbye", text)

    @welcome.command(name="embed")
    @commands.has_permissions(manage_guild=True)
    async def welcome_embed(self, ctx, state: str):
        """`on` for an embed with their picture, `off` for plain text."""
        await self.set_embed(ctx, "welcome", state)

    @goodbye.command(name="embed")
    @commands.has_permissions(manage_guild=True)
    async def goodbye_embed(self, ctx, state: str):
        """`on` for an embed with their picture, `off` for plain text."""
        await self.set_embed(ctx, "goodbye", state)

    @welcome.command(name="test")
    @commands.has_permissions(manage_guild=True)
    async def welcome_test(self, ctx):
        """See the welcome, as if you'd just joined."""
        await self.test(ctx, "welcome")

    @goodbye.command(name="test")
    @commands.has_permissions(manage_guild=True)
    async def goodbye_test(self, ctx):
        """See the goodbye, as if you'd just left."""
        await self.test(ctx, "goodbye")

    @welcome.command(name="off", aliases=["disable", "stop"])
    @commands.has_permissions(manage_guild=True)
    async def welcome_off(self, ctx):
        """Stop welcoming new members."""
        await self.off(ctx, "welcome")

    @goodbye.command(name="off", aliases=["disable", "stop"])
    @commands.has_permissions(manage_guild=True)
    async def goodbye_off(self, ctx):
        """Stop the goodbyes."""
        await self.off(ctx, "goodbye")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not member.bot and not member.pending:
            await self.give_autoroles(member)
            await self.sync_tag_role(member)
        await self.greet(member, "welcome")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Behind membership screening, roles wait until they've agreed.
        if before.pending and not after.pending and not after.bot:
            await self.give_autoroles(after)
            await self.sync_tag_role(after)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self.greet(member, "goodbye")

    # ------------------------------------------------------ reaction roles

    def emoji_shown(self, key: str) -> str:
        if key.isdigit():
            emoji = self.bot.get_emoji(int(key))
            return str(emoji) if emoji else f"(emoji {key})"
        return key

    @commands.group(name="reactionrole", aliases=["rr", "reactionroles"],
                    invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def reactionrole(self, ctx):
        """Every reaction role here."""
        rows = self.db.reaction_roles_of(ctx.guild.id)
        lines = [f"{self.emoji_shown(r['emoji'])} → <@&{r['role_id']}> on"
                 f" [this message](https://discord.com/channels/{ctx.guild.id}/"
                 f"{r['channel_id']}/{r['message_id']})" for r in rows]
        await ctx.send(embed=discord.Embed(
            title="Reaction roles",
            description="\n".join(lines)[:4000] or
            f"None yet. `{ctx.prefix}reactionrole add <message link> <emoji> @role`",
            colour=config.CARD_COLOUR))

    @reactionrole.command(name="add")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True, add_reactions=True)
    async def reactionrole_add(self, ctx, message: discord.Message, emoji: str, *,
                               role: FuzzyRole):
        """`$rr add <message link> <emoji> @role`: reacting gives the role,
        un-reacting takes it away."""
        if message.guild != ctx.guild:
            await ctx.send("That message isn't in this server.")
            return
        why = usable_role(ctx.guild, role)
        if not why and ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
            why = f"**{role.name}** is above your highest role."
        if why:
            await ctx.send(why, allowed_mentions=discord.AllowedMentions.none())
            return
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            await ctx.send("I can't react with that emoji. Use a standard emoji or one"
                           " from a server I'm in.")
            return
        self.db.add_reaction_role(ctx.guild.id, message.channel.id, message.id,
                                  emoji_key(emoji), role.id)
        await ctx.send(f"Reacting with {emoji} on that message gives **{role.name}** now.",
                       allowed_mentions=discord.AllowedMentions.none())

    @reactionrole.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_remove(self, ctx, message: discord.Message, emoji: str = None):
        """Stop one reaction role on a message, or all of them if you leave
        out the emoji."""
        gone = self.db.remove_reaction_role(ctx.guild.id, message.id,
                                            emoji_key(emoji) if emoji else None)
        await ctx.send(f"Removed {gone} reaction role{'s' if gone != 1 else ''}."
                       if gone else "There were no reaction roles there.")

    async def reaction_member(self, payload):
        if not payload.guild_id:
            return None, None
        row = self.db.reaction_role(payload.message_id, emoji_key(payload.emoji))
        if not row:
            return None, None
        guild = self.bot.get_guild(payload.guild_id)
        role = guild.get_role(row["role_id"]) if guild else None
        member = payload.member or (guild.get_member(payload.user_id) if guild else None)
        if not role or not member or member.bot or usable_role(guild, role):
            return None, None
        return member, role

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        member, role = await self.reaction_member(payload)
        if member and role not in member.roles:
            try:
                await member.add_roles(role, reason="Reaction role")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        member, role = await self.reaction_member(payload)
        if member and role in member.roles:
            try:
                await member.remove_roles(role, reason="Reaction role")
            except discord.HTTPException:
                pass

    # -------------------------------------------------------- auto replies

    def replies_for(self, guild_id: int):
        if guild_id not in self.replies:
            self.replies[guild_id] = (list(self.db.autoresponders_of(guild_id)),
                                      list(self.db.autoreacts_of(guild_id)))
        return self.replies[guild_id]

    @commands.group(name="autoresponder", aliases=["ar", "autoreply"],
                    invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def autoresponder(self, ctx):
        """Every auto reply here."""
        rows = self.db.autoresponders_of(ctx.guild.id)
        lines = [f"**{discord.utils.escape_markdown(r['trigger'])}** →"
                 f" {discord.utils.escape_markdown(r['response'])[:80]}" for r in rows]
        await ctx.send(embed=discord.Embed(
            title="Auto replies",
            description="\n".join(lines)[:4000] or
            f"None yet. `{ctx.prefix}autoresponder add hello, hi there!`",
            colour=config.CARD_COLOUR).set_footer(
                text="Replies when the trigger is said as a word or phrase, any case."))

    @autoresponder.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def autoresponder_add(self, ctx, *, text: str):
        """`$ar add trigger, response`: reply with the response whenever
        someone says the trigger. Fill-ins: {user} {user.name} {server}."""
        trigger, sep, response = text.partition(",")
        trigger, response = trigger.strip().lower(), response.strip()
        if not sep or not trigger or not response:
            await ctx.send(f"Put a comma between them: `{ctx.prefix}ar add hello, hi there!`")
            return
        if len(trigger) > 100 or len(response) > 1500:
            await ctx.send("Keep the trigger under 100 characters and the reply under 1,500.")
            return
        existing = {r["trigger"] for r in self.db.autoresponders_of(ctx.guild.id)}
        if trigger not in existing and len(existing) >= MAX_RESPONDERS:
            await ctx.send(f"That's {MAX_RESPONDERS} auto replies already.")
            return
        self.db.set_autoresponder(ctx.guild.id, trigger, response)
        self.replies.pop(ctx.guild.id, None)
        await ctx.send(f"When someone says **{discord.utils.escape_markdown(trigger)}**, I'll reply.",
                       allowed_mentions=discord.AllowedMentions.none())

    @autoresponder.command(name="remove", aliases=["delete"])
    @commands.has_permissions(manage_guild=True)
    async def autoresponder_remove(self, ctx, *, trigger: str):
        """Stop an auto reply."""
        gone = self.db.remove_autoresponder(ctx.guild.id, trigger.strip().lower())
        self.replies.pop(ctx.guild.id, None)
        await ctx.send("Removed." if gone else "There's no auto reply with that trigger.")

    @commands.group(name="autoreact", aliases=["autoreaction"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def autoreact(self, ctx):
        """Every auto reaction here."""
        rows = self.db.autoreacts_of(ctx.guild.id)
        grouped = {}
        for r in rows:
            grouped.setdefault(r["trigger"], []).append(r["emoji"])
        lines = [f"**{discord.utils.escape_markdown(t)}** → {' '.join(e)}"
                 for t, e in grouped.items()]
        await ctx.send(embed=discord.Embed(
            title="Auto reactions",
            description="\n".join(lines)[:4000] or
            f"None yet. `{ctx.prefix}autoreact add paper 📄`",
            colour=config.CARD_COLOUR))

    @autoreact.command(name="add")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(add_reactions=True)
    async def autoreact_add(self, ctx, trigger: str, *emojis: str):
        """`$autoreact add <word> <emoji>`: react whenever someone says it.
        Use quotes for a phrase."""
        trigger = trigger.strip().lower()
        if not emojis:
            await ctx.send(f"Give an emoji too: `{ctx.prefix}autoreact add paper 📄`")
            return
        if len(self.db.autoreacts_of(ctx.guild.id)) + len(emojis) > MAX_REACTS:
            await ctx.send(f"That's more than {MAX_REACTS} auto reactions.")
            return
        added = []
        for emoji in emojis[:5]:
            try:
                await ctx.message.add_reaction(emoji)
            except discord.HTTPException:
                continue
            self.db.add_autoreact(ctx.guild.id, trigger, emoji)
            added.append(emoji)
        self.replies.pop(ctx.guild.id, None)
        if not added:
            await ctx.send("I can't use those emojis. Use standard ones or ones from a"
                           " server I'm in.")
            return
        await ctx.send(f"I'll react {' '.join(added)} whenever someone says"
                       f" **{discord.utils.escape_markdown(trigger)}**.",
                       allowed_mentions=discord.AllowedMentions.none())

    @autoreact.command(name="remove", aliases=["delete"])
    @commands.has_permissions(manage_guild=True)
    async def autoreact_remove(self, ctx, *, trigger: str):
        """Stop reacting to a word."""
        gone = self.db.remove_autoreact(ctx.guild.id, trigger.strip().lower())
        self.replies.pop(ctx.guild.id, None)
        await ctx.send("Removed." if gone else "There are no auto reactions for that.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild or not message.content:
            return
        responders, reacts = self.replies_for(message.guild.id)
        if not (responders or reacts):
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return
        now = time.time()
        for row in responders:
            if matches(row["trigger"], message.content):
                key = (message.channel.id, row["trigger"])
                if now - self.last_reply.get(key, 0) < REPLY_COOLDOWN:
                    break
                self.last_reply[key] = now
                try:
                    await message.channel.send(
                        fill(row["response"], message.author, message.guild),
                        allowed_mentions=discord.AllowedMentions(users=[message.author]))
                except discord.HTTPException:
                    pass
                break           # one reply per message
        for row in reacts:
            if matches(row["trigger"], message.content):
                try:
                    await message.add_reaction(row["emoji"])
                except discord.HTTPException:
                    pass


async def setup(bot):
    await bot.add_cog(ServerSetup(bot))
