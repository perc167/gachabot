"""Daily backups of the database, sent to the bot's owners by DM.

Every BACKUP_EVERY the bot makes a backup (backup.py) and DMs it, quietly,
to everyone in BOT_OWNERS. A DM is private and lives with Discord, not
Railway, so the copy survives even if Railway loses the database.

`$backup` sends one now. `$restore`, in a DM with the backup file
attached, checks it and swaps it in at the next restart.
"""
import asyncio
import io
import logging
import time

import discord
from discord.ext import commands, tasks

import backup
import config
from cogs.admin import is_bot_owner

BACKUP_EVERY = 24 * 3600
DM_LIMIT = 10 * 1024 * 1024      # what Discord lets a bot send in a DM
log = logging.getLogger("backups")


class Backups(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.daily.start()

    async def cog_unload(self):
        self.daily.cancel()

    async def send(self, reason: str) -> str:
        """Make a backup and DM it to every owner. Returns what happened."""
        if not config.OWNERS:
            return "Nobody is in BOT_OWNERS, so there's nobody to send it to."
        data, note = await asyncio.to_thread(backup.make, config.DB_PATH)
        size = f"{len(data) / 1024 / 1024:.1f} MB"
        if len(data) > DM_LIMIT:
            text = (f"⚠️ Today's backup is {size}, over Discord's {DM_LIMIT // 1024 // 1024} MB"
                    " limit, so it couldn't be sent. Turn on Railway's volume backups as well.")
            payload = {}
        else:
            text = (f"\U0001f5c4️ Paper backup, {backup.stamp()} ({reason}): {note}, {size}."
                    "\nKeep it somewhere safe. To restore, DM me `$restore` with this file attached.")
            payload = {"file": None}
        sent = 0
        for owner_id in config.OWNERS:
            try:
                user = self.bot.get_user(owner_id) or await self.bot.fetch_user(owner_id)
                if "file" in payload:
                    payload["file"] = discord.File(io.BytesIO(data),
                                                   filename=f"paper-backup-{backup.stamp()}.db.gz")
                await user.send(text, silent=True, **payload)
                sent += 1
            except discord.HTTPException:
                log.warning("couldn't DM the backup to %s", owner_id)
        self.bot.db.set_pref(0, "backup_at", int(time.time()))
        return f"Sent to {sent} of {len(config.OWNERS)} owners: {note}, {size}."

    @tasks.loop(hours=1)
    async def daily(self):
        last = self.bot.db.get_pref(0, "backup_at", 0)
        if time.time() - last < BACKUP_EVERY:
            return
        try:
            await self.send("daily")
        except Exception:  # noqa: BLE001 - a failed backup must not stop the loop
            log.exception("daily backup failed")

    @daily.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()

    @commands.command(name="backup")
    @is_bot_owner()
    async def backup_now(self, ctx):
        """Owner only: DM the owners a backup now."""
        async with ctx.typing():
            result = await self.send("asked for")
        await ctx.send(result)

    @commands.command(name="restore")
    @commands.dm_only()
    @is_bot_owner()
    async def restore(self, ctx):
        """Owner only, in DMs: attach a backup file to restore it at the next
        restart. The current database is kept beside it."""
        if not ctx.message.attachments:
            await ctx.send("Attach the backup file (paper-backup-....db.gz) to `$restore`.")
            return
        raw = await ctx.message.attachments[0].read()
        try:
            data = await asyncio.to_thread(backup.check, raw)
        except backup.BadBackup as e:
            await ctx.send(str(e))
            return
        await asyncio.to_thread(backup.stage, config.DB_PATH, data)
        await ctx.send("That backup checks out and is ready. Restart the bot (Railway →"
                       " the service → Restart) to swap it in. The current database is"
                       " kept as a copy, so this can be undone the same way.")


async def setup(bot):
    await bot.add_cog(Backups(bot))
