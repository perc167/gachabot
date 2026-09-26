"""Talk-first automod.

A message that breaks a filter is deleted, and then, as the server
chooses per filter, its sender is warned, timed out or jailed. Jail is
the default for spam and blocked words: staff talk it out, the same as
every other rule break here.

Free: invite links and mass mentions. Paper Premium adds spam, blocked
words, all links and shouting.

Staff (Manage Messages, or a staff role), bots and exempt channels are
left alone. One member gets at most one punishment a minute, so a burst of
spam is one jail, not twenty. Every action is a case in the mod log, made
by the bot, so it earns nobody staff points.
"""
import re
import time

import discord
from discord.ext import commands

import config
from cogs.modtools import DEFAULT_TIMEOUT, outranks

# filter: (name, what it catches, Premium?, default action)
FILTERS = {
    "invites": ("Invite links", "Invites to other Discord servers", False, "warn"),
    "mentions": ("Mass mentions", "Pinging lots of people at once", False, "warn"),
    "spam": ("Spam", "Lots of messages in a few seconds", True, "jail"),
    "words": ("Blocked words", "Words on your list", True, "jail"),
    "links": ("All links", "Any web link", True, "warn"),
    "caps": ("Shouting", "Messages mostly in capitals", True, "delete"),
}
ACTIONS = ("delete", "warn", "timeout", "jail")
NUMBERS = {                       # key: (default, lowest, highest)
    "mentions_limit": (5, 2, 50),
    "spam_count": (6, 3, 30),
    "spam_seconds": (8, 2, 60),
}
MAX_WORDS = 200
PUNISH_COOLDOWN = 60

INVITE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/[\w-]+", re.I)
LINK = re.compile(r"https?://\S+", re.I)


def settings_of(db, guild_id: int) -> dict:
    """Every filter's switch and action, and the numbers, with defaults."""
    raw = db.automod_all(guild_id)
    out = {}
    for key, (_n, _d, _p, action) in FILTERS.items():
        out[key] = {"on": raw.get(f"{key}_on", "0") == "1",
                    "action": raw.get(f"{key}_action", action)}
    for key, (default, low, high) in NUMBERS.items():
        try:
            out[key] = max(low, min(high, int(raw.get(key, default))))
        except ValueError:
            out[key] = default
    return out


def clean_words(text_or_list) -> list:
    items = (text_or_list.splitlines() if isinstance(text_or_list, str)
             else list(text_or_list))
    words = []
    for item in items:
        word = " ".join(str(item).lower().split())[:60]
        if word and word not in words:
            words.append(word)
    return words[:MAX_WORDS]


def breaks(message, settings: dict, words: list, recent: list, premium: bool):
    """The first filter a message breaks, or None."""
    text = message.content or ""
    on = lambda key: settings[key]["on"] and (premium or not FILTERS[key][2])
    if on("invites") and INVITE.search(text):
        return "invites"
    if on("mentions") and len(set(message.mentions)) + len(message.role_mentions) \
            >= settings["mentions_limit"]:
        return "mentions"
    if on("spam") and len(recent) >= settings["spam_count"]:
        return "spam"
    if on("words") and words:
        # Spaces collapsed, so "bad   word" can't slip past "bad word".
        low = " ".join(text.lower().split())
        for word in words:
            if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", low):
                return "words"
    if on("links") and LINK.search(text):
        return "links"
    if on("caps"):
        letters = [c for c in text if c.isalpha()]
        if len(letters) >= 15 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
            return "caps"
    return None


