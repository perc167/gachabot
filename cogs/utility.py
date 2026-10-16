"""Everyday commands, the ones people use most on bleed.

Snipes     $snipe, $editsnipe, $reactionsnipe, $clearsnipe. Kept in memory
           only, for SNIPE_FOR, and never written to the database.
AFK        $afk [reason]. Anyone who pings you is told; talking again ends it.
Info       $userinfo, $serverinfo, $roleinfo, $banner, $servericon,
           $membercount, $firstmessage.
Reminders  $remind 10m stretch, then $reminders to see or cancel them.
Translate  Reply to somebody with $translate, or $translate es hello.
Emoji      $steal <emoji>, or reply to a message with $steal.
Roles      $role @someone @role gives it, or takes it if they have it.
"""
import asyncio
import re
import time
from collections import defaultdict, deque

import aiohttp
import discord
from discord.ext import commands, tasks

import config
import translator
from converters import FuzzyRole
from cogs.modtools import parse_duration

SNIPE_FOR = 2 * 3600          # seconds a deleted or edited message stays snipable
SNIPE_KEEP = 25               # per channel
MAX_REMINDERS = 25            # per person
LONGEST_REMINDER = 365 * 86400
CUSTOM_EMOJI = re.compile(r"<(a?):(\w{2,32}):(\d{15,25})>")


def ago(seconds: float) -> str:
    seconds = int(max(0, seconds))
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def when(moment) -> str:
    """A Discord timestamp: the date, and how long ago."""
    stamp = int(moment.timestamp())
    return f"<t:{stamp}:D> (<t:{stamp}:R>)"


