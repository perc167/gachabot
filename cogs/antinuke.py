"""Antinuke: stop someone wrecking the server, whoever they are.

A nuke is one account (a hijacked admin, a rogue mod, a bot someone added)
deleting channels and roles, banning everyone, or making webhooks to spam,
faster than anyone can react. Paper watches the audit log as it's written
(on_audit_log_entry_create) and counts what each person does in a minute.
Past a module's limit, it punishes them at once and undoes what it can:

    ban             bans            unbans everyone they banned
    kick            kicks
    prune           member prunes
    channel_delete  deleted channels
    channel_create  made channels   deletes the ones they made
    role_delete     deleted roles
    role_create     made roles      deletes the ones they made
    webhook         made webhooks   deletes the ones they made
    emoji_delete    deleted emojis
    bot_add         added a bot     kicks the bot
    vanity          vanity URL      puts it back
    danger_perms    gave a role dangerous permissions   puts them back
    danger_roles    gave someone a dangerous role       takes it back

Never punished: the server owner, Paper, and anyone on the trusted list.
Only the owner and antinuke admins (picked by the owner) can change any of
it, so a hijacked admin can't switch it off first. It starts off.
"""
import time
from collections import defaultdict, deque

import discord
from discord.ext import commands

import config

A = discord.AuditLogAction
WINDOW = 60              # seconds a count covers
COOLDOWN = 300           # once punished, not punished again for this long

# key: (actions, default limit per minute (0 = off), label)
MODULES = {
    "ban": ((A.ban,), 3, "Banning members"),
    "kick": ((A.kick,), 3, "Kicking members"),
    "prune": ((A.member_prune,), 1, "Pruning members"),
    "channel_delete": ((A.channel_delete,), 2, "Deleting channels"),
    "channel_create": ((A.channel_create,), 5, "Making channels"),
    "role_delete": ((A.role_delete,), 2, "Deleting roles"),
    "role_create": ((A.role_create,), 5, "Making roles"),
    "webhook": ((A.webhook_create,), 3, "Making webhooks"),
    "emoji_delete": ((A.emoji_delete,), 3, "Deleting emojis"),
    "bot_add": ((A.bot_add,), 1, "Adding bots"),
    "vanity": ((A.guild_update,), 1, "Changing the vanity URL"),
    # Off by default: admins give out mod roles and edit them all the time.
    "danger_perms": ((A.role_update,), 0, "Giving a role dangerous permissions"),
    "danger_roles": ((A.member_role_update,), 0, "Giving someone a dangerous role"),
}
PUNISHMENTS = ("strip", "kick", "ban")
DANGEROUS = discord.Permissions(
    administrator=True, manage_guild=True, manage_roles=True, manage_channels=True,
    ban_members=True, kick_members=True, manage_webhooks=True)


def dangerous(perms: discord.Permissions) -> bool:
    return bool(perms.value & DANGEROUS.value)


def module_for(entry) -> str:
    """Which module an audit log entry counts towards, or ''."""
    action = entry.action
    if action == A.guild_update:
        before = getattr(entry.before, "vanity_url_code", None)
        after = getattr(entry.after, "vanity_url_code", None)
        return "vanity" if before != after else ""
    if action == A.role_update:
        before = getattr(entry.before, "permissions", None)
        after = getattr(entry.after, "permissions", None)
        if after is not None and dangerous(discord.Permissions(
                after.value & ~(before.value if before else 0))):
            return "danger_perms"
        return ""
    if action == A.member_role_update:
        added = getattr(entry.after, "roles", None) or []
        return "danger_roles" if any(dangerous(r.permissions) for r in added
                                     if isinstance(r, discord.Role)) else ""
    for key, (actions, _limit, _label) in MODULES.items():
        if action in actions:
            return key
    return ""


