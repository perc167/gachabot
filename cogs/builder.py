"""$serversetup: build a whole server in one go. A Premium Plus feature.

Four parts, each optional, picked from a menu before anything happens:

    roles      staff roles from Owner to Trial, with colours (a gradient and
               an icon too where the server has those unlocked), dividers,
               and the punishment roles Paper's moderation uses
    staff      a mod area (jail, moderator-only, jail vc, mod vc) and logs
               (logs, mod-logs), wired to Paper's jail and mod log
    forum      a MUST READ category with a how-to-mod forum: the mod guide
               and the command list as posts (data/guides/)
    community  info, chat and voice channels, a Member role new people get,
               level roles, and Paper switched on in them: welcomes,
               level-ups, the gacha channel and Join To Create

Nothing is made twice: anything already there with the same name is used
as it is, so it's safe to run again, or to run one part at a time.

Roles can only be given permissions Paper has itself; Owner and Co-owner
get Administrator only if Paper has it, and the result says what it left out.
"""
import os
import re

import discord
from discord.ext import commands

import billing

GUIDES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "guides")


def fancy(name: str) -> str:
    return f"「 ✦ {name} ✦ 」"


def divider(name: str) -> str:
    return f"-ˏˋ ✶ ˊˎ- {name} -ˏˋ ✶ ˊˎ-"


def category_name(name: str) -> str:
    return f"----୨୧----{name}----୨୧----"


P = discord.Permissions
ADMIN = P(administrator=True)
ADMIN_ISH = P(manage_guild=True, manage_roles=True, manage_channels=True,
              manage_messages=True, manage_nicknames=True, manage_threads=True,
              kick_members=True, ban_members=True, moderate_members=True,
              view_audit_log=True, mention_everyone=True, move_members=True,
              mute_members=True, deafen_members=True, manage_expressions=True,
              manage_events=True)
MOD = P(kick_members=True, ban_members=True, moderate_members=True, manage_messages=True,
        manage_nicknames=True, manage_threads=True, view_audit_log=True,
        move_members=True, mute_members=True)
TRIAL = P(moderate_members=True, view_audit_log=True)

# key, name, colour, second colour for a gradient, permissions, shown
# separately, icon. Top to bottom; they're made in this order, and each new
# role goes in below the last.
STAFF_ROLES = [
    ("div_staff", divider("hierarchy"), 0, None, P.none(), False, None),
    ("owner", fancy("OWNER"), 0x2F5BEA, 0x8FA8FF, ADMIN, True, "👑"),
    ("coowner", fancy("Co-owner"), 0xD9A066, 0xF6D8A8, ADMIN, True, "💫"),
    ("admin", fancy("Admin"), 0xC9CDD6, 0xFFFFFF, ADMIN_ISH, True, "🛡️"),
    ("mod", fancy("Mod"), 0x7FD1D8, 0xC4F3F6, MOD, True, "⚔️"),
    ("trial", fancy("Trial"), 0xE6B9A6, 0xF8E0D6, TRIAL, True, "🌱"),
]
PUNISH_ROLES = [
    ("jail_role", "Jailed", 0x7A3E12),
    ("imute_role", "imuted", 0xA0522D),
    ("rmute_role", "rmuted", 0x8B3A2B),
]
LEVEL_ROLES = [
    (50, fancy("Level 50"), 0xE5C55A, 0xFFF1B8),
    (30, fancy("Level 30"), 0xEE7FA8, 0xFFC4D8),
    (20, fancy("Level 20"), 0xB08CFF, 0xDCCBFF),
    (10, fancy("Level 10"), 0x7FB8FF, 0xC6E0FF),
    (5, fancy("Level 5"), 0x9AD9B0, 0xD2F2DC),
]
MEMBER = (fancy("Member"), 0xB9A8FF, 0xE3DAFF)

PARTS = {
    "roles": ("Roles", "Owner, Co-owner, Admin, Mod and Trial with colours, dividers,"
                       " and the Jailed, imuted and rmuted roles"),
    "staff": ("Staff area and logs", "jail, moderator-only, jail vc and mod vc, then"
                                     " logs and mod-logs, all hooked up to Paper"),
    "forum": ("How-to-mod forum", "a MUST READ category with the mod guide and the"
                                  " command list as forum posts"),
    "community": ("Community channels", "welcome, rules, general, media, gacha,"
                                        " level-ups, voice with Join To Create, a"
                                        " Member role and level roles"),
}


