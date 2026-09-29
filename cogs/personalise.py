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
import wishes
from views import Confirm, choose_character

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
        """A wish that rolls five times as often as a normal one, for wish
        slots: the first costs 2, the next 4, the next 6. `$starwish <name>`
        stars someone, `$starwish` shows yours, `$starwish remove <name>`
        gives the slots back."""
        db = self.bot.db
        gid, uid = ctx.guild.id, ctx.author.id
        starred = db.starwishes_of(gid, uid)

        if name is None:
            lines = [f"\u2b50 **{row['name']}** \u00b7 {row['series']}" for row in starred]
            next_cost = wishes.next_star_cost(len(starred))
            await ctx.send(embed=discord.Embed(
                title="\u2b50 Your starwishes",
                description=("\n".join(lines) if lines else "None yet.")
                + f"\n\nA starwish rolls **{wishes.STAR_WEIGHT}x** as often as a normal"
                  f" wish. Your next one costs **{next_cost}** wish slots; you have"
                  f" **{max(0, wishes.room(db, gid, uid))}** free."
                  f"\n`{ctx.prefix}starwish <name>` to add one,"
                  f" `{ctx.prefix}starwish remove <name>` to give one up.",
                colour=config.CARD_COLOUR))
            return

        words = name.strip().split(maxsplit=1)
        if words[0].lower() in ("remove", "unstar", "drop", "delete"):
            if len(words) < 2 or not starred:
                await ctx.send(f"Say who: `{ctx.prefix}starwish remove <name>`."
                               if starred else "You have no starwishes.")
                return
            query = words[1].lower()
            rows = [r for r in starred if query in r["name"].lower()]
            character = await choose_character(ctx, rows, "Which one?", config.CARD_COLOUR) \
                if rows else None
            if not character:
                await ctx.send(f"`{words[1]}` isn't one of your starwishes.")
                return
            db.remove_starwish(gid, uid, character["id"])
            await ctx.send(f"**{character['name']}** isn't a starwish any more, and"
                           f" the slots are yours again.")
            return

        matches = db.find_by_name_or_alias(gid, uid, name)
        if not matches:
            await ctx.send(f"No character matching `{name}`.")
            return
        character = await choose_character(ctx, matches, "Which one?", config.CARD_COLOUR)
        if not character:
            return
        if any(r["id"] == character["id"] for r in starred):
            await ctx.send(f"**{character['name']}** is already one of your starwishes.")
            return
        if db.owner_of(gid, character["id"]) == uid:
            await ctx.send(f"You already own **{character['name']}**.")
            return

        cost = wishes.next_star_cost(len(starred))
        was_wished = any(r["id"] == character["id"] for r in db.wishes_of(gid, uid))
        # A plain wish for them is folded in, so its slot counts towards it.
        free = wishes.room(db, gid, uid) + (1 if was_wished else 0)
        if free < cost:
            await ctx.send(
                f"A starwish costs **{cost}** wish slots right now and you have **{free}**"
                f" free. Drop some wishes with `{ctx.prefix}unwish`, or get more slots"
                f" in `{ctx.prefix}shop`.")
            return
        left = free - cost
        view = Confirm({uid})
        view.message = await ctx.send(
            f"\u2b50 Starwish **{character['name']}**? This sacrifices **{cost}** of your"
            f" wish slots" + (" (their wish is folded in)" if was_wished else "")
            + f", leaving you **{left}** free. They'll roll {wishes.STAR_WEIGHT}x as often"
              " as a normal wish.", view=view)
        await view.wait()
        if not view.accepted or view.declined_by:
            await ctx.send("No starwish. Your slots are untouched.")
            return
        db.add_starwish(gid, uid, character["id"])
        await ctx.send(f"\u2b50 **{character['name']}** is a starwish now.")

    @commands.command(name="wishprotect", aliases=["wp"])
    @commands.guild_only()
    async def wishprotect(self, ctx):
        """How long a wish holds a roll for you."""
        db = self.bot.db
        seconds = db.get_setting(ctx.guild.id, "wish_protect_seconds")
        limit = wishes.capacity(db, ctx.guild.id, ctx.author.id)
        extra = limit - db.get_setting(ctx.guild.id, "wish_limit")
        used = wishes.used(db, ctx.guild.id, ctx.author.id)
        await ctx.send(
            embed=discord.Embed(
                title="⭐  Wishes",
                description=(
                    f"When somebody you wished for rolls, you are pinged and"
                    f" nobody else may claim them for **{seconds}s**.\n\n"
                    f"You are using **{used}** of **{limit}** slots"
                    f"{f' ({extra} earned)' if extra else ''}."
                ),
                colour=db.get_pref(ctx.guild.id, "cardcolour",
                                   config.CARD_COLOUR),
            )
        )


async def setup(bot):
    await bot.add_cog(Personalise(bot))
