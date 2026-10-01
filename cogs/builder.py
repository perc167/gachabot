"""$serversetup: set up a whole server, one yes-or-no question at a time.
A Premium Plus feature.

Each step in STEPS is a question; nothing happens until the last screen's
Build it, and then only the yeses are built, in order:

    roles      staff roles from Owner to Trial, with colours (a gradient and
               an icon too where the server has those unlocked), dividers,
               and the punishment roles Paper's moderation uses
    staff      a mod area (jail, moderator-only, jail vc, mod vc) and logs
               (logs, mod-logs), wired to Paper's jail and mod log
    forum      a MUST READ category with a how-to-mod forum: the mod guide
               and the command list as posts (data/guides/)
    welcome    #welcome, with Paper's welcomes and goodbyes in it
    channels   announcements, giveaways, rules; general and booster-general;
               bot-commands; artwork, media, face-reveal, hall-of-shame, edits
    member     a Member role new people get
    gacha      #paper, with rolling kept to it
    levels     #levelup and level roles
    voice      vc I, II and III, then vc-info and Join To Create

The layout follows Paper's own server: IMPORTANT, Text Channels, Misc
Category, Voice Channels, Private Vcs and Media, then the staff categories
(MUST READ, mod, logs) moved to the very bottom.
    automod    invite, mass mention and spam filters on
    antinuke   on, if the owner (or an antinuke admin) is the one asking
    antialt    new accounts jailed, hardban look-alikes flagged

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
import config

GUIDES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "data", "guides")


def fancy(name: str) -> str:
    return f"「 ✦ {name} ✦ 」"


def divider(name: str) -> str:
    return f"-ˏˋ ✶ ˊˎ- {name} -ˏˋ ✶ ˊˎ-"


def category_name(name: str) -> str:
    return f"----୨୧----{name}----୨୧----"


# The layout, top to bottom, as on Paper's own server. Each category's
# channels share a little decoration in front of their names.
IMPORTANT, TEXT, MISC = category_name("IMPORTANT"), category_name("Text Channels"), \
    category_name("Misc Category")
VOICE, PRIVATE_VC, MEDIA = category_name("Voice Channels"), category_name("Private Vcs"), \
    category_name("Media")
MUST_READ, MOD_CAT, LOGS_CAT = "MUST READ", category_name("mod"), category_name("logs")
LAYOUT = (IMPORTANT, TEXT, MISC, VOICE, PRIVATE_VC, MEDIA)
# Which steps put channels in which of those.
NEEDS = {"welcome": (IMPORTANT,), "channels": (IMPORTANT, TEXT, MISC, MEDIA),
         "gacha": (MISC,), "levels": (MISC,), "voice": (VOICE, PRIVATE_VC)}
# Staff categories always end up at the very bottom, in this order.
STAFF_CATEGORIES = (MUST_READ, MOD_CAT, LOGS_CAT)
TOP_MARK = "ᶻ-z-𐰁-"       # IMPORTANT and Text Channels
MISC_MARK = "❀⸝⸝-"         # Misc Category
MEDIA_MARK = "ঌ⁀➷⋆˚-"      # Media
VC_MARK = "ᰔ vc"            # the open voice channels: ᰔ vc I, II, III


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

# One question each, asked in this order and built in this order. Every
# step is safe to run again: what's already there is kept as it is.
# key: (emoji, title, the question, what a yes makes or switches on)
STEPS = {
    "roles": ("\U0001f451", "Staff roles", "Make staff roles?",
              "Owner, Co-owner, Admin, Mod and Trial with colours and dividers, and the"
              " Jailed, imuted and rmuted roles Paper's moderation uses."),
    "staff": ("\U0001f6e1\ufe0f", "Staff area and logs", "Make a staff area and logs?",
              "jail, moderator-only, jail vc and mod vc, then logs and mod-logs, all hidden"
              " from members and hooked up to Paper's jail and mod log."),
    "forum": ("\U0001f4d6", "How-to-mod forum", "Make a how-to-mod forum for your staff?",
              "A MUST READ category with the mod guide and the command list as posts."),
    "welcome": ("\U0001f44b", "Welcomes", "Greet people who join and leave?",
                "A #welcome channel at the top, with Paper's welcome and goodbye messages."),
    "channels": ("\U0001f4ac", "Chat channels", "Make the usual chat channels?",
                 "IMPORTANT: announcements, giveaways and rules (read-only). Text Channels:"
                 " general, and booster-general for your boosters. Misc: bot-commands."
                 " Media: artwork, media, face-reveal, hall-of-shame and edits."),
    "member": ("\U0001f9d1", "Member role", "Give everyone who joins a Member role?",
               "A Member role, handed out automatically to new members."),
    "gacha": ("\U0001f3b2", "Gacha", "Use Paper's gacha game?",
              "A #paper channel in Misc, with rolling and claiming kept to it so chat"
              " stays clear."),
    "levels": ("\U0001f4c8", "Levels", "Use levels and level roles?",
               "A #levelup channel in Misc for level-up messages, and roles at levels"
               " 5, 10, 20, 30 and 50."),
    "voice": ("\U0001f50a", "Voice rooms", "Make voice channels with Join To Create?",
              "Voice Channels: vc I, II and III. Private Vcs: vc-info and Join To Create,"
              " where everyone gets their own room."),
    "automod": ("\U0001f916", "Automod", "Switch on automod?",
                "Deletes invite links, mass mentions and spam, and warns or jails the sender."),
    "antinuke": ("\U0001f6a8", "Antinuke", "Switch on the antinuke?",
                 "Stops anyone (even an admin) mass-banning, deleting channels or roles,"
                 " or adding bots, strips their roles and undoes what it can."
                 " Only the server owner can switch it on."),
    "antialt": ("\U0001f575\ufe0f", "Anti-alt", "Catch ban evaders' new accounts?",
                "Accounts under 7 days old are jailed when they join, and look-alikes of"
                " hardbanned users are flagged to staff."),
}
PARTS = tuple(STEPS)
YES, NO = "\u2705", "\u2716\ufe0f"

class Build:
    """One run of the builder: makes what's missing, remembers what it did."""

    def __init__(self, bot, guild, prefix: str, author=None):
        self.bot, self.guild, self.db, self.prefix = bot, guild, bot.db, prefix
        self.author = author
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
        mod = await self.category(MOD_CAT, self.staff_only())
        jail = await self.text("jail", mod, self.staff_only([jailed]),
                               topic="Jailed members talk to staff here.")
        self.db.set_mod_config(self.guild.id, "jail_channel", jail.id)
        await self.text("moderator-only", mod, topic="Staff chat.")
        await self.voice("jail vc", mod, self.staff_only([jailed]))
        await self.voice("mod vc", mod)
        logs = await self.category(LOGS_CAT, self.staff_only())
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
        must = await self.category(MUST_READ, self.staff_only())
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

    async def build_welcome(self):
        top = await self.category(IMPORTANT)
        welcome = await self.text(f"{TOP_MARK}welcome", top, self.read_only())
        for kind in ("welcome", "goodbye"):
            if not self.guild.get_channel(self.db.greeting(self.guild.id, kind)["channel_id"]):
                self.db.set_greeting(self.guild.id, kind, channel_id=welcome.id)

    def boosters_only(self):
        booster = getattr(self.guild, "premium_subscriber_role", None)
        if booster is None:
            return None
        can = discord.PermissionOverwrite(view_channel=True, send_messages=True)
        return {self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                self.guild.me: can, booster: can}

    async def build_channels(self):
        top = await self.category(IMPORTANT)
        for name in ("announcements", "giveaways"):
            await self.text(f"{TOP_MARK}{name}", top, self.read_only())
        await self.text(f"{TOP_MARK}rules", top, self.read_only(), topic="Read these first.")
        text = await self.category(TEXT)
        await self.text(f"{TOP_MARK}general", text)
        boosters = self.boosters_only()
        if boosters:
            await self.text(f"{TOP_MARK}booster-general", text, boosters,
                            topic="Thank you for boosting.")
        misc = await self.category(MISC)
        await self.text(f"{MISC_MARK}bot-commands", misc)
        media = await self.category(MEDIA)
        for name in ("artwork", "media", "face-reveal", "hall-of-shame", "edits"):
            await self.text(f"{MEDIA_MARK}{name}", media)

    async def build_member(self):
        gid = self.guild.id
        member = await self.role(*MEMBER)
        self.db.replace_autoroles(gid, [*self.db.autoroles_of(gid), member.id])

    async def build_gacha(self):
        misc = await self.category(MISC)
        gacha = await self.text(f"{MISC_MARK}paper", misc,
                                topic=f"Roll with {self.prefix}w, {self.prefix}h"
                                      f" and {self.prefix}m.")
        if not self.db.allowed_channels(self.guild.id):
            self.db.allow_channel(self.guild.id, gacha.id)

    async def build_levels(self):
        gid = self.guild.id
        pairs = []
        for level, name, colour, second in LEVEL_ROLES:
            role = await self.role(name, colour, second, hoist=level >= 20)
            pairs.append((level, role.id))
        existing = {lvl: rid for lvl, rid in
                    ((r["level"], r["role_id"]) for r in self.db.level_roles_of(gid))}
        existing.update(dict(pairs))
        self.db.replace_level_roles(gid, sorted(existing.items()))
        misc = await self.category(MISC)
        level_ups = await self.text(f"{MISC_MARK}levelup", misc, self.read_only())
        levels = self.bot.get_cog("Levels")
        if levels:
            levels.save_settings(gid, {"channel": level_ups.id})

    async def build_voice(self):
        voice = await self.category(VOICE)
        for number in ("I", "II", "III"):
            await self.voice(f"{VC_MARK} {number}", voice)
        private = await self.category(PRIVATE_VC)
        info = await self.text("vc-info", private, self.read_only(),
                               topic="How your own voice room works.")
        join = await self.voice("Join To Create", private)
        if not self.guild.get_channel(self.db.get_vc_setting(self.guild.id, "create_channel")):
            self.db.set_vc_setting(self.guild.id, "create_channel", join.id)
        if "#vc-info" in self.made and hasattr(info, "send"):
            p = self.prefix
            try:
                await info.send(
                    "**Your own voice room**\n"
                    f"Join **Join To Create** and Paper makes you a room. It's yours:\n"
                    f"`{p}vc lock` / `{p}vc unlock` · `{p}vc hide` / `{p}vc unhide`\n"
                    f"`{p}vc rename <name>` · `{p}vc limit <number>`\n"
                    f"`{p}vc permit @someone` · `{p}vc ban @someone`\n"
                    f"`{p}vc claim` takes over a room its owner left."
                    " The room goes away when everyone leaves.")
            except discord.HTTPException:
                pass

    def switch_on(self, label: str, is_on: bool, turn_on):
        """A setting rather than a channel: counted as kept if it was already on."""
        if is_on:
            self.kept.append(label)
            return
        turn_on()
        self.made.append(label)

    async def build_automod(self):
        # Spam is a Premium filter, and the builder is Plus, so it's there.
        gid, keys = self.guild.id, ("invites", "mentions", "spam")
        on = self.db.automod_all(gid)

        def turn_on():
            for key in keys:
                self.db.set_automod(gid, f"{key}_on", 1)
        self.switch_on("automod: invites, mass mentions, spam",
                       all(on.get(f"{k}_on") == "1" for k in keys), turn_on)

    def owner_ran_it(self) -> bool:
        uid = getattr(self.author, "id", None)
        return uid is not None and (
            uid == getattr(self.guild, "owner_id", None) or uid in config.OWNERS
            or uid in self.db.antinuke_people(self.guild.id, "admin"))

    async def build_antinuke(self):
        if not self.owner_ran_it():
            self.problems.append(f"The antinuke is the owner's to switch on: ask them to"
                                 f" run `{self.prefix}antinuke on`.")
            return
        gid = self.guild.id
        self.switch_on("antinuke: on", self.db.antinuke_get(gid, "enabled") == 1,
                       lambda: self.db.antinuke_set(gid, "enabled", 1))

    async def build_antialt(self):
        gid = self.guild.id
        self.switch_on("anti-alt: on", self.db.antinuke_get(gid, "alt:enabled") == 1,
                       lambda: self.db.antinuke_set(gid, "alt:enabled", 1))
        if not self.punishment("jail_role"):
            self.problems.append("Anti-alt kicks new accounts until there's a jail: say yes"
                                 " to the staff area, or run "
                                 f"`{self.prefix}setupmod`.")

    async def run(self, parts):
        # The categories go in first, in the layout's order, so they line up
        # however the steps fill them; the staff ones are moved down after.
        for category in LAYOUT:
            if any(category in NEEDS.get(part, ()) for part in parts):
                await self.category(category)
        for part in STEPS:
            if part in parts:
                await getattr(self, f"build_{part}")()
        await self.staff_to_the_bottom()

    async def staff_to_the_bottom(self):
        """MUST READ, mod and logs below everything else, in that order."""
        for name in STAFF_CATEGORIES:
            category = discord.utils.get(self.guild.categories, name=name)
            if category is None:
                continue
            try:
                await category.move(end=True, reason="$serversetup")
            except discord.HTTPException:
                self.problems.append(f"I couldn't move **{name}** to the bottom;"
                                     " drag it down yourself.")