class Build:
    """One run of the builder: makes what's missing, remembers what it did."""

    def __init__(self, bot, guild, prefix: str):
        self.bot, self.guild, self.db, self.prefix = bot, guild, bot.db, prefix
        self.made, self.kept, self.problems = [], [], []
        self.features = set(guild.features)
        self.can = guild.me.guild_permissions

    # ------------------------------------------------------------ making

    async def role(self, name: str, colour: int = 0, second: int = None,
                   perms: discord.Permissions = None, hoist: bool = False, icon: str = None):
        existing = discord.utils.get(self.guild.roles, name=name)
        if existing:
            self.kept.append(name)
            return existing
        perms = perms or P.none()
        allowed = P(perms.value & self.can.value) if not self.can.administrator else perms
        if allowed.value != perms.value:
            self.problems.append(f"**{name}** is missing some permissions I don't have"
                                 " myself. Add them in Server Settings → Roles.")
        kwargs = {"name": name, "colour": discord.Colour(colour), "permissions": allowed,
                  "hoist": hoist, "reason": "$serversetup"}
        if second is not None and "ENHANCED_ROLE_COLORS" in self.features:
            kwargs["secondary_colour"] = discord.Colour(second)
        if icon and "ROLE_ICONS" in self.features:
            kwargs["display_icon"] = icon
        try:
            role = await self.guild.create_role(**kwargs)
        except (discord.HTTPException, TypeError):
            # A gradient or icon the server can't have after all: plainer.
            kwargs.pop("secondary_colour", None)
            kwargs.pop("display_icon", None)
            role = await self.guild.create_role(**kwargs)
        self.made.append(name)
        return role

    def find_channel(self, name: str, category=None):
        for channel in (category.channels if category else self.guild.channels):
            if channel.name == name:
                return channel
        return None

    async def category(self, name: str, overwrites=None):
        existing = discord.utils.get(self.guild.categories, name=name)
        if existing:
            self.kept.append(name)
            return existing
        made = await self.guild.create_category(name, overwrites=overwrites or {},
                                                reason="$serversetup")
        self.made.append(name)
        return made

    async def text(self, name: str, category, overwrites=None, topic: str = None):
        existing = self.find_channel(name, category)
        if existing:
            self.kept.append(f"#{name}")
            return existing
        made = await self.guild.create_text_channel(
            name, category=category, overwrites=overwrites or category.overwrites,
            topic=topic, reason="$serversetup")
        self.made.append(f"#{name}")
        return made

    async def voice(self, name: str, category, overwrites=None):
        existing = self.find_channel(name, category)
        if existing:
            self.kept.append(f"🔊 {name}")
            return existing
        made = await self.guild.create_voice_channel(
            name, category=category, overwrites=overwrites or category.overwrites,
            reason="$serversetup")
        self.made.append(f"🔊 {name}")
        return made

    # ------------------------------------------------------------- views

    def staff(self) -> list:
        roles = [self.guild.get_role(r) for r in self.db.staff_roles_of(self.guild.id)]
        return [r for r in roles if r]

    def staff_only(self, extra=None) -> dict:
        can = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                          read_message_history=True, connect=True, speak=True)
        overwrites = {self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                      self.guild.me: can}
        overwrites.update({role: can for role in self.staff()})
        for role in extra or ():
            overwrites[role] = can
        return overwrites

    def read_only(self) -> dict:
        return {self.guild.default_role: discord.PermissionOverwrite(
                    send_messages=False, create_public_threads=False,
                    create_private_threads=False),
                self.guild.me: discord.PermissionOverwrite(send_messages=True,
                                                           embed_links=True)}

    def punishment(self, key: str):
        return self.guild.get_role(self.db.get_mod_config(self.guild.id, key))

    # ------------------------------------------------------------- parts

    async def build_roles(self):
        for key, name, colour, second, perms, hoist, icon in STAFF_ROLES:
            role = await self.role(name, colour, second, perms, hoist, icon)
            if key not in ("div_staff",):
                self.db.add_staff_role(self.guild.id, role.id)
        await self.punishment_roles()

    async def punishment_roles(self):
        for key, name, colour in PUNISH_ROLES:
            if self.punishment(key):
                continue
            role = await self.role(name, colour)
            self.db.set_mod_config(self.guild.id, key, role.id)

    async def build_staff(self):
        await self.punishment_roles()
        jailed = self.punishment("jail_role")
        mod = await self.category(category_name("mod"), self.staff_only())
        jail = await self.text("jail", mod, self.staff_only([jailed]),
                               topic="Jailed members talk to staff here.")
        self.db.set_mod_config(self.guild.id, "jail_channel", jail.id)
        await self.text("moderator-only", mod, topic="Staff chat.")
        await self.voice("jail vc", mod, self.staff_only([jailed]))
        await self.voice("mod vc", mod)
        logs = await self.category(category_name("logs"), self.staff_only())
        await self.text("logs", logs, topic="For other bots' logs.")
        mod_logs = await self.text("mod-logs", logs, topic="Every mod action, from Paper.")
        self.db.set_mod_config(self.guild.id, "log_channel", mod_logs.id)
        # Every channel, new and old, gets the jail and mute overwrites.
        tools = self.bot.get_cog("ModTools")
        if tools:
            await tools.show_staff_the_rooms(self.guild)
            failed = 0
            for channel in self.guild.channels:
                try:
                    await tools.lock_out(channel, self.guild)
                except discord.HTTPException:
                    failed += 1
            if failed:
                self.problems.append(f"I couldn't add the jail to {failed} channels."
                                     f" Run `{self.prefix}setupmod` once I can see them.")

    def guide(self, filename: str) -> str:
        with open(os.path.join(GUIDES, filename), encoding="utf-8") as handle:
            text = handle.read()
        # Commands in the server's own prefix.
        return re.sub(r"\$(?=[a-z])", lambda _m: self.prefix, text) if self.prefix != "$" else text

    async def build_forum(self):
        must = await self.category("MUST READ", self.staff_only())
        posts = [("MOD GUIDE: HOW TO MOD", "how-to-mod.md"),
                 ("MOD GUIDE: COMMANDS", "mod-commands.md")]
        existing = self.find_channel("how-to-mod", must)
        if existing:
            self.kept.append("how-to-mod")
            return
        try:
            forum = await self.guild.create_forum("how-to-mod", category=must,
                                                  overwrites=must.overwrites,
                                                  reason="$serversetup")
            for title, filename in posts:
                await forum.create_thread(name=title, content=self.guide(filename)[:2000])
            self.made.append("how-to-mod (forum)")
        except discord.HTTPException:
            # No forums here: a read-only channel with the posts instead.
            channel = await self.text("how-to-mod", must)
            for title, filename in posts:
                await channel.send(f"# {title}\n" + self.guide(filename)[:1900])

    async def build_community(self):
        gid = self.guild.id
        member = await self.role(*MEMBER)
        self.db.replace_autoroles(gid, [*self.db.autoroles_of(gid), member.id])
        pairs = []
        for level, name, colour, second in LEVEL_ROLES:
            role = await self.role(name, colour, second, hoist=level >= 20)
            pairs.append((level, role.id))
        existing = {lvl: rid for lvl, rid in
                    ((r["level"], r["role_id"]) for r in self.db.level_roles_of(gid))}
        existing.update(dict(pairs))
        self.db.replace_level_roles(gid, sorted(existing.items()))

        info = await self.category(category_name("info"))
        welcome = await self.text("welcome", info, self.read_only())
        await self.text("rules", info, self.read_only(), topic="Read these first.")
        await self.text("announcements", info, self.read_only())
        chat = await self.category(category_name("chat"))
        await self.text("general", chat)
        await self.text("media", chat)
        gacha = await self.text("gacha", chat, topic=f"Roll with {self.prefix}w, {self.prefix}h"
                                                     f" and {self.prefix}m.")
        await self.text("bot-cmds", chat)
        level_ups = await self.text("level-ups", chat, self.read_only())
        voice = await self.category(category_name("voice"))
        join = await self.voice("Join To Create", voice)
        await self.voice("general vc", voice)
        await self.voice("music", voice)

        # Paper, switched on in them.
        for kind in ("welcome", "goodbye"):
            if not self.guild.get_channel(self.db.greeting(gid, kind)["channel_id"]):
                self.db.set_greeting(gid, kind, channel_id=welcome.id)
        levels = self.bot.get_cog("Levels")
        if levels:
            levels.save_settings(gid, {"channel": level_ups.id})
        if not self.guild.get_channel(self.db.get_vc_setting(gid, "create_channel")):
            self.db.set_vc_setting(gid, "create_channel", join.id)
        if not self.db.allowed_channels(gid):
            self.db.allow_channel(gid, gacha.id)

    async def run(self, parts):
        for part in ("roles", "staff", "forum", "community"):
            if part in parts:
                await getattr(self, f"build_{part}")()


