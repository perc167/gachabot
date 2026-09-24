"""Server moderation: jail, mutes, warnings, kicks, bans and the history of it.

The same shape as bleed and greed, so staff who know those are at home. Every
action is saved as a numbered case, so `$history` and `$modhistory` answer
from one table.

Permissions follow the two staff ranks. Anything a trial mod does (jail,
timeout, the two mutes, warnings) needs Timeout Members. Kicking needs Kick
Members and banning needs Ban Members, which only full Mods should have.

Jails and mutes also give whoever issued them a staff point, so promotions
can be judged from `$points` without counting by hand. Anything the bot does
by itself, like a warn punishment, earns nobody a point.

These commands answer in every channel. A server that keeps the gacha to one
channel with `$channelallow` still needs `$jail` to work in general.

The settings side (staff roles, warn punishments, custom messages) lives in
cogs/modsettings.py.
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
    "hardban": ("Hardbanned", False),
    "unban": ("Unbanned", False),
    "unhardban": ("Hardban lifted", False),
    "strip": ("Stripped", False),
    "staffstrip": ("Staff stripped", False),
}

# The member hears about these by DM unless the server wrote its own.
DM_BY_DEFAULT = {"warn", "timeout", "kick", "softban", "ban", "hardban"}

# A role with any of these is what $strip takes away.
DANGEROUS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels",
    "manage_webhooks", "manage_expressions", "ban_members", "kick_members",
    "moderate_members", "manage_messages", "mention_everyone",
)

# The words an invoke message can use, and what each becomes.
VARIABLES = (
    "{user}", "{user.mention}", "{user.name}", "{user.id}", "{moderator}",
    "{moderator.mention}", "{reason}", "{duration}", "{case}", "{guild}",
)


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


def audit(moderator, reason: str) -> str:
    """What the server's audit log shows, which names the staff member."""
    return f"{moderator} ({moderator.id}): {reason or 'no reason given'}"[:512]


def render(template: str, guild, user, moderator, reason: str = "",
           duration: int = 0, case: int = 0) -> str:
    """Fill in an invoke message's {variables}."""
    values = {
        "{user}": str(user), "{user.mention}": user.mention,
        "{user.name}": getattr(user, "display_name", user.name),
        "{user.id}": str(user.id), "{moderator}": str(moderator),
        "{moderator.mention}": moderator.mention,
        "{reason}": reason or "no reason given",
        "{duration}": describe_duration(duration) if duration else "",
        "{case}": str(case), "{guild}": guild.name,
    }
    for key, value in values.items():
        template = template.replace(key, value)
    return template[:2000]


def outranks(guild, moderator, member) -> str:
    """Why this moderator can't act on this member, or ''."""
    if member == moderator:
        return "You can't do that to yourself."
    if member == guild.me:
        return "I'm not doing that to myself."
    if member == guild.owner:
        return "That's the server owner."
    if moderator != guild.owner and moderator != guild.me \
            and member.top_role >= moderator.top_role:
        return f"**{member.display_name}**'s top role is the same as or above yours."
    if member.top_role >= guild.me.top_role:
        return (f"**{member.display_name}**'s top role is above mine."
                " Move my role higher in Server Settings > Roles.")
    return ""


def blocker(ctx, member) -> str:
    return outranks(ctx.guild, ctx.author, member)


