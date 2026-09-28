"""Entry point. Run with: python bot.py"""
import asyncio
import difflib
import json
import logging
import os
import sys
import time

import discord
from discord.ext import commands

import backup
import config
import views
from db import Database
import utils
from utils import Cooldowns

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("gacha")

COGS = [
    "cogs.rolling",
    "cogs.harem",
    "cogs.karuda",
    "cogs.wishlist",
    "cogs.trading",
    "cogs.shop",
    "cogs.likes",
    "cogs.bulk",
    "cogs.profile",
    "cogs.serverconfig",
    "cogs.access",
    "cogs.custom",
    "cogs.progress",
    "cogs.bonds",
    "cogs.games",
    "cogs.admin",
    "cogs.settings",
    "cogs.toggles",
    "cogs.fun",
    "cogs.notes",
    "cogs.moderation",
    "cogs.staffpoints",
    "cogs.modtools",
    "cogs.modsettings",
    "cogs.voice",
    "cogs.levels",
    "cogs.events",
    "cogs.champions",
    "cogs.automod",
    "cogs.customizer",
    "cogs.utility",
    "cogs.serversetup",
    "cogs.backups",
    "cogs.dashboard",
    "cogs.aliases",
    "cogs.tea",
    "cogs.leaderboards",
    "cogs.about",
    "cogs.haremextra",
    "cogs.tutorial",
    "cogs.personalise",
    "cogs.find",
    "cogs.help",
]


# How alike a typo has to be before the bot guesses. 0.72 catches harme/harem
# and rol/roll without offering $roll to somebody who typed a word that merely
# starts with r.
SUGGEST_CUTOFF = 0.72


def suggestion_for(typed: str, names, cutoff: float = SUGGEST_CUTOFF) -> str:
    """The command a mistyped name was probably reaching for, or "".

    Separate from the bot so the rules are testable: most of this is about
    what NOT to guess at. "$20" and "$5 each" are money, "$" on its own is a
    stray keystroke, and anything long or punctuated is somebody talking
    rather than somebody typing a command badly.
    """
    typed = (typed or "").lower()
    if len(typed) < 2 or len(typed) > 24:
        return ""
    if not typed[0].isalpha() or not typed.replace("_", "").isalnum():
        return ""
    close = difflib.get_close_matches(typed, names, n=1, cutoff=cutoff)
    if not close or close[0] == typed:
        return ""
    return close[0]


def permission_names(missing) -> str:
    """['manage_guild', 'ban_members'] -> 'Manage Server and Ban Members'."""
    names = [p.replace("guild", "server").replace("_", " ").title()
             for p in missing]
    return " and ".join(names)


class GachaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # needed for prefix commands
        intents.members = True  # needed to resolve @mentions in trades
        super().__init__(
            command_prefix=self._prefix_for,
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        # A backup parked by $restore goes in before the database opens.
        if backup.apply_pending(config.DB_PATH):
            log.warning("restored the database from a backup")
        self.db = Database()
        self.started_at = time.time()
        self.cooldowns = Cooldowns(self.db)
        # Filled the first time a typo needs guessing at, after the cogs are
        # loaded - asking for it here would find no commands at all.
        self._command_names = None

    async def _prefix_for(self, bot, message):
        """Servers can set their own prefix; mentions always work."""
        custom = None
        if message.guild:
            custom = self.db.get_prefix(message.guild.id)
        return commands.when_mentioned_or(custom or config.PREFIX)(bot, message)

    async def on_guild_join(self, guild):
        self.db.note_guild(guild.id)

    async def check_allowed(self, ctx) -> bool:
        """Global gate: disabled commands, and the channel allow list.

        Runs before every command. Owner commands ignore it, so a server
        cannot lock the bot owner out of their own bot.
        """
        if ctx.guild is None:
            return True
        self.db.note_guild(ctx.guild.id)
        if ctx.author.id in config.OWNERS:
            return True

        # Staff and voice commands work everywhere: a server that keeps the
        # gacha to one channel still needs $jail in general and $vc lock in
        # the voice channel's own chat.
        anywhere = getattr(ctx.cog, "works_everywhere", False)
        allowed = self.db.allowed_channels(ctx.guild.id)
        if allowed and ctx.channel.id not in allowed and not anywhere:
            return False
        if ctx.command and ctx.command.name in self.db.disabled_commands(ctx.guild.id):
            raise commands.DisabledCommand()
        return True

    async def setup_hook(self):
        # Shard icons prefer custom emoji uploaded to the server.
        utils.use_emoji_from(self)
        self.add_check(self.check_allowed)
        for cog in COGS:
            await self.load_extension(cog)
            log.info("loaded %s", cog)

    async def on_ready(self):
        log.info("logged in as %s (%s guilds)", self.user, len(self.guilds))
        log.info("database: %s", os.path.abspath(config.DB_PATH))
        if config.DB_PERSISTS:
            log.info("this database survives a redeploy")
        else:
            log.warning(
                "NO VOLUME MOUNTED - every claim, balance and tutorial on"
                " this bot will be lost the next time it is deployed."
                " Attach a volume and redeploy; nothing else needs changing."
            )
        await self._seed_pool()
        # Outside _seed_pool on purpose: that returns early once the pool has
        # anything in it, and art arrives in batches long after the roster.
        await self._seed_art()
        await self._seed_secrets()
        await self._sync_emojis()
        log.info("%s characters in the pool", self.db.character_count())

    async def _seed_pool(self):
        """Load the shipped roster if the pool is empty.

        Saves running $import by hand on a fresh database, which is exactly
        the moment somebody is least likely to know they have to.
        """
        # A restored backup carries only the characters something points at;
        # it's marked, and the rest of the roster is loaded back in here.
        trimmed = self.db.get_pref(0, "backup_trimmed", 0)
        if self.db.character_count() and not trimmed:
            return
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "characters.json")
        if not os.path.exists(path):
            log.warning("no roster at %s - use %simport", path, config.PREFIX)
            return
        log.info("empty pool, loading %s", path)
        try:
            batch, loaded = [], 0
            for record in utils.iter_roster(path):
                batch.append(record)
                if len(batch) >= 10000:
                    loaded += (await asyncio.to_thread(
                        self.db.import_characters, batch))["total"]
                    batch.clear()
            if batch:
                loaded += (await asyncio.to_thread(
                    self.db.import_characters, batch))["total"]
            log.info("loaded %s characters", f"{loaded:,}")
            if trimmed:
                self.db.set_pref(0, "backup_trimmed", 0)
        except Exception:  # noqa: BLE001 - a bad roster must not stop the bot
            log.exception("could not load the roster; use %simport",
                          config.PREFIX)
        await self.change_presence(
            activity=discord.Game(name=f"{config.PREFIX}help | {config.PREFIX}w")
        )

    async def _seed_art(self):
        """Top up character albums from the shipped extra art.

        Unlike the roster this runs on every boot, because art arrives in
        batches long after the characters do. It is skipped when the file has
        not changed since it was last applied - the inserts are harmless
        either way, but a few hundred thousand of them on every restart is
        not a thing to do for nothing.
        """
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "character_art.json")
        if not os.path.exists(path):
            return

        # Size and mtime together: enough to notice a new file, and cheaper
        # than hashing 20MB on a cold start.
        info = os.stat(path)
        stamp = (int(info.st_mtime) * 1000003) ^ info.st_size
        # Guild 0 is not a guild - snowflakes are never zero - so it serves
        # as the slot for facts about the bot rather than about a server.
        if self.db.get_pref(0, "art_stamp", 0) == stamp:
            return

        try:
            def apply():
                with open(path, encoding="utf-8") as handle:
                    art = json.load(handle)
                entries = []
                for key, urls in art.items():
                    name, _, series = key.partition("\x1f")
                    if name and urls:
                        entries.append((name, series, urls))
                # Official art replaces the fan art the first collector
                # shipped; both are the art file's to manage.
                return self.db.add_art(
                    entries, source="official",
                    replace=("safebooru", "official"),
                ), len(entries)

            added, characters = await asyncio.to_thread(apply)
            self.db.set_pref(0, "art_stamp", stamp)
            if added:
                log.info("added %s images across %s characters",
                         f"{added:,}", f"{characters:,}")
        except Exception:  # noqa: BLE001 - art is a nicety, not a reason to die
            log.exception("could not load the extra art")

    # The series every secret character is filed under. It is what $im
    # shows beneath the name, and a real series could never be called this.
    SECRET_SERIES = "Secret"

    async def _seed_secrets(self):
        """Load the rollable secret characters from data/secret_characters.json.

        Every boot, and cheap: there are a handful of them. Anyone taken off
        the list stops rolling but is not deleted, so a claim survives.
        """
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "secret_characters.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as handle:
                people = json.load(handle).get("characters", [])
            listed = []
            for person in people:
                images = person.get("bot_images") or []
                if not person.get("rollable") or not images:
                    continue
                self.db.upsert_secret(
                    person["name"], self.SECRET_SERIES, images,
                    value=person.get("value", 2000),
                    odds=person.get("odds", 20000),
                    gender=person.get("gender", ""),
                )
                listed.append(person["name"])
            retired = self.db.retire_secrets(listed)
            if listed:
                log.info("%s secret character(s) can be rolled", len(listed))
            if retired:
                log.info("%s secret character(s) retired", retired)
        except Exception:  # noqa: BLE001 - a bad list must not stop the bot
            log.exception("could not load the secret characters")

    # Where the bot's own artwork lives, and what each folder's emoji are
    # called. Badges are prefixed because "gold" and "paper" are words a
    # server might already have an emoji for.
    EMOJI_SOURCES = (("assets/badges", "badge"), ("assets/shards", ""))

    async def _sync_emojis(self):
        """Upload the bot's icons to itself, once, and remember them.

        Application emoji belong to the bot rather than to a server, so they
        work everywhere it is and nobody has to paste anything into Server
        Settings. Discord allows two thousand; this uploads about fifteen,
        and only the ones that are not there already.
        """
        root = os.path.dirname(os.path.abspath(__file__))
        try:
            existing = {emoji.name: emoji
                        for emoji in await self.fetch_application_emojis()}
        except discord.HTTPException:
            log.warning("could not read the bot's own emoji; using plain ones")
            return

        added = 0
        for folder, prefix in self.EMOJI_SOURCES:
            directory = os.path.join(root, folder)
            if not os.path.isdir(directory):
                continue
            for entry in sorted(os.listdir(directory)):
                # _preview.png is a contact sheet for people, not an icon.
                if not entry.endswith(".png") or entry.startswith("_"):
                    continue
                name = prefix + os.path.splitext(entry)[0]
                if name in existing:
                    continue
                try:
                    with open(os.path.join(directory, entry), "rb") as handle:
                        existing[name] = await self.create_application_emoji(
                            name=name, image=handle.read())
                    added += 1
                except discord.HTTPException as error:
                    log.warning("could not upload emoji %s: %s", name, error)

        utils.set_app_emojis({name: str(emoji)
                              for name, emoji in existing.items()})
        log.info("%s emoji ready%s", len(existing),
                 f", {added} newly uploaded" if added else "")

    def every_command_name(self):
        """Every name and alias the bot answers to, built once."""
        if self._command_names is None:
            names = set()
            for command in self.walk_commands():
                names.add(command.name.lower())
                names.update(alias.lower() for alias in command.aliases)
            self._command_names = sorted(names)
        return self._command_names

    async def suggest_command(self, ctx):
        """Offer the command a mistyped one was probably reaching for."""
        guess = suggestion_for(ctx.invoked_with, self.every_command_name())
        if not guess:
            return
        close = [guess]

        # Silent wherever the real command would have been silent: outside
        # the allowed channels, and for anything the server switched off.
        if ctx.guild is not None and ctx.author.id not in config.OWNERS:
            allowed = self.db.allowed_channels(ctx.guild.id)
            if allowed and ctx.channel.id not in allowed:
                return
            if close[0] in self.db.disabled_commands(ctx.guild.id):
                return

        prefix = ctx.prefix or config.PREFIX
        rest = ctx.message.content[len(prefix) + len(ctx.invoked_with):]
        view = views.DidYouMean(ctx.message, prefix, close[0], rest,
                                ctx.author.id)
        try:
            view.sent = await ctx.send(
                f"There is no `{prefix}{ctx.invoked_with}`."
                f" Did you mean `{prefix}{close[0]}`?",
                view=view,
            )
        except discord.HTTPException:
            pass

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            await self.suggest_command(ctx)
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(f"You need {permission_names(error.missing_permissions)}"
                           " for that.")
            return
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"I need {permission_names(error.missing_permissions)}"
                           " to do that. Check my role in Server Settings.")
            return
        if (isinstance(error, commands.CommandInvokeError)
                and isinstance(error.original, discord.Forbidden)):
            await ctx.send("Discord wouldn't let me do that. My role needs to"
                           " be above the roles of whoever I'm acting on.")
            return
        if isinstance(error, commands.NotOwner):
            await ctx.send("Owner-only command.")
            return
        if isinstance(error, (commands.BadArgument, commands.MissingRequiredArgument)):
            await ctx.send(f"Usage: `{config.PREFIX}{ctx.command.qualified_name} {ctx.command.signature}`")
            return
        if isinstance(error, commands.DisabledCommand):
            await ctx.send(
                f"`{ctx.command.name}` is switched off on this server."
            )
            return
        if isinstance(error, commands.CheckFailure):
            return  # wrong channel; staying quiet is the point
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This one only works in a server.")
            return
        log.exception("command error in %s", ctx.command, exc_info=error)
        await ctx.send("Something broke running that. Check the bot logs.")

    async def close(self):
        self.db.close()
        await super().close()


