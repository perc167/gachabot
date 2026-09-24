"""Server moderation: jail, mutes, warnings, kicks, bans and the history of it.

The same shape as bleed and greed, so staff who know those are at home. Every
action is saved as a numbered case, so `$history` and `$modhistory` answer
from one table.

Permissions follow the two staff ranks. Anything a trial mod does (jail,
timeout, the two mutes, warnings) needs Timeout Members. Kicking needs Kick
Members and banning needs Ban Members, which only full Mods should have.

Jails and mutes also give whoever issued them a staff point, so promotions
can be judged from `$points` without counting by hand.

These commands answer in every channel. A server that keeps the gacha to one
channel with `$channelallow` still needs `$jail` to work in general.
"""
import re
from datetime import timedelta
from typing import Optional, Union

import discord
from discord.ext import commands

import config
from views import Paginator

REASON_LIMIT = 400
MAX_TIMEOUT = 28 * 24 * 3600  # Discord will not go longer
DEFAULT_TIMEOUT = 10 * 60

UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

# (config key, role name, the overwrite that role gets in every channel)
PUNISHMENT_ROLES = (
    ("jail_role", "Jailed", {"view_channel": False}),
    ("imute_role", "Image Muted", {"attach_files": False, "embed_links": False}),
    ("rmute_role", "Reaction Muted",
     {"add_reactions": False, "use_external_emojis": False}),
)

# What each action is called in a history, and whether it earns a point.
ACTIONS = {
    "warn": ("Warned", False),
    "jail": ("Jailed", True),
    "unjail": ("Unjailed", False),
    "timeout": ("Timed out", True),
    "untimeout": ("Timeout removed", False),
    "imute": ("Image muted", True),
    "unimute": ("Image mute removed", False),
    "rmute": ("Reaction muted", True),
    "unrmute": ("Reaction mute removed", False),
    "kick": ("Kicked", False),
    "softban": ("Softbanned", False),
    "ban": ("Banned", False),
    "unban": ("Unbanned", False),
}


def parse_duration(text: str) -> int:
    """'10m', '1h30m', '2d' -> seconds. 0 when it isn't a duration at all."""
    text = (text or "").strip().lower()
    parts = re.findall(r"(\d+)\s*([smhdw])", text)
    if not parts or re.sub(r"(\d+)\s*([smhdw])", "", text).strip():
        return 0
    return sum(int(number) * UNITS[unit] for number, unit in parts)


def describe_duration(seconds: int) -> str:
    out = []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            out.append(f"{seconds // size}{unit}")
            seconds %= size
    return " ".join(out) or "0s"


def clean_reason(reason: str) -> str:
    return (reason or "").strip()[:REASON_LIMIT]


def audit(ctx, reason: str) -> str:
    """What the server's audit log shows, which names the staff member."""
    return f"{ctx.author} ({ctx.author.id}): {reason or 'no reason given'}"[:512]


def blocker(ctx, member: discord.Member) -> str:
    """Why this member can't be actioned by this person, or ''."""
    if member == ctx.author:
        return "You can't do that to yourself."
    if member == ctx.guild.me:
        return "I'm not doing that to myself."
    if member == ctx.guild.owner:
        return "That's the server owner."
    if (ctx.author != ctx.guild.owner
            and member.top_role >= ctx.author.top_role):
        return f"**{member.display_name}**'s top role is the same as or above yours."
    if member.top_role >= ctx.guild.me.top_role:
        return (f"**{member.display_name}**'s top role is above mine."
                " Move my role higher in Server Settings > Roles.")
    return ""


