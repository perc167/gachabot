"""Voice: Join To Create rooms, and hours spent in voice.

Joining the Join To Create channel makes you your own voice channel and
moves you into it. You own it: lock it, hide it, rename it, let people in or
keep them out. It is deleted as soon as the last person leaves.

Separately, every minute anyone spends in any voice channel (bar the AFK
one) is counted, for `$vc stats`, a leaderboard, and roles handed out at so
many hours.

A session is saved when it starts, so a restart doesn't lose it. If the bot
was down while someone left, there is no telling when they did, so that
session is dropped rather than guessed at.
"""
import time
from typing import Optional

import discord
from discord.ext import commands

import config

RENAMES_PER_WINDOW = 2   # Discord's own limit on renaming a channel
RENAME_WINDOW = 600
CREATE_COOLDOWN = 5      # seconds between rooms for one person


def fmt_time(seconds: int) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes = rest // 60
    return f"{hours:,}h {minutes}m" if hours else f"{minutes}m"


def counts(channel, guild) -> bool:
    """Whether time in this channel counts. The AFK channel doesn't."""
    return channel is not None and channel != guild.afk_channel


class Voice(commands.Cog):
    # Read by the channel gate in bot.py and by tools/automod.py: $vc is used
    # from the voice channel's own chat, so it works in every channel.
    works_everywhere = True

    def __init__(self, bot):
        self.bot = bot
        self.renames = {}   # channel id -> times it was renamed
        self.created = {}   # member id -> when their last room was made

    @property
    def db(self):
        return self.bot.db

    async def cog_check(self, ctx):
        # Here rather than on $vc: a group's own checks don't run for its
        # subcommands, and every one of these needs a server.
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    def colour(self, guild_id: int) -> int:
        return self.db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR)

    # ------------------------------------------------------------ panel

    def panel(self, guild, prefix: str) -> discord.Embed:
        p = f"{prefix}vc"
        create = self.db.get_vc_setting(guild.id, "create_channel")
        where = f"<#{create}>" if create else "**Join To Create**"

        def block(lines):
            width = max(len(command) for command, _ in lines)
            return "```py\n" + "\n".join(
                f"{command.ljust(width)} # {note}" for command, note in lines
            ) + "\n```"

        embed = discord.Embed(
            title="Voice",
            description=f"> join {where} to make a channel, then use these"
                        " while in it:",
            colour=self.colour(guild.id))
        embed.add_field(name="\U0001f512 Room", inline=False, value=block([
            (f"{p} lock", "lock the call"),
            (f"{p} unlock", "open the call"),
            (f"{p} hide", "hide from list"),
            (f"{p} unhide", "show in list"),
            (f"{p} rename (name)", "set the name"),
            (f"{p} limit (0-99)", "user cap"),
        ]))
        embed.add_field(name="\U0001f465 People", inline=False, value=block([
            (f"{p} permit @user", "allow in"),
            (f"{p} reject @user", "remove access"),
            (f"{p} ban @user", "block join"),
            (f"{p} unban @user", "allow join"),
        ]))
        embed.add_field(name="\U0001f451 Owner", inline=False, value=block([
            (f"{p} claim", "take over"),
            (f"{p} transfer @user", "give owner"),
        ]))
        embed.add_field(name="\U0001f4ca Stats", inline=False, value=block([
            (f"{p} stats", "your vc time"),
            (f"{p} lb", "hour leaderboard"),
            (f"{p} @user", "their hours"),
            (f"{p} hours", "hour roles"),
        ]))
        if guild.me and guild.me.display_avatar:
            embed.set_thumbnail(url=guild.me.display_avatar.url)
        return embed

    # ------------------------------------------------------ rooms: events

    async def make_room(self, member):
        """Give someone their own channel and move them into it."""
        guild = member.guild
        mine = self.db.temp_vc_of(guild.id, member.id)
        if mine:
            existing = guild.get_channel(mine["channel_id"])
            if existing:
                await member.move_to(existing)
                return
            self.db.remove_temp_vc(mine["channel_id"])

        now = time.time()
        if now - self.created.get(member.id, 0) < CREATE_COOLDOWN:
            return
        self.created[member.id] = now

        join = guild.get_channel(self.db.get_vc_setting(guild.id, "create_channel"))
        category = join.category if join else None
        # Start from the category's permissions, so a room is hidden from
        # whoever the category is hidden from (the jailed, for one).
        overwrites = dict(category.overwrites) if category else {}
        overwrites[member] = discord.PermissionOverwrite(
            view_channel=True, connect=True, speak=True)
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True, connect=True, move_members=True,
            manage_channels=True)
        channel = await guild.create_voice_channel(
            f"{member.display_name}'s VC"[:100], category=category,
            overwrites=overwrites, reason=f"Join To Create: {member}")
        self.db.add_temp_vc(guild.id, channel.id, member.id)
        try:
            await member.move_to(channel)
        except discord.HTTPException:
            # They left before the room was ready.
            await self.remove_room(channel)

    async def remove_room(self, channel):
        self.db.remove_temp_vc(channel.id)
        self.renames.pop(channel.id, None)
        try:
            await channel.delete(reason="Join To Create: empty")
        except discord.HTTPException:
            pass

    async def award_hour_roles(self, member):
        """Hand out every hour role they've earned and don't have yet."""
        hours = self.db.vc_seconds(member.guild.id, member.id) // 3600
        due = [member.guild.get_role(row["role_id"])
               for row in self.db.hour_roles_of(member.guild.id)
               if row["hours"] <= hours]
        missing = [role for role in due if role and role not in member.roles]
        if missing:
            try:
                await member.add_roles(*missing, reason="Voice hours")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or before.channel == after.channel:
            return
        guild = member.guild

        was, now = counts(before.channel, guild), counts(after.channel, guild)
        if now and not was:
            self.db.start_vc_session(guild.id, member.id)
        elif was and not now:
            self.db.end_vc_session(guild.id, member.id)
            await self.award_hour_roles(member)

        # Empty rooms go first, so moving from your room into Join To
        # Create doesn't move you back into a room that's about to vanish.
        if before.channel and self.db.temp_vc(before.channel.id) \
                and not before.channel.members:
            await self.remove_room(before.channel)

        create = self.db.get_vc_setting(guild.id, "create_channel")
        if after.channel and after.channel.id == create:
            try:
                await self.make_room(member)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        self.db.remove_temp_vc(channel.id)

    @commands.Cog.listener()
    async def on_ready(self):
        """Square the books with who is actually in voice right now."""
        for guild in self.bot.guilds:
            in_voice = {m.id for c in guild.voice_channels if counts(c, guild)
                        for m in c.members if not m.bot}
            for row in self.db.vc_sessions_in(guild.id):
                if row["user_id"] not in in_voice:
                    self.db.drop_vc_session(guild.id, row["user_id"])
            for user_id in in_voice:
                self.db.start_vc_session(guild.id, user_id)
            for row in self.db.temp_vcs_in(guild.id):
                channel = guild.get_channel(row["channel_id"])
                if not channel:
                    self.db.remove_temp_vc(row["channel_id"])
                elif not channel.members:
                    await self.remove_room(channel)

    # --------------------------------------------------- rooms: commands

    async def room(self, ctx, owner_only: bool = True):
        """The temporary channel the author is in, if it's theirs to run."""
        voice = ctx.author.voice
        channel = voice.channel if voice else None
        record = self.db.temp_vc(channel.id) if channel else None
        if not record:
            await ctx.send("Join your voice channel first.")
            return None
        if owner_only and record["owner_id"] != ctx.author.id:
            await ctx.send(f"Only <@{record['owner_id']}> can do that. If"
                           f" they've left, use `{ctx.prefix}vc claim`.",
                           allowed_mentions=discord.AllowedMentions.none())
            return None
        return channel

    async def set_perms(self, channel, target, **changes):
        overwrite = channel.overwrites_for(target)
        for permission, value in changes.items():
            setattr(overwrite, permission, value)
        if overwrite.is_empty():
            await self.clear_perms(channel, target)
        else:
            await channel.set_permissions(target, overwrite=overwrite)

    async def clear_perms(self, channel, target):
        """Remove someone's overwrite. Removing one that isn't there is a 404."""
        if target in channel.overwrites:
            await channel.set_permissions(target, overwrite=None)

    @commands.group(name="vc", aliases=["voice", "voicemaster", "vm"],
                    invoke_without_command=True)
    @commands.guild_only()
    async def vc(self, ctx, member: Optional[discord.Member] = None):
        """Your own voice channel. On its own, shows every $vc command."""
        if member:
            await self.show_stats(ctx, member)
        else:
            await ctx.send(embed=self.panel(ctx.guild, ctx.prefix))

    @vc.command(name="lock")
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_lock(self, ctx):
        """Stop anyone else joining."""
        if channel := await self.room(ctx):
            await self.set_perms(channel, ctx.guild.default_role, connect=False)
            await ctx.send(f"\U0001f512 {channel.mention} is locked.")

    @vc.command(name="unlock")
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_unlock(self, ctx):
        """Let anyone join again."""
        if channel := await self.room(ctx):
            await self.set_perms(channel, ctx.guild.default_role, connect=None)
            await ctx.send(f"\U0001f513 {channel.mention} is open.")

    @vc.command(name="hide")
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_hide(self, ctx):
        """Hide the channel from the list."""
        if channel := await self.room(ctx):
            await self.set_perms(channel, ctx.guild.default_role, view_channel=False)
            await ctx.send(f"{channel.mention} is hidden.")

    @vc.command(name="unhide", aliases=["show"])
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_unhide(self, ctx):
        """Show the channel in the list again."""
        if channel := await self.room(ctx):
            await self.set_perms(channel, ctx.guild.default_role, view_channel=None)
            await ctx.send(f"{channel.mention} is visible.")

    @vc.command(name="rename", aliases=["name"])
    async def vc_rename(self, ctx, *, name: str):
        """Rename your channel. Discord allows twice every 10 minutes."""
        channel = await self.room(ctx)
        if not channel:
            return
        now = time.time()
        recent = [t for t in self.renames.get(channel.id, []) if now - t < RENAME_WINDOW]
        if len(recent) >= RENAMES_PER_WINDOW:
            wait = int(RENAME_WINDOW - (now - recent[0])) // 60 + 1
            await ctx.send(f"Discord only allows 2 renames every 10 minutes."
                           f" Try again in about {wait} minutes.")
            return
        await channel.edit(name=name[:100])
        self.renames[channel.id] = recent + [now]
        await ctx.send(f"Renamed to **{name[:100]}**.",
                       allowed_mentions=discord.AllowedMentions.none())

    @vc.command(name="limit", aliases=["cap"])
    async def vc_limit(self, ctx, number: int):
        """Cap how many people can join. 0 for no cap."""
        channel = await self.room(ctx)
        if not channel:
            return
        if not 0 <= number <= 99:
            await ctx.send("Pick a number from 0 (no cap) to 99.")
            return
        await channel.edit(user_limit=number)
        await ctx.send(f"Limit set to **{number}**." if number else "Limit removed.")

    @vc.command(name="permit", aliases=["allow"])
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_permit(self, ctx, member: discord.Member):
        """Let someone in, even when it's locked or hidden."""
        if channel := await self.room(ctx):
            await self.set_perms(channel, member, view_channel=True, connect=True)
            await ctx.send(f"**{member.display_name}** can join.",
                           allowed_mentions=discord.AllowedMentions.none())

    @vc.command(name="reject", aliases=["deny"])
    @commands.bot_has_permissions(manage_roles=True, move_members=True)
    async def vc_reject(self, ctx, member: discord.Member):
        """Take away someone's access and remove them if they're in."""
        channel = await self.room(ctx)
        if not channel:
            return
        if member == ctx.author:
            await ctx.send("You can't reject yourself.")
            return
        await self.clear_perms(channel, member)
        if member in channel.members:
            await member.move_to(None)
        await ctx.send(f"**{member.display_name}** no longer has access.",
                       allowed_mentions=discord.AllowedMentions.none())

    @vc.command(name="ban", aliases=["block"])
    @commands.bot_has_permissions(manage_roles=True, move_members=True)
    async def vc_ban(self, ctx, member: discord.Member):
        """Stop someone joining or seeing your channel at all."""
        channel = await self.room(ctx)
        if not channel:
            return
        if member == ctx.author or member == ctx.guild.me:
            await ctx.send("You can't ban that account.")
            return
        await self.set_perms(channel, member, view_channel=False, connect=False)
        if member in channel.members:
            await member.move_to(None)
        await ctx.send(f"**{member.display_name}** is banned from this channel.",
                       allowed_mentions=discord.AllowedMentions.none())

    @vc.command(name="unban", aliases=["unblock"])
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_unban(self, ctx, member: discord.Member):
        """Let someone you banned join again."""
        if channel := await self.room(ctx):
            await self.clear_perms(channel, member)
            await ctx.send(f"**{member.display_name}** can join again.",
                           allowed_mentions=discord.AllowedMentions.none())

    async def hand_over(self, channel, member):
        self.db.set_temp_vc_owner(channel.id, member.id)
        await self.set_perms(channel, member, view_channel=True, connect=True,
                             speak=True)

    @vc.command(name="claim")
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_claim(self, ctx):
        """Take over a channel whose owner has left."""
        channel = await self.room(ctx, owner_only=False)
        if not channel:
            return
        owner = self.db.temp_vc(channel.id)["owner_id"]
        if owner == ctx.author.id:
            await ctx.send("It's already yours.")
            return
        if any(m.id == owner for m in channel.members):
            await ctx.send(f"<@{owner}> is still here. Ask them to"
                           f" `{ctx.prefix}vc transfer` it to you.",
                           allowed_mentions=discord.AllowedMentions.none())
            return
        await self.hand_over(channel, ctx.author)
        await ctx.send(f"\U0001f451 {channel.mention} is yours now.")

    @vc.command(name="transfer", aliases=["give"])
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_transfer(self, ctx, member: discord.Member):
        """Give your channel to someone in it."""
        channel = await self.room(ctx)
        if not channel:
            return
        if member not in channel.members or member.bot or member == ctx.author:
            await ctx.send("They need to be in your channel.")
            return
        await self.hand_over(channel, member)
        await ctx.send(f"\U0001f451 {channel.mention} belongs to"
                       f" **{member.display_name}** now.",
                       allowed_mentions=discord.AllowedMentions.none())

    # --------------------------------------------------------------- stats

    async def show_stats(self, ctx, member):
        seconds = self.db.vc_seconds(ctx.guild.id, member.id)
        board = self.db.top_vc(ctx.guild.id, limit=1000)
        rank = next((i + 1 for i, row in enumerate(board)
                     if row["user_id"] == member.id), None)
        hours = seconds // 3600
        next_role = next((row for row in self.db.hour_roles_of(ctx.guild.id)
                          if row["hours"] > hours), None)
        lines = [f"**{fmt_time(seconds)}** in voice"]
        if rank:
            lines.append(f"#{rank} on the server")
        if next_role:
            lines.append(f"<@&{next_role['role_id']}> at {next_role['hours']}h")
        embed = discord.Embed(title=member.display_name,
                              description="\n".join(lines),
                              colour=self.colour(ctx.guild.id))
        embed.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=embed)
        if member == ctx.author:
            await self.award_hour_roles(member)

    @vc.command(name="stats", aliases=["time", "me"])
    async def vc_stats(self, ctx, member: discord.Member = None):
        """How long you've spent in voice."""
        await self.show_stats(ctx, member or ctx.author)

    @vc.command(name="lb", aliases=["leaderboard", "top"])
    async def vc_lb(self, ctx):
        """Who has spent the most time in voice."""
        rows = self.db.top_vc(ctx.guild.id, limit=10)
        medals = ("\U0001f947", "\U0001f948", "\U0001f949")
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1:>2}.`'} <@{row['user_id']}>"
            f" · **{fmt_time(row['seconds'])}**"
            for i, row in enumerate(rows)
        ]
        await ctx.send(embed=discord.Embed(
            title=f"Voice hours in {ctx.guild.name}",
            description="\n".join(lines) or "Nobody has been in voice yet.",
            colour=self.colour(ctx.guild.id)))

    @vc.group(name="hours", aliases=["roles"], invoke_without_command=True)
    async def vc_hours(self, ctx):
        """The roles you get for time in voice."""
        rows = self.db.hour_roles_of(ctx.guild.id)
        lines = [f"**{row['hours']}h** → <@&{row['role_id']}>" for row in rows]
        await ctx.send(embed=discord.Embed(
            title="Hour roles",
            description="\n".join(lines) or
            f"None yet. An admin can add one with"
            f" `{ctx.prefix}vc hours add 10 @role`.",
            colour=self.colour(ctx.guild.id)))

    @vc_hours.command(name="add", aliases=["set"])
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def vc_hours_add(self, ctx, hours: int, role: discord.Role):
        """Give a role at so many hours in voice."""
        if not 1 <= hours <= 100_000:
            await ctx.send("Pick a number of hours above 0.")
            return
        if role >= ctx.guild.me.top_role or role.managed:
            await ctx.send(f"I can't give **{role.name}**. It needs to be below"
                           " my role.", allowed_mentions=discord.AllowedMentions.none())
            return
        self.db.set_hour_role(ctx.guild.id, hours, role.id)
        await ctx.send(f"At **{hours}h** in voice, people get **{role.name}**.",
                       allowed_mentions=discord.AllowedMentions.none())

    @vc_hours.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def vc_hours_remove(self, ctx, hours: int):
        """Stop giving a role at so many hours. Nobody loses it."""
        gone = self.db.remove_hour_role(ctx.guild.id, hours)
        await ctx.send(f"No role at **{hours}h** any more." if gone
                       else f"There was no role at {hours}h.")

    # --------------------------------------------------------------- setup

    @vc.command(name="setup")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_channels=True, move_members=True,
                                  manage_roles=True)
    async def vc_setup(self, ctx, join: discord.VoiceChannel = None):
        """Make Join To Create. Or name an existing voice channel to use it."""
        guild = ctx.guild
        if join:
            category = join.category
            info = None
        else:
            category = await guild.create_category("Private VCs",
                                                   reason="Voice setup")
            info = await guild.create_text_channel("vc-info", category=category,
                                                   reason="Voice setup")
            await info.set_permissions(guild.default_role, send_messages=False)
            join = await guild.create_voice_channel("Join To Create",
                                                    category=category,
                                                    reason="Voice setup")
        self.db.set_vc_setting(guild.id, "create_channel", join.id)
        if info:
            await info.send(embed=self.panel(guild, ctx.prefix))
        await ctx.send(
            f"Voice is set up. Joining {join.mention} makes a channel"
            + (f" in **{category.name}**" if category else "") + "."
            + (f" The commands are pinned up in {info.mention}." if info else
               f" Post the commands anywhere with `{ctx.prefix}vc panel`."),
            allowed_mentions=discord.AllowedMentions.none())

    @vc.command(name="panel")
    @commands.has_permissions(manage_guild=True)
    async def vc_panel(self, ctx):
        """Post the list of $vc commands here."""
        await ctx.send(embed=self.panel(ctx.guild, ctx.prefix))

    @vc.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def vc_reset(self, ctx):
        """Turn Join To Create off. Hours and hour roles are kept."""
        self.db.clear_vc_settings(ctx.guild.id)
        await ctx.send("Join To Create is off. The channels are still there;"
                       " delete them yourself if you don't want them.")


async def setup(bot):
    await bot.add_cog(Voice(bot))
