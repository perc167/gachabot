"""Characters a server invents for itself.

These live in the same table as the shared pool but carry the guild's id, so
they roll, claim and trade exactly like anything else - and only in the server
that made them. Nobody else ever sees them.

Managed with Manage Server rather than bot ownership: it is that server's
pool, and waiting on the bot owner to add an inside joke would defeat the
point.
"""
import discord
from discord.ext import commands

import config
import utils
from views import Paginator, choose_character


class Custom(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.NoPrivateMessage()
        # Reading the list is open; changing it needs Manage Server.
        if ctx.command.name in ("customlist", "customs"):
            return True
        if not ctx.author.guild_permissions.manage_guild:
            raise commands.MissingPermissions(["manage_guild"])
        return True

    def _limit(self, gid: int) -> int:
        return self.bot.db.get_setting(gid, "custom_limit")

    async def _own_custom(self, ctx, name: str):
        """Find one of this server's own customs by name."""
        rows = [
            row
            for row in self.bot.db.find_characters_by_name(
                name, guild_id=ctx.guild.id
            )
            if row["guild_id"] == ctx.guild.id
        ]
        if not rows:
            await ctx.send(
                f"`{name}` is not one of this server's custom characters."
                f" See `{ctx.prefix}customlist`."
            )
            return None
        return await choose_character(ctx, rows, "Which one?", config.CARD_COLOUR)

    @commands.command(name="addcustom", aliases=["ac", "customadd"])
    async def addcustom(self, ctx, *, args: str):
        """`$addcustom Name | Series | image url` — image optional.

        Attach an image instead of pasting a link if you prefer.
        """
        db = self.bot.db
        gid = ctx.guild.id
        limit = self._limit(gid)
        if db.custom_count(gid) >= limit:
            await ctx.send(
                f"This server is at its limit of **{limit}** custom characters."
                f" Raise it with `{ctx.prefix}set custom_limit <n>` or remove one."
            )
            return

        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            await ctx.send(
                f"Usage: `{ctx.prefix}addcustom Name | Series | image url`"
            )
            return
        name, series = parts[0][:100], parts[1][:100]
        image = parts[2] if len(parts) > 2 else ""
        if not image and ctx.message.attachments:
            image = ctx.message.attachments[0].url
        if image and not image.startswith(("http://", "https://")):
            await ctx.send("The image has to be an http(s) link, or left out.")
            return

        character_id = db.add_custom(gid, name, series, image)
        if character_id is None:
            await ctx.send(f"**{name}** ({series}) already exists.")
            return

        embed = utils.character_embed(db, gid, db.get_character(character_id))
        await ctx.send(
            f"Added **{name}** — only this server rolls them."
            f" ({db.custom_count(gid)}/{limit} used)",
            embed=embed,
        )

    @commands.command(name="deletecustom", aliases=["dc", "customdelete"])
    async def deletecustom(self, ctx, *, name: str):
        """Remove one of this server's custom characters."""
        character = await self._own_custom(ctx, name)
        if not character:
            return
        self.bot.db.delete_character(character["id"])
        await ctx.send(
            f"Deleted **{character['name']}**, along with any claims on them."
        )

    @commands.command(name="namecustom", aliases=["renamecustom"])
    async def namecustom(self, ctx, *, args: str):
        """`$namecustom Old name | New name`"""
        if "|" not in args:
            await ctx.send(f"Usage: `{ctx.prefix}namecustom Old | New`")
            return
        old, _, new = args.partition("|")
        character = await self._own_custom(ctx, old.strip())
        if not character:
            return
        new = new.strip()[:100]
        if not new:
            await ctx.send("Give them a new name.")
            return
        try:
            self.bot.db.update_character(character["id"], name=new)
        except Exception:  # DuplicateCharacter, reported plainly
            await ctx.send(f"**{new}** already exists in that series.")
            return
        await ctx.send(f"**{character['name']}** is now **{new}**.")

    @commands.command(name="seriescustom", aliases=["setseriescustom"])
    async def seriescustom(self, ctx, *, args: str):
        """`$seriescustom Name | New series`"""
        if "|" not in args:
            await ctx.send(f"Usage: `{ctx.prefix}seriescustom Name | New series`")
            return
        name, _, series = args.partition("|")
        character = await self._own_custom(ctx, name.strip())
        if not character:
            return
        self.bot.db.update_character(character["id"], series=series.strip()[:100])
        await ctx.send(
            f"**{character['name']}** is now filed under **{series.strip()}**."
        )

    @commands.command(name="imgcustom", aliases=["customimg", "addimgcustom"])
    async def imgcustom(self, ctx, *, args: str):
        """`$imgcustom Name | url` — add an image, or attach one."""
        name, _, url = args.partition("|")
        url = url.strip()
        if not url and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        character = await self._own_custom(ctx, name.strip())
        if not character:
            return
        if not url.startswith(("http://", "https://")):
            await ctx.send("Give me an http(s) link, or attach an image.")
            return
        if self.bot.db.add_image(character["id"], url, source="custom"):
            total = self.bot.db.image_count(character["id"])
            await ctx.send(
                f"Added an image to **{character['name']}** — album is now {total}."
            )
        else:
            await ctx.send("That image is already in the album.")

    @commands.command(name="valuecustom", aliases=["setvaluecustom"])
    async def valuecustom(self, ctx, value: int, *, name: str):
        """`$valuecustom 250 Some Name` — what they are worth."""
        if not 1 <= value <= 5000:
            await ctx.send("Pick a value between 1 and 5000.")
            return
        character = await self._own_custom(ctx, name)
        if not character:
            return
        self.bot.db.update_character(character["id"], base_karuda=value)
        await ctx.send(f"**{character['name']}** is now worth **{value:,}**.")

    @commands.command(name="customlist", aliases=["customs"])
    async def customlist(self, ctx):
        """Every custom character this server has made."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.customs_of(gid)
        if not rows:
            await ctx.send(
                f"No custom characters yet. Add one with"
                f" `{ctx.prefix}addcustom Name | Series`."
            )
            return

        rate = db.get_setting(gid, "karuda_rate")
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])
        lines = []
        for row in rows:
            owner = db.owner_of(gid, row["id"])
            tag = f" — <@{owner}>" if owner else ""
            art = "" if row["image_url"] else " · *no image*"
            lines.append(
                f"**{row['name']}** · {row['series']} ·"
                f" {icon} {utils.karuda_value(row, rate):,}{art}{tag}"
            )

        pages = utils.paginate(lines, 10)
        embeds = []
        for number, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{ctx.guild.name}'s custom characters",
                description="\n".join(page),
                colour=config.CARD_COLOUR,
            )
            embed.set_footer(
                text=f"Page {number}/{len(pages)} · "
                     f"{len(rows)}/{self._limit(gid)} used"
            )
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)


async def setup(bot):
    await bot.add_cog(Custom(bot))
