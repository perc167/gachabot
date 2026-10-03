"""Slash versions of every $ command, built from the $ commands themselves.

Nothing is written twice. Each slash command turns its options back into the
text a $ command would have been given and runs the very same command, with
the same checks, cooldowns, permissions, replies and error messages.

Discord allows 100 top-level slash commands and 25 inside each group, so:
  * TOP: the everyday commands keep their own name: /roll, /harem, /ban...
  * everything else sits in a group by area, following $help's sections:
    /mod warn-list, /levels role-add, /vc lock. A $ subcommand becomes
    "parent-child" inside its group, and when the group shares the parent's
    name the prefix goes: $vc lock is /vc lock, $vc on its own is /vc show.
Owner-only commands get no slash version.

The commands are only re-sent to Discord when they change (a checksum is
kept), since every deploy restarts the bot.
"""
import asyncio
import inspect
import json
import logging
import re
import typing
import zlib

import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands.view import StringView

import config
from cogs import help as help_cog

log = logging.getLogger("gacha.slash")

TOP_LIMIT = 100
GROUP_LIMIT = 25
OPTION_LIMIT = 25
NAME = re.compile(r"^[-_\w]{1,32}$")

# Everyday commands that get their own top-level name.
TOP = [
    # gacha
    "w", "h", "m", "wa", "wg", "ha", "hg", "ma", "mg", "tu", "mu", "daily", "dk",
    "rt", "us", "harem", "info", "divorce", "wish", "wishlist", "trade", "gift",
    "like", "profile", "top",
    # everyday
    "help", "snipe", "editsnipe", "afk", "userinfo", "serverinfo", "remind", "role",
    "steal", "level", "leaderboard", "upgrade", "dashboard",
    # moderation
    "jail", "unjail", "timeout", "untimeout", "warn", "warnings", "kick", "ban",
    "unban", "softban", "purge", "lockdown", "unlockdown", "history",
]

# $help section -> slash group. Commands outside $help are placed by EXTRA.
GROUPS = {
    "Rolling": "gacha", "Your harem": "gacha", "Shop": "gacha", "Trading": "gacha",
    "Artwork": "gacha",
    "Harem tools": "haremtools", "Clearing out": "haremtools", "Your words": "haremtools",
    "Karuda": "karuda", "Switches — karuda": "karuda",
    "Badges & tower": "tower", "Bonds": "bond",
    "Wishes": "wishes", "Likes": "wishes", "Wish settings": "wishes",
    "Games": "fun", "Toy box": "fun", "Word games": "words",
    "You": "paper", "About": "paper",
    "Your own characters": "custom",
    "Server admin": "admin", "Moderation": "admin",
    "Leaderboards": "board",
    "Tea": "tea", "Nicknames": "alias", "Finding things": "find", "Notes": "notes",
    "Resets — yours": "reset", "Resets — server": "reset",
    "Jail & mutes": "mod", "Warnings": "mod", "Kicks & bans": "mod",
    "Cleaning up": "modtools", "Records & names": "modtools",
    "Mod setup": "modsetup", "Staff points": "modsetup",
    "Levels": "levels", "Level setup": "levels",
    "Voice rooms": "vc", "Voice hours": "vc",
    "Premium": "premium", "Make Paper yours": "botprofile",
    "Automod": "automod", "Antinuke": "security", "Anti-alt": "security",
    "Utility": "util", "Welcome & roles": "welcome",
    "Auto replies & reaction roles": "auto",
    "Switches — pool": "toggle", "Switches — cards": "toggle",
}
EXTRA = {"tower": "tower", "fullresetcustimg": "reset", "waifu": "gacha",
         "husbando": "gacha", "roll": "gacha"}
# Where a $help section lists a command that belongs better elsewhere.
MOVE = {"note": "notes", "sitelist": "admin", "level background": "premium",
        "levels card": "premium", "leaderboard month": "premium"}

