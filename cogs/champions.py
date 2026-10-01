"""Weekly champions and the weekly staff report, Paper Premium features.

Champions: every Monday the week's top chatter (message XP) and top voice
member (minutes in voice with someone else, not deafened) each get a
role, taken back from last week's winner, and an announcement.

Staff report: every Monday the server owner gets a DM of what each staff
member did that week, and the staff points they earned, which is what
promotions are judged on.

Both run from one loop that checks every few minutes whether a server has
had this Monday's round yet, so a restart can't skip one or run it twice.
"""
import time

import discord
from discord.ext import commands, tasks

import config
import premium
import weekly
from cogs.modtools import ACTIONS
from cogs.voice import fmt_time

REPORT_ACTIONS = ("warn", "jail", "timeout", "imute", "rmute", "kick", "ban",
                  "softban", "hardban")


def report_embed(db, guild, week: int, colour: int) -> discord.Embed:
    """What each staff member did in a week."""
    start, end = weekly.bounds(week)
    per = {}
    for case in db.cases_between(guild.id, start, end):
        if case["action"] in REPORT_ACTIONS and case["mod_id"] != guild.me.id:
            per.setdefault(case["mod_id"], {}).setdefault(case["action"], 0)
            per[case["mod_id"]][case["action"]] += 1
    points = {row["user_id"]: row["points"] for row in db.points_between(guild.id, start, end)}
    staff = sorted(set(per) | set(points),
                   key=lambda m: -(sum(per.get(m, {}).values()) + points.get(m, 0)))
    lines = []
    for mod in staff[:20]:
        did = ", ".join(f"{n} {ACTIONS[a][0].lower()}" for a, n in
                        sorted(per.get(mod, {}).items(), key=lambda x: -x[1]))
        lines.append(f"<@{mod}>: {did or 'no actions'}"
                     + (f" · **{points[mod]}** points" if points.get(mod) else ""))
    embed = discord.Embed(
        title=f"Staff report for {guild.name}",
        description="\n".join(lines) or "A quiet week: no moderation actions.",
        colour=colour)
    embed.set_footer(text=f"Week of {time.strftime('%d %B %Y', time.gmtime(start))}"
                          " · Paper Premium")
    return embed


