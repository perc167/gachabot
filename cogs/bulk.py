"""Doing things to many characters at once.

Divorcing forty characters one at a time is nobody's idea of a game, and the
same goes for wishing a whole cast. Everything destructive here asks first
and says exactly how many it is about to touch.
"""
import discord
from discord.ext import commands

import config
import perks
import utils
import wishes
from views import Confirm, Paginator, choose_character


class Bulk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _paid(self, ctx, refund: int) -> str:
        """Hand the refund over and say so, or say nothing."""
        if not refund:
            return ""
        total = self.bot.db.add_karuda(ctx.guild.id, ctx.author.id, refund)
        return f" +{refund:,} karuda (total: {total:,})."

    async def _confirm(self, ctx, question: str) -> bool:
        view = Confirm({ctx.author.id})
        view.message = await ctx.send(question, view=view)
        await view.wait()
        return bool(view.accepted) and not view.declined_by

    async def _pick_series(self, ctx, query: str):
        """Turn a typed series name into one actual series."""
        matches = self.bot.db.search_series(query, guild_id=ctx.guild.id)
        if not matches:
            await ctx.send(f"No series matching `{query}`.")
            return None
        if len(matches) == 1:
            return matches[0][0]

        view = discord.ui.View(timeout=120)
        select = discord.ui.Select(
            placeholder="Which series?",
            options=[
                discord.SelectOption(
                    label=title[:100], value=str(index), description=f"{cast} characters"
                )
                for index, (title, cast) in enumerate(matches[:25])
            ],
        )
        picked = {}

        async def on_select(interaction: discord.Interaction):
            if interaction.user.id != ctx.author.id:
                await interaction.response.send_message(
                    "Not your menu.", ephemeral=True
                )
                return
            picked["series"] = matches[int(interaction.data["values"][0])][0]
            select.disabled = True
            await interaction.response.edit_message(view=view)
            view.stop()

        select.callback = on_select
        view.add_item(select)
        await ctx.send(
            embed=discord.Embed(
                title=f"{len(matches)} series match “{query}”",
                colour=config.CARD_COLOUR,
            ),
            view=view,
        )
        await view.wait()
        return picked.get("series")

    @commands.command(name="divorceall", aliases=["dva", "divorceall2"])
    @commands.guild_only()
    async def divorceall(self, ctx):
        """Let go of your entire harem."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.harem(gid, ctx.author.id)
        if not rows:
            await ctx.send("You have not claimed anyone.")
            return
        refund = utils.divorce_refund(db, gid, rows)
        worth = f" for **+{refund:,}** karuda" if refund else ""
        if not await self._confirm(
            ctx,
            f"{ctx.author.mention} this divorces **all {len(rows)}** of your"
            f" characters{worth}. There is no undo.",
        ):
            await ctx.send("Nothing divorced.")
            return
        count = db.divorce_many(gid, ctx.author.id, [r["id"] for r in rows])
        await ctx.send(f"Divorced **{count}** characters."
                       + self._paid(ctx, refund))

    @commands.command(name="divorceseries", aliases=["dvs", "divorcesl", "dsl"])
    @commands.guild_only()
    async def divorceseries(self, ctx, *, series: str):
        """Let go of everyone you own from one series."""
        db = self.bot.db
        gid = ctx.guild.id
        title = await self._pick_series(ctx, series)
        if not title:
            return
        rows = db.harem_by_series(gid, ctx.author.id, title)
        if not rows:
            await ctx.send(f"You own nobody from **{title}**.")
            return
        listing = ", ".join(r["name"] for r in rows[:10])
        if len(rows) > 10:
            listing += f" and {len(rows) - 10} more"
        refund = utils.divorce_refund(db, gid, rows)
        worth = f" for **+{refund:,}** karuda" if refund else ""
        if not await self._confirm(
            ctx,
            f"Divorce **{len(rows)}** from **{title}**{worth}?\n{listing}"
        ):
            await ctx.send("Nothing divorced.")
            return
        count = db.divorce_many(gid, ctx.author.id, [r["id"] for r in rows])
        await ctx.send(f"Divorced **{count}** from **{title}**."
                       + self._paid(ctx, refund))

    @commands.command(name="divorceallbut", aliases=["dvab"])
    @commands.guild_only()
    async def divorceallbut(self, ctx, keep: int = 10):
        """Keep your most valuable N and divorce the rest."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.harem(gid, ctx.author.id, "karuda")
        if len(rows) <= keep:
            await ctx.send(f"You only have {len(rows)}; nothing to trim.")
            return
        doomed = rows[keep:]
        refund = utils.divorce_refund(db, gid, doomed)
        worth = f" for **+{refund:,}** karuda" if refund else ""
        if not await self._confirm(
            ctx,
            f"Keep your top **{keep}** by value and divorce the other"
            f" **{len(doomed)}**{worth}?",
        ):
            await ctx.send("Nothing divorced.")
            return
        count = db.divorce_many(gid, ctx.author.id, [r["id"] for r in doomed])
        await ctx.send(f"Divorced **{count}**, kept your top {keep}."
                       + self._paid(ctx, refund))

    @commands.command(name="wishseries", aliases=["wsr"])
    @commands.guild_only()
    async def wishseries(self, ctx, *, series: str):
        """Wish for everyone from a series, up to your remaining slots."""
        db = self.bot.db
        gid = ctx.guild.id
        title = await self._pick_series(ctx, series)
        if not title:
            return

        room = wishes.room(db, gid, ctx.author.id)
        if room <= 0:
            await ctx.send(f"Your wishlist is full"
                           f" ({wishes.capacity(db, gid, ctx.author.id)} slots).")
            return

        cast = db.characters_in_series(title, guild_id=ctx.guild.id)
        added = 0
        for row in cast:
            if added >= room:
                break
            if db.owner_of(gid, row["id"]) == ctx.author.id:
                continue
            if db.add_wish(gid, ctx.author.id, row["id"]):
                added += 1
        if not added:
            await ctx.send(f"Nothing new to wish for from **{title}**.")
            return
        note = ""
        if len(cast) > added:
            note = f" ({len(cast) - added} skipped — no room, or already wished)"
        await ctx.send(f"Wished for **{added}** from **{title}**{note}.")

    @commands.command(name="wishremoveall", aliases=["wishpurge", "clearwishes"])
    @commands.guild_only()
    async def wishremoveall(self, ctx):
        """Empty your wishlist."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.wishes_of(gid, ctx.author.id)
        if not rows:
            await ctx.send("Your wishlist is already empty.")
            return
        if not await self._confirm(ctx, f"Clear all **{len(rows)}** of your wishes?"):
            await ctx.send("Wishlist untouched.")
            return
        for row in rows:
            db.remove_wish(gid, ctx.author.id, row["id"])
        kept = db.starwish_count(gid, ctx.author.id)
        await ctx.send(f"Cleared **{len(rows)}** wishes."
                       + (f" Your {kept} starwish{'es' if kept != 1 else ''} stayed;"
                          f" `{ctx.prefix}starwish remove <name>` drops one." if kept else ""))

    @commands.command(name="series", aliases=["sr", "mudanime", "anime", "sl"])
    @commands.guild_only()
    async def series(self, ctx, *, query: str):
        """Look up a series and who is in it."""
        db = self.bot.db
        title = await self._pick_series(ctx, query)
        if not title:
            return
        cast = db.characters_in_series(title, guild_id=ctx.guild.id)
        rate = db.get_setting(ctx.guild.id, "karuda_rate")
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])

        lines = []
        for row in cast:
            owner = db.owner_of(ctx.guild.id, row["id"])
            tag = f" — <@{owner}>" if owner else ""
            lines.append(
                f"**{row['name']}** · {icon} {utils.karuda_value(row, rate):,}"
                f" · #{row['like_rank']:,}{tag}"
            )
        pages = utils.paginate(lines, 10)
        embeds = []
        for number, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=title,
                description="\n".join(page),
                colour=config.CARD_COLOUR,
            )
            embed.set_footer(
                text=f"Page {number}/{len(pages)} · {len(cast)} characters"
            )
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)


async def setup(bot):
    await bot.add_cog(Bulk(bot))
