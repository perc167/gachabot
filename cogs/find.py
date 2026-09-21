"""Finding things: in the pool, in your harem, in your lists.

Mudae does this with flags - $fn, $fnw, $fnsl, $imas and a dozen more, each
a letter bolted onto a stem. That is a lot to remember for somebody who just
wants to know whether they already own a character, so these are separate
commands with names that say what they do, and the Mudae spellings are
aliases on top.

Everything here reads; nothing here changes anything.
"""
import discord
from discord.ext import commands

import config
import utils
from views import Paginator

PER_PAGE = 10


def listing(db, guild_id: int, title: str, rows, note: str = None,
            rate: int = 100):
    """A paged list of characters, worth and rank included."""
    icon = utils.shard_icon(config.SHARD_TYPES[0][0])
    lines = [
        f"**{row['name']}** · {row['series']}\n"
        f"　{icon} {utils.karuda_value(row, rate):,} · #{row['claim_rank']:,}"
        for row in rows
    ]
    pages = utils.paginate(lines, PER_PAGE)
    embeds = []
    for number, page in enumerate(pages, 1):
        embed = discord.Embed(
            title=title[:256],
            description="\n".join(page),
            colour=db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR),
        )
        embed.set_footer(
            text=f"Page {number}/{len(pages)} · {len(rows)} found"
                 + (f" · {note}" if note else "")
        )
        embeds.append(embed)
    return embeds


