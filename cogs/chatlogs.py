"""Chat logs: every deleted or edited message is posted to a channel staff pick.

$chatlog #channel   start logging there
$chatlog off        stop
$chatlog            show where it goes

Deletes, edits and purges are all logged. Discord only sends the old text of
a message the bot still remembers, so the bot keeps the last MESSAGE_CACHE
messages it has seen; anything older is logged without its text. Bots'
messages and the log channel itself are never logged.

Who deleted it: Discord's audit log records a mod deleting someone else's
message, but not people deleting their own, so no entry means the sender.
The audit log merges repeat deletes (same mod, same member, same channel)
into one entry with a rising count, so a delete is matched either by a new
entry or by a count that went up since the last look. Paper's own purge
commands announce themselves through expect(), since the audit log would
only name Paper.
"""
import asyncio
import io
import time
from collections import defaultdict
from typing import Optional

import discord
from discord.ext import commands

MESSAGE_CACHE = 10_000   # messages the bot remembers, across every server
SETTING = "chat_log_channel"
DELETED = 0xE74C3C
EDITED = 0xF1C40F
PURGED = 0x992D22
AUDIT_DELAY = 1.5   # seconds: the audit entry lands just after the delete event
AUDIT_FRESH = 20    # seconds: a never-seen entry older than this is an old one
EXPECT_FOR = 30     # seconds a purge command's claim on its channel lasts


def clip(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1] + "…"


def attachment_lines(message: discord.Message) -> list:
    lines = [f"📎 {a.filename}" for a in message.attachments]
    lines += [f"🏷️ sticker: {s.name}" for s in message.stickers]
    return lines


def purge_transcript(messages: list) -> str:
    """Plain text of a purge, oldest first, for the log's attachment."""
    out = []
    for m in sorted(messages, key=lambda m: m.created_at):
        stamp = m.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        extra = "".join(f" [{line}]" for line in attachment_lines(m))
        out.append(f"[{stamp}] {m.author} ({m.author.id}): {m.content}{extra}")
    return "\n".join(out)