class SetupMenu(discord.ui.View):
    """Choose the parts, then build."""

    def __init__(self, cog, ctx):
        super().__init__(timeout=300)
        self.cog, self.ctx = cog, ctx
        self.parts = set(PARTS)
        self.picker = discord.ui.Select(
            placeholder="What should I build?", min_values=1, max_values=len(PARTS),
            options=[discord.SelectOption(label=label, value=key, description=line[:100],
                                          default=True)
                     for key, (label, line) in PARTS.items()])
        self.picker.callback = self.picked
        self.add_item(self.picker)
        self.message = None

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only whoever ran it can build.",
                                                    ephemeral=True)
            return False
        return True

    async def picked(self, interaction):
        self.parts = set(self.picker.values)
        for option in self.picker.options:
            option.default = option.value in self.parts
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Build it", style=discord.ButtonStyle.success, emoji="🏗️", row=1)
    async def go(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(
            content="🏗️ Building… this takes a minute. Please don't run it twice.",
            embed=None, view=None)
        await self.cog.build(self.ctx, self.parts, interaction.message)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled. Nothing was made.",
                                                embed=None, view=None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class Builder(commands.Cog):
    works_everywhere = True  # admin setup; see bot.check_allowed

    def __init__(self, bot):
        self.bot = bot
        self.building = set()

    @commands.command(name="serversetup", aliases=["buildserver", "setupserver", "serverbuild"])
    @commands.guild_only()
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_roles=True, manage_channels=True)
    async def serversetup(self, ctx):
        """Premium Plus: build the server's roles, channels, staff area, logs and
        a how-to-mod forum, with Paper set up in them."""
        if not self.bot.db.is_plus(ctx.guild.id):
            plans = " or ".join(f"**{billing.PLANS[k][3]}**"
                                + (f" ({billing.plan_label(k)})" if billing.plan_label(k) else "")
                                for k in ("plus", "lifetime"))
            await ctx.send(f"The server builder comes with {plans}."
                           f" `{ctx.prefix}upgrade` to see how to get it.")
            return
        if ctx.guild.id in self.building:
            await ctx.send("I'm already building this server.")
            return
        embed = discord.Embed(
            title="🏗️ Build this server",
            description=("Pick what to make, then press **Build it**. Anything that's"
                         " already here with the same name is kept as it is, so it's safe"
                         " to run again.\n\n"
                         + "\n".join(f"**{label}:** {line}" for label, line in PARTS.values())),
            colour=0xE5C55A)
        embed.set_footer(text="Put Paper's role at the top of the role list first, so it"
                              " can manage everything it makes.")
        view = SetupMenu(self, ctx)
        view.message = await ctx.send(embed=embed, view=view)

    async def build(self, ctx, parts, message):
        guild = ctx.guild
        self.building.add(guild.id)
        run = Build(self.bot, guild, ctx.prefix)
        try:
            await run.run(parts)
        except discord.HTTPException as e:
            run.problems.append(f"Discord stopped me partway: {e.text or e.status}."
                                " Fix that and run it again; what's done is kept.")
        finally:
            self.building.discard(guild.id)
        lines = ["✅ **Done.**" if not run.problems else "⚠️ **Mostly done.**"]
        if run.made:
            lines.append(f"Made {len(run.made)}: " + ", ".join(run.made)[:1500])
        if run.kept:
            lines.append(f"Already here, kept: {len(run.kept)}")
        lines += run.problems[:8]
        if "staff" in parts or "roles" in parts:
            lines.append(f"Give your staff their roles, then read the how-to-mod forum."
                         f" `{ctx.prefix}dashboard` changes the rest.")
        text = "\n".join(lines)[:2000]
        try:
            await message.edit(content=text)
        except discord.HTTPException:
            await ctx.send(text)


async def setup(bot):
    await bot.add_cog(Builder(bot))
