"""Entry point. Run with: python bot.py"""
import logging
import sys

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
    "cogs.admin",
    "cogs.settings",
    "cogs.help",
]


class GachaBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # needed for prefix commands
        intents.members = True  # needed to resolve @mentions in trades
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.PREFIX),
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self.db = Database()
        self.cooldowns = Cooldowns(self.db)

    async def setup_hook(self):
        # Shard icons prefer custom emoji uploaded to the server.
        utils.use_emoji_from(self)
        for cog in COGS:
            await self.load_extension(cog)
            log.info("loaded %s", cog)

    async def on_ready(self):
        log.info("logged in as %s (%s guilds)", self.user, len(self.guilds))
        log.info("%s characters in the pool", self.db.character_count())
        await self.change_presence(
            activity=discord.Game(name=f"{config.PREFIX}help | {config.PREFIX}w")
        )

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
