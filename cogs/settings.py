"""Per-guild tuning. Anyone with Manage Server can change the rates."""
import discord
from discord.ext import commands

import config
import premium



def out_of_range(db, ctx, key: str, low: int, high: int) -> str:
    """Why a value wasn't taken, and which plan would take it."""
    more = premium.more_room(key, db.plan_rank(ctx.guild.id))
    return (f"`{key}` can be {low:,} to {high:,} here."
            + (f" {more}. `{ctx.prefix}upgrade` to see the plans." if more else ""))

class Settings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="settings", aliases=["conf"])
    @commands.guild_only()
    async def settings(self, ctx):
        """Show every tunable and its current value."""
        values = self.bot.db.all_settings(ctx.guild.id)
        embed = discord.Embed(
            title=f"Settings for {ctx.guild.name}",
            description=f"Change one with `{ctx.prefix}set <key> <value>`",
            colour=0x4EA8DE,
        )
        for key, (default, low, high, description) in config.GUILD_SETTINGS.items():
            current = values[key]
            low, high = self.bot.db.setting_range(ctx.guild.id, key)
            marker = "" if current == default else " *(changed)*"
            embed.add_field(
                name=f"{key} = {current}{marker}",
                value=f"{description}\nrange {low}–{high}, default {default}"
                      + (f"\n✨ {more}" if (more := premium.more_room(
                          key, self.bot.db.plan_rank(ctx.guild.id))) else ""),
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="set", aliases=["setconfig"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def set_setting(self, ctx, key: str, value: int):
        """Change one setting for this server."""
        key = key.lower()
        if key not in config.GUILD_SETTINGS:
            await ctx.send(
                "Unknown setting. Options: "
                + ", ".join(f"`{k}`" for k in config.GUILD_SETTINGS)
            )
            return
        low, high = self.bot.db.setting_range(ctx.guild.id, key)
        if not low <= value <= high:
            await ctx.send(out_of_range(self.bot.db, ctx, key, low, high))
            return
        self.bot.db.set_setting(ctx.guild.id, key, value)
        await ctx.send(f"`{key}` is now **{value}**.")

    @commands.command(name="resetsettings")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def reset_settings(self, ctx):
        """Put every setting back to its default."""
        self.bot.db.reset_settings(ctx.guild.id)
        await ctx.send("All settings reset to defaults.")


async def setup(bot):
    await bot.add_cog(Settings(bot))
