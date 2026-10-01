"""Anti-alt: catch ban evaders as they join.

A bot can't see IPs or devices, so a banned person can always come back on
a new account. What gives most of them away is the account itself:

    new       made less than N days ago (7 by default). Paper jails, kicks
              or bans them, or only tells staff, as the server chooses.
    lookalike the same name or profile picture as someone hardbanned here.
              Names can be shared by chance, so this only ever alerts.

Both go to the antinuke log if there is one, otherwise the mod log. Someone
legitimate who trips it can be let in with `$antialt allow`. It starts off,
and the settings live beside antinuke's, under alt: keys.
"""
import asyncio
import difflib
import re
import time

import discord
from discord.ext import commands

DAY = 86400
DEFAULT_DAYS = 7
PUNISHMENTS = ("alert", "jail", "kick", "ban")
DEFAULT_PUNISHMENT = 1          # jail: talk first, as the rest of Paper does
DONE = {"alert": "flagged to staff", "jail": "jailed", "kick": "kicked", "ban": "banned"}
# What people type for each punishment.
SAYS = {**{p: p for p in PUNISHMENTS}, **{v: k for k, v in DONE.items()},
        "flag": "alert", "warn": "alert", "none": "alert"}
LOOKUP_TTL = 3600               # how long a hardbanned user's name is cached


