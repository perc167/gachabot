"""The rest of Mudae's harem vocabulary: sorting, slicing and showcasing.

`$mm` itself lives in cogs/harem.py. These are the commands that do something
to a harem rather than just show it - narrowing it to one gender, finding
where somebody sits in it, letting go of a page at a time, and picking the
one character who sits at the top of your profile.
"""
import discord
from discord.ext import commands

import config
import utils
from views import Confirm, Paginator, choose_character

ORDERS = ("likes", "name", "recent", "karuda")
PER_PAGE = 8


def cards(db, guild_id: int, rows, member, order: str, note: str = None):
    """One card per character, art and all."""
    embeds, art = [], []
    total = len(rows)
    for position, row in enumerate(rows, 1):
        footer = f"{position}/{total} · {member.display_name} · by {order}"
        if note:
            footer = f"{note} · {footer}"
        image = db.random_image(row["id"]) or row["image_url"]
        embeds.append(utils.character_embed(db, guild_id, row,
                                            image_url=image, footer=footer))
        art.append(image)
    return embeds, art


class HaremExtra(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _order_for(self, ctx, given: str = None) -> str:
        """What to sort by: what they asked for, else what they chose once."""
        if given in ORDERS:
            return given
        saved = self.bot.db.harem_sort_of(ctx.guild.id, ctx.author.id)
        return saved if saved in ORDERS else "likes"

    async def _show(self, ctx, member, gender, label, order=None):
        db = self.bot.db
        gid = ctx.guild.id
        order = self._order_for(ctx, order)
        rows = db.harem_filtered(gid, member.id, order, gender)
        if not rows:
            what = f" {label}" if label else ""
            await ctx.send(
                f"{member.display_name} has no{what} characters here."
                + ("\nAbout half the roster has no gender recorded, so they"
                   " only show under the plain harem." if gender else "")
            )
            return
        embeds, art = cards(db, gid, rows, member, order, label or None)
        await Paginator(embeds, ctx.author.id, art=art).start(ctx)

    @commands.command(name="mmw", aliases=["haremwaifus"])
    @commands.guild_only()
    async def mmw(self, ctx, member: discord.Member = None, order: str = None):
        """The women in a harem."""
        await self._show(ctx, member or ctx.author, "Female", "women", order)

    @commands.command(name="mmh", aliases=["haremhusbandos"])
    @commands.guild_only()
    async def mmh(self, ctx, member: discord.Member = None, order: str = None):
        """The men in a harem."""
        await self._show(ctx, member or ctx.author, "Male", "men", order)

    @commands.command(name="mmr", aliases=["haremvalue"])
    @commands.guild_only()
    async def mmr(self, ctx, member: discord.Member = None):
        """A harem, most valuable first."""
        await self._show(ctx, member or ctx.author, None, None, "karuda")

    @commands.command(name="sortmarry", aliases=["sortm", "haremsort"])
    @commands.guild_only()
    async def sortmarry(self, ctx, order: str = None):
        """Choose how your harem sorts by default."""
        if order not in ORDERS:
            current = self._order_for(ctx)
            await ctx.send(
                f"Your harem sorts by **{current}**. Pick one of: "
                + ", ".join(f"`{o}`" for o in ORDERS)
            )
            return
        self.bot.db.set_harem_sort(ctx.guild.id, ctx.author.id, order)
        await ctx.send(f"Your harem sorts by **{order}** from now on.")

    @commands.command(name="smpos", aliases=["sortmarrypos", "harempos"])
    @commands.guild_only()
    async def smpos(self, ctx, *, name: str):
        """Where a character sits in your harem."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = [row for row in db.find_by_name_or_alias(gid, ctx.author.id, name)
                if db.owner_of(gid, row["id"]) == ctx.author.id]
        if not rows:
            await ctx.send(f"You do not own anyone called `{name}`.")
            return
        character = await choose_character(ctx, rows, "Which one?",
                                           config.CARD_COLOUR)
        if not character:
            return
        order = self._order_for(ctx)
        position = db.harem_position(gid, ctx.author.id, character["id"], order)
        size = db.harem_size(gid, ctx.author.id)
        page = (position - 1) // PER_PAGE + 1
        await ctx.send(
            f"**{character['name']}** is **#{position}** of {size},"
            f" sorted by {order} — page {page}."
        )

    @commands.command(name="divorcepage", aliases=["dpage"])
    @commands.guild_only()
    async def divorcepage(self, ctx, page: int, order: str = None):
        """Let go of everyone on one page of your harem."""
        db = self.bot.db
        gid = ctx.guild.id
        order = self._order_for(ctx, order)
        rows = db.harem(gid, ctx.author.id, order)
        if not rows:
            await ctx.send("You have not claimed anyone yet.")
            return
        pages = (len(rows) - 1) // PER_PAGE + 1
        if not 1 <= page <= pages:
            await ctx.send(f"You have {pages} pages, sorted by {order}.")
            return

        slice_ = rows[(page - 1) * PER_PAGE:page * PER_PAGE]
        names = ", ".join(row["name"] for row in slice_)
        refund = utils.divorce_refund(db, gid, slice_)
        worth = f" for **+{refund:,}** karuda" if refund else ""
        view = Confirm([ctx.author.id])
        view.message = await ctx.send(
            f"Divorce all **{len(slice_)}** on page {page} of {pages}"
            f" (by {order}){worth}?\n{names}",
            view=view,
        )
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Nobody was divorced.")
            return
        gone = db.divorce_many(gid, ctx.author.id, [row["id"] for row in slice_])
        line = f"Divorced **{gone}**."
        if refund:
            total = db.add_karuda(gid, ctx.author.id, refund)
            line += f" +{refund:,} karuda (total: {total:,})."
        await ctx.send(line)

    @commands.command(name="firstmarry", aliases=["fm", "showcase"])
    @commands.guild_only()
    async def firstmarry(self, ctx, *, name: str = None):
        """The one character shown at the top of your profile."""
        db = self.bot.db
        gid = ctx.guild.id
        if not name:
            current = db.showcase_of(gid, ctx.author.id)
            if not current:
                await ctx.send(
                    f"You have not picked one. `{ctx.prefix}fm <name>` does it."
                )
                return
            embed, art = utils.character_card(db, gid, current,
                                              footer="Your showcase")
            await ctx.send(embed=embed, **art)
            return

        rows = [row for row in db.find_by_name_or_alias(gid, ctx.author.id, name)
                if db.owner_of(gid, row["id"]) == ctx.author.id]
        if not rows:
            await ctx.send(f"You do not own anyone called `{name}`.")
            return
        character = await choose_character(ctx, rows, "Which one?",
                                           config.CARD_COLOUR)
        if not character:
            return
        db.set_showcase(gid, ctx.author.id, character["id"])
        embed, art = utils.character_card(db, gid, character,
                                          footer="Your showcase")
        await ctx.send(f"**{character['name']}** leads your profile now.",
                       embed=embed, **art)

    @commands.command(name="infomarry", aliases=["infomarrya", "claiminfo"])
    @commands.guild_only()
    async def infomarry(self, ctx, *, name: str):
        """Who owns a character here, and since when."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.find_by_name_or_alias(gid, ctx.author.id, name)
        if not rows:
            await ctx.send(f"No character matching `{name}`.")
            return
        character = await choose_character(ctx, rows, "Which one?",
                                           config.CARD_COLOUR)
        if not character:
            return
        info = db.claim_info(gid, character["id"])
        if not info:
            await ctx.send(
                f"**{character['name']}** is unclaimed here — roll and take them."
            )
            return
        embed, art = utils.character_card(db, gid, character)
        embed.add_field(
            name="Claimed",
            value=f"<@{info['user_id']}> · <t:{info['claimed_at']}:R>",
            inline=False,
        )
        if info["note"]:
            embed.add_field(name="Their note", value=f"*{info['note']}*",
                            inline=False)
        await ctx.send(embed=embed, **art)

    @commands.command(name="haremcopy", aliases=["hcopy", "haremexport"])
    @commands.guild_only()
    async def haremcopy(self, ctx, member: discord.Member = None):
        """Your harem as plain text, ready to paste somewhere."""
        member = member or ctx.author
        rows = self.bot.db.harem(ctx.guild.id, member.id,
                                 self._order_for(ctx))
        if not rows:
            await ctx.send(f"{member.display_name} has not claimed anyone.")
            return
        text = "\n".join(f"{row['name']} · {row['series']}" for row in rows)
        if len(text) > 1900:
            # Too long to paste in a message, so send it as a file instead of
            # quietly cutting the list off.
            import io as _io
            buffer = _io.BytesIO(text.encode("utf-8"))
            await ctx.send(
                f"{len(rows)} characters — too many for one message.",
                file=discord.File(buffer, filename="harem.txt"),
            )
            return
        await ctx.send(f"**{member.display_name}** — {len(rows)} characters\n"
                       f"```\n{text}\n```")

    @commands.command(name="haremlimit", aliases=["maxharem"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def haremlimit(self, ctx, size: int = None):
        """Cap how many characters one person may hold. 0 is no cap."""
        db = self.bot.db
        if size is None:
            current = db.get_setting(ctx.guild.id, "max_marriages")
            await ctx.send(
                f"Harems are capped at **{current}**." if current
                else "Harems are uncapped here."
            )
            return
        _default, low, high, _desc = config.GUILD_SETTINGS["max_marriages"]
        if not low <= size <= high:
            await ctx.send(f"Pick a number from {low} to {high}.")
            return
        db.set_setting(ctx.guild.id, "max_marriages", size)
        await ctx.send(
            f"Harems are capped at **{size}**." if size
            else "Harems are uncapped now."
        )


async def setup(bot):
    await bot.add_cog(HaremExtra(bot))
