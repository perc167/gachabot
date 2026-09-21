"""Entry point. Run with: python bot.py"""
import asyncio
import json
import logging
import os
import sys
import time

import discord
from discord.ext import commands

import config
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
        self.db = Database()
        self.started_at = time.time()
        self.cooldowns = Cooldowns(self.db)

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

        allowed = self.db.allowed_channels(ctx.guild.id)
        if allowed and ctx.channel.id not in allowed:
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
        log.info("%s characters in the pool", self.db.character_count())

    async def _seed_pool(self):
        """Load the shipped roster if the pool is empty.

        Saves running $import by hand on a fresh database, which is exactly
        the moment somebody is least likely to know they have to.
        """
        if self.db.character_count():
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
        except Exception:  # noqa: BLE001 - a bad roster must not stop the bot
            log.exception("could not load the roster; use %simport",
                          config.PREFIX)
        await self._seed_art()
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
                return self.db.add_art(entries), len(entries)

            added, characters = await asyncio.to_thread(apply)
            self.db.set_pref(0, "art_stamp", stamp)
            if added:
                log.info("added %s images across %s characters",
                         f"{added:,}", f"{characters:,}")
        except Exception:  # noqa: BLE001 - art is a nicety, not a reason to die
            log.exception("could not load the extra art")

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You need Manage Server for that.")
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