GROUP_INFO = {
    "gacha": "Rolling, your harem, the shop and artwork",
    "haremtools": "Sorting, renaming and clearing out your harem",
    "karuda": "Karuda: balance, paying and its switches",
    "tower": "Badges and the tower", "bond": "Soulmates and keys",
    "wishes": "Wishes and likes", "fun": "Toys and games", "words": "Word games",
    "paper": "About Paper, the tutorial and your account",
    "custom": "Your own characters", "admin": "Server settings for Paper",
    "board": "Gacha leaderboards", "tea": "Tea", "alias": "Character nicknames",
    "find": "Finding characters and owners", "notes": "Notes on your characters",
    "reset": "Resets for you or the whole server",
    "mod": "Jail, mutes, warnings and bans", "modtools": "Cleaning up, lockdowns and records",
    "modsetup": "Moderation setup, staff roles and staff points",
    "levels": "Levels: settings, roles and XP", "vc": "Voice rooms and voice hours",
    "premium": "Premium, events, champions and weekly reports",
    "botprofile": "Paper's name, picture and bio on this server",
    "automod": "Automod filters", "security": "Antinuke and anti-alt",
    "util": "Snipes, info and handy tools", "welcome": "Welcome, goodbye and autoroles",
    "auto": "Auto replies, auto reactions and reaction roles",
    "toggle": "Gacha switches: the pool and the cards",
}
# A $ group's own command, when the slash group has the same name.
BASE_NAME = {"vc": "help", "levels": "settings", "automod": "settings",
             "welcome": "set", "alias": "set"}


# ------------------------------------------------------------ the layout

def help_sections() -> dict:
    """Command name -> $help section title."""
    where = {}
    for _emoji, title, rows in help_cog.CATEGORIES:
        for name, _what in rows:
            where.setdefault(name, title)
    return where


def owner_only(command) -> bool:
    return any("is_owner" in getattr(check, "__qualname__", "") for check in command.checks)


def slash_route(command, sections: dict):
    """(group or None, name) for a $ command, or None if it gets no slash."""
    qualified = command.qualified_name
    if owner_only(command) or command.hidden:
        return None
    for name in (qualified, *command.aliases):  # /w is $waifu by its alias
        if name in TOP and " " not in qualified:
            return None, name
    group = MOVE.get(qualified) or GROUPS.get(sections.get(qualified, "")) or EXTRA.get(qualified)
    if group is None:
        return None
    parts = qualified.split()
    if parts[0] == group:
        name = "-".join(parts[1:]) or BASE_NAME.get(group, "show")
    else:
        name = "-".join(parts)
    return group, name


def slash_type(annotation):
    """The slash option type for a $ parameter's annotation."""
    if isinstance(annotation, commands.Greedy):
        return str
    origin, args = typing.get_origin(annotation), typing.get_args(annotation)
    if origin is typing.Union:
        inner = [a for a in args if a is not type(None)]
        if inner and all(a in (discord.Member, discord.User) for a in inner):
            return discord.User
        return slash_type(inner[0]) if len(inner) == 1 else str
    if origin is typing.Literal:
        ok = args and len(args) <= 25 and all(isinstance(a, str) for a in args)
        return annotation if ok else str
    if annotation in (discord.Member, discord.User):
        return discord.User
    if annotation is discord.Role or getattr(annotation, "__name__", "") == "FuzzyRole":
        return discord.Role
    if annotation in (discord.TextChannel, discord.VoiceChannel, int, float, bool):
        return annotation
    return str


def optional_typed(annotation) -> bool:
    """Optional[X]: the $ parser skips it when the next word doesn't fit."""
    return (typing.get_origin(annotation) is typing.Union
            and type(None) in typing.get_args(annotation))