class Utility(commands.Cog):
    works_everywhere = True  # none of this is gacha; see bot.check_allowed

    def __init__(self, bot):
        self.bot = bot
        self.deleted = defaultdict(lambda: deque(maxlen=SNIPE_KEEP))
        self.edited = defaultdict(lambda: deque(maxlen=SNIPE_KEEP))
        self.unreacted = defaultdict(lambda: deque(maxlen=SNIPE_KEEP))
        self.afk = {}   # (guild, user) -> (reason, since)

    @property
    def db(self):
        return self.bot.db

    async def cog_load(self):
        self.afk = {(r["guild_id"], r["user_id"]): (r["reason"], r["since"])
                    for r in self.db.all_afk()}
        self.reminder_loop.start()

    async def cog_unload(self):
        self.reminder_loop.cancel()

    async def cog_check(self, ctx):
        if ctx.guild is None and ctx.command.name not in ("reminders", "remind"):
            raise commands.NoPrivateMessage()
        return True

    # -------------------------------------------------------------- snipes

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        if not (message.content or message.attachments or message.stickers):
            return
        self.deleted[message.channel.id].appendleft({
            "author": message.author, "content": message.content,
            "files": [(a.filename, a.proxy_url, (a.content_type or "").startswith("image"))
                      for a in message.attachments],
            "stickers": [s.name for s in message.stickers],
            "at": time.time(),
        })

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        self.edited[before.channel.id].appendleft({
            "author": before.author, "before": before.content, "after": after.content,
            "link": after.jump_url, "at": time.time(),
        })

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id) if guild else None
        if member is None or member.bot:
            return
        link = (f"https://discord.com/channels/{payload.guild_id}/{payload.channel_id}"
                f"/{payload.message_id}")
        self.unreacted[payload.channel_id].appendleft({
            "author": member, "emoji": str(payload.emoji), "link": link, "at": time.time(),
        })

    def fresh(self, store, channel_id: int) -> list:
        cutoff = time.time() - SNIPE_FOR
        return [item for item in store.get(channel_id, ()) if item["at"] >= cutoff]

    async def pick(self, ctx, store, index: int, what: str):
        items = self.fresh(store, ctx.channel.id)
        if not items:
            await ctx.send(f"There's nothing to snipe here. {what.capitalize()} messages"
                           f" stay snipable for {SNIPE_FOR // 3600} hours.")
            return None, 0
        if not 1 <= index <= len(items):
            await ctx.send(f"There {'is' if len(items) == 1 else 'are'} only {len(items)}"
                           f" {what} message{'s' if len(items) != 1 else ''} to snipe here.")
            return None, 0
        return items[index - 1], len(items)

    @staticmethod
    def author_embed(item, colour=config.CARD_COLOUR) -> discord.Embed:
        embed = discord.Embed(colour=colour)
        author = item["author"]
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        return embed

    @commands.command(name="snipe", aliases=["sn"])
    async def snipe(self, ctx, index: int = 1):
        """The last deleted message here. `$snipe 2` for the one before."""
        item, total = await self.pick(ctx, self.deleted, index, "deleted")
        if not item:
            return
        embed = self.author_embed(item)
        embed.description = item["content"][:4000] or None
        pictures = [url for _name, url, image in item["files"] if image]
        if pictures:
            embed.set_image(url=pictures[0])
        extras = [f"📎 {name}" for name, _url, _image in item["files"]]
        extras += [f"🏷️ sticker: {name}" for name in item["stickers"]]
        if extras:
            embed.add_field(name="Attached", value="\n".join(extras)[:1024], inline=False)
        embed.set_footer(text=f"Deleted {ago(time.time() - item['at'])} ago · {index}/{total}")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="editsnipe", aliases=["es"])
    async def editsnipe(self, ctx, index: int = 1):
        """The last edited message here, before and after."""
        item, total = await self.pick(ctx, self.edited, index, "edited")
        if not item:
            return
        embed = self.author_embed(item)
        embed.add_field(name="Before", value=(item["before"] or "*nothing*")[:1024], inline=False)
        embed.add_field(name="After", value=f"{(item['after'] or '*nothing*')[:900]}\n"
                                            f"[Jump to it]({item['link']})", inline=False)
        embed.set_footer(text=f"Edited {ago(time.time() - item['at'])} ago · {index}/{total}")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="reactionsnipe", aliases=["rs", "rsnipe"])
    async def reactionsnipe(self, ctx, index: int = 1):
        """The last reaction someone took back here."""
        item, total = await self.pick(ctx, self.unreacted, index, "removed reaction")
        if not item:
            return
        embed = self.author_embed(item)
        embed.description = f"Removed {item['emoji']} from [this message]({item['link']})"
        embed.set_footer(text=f"{ago(time.time() - item['at'])} ago · {index}/{total}")
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="clearsnipe", aliases=["cs"])
    @commands.has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx):
        """Forget every snipe in this channel."""
        for store in (self.deleted, self.edited, self.unreacted):
            store.pop(ctx.channel.id, None)
        await ctx.message.add_reaction("✅")

    # ----------------------------------------------------------------- afk

    @commands.command(name="afk", aliases=["away"])
    async def afk_cmd(self, ctx, *, reason: str = "AFK"):
        """Go AFK. Anyone who pings you is told why; talking again ends it."""
        reason = discord.utils.escape_mentions(reason)[:200]
        now = int(time.time())
        self.afk[(ctx.guild.id, ctx.author.id)] = (reason, now)
        self.db.set_afk(ctx.guild.id, ctx.author.id, reason, now)
        await ctx.send(f"💤 {ctx.author.mention}, you're AFK: **{reason}**",
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        gid = message.guild.id
        key = (gid, message.author.id)
        if key in self.afk:
            ctx = await self.bot.get_context(message)
            if not (ctx.valid and ctx.command and ctx.command.name == "afk"):
                _reason, since = self.afk.pop(key)
                self.db.clear_afk(gid, message.author.id)
                try:
                    await message.channel.send(
                        f"👋 Welcome back {message.author.mention}, you were away for"
                        f" {ago(time.time() - since)}.", delete_after=10,
                        allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass
        away = []
        for person in message.mentions[:10]:
            found = self.afk.get((gid, person.id))
            if found and person.id != message.author.id:
                away.append(f"💤 **{person.display_name}** is AFK: {found[0]}"
                            f" ({ago(time.time() - found[1])} ago)")
        if away:
            try:
                await message.reply("\n".join(away[:3]), mention_author=False,
                                    allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    # ---------------------------------------------------------------- info

    @commands.command(name="userinfo", aliases=["ui", "whois", "user"])
    async def userinfo(self, ctx, *, member: discord.Member = None):
        """About someone: when they joined Discord and here, and their roles."""
        member = member or ctx.author
        embed = discord.Embed(colour=member.colour if member.colour.value else config.CARD_COLOUR)
        embed.set_author(name=f"{member.display_name} (@{member.name})",
                         icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Joined Discord", value=when(member.created_at), inline=False)
        if member.joined_at:
            joined = sorted((m for m in ctx.guild.members if m.joined_at),
                            key=lambda m: m.joined_at)
            position = next((n for n, m in enumerate(joined, 1) if m.id == member.id), None)
            embed.add_field(name="Joined here", value=when(member.joined_at)
                            + (f"\nMember #{position:,}" if position else ""), inline=False)
        if member.premium_since:
            embed.add_field(name="Boosting since", value=when(member.premium_since), inline=False)
        roles = [r.mention for r in reversed(member.roles) if not r.is_default()]
        if roles:
            shown = " ".join(roles[:25]) + (f" +{len(roles) - 25} more" if len(roles) > 25 else "")
            embed.add_field(name=f"Roles ({len(roles)})", value=shown[:1024], inline=False)
        try:
            user = await self.bot.fetch_user(member.id)
            if user.banner:
                embed.set_image(url=user.banner.url)
        except discord.HTTPException:
            pass
        embed.set_footer(text=f"ID {member.id}")
        await ctx.send(embed=embed)

    @commands.command(name="serverinfo", aliases=["si", "guildinfo", "server"])
    async def serverinfo(self, ctx):
        """About this server: its owner, age, members, channels and boosts."""
        g = ctx.guild
        humans = sum(1 for m in g.members if not m.bot)
        embed = discord.Embed(title=g.name, description=g.description or None,
                              colour=config.CARD_COLOUR)
        if g.icon:
            embed.set_thumbnail(url=g.icon.url)
        if g.banner:
            embed.set_image(url=g.banner.url)
        embed.add_field(name="Owner", value=g.owner.mention if g.owner else "unknown")
        embed.add_field(name="Created", value=when(g.created_at))
        embed.add_field(name="Members", value=f"{g.member_count:,}\n{humans:,} people ·"
                                              f" {g.member_count - humans:,} bots"
                        if g.member_count else "unknown")
        embed.add_field(name="Channels", value=f"{len(g.text_channels)} text ·"
                                               f" {len(g.voice_channels)} voice ·"
                                               f" {len(g.categories)} categories")
        embed.add_field(name="Roles", value=f"{len(g.roles) - 1:,}")
        embed.add_field(name="Emojis", value=f"{len(g.emojis)} / {g.emoji_limit}")
        embed.add_field(name="Boosts", value=f"Level {g.premium_tier} ·"
                                             f" {g.premium_subscription_count or 0} boosts")
        if g.vanity_url_code:
            embed.add_field(name="Vanity", value=f"discord.gg/{g.vanity_url_code}")
        embed.set_footer(text=f"ID {g.id}")
        await ctx.send(embed=embed)

    @commands.command(name="roleinfo", aliases=["ri"])
    async def roleinfo(self, ctx, *, role: FuzzyRole):
        """About a role: who has it, its colour, and what it can do."""
        embed = discord.Embed(title=role.name, colour=role.colour if role.colour.value
                              else config.CARD_COLOUR)
        embed.add_field(name="Members", value=f"{len(role.members):,}")
        embed.add_field(name="Colour", value=str(role.colour) if role.colour.value else "none")
        embed.add_field(name="Created", value=when(role.created_at))
        embed.add_field(name="Shown separately", value="yes" if role.hoist else "no")
        embed.add_field(name="Mentionable", value="yes" if role.mentionable else "no")
        embed.add_field(name="Position", value=f"{role.position} of {len(ctx.guild.roles) - 1}")
        key = [name.replace("_", " ").title() for name, on in role.permissions
               if on and name in ("administrator", "manage_guild", "manage_roles",
                                  "manage_channels", "manage_messages", "ban_members",
                                  "kick_members", "moderate_members", "mention_everyone")]
        if key:
            embed.add_field(name="Key permissions", value=", ".join(key), inline=False)
        if role.display_icon and hasattr(role.display_icon, "url"):
            embed.set_thumbnail(url=role.display_icon.url)
        embed.set_footer(text=f"ID {role.id}")
        await ctx.send(embed=embed)

    @commands.command(name="banner", aliases=["userbanner"])
    async def banner(self, ctx, *, member: discord.Member = None):
        """Someone's profile banner, full size."""
        member = member or ctx.author
        user = await self.bot.fetch_user(member.id)
        if not user.banner:
            await ctx.send(f"**{member.display_name}** has no banner.",
                           allowed_mentions=discord.AllowedMentions.none())
            return
        embed = discord.Embed(title=f"{member.display_name}'s banner",
                              url=user.banner.with_size(4096).url, colour=config.CARD_COLOUR)
        embed.set_image(url=user.banner.with_size(4096).url)
        await ctx.send(embed=embed)

    @commands.command(name="servericon", aliases=["icon", "guildicon"])
    async def servericon(self, ctx):
        """This server's icon, full size."""
        if not ctx.guild.icon:
            await ctx.send("This server has no icon.")
            return
        embed = discord.Embed(title=ctx.guild.name, url=ctx.guild.icon.with_size(4096).url,
                              colour=config.CARD_COLOUR)
        embed.set_image(url=ctx.guild.icon.with_size(4096).url)
        await ctx.send(embed=embed)

    @commands.command(name="membercount", aliases=["mc", "members"])
    async def membercount(self, ctx):
        """How many people and bots are here."""
        g = ctx.guild
        humans = sum(1 for m in g.members if not m.bot)
        embed = discord.Embed(title=g.name, colour=config.CARD_COLOUR)
        embed.add_field(name="Total", value=f"**{g.member_count:,}**")
        embed.add_field(name="People", value=f"{humans:,}")
        embed.add_field(name="Bots", value=f"{g.member_count - humans:,}")
        await ctx.send(embed=embed)

    @commands.command(name="firstmessage", aliases=["firstmsg", "first"])
    async def firstmessage(self, ctx, channel: discord.TextChannel = None):
        """A link to the first message ever sent in this channel."""
        channel = channel or ctx.channel
        async for message in channel.history(limit=1, oldest_first=True):
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Jump to it", url=message.jump_url))
            await ctx.send(f"The first message in {channel.mention}, sent"
                           f" <t:{int(message.created_at.timestamp())}:R> by"
                           f" **{message.author.display_name}**.", view=view,
                           allowed_mentions=discord.AllowedMentions.none())
            return
        await ctx.send(f"{channel.mention} has no messages yet.")

    # ----------------------------------------------------------- reminders

    @commands.command(name="remind", aliases=["remindme", "reminder"])
    async def remind(self, ctx, duration: str, *, text: str = "you asked me to remind you"):
        """`$remind 10m stretch`: I'll ping you here when it's time.
        Times like 30s, 10m, 2h, 1d or 1h30m."""
        seconds = parse_duration(duration)
        if not seconds:
            await ctx.send("Say how long first, like `10m`, `2h`, `1d` or `1h30m`:"
                           f" `{ctx.prefix}remind 10m stretch`")
            return
        if seconds > LONGEST_REMINDER:
            await ctx.send("I can remind you up to a year from now.")
            return
        if len(self.db.reminders_of(ctx.author.id)) >= MAX_REMINDERS:
            await ctx.send(f"You have {MAX_REMINDERS} reminders already."
                           f" `{ctx.prefix}reminders` to see or cancel some.")
            return
        due = int(time.time()) + seconds
        number = self.db.add_reminder(ctx.guild.id if ctx.guild else 0, ctx.channel.id,
                                      ctx.author.id, due, text[:1000])
        await ctx.send(f"⏰ Got it. I'll remind you <t:{due}:R>. (reminder {number})",
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="reminders", aliases=["myreminders"])
    async def reminders(self, ctx, cancel: str = None, number: int = None):
        """Your reminders. `$reminders cancel 12` to cancel one."""
        if cancel and cancel.lower() in ("cancel", "delete", "remove") and number:
            gone = self.db.remove_reminder(number, ctx.author.id)
            await ctx.send("Cancelled." if gone else "You don't have a reminder with that number.")
            return
        rows = self.db.reminders_of(ctx.author.id)
        lines = [f"`{r['id']}` <t:{r['due']}:R> · {discord.utils.escape_markdown(r['text'])[:80]}"
                 for r in rows]
        await ctx.send(embed=discord.Embed(
            title="Your reminders",
            description="\n".join(lines) or f"None. `{ctx.prefix}remind 10m stretch` to make one.",
            colour=config.CARD_COLOUR).set_footer(
                text=f"{ctx.prefix}reminders cancel <number> to cancel one"))

    @tasks.loop(seconds=20)
    async def reminder_loop(self):
        for row in self.db.due_reminders(int(time.time())):
            self.db.remove_reminder(row["id"])
            text = (f"⏰ <@{row['user_id']}>, reminder:"
                    f" {row['text']}\n-# set <t:{row['made']}:R>")
            mentions = discord.AllowedMentions(users=[discord.Object(row["user_id"])])
            channel = self.bot.get_channel(row["channel_id"])
            try:
                await channel.send(text, allowed_mentions=mentions)
            except (discord.HTTPException, AttributeError):
                # The channel's gone or closed to me: a DM instead.
                try:
                    user = self.bot.get_user(row["user_id"]) or await self.bot.fetch_user(row["user_id"])
                    await user.send(text)
                except discord.HTTPException:
                    pass

    @reminder_loop.before_loop
    async def before_reminders(self):
        await self.bot.wait_until_ready()

    # --------------------------------------------------------------- emoji

    @commands.command(name="translate", aliases=["trans", "translation", "tlate"])
    @commands.guild_only()
    async def translate(self, ctx, *, request: str = None):
        """Put a message into another language.

        Reply to somebody and say `$translate`, which is how it is wanted
        nine times out of ten. Otherwise `$translate hola` works, and a
        language in front of it picks where it is going: `$translate es how
        are you` or `$translate spanish how are you`.
        """
        words = (request or "").split()
        into = "en"
        if words:
            named = translator.code_for(words[0])
            # Only treat the first word as a language when something follows
            # it, or when it is a reply - otherwise "$translate es" would
            # mean translating the Spanish word "es".
            if named and (len(words) > 1 or ctx.message.reference):
                into = named
                words = words[1:]
        text = " ".join(words)

        if not text and ctx.message.reference:
            reference = ctx.message.reference
            quoted = reference.resolved
            if quoted is None or isinstance(quoted, discord.DeletedReferencedMessage):
                try:
                    quoted = await ctx.channel.fetch_message(
                        reference.message_id)
                except discord.HTTPException:
                    quoted = None
            if quoted is not None:
                text = quoted.content

        if not text.strip():
            await ctx.send(
                f"Reply to a message with `{ctx.prefix}translate`, or give me"
                f" something to translate: `{ctx.prefix}translate hola`.")
            return

        async with ctx.typing():
            done, came_from, trouble = await asyncio.to_thread(
                translator.translate, text, into)
        if trouble:
            await ctx.send(trouble[:1500])
            return

        embed = discord.Embed(colour=config.CARD_COLOUR, description=done[:2000])
        embed.set_author(
            name=f"{translator.name_of(came_from)} \u2192"
                 f" {translator.name_of(into)}")
        shown = text if len(text) <= 300 else text[:297] + "..."
        embed.add_field(name="Original", value=shown, inline=False)
        embed.set_footer(text="The language is a guess · "
                              f"{ctx.prefix}translate <language> to pick one")
        await ctx.send(embed=embed,
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="steal", aliases=["addemoji", "emojiadd", "stealemoji"])
    @commands.has_permissions(manage_expressions=True)
    @commands.bot_has_permissions(manage_expressions=True)
    async def steal(self, ctx, *, emojis: str = ""):
        """Copy emojis into this server: `$steal <emoji>`, or reply to a
        message with `$steal` to take the ones in it. `$steal <emoji> name`
        to name it."""
        text = emojis
        if not CUSTOM_EMOJI.search(text) and ctx.message.reference:
            replied = ctx.message.reference.resolved
            if isinstance(replied, discord.Message):
                text = replied.content
        found = CUSTOM_EMOJI.findall(text)
        if not found:
            await ctx.send(f"Give me a custom emoji: `{ctx.prefix}steal <emoji>`, or reply"
                           f" to a message that has some with `{ctx.prefix}steal`.")
            return
        rename = None
        leftover = CUSTOM_EMOJI.sub("", emojis).strip()
        if len(found) == 1 and re.fullmatch(r"\w{2,32}", leftover or ""):
            rename = leftover
        added, failed = [], []
        async with aiohttp.ClientSession() as http:
            for animated, name, emoji_id in list(dict.fromkeys(found))[:10]:
                url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if animated else 'png'}"
                try:
                    async with http.get(url) as response:
                        if response.status != 200:
                            raise ValueError
                        image = await response.read()
                    emoji = await ctx.guild.create_custom_emoji(
                        name=rename or name, image=image, reason=f"$steal by {ctx.author}")
                    added.append(str(emoji))
                except (discord.HTTPException, ValueError, aiohttp.ClientError):
                    failed.append(name)
        parts = []
        if added:
            parts.append("Added " + " ".join(added))
        if failed:
            parts.append("Couldn't add " + ", ".join(f"`{n}`" for n in failed)
                         + " (the server may be out of emoji slots).")
        await ctx.send(". ".join(parts))

    # --------------------------------------------------------------- roles

    @commands.command(name="role", aliases=["giverole", "r"])
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role(self, ctx, member: discord.Member, *, role: FuzzyRole):
        """`$role @someone @role`: gives them the role, or takes it away if
        they have it."""
        me = ctx.guild.me
        if role.is_default() or role.managed:
            await ctx.send("That role can't be given by hand.")
            return
        if role >= me.top_role:
            await ctx.send(f"**{role.name}** is above my highest role, so I can't give it.",
                           allowed_mentions=discord.AllowedMentions.none())
            return
        if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
            await ctx.send(f"**{role.name}** is above your highest role.",
                           allowed_mentions=discord.AllowedMentions.none())
            return
        if role in member.roles:
            await member.remove_roles(role, reason=f"$role by {ctx.author}")
            await ctx.send(f"Took **{role.name}** from {member.mention}.",
                           allowed_mentions=discord.AllowedMentions.none())
        else:
            await member.add_roles(role, reason=f"$role by {ctx.author}")
            await ctx.send(f"Gave {member.mention} **{role.name}**.",
                           allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Utility(bot))