class Automod(commands.Cog):
    works_everywhere = True  # a staff command; see cogs/modtools.py

    def __init__(self, bot):
        self.bot = bot
        self.seen = {}        # (guild, user) -> recent message times
        self.punished = {}    # (guild, user) -> when they were last punished

    @property
    def db(self):
        return self.bot.db

    def exempt(self, message) -> bool:
        member = message.author
        if member.bot or not isinstance(member, discord.Member):
            return True
        if member.guild_permissions.manage_messages:
            return True
        staff = set(self.db.staff_roles_of(message.guild.id))
        if staff and any(r.id in staff for r in member.roles):
            return True
        return message.channel.id in self.db.automod_exempt(message.guild.id)

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        settings = settings_of(self.db, message.guild.id)
        if not any(f["on"] for k, f in settings.items() if k in FILTERS):
            return
        if self.exempt(message):
            return
        key = (message.guild.id, message.author.id)
        now = time.time()
        window = settings["spam_seconds"]
        recent = [t for t in self.seen.get(key, []) if now - t < window] + [now]
        self.seen[key] = recent
        premium = self.db.is_premium(message.guild.id)
        hit = breaks(message, settings, self.db.automod_words(message.guild.id),
                     recent, premium)
        if hit:
            await self.act(message, hit, settings[hit]["action"])

    async def act(self, message, hit: str, action: str):
        guild, member = message.guild, message.author
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        key = (guild.id, member.id)
        now = time.time()
        if now - self.punished.get(key, 0) < PUNISH_COOLDOWN or action == "delete":
            return
        self.punished[key] = now
        name = FILTERS[hit][0].lower()
        reason = f"automod: {name}"
        try:
            await message.channel.send(
                f"{member.mention}, that message was removed ({name}).",
                delete_after=8, allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException:
            pass
        mod = self.bot.get_cog("ModTools")
        if not mod or outranks(guild, guild.me, member):
            return
        try:
            if action == "jail" and mod.role(guild, "jail_role"):
                if mod.role(guild, "jail_role") not in member.roles:
                    await mod.apply_jail(guild, member, guild.me, reason)
            elif action in ("timeout", "jail"):
                # No jail set up yet: a timeout is the next best thing.
                await mod.apply_timeout(guild, member, guild.me, DEFAULT_TIMEOUT, reason)
            elif action == "warn":
                case = await mod.record(guild, member, guild.me, "warn", reason)
                await mod.tell(guild, member, guild.me, "warn", reason, case=case)
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------ commands

    @commands.group(name="automod", aliases=["am"], invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def automod(self, ctx):
        """How automod is set up here."""
        gid = ctx.guild.id
        s = settings_of(self.db, gid)
        premium = self.db.is_premium(gid)
        lines = []
        for key, (name, what, paid, _a) in FILTERS.items():
            state = "on" if s[key]["on"] else "off"
            locked = paid and not premium
            mark = "✅" if s[key]["on"] and not locked else "⬜"
            lines.append(f"{mark} **{name}** ({key}): {state}, then {s[key]['action']}"
                         + ("  ✨ *Premium*" if locked else ""))
        exempt = self.db.automod_exempt(gid)
        lines += ["",
                  f"Mass mentions at **{s['mentions_limit']}** pings;"
                  f" spam at **{s['spam_count']}** messages in **{s['spam_seconds']}s**.",
                  f"**{len(self.db.automod_words(gid))}** blocked words.",
                  "Leaves alone: staff, bots"
                  + ("".join(f", <#{c}>" for c in exempt) if exempt else "") + ".",
                  f"*e.g. `{ctx.prefix}automod invites on`,"
                  f" `{ctx.prefix}automod action spam jail`*"]
        await ctx.send(embed=discord.Embed(
            title="Automod", description="\n".join(lines),
            colour=self.db.get_pref(gid, "cardcolour", config.CARD_COLOUR)))

    async def switch(self, ctx, key: str, state: str):
        state = state.lower()
        if state not in ("on", "off"):
            await ctx.send("Say `on` or `off`.")
            return
        if state == "on" and FILTERS[key][2] and not self.db.is_premium(ctx.guild.id):
            await ctx.send(f"The {FILTERS[key][0].lower()} filter comes with Paper Premium."
                           f" `{ctx.prefix}upgrade` to see how to get it.")
            return
        self.db.set_automod(ctx.guild.id, f"{key}_on", 1 if state == "on" else 0)
        await ctx.send(f"{FILTERS[key][0]}: **{state}**.")

    @automod.command(name="invites")
    @commands.has_permissions(manage_guild=True)
    async def automod_invites(self, ctx, state: str):
        """`on` or `off`: remove invites to other servers."""
        await self.switch(ctx, "invites", state)

    @automod.command(name="mentions")
    @commands.has_permissions(manage_guild=True)
    async def automod_mentions(self, ctx, state: str):
        """`on`, `off`, or a number of pings that counts as mass mentions."""
        if state.isdigit():
            n = int(state)
            low, high = NUMBERS["mentions_limit"][1:]
            if not low <= n <= high:
                await ctx.send(f"Pick from {low} to {high}.")
                return
            self.db.set_automod(ctx.guild.id, "mentions_limit", n)
            await ctx.send(f"Mass mentions start at **{n}** pings.")
            return
        await self.switch(ctx, "mentions", state)

    @automod.command(name="spam")
    @commands.has_permissions(manage_guild=True)
    async def automod_spam(self, ctx, state: str, seconds: int = None):
        """Premium: `on`, `off`, or how many messages in how many seconds,
        e.g. `6 8`."""
        if state.isdigit():
            count = int(state)
            seconds = seconds or settings_of(self.db, ctx.guild.id)["spam_seconds"]
            (_, clow, chigh), (_, slow, shigh) = NUMBERS["spam_count"], NUMBERS["spam_seconds"]
            if not (clow <= count <= chigh and slow <= seconds <= shigh):
                await ctx.send(f"Pick {clow}-{chigh} messages in {slow}-{shigh} seconds.")
                return
            self.db.set_automod(ctx.guild.id, "spam_count", count)
            self.db.set_automod(ctx.guild.id, "spam_seconds", seconds)
            await ctx.send(f"Spam is **{count}** messages in **{seconds}s**.")
            return
        await self.switch(ctx, "spam", state)

    @automod.command(name="links")
    @commands.has_permissions(manage_guild=True)
    async def automod_links(self, ctx, state: str):
        """Premium: `on` or `off`: remove every web link."""
        await self.switch(ctx, "links", state)

    @automod.command(name="caps")
    @commands.has_permissions(manage_guild=True)
    async def automod_caps(self, ctx, state: str):
        """Premium: `on` or `off`: remove shouting."""
        await self.switch(ctx, "caps", state)

    @automod.command(name="action")
    @commands.has_permissions(manage_guild=True)
    async def automod_action(self, ctx, key: str, action: str):
        """What happens after a filter deletes a message: delete (nothing
        more), warn, timeout or jail."""
        key, action = key.lower(), action.lower()
        if key not in FILTERS or action not in ACTIONS:
            await ctx.send("e.g. `automod action spam jail`. Filters: "
                           + ", ".join(FILTERS) + ". Actions: " + ", ".join(ACTIONS) + ".")
            return
        self.db.set_automod(ctx.guild.id, f"{key}_action", action)
        await ctx.send(f"{FILTERS[key][0]}: delete, then **{action}**." if action != "delete"
                       else f"{FILTERS[key][0]}: just delete the message.")

    @automod.group(name="words", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def automod_words(self, ctx, state: str = None):
        """Premium: `on` or `off`, or `add`/`remove`/`list` the words."""
        if state:
            await self.switch(ctx, "words", state)
            return
        words = self.db.automod_words(ctx.guild.id)
        try:
            await ctx.author.send("Blocked words in **%s**:\n%s" % (
                ctx.guild.name, ", ".join(f"||{w}||" for w in words) or "none yet"))
            await ctx.send("Sent you the list in DMs.")
        except discord.HTTPException:
            await ctx.send("I couldn't DM you the list.")

    @automod_words.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def automod_words_add(self, ctx, *, words: str):
        """Add words, separated by commas."""
        now = self.db.automod_words(ctx.guild.id)
        new = clean_words(now + words.split(","))
        self.db.replace_automod_words(ctx.guild.id, new)
        try:
            await ctx.message.delete()      # the words shouldn't sit in chat
        except discord.HTTPException:
            pass
        await ctx.send(f"**{len(new) - len(now)}** added; **{len(new)}** blocked words now.")

    @automod_words.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def automod_words_remove(self, ctx, *, words: str):
        """Remove words, separated by commas."""
        drop = set(clean_words(words.split(",")))
        now = self.db.automod_words(ctx.guild.id)
        self.db.replace_automod_words(ctx.guild.id, [w for w in now if w not in drop])
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send(f"Removed **{len(now) - len(self.db.automod_words(ctx.guild.id))}**.")

    @automod.command(name="exempt")
    @commands.has_permissions(manage_guild=True)
    async def automod_exempt(self, ctx, channel: discord.TextChannel):
        """Leave a channel alone, or stop leaving it alone if it already is."""
        now = self.db.automod_exempt(ctx.guild.id)
        if channel.id in now:
            self.db.replace_automod_exempt(ctx.guild.id, [c for c in now if c != channel.id])
            await ctx.send(f"Automod watches {channel.mention} again.")
        else:
            self.db.replace_automod_exempt(ctx.guild.id, now + [channel.id])
            await ctx.send(f"Automod leaves {channel.mention} alone.")


async def setup(bot):
    await bot.add_cog(Automod(bot))