def parse_days(text: str):
    """'7', '7d', '2w' or '48h' as whole days (at least 1), or None."""
    match = re.fullmatch(r"\s*(\d+)\s*(d|day|days|w|week|weeks|h|hour|hours)?\s*",
                         (text or "").lower())
    if not match:
        return None
    number, unit = int(match.group(1)), (match.group(2) or "d")[0]
    days = number * 7 if unit == "w" else -(-number // 24) if unit == "h" else number
    return days if 1 <= days <= 365 else None


def account_age(created_at, now: float = None) -> float:
    """Seconds since the account was made."""
    return (now if now is not None else time.time()) - created_at.timestamp()


def clean_name(name: str) -> str:
    """Lowercase letters and digits only, so 'X_Evader.' matches 'xevader'."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def looks_alike(names_a, avatar_a, names_b, avatar_b) -> str:
    """Why two accounts look like the same person, or ''.

    Names are compared cleaned, and close counts (one letter changed); short
    names have to match exactly, or every 'sam' would look like every 'sim'.
    """
    if avatar_a and avatar_a == avatar_b:
        return "the same profile picture"
    for a in filter(None, map(clean_name, names_a)):
        for b in filter(None, map(clean_name, names_b)):
            if a == b:
                return "the same name"
            if min(len(a), len(b)) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
                return "a very similar name"
    return ""


def names_of(user) -> list:
    return [user.name, getattr(user, "global_name", None)]


def avatar_of(user) -> str:
    # Only an uploaded picture counts: everyone on a default avatar shares it.
    return user.avatar.key if getattr(user, "avatar", None) else ""


class AntiAlt(commands.Cog):
    works_everywhere = True  # security; see bot.check_allowed

    def __init__(self, bot):
        self.bot = bot
        self.users = {}          # user id -> (fetched at, user) for hardbanned users

    @property
    def db(self):
        return self.bot.db

    # ------------------------------------------------------------ settings

    def setting(self, guild_id: int, key: str, default: int = 0) -> int:
        return self.db.antinuke_get(guild_id, f"alt:{key}", default)

    def put(self, guild_id: int, key: str, value: int):
        self.db.antinuke_set(guild_id, f"alt:{key}", value)

    def enabled(self, guild_id: int) -> bool:
        return bool(self.setting(guild_id, "enabled"))

    def days(self, guild_id: int) -> int:
        return self.setting(guild_id, "days", DEFAULT_DAYS)

    def punishment(self, guild_id: int) -> str:
        index = self.setting(guild_id, "punishment", DEFAULT_PUNISHMENT)
        return PUNISHMENTS[min(max(index, 0), len(PUNISHMENTS) - 1)]

    def lookalike_on(self, guild_id: int) -> bool:
        return bool(self.setting(guild_id, "lookalike", 1))

    def allowed(self, guild_id: int) -> list:
        return self.db.antinuke_people(guild_id, "alt_allow")

    # ------------------------------------------------------------ watching

    async def hardbanned_users(self, guild) -> list:
        now = time.time()
        users = []
        for row in self.db.hardbans_in(guild.id):
            uid = row["user_id"]
            cached = self.users.get(uid)
            if cached is None or now - cached[0] > LOOKUP_TTL:
                user = self.bot.get_user(uid)
                if user is None:
                    try:
                        user = await self.bot.fetch_user(uid)
                    except discord.HTTPException:
                        user = None
                cached = self.users[uid] = (now, user)
            if cached[1] is not None:
                users.append(cached[1])
        return users

    async def lookalike_of(self, member):
        """The hardbanned user this member looks like, and why, or (None, '')."""
        for banned in await self.hardbanned_users(member.guild):
            if banned.id == member.id:
                continue
            why = looks_alike(names_of(member), avatar_of(member),
                              names_of(banned), avatar_of(banned))
            if why:
                return banned, why
        return None, ""

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        if member.bot or not self.enabled(guild.id) or member.id in self.allowed(guild.id):
            return
        days = self.days(guild.id)
        new = account_age(member.created_at) < days * DAY
        twin, why = (await self.lookalike_of(member)
                     if self.lookalike_on(guild.id) else (None, ""))
        if not new and twin is None:
            return

        done = "only flagged"
        if new:
            # A moment for autoroles to land, so the jail takes them too.
            await asyncio.sleep(3)
            member = guild.get_member(member.id)
            if member is None:
                return  # they left already
            done = await self.punish(guild, member, days)
        await self.report(guild, member, new, days, twin, why, done)

    async def punish(self, guild, member, days: int) -> str:
        action = self.punishment(guild.id)
        mod = self.bot.get_cog("ModTools")
        reason = f"Anti-alt: account under {days} day{'s' if days != 1 else ''} old"
        me = guild.me
        try:
            if action == "jail" and mod and mod.role(guild, "jail_role"):
                await mod.apply_jail(guild, member, me, reason)
                return "jailed"
            if action in ("jail", "kick"):
                # No jail set up yet: kicking is the gentlest real stop.
                if mod:
                    await mod.apply_kick(guild, member, me, reason)
                else:
                    await member.kick(reason=reason)
                return "kicked" + (" (no jail set up)" if action == "jail" else "")
            if action == "ban":
                if mod:
                    await mod.apply_ban(guild, member, me, reason)
                else:
                    await guild.ban(member, reason=reason)
                return "banned"
        except discord.HTTPException:
            return f"not {DONE[action]} (Paper is missing the permission or the role order)"
        return "only flagged"

    async def report(self, guild, member, new: bool, days: int, twin, why: str, done: str):
        made = int(member.created_at.timestamp())
        lines = []
        if new:
            lines.append(f"Account made <t:{made}:R> (under {days} day"
                         f"{'s' if days != 1 else ''}).")
        if twin is not None:
            lines.append(f"Has {why} as hardbanned **{twin}** (`{twin.id}`).")
        embed = discord.Embed(
            title="\U0001f575️ Possible alt account",
            description=f"{member.mention} ({member}, `{member.id}`) joined and was"
                        f" **{done}**.\n\n" + "\n".join(lines),
            colour=0xE0A33B)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text="Let them in with $antialt allow " + str(member.id))
        channel = guild.get_channel(self.db.antinuke_get(guild.id, "log_channel")
                                    or self.db.get_mod_config(guild.id, "log_channel"))
        if channel is not None:
            try:
                await channel.send(embed=embed,
                                   allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------ commands

    def status_embed(self, ctx) -> discord.Embed:
        gid, p = ctx.guild.id, ctx.prefix
        days = self.days(gid)
        allowed = self.allowed(gid)
        embed = discord.Embed(
            title="\U0001f575️ Anti-alt: " + ("on" if self.enabled(gid) else "off"),
            description=(
                "Discord never shows bots IPs or devices, so this catches the next"
                " best thing: brand-new accounts, and accounts that look like"
                " someone hardbanned here.\n\n"
                f"**New accounts:** under **{days}** day{'s' if days != 1 else ''}"
                f" old are **{DONE[self.punishment(gid)]}**\n"
                + f"**Look-alikes of hardbanned users:** "
                + ("flagged to staff" if self.lookalike_on(gid) else "off") + "\n"
                + f"**Let in anyway:** "
                + (", ".join(f"<@{u}>" for u in allowed[:15]) if allowed else "nobody")),
            colour=0xE0A33B)
        embed.add_field(name="Change it", value=(
            f"`{p}antialt on` / `off`\n"
            f"`{p}antialt age 7d` how new is too new\n"
            f"`{p}antialt punish jail` alert, jail, kick or ban\n"
            f"`{p}antialt lookalike on` / `off`\n"
            f"`{p}antialt allow @user` let someone in"), inline=False)
        return embed

    @commands.group(name="antialt", aliases=["alts", "altcheck", "antialts"],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def antialt(self, ctx):
        """Catch ban evaders' new accounts as they join."""
        await ctx.send(embed=self.status_embed(ctx),
                       allowed_mentions=discord.AllowedMentions.none())

    @antialt.command(name="on", aliases=["enable"])
    async def antialt_on(self, ctx):
        self.put(ctx.guild.id, "enabled", 1)
        await ctx.send(embed=self.status_embed(ctx),
                       allowed_mentions=discord.AllowedMentions.none())

    @antialt.command(name="off", aliases=["disable"])
    async def antialt_off(self, ctx):
        self.put(ctx.guild.id, "enabled", 0)
        await ctx.send("Anti-alt is off. New accounts join like anyone else.")

    @antialt.command(name="age", aliases=["days", "minage"])
    async def antialt_age(self, ctx, *, age: str):
        """How new is too new: `7d`, `2w` or `48h`."""
        days = parse_days(age)
        if days is None:
            await ctx.send(f"Give an age between 1 day and a year: `{ctx.prefix}antialt age 7d`.")
            return
        self.put(ctx.guild.id, "days", days)
        await ctx.send(f"Accounts younger than **{days}** day{'s' if days != 1 else ''}"
                       f" are caught now.")

    @antialt.command(name="punish", aliases=["punishment", "action"])
    async def antialt_punish(self, ctx, action: str):
        """What happens to a new account: alert, jail, kick or ban."""
        action = SAYS.get(action.lower())
        if action is None:
            await ctx.send("Pick one of: " + ", ".join(f"`{a}`" for a in PUNISHMENTS) + ".")
            return
        self.put(ctx.guild.id, "punishment", PUNISHMENTS.index(action))
        note = ""
        mod = self.bot.get_cog("ModTools")
        if action == "jail" and not (mod and mod.role(ctx.guild, "jail_role")):
            note = (f" There's no jail yet, so they're kicked until you run"
                    f" `{ctx.prefix}setupmod`.")
        await ctx.send({"alert": "New accounts are only flagged to staff.",
                        "jail": "New accounts go straight to jail.",
                        "kick": "New accounts are kicked.",
                        "ban": "New accounts are banned."}[action] + note)

    @antialt.command(name="lookalike", aliases=["lookalikes", "twins"])
    async def antialt_lookalike(self, ctx, state: str):
        on = state.lower() in ("on", "yes", "true", "1", "enable")
        self.put(ctx.guild.id, "lookalike", int(on))
        await ctx.send("Look-alikes of hardbanned users are flagged to staff." if on
                       else "Look-alike checks are off.")

    @antialt.command(name="allow", aliases=["trust", "whitelist", "wl"])
    async def antialt_allow(self, ctx, user: discord.User):
        """Let someone in even if they'd be caught."""
        self.db.antinuke_add_person(ctx.guild.id, user.id, "alt_allow")
        mod = self.bot.get_cog("ModTools")
        member = ctx.guild.get_member(user.id)
        freed = ""
        if member and mod and self.db.jail_record(ctx.guild.id, user.id):
            freed = f" They're still in jail: `{ctx.prefix}unjail {user.id}` lets them out."
        await ctx.send(f"**{user}** won't be caught by anti-alt.{freed}",
                       allowed_mentions=discord.AllowedMentions.none())

    @antialt.command(name="unallow", aliases=["untrust", "unwhitelist"])
    async def antialt_unallow(self, ctx, user: discord.User):
        self.db.antinuke_remove_person(ctx.guild.id, user.id, "alt_allow")
        await ctx.send(f"**{user}** is checked like everyone else again.",
                       allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(AntiAlt(bot))
