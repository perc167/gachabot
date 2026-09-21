"""The commands that make the bot talk about your collection your way.

Mudae lets you rename the words it uses at you - your harem, your claims,
your divorces - and choose how it reaches you. None of it changes the game;
all of it changes how the game reads, which is most of why people keep a
harem in the first place.

Also here: the wish commands that are about *how* you wish rather than who
for, since they are the same kind of preference.
"""
import discord
from discord.ext import commands

import config
import utils
from views import choose_character

# key: (what it renames, the default, an example)
RENAMES = {
    "harem_name": ("what your collection is called", "harem", "collection"),
    "claim_word": ("the word for claiming somebody", "married", "recruited"),
    "divorce_word": ("the word for letting somebody go", "divorced", "released"),
    "likelist_name": ("what your likes are called", "likelist", "shortlist"),
}

MAX_RENAME = 32


def word(db, guild_id: int, user_id: int, key: str) -> str:
    """The player's word for something, or the default."""
    return db.get_player_pref(guild_id, user_id, key, RENAMES[key][1])


class Personalise(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _rename(self, ctx, key: str, value: str):
        what, default, example = RENAMES[key]
        db = self.bot.db
        if value is None:
            current = word(db, ctx.guild.id, ctx.author.id, key)
            await ctx.send(
                f"You call it **{current}** ({what}).\n"
                f"`{ctx.prefix}{ctx.invoked_with} {example}` changes it,"
                f" `{ctx.prefix}{ctx.invoked_with} reset` puts it back."
            )
            return
        cleaned = value.strip()[:MAX_RENAME]
        if cleaned.lower() in ("reset", "default", "clear"):
            db.set_player_pref(ctx.guild.id, ctx.author.id, key, "")
            await ctx.send(f"Back to **{default}**.")
            return
        if not cleaned:
            await ctx.send("Give me a word to use.")
            return
        db.set_player_pref(ctx.guild.id, ctx.author.id, key, cleaned)
        await ctx.send(f"It is your **{cleaned}** from now on.")

    @commands.command(name="renameharem", aliases=["rh"])
    @commands.guild_only()
    async def renameharem(self, ctx, *, value: str = None):
        """Rename your collection. `$renameharem menagerie`."""
        await self._rename(ctx, "harem_name", value)

    @commands.command(name="renameclaim", aliases=["rcl"])
    @commands.guild_only()
    async def renameclaim(self, ctx, *, value: str = None):
        """Rename what claiming somebody is called."""
        await self._rename(ctx, "claim_word", value)

    @commands.command(name="renamedivorce", aliases=["rd"])
    @commands.guild_only()
    async def renamedivorce(self, ctx, *, value: str = None):
        """Rename what letting somebody go is called."""
        await self._rename(ctx, "divorce_word", value)

    @commands.command(name="renamelikelist", aliases=["rll"])
    @commands.guild_only()
    async def renamelikelist(self, ctx, *, value: str = None):
        """Rename your likelist."""
        await self._rename(ctx, "likelist_name", value)

    @commands.command(name="renames", aliases=["mywords"])
    @commands.guild_only()
    async def renames(self, ctx):
        """Every word you have changed."""
        db = self.bot.db
        lines = []
        for key, (what, default, _example) in RENAMES.items():
            chosen = word(db, ctx.guild.id, ctx.author.id, key)
            mark = "" if chosen == default else "  *(yours)*"
            lines.append(f"**{chosen}**{mark}\n　{what}")
        await ctx.send(
            embed=discord.Embed(
                title="Your words",
                description="\n".join(lines),
                colour=db.get_pref(ctx.guild.id, "cardcolour",
                                   config.CARD_COLOUR),
            )
        )

    # ------------------------------------------------------------- wishes

    @commands.command(name="wishdm", aliases=["wishprivate"])
    @commands.guild_only()
    async def wishdm(self, ctx):
        """Get wish pings by DM instead of in the channel."""
        db = self.bot.db
        now = db.get_player_pref(ctx.guild.id, ctx.author.id, "wish_dm")
        db.set_player_pref(ctx.guild.id, ctx.author.id, "wish_dm",
                           "" if now else "1")
        await ctx.send(
            "Wish pings will stay in the channel."
            if now else
            "Wish pings will come by DM. If your DMs are shut the channel"
            " ping still happens, so you cannot miss one this way."
        )

    @commands.command(name="wishsort", aliases=["ws2"])
    @commands.guild_only()
    async def wishsort(self, ctx, order: str = None):
        """Sort your wishlist: `name`, `value` or `added`."""
        db = self.bot.db
        allowed = ("name", "value", "added")
        if order not in allowed:
            current = db.get_player_pref(ctx.guild.id, ctx.author.id,
                                         "wish_sort", "added")
            await ctx.send(
                f"Your wishlist sorts by **{current}**. Pick one of: "
                + ", ".join(f"`{o}`" for o in allowed)
            )
            return
        db.set_player_pref(ctx.guild.id, ctx.author.id, "wish_sort", order)
        await ctx.send(f"Your wishlist sorts by **{order}**.")

    @commands.command(name="starwish", aliases=["star", "sw", "firstwish"])
    @commands.guild_only()
    async def starwish(self, ctx, *, name: str = None):
        """The one wish you care about most.

        A starred wish is listed first and called out when they roll. It does
        not change the odds - nothing here quietly sells you a better chance.
        """
        db = self.bot.db
        gid = ctx.guild.id
        starred = db.get_player_pref(gid, ctx.author.id, "star_wish")

        if name is None:
            if not starred:
                await ctx.send(
                    f"You have not starred a wish. `{ctx.prefix}starwish"
                    f" <name>` does it."
                )
                return
            character = db.get_character(int(starred))
            if not character:
                await ctx.send("Your starred wish is no longer in the pool.")
                return
            embed, art = utils.character_card(db, gid, character,
                                              footer="Your starred wish")
            await ctx.send(embed=embed, **art)
            return

        if name.strip().lower() in ("reset", "clear", "none"):
            db.set_player_pref(gid, ctx.author.id, "star_wish", "")
            await ctx.send("Star removed.")
            return

        wished = {row["id"] for row in db.wishes_of(gid, ctx.author.id)}
        rows = [r for r in db.find_by_name_or_alias(gid, ctx.author.id, name)
                if r["id"] in wished]
        if not rows:
            await ctx.send(
                f"`{name}` is not on your wishlist — `{ctx.prefix}wish"
                f" {name}` first."
            )
            return
        character = await choose_character(ctx, rows, "Which one?",
                                           config.CARD_COLOUR)
        if not character:
            return
        db.set_player_pref(gid, ctx.author.id, "star_wish",
                           str(character["id"]))
        await ctx.send(f"⭐ **{character['name']}** is your starred wish.")

    @commands.command(name="wishprotect", aliases=["wp"])
    @commands.guild_only()
    async def wishprotect(self, ctx):
        """How long a wish holds a roll for you."""
        db = self.bot.db
        seconds = db.get_setting(ctx.guild.id, "wish_protect_seconds")
        limit = db.get_setting(ctx.guild.id, "wish_limit")
        extra = db.get_player(ctx.guild.id, ctx.author.id)["extra_wish_slots"]
        used = len(db.wishes_of(ctx.guild.id, ctx.author.id))
        await ctx.send(
            embed=discord.Embed(
                title="⭐  Wishes",
                description=(
                    f"When somebody you wished for rolls, you are pinged and"
                    f" nobody else may claim them for **{seconds}s**.\n\n"
                    f"You are using **{used}** of **{limit + extra}** slots"
                    f"{f' ({extra} earned)' if extra else ''}."
                ),
                colour=db.get_pref(ctx.guild.id, "cardcolour",
                                   config.CARD_COLOUR),
            )
        )


async def setup(bot):
    await bot.add_cog(Personalise(bot))