class Champions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    async def cog_load(self):
        self.weekly_round.start()

    async def cog_unload(self):
        self.weekly_round.cancel()

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    def colour(self, guild_id):
        return self.db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR)

    def premium_note(self, ctx):
        return ("" if self.db.has_feature(ctx.guild.id, "champions") else
                f"\n\n*This comes with {premium.needs('champions')}."
                f" `{ctx.prefix}upgrade` to see how to get it.*")

    def switch_on(self, guild_id):
        """Starting champions counts from now, not from last week."""
        if not self.db.get_premium_setting(guild_id, "champ_week"):
            self.db.set_premium_setting(guild_id, "champ_week", weekly.week_now())

    # ----------------------------------------------------------- champions

    @commands.group(name="champions", aliases=["champion", "champs"],
                    invoke_without_command=True)
    async def champions(self, ctx):
        """Weekly champions: who leads this week, and how it's set up."""
        db, gid = self.db, ctx.guild.id
        week = weekly.week_now()
        chat = db.weekly_top(gid, week, "chat", 3)
        voice = db.weekly_top(gid, week, "voice", 3)
        get = db.get_premium_setting
        lines = [
            "**This week so far**",
            "Chat: " + (", ".join(f"<@{r['user_id']}> ({r['amount']:,} XP)" for r in chat) or "nobody yet"),
            "Voice: " + (", ".join(f"<@{r['user_id']}> ({fmt_time(r['amount'])})" for r in voice) or "nobody yet"),
            "",
            f"**Announced in:** " + (f"<#{get(gid, 'champ_channel')}>" if get(gid, "champ_channel") else "nowhere"),
            f"**Chat champion role:** " + (f"<@&{get(gid, 'champ_chat_role')}>" if get(gid, "champ_chat_role") else "none"),
            f"**Voice champion role:** " + (f"<@&{get(gid, 'champ_voice_role')}>" if get(gid, "champ_voice_role") else "none"),
            f"*New champions every Monday. e.g. `{ctx.prefix}champions role chat @Top Chatter`*",
        ]
        await ctx.send(embed=discord.Embed(title="Weekly champions",
                                           description="\n".join(lines) + self.premium_note(ctx),
                                           colour=self.colour(gid)),
                       allowed_mentions=discord.AllowedMentions.none())

    async def premium_only(self, ctx) -> bool:
        if self.db.has_feature(ctx.guild.id, "champions"):
            return True
        await ctx.send(f"Weekly champions come with {premium.needs('champions')}."
                       f" `{ctx.prefix}upgrade` to see how to get it.")
        return False

    @champions.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def champions_channel(self, ctx, channel: discord.TextChannel):
        """Where the weekly champions are announced."""
        if not await self.premium_only(ctx):
            return
        self.db.set_premium_setting(ctx.guild.id, "champ_channel", channel.id)
        self.switch_on(ctx.guild.id)
        await ctx.send(f"Champions will be announced in {channel.mention} every Monday.")

    @champions.command(name="role")
    @commands.has_permissions(manage_guild=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def champions_role(self, ctx, which: str, role: discord.Role):
        """`chat` or `voice`, and the role the week's champion gets."""
        which = which.lower()
        if which not in ("chat", "voice"):
            await ctx.send("Say `chat` or `voice`, then the role.")
            return
        if not await self.premium_only(ctx):
            return
        if role >= ctx.guild.me.top_role or role.managed or role.is_default():
            await ctx.send(f"I can't give **{role.name}**. It needs to be below my role.",
                           allowed_mentions=discord.AllowedMentions.none())
            return
        self.db.set_premium_setting(ctx.guild.id, f"champ_{which}_role", role.id)
        self.switch_on(ctx.guild.id)
        await ctx.send(f"The week's top {which} member gets **{role.name}** every Monday.",
                       allowed_mentions=discord.AllowedMentions.none())

    @champions.command(name="off")
    @commands.has_permissions(manage_guild=True)
    async def champions_off(self, ctx):
        """Stop weekly champions."""
        for key in ("champ_channel", "champ_chat_role", "champ_voice_role", "champ_week"):
            self.db.set_premium_setting(ctx.guild.id, key, 0)
        await ctx.send("Weekly champions are off. Nobody's week is counted any more.")

    # --------------------------------------------------------- staff report

    @commands.group(name="staffreport", aliases=["modreport"], invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def staffreport(self, ctx, state: str = None):
        """`on` or `off`: a weekly DM to the owner of what each staff member
        did. On its own, shows whether it's on."""
        gid = ctx.guild.id
        if state is None:
            on = self.db.get_premium_setting(gid, "report_on")
            await ctx.send(f"The weekly staff report is **{'on' if on else 'off'}**."
                           f" `{ctx.prefix}staffreport now` shows this week's so far."
                           + self.premium_note(ctx))
            return
        state = state.lower()
        if state not in ("on", "off"):
            await ctx.send("Say `on` or `off`.")
            return
        if state == "on" and not self.db.has_feature(gid, "staff_report"):
            await ctx.send(f"The staff report comes with {premium.needs('staff_report')}."
                           f" `{ctx.prefix}upgrade` to see how to get it.")
            return
        self.db.set_premium_setting(gid, "report_on", 1 if state == "on" else 0)
        if state == "on" and not self.db.get_premium_setting(gid, "report_week"):
            self.db.set_premium_setting(gid, "report_week", weekly.week_now())
        await ctx.send("The owner gets a staff report every Monday." if state == "on"
                       else "The weekly staff report is off.")

    @staffreport.command(name="now")
    @commands.has_permissions(manage_guild=True)
    async def staffreport_now(self, ctx):
        """This week's report so far."""
        if not await self.premium_only(ctx):
            return
        await ctx.send(embed=report_embed(self.db, ctx.guild, weekly.week_now(),
                                          self.colour(ctx.guild.id)),
                       allowed_mentions=discord.AllowedMentions.none())

    # ----------------------------------------------------------- the round

    async def crown(self, guild, week: int):
        """Last week's champions: roles moved, winners announced."""
        db, gid = self.db, guild.id
        lines = []
        for kind, label in (("chat", "\U0001f4ac Top chatter"), ("voice", "\U0001f3a7 Top in voice")):
            top = db.weekly_top(gid, week, kind, 1)
            role = guild.get_role(db.get_premium_setting(gid, f"champ_{kind}_role"))
            winner = guild.get_member(top[0]["user_id"]) if top else None
            if role:
                for holder in list(role.members):
                    if holder != winner:
                        try:
                            await holder.remove_roles(role, reason="Last week's champion")
                        except discord.HTTPException:
                            pass
                if winner and role not in winner.roles:
                    try:
                        await winner.add_roles(role, reason="This week's champion")
                    except discord.HTTPException:
                        pass
            if winner:
                amount = (f"{top[0]['amount']:,} XP" if kind == "chat"
                          else fmt_time(top[0]["amount"]))
                lines.append(f"{label}: {winner.mention} with {amount}"
                             + (f", and the **{role.name}** role" if role else ""))
        channel = guild.get_channel(db.get_premium_setting(gid, "champ_channel"))
        if channel and lines:
            try:
                await channel.send(embed=discord.Embed(
                    title="\U0001f3c6 This week's champions",
                    description="\n".join(lines) + "\n\nA new race starts now. Good luck!",
                    colour=self.colour(gid)))
            except discord.HTTPException:
                pass

    async def report(self, guild, week: int):
        embed = report_embed(self.db, guild, week, self.colour(guild.id))
        owner = guild.owner or await self.bot.fetch_user(guild.owner_id)
        try:
            await owner.send(embed=embed)
        except (discord.HTTPException, AttributeError):
            # DMs closed: the mod log is the next best place.
            channel = guild.get_channel(self.db.get_mod_config(guild.id, "log_channel"))
            if channel:
                try:
                    await channel.send(embed=embed,
                                       allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass

    @tasks.loop(minutes=5)
    async def weekly_round(self):
        week = weekly.week_now()
        db = self.db
        for guild in self.bot.guilds:
            gid = guild.id
            if not db.has_feature(gid, "champions"):
                continue
            if weekly.champions_on(db, gid):
                done = db.get_premium_setting(gid, "champ_week")
                if done and done < week:
                    # Marked first: a failure mid-way must not crown twice.
                    db.set_premium_setting(gid, "champ_week", week)
                    await self.crown(guild, week - 1)
                elif not done:
                    db.set_premium_setting(gid, "champ_week", week)
            if db.get_premium_setting(gid, "report_on"):
                done = db.get_premium_setting(gid, "report_week")
                if done and done < week:
                    db.set_premium_setting(gid, "report_week", week)
                    await self.report(guild, week - 1)
                elif not done:
                    db.set_premium_setting(gid, "report_week", week)
        db.prune_weekly(week - 4)

    @weekly_round.before_loop
    async def before_round(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Champions(bot))
