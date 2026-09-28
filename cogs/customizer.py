"""$botprofile: Paper's own name, picture, banner and bio on this server.

A Paper Premium perk (the name is free). The work is in botprofile.py,
shared with the dashboard. Every hour this checks for servers whose Premium
has ended and puts Paper's own picture, banner and bio back there.
"""
import logging

import discord
from discord.ext import commands, tasks

import botprofile

log = logging.getLogger("customizer")


class Customizer(commands.Cog):
    works_everywhere = True  # an admin command; see cogs/modtools.py

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.lapsed.start()

    async def cog_unload(self):
        self.lapsed.cancel()

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        return True

    async def change(self, ctx, done: str, **fields):
        try:
            await botprofile.update(self.bot, ctx.guild,
                                    f"$botprofile by {ctx.author} ({ctx.author.id})",
                                    **fields)
        except botprofile.ProfileError as e:
            message = str(e)
            if "Premium" in message:
                message += f" `{ctx.prefix}upgrade` to see how to get it."
            await ctx.send(message)
            return
        await ctx.send(done)

    async def picture(self, ctx, kind: str, reset: str):
        if reset and reset.lower() in ("reset", "off", "remove", "default"):
            await self.change(ctx, f"My {kind} here is Paper's own again.", **{kind: None})
            return
        if not ctx.message.attachments:
            await ctx.send(f"Attach a picture to `{ctx.prefix}botprofile {kind}`,"
                           f" or say `{ctx.prefix}botprofile {kind} reset`.")
            return
        raw = await ctx.message.attachments[0].read()
        await self.change(ctx, f"Done: that's my {kind} on this server now.",
                          **{kind: raw})

    @commands.group(name="botprofile", aliases=["customize", "customise"],
                    invoke_without_command=True)
    async def botprofile_(self, ctx):
        """Paper's profile on this server, and how to change it."""
        now = botprofile.state(self.bot, ctx.guild)
        p = ctx.prefix
        embed = discord.Embed(
            title="Make Paper yours",
            description=(
                "Give Paper its own look on this server. Only this server sees it.\n\n"
                f"`{p}botprofile name <name>` · a new name (free)\n"
                f"`{p}botprofile avatar` + a picture · ✨ a new profile picture\n"
                f"`{p}botprofile banner` + a picture · ✨ a profile banner\n"
                f"`{p}botprofile bio <text>` · ✨ an About Me\n"
                f"`{p}botprofile reset` · everything back to Paper's own\n\n"
                "Add `reset` to any of them to undo just that one."),
            colour=0x7C6BF0)
        embed.add_field(name="Name", value=now["nick"] or f"{now['name']} (Paper's own)")
        embed.add_field(name="Bio", value=now["bio"] or "Paper's own", inline=False)
        if now["avatar"]:
            embed.set_thumbnail(url=now["avatar"])
        if now["banner"]:
            embed.set_image(url=now["banner"])
        if not self.bot.db.is_premium(ctx.guild.id):
            embed.set_footer(text=f"✨ The picture, banner and bio come with Paper Premium."
                                  f" {p}upgrade to see how to get it.")
        await ctx.send(embed=embed)

    @botprofile_.command(name="name", aliases=["nick", "nickname"])
    @commands.has_permissions(manage_guild=True)
    async def bp_name(self, ctx, *, name: str):
        """A name for Paper on this server. `reset` for its own."""
        if name.lower() in ("reset", "off", "remove", "default"):
            await self.change(ctx, "I'm back to my own name here.", nick=None)
            return
        await self.change(ctx, f"I'm **{discord.utils.escape_markdown(name.strip())}** here now.",
                          nick=name)

    @botprofile_.command(name="avatar", aliases=["picture", "pfp", "icon"])
    @commands.has_permissions(manage_guild=True)
    async def bp_avatar(self, ctx, reset: str = None):
        """Premium: attach a picture for Paper's profile picture here."""
        await self.picture(ctx, "avatar", reset)

    @botprofile_.command(name="banner")
    @commands.has_permissions(manage_guild=True)
    async def bp_banner(self, ctx, reset: str = None):
        """Premium: attach a picture for Paper's profile banner here."""
        await self.picture(ctx, "banner", reset)

    @botprofile_.command(name="bio", aliases=["about", "aboutme"])
    @commands.has_permissions(manage_guild=True)
    async def bp_bio(self, ctx, *, text: str):
        """Premium: Paper's About Me on this server. `reset` for its own."""
        if text.lower() in ("reset", "off", "remove", "default"):
            await self.change(ctx, "My bio here is Paper's own again.", bio=None)
            return
        await self.change(ctx, "Done: that's my bio on this server now.", bio=text)

    @botprofile_.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def bp_reset(self, ctx):
        """Paper's own name, picture, banner and bio again."""
        try:
            await botprofile.reset(self.bot, ctx.guild, f"$botprofile reset by {ctx.author}")
        except botprofile.ProfileError as e:
            await ctx.send(str(e))
            return
        await ctx.send("I'm back to my own profile here.")

    @tasks.loop(hours=1)
    async def lapsed(self):
        """Premium ended: Paper's own picture, banner and bio again. The name
        was never Premium, so it stays."""
        for row in self.bot.db.custom_bot_profiles():
            if self.bot.db.is_premium(row["guild_id"]):
                continue
            guild = self.bot.get_guild(row["guild_id"])
            if guild is None:
                self.bot.db.save_bot_profile(row["guild_id"], "", "", "")
                continue
            try:
                await botprofile.reset(self.bot, guild, "Paper Premium ended", name_too=False)
            except botprofile.ProfileError:
                log.warning("couldn't reset Paper's profile in %s", guild.id)

    @lapsed.before_loop
    async def before_lapsed(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Customizer(bot))