class ModTools(commands.Cog):
    # Read by the channel gate in bot.py and by tools/automod.py: these
    # commands work everywhere and are never on the AutoMod block list.
    works_everywhere = True

    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------ helpers

    @property
    def db(self):
        return self.bot.db

    def role(self, guild: discord.Guild, key: str) -> Optional[discord.Role]:
        return guild.get_role(self.db.get_mod_config(guild.id, key))

    def colour(self, guild_id: int) -> int:
        return self.db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR)

    async def record(self, guild, user, moderator, action: str, reason: str,
                     duration: int = 0) -> int:
        """Save the case, give the point, post to the log. Returns the case id."""
        case = self.db.add_case(guild.id, user.id, moderator.id, action,
                                reason, duration)
        label, earns = ACTIONS[action]
        if earns and moderator != guild.me:
            self.db.add_staff_point(guild.id, moderator.id, guild.me.id,
                                    f"{label.lower()} {user} (case #{case})")

        channel = guild.get_channel(self.db.get_mod_config(guild.id, "log_channel"))
        if channel:
            embed = discord.Embed(
                title=f"{label} · case #{case}",
                colour=self.colour(guild.id),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="Member", value=f"{user.mention}\n`{user.id}`")
            embed.add_field(name="By", value=moderator.mention)
            if duration:
                embed.add_field(name="For", value=describe_duration(duration))
            embed.add_field(name="Reason", value=reason or "No reason given",
                            inline=False)
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
        return case

    async def tell(self, guild, user, moderator, action: str, reason: str,
                   duration: int = 0, case: int = 0):
        """DM the member what happened. Closed DMs are their business."""
        template = self.db.invoke_of(guild.id, action, "dm")
        if template:
            text = render(template, guild, user, moderator, reason, duration, case)
        elif action in DM_BY_DEFAULT:
            text = f"You were **{ACTIONS[action][0].lower()}** in **{guild.name}**"
            if duration:
                text += f" for {describe_duration(duration)}"
            text += f".\nReason: {reason or 'no reason given'}"
        else:
            return
        try:
            await user.send(text)
        except (discord.HTTPException, AttributeError):
            pass

    async def done(self, ctx, user, action: str, case: int, extra: str = "",
                   reason: str = "", duration: int = 0):
        """Say it worked, in the server's own words if it wrote some."""
        template = self.db.invoke_of(ctx.guild.id, action, "message")
        if template:
            await ctx.send(render(template, ctx.guild, user, ctx.author,
                                  reason, duration, case))
            return
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
        jail_channel = self.db.get_mod_config(guild.id, "jail_channel")
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

    async def paged(self, ctx, title: str, header: str, lines: list,
                    per_page: int = 8):
        pages = [lines[i:i + per_page] for i in range(0, len(lines), per_page)]
        embeds = []
        for number, page in enumerate(pages or [[]]):
            embed = discord.Embed(
                title=title,
                description="\n".join(([header, ""] if header else []) + page)
                            or "Nothing here.",
                colour=self.colour(ctx.guild.id))
            if len(pages) > 1:
                embed.set_footer(text=f"Page {number + 1}/{len(pages)}")
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    # The actions themselves, apart from the commands, so a warn punishment
    # can jail or ban someone exactly the way a moderator would.

    async def apply_jail(self, guild, member, moderator, reason) -> int:
        jailed = self.role(guild, "jail_role")
        top = guild.me.top_role
        # Roles the bot can't remove (boosters, other bots' roles, anything
        # above it) stay on; everything else is saved and taken off.
        taken = [r for r in member.roles
                 if not r.is_default() and not r.managed and r < top]
        kept = [r for r in member.roles if r not in taken and not r.is_default()]
        self.db.save_jail(guild.id, member.id, [r.id for r in taken])
        await member.edit(roles=kept + [jailed], reason=audit(moderator, reason))
        case = await self.record(guild, member, moderator, "jail", reason)
        await self.tell(guild, member, moderator, "jail", reason, case=case)
        cell = guild.get_channel(self.db.get_mod_config(guild.id, "jail_channel"))
        if cell:
            await cell.send(
                f"{member.mention}, you've been jailed"
                + (f" for: {reason}" if reason else "")
                + f".\nA member of staff will talk to you here. {moderator.mention}",
            )
        return case

    async def apply_timeout(self, guild, member, moderator, seconds, reason) -> int:
        await member.timeout(timedelta(seconds=seconds),
                             reason=audit(moderator, reason))
        case = await self.record(guild, member, moderator, "timeout", reason,
                                 seconds)
        await self.tell(guild, member, moderator, "timeout", reason, seconds, case)
        return case

    async def apply_kick(self, guild, member, moderator, reason) -> int:
        await self.tell(guild, member, moderator, "kick", reason)
        await member.kick(reason=audit(moderator, reason))
        self.db.release_jail(guild.id, member.id)
        return await self.record(guild, member, moderator, "kick", reason)

    async def apply_ban(self, guild, user, moderator, reason,
                        action: str = "ban", wipe_days: int = 0) -> int:
        if guild.get_member(user.id):
            await self.tell(guild, user, moderator, action, reason)
        await guild.ban(user, reason=audit(moderator, reason),
                        delete_message_seconds=wipe_days * 86400)
        if action == "softban":
            await guild.unban(user, reason=audit(moderator, "softban"))
        if action == "hardban":
            self.db.add_hardban(guild.id, user.id, moderator.id, reason)
        self.db.release_jail(guild.id, user.id)
        return await self.record(guild, user, moderator, action, reason)

    # -------------------------------------------------------------- setup

    @commands.group(name="setupmod", aliases=["modsetup"],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def setupmod(self, ctx, *staff: discord.Role):
        """Make the jail, the mute roles and the mod log. Name your staff roles."""
        guild, db = ctx.guild, self.db
        status = await ctx.send("Setting up moderation, this can take a minute…")
        for role in staff:
            db.add_staff_role(guild.id, role.id)
        staff = [r for r in map(guild.get_role, db.staff_roles_of(guild.id)) if r]

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
        await self.show_staff_the_rooms(guild)

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

    async def show_staff_the_rooms(self, guild):
        """Let every staff role into the jail and the mod log."""
        staff_can = discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True)
        for key in ("jail_channel", "log_channel"):
            channel = guild.get_channel(self.db.get_mod_config(guild.id, key))
            if not channel:
                continue
            for role_id in self.db.staff_roles_of(guild.id):
                role = guild.get_role(role_id)
                if role and channel.overwrites_for(role) != staff_can:
                    await channel.set_permissions(role, overwrite=staff_can)

    @setupmod.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def setupmod_reset(self, ctx):
        """Forget the jail, roles and log so $setupmod starts fresh."""
        gone = self.db.clear_mod_config(ctx.guild.id)
        await ctx.send(
            f"Forgot **{gone}** moderation settings. The roles and channels"
            " are still there. Delete them yourself if you don't want them,"
            f" then run `{ctx.prefix}setupmod` again.")

    @commands.command(name="modlog", aliases=["setmodlog"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def modlog(self, ctx, channel: discord.TextChannel):
        """Choose the channel every mod action is posted to."""
        self.db.set_mod_config(ctx.guild.id, "log_channel", channel.id)
        await ctx.send(f"Mod actions will be posted in {channel.mention}.")

    # ---------------------------------------------------------- listeners

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
        """Leaving and rejoining doesn't get you out of jail, or a nickname."""
        guild = member.guild
        try:
            if self.db.jail_record(guild.id, member.id):
                role = self.role(guild, "jail_role")
                if role:
                    await member.add_roles(role, reason="Rejoined while jailed")
            nick = self.db.forced_nick_of(guild.id, member.id)
            if nick:
                await member.edit(nick=nick, reason="Forced nickname")
        except discord.HTTPException:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Put a forced nickname straight back."""
        if before.nick == after.nick:
            return
        nick = self.db.forced_nick_of(after.guild.id, after.id)
        if nick and after.nick != nick:
            try:
                await after.edit(nick=nick, reason="Forced nickname")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        """A hardban comes back unless it was lifted with $hardban remove."""
        if self.db.hardban_of(guild.id, user.id):
            try:
                await guild.ban(user, reason="Hardbanned: lift it with"
                                             " $hardban remove first")
            except discord.HTTPException:
                pass

    # --------------------------------------------------------------- jail

    @commands.group(name="jail", invoke_without_command=True)
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
        case = await self.apply_jail(ctx.guild, member, ctx.author, reason)
        await self.done(ctx, member, "jail", case, reason=reason)

    @jail.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def jail_list(self, ctx):
        """Everyone in jail right now."""
        rows = self.db.jailed_in(ctx.guild.id)
        await self.paged(ctx, f"In jail: {len(rows)}", "", [
            f"<@{row['user_id']}> · since <t:{row['jailed_at']}:R>"
            for row in rows], per_page=15)

    @commands.command(name="unjail")
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def unjail(self, ctx, member: discord.Member, *, reason: str = ""):
        """Let someone out and give them their roles back."""
        jailed = self.role(ctx.guild, "jail_role")
        if not (jailed and jailed in member.roles) and not self.db.jail_record(
                ctx.guild.id, member.id):
            await ctx.send(f"**{member.display_name}** isn't jailed.")
            return
        reason = clean_reason(reason)
        saved = self.db.release_jail(ctx.guild.id, member.id)
        top = ctx.guild.me.top_role
        back = [role for role in (ctx.guild.get_role(r) for r in saved)
                if role and not role.managed and role < top]
        roles = [r for r in member.roles if r != jailed and not r.is_default()]
        await member.edit(roles=list({r.id: r for r in roles + back}.values()),
                          reason=audit(ctx.author, reason))
        case = await self.record(ctx.guild, member, ctx.author, "unjail", reason)
        await self.tell(ctx.guild, member, ctx.author, "unjail", reason, case=case)
        await self.done(ctx, member, "unjail", case, reason=reason)

    # ------------------------------------------------------ timeouts, mutes

    @commands.group(name="timeout", aliases=["to"], invoke_without_command=True)
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
        case = await self.apply_timeout(ctx.guild, member, ctx.author, seconds,
                                        reason)
        await self.done(ctx, member, "timeout", case,
                        f" for {describe_duration(seconds)}", reason, seconds)

    @timeout.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def timeout_list(self, ctx):
        """Everyone timed out right now."""
        out = [m for m in ctx.guild.members if m.is_timed_out()]
        await self.paged(ctx, f"Timed out: {len(out)}", "", [
            f"{m.mention} · until <t:{int(m.timed_out_until.timestamp())}:R>"
            for m in out], per_page=15)

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
        await member.timeout(None, reason=audit(ctx.author, reason))
        case = await self.record(ctx.guild, member, ctx.author, "untimeout", reason)
        await self.done(ctx, member, "untimeout", case, reason=reason)

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
        await change(role, reason=audit(ctx.author, reason))
        case = await self.record(ctx.guild, member, ctx.author, action, reason)
        await self.tell(ctx.guild, member, ctx.author, action, reason, case=case)
        await self.done(ctx, member, action, case, reason=reason)

    @commands.command(name="imute", aliases=["imagemute"])
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def imute(self, ctx, member: discord.Member, *, reason: str = ""):
        """Stop someone posting images and files. They can still chat."""
        await self.toggle_role(ctx, member, "imute_role", "imute", True, reason)

    @commands.command(name="unimute", aliases=["iunmute", "unimagemute"])
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

    @commands.command(name="unrmute", aliases=["runmute", "unreactionmute"])
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
        case = await self.record(ctx.guild, member, ctx.author, "warn", reason)
        await self.tell(ctx.guild, member, ctx.author, "warn", reason, case=case)
        count = len(self.db.cases_for(ctx.guild.id, member.id, "warn"))
        await self.done(ctx, member, "warn", case,
                        f", that's warning **{count}**", reason)
        await self.punish_for_warnings(ctx, member, count)

    async def punish_for_warnings(self, ctx, member, count: int):
        """Carry out the server's punishment for reaching this many warnings."""
        rule = next((row for row in self.db.warn_punishments_of(ctx.guild.id)
                     if row["threshold"] == count), None)
        if not rule:
            return
        guild, me = ctx.guild, ctx.guild.me
        if outranks(guild, me, member):
            await ctx.send(f"That's {count} warnings, but I can't"
                           f" {rule['action']} **{member.display_name}**.")
            return
        reason = f"reached {count} warnings"
        action = rule["action"]
        try:
            if action == "timeout":
                await self.apply_timeout(guild, member, me,
                                         rule["duration"] or DEFAULT_TIMEOUT, reason)
            elif action == "jail":
                if not self.role(guild, "jail_role") or \
                        self.role(guild, "jail_role") in member.roles:
                    return
                await self.apply_jail(guild, member, me, reason)
            elif action == "kick":
                await self.apply_kick(guild, member, me, reason)
            elif action == "ban":
                await self.apply_ban(guild, member, me, reason)
        except discord.HTTPException:
            await ctx.send(f"I couldn't {action} **{member.display_name}**."
                           " Check my permissions.")
            return
        await ctx.send(f"That's **{count}** warnings, so **{member.display_name}**"
                       f" has been automatically {ACTIONS[action][0].lower()}.",
                       allowed_mentions=discord.AllowedMentions.none())

    @warn.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def warn_list(self, ctx, member: discord.Member):
        """Every warning someone has."""
        await self.show_cases(ctx, member, "warn")

    @warn.command(name="remove")
    @commands.has_permissions(moderate_members=True)
    async def warn_remove(self, ctx, member: discord.Member, case_id: int):
        """Remove one warning by its case number."""
        row = self.db.delete_case(ctx.guild.id, case_id, "warn")
        if not row or row["user_id"] != member.id:
            await ctx.send(f"**{member.display_name}** has no warning #{case_id}.")
            return
        await ctx.send(f"Removed warning #{case_id} from **{member.display_name}**.")

    @warn.command(name="clear")
    @commands.has_permissions(moderate_members=True)
    async def warn_clear(self, ctx, member: discord.Member):
        """Remove all of someone's warnings."""
        gone = self.db.clear_cases(ctx.guild.id, member.id, "warn")
        await ctx.send(f"Cleared **{gone}** warnings from **{member.display_name}**.")

    @commands.command(name="warnings", aliases=["warns"])
    @commands.guild_only()
    async def warnings(self, ctx, member: discord.Member = None):
        """Every warning someone has. Anyone can see their own."""
        member = member or ctx.author
        if member != ctx.author and not ctx.author.guild_permissions.moderate_members:
            await ctx.send("You can only see your own warnings.")
            return
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
        case = await self.apply_kick(ctx.guild, member, ctx.author, reason)
        await self.done(ctx, member, "kick", case, reason=reason)

    async def banish(self, ctx, user, reason: str, action: str, wipe_days: int):
        member = ctx.guild.get_member(user.id)
        if member and (problem := blocker(ctx, member)):
            await ctx.send(problem)
            return
        reason = clean_reason(reason)
        case = await self.apply_ban(ctx.guild, user, ctx.author, reason, action,
                                    wipe_days)
        await self.done(ctx, user, action, case, reason=reason)

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

    @commands.group(name="hardban", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def hardban(self, ctx, user: Union[discord.Member, discord.User], *,
                      reason: str = ""):
        """A ban that comes back if anyone unbans them."""
        await self.banish(ctx, user, reason, "hardban", 0)

    @hardban.command(name="list")
    @commands.has_permissions(ban_members=True)
    async def hardban_list(self, ctx):
        """Everyone who is hardbanned."""
        rows = self.db.hardbans_in(ctx.guild.id)
        await self.paged(ctx, f"Hardbanned: {len(rows)}", "", [
            f"<@{row['user_id']}> `{row['user_id']}` · by <@{row['mod_id']}>"
            + (f"\n　{row['reason'][:120]}" if row["reason"] else "")
            for row in rows])

    @hardban.command(name="remove")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def hardban_remove(self, ctx, user: discord.User, *, reason: str = ""):
        """Lift a hardban for good. Use their user ID."""
        if not self.db.remove_hardban(ctx.guild.id, user.id):
            await ctx.send(f"**{user}** isn't hardbanned.")
            return
        reason = clean_reason(reason)
        try:
            await ctx.guild.unban(user, reason=audit(ctx.author, reason))
        except discord.NotFound:
            pass
        case = await self.record(ctx.guild, user, ctx.author, "unhardban", reason)
        await self.done(ctx, user, "unhardban", case, reason=reason)

    @commands.command(name="unban")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban(self, ctx, user: discord.User, *, reason: str = ""):
        """Lift a ban. Use their user ID."""
        if self.db.hardban_of(ctx.guild.id, user.id):
            await ctx.send(f"**{user}** is hardbanned. Use"
                           f" `{ctx.prefix}hardban remove {user.id}` instead.")
            return
        reason = clean_reason(reason)
        try:
            await ctx.guild.unban(user, reason=audit(ctx.author, reason))
        except discord.NotFound:
            await ctx.send(f"**{user}** isn't banned.")
            return
        case = await self.record(ctx.guild, user, ctx.author, "unban", reason)
        await self.done(ctx, user, "unban", case, reason=reason)

    # --------------------------------------------------------------- strip

    @commands.command(name="strip")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def strip(self, ctx, member: discord.Member, *, reason: str = ""):
        """Take every role with dangerous permissions off someone. For hacked
        or rogue staff accounts."""
        if problem := blocker(ctx, member):
            await ctx.send(problem)
            return
        top = ctx.guild.me.top_role
        risky = [r for r in member.roles if not r.is_default()
                 and any(getattr(r.permissions, p, False) for p in DANGEROUS)]
        removable = [r for r in risky if not r.managed and r < top]
        if not risky:
            await ctx.send(f"**{member.display_name}** has no dangerous roles.")
            return
        reason = clean_reason(reason)
        if removable:
            await member.remove_roles(*removable, reason=audit(ctx.author, reason))
        case = await self.record(ctx.guild, member, ctx.author, "strip", reason)
        stuck = len(risky) - len(removable)
        await self.done(ctx, member, "strip", case,
                        f" of {len(removable)} roles"
                        + (f" ({stuck} I couldn't remove)" if stuck else ""),
                        reason)

    @commands.command(name="staffstrip")
    @commands.guild_only()
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def staffstrip(self, ctx, member: discord.Member, *, reason: str = ""):
        """Take every staff role off someone."""
        staff = [ctx.guild.get_role(r) for r in self.db.staff_roles_of(ctx.guild.id)]
        if not any(staff):
            await ctx.send("No staff roles are set. Add them with"
                           f" `{ctx.prefix}staffroles add @role`.")
            return
        if problem := blocker(ctx, member):
            await ctx.send(problem)
            return
        theirs = [r for r in member.roles if r in staff]
        if not theirs:
            await ctx.send(f"**{member.display_name}** has no staff roles.")
            return
        reason = clean_reason(reason)
        await member.remove_roles(*theirs, reason=audit(ctx.author, reason))
        case = await self.record(ctx.guild, member, ctx.author, "staffstrip", reason)
        await self.done(ctx, member, "staffstrip", case, reason=reason)

    # ------------------------------------------------------------ messages

    async def sweep(self, ctx, amount: int, keep, scan: int = None):
        """Delete up to `amount` recent messages that `keep` picks out."""
        if not 1 <= amount <= 500:
            await ctx.send("Pick between 1 and 500 messages.")
            return
        matched = 0

        def wanted(message):
            nonlocal matched
            if message.pinned or matched >= amount or message.id == ctx.message.id:
                return False
            if not keep(message):
                return False
            matched += 1
            return True

        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        gone = await ctx.channel.purge(limit=scan or amount, check=wanted)
        await ctx.send(f"Deleted **{len(gone)}** messages.", delete_after=5)

    @commands.command(name="purge", aliases=["clear"])
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge(self, ctx, member: Optional[discord.Member] = None,
                    amount: int = 10):
        """Delete recent messages, or just one person's. Pinned ones stay."""
        if member:
            await self.sweep(ctx, amount, lambda m: m.author.id == member.id, 500)
        else:
            await self.sweep(ctx, amount, lambda m: True)

    @commands.command(name="cleanup")
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def cleanup(self, ctx, amount: int = 50):
        """Delete this bot's messages and the commands people sent it."""
        prefix = ctx.prefix or config.PREFIX
        await self.sweep(
            ctx, amount,
            lambda m: m.author == ctx.guild.me or m.content.startswith(prefix),
            500)

    @commands.command(name="botclear", aliases=["bc"])
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def botclear(self, ctx, amount: int = 50):
        """Delete messages from any bot."""
        await self.sweep(ctx, amount, lambda m: m.author.bot, 500)

    @commands.command(name="selfpurge", aliases=["sp"])
    @commands.guild_only()
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def selfpurge(self, ctx, amount: int = 10):
        """Delete your own recent messages. Anyone can use this."""
        await self.sweep(ctx, amount, lambda m: m.author.id == ctx.author.id, 500)

    # ------------------------------------------------------------ lockdown

    def lock_role(self, guild):
        return self.role(guild, "lock_role") or guild.default_role

    async def set_lock(self, channel, role, locked: bool, reason: str):
        await channel.set_permissions(
            role,
            overwrite=self.overwrite_for(channel, role, {
                "send_messages": False if locked else None,
                "send_messages_in_threads": False if locked else None,
                "add_reactions": False if locked else None,
            }),
            reason=reason)

    async def lock_many(self, ctx, locked: bool, reason: str):
        ignored = set(self.db.lockdown_ignored(ctx.guild.id))
        role = self.lock_role(ctx.guild)
        done = failed = 0
        for channel in ctx.guild.text_channels:
            if channel.id in ignored:
                continue
            try:
                await self.set_lock(channel, role, locked,
                                    audit(ctx.author, clean_reason(reason)))
                done += 1
            except discord.HTTPException:
                failed += 1
        await ctx.send(f"{'Locked' if locked else 'Unlocked'} **{done}** channels"
                       + (f", couldn't change {failed}" if failed else "") + ".")

    @commands.group(name="lockdown", aliases=["lock"], invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def lockdown(self, ctx, channel: Optional[discord.TextChannel] = None,
                       *, reason: str = ""):
        """Stop everyone typing in a channel. This one, if you don't name one."""
        channel = channel or ctx.channel
        await self.set_lock(channel, self.lock_role(ctx.guild), True,
                            audit(ctx.author, clean_reason(reason)))
        await ctx.send(f"{channel.mention} is locked.")

    @lockdown.command(name="all")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def lockdown_all(self, ctx, *, reason: str = ""):
        """Lock every channel except the ignored ones. For raids."""
        await self.lock_many(ctx, True, reason)

    @lockdown.group(name="ignore", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    async def lockdown_ignore(self, ctx, channel: discord.TextChannel):
        """Leave a channel alone during $lockdown all."""
        self.db.ignore_lockdown(ctx.guild.id, channel.id)
        await ctx.send(f"{channel.mention} will stay open during a full lockdown.")

    @lockdown_ignore.command(name="list")
    @commands.has_permissions(manage_channels=True)
    async def lockdown_ignore_list(self, ctx):
        """Channels a full lockdown leaves alone."""
        ids = self.db.lockdown_ignored(ctx.guild.id)
        await ctx.send(embed=discord.Embed(
            title="Ignored by lockdown",
            description=" ".join(f"<#{i}>" for i in ids) or "None.",
            colour=self.colour(ctx.guild.id)))

    @lockdown_ignore.command(name="remove")
    @commands.has_permissions(manage_channels=True)
    async def lockdown_ignore_remove(self, ctx, channel: discord.TextChannel):
        """Include a channel in full lockdowns again."""
        gone = self.db.unignore_lockdown(ctx.guild.id, channel.id)
        await ctx.send(f"{channel.mention} will be locked with the rest."
                       if gone else f"{channel.mention} wasn't ignored.")

    @lockdown.command(name="role")
    @commands.has_permissions(manage_guild=True)
    async def lockdown_role(self, ctx, role: discord.Role = None):
        """Lock a role instead of @everyone. Leave it out to go back."""
        self.db.set_mod_config(ctx.guild.id, "lock_role", role.id if role else 0)
        await ctx.send(f"Lockdowns now apply to **{role.name if role else '@everyone'}**.",
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.group(name="unlockdown", aliases=["unlock"],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def unlockdown(self, ctx, channel: Optional[discord.TextChannel] = None,
                         *, reason: str = ""):
        """Let everyone type in a channel again."""
        channel = channel or ctx.channel
        await self.set_lock(channel, self.lock_role(ctx.guild), False,
                            audit(ctx.author, clean_reason(reason)))
        await ctx.send(f"{channel.mention} is unlocked.")

    @unlockdown.command(name="all")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def unlockdown_all(self, ctx, *, reason: str = ""):
        """Unlock every channel a full lockdown locked."""
        await self.lock_many(ctx, False, reason)

    # ----------------------------------------------------------- nicknames

    @commands.group(name="nickname", aliases=["nick", "setnick"],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nickname(self, ctx, member: discord.Member, *, name: str = None):
        """Change someone's nickname. Leave the name out to reset it."""
        if member != ctx.author and (problem := blocker(ctx, member)):
            await ctx.send(problem)
            return
        if self.db.forced_nick_of(ctx.guild.id, member.id):
            await ctx.send(f"That nickname is forced. Use"
                           f" `{ctx.prefix}nickname force cancel` first.")
            return
        await member.edit(nick=name[:32] if name else None,
                          reason=audit(ctx.author, "nickname"))
        await ctx.send(
            f"Nickname {'set to **' + name[:32] + '**' if name else 'reset'}.",
            allowed_mentions=discord.AllowedMentions.none())

    @nickname.command(name="remove")
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nickname_remove(self, ctx, member: discord.Member):
        """Reset someone's nickname to their username."""
        await self.nickname.callback(self, ctx, member, name=None)

    @nickname.group(name="force", invoke_without_command=True)
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def nickname_force(self, ctx, member: discord.Member, *, name: str):
        """Pin a nickname on someone. Changing it puts it straight back."""
        if problem := blocker(ctx, member):
            await ctx.send(problem)
            return
        name = name[:32]
        self.db.force_nick(ctx.guild.id, member.id, name)
        await member.edit(nick=name, reason=audit(ctx.author, "forced nickname"))
        await ctx.send(f"**{member}** is stuck as **{name}** until"
                       f" `{ctx.prefix}nickname force cancel`.",
                       allowed_mentions=discord.AllowedMentions.none())

    @nickname_force.command(name="cancel")
    @commands.has_permissions(manage_nicknames=True)
    async def nickname_force_cancel(self, ctx, member: discord.Member):
        """Stop forcing someone's nickname. It stays until they change it."""
        gone = self.db.unforce_nick(ctx.guild.id, member.id)
        await ctx.send(f"**{member}** can change their nickname again."
                       if gone else f"**{member}** doesn't have a forced nickname.",
                       allowed_mentions=discord.AllowedMentions.none())

    # greed calls this ,fn, but here $fn is the gacha's find command.
    @commands.command(name="forcenick", aliases=["forcenickname"])
    @commands.guild_only()
    @commands.has_permissions(manage_nicknames=True)
    @commands.bot_has_permissions(manage_nicknames=True)
    async def forcenick(self, ctx, member: discord.Member, *, name: str = None):
        """Force a nickname, or leave the name out to stop forcing it."""
        if name:
            await self.nickname_force.callback(self, ctx, member, name=name)
        else:
            await self.nickname_force_cancel.callback(self, ctx, member)

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

    async def show_cases(self, ctx, member, action: str = None):
        rows = self.db.cases_for(ctx.guild.id, member.id, action)
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
        rows = self.db.cases_by(ctx.guild.id, moderator.id)
        counts = {}
        for row in rows:
            counts[row["action"]] = counts.get(row["action"], 0) + 1
        header = " · ".join(
            f"{ACTIONS[a][0]} **{n}**" for a, n in counts.items() if a in ACTIONS)
        await self.paged(ctx, f"{moderator.display_name}: {len(rows)} actions",
                         header, [self.case_line(row, True) for row in rows])

    @commands.command(name="audit", aliases=["auditlog"])
    @commands.guild_only()
    @commands.has_permissions(view_audit_log=True)
    @commands.bot_has_permissions(view_audit_log=True)
    async def audit_log(self, ctx, limit: int = 10):
        """The server's latest audit log entries."""
        limit = max(1, min(limit, 50))
        lines = []
        async for entry in ctx.guild.audit_logs(limit=limit):
            action = entry.action.name.replace("_", " ")
            target = getattr(entry.target, "mention", None) or (
                f"`{entry.target.id}`" if getattr(entry.target, "id", None) else "")
            line = (f"<t:{int(entry.created_at.timestamp())}:R>"
                    f" {entry.user.mention if entry.user else 'Someone'}"
                    f" **{action}** {target}")
            if entry.reason:
                line += f"\n　{entry.reason[:120]}"
            lines.append(line)
        await self.paged(ctx, "Audit log", "", lines, per_page=10)


async def setup(bot):
    await bot.add_cog(ModTools(bot))
