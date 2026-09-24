"""The settings side of moderation: staff roles, warn punishments and the
server's own wording for what the bot says after an action.

The actions themselves are in cogs/modtools.py. Changing any of this needs
Manage Server; staff can look.
"""
import discord
from discord.ext import commands

import config
from cogs.modtools import (ACTIONS, VARIABLES, describe_duration,
                           parse_duration, render)

PUNISHMENTS = ("timeout", "jail", "kick", "ban")
KINDS = ("message", "dm")


class ModSettings(commands.Cog):
    works_everywhere = True  # see cogs/modtools.py

    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    def embed(self, ctx, title: str, description: str) -> discord.Embed:
        return discord.Embed(
            title=title, description=description,
            colour=self.db.get_pref(ctx.guild.id, "cardcolour", config.CARD_COLOUR))

    # --------------------------------------------------------- staff roles

    @commands.group(name="staffroles", aliases=["staffrole", "staff"],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def staffroles(self, ctx):
        """The roles that count as staff."""
        await self.staffroles_list(ctx)

    @staffroles.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def staffroles_list(self, ctx):
        """The roles that count as staff."""
        ids = self.db.staff_roles_of(ctx.guild.id)
        await ctx.send(embed=self.embed(
            ctx, "Staff roles",
            " ".join(f"<@&{i}>" for i in ids) or
            f"None yet. Add one with `{ctx.prefix}staffroles add @role`."))

    @staffroles.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def staffroles_add(self, ctx, role: discord.Role):
        """Make a role staff: it can see the jail and mod log."""
        self.db.add_staff_role(ctx.guild.id, role.id)
        modtools = self.bot.get_cog("ModTools")
        if modtools:
            try:
                await modtools.show_staff_the_rooms(ctx.guild)
            except discord.HTTPException:
                pass
        await ctx.send(f"**{role.name}** is staff now.",
                       allowed_mentions=discord.AllowedMentions.none())

    @staffroles.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def staffroles_remove(self, ctx, role: discord.Role):
        """Stop a role counting as staff."""
        gone = self.db.remove_staff_role(ctx.guild.id, role.id)
        await ctx.send(f"**{role.name}** isn't staff any more. It can still see"
                       " the jail until you change that channel's permissions."
                       if gone else f"**{role.name}** wasn't staff.",
                       allowed_mentions=discord.AllowedMentions.none())

    # ---------------------------------------------------- warn punishments

    @commands.group(name="warnpunish", aliases=["warnpunishment", "warnaction"],
                    invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def warnpunish(self, ctx):
        """What happens automatically at so many warnings."""
        await self.warnpunish_list(ctx)

    @warnpunish.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def warnpunish_list(self, ctx):
        """What happens automatically at so many warnings."""
        rows = self.db.warn_punishments_of(ctx.guild.id)
        lines = [
            f"**{row['threshold']}** warnings → {row['action']}"
            + (f" for {describe_duration(row['duration'])}" if row["duration"] else "")
            for row in rows
        ]
        await ctx.send(embed=self.embed(
            ctx, "Warn punishments",
            "\n".join(lines) or
            f"None yet. e.g. `{ctx.prefix}warnpunish add 3 timeout 1h`"))

    @warnpunish.command(name="add", aliases=["set"])
    @commands.has_permissions(manage_guild=True)
    async def warnpunish_add(self, ctx, threshold: int, action: str,
                             duration: str = ""):
        """At this many warnings, timeout, jail, kick or ban them."""
        action = action.lower()
        if action not in PUNISHMENTS:
            await ctx.send("The punishment has to be one of: "
                           + ", ".join(f"`{p}`" for p in PUNISHMENTS) + ".")
            return
        if not 1 <= threshold <= 50:
            await ctx.send("Pick a number of warnings between 1 and 50.")
            return
        seconds = 0
        if action == "timeout":
            seconds = parse_duration(duration) or 3600
            if seconds > 28 * 86400:
                await ctx.send("Discord only allows timeouts of up to 28 days.")
                return
        self.db.set_warn_punishment(ctx.guild.id, threshold, action, seconds)
        await ctx.send(f"At **{threshold}** warnings, they'll be"
                       f" {ACTIONS[action][0].lower()}"
                       + (f" for {describe_duration(seconds)}" if seconds else "")
                       + ".")

    @warnpunish.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def warnpunish_remove(self, ctx, threshold: int):
        """Stop punishing at this many warnings."""
        gone = self.db.remove_warn_punishment(ctx.guild.id, threshold)
        await ctx.send(f"Nothing happens at **{threshold}** warnings now."
                       if gone else f"There was no punishment at {threshold}.")

    # ------------------------------------------------------ invoke messages

    def check_target(self, action: str, kind: str = None) -> str:
        if action not in ACTIONS:
            return ("That isn't an action I know. Try one of: "
                    + ", ".join(f"`{a}`" for a in ACTIONS) + ".")
        if kind is not None and kind not in KINDS:
            return "The type is `message` (said in the channel) or `dm`."
        return ""

    @commands.group(name="invoke", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(moderate_members=True)
    async def invoke(self, ctx):
        """Your own wording for what the bot says after an action."""
        await self.invoke_list(ctx)

    @invoke.command(name="set")
    @commands.has_permissions(manage_guild=True)
    async def invoke_set(self, ctx, action: str, kind: str, *, content: str):
        """e.g. $invoke set jail message {user.mention} is in jail: {reason}"""
        action, kind = action.lower(), kind.lower()
        if problem := self.check_target(action, kind):
            await ctx.send(problem)
            return
        self.db.set_invoke(ctx.guild.id, action, kind, content[:1500])
        await ctx.send(f"Saved the `{action}` {kind}. Try it with"
                       f" `{ctx.prefix}invoke test {action}`.")

    @invoke.command(name="view")
    @commands.has_permissions(moderate_members=True)
    async def invoke_view(self, ctx, action: str, kind: str = "message"):
        """Show the saved wording for one action."""
        action, kind = action.lower(), kind.lower()
        if problem := self.check_target(action, kind):
            await ctx.send(problem)
            return
        content = self.db.invoke_of(ctx.guild.id, action, kind)
        await ctx.send(f"```\n{content}\n```" if content else
                       f"`{action}` {kind} uses the default wording.")

    @invoke.command(name="list")
    @commands.has_permissions(moderate_members=True)
    async def invoke_list(self, ctx):
        """Every action with its own wording, and the variables you can use."""
        rows = self.db.invokes_in(ctx.guild.id)
        lines = [f"`{row['action']}` {row['kind']}: {row['content'][:80]}"
                 for row in rows]
        await ctx.send(embed=self.embed(
            ctx, "Invoke messages",
            ("\n".join(lines) or "All default.")
            + "\n\n**Variables:** " + " ".join(f"`{v}`" for v in VARIABLES)))

    @invoke.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def invoke_reset(self, ctx, action: str, kind: str = None):
        """Go back to the default wording for an action."""
        action = action.lower()
        kind = kind.lower() if kind else None
        if problem := self.check_target(action, kind):
            await ctx.send(problem)
            return
        gone = self.db.reset_invoke(ctx.guild.id, action, kind)
        await ctx.send(f"`{action}` is back to the default." if gone
                       else f"`{action}` was already default.")

    @invoke.command(name="test")
    @commands.has_permissions(moderate_members=True)
    async def invoke_test(self, ctx, action: str):
        """Preview an action's wording, with you as the member."""
        action = action.lower()
        if problem := self.check_target(action):
            await ctx.send(problem)
            return
        shown = False
        for kind in KINDS:
            content = self.db.invoke_of(ctx.guild.id, action, kind)
            if content:
                shown = True
                await ctx.send(f"**{kind}:**\n" + render(
                    content, ctx.guild, ctx.author, ctx.author, "test reason",
                    3600, 0), allowed_mentions=discord.AllowedMentions.none())
        if not shown:
            await ctx.send(f"`{action}` uses the default wording.")


async def setup(bot):
    await bot.add_cog(ModSettings(bot))
