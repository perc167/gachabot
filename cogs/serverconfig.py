"""Server configuration: friendly setters, prefix, and switching things off.

`$set <key> <value>` already reaches every tunable, but nobody arriving from
Mudae knows that. These are the names they will actually type, each mapping
onto the same settings table.
"""
import discord
from discord.ext import commands

import config
import premium
from cogs.settings import out_of_range

# command name -> (setting key, unit shown in the reply)
SETTERS = {
    "setrolls": ("roll_limit", "rolls per window"),
    "setinterval": ("roll_reset_minutes", "minutes between roll refills"),
    "setclaim": ("claim_interval_minutes", "minutes between claims"),
    "setkinterval": ("karuda_interval_minutes", "minutes between karuda grabs"),
    "setwindow": ("claim_window_seconds", "seconds a roll stays claimable"),
    "setrate": ("karuda_rate", "percent karuda payout"),
    "setgrab": ("karuda_grab_percent", "percent of value per grab"),
    "setrefund": ("divorce_refund_percent", "percent refunded on divorce"),
    "setwishlimit": ("wish_limit", "wishes per person"),
    "setharemlimit": ("max_marriages", "harem cap, 0 for none"),
    "setwishprotect": ("wish_protect_seconds", "seconds of wisher head start"),
}

# Commands that must never be switched off, or a server could lock itself out.
PROTECTED = {"enable", "enableall", "settings", "help", "channelallow"}


class ServerConfig(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        # Everything here changes the server, so it needs Manage Server.
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        if not ctx.author.guild_permissions.manage_guild:
            raise commands.MissingPermissions(["manage_guild"])
        return True

    @commands.command(name="setrolls", aliases=list(SETTERS)[1:])
    async def setter(self, ctx, value: int = None):
        """Friendly wrappers around $set: $setrolls 20, $setclaim 60, ..."""
        key, unit = SETTERS[ctx.invoked_with.lower()]
        default, _low, _high, description = config.GUILD_SETTINGS[key]
        low, high = self.bot.db.setting_range(ctx.guild.id, key)
        if value is None:
            current = self.bot.db.get_setting(ctx.guild.id, key)
            more = premium.more_room(key, self.bot.db.plan_rank(ctx.guild.id))
            await ctx.send(
                f"`{key}` is **{current}** {unit} (default {default},"
                f" range {low}–{high}).\n{description}"
                + (f"\n✨ {more}" if more else "")
            )
            return
        if not low <= value <= high:
            await ctx.send(out_of_range(self.bot.db, ctx, key, low, high))
            return
        self.bot.db.set_setting(ctx.guild.id, key, value)
        await ctx.send(f"`{key}` is now **{value}** {unit}.")

    @commands.command(name="prefix", aliases=["setprefix"])
    async def prefix(self, ctx, new: str = None):
        """Change the prefix for this server. `$prefix reset` to undo."""
        db = self.bot.db
        if new is None:
            current = db.get_prefix(ctx.guild.id) or config.PREFIX
            await ctx.send(f"Prefix here is `{current}`.")
            return
        if new.lower() in ("reset", "default"):
            db.clear_prefix(ctx.guild.id)
            await ctx.send(f"Prefix back to `{config.PREFIX}`.")
            return
        if len(new) > 5 or new.isspace():
            await ctx.send("Prefixes are 1 to 5 characters, no spaces.")
            return
        db.set_prefix(ctx.guild.id, new)
        await ctx.send(f"Prefix is now `{new}` — try `{new}help`.")

    @commands.command(name="disable", aliases=["serverdisable"])
    async def disable(self, ctx, command: str):
        """Switch a command off for this server."""
        name = command.lstrip(ctx.prefix).lower()
        found = self.bot.get_command(name)
        if not found:
            await ctx.send(f"No command called `{name}`.")
            return
        if found.name in PROTECTED:
            await ctx.send(
                f"`{found.name}` cannot be disabled — you would lock yourself out."
            )
            return
        if self.bot.db.disable_command(ctx.guild.id, found.name):
            await ctx.send(f"`{found.name}` is off for this server.")
        else:
            await ctx.send(f"`{found.name}` was already off.")

    @commands.command(name="enable", aliases=["serverenable"])
    async def enable(self, ctx, command: str):
        """Switch a command back on."""
        name = command.lstrip(ctx.prefix).lower()
        found = self.bot.get_command(name)
        target = found.name if found else name
        if self.bot.db.enable_command(ctx.guild.id, target):
            await ctx.send(f"`{target}` is on again.")
        else:
            await ctx.send(f"`{target}` was not disabled.")

    @commands.command(name="enableall", aliases=["serverenableall"])
    async def enableall(self, ctx):
        """Switch every disabled command back on."""
        count = self.bot.db.enable_all_commands(ctx.guild.id)
        await ctx.send(f"Re-enabled **{count}** command(s).")

    @commands.command(name="disablelist", aliases=["disabled"])
    async def disablelist(self, ctx):
        """What is currently switched off here."""
        off = sorted(self.bot.db.disabled_commands(ctx.guild.id))
        if not off:
            await ctx.send("Nothing is disabled here.")
            return
        await ctx.send(
            embed=discord.Embed(
                title=f"{len(off)} disabled",
                description=" ".join(f"`{name}`" for name in off),
                colour=config.CARD_COLOUR,
            )
        )

    @commands.command(name="channelallow", aliases=["setchannel"])
    async def channelallow(self, ctx, channel: discord.TextChannel = None):
        """Limit the bot to certain channels. Allow one and only those work."""
        channel = channel or ctx.channel
        if self.bot.db.allow_channel(ctx.guild.id, channel.id):
            allowed = self.bot.db.allowed_channels(ctx.guild.id)
            await ctx.send(
                f"{channel.mention} allowed. The bot now answers in"
                f" **{len(allowed)}** channel(s) only."
            )
        else:
            await ctx.send(f"{channel.mention} was already allowed.")

    @commands.command(name="channeldeny", aliases=["unsetchannel"])
    async def channeldeny(self, ctx, channel: discord.TextChannel = None):
        """Remove a channel from the allow list."""
        channel = channel or ctx.channel
        if self.bot.db.unallow_channel(ctx.guild.id, channel.id):
            left = self.bot.db.allowed_channels(ctx.guild.id)
            note = (
                " The list is empty, so the bot answers everywhere again."
                if not left
                else f" {len(left)} channel(s) still allowed."
            )
            await ctx.send(f"{channel.mention} removed.{note}")
        else:
            await ctx.send(f"{channel.mention} was not on the list.")

    @commands.command(name="channellist", aliases=["channels"])
    async def channellist(self, ctx):
        """Which channels the bot will answer in."""
        allowed = self.bot.db.allowed_channels(ctx.guild.id)
        if not allowed:
            await ctx.send("No restriction — the bot answers in every channel.")
            return
        await ctx.send(
            "Answering only in: "
            + ", ".join(f"<#{channel_id}>" for channel_id in allowed)
        )

    @commands.command(name="channelclear")
    async def channelclear(self, ctx):
        """Drop the channel restriction entirely."""
        count = self.bot.db.clear_allowed_channels(ctx.guild.id)
        await ctx.send(f"Cleared {count} channel restriction(s).")


async def setup(bot):
    await bot.add_cog(ServerConfig(bot))