def options_of(command) -> list:
    """[(name, slash type, required, $ parameter)] for a command."""
    out, optional_seen = [], False
    for name, param in command.clean_params.items():
        kind = slash_type(param.annotation)
        required = param.required and param.kind != param.VAR_POSITIONAL
        if not required:
            optional_seen = True
        elif optional_seen:  # Discord wants required options first
            required = False
        out.append((name.lower(), kind, required, param))
    try:
        source = inspect.getsource(command.callback)
    except (OSError, TypeError):
        source = ""
    if "ctx.message.attachments" in source and len(out) < OPTION_LIMIT:
        out.append(("file", discord.Attachment, False, None))
    return out[:OPTION_LIMIT]


def describe(command) -> str:
    text = (command.short_doc or command.help or "").strip().replace("`", "")
    text = re.sub(r"\s+", " ", text) or f"{config.PREFIX}{command.qualified_name}"
    return text if len(text) <= 100 else text[:99] + "…"


# ---------------------------------------------- options back into words

def quote(text: str) -> str:
    if text and not re.search(r'[\s"]', text):
        return text
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def token(value, raw: bool) -> str:
    if isinstance(value, (discord.Member, discord.User)):
        return f"<@{value.id}>"
    if isinstance(value, discord.Role):
        return f"<@&{value.id}>"
    if isinstance(value, (discord.abc.GuildChannel, discord.Thread,
                          app_commands.AppCommandChannel, app_commands.AppCommandThread)):
        return f"<#{value.id}>"
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return text if raw else quote(text)


def build_args(options: list, values: list) -> str:
    """The text a $ command would have been typed with."""
    words = []
    last_given = max((i for i, v in enumerate(values) if v is not None), default=-1)
    for i, ((_name, kind, _req, param), value) in enumerate(zip(options, values)):
        if kind is discord.Attachment or param is None:
            continue
        raw = param.kind in (param.KEYWORD_ONLY, param.VAR_POSITIONAL)
        if value is None:
            # A gap before something given: fill it with the $ default, or
            # leave it out where the $ parser skips a word that doesn't fit.
            if i > last_given or optional_typed(param.annotation):
                continue
            default = param.default
            if isinstance(default, (int, float, str)) and not isinstance(default, bool) \
                    and default != "":
                words.append(token(default, raw))
            continue
        words.append(token(value, raw))
    return " ".join(words)


# --------------------------------------------------------------- running

class MessageStandIn:
    """ctx.message for a slash command: the real (synthetic) message, except
    that reacting to it says the reaction instead, and deleting it is a no-op,
    since a slash command has no message of its own in the channel."""

    def __init__(self, message, ctx):
        object.__setattr__(self, "_message", message)
        object.__setattr__(self, "_ctx", ctx)

    def __getattr__(self, name):
        return getattr(self._message, name)

    async def add_reaction(self, emoji):
        await self._ctx.send(str(emoji))

    async def delete(self, *, delay=None):
        return None


class SlashContext(commands.Context):
    sent = False

    async def send(self, content=None, **kwargs):
        delete_after = kwargs.pop("delete_after", None)
        message = await super().send(content, **kwargs)
        self.sent = True
        if delete_after and message is not None:
            async def later():
                await asyncio.sleep(delete_after)
                try:
                    await message.delete()
                except discord.HTTPException:
                    pass
            asyncio.ensure_future(later())
        return message


def notify(bot, event: str, ctx):
    """Tell listeners (the tutorial, for one) without risking the command."""
    try:
        bot.dispatch(event, ctx)
    except Exception:
        log.exception("couldn't dispatch %s", event)