def die(message: str):
    """Print a plain-English setup error instead of a traceback."""
    print("\n" + "=" * 62)
    print(message.strip())
    print("=" * 62 + "\n")
    sys.exit(1)


def main():
    if not config.TOKEN or config.TOKEN.startswith("paste-"):
        die(
            """
SETUP NEEDED: the bot does not have a token yet.

Open the file called .env in this folder and replace
    DISCORD_TOKEN=paste-your-bot-token-here
with the token from your bot's page at
https://discord.com/developers/applications  (Bot tab -> Reset Token)

Step 2 of the README walks through it.
"""
        )

    if not config.OWNERS:
        log.warning(
            "BOT_OWNERS is empty in .env, so owner commands like $import and"
            " $addchar will not work. Put your own Discord user ID there."
        )

    bot = GachaBot()
    try:
        bot.run(config.TOKEN)
    except discord.LoginFailure:
        die(
            """
Discord rejected that token.

Most likely the token in .env is incomplete, has a stray space, or was
reset after you copied it. Go back to the Bot tab, click Reset Token,
and paste the new one.
"""
        )
    except discord.PrivilegedIntentsRequired:
        die(
            """
SETUP NEEDED: two switches are still off in the Developer Portal.

Go to https://discord.com/developers/applications -> your app -> Bot,
scroll to "Privileged Gateway Intents", and turn ON both:
    MESSAGE CONTENT INTENT
    SERVER MEMBERS INTENT
Click Save Changes, then run this again.
"""
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