class AntiNuke(commands.Cog):
    works_everywhere = True  # security; see bot.check_allowed

    def __init__(self, bot):
        self.bot = bot
        self.seen = defaultdict(deque)     # (guild, user, module) -> [(when, entry)]
        self.punished = {}                 # (guild, user) -> when

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------ settings

    def setting(self, guild_id: int, key: str, default: int = 0) -> int:
        return self.db.antinuke_get(guild_id, key, default)

    def enabled(self, guild_id: int) -> bool:
        return bool(self.setting(guild_id, "enabled"))

    def limit(self, guild_id: int, module: str) -> int:
        return self.setting(guild_id, f"limit:{module}", MODULES[module][1])

    def punishment(self, guild_id: int) -> str:
        return PUNISHMENTS[min(self.setting(guild_id, "punishment", 0), len(PUNISHMENTS) - 1)]

    def exempt(self, guild, user_id: int) -> bool:
        return (user_id == guild.owner_id or user_id == self.bot.user.id
                or user_id in self.db.antinuke_people(guild.id, "trusted"))

    def can_configure(self, ctx) -> bool:
        return (ctx.author.id == ctx.guild.owner_id or ctx.author.id in config.OWNERS
                or ctx.author.id in self.db.antinuke_people(ctx.guild.id, "admin"))

    # ------------------------------------------------------------ watching

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        guild = entry.guild
        user_id = entry.user_id or (entry.user.id if entry.user else None)
        if not user_id or not self.enabled(guild.id) or self.exempt(guild, user_id):
            return
        module = module_for(entry)
        if not module:
            return
        limit = self.limit(guild.id, module)
        if limit <= 0:
            return
        now = time.time()
        seen = self.seen[(guild.id, user_id, module)]
        seen.append((now, entry))
        while seen and now - seen[0][0] > WINDOW:
            seen.popleft()
        if len(seen) < limit:
            return
        if now - self.punished.get((guild.id, user_id), 0) < COOLDOWN:
            # Already dealt with; still clean up what they keep doing.
            await self.undo(guild, module, [entry])
            return
        self.punished[(guild.id, user_id)] = now
        entries = [e for _t, e in seen]
        seen.clear()
        await self.respond(guild, user_id, module, entries)

    async def respond(self, guild, user_id: int, module: str, entries: list):
        """Stop them, undo what can be undone, and tell the owner."""
        member = guild.get_member(user_id)
        punished = await self.punish(guild, member, user_id)
        undone = await self.undo(guild, module, entries)
        await self.report(guild, user_id, member, module, len(entries), punished, undone)

    async def punish(self, guild, member, user_id: int) -> str:
        how = self.punishment(guild.id)
        reason = "Antinuke: went past a limit"
        me = guild.me
        try:
            if member is not None and member.top_role >= me.top_role:
                return ("couldn't be punished: their highest role is above mine. Put my"
                        " role at the top of the role list.")
            if member is not None and member.bot and how == "strip":
                how = "kick"     # a bot's own role can't be taken away
            if how == "ban":
                await guild.ban(discord.Object(user_id), reason=reason, delete_message_seconds=0)
                return "banned"
            if member is None:
                return "had already left"
            if how == "kick":
                await member.kick(reason=reason)
                return "kicked"
            roles = [r for r in member.roles if not r.is_default() and not r.managed
                     and r < me.top_role]
            await member.remove_roles(*roles, reason=reason)
            return f"stripped of {len(roles)} role{'s' if len(roles) != 1 else ''}"
        except discord.HTTPException:
            return "couldn't be punished: Discord refused. Check my permissions."

    async def undo(self, guild, module: str, entries) -> list:
        """Put back what can be put back. Returns lines saying what."""
        done = []
        for entry in entries:
            target = entry.target
            try:
                if module == "ban" and target is not None:
                    await guild.unban(discord.Object(target.id), reason="Antinuke: undoing a nuke")
                    done.append(f"unbanned <@{target.id}>")
                elif module in ("channel_create", "role_create") and target is not None:
                    made = (guild.get_channel(target.id) if module == "channel_create"
                            else guild.get_role(target.id))
                    if made is not None:
                        await made.delete(reason="Antinuke: undoing a nuke")
                        done.append(f"deleted {'#' if module == 'channel_create' else '@'}{made.name}")
                elif module == "webhook" and target is not None:
                    for hook in await guild.webhooks():
                        if hook.id == target.id:
                            await hook.delete(reason="Antinuke: undoing a nuke")
                            done.append(f"deleted the webhook {hook.name}")
                elif module == "bot_add" and target is not None:
                    bot = guild.get_member(target.id)
                    if bot is not None:
                        await bot.kick(reason="Antinuke: added by someone untrusted")
                        done.append(f"kicked the bot {bot.name}")
                elif module == "danger_perms" and isinstance(target, discord.Role):
                    before = getattr(entry.before, "permissions", None)
                    if before is not None:
                        await target.edit(permissions=before, reason="Antinuke: undoing a nuke")
                        done.append(f"put @{target.name}'s permissions back")
                elif module == "danger_roles" and isinstance(target, discord.Member):
                    added = [r for r in getattr(entry.after, "roles", []) or []
                             if isinstance(r, discord.Role) and dangerous(r.permissions)]
                    if added:
                        await target.remove_roles(*added, reason="Antinuke: undoing a nuke")
                        done.append(f"took {', '.join('@' + r.name for r in added)} back from"
                                    f" {target.display_name}")
                elif module == "vanity":
                    before = getattr(entry.before, "vanity_url_code", None)
                    if before:
                        await guild.edit(vanity_code=before, reason="Antinuke: undoing a nuke")
                        done.append(f"put the vanity back to discord.gg/{before}")
            except (discord.HTTPException, TypeError, AttributeError):
                continue
        return done

    async def report(self, guild, user_id, member, module, count, punished, undone):
        label = MODULES[module][2].lower()
        embed = discord.Embed(
            title="\U0001f6a8 Antinuke stopped someone",
            description=f"<@{user_id}> ({member or user_id}) went past the limit for"
                        f" **{label}**: {count} in a minute. They were **{punished}**.",
            colour=0xE0525F)
        if undone:
            embed.add_field(name="Undone", value="\n".join(undone)[:1024], inline=False)
        embed.set_footer(text=f"{guild.name} · trust someone with $antinuke trust @them")
        channel = guild.get_channel(self.setting(guild.id, "log_channel")
                                    or self.db.get_mod_config(guild.id, "log_channel"))
        if channel is not None:
            try:
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass
        owner = guild.owner or (await self._fetch(guild.owner_id))
        if owner is not None:
            try:
                await owner.send(embed=embed)
            except discord.HTTPException:
                pass

    async def _fetch(self, user_id):
        try:
            return await self.bot.fetch_user(user_id)
        except discord.HTTPException:
            return None

    # ------------------------------------------------------------ commands

    def status_embed(self, ctx) -> discord.Embed:
        gid = ctx.guild.id
        p = ctx.prefix
        on = self.enabled(gid)
        lines = []
        for key, (_actions, _default, label) in MODULES.items():
            limit = self.limit(gid, key)
            lines.append(f"`{key}` {label}: " + (f"**{limit}** a minute" if limit else "off"))
        trusted = self.db.antinuke_people(gid, "trusted")
        admins = self.db.antinuke_people(gid, "admin")
        embed = discord.Embed(
            title="\U0001f6e1️ Antinuke " + ("is on" if on else "is off"),
            description=(f"Anyone who goes past a limit is **{self.punishment(gid)}**"
                         + (" (bots are kicked)" if self.punishment(gid) == "strip" else "")
                         + ", and what they did is undone where it can be. The owner, Paper"
                           " and trusted people are never touched.\n\n" + "\n".join(lines)),
            colour=0x43B581 if on else 0x99AAB5)
        embed.add_field(name="Trusted", value=" ".join(f"<@{u}>" for u in trusted) or "nobody",
                        inline=False)
        embed.add_field(name="Antinuke admins", value=" ".join(f"<@{u}>" for u in admins)
                        or "only the owner", inline=False)
        warnings = []
        me = ctx.guild.me
        above = [r for r in ctx.guild.roles if r > me.top_role and not r.managed]
        if above:
            warnings.append("My role isn't at the top, so I can't stop anyone above it."
                            " Drag it to the top of Server Settings → Roles.")
        needed = [name for name in ("view_audit_log", "ban_members", "kick_members",
                                    "manage_roles", "manage_channels", "manage_webhooks")
                  if not getattr(me.guild_permissions, name)]
        if needed:
            warnings.append("I'm missing: " + ", ".join(n.replace("_", " ").title() for n in needed))
        if warnings:
            embed.add_field(name="⚠️ Fix these", value="\n".join(warnings), inline=False)
        embed.set_footer(text=f"{p}antinuke on/off · {p}antinuke punishment strip/kick/ban ·"
                              f" {p}antinuke limit <module> <number or off> ·"
                              f" {p}antinuke trust @someone")
        return embed

    async def gate(self, ctx) -> bool:
        if self.can_configure(ctx):
            return True
        await ctx.send("Only the server owner and antinuke admins can change the antinuke.")
        return False

    @commands.group(name="antinuke", aliases=["an", "antiraid"], invoke_without_command=True)
    @commands.guild_only()
    async def antinuke(self, ctx):
        """The antinuke: what it watches, what it does, and who it trusts."""
        await ctx.send(embed=self.status_embed(ctx))

    @antinuke.command(name="on", aliases=["enable"])
    async def an_on(self, ctx):
        """Turn the antinuke on."""
        if await self.gate(ctx):
            self.db.antinuke_set(ctx.guild.id, "enabled", 1)
            await ctx.send(embed=self.status_embed(ctx))

    @antinuke.command(name="off", aliases=["disable"])
    async def an_off(self, ctx):
        """Turn the antinuke off."""
        if await self.gate(ctx):
            self.db.antinuke_set(ctx.guild.id, "enabled", 0)
            await ctx.send("The antinuke is off.")

    @antinuke.command(name="punishment", aliases=["punish"])
    async def an_punishment(self, ctx, how: str):
        """What happens to whoever goes past a limit: strip, kick or ban."""
        if not await self.gate(ctx):
            return
        how = how.lower()
        if how not in PUNISHMENTS:
            await ctx.send("Pick strip (take their roles), kick or ban.")
            return
        self.db.antinuke_set(ctx.guild.id, "punishment", PUNISHMENTS.index(how))
        await ctx.send(f"Anyone who goes past a limit will be **{how}**"
                       + ("ped of their roles." if how == "strip" else "ed." if how == "kick"
                          else "ned."))

    @antinuke.command(name="limit", aliases=["set", "threshold"])
    async def an_limit(self, ctx, module: str, value: str):
        """`$antinuke limit ban 3`: how many in a minute before acting.
        `off` turns that one off."""
        if not await self.gate(ctx):
            return
        module = module.lower()
        if module not in MODULES:
            await ctx.send("Modules: " + ", ".join(f"`{m}`" for m in MODULES))
            return
        number = 0 if value.lower() in ("off", "0", "none") else None
        if number is None:
            try:
                number = int(value)
            except ValueError:
                await ctx.send("Give a number, or `off`.")
                return
        if not 0 <= number <= 50:
            await ctx.send("From 1 to 50 a minute, or `off`.")
            return
        self.db.antinuke_set(ctx.guild.id, f"limit:{module}", number)
        await ctx.send(f"**{MODULES[module][2]}**: " + (f"{number} a minute." if number else "off."))

    @antinuke.command(name="trust", aliases=["whitelist", "wl"])
    async def an_trust(self, ctx, member: discord.Member):
        """Never punish this person or bot."""
        if await self.gate(ctx):
            self.db.antinuke_add_person(ctx.guild.id, member.id, "trusted")
            await ctx.send(f"The antinuke trusts **{member.display_name}** now.",
                           allowed_mentions=discord.AllowedMentions.none())

    @antinuke.command(name="untrust", aliases=["unwhitelist", "unwl"])
    async def an_untrust(self, ctx, member: discord.User):
        """Stop trusting someone."""
        if await self.gate(ctx):
            gone = self.db.antinuke_remove_person(ctx.guild.id, member.id, "trusted")
            await ctx.send("Done." if gone else "They weren't trusted.")

    @antinuke.command(name="admin")
    async def an_admin(self, ctx, member: discord.Member):
        """Owner only: let someone change the antinuke."""
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.send("Only the server owner can choose antinuke admins.")
            return
        self.db.antinuke_add_person(ctx.guild.id, member.id, "admin")
        await ctx.send(f"**{member.display_name}** can change the antinuke now.",
                       allowed_mentions=discord.AllowedMentions.none())

    @antinuke.command(name="unadmin")
    async def an_unadmin(self, ctx, member: discord.User):
        """Owner only: take someone's antinuke admin away."""
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.send("Only the server owner can choose antinuke admins.")
            return
        gone = self.db.antinuke_remove_person(ctx.guild.id, member.id, "admin")
        await ctx.send("Done." if gone else "They weren't an antinuke admin.")

    @antinuke.command(name="log")
    async def an_log(self, ctx, channel: discord.TextChannel = None):
        """Where alerts go (the mod log if you don't pick one). The owner
        always gets a DM too."""
        if await self.gate(ctx):
            self.db.antinuke_set(ctx.guild.id, "log_channel", channel.id if channel else 0)
            await ctx.send(f"Antinuke alerts go to {channel.mention}." if channel
                           else "Antinuke alerts go to the mod log.")


async def setup(bot):
    await bot.add_cog(AntiNuke(bot))