class ModTools(commands.Cog):
    # Read by the channel gate in bot.py and by tools/automod.py: staff
    # commands work everywhere and are never on the AutoMod block list.
    staff_cog = True

    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------ helpers

    def role(self, guild: discord.Guild, key: str) -> Optional[discord.Role]:
        return guild.get_role(self.bot.db.get_mod_config(guild.id, key))

    def colour(self, guild_id: int) -> int:
        return self.bot.db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR)

    async def record(self, ctx, user, action: str, reason: str,
                     duration: int = 0) -> int:
        """Save the case, give the point, post to the log. Returns the case id."""
        db = self.bot.db
        case = db.add_case(ctx.guild.id, user.id, ctx.author.id, action,
                           reason, duration)
        label, earns = ACTIONS[action]
        if earns:
            db.add_staff_point(ctx.guild.id, ctx.author.id, ctx.guild.me.id,
                               f"{label.lower()} {user} (case #{case})")

        channel = ctx.guild.get_channel(db.get_mod_config(ctx.guild.id, "log_channel"))
        if channel:
            embed = discord.Embed(
                title=f"{label} · case #{case}",
                colour=self.colour(ctx.guild.id),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Member", value=f"{user.mention}\n`{user.id}`")
            embed.add_field(name="By", value=ctx.author.mention)
            if duration:
                embed.add_field(name="For", value=describe_duration(duration))
            embed.add_field(name="Reason", value=reason or "No reason given",
                            inline=False)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
        return case

    async def tell(self, user, action: str, guild: discord.Guild, reason: str,
                   duration: int = 0):
        """DM the member what happened. Closed DMs are their business."""
        text = f"You were **{ACTIONS[action][0].lower()}** in **{guild.name}**"
        if duration:
            text += f" for {describe_duration(duration)}"
        text += f".\nReason: {reason or 'no reason given'}"
        try:
            await user.send(text)
        except (discord.HTTPException, AttributeError):
            pass

    async def done(self, ctx, user, action: str, case: int, extra: str = ""):
        await ctx.send(
            f"**{user}** {ACTIONS[action][0].lower()}{extra}. (case #{case})",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    def overwrite_for(self, channel, role, changes: dict):
        overwrite = channel.overwrites_for(role)
        for permission, value in changes.items():
            setattr(overwrite, permission, value)
        return overwrite

    async def lock_out(self, channel, guild: discord.Guild):
        """Give one channel the punishment-role overwrites, in one edit."""
        jail_channel = self.bot.db.get_mod_config(guild.id, "jail_channel")
        overwrites = dict(channel.overwrites)
        for key, _name, changes in PUNISHMENT_ROLES:
            role = self.role(guild, key)
            if not role:
                continue
            if key == "jail_role" and channel.id == jail_channel:
                # Said outright rather than skipped: this channel can be
                # created and caught by on_guild_channel_create before
                # setup has recorded which one the jail is.
                changes = {"view_channel": True, "send_messages": True}
            overwrites[role] = self.overwrite_for(channel, role, changes)
        if overwrites != channel.overwrites:
            await channel.edit(overwrites=overwrites, reason="Moderation setup")

    # -------------------------------------------------------------- setup

    @commands.command(name="setupmod", aliases=["modsetup"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def setupmod(self, ctx, *staff: discord.Role):
        """Make the jail, the mute roles and the mod log. Name your staff roles."""
        guild, db = ctx.guild, self.bot.db
        status = await ctx.send("Setting up moderation, this can take a minute…")

        for key, name, _changes in PUNISHMENT_ROLES:
            if not self.role(guild, key):
                role = await guild.create_role(name=name, reason="Moderation setup")
                db.set_mod_config(guild.id, key, role.id)

        jailed = self.role(guild, "jail_role")
        staff_can = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True)
        hidden = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                  guild.me: staff_can}
        hidden.update({role: staff_can for role in staff})

        jail = guild.get_channel(db.get_mod_config(guild.id, "jail_channel"))
        if not jail:
            jail = await guild.create_text_channel(
                "jail", reason="Moderation setup",
                overwrites={**hidden, jailed: staff_can})
            db.set_mod_config(guild.id, "jail_channel", jail.id)
        logs = guild.get_channel(db.get_mod_config(guild.id, "log_channel"))
        if not logs:
            logs = await guild.create_text_channel(
                "mod-logs", reason="Moderation setup", overwrites=hidden)
            db.set_mod_config(guild.id, "log_channel", logs.id)
        for role in staff:
            await jail.set_permissions(role, overwrite=staff_can)
            await logs.set_permissions(role, overwrite=staff_can)

        failed = 0
        for channel in guild.channels:
            try:
                await self.lock_out(channel, guild)
            except discord.HTTPException:
                failed += 1

        lines = [
            "**Moderation is set up.**",
            f"Jail: {jail.mention} · Logs: {logs.mention}",
            f"Roles: {', '.join(self.role(guild, k).mention for k, *_ in PUNISHMENT_ROLES)}",
        ]
        if staff:
            lines.append(f"Staff who can see both: {', '.join(r.mention for r in staff)}")
        else:
            lines.append("No staff roles given, so only admins can see the jail."
                         " Run it again with your staff roles, e.g."
                         f" `{ctx.prefix}setupmod @Mod @Trial Mod`.")
        if failed:
            lines.append(f"I couldn't update **{failed}** channels. Check my"
                         " permissions there and run it again.")
        await status.edit(content="\n".join(lines),
                          allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="modlog", aliases=["setmodlog"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def modlog(self, ctx, channel: discord.TextChannel):
        """Choose the channel every mod action is posted to."""
        self.bot.db.set_mod_config(ctx.guild.id, "log_channel", channel.id)
        await ctx.send(f"Mod actions will be posted in {channel.mention}.")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """New channels get the punishment overwrites too."""
        if self.role(channel.guild, "jail_role"):
            try:
                await self.lock_out(channel, channel.guild)
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Leaving and rejoining doesn't get you out of jail."""
        if not self.bot.db.jail_record(member.guild.id, member.id):
            return
        role = self.role(member.guild, "jail_role")
        if role:
            try:
                await member.add_roles(role, reason="Rejoined while jailed")
            except discord.HTTPException:
                pass

    # --------------------------------------------------------------- jail

    @commands.command(name="jail")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def jail(self, ctx, member: discord.Member, *, reason: str = ""):
        """Lock someone in the jail channel so you can talk it out."""
        jailed = self.role(ctx.guild, "jail_role")
        if not jailed:
            await ctx.send(f"Run `{ctx.prefix}setupmod` first to make the jail.")
            return
        if problem := blocker(ctx, member):
            await ctx.send(problem)
            return
        if jailed in member.roles:
            await ctx.send(f"**{member.display_name}** is already jailed.")
            return
        reason = clean_reason(reason)

        top = ctx.guild.me.top_role
        # Roles the bot can't remove (boosters, other bots' roles, anything
        # above it) stay on; everything else is saved and taken off.
        taken = [r for r in member.roles
                 if not r.is_default() and not r.managed and r < top]
        kept = [r for r in member.roles if r not in taken and not r.is_default()]
        self.bot.db.save_jail(ctx.guild.id, member.id, [r.id for r in taken])
        await member.edit(roles=kept + [jailed], reason=audit(ctx, reason))

        case = await self.record(ctx, member, "jail", reason)
        await self.done(ctx, member, "jail", case)
        cell = ctx.guild.get_channel(
            self.bot.db.get_mod_config(ctx.guild.id, "jail_channel"))
        if cell:
            await cell.send(
                f"{member.mention}, you've been jailed"
                + (f" for: {reason}" if reason else "")
                + f".\nA member of staff will talk to you here. {ctx.author.mention}",
            )

    @commands.command(name="unjail")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unjail(self, ctx, member: discord.Member, *, reason: str = ""):
        """Let someone out and give them their roles back."""
        jailed = self.role(ctx.guild, "jail_role")
        if not (jailed and jailed in member.roles) and not self.bot.db.jail_record(
                ctx.guild.id, member.id):
            await ctx.send(f"**{member.display_name}** isn't jailed.")
            return
        reason = clean_reason(reason)
        saved = self.bot.db.release_jail(ctx.guild.id, member.id)
        top = ctx.guild.me.top_role
        back = [role for role in (ctx.guild.get_role(r) for r in saved)
                if role and not role.managed and role < top]
        roles = [r for r in member.roles if r != jailed and not r.is_default()]
        await member.edit(roles=list({r.id: r for r in roles + back}.values()),
                          reason=audit(ctx, reason))
        case = await self.record(ctx, member, "unjail", reason)
        await self.done(ctx, member, "unjail", case)

    # ------------------------------------------------------ timeouts, mutes

    @commands.command(name="timeout", aliases=["to"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout(self, ctx, member: discord.Member, duration: str = "",
                      *, reason: str = ""):
        """Stop someone typing, talking and reacting for a while. e.g. 10m, 1h, 1d"""
        seconds = parse_duration(duration)
        if not seconds:
            # No duration given, so that word was the start of the reason.
            reason = f"{duration} {reason}".strip()
            seconds = DEFAULT_TIMEOUT
        if seconds > MAX_TIMEOUT:
            await ctx.send("Discord only allows timeouts of up to 28 days.")
            return
        if problem := blocker(ctx, member):
            await ctx.send(problem)
            return
        reason = clean_reason(reason)
        await member.timeout(timedelta(seconds=seconds), reason=audit(ctx, reason))
        case = await self.record(ctx, member, "timeout", reason, seconds)
        await self.tell(member, "timeout", ctx.guild, reason, seconds)
        await self.done(ctx, member, "timeout", case,
                        f" for {describe_duration(seconds)}")

    @commands.command(name="untimeout", aliases=["uto"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout(self, ctx, member: discord.Member, *, reason: str = ""):
        """End someone's timeout early."""
        if not member.is_timed_out():
            await ctx.send(f"**{member.display_name}** isn't timed out.")
            return
        reason = clean_reason(reason)
        await member.timeout(None, reason=audit(ctx, reason))
        case = await self.record(ctx, member, "untimeout", reason)
        await self.done(ctx, member, "untimeout", case)

    async def toggle_role(self, ctx, member, key: str, action: str,
                          adding: bool, reason: str):
        role = self.role(ctx.guild, key)
        if not role:
            await ctx.send(f"Run `{ctx.prefix}setupmod` first to make the mute roles.")
            return
        if problem := blocker(ctx, member):
            await ctx.send(problem)
            return
        if adding == (role in member.roles):
            await ctx.send(f"**{member.display_name}** "
                           + ("already has" if adding else "doesn't have")
                           + f" **{role.name}**.")
            return
        reason = clean_reason(reason)
        change = member.add_roles if adding else member.remove_roles
        await change(role, reason=audit(ctx, reason))
        case = await self.record(ctx, member, action, reason)
        await self.done(ctx, member, action, case)

    @commands.command(name="imute", aliases=["imagemute"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def imute(self, ctx, member: discord.Member, *, reason: str = ""):
        """Stop someone posting images and files. They can still chat."""
        await self.toggle_role(ctx, member, "imute_role", "imute", True, reason)

    @commands.command(name="unimute", aliases=["unimagemute"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unimute(self, ctx, member: discord.Member, *, reason: str = ""):
        """Let someone post images again."""
        await self.toggle_role(ctx, member, "imute_role", "unimute", False, reason)

    @commands.command(name="rmute", aliases=["reactionmute"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def rmute(self, ctx, member: discord.Member, *, reason: str = ""):
        """Stop someone reacting or using emoji from other servers."""
        await self.toggle_role(ctx, member, "rmute_role", "rmute", True, reason)

    @commands.command(name="unrmute", aliases=["unreactionmute"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unrmute(self, ctx, member: discord.Member, *, reason: str = ""):
        """Let someone react again."""
        await self.toggle_role(ctx, member, "rmute_role", "unrmute", False, reason)

    # ----------------------------------------------------------- warnings

    @commands.group(name="warn", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx, member: discord.Member, *, reason: str = ""):
        """Give someone a warning. It goes on their record."""
        if member.bot or member == ctx.author:
            await ctx.send("You can't warn that account.")
            return
        reason = clean_reason(reason)
        case = await self.record(ctx, member, "warn", reason)
        await self.tell(member, "warn", ctx.guild, reason)
        count = len(self.bot.db.cases_for(ctx.guild.id, member.id, "warn"))
        await self.done(ctx, member, "warn", case,
                        f", that's warning **{count}**")

    @warn.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def warn_list(self, ctx, member: discord.Member):
        """Every warning someone has."""
        await self.show_cases(ctx, member, "warn")

    @warn.command(name="remove")
    @commands.has_permissions(moderate_members=True)
    async def warn_remove(self, ctx, member: discord.Member, case_id: int):
        """Remove one warning by its case number."""
        row = self.bot.db.delete_case(ctx.guild.id, case_id, "warn")
        if not row or row["user_id"] != member.id:
            await ctx.send(f"**{member.display_name}** has no warning #{case_id}.")
            return
        await ctx.send(f"Removed warning #{case_id} from **{member.display_name}**.")

    @warn.command(name="clear")
    @commands.has_permissions(moderate_members=True)
    async def warn_clear(self, ctx, member: discord.Member):
        """Remove all of someone's warnings."""
        gone = self.bot.db.clear_cases(ctx.guild.id, member.id, "warn")
        await ctx.send(f"Cleared **{gone}** warnings from **{member.display_name}**.")

    @commands.command(name="warnings", aliases=["warns"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warnings(self, ctx, member: discord.Member):
        """Every warning someone has."""
        await self.show_cases(ctx, member, "warn")

    # ------------------------------------------------------ kicks and bans

    @commands.command(name="kick")
    @commands.guild_only()
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = ""):
        """Remove someone. They can rejoin with an invite."""
        if problem := blocker(ctx, member):
            await ctx.send(problem)
            return
        reason = clean_reason(reason)
        await self.tell(member, "kick", ctx.guild, reason)
        await member.kick(reason=audit(ctx, reason))
        self.bot.db.release_jail(ctx.guild.id, member.id)
        case = await self.record(ctx, member, "kick", reason)
        await self.done(ctx, member, "kick", case)

    async def banish(self, ctx, user, reason: str, action: str, wipe_days: int):
        member = ctx.guild.get_member(user.id)
        if member and (problem := blocker(ctx, member)):
            await ctx.send(problem)
            return
        reason = clean_reason(reason)
        if member:
            await self.tell(member, action, ctx.guild, reason)
        await ctx.guild.ban(user, reason=audit(ctx, reason),
                            delete_message_seconds=wipe_days * 86400)
        if action == "softban":
            await ctx.guild.unban(user, reason=audit(ctx, "softban"))
        self.bot.db.release_jail(ctx.guild.id, user.id)
        case = await self.record(ctx, user, action, reason)
        await self.done(ctx, user, action, case)

    @commands.command(name="ban")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban(self, ctx, user: Union[discord.Member, discord.User], *,
                  reason: str = ""):
        """Ban someone, even if they've already left. Use their ID then."""
        await self.banish(ctx, user, reason, "ban", 0)

    @commands.command(name="softban")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban(self, ctx, user: Union[discord.Member, discord.User], *,
                      reason: str = ""):
        """Kick someone and delete their last week of messages."""
        await self.banish(ctx, user, reason, "softban", 7)

    @commands.command(name="unban")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason: str = ""):
        """Lift a ban. Use their user ID."""
        reason = clean_reason(reason)
        try:
            await ctx.guild.unban(user, reason=audit(ctx, reason))
        except discord.NotFound:
            await ctx.send(f"**{user}** isn't banned.")
            return
        case = await self.record(ctx, user, "unban", reason)
        await self.done(ctx, user, "unban", case)

    # ------------------------------------------------------------ channels

    @commands.command(name="purge", aliases=["clear"])
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx, member: Optional[discord.Member] = None,
                    amount: int = 10):
        """Delete recent messages, or just one person's. Pinned ones stay."""
        if not 1 <= amount <= 500:
            await ctx.send("Pick between 1 and 500 messages.")
            return
        matched = 0

        def wanted(message):
            nonlocal matched
            if message.pinned or matched >= amount:
                return False
            if member and message.author.id != member.id:
                return False
            matched += 1
            return True

        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        gone = await ctx.channel.purge(limit=500 if member else amount,
                                       check=wanted)
        await ctx.send(
            f"Deleted **{len(gone)}** messages"
            + (f" from **{member.display_name}**" if member else "") + ".",
            delete_after=5, allowed_mentions=discord.AllowedMentions.none())

    async def set_lock(self, ctx, channel, locked: bool, reason: str):
        channel = channel or ctx.channel
        everyone = ctx.guild.default_role
        await channel.set_permissions(
            everyone,
            overwrite=self.overwrite_for(channel, everyone, {
                "send_messages": False if locked else None,
                "send_messages_in_threads": False if locked else None,
            }),
            reason=audit(ctx, clean_reason(reason)))
        await ctx.send(f"{channel.mention} is "
                       + ("locked." if locked else "unlocked."))

    @commands.command(name="lock", aliases=["lockdown"])
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def lock(self, ctx, channel: Optional[discord.TextChannel] = None, *,
                   reason: str = ""):
        """Stop everyone typing in a channel. This one, if you don't name one."""
        await self.set_lock(ctx, channel, True, reason)

    @commands.command(name="unlock", aliases=["unlockdown"])
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def unlock(self, ctx, channel: Optional[discord.TextChannel] = None, *,
                     reason: str = ""):
        """Let everyone type in a channel again."""
        await self.set_lock(ctx, channel, False, reason)

    @commands.command(name="nick", aliases=["nickname", "setnick"])
    @commands.guild_only()
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: discord.Member, *, name: str = None):
        """Change someone's nickname. Leave the name out to reset it."""
        if member != ctx.author and (problem := blocker(ctx, member)):
            await ctx.send(problem)
            return
        await member.edit(nick=name[:32] if name else None,
                          reason=audit(ctx, "nickname"))
        await ctx.send(
            f"Nickname {'set to **' + name[:32] + '**' if name else 'reset'}.",
            allowed_mentions=discord.AllowedMentions.none())

    # ------------------------------------------------------------- history

    def case_line(self, row, show_member: bool) -> str:
        label = ACTIONS.get(row["action"], (row["action"], False))[0]
        who = (f" <@{row['user_id']}>" if show_member
               else f" by <@{row['mod_id']}>")
        line = f"`#{row['id']}` **{label}**{who} · <t:{row['created_at']}:d>"
        if row["duration"]:
            line += f" · {describe_duration(row['duration'])}"
        if row["reason"]:
            line += f"\n　{row['reason'][:150]}"
        return line

    async def paged(self, ctx, title: str, header: str, lines: list):
        per_page = 8
        pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
        embeds = []
        for number, page in enumerate(pages or [[]]):
            embed = discord.Embed(
                title=title,
                description="\n".join(([header, ""] if header else []) + page)
                            or "Nothing on record.",
                colour=self.colour(ctx.guild.id))
            if len(pages) > 1:
                embed.set_footer(text=f"Page {number + 1}/{len(pages)}")
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    async def show_cases(self, ctx, member, action: str = None):
        rows = self.bot.db.cases_for(ctx.guild.id, member.id, action)
        noun = "warnings" if action == "warn" else "cases"
        await self.paged(ctx, f"{member}: {len(rows)} {noun}", "",
                         [self.case_line(row, False) for row in rows])

    @commands.command(name="history", aliases=["cases", "record"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def history(self, ctx, user: Union[discord.Member, discord.User]):
        """Everything staff have done to someone."""
        await self.show_cases(ctx, user)

    @commands.command(name="modhistory", aliases=["modstats", "staffhistory"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def modhistory(self, ctx, moderator: discord.Member = None):
        """Everything a staff member has done, with a count of each."""
        moderator = moderator or ctx.author
        rows = self.bot.db.cases_by(ctx.guild.id, moderator.id)
        counts = {}
        for row in rows:
            counts[row["action"]] = counts.get(row["action"], 0) + 1
        header = " · ".join(
            f"{ACTIONS[a][0]} **{n}**" for a, n in counts.items() if a in ACTIONS)
        await self.paged(ctx, f"{moderator.display_name}: {len(rows)} actions",
                         header, [self.case_line(row, True) for row in rows])


async def setup(bot):
    await bot.add_cog(ModTools(bot))