class Find(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _rate(self, ctx):
        return self.bot.db.get_setting(ctx.guild.id, "karuda_rate")

    # ------------------------------------------------- inside your things

    @commands.command(name="findharem", aliases=["fna", "fnall", "searchharem"])
    @commands.guild_only()
    async def findharem(self, ctx, *, text: str):
        """Find somebody in your own harem, by name or series."""
        db = self.bot.db
        gid = ctx.guild.id
        needle = text.lower()
        rows = [row for row in db.harem(gid, ctx.author.id, "likes")
                if needle in row["name"].lower()
                or needle in row["series"].lower()]
        if not rows:
            await ctx.send(f"Nobody in your harem matches `{text}`.")
            return
        await Paginator(
            listing(db, gid, f"Yours matching “{text}”", rows,
                    rate=self._rate(ctx)),
            ctx.author.id,
        ).start(ctx)

    @commands.command(name="findwish", aliases=["fnw", "searchwish"])
    @commands.guild_only()
    async def findwish(self, ctx, *, text: str = None):
        """Search your wishlist."""
        db = self.bot.db
        rows = db.wishes_of(ctx.guild.id, ctx.author.id)
        if text:
            needle = text.lower()
            rows = [r for r in rows if needle in r["name"].lower()
                    or needle in r["series"].lower()]
        if not rows:
            await ctx.send(
                f"Nothing on your wishlist matches `{text}`." if text
                else "Your wishlist is empty."
            )
            return
        await Paginator(
            listing(db, ctx.guild.id, "Your wishes", rows,
                    rate=self._rate(ctx)),
            ctx.author.id,
        ).start(ctx)

    @commands.command(name="findlike", aliases=["fnl", "searchlike"])
    @commands.guild_only()
    async def findlike(self, ctx, *, text: str = None):
        """Search your likelist."""
        db = self.bot.db
        rows = db.likes_of(ctx.guild.id, ctx.author.id)
        if text:
            needle = text.lower()
            rows = [r for r in rows if needle in r["name"].lower()
                    or needle in r["series"].lower()]
        if not rows:
            await ctx.send(
                f"Nothing you like matches `{text}`." if text
                else "You have not liked anybody."
            )
            return
        await Paginator(
            listing(db, ctx.guild.id, "Characters you like", rows,
                    rate=self._rate(ctx)),
            ctx.author.id,
        ).start(ctx)

    @commands.command(name="unowned", aliases=["fne", "findfree"])
    @commands.guild_only()
    async def unowned(self, ctx, *, series: str):
        """Who from a series nobody here has claimed yet."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = [row for row in db.series_cast(gid, series)
                if db.owner_of(gid, row["id"]) is None]
        if not rows:
            await ctx.send(
                f"Either nothing matches `{series}`, or this server has"
                " claimed every one of them."
            )
            return
        await Paginator(
            listing(db, gid, f"Unclaimed in {series}", rows,
                    note="free to roll for", rate=self._rate(ctx)),
            ctx.author.id,
        ).start(ctx)

    # ---------------------------------------------------- about the pool

    @commands.command(name="quietly", aliases=["ims", "imdm"])
    @commands.guild_only()
    async def quietly(self, ctx, *, name: str):
        """Look a character up, and get the card by DM."""
        db = self.bot.db
        rows = db.find_by_name_or_alias(ctx.guild.id, ctx.author.id, name)
        if not rows:
            await ctx.send(f"No character matching `{name}`.")
            return
        embed, art = utils.character_card(db, ctx.guild.id, rows[0])
        try:
            await ctx.author.send(embed=embed, **art)
        except discord.Forbidden:
            await ctx.send("Your DMs are closed.", embed=embed, **art)
            return
        await ctx.send(f"{ctx.author.mention} sent you a DM \U0001f4ec")

    @commands.command(name="imagecount", aliases=["ic", "imd"])
    @commands.guild_only()
    async def imagecount(self, ctx, *, name: str):
        """How many pictures a character has."""
        db = self.bot.db
        rows = db.find_by_name_or_alias(ctx.guild.id, ctx.author.id, name)
        if not rows:
            await ctx.send(f"No character matching `{name}`.")
            return
        character = rows[0]
        count = db.image_count(character["id"])
        await ctx.send(
            f"**{character['name']}** · {character['series']} — "
            + (f"**{count}** pictures. `{ctx.prefix}album {character['name']}`"
               " flips through them." if count
               else "no pictures yet.")
        )

    @commands.command(name="castof", aliases=["gc", "seriesinfo"])
    @commands.guild_only()
    async def castof(self, ctx, *, series: str):
        """What a series looks like: how many, how well known, who owns them."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.series_cast(gid, series)
        if not rows:
            await ctx.send(f"Nothing in the pool matches `{series}`.")
            return

        owned = sum(1 for r in rows if db.owner_of(gid, r["id"]) is not None)
        women = sum(1 for r in rows if (r["gender"] or "") == "Female")
        men = sum(1 for r in rows if (r["gender"] or "") == "Male")
        rate = self._rate(ctx)
        best = min(rows, key=lambda r: r["claim_rank"])
        worth = sum(utils.karuda_value(r, rate) for r in rows)

        embed = discord.Embed(
            title=rows[0]["series"][:256],
            colour=db.get_pref(gid, "cardcolour", config.CARD_COLOUR),
        )
        embed.add_field(
            name="Cast",
            value=f"**{len(rows)}** characters\n{women} women · {men} men",
            inline=True,
        )
        embed.add_field(
            name="Claimed here",
            value=f"**{owned}** of {len(rows)}\n"
                  f"{len(rows) - owned} still free",
            inline=True,
        )
        embed.add_field(
            name="Worth",
            value=f"{worth:,} all told\nbest: **{best['name']}**"
                  f" (#{best['claim_rank']:,})",
            inline=True,
        )
        embed.set_footer(
            text=f"{ctx.prefix}series {series} lists them · "
                 f"{ctx.prefix}unowned {series} shows the free ones"
        )
        await ctx.send(embed=embed)

    @commands.command(name="random", aliases=["rdmperso", "randomchar", "rp"])
    @commands.guild_only()
    async def random_character(self, ctx):
        """A character at random, without spending a roll."""
        db = self.bot.db
        character = db.random_character(
            ctx.guild.id, True, db.get_setting(ctx.guild.id, "roll_bias"))
        if character is None:
            await ctx.send("The pool is empty.")
            return
        embed, art = utils.character_card(
            db, ctx.guild.id, character, random_art=True,
            footer="a random character · this did not cost you a roll",
        )
        await ctx.send(embed=embed, **art)


async def setup(bot):
    await bot.add_cog(Find(bot))