class SetupWizard(discord.ui.View):
    """One question at a time: yes or no to each part, then build."""

    def __init__(self, cog, ctx):
        super().__init__(timeout=600)
        self.cog, self.ctx = cog, ctx
        self.keys = list(STEPS)
        self.answers = {}            # key -> True / False
        self.at = 0
        self.message = None
        self.show()

    # ----------------------------------------------------------- screens

    def show(self):
        self.clear_items()
        if self.at < len(self.keys):
            for item in (self.yes, self.no, self.back, self.rest, self.cancel):
                self.add_item(item)
            self.back.disabled = self.at == 0
        else:
            for item in (self.build_button, self.again, self.cancel):
                self.add_item(item)
            self.build_button.disabled = not any(self.answers.values())

    def embed(self) -> discord.Embed:
        if self.at >= len(self.keys):
            picked = [k for k in self.keys if self.answers.get(k)]
            skipped = [k for k in self.keys if not self.answers.get(k)]
            lines = [f"\u2705 {STEPS[k][0]} **{STEPS[k][1]}**" for k in picked]
            if skipped:
                lines.append("\nSkipped: " + ", ".join(STEPS[k][1] for k in skipped))
            embed = discord.Embed(title="\U0001f3d7\ufe0f Ready to build",
                                  description="\n".join(lines) or "Nothing picked.",
                                  colour=0xE5C55A)
            embed.set_footer(text="Anything already here with the same name is kept,"
                                  " so it's safe to run again.")
            return embed
        key = self.keys[self.at]
        emoji, title, question, what = STEPS[key]
        embed = discord.Embed(title=f"{emoji} {question}", description=what, colour=0xE5C55A)
        done = [(YES if self.answers[k] else NO) + " " + STEPS[k][1]
                for k in self.keys[:self.at]]
        if done:
            embed.add_field(name="So far", value=" \u00b7 ".join(done)[:1024], inline=False)
        embed.set_footer(text=f"Step {self.at + 1} of {len(self.keys)} \u00b7 {title}")
        return embed

    async def move(self, interaction, answer=None, to=None):
        if answer is not None:
            self.answers[self.keys[self.at]] = answer
            self.at += 1
        if to is not None:
            self.at = to
        self.show()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("Only whoever ran it can answer.",
                                                    ephemeral=True)
            return False
        return True

    # ----------------------------------------------------------- buttons

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success, emoji="\u2705")
    async def yes(self, interaction, button):
        await self.move(interaction, True)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary, emoji="\u2716\ufe0f")
    async def no(self, interaction, button):
        await self.move(interaction, False)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary, emoji="\u25c0\ufe0f")
    async def back(self, interaction, button):
        await self.move(interaction, to=max(0, self.at - 1))

    @discord.ui.button(label="Yes to the rest", style=discord.ButtonStyle.primary,
                       emoji="\u23e9", row=1)
    async def rest(self, interaction, button):
        for key in self.keys[self.at:]:
            self.answers[key] = True
        await self.move(interaction, to=len(self.keys))

    @discord.ui.button(label="Build it", style=discord.ButtonStyle.success,
                       emoji="\U0001f3d7\ufe0f")
    async def build_button(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(
            content="\U0001f3d7\ufe0f Building\u2026 this takes a minute. Please don't run it twice.",
            embed=None, view=None)
        await self.cog.build(self.ctx, {k for k, v in self.answers.items() if v},
                             interaction.message)

    @discord.ui.button(label="Start over", style=discord.ButtonStyle.secondary,
                       emoji="\U0001f501")
    async def again(self, interaction, button):
        self.answers.clear()
        await self.move(interaction, to=0)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger, row=1)
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
        """Premium Plus: set the server up one question at a time: roles,
        channels, staff area, logs, a mod forum, and every part of Paper."""
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
        view = SetupWizard(self, ctx)
        view.message = await ctx.send(
            f"🏗️ **Let's set up {ctx.guild.name}.** {len(STEPS)} quick questions, yes or no;"
            " nothing is made until you press **Build it** at the end.\n"
            "-# First, drag Paper's role to the top of the role list, so it can manage"
            " everything it makes.",
            embed=view.embed(), view=view, allowed_mentions=discord.AllowedMentions.none())

    async def build(self, ctx, parts, message):
        guild = ctx.guild
        self.building.add(guild.id)
        run = Build(self.bot, guild, ctx.prefix, author=ctx.author)
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
            lines.append("Give your staff their roles"
                         + (", then read the how-to-mod forum." if "forum" in parts else "."))
        lines.append(f"`{ctx.prefix}dashboard` changes the rest, and `{ctx.prefix}serversetup`"
                     f" again adds anything you skipped.")
        text = "\n".join(lines)[:2000]
        try:
            await message.edit(content=text)
        except discord.HTTPException:
            await ctx.send(text)


async def setup(bot):
    await bot.add_cog(Builder(bot))