class ChatLogs(commands.Cog):
    works_everywhere = True  # moderation, not gacha; see bot.check_allowed

    def __init__(self, bot):
        self.bot = bot
        self.expected = {}                      # channel id -> (moderator, command, until)
        self.audit_counts = defaultdict(dict)   # guild id -> {entry id: count}
        self.audit_locks = defaultdict(asyncio.Lock)

    @property
    def db(self):
        return self.bot.db

    def log_channel(self, guild_id: Optional[int], source_channel_id: int):
        """The chat log channel, or None if it's off or this is that channel."""
        if not guild_id:
            return None
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        channel = guild.get_channel(self.db.get_mod_config(guild_id, SETTING))
        if not channel or channel.id == source_channel_id:
            return None
        return channel

    async def post(self, channel, embed, file=None):
        try:
            await channel.send(embed=embed, file=file,
                               allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            pass  # missing permissions or the channel is gone: nothing to do

    def author_line(self, embed, author):
        embed.set_author(name=f"{author} ({author.id})",
                         icon_url=author.display_avatar.url)

    # -------------------------------------------------------- who did it

    def expect(self, channel_id: int, moderator, command: str):
        """A Paper command is about to delete messages here for a moderator."""
        self.expected[channel_id] = (moderator, command, time.time() + EXPECT_FOR)

    async def audit_entry(self, guild, channel_id: int, author_id: Optional[int], bulk: bool):
        """The audit log entry for this delete, or None if there isn't one."""
        await asyncio.sleep(AUDIT_DELAY)
        action = (discord.AuditLogAction.message_bulk_delete if bulk
                  else discord.AuditLogAction.message_delete)
        seen = self.audit_counts[guild.id]
        found = None
        async with self.audit_locks[guild.id]:
            try:
                entries = [e async for e in guild.audit_logs(action=action, limit=10)]
            except discord.HTTPException:
                return None
            now = discord.utils.utcnow()
            for entry in entries:
                count = getattr(entry.extra, "count", None) or 1
                before = seen.get(entry.id)
                seen[entry.id] = count
                if found:
                    continue
                if bulk:
                    where = getattr(entry.target, "id", None)
                else:
                    where = getattr(getattr(entry.extra, "channel", None), "id", None)
                    if author_id and getattr(entry.target, "id", None) != author_id:
                        continue
                if where != channel_id:
                    continue
                if before is None:
                    if (now - entry.created_at).total_seconds() <= AUDIT_FRESH:
                        found = entry
                elif count > before:
                    found = entry
            if len(seen) > 200:  # only recent entries ever matter
                for old in sorted(seen)[:-50]:
                    del seen[old]
        return found

    async def deleted_by(self, guild, channel_id: int, author_id: Optional[int],
                         bulk: bool = False) -> str:
        """Who deleted it, written for the log."""
        claim = self.expected.get(channel_id)
        if claim and claim[2] > time.time():
            return f"{claim[0].mention} with `{claim[1]}`"
        me = guild.me
        if not me or not me.guild_permissions.view_audit_log:
            return "Unknown: give Paper **View Audit Log** to see who"
        entry = await self.audit_entry(guild, channel_id, author_id, bulk)
        if entry and entry.user:
            if entry.user.id == me.id:
                return "Paper (automod or one of its commands)"
            who = entry.user.mention + (" (a bot)" if entry.user.bot else "")
            if entry.reason:
                who += f"\nReason: {clip(entry.reason, 200)}"
            return who
        if bulk:
            return "Unknown"
        return "The sender" if author_id else "Probably the sender"

    # ---------------------------------------------------------- listeners

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        channel = self.log_channel(payload.guild_id, payload.channel_id)
        if not channel:
            return
        message = payload.cached_message
        if message and message.author.bot:
            return
        embed = discord.Embed(colour=DELETED, timestamp=discord.utils.utcnow())
        if message:
            self.author_line(embed, message.author)
            body = clip(message.content, 3500) or "*no text*"
            extras = attachment_lines(message)
            if extras:
                body += "\n\n" + "\n".join(extras)
            embed.description = f"**Message deleted in <#{payload.channel_id}>**\n{body}"
            embed.add_field(name="Sent", value=discord.utils.format_dt(message.created_at, "R"))
        else:
            embed.description = (f"**Message deleted in <#{payload.channel_id}>**\n"
                                 "*It was sent before Paper last restarted or is too old,"
                                 " so its text wasn't saved.*")
        embed.add_field(name="Deleted by", value=await self.deleted_by(
            channel.guild, payload.channel_id, message.author.id if message else None))
        embed.set_footer(text=f"Message {payload.message_id}")
        await self.post(channel, embed)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        channel = self.log_channel(payload.guild_id, payload.channel_id)
        if not channel:
            return
        known = [m for m in payload.cached_messages if not m.author.bot]
        unknown = len(payload.message_ids) - len(payload.cached_messages)
        embed = discord.Embed(
            colour=PURGED, timestamp=discord.utils.utcnow(),
            description=(f"**{len(payload.message_ids)} messages purged in"
                         f" <#{payload.channel_id}>**"))
        if unknown:
            embed.description += f"\n{unknown} were too old to have their text saved."
        file = None
        if known:
            file = discord.File(io.BytesIO(purge_transcript(known).encode("utf-8")),
                                filename=f"purge-{payload.channel_id}.txt")
            embed.description += "\nThe saved ones are in the attached file."
        embed.add_field(name="Deleted by", value=await self.deleted_by(
            channel.guild, payload.channel_id, None, bulk=True))
        await self.post(channel, embed, file)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        after = payload.message
        if not after or after.author.bot:
            return
        before = payload.cached_message
        # Discord also "edits" a message when it adds a link preview; skip those.
        if before is not None and before.content == after.content:
            return
        channel = self.log_channel(payload.guild_id, payload.channel_id)
        if not channel:
            return
        embed = discord.Embed(
            colour=EDITED, timestamp=discord.utils.utcnow(),
            description=f"**Message edited in <#{payload.channel_id}>** · [jump]({after.jump_url})")
        self.author_line(embed, after.author)
        embed.add_field(name="Before", inline=False, value=(
            clip(before.content, 1024) or "*no text*") if before
            else "*Not saved: sent before Paper last restarted or too old.*")
        embed.add_field(name="After", value=clip(after.content, 1024) or "*no text*",
                        inline=False)
        embed.set_footer(text=f"Message {after.id}")
        await self.post(channel, embed)

    # ------------------------------------------------------------ command

    @commands.command(name="chatlog", aliases=["chatlogs", "messagelog"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def chatlog(self, ctx, channel: Optional[discord.TextChannel] = None, *, off: str = ""):
        """Post every deleted and edited message to a channel."""
        if channel is None and off.lower() in ("off", "stop", "disable", "none"):
            self.db.set_mod_config(ctx.guild.id, SETTING, 0)
            return await ctx.send("Chat logs are off.")
        if channel is None:
            current = ctx.guild.get_channel(self.db.get_mod_config(ctx.guild.id, SETTING))
            if current:
                return await ctx.send(
                    f"Deleted and edited messages go to {current.mention}."
                    f" `{ctx.prefix}chatlog off` stops it.")
            return await ctx.send(
                f"Chat logs are off. Turn them on with `{ctx.prefix}chatlog #channel`"
                " (a channel only staff can see).")
        me = channel.permissions_for(ctx.guild.me)
        if not (me.send_messages and me.embed_links and me.attach_files):
            return await ctx.send(
                f"I need Send Messages, Embed Links and Attach Files in {channel.mention}.")
        self.db.set_mod_config(ctx.guild.id, SETTING, channel.id)
        warning = ""
        if channel.permissions_for(ctx.guild.default_role).view_channel:
            warning += ("\n⚠️ Everyone can see that channel, so deleted messages"
                        " would be public. Make it staff-only.")
        if not ctx.guild.me.guild_permissions.view_audit_log:
            warning += ("\n⚠️ Give me **View Audit Log** so the log can say which"
                        " mod deleted a message.")
        await ctx.send(f"Deleted and edited messages will be posted in {channel.mention}."
                       + warning)


async def setup(bot):
    await bot.add_cog(ChatLogs(bot))