async def run(interaction: discord.Interaction, command, options: list, values: list):
    """Run a $ command for a slash command, exactly as typing it would."""
    bot = interaction.client
    await interaction.response.defer(thinking=True)
    ctx = await SlashContext.from_interaction(interaction)
    ctx.command = command
    ctx.invoked_with = command.name
    ctx.prefix = (bot.db.get_prefix(interaction.guild_id) if interaction.guild_id else None) \
        or config.PREFIX
    ctx.view = StringView(build_args(options, values))
    ctx.message = MessageStandIn(ctx.message, ctx)
    error = None
    try:
        notify(bot, "command", ctx)
        try:
            if await bot.can_run(ctx, call_once=True):
                await command.invoke(ctx)
            else:
                raise commands.CheckFailure("The global check once functions failed.")
        except commands.CommandError as exc:
            error = exc
            await bot.on_command_error(ctx, exc)
        else:
            notify(bot, "command_completion", ctx)
    except Exception:
        log.exception("slash /%s failed", command.qualified_name)
        if not ctx.sent:
            await ctx.send("Something broke running that. Check the bot logs.")
    if ctx.sent:
        return
    # Nothing was said (it posted elsewhere, or a check said no quietly):
    # don't leave "Paper is thinking..." hanging.
    try:
        await interaction.delete_original_response()
        if isinstance(error, commands.CheckFailure):
            await interaction.followup.send(
                "Paper's commands are switched off in this channel.", ephemeral=True)
    except discord.HTTPException:
        pass


def make_callback(command, options: list):
    """An async function with one argument per option, for app_commands to read."""
    space = {"run": run, "command": command, "options": options, "discord": discord}
    params = []
    for i, (name, kind, required, _param) in enumerate(options):
        space[f"_t{i}"] = kind
        params.append(f"{name}: _t{i}" + ("" if required else " = None"))
    names = ", ".join(name for name, *_ in options)
    source = (f"async def callback(interaction: discord.Interaction"
              f"{', ' if params else ''}{', '.join(params)}):\n"
              f"    return await run(interaction, command, options, [{names}])\n")
    exec(source, space)
    callback = space["callback"]
    if options:
        callback = app_commands.describe(**{
            name: ("a file to upload" if kind is discord.Attachment else name.replace("_", " "))
            for name, kind, *_ in options})(callback)
    return callback


def build_tree(bot) -> list:
    """Every slash command and group, ready for bot.tree. Also returns nothing
    twice: a $ command reached by two $help sections gets one slash route."""
    sections = help_sections()
    groups, top, seen = {}, [], set()
    for command in bot.walk_commands():
        route = slash_route(command, sections)
        if route is None or command.qualified_name in seen:
            continue
        seen.add(command.qualified_name)
        group_name, name = route
        options = options_of(command)
        if any(not NAME.match(n) for n, *_ in options):
            log.warning("no slash for %s: an option name Discord won't take", command)
            continue
        parent = None
        if group_name:
            parent = groups.get(group_name)
            if parent is None:
                parent = groups[group_name] = app_commands.Group(
                    name=group_name, description=GROUP_INFO.get(group_name, group_name))
        taken = {c.name for c in (parent.commands if parent else top)}
        for fallback in ("show", "overview", "main"):
            if name not in taken:
                break
            name = fallback  # a $ group's own command clashing with a real subcommand
        slash = app_commands.Command(name=name, description=describe(command),
                                     callback=make_callback(command, options), parent=parent)
        slash.extras["prefix_command"] = command.qualified_name
        if parent is not None:
            parent.add_command(slash)
        else:
            top.append(slash)
    return top + list(groups.values())


def checksum(tree) -> int:
    payload = [c.to_dict(tree) for c in tree.get_commands()]
    return zlib.crc32(json.dumps(payload, sort_keys=True).encode())


class Slash(commands.Cog):
    """Loads last, so every other cog's commands exist when it builds."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        for item in build_tree(self.bot):
            self.bot.tree.add_command(item)
        if self.bot.application_id:
            asyncio.ensure_future(self.sync())

    async def sync(self):
        crc = checksum(self.bot.tree)
        if self.bot.db.get_pref(0, "slash_crc", 0) == crc:
            return
        try:
            synced = await self.bot.tree.sync()
        except discord.HTTPException:
            log.exception("couldn't send the slash commands to Discord")
            return
        self.bot.db.set_pref(0, "slash_crc", crc)
        log.info("sent %d slash commands to Discord", len(synced))

    async def cog_unload(self):
        for item in list(self.bot.tree.get_commands()):
            self.bot.tree.remove_command(item.name)


async def setup(bot):
    await bot.add_cog(Slash(bot))
