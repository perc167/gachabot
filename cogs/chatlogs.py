"""Chat logs: every deleted or edited message is posted to a channel staff pick.

$chatlog #channel   start logging there
$chatlog off        stop
$chatlog            show where it goes

Deletes, edits and purges are all logged. Discord only sends the old text of
a message the bot still remembers, so the bot keeps the last MESSAGE_CACHE
messages it has seen; anything older is logged without its text. Bots'
messages and the log channel itself are never logged.
"""
import io
from typing import Optional

import discord
from discord.ext import commands

MESSAGE_CACHE = 10_000   # messages the bot remembers, across every server
SETTING = "chat_log_channel"
DELETED = 0xE74C3C
EDITED = 0xF1C40F
PURGED = 0x992D22


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
            embed.description = (f"**Message deleted in <#{payload.channel_id}>**"
                                 f" by its sender or a mod\n{body}")
            embed.add_field(name="Sent", value=discord.utils.format_dt(message.created_at, "R"))
        else:
            embed.description = (f"**Message deleted in <#{payload.channel_id}>**\n"
                                 "*It was sent before Paper last restarted or is too old,"
                                 " so its text wasn't saved.*")
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
            warning = ("\n⚠️ Everyone can see that channel, so deleted messages"
                       " would be public. Make it staff-only.")
        await ctx.send(f"Deleted and edited messages will be posted in {channel.mention}."
                       + warning)


async def setup(bot):
    await bot.add_cog(ChatLogs(bot))
