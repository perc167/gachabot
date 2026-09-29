"""Harem browsing, character lookup, divorces, notes, leaderboards."""
import discord
from discord.ext import commands

import config
import perks
import utils
from cogs.personalise import word
from views import CharacterPicker, Paginator, choose_character

ORDERS = ("likes", "name", "recent", "karuda")



def harem_colour(db, guild_id: int, user_id: int):
    """The colour someone chose for their harem with $haremcolor, if the
    tower's perk 12 is theirs; otherwise None."""
    colour = db.get_player_pref(guild_id, user_id, "harem_colour")
    if colour and perks.effective(db, guild_id, user_id)["harem_colour"]:
        try:
            return int(colour)
        except (TypeError, ValueError):
            return None
    return None

class NoteModal(discord.ui.Modal, title="Note"):
    text = discord.ui.TextInput(
        label="Your note",
        placeholder="best girl",
        required=False,
        max_length=200,
        style=discord.TextStyle.short,
    )

    def __init__(self, db, guild_id, user_id, character):
        super().__init__()
        self.db = db
        self.guild_id = guild_id
        self.user_id = user_id
        self.character = character

    async def on_submit(self, interaction: discord.Interaction):
        note = str(self.text) or None
        if self.db.set_note(
            self.guild_id, self.character["id"], self.user_id, note
        ):
            wording = f"Note on **{self.character['name']}**: _{note}_" if note \
                else f"Note cleared on **{self.character['name']}**."
            await interaction.response.send_message(wording)
        else:
            await interaction.response.send_message(
                f"You no longer own **{self.character['name']}**.", ephemeral=True
            )


class NoteButton(discord.ui.View):
    """One button, whose only job is to give the modal an interaction."""

    def __init__(self, db, guild_id, user_id, character, timeout: float = 120):
        super().__init__(timeout=timeout)
        self.db = db
        self.guild_id = guild_id
        self.user_id = user_id
        self.character = character

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Write the note", style=discord.ButtonStyle.primary)
    async def write(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(
            NoteModal(self.db, self.guild_id, self.user_id, self.character)
        )
        self.stop()


class Harem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _harem_rows(self, ctx, member, order):
        """Shared by every harem view: the rows, the rate and the totals."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.harem(gid, member.id, order if order in ORDERS else "likes")
        rate = db.get_setting(gid, "karuda_rate")
        return rows, rate

    @commands.command(name="harem", aliases=["mm", "hl", "marry", "mymarry",
                                             "ml", "mmi"])
    @commands.guild_only()
    async def harem(self, ctx, member: discord.Member = None, order: str = "likes"):
        """Flip through a harem, one card at a time, art and all.

        `$mm @user recent` sorts by claim time. `$haremlist` is the same
        harem as a plain list if you would rather read it all at once.
        """
        member = member or ctx.author
        if order not in ORDERS:
            order = "likes"
        rows, rate = self._harem_rows(ctx, member, order)
        if not rows:
            await ctx.send(f"{member.display_name} has not claimed anyone yet.")
            return

        db = self.bot.db
        gid = ctx.guild.id
        total_karuda = sum(utils.karuda_value(r, rate) for r in rows)

        # One card per character, so the art actually shows. A plain list of
        # names is faster to scan but the whole point of a gacha is the
        # picture, and $haremlist is one command away for anyone who
        # disagrees.
        embeds, art = [], []
        for position, row in enumerate(rows, 1):
            note = row["note"] if "note" in row.keys() else None
            called = word(db, gid, member.id, "harem_name")
            footer = (f"{position}/{len(rows)} in {member.display_name}'s {called}"
                      f" • {total_karuda:,} karuda total • by {order}")
            if note:
                footer = f"“{note}” • {footer}"
            image = db.random_image(row["id"]) or row["image_url"]
            card = utils.character_embed(db, gid, row, image_url=image,
                                         footer=footer[:2048])
            colour = harem_colour(db, gid, member.id)
            if colour is not None:
                card.colour = colour
            embeds.append(card)
            art.append(image)

        await Paginator(embeds, ctx.author.id, art=art).start(ctx)

    @commands.command(name="haremcolor", aliases=["haremcolour", "colormm", "colourmm"])
    @commands.guild_only()
    async def haremcolor(self, ctx, *, value: str = None):
        """Tower perk 12: your own colour on $harem. A colour name, a hex
        code, or `reset`."""
        from cogs.moderation import COLOURS
        db = self.bot.db
        gid, uid = ctx.guild.id, ctx.author.id
        if not perks.effective(db, gid, uid)["harem_colour"]:
            await ctx.send(f"Your own harem colour is perk **12** of the tower."
                           f" `{ctx.prefix}kt` to see it, `{ctx.prefix}build 12` to get it.")
            return
        if not value:
            current = harem_colour(db, gid, uid)
            await ctx.send(embed=discord.Embed(
                title="Harem colour",
                description=(f"Yours is `#{current:06X}`." if current is not None
                             else "You're using the server's colour.")
                + f"\n`{ctx.prefix}haremcolor pink` or `{ctx.prefix}haremcolor #FF77AA`,"
                  f" or `{ctx.prefix}haremcolor reset`.\nNames: "
                + ", ".join(f"`{name}`" for name in COLOURS),
                colour=current if current is not None else config.CARD_COLOUR))
            return
        key = value.strip().lstrip("#").lower()
        if key in ("reset", "default", "off"):
            db.set_player_pref(gid, uid, "harem_colour", "")
            await ctx.send("Your harem uses the server's colour again.")
            return
        if key in COLOURS:
            colour = COLOURS[key]
        else:
            try:
                colour = int(key, 16)
            except ValueError:
                colour = -1
        if not 0 <= colour <= 0xFFFFFF:
            await ctx.send("Give me a colour name or a hex code like `FF77AA`.")
            return
        db.set_player_pref(gid, uid, "harem_colour", str(colour))
        await ctx.send(embed=discord.Embed(description=f"Your harem is `#{colour:06X}` now.",
                                           colour=colour))

    @commands.command(name="haremlist", aliases=["mml", "mmt", "haremtext"])
    @commands.guild_only()
    async def haremlist(self, ctx, member: discord.Member = None,
                        order: str = "likes"):
        """The same harem as a plain list, eight to a page."""
        member = member or ctx.author
        if order not in ORDERS:
            order = "likes"
        rows, rate = self._harem_rows(ctx, member, order)
        if not rows:
            await ctx.send(f"{member.display_name} has not claimed anyone yet.")
            return

        total_likes = sum(r["likes"] for r in rows)
        total_karuda = sum(utils.karuda_value(r, rate) for r in rows)

        lines = []
        icon = utils.shard_icon(config.SHARD_TYPES[0][0])
        for i, row in enumerate(rows, 1):
            note = f" — _{row['note']}_" if row["note"] else ""
            lines.append(
                f"`{i:>3}.` **{row['name']}** · {row['series']}\n"
                f"       {icon} {utils.karuda_value(row, rate):,}"
                f" · #{row['like_rank']:,}{note}"
            )

        embeds = []
        pages = utils.paginate(lines, 8)
        for page_no, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{member.display_name}'s "
                      f"{word(self.bot.db, ctx.guild.id, member.id, 'harem_name')}"
                      f" — {len(rows)} characters",
                description="\n".join(page),
                colour=harem_colour(self.bot.db, ctx.guild.id, member.id)
                or self.bot.db.get_pref(ctx.guild.id, "cardcolour", config.CARD_COLOUR),
            )
            # The first character on the page, so a list still has a face on
            # it rather than being a wall of text.
            top = rows[(page_no - 1) * 8]
            if top["image_url"] and not str(top["image_url"]).startswith(
                    utils.LOCAL_ART):
                embed.set_thumbnail(url=top["image_url"])
            embed.set_footer(
                text=f"Page {page_no}/{len(pages)} • {total_likes} likes"
                f" • {total_karuda} karuda • sorted by {order}"
            )
            embeds.append(embed)

        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="info", aliases=["im", "char", "ci", "character"])
    @commands.guild_only()
    async def info(self, ctx, *, name: str):
        """Look up a character by name."""
        # A nickname counts as a name here, which is the whole point of
        # teaching the bot one.
        matches = self.bot.db.find_by_name_or_alias(
            ctx.guild.id, ctx.author.id, name)
        if not matches:
            await ctx.send(f"No character matching `{name}`.")
            return
        character = await choose_character(
            ctx, matches, "Which character?", config.CARD_COLOUR
        )
        if not character:
            return
        # One page per image, so the card flips rather than showing one
        # picture and hiding the rest behind $album.
        embeds, urls = utils.character_pages(
            self.bot.db, ctx.guild.id, character,
            footer=f"ID {character['id']}",
        )
        await Paginator(embeds, ctx.author.id, art=urls).start(ctx)

    @commands.command(name="search", aliases=["sc", "s", "commandsearch"])
    @commands.guild_only()
    async def search(self, ctx, *, query: str):
        """Search the pool by character or series name."""
        rows = self.bot.db.search_characters(query, limit=25, guild_id=ctx.guild.id)
        if not rows:
            await ctx.send(f"Nothing matches `{query}`.")
            return
        lines = []
        for row in rows:
            owner = self.bot.db.owner_of(ctx.guild.id, row["id"])
            tag = f" — <@{owner}>" if owner else ""
            lines.append(
                f"`{row['id']:>4}` **{row['name']}** · {row['series']}"
                f" · #{row['like_rank']:,}{tag}"
            )
        embed = discord.Embed(
            title=f"Results for {query}",
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        await ctx.send(embed=embed)

    @commands.command(name="divorce", aliases=["dv", "d", "userdivorce"])
    @commands.guild_only()
    async def divorce(self, ctx, *, name: str = None):
        """`$divorce` — pick from your harem, or name someone directly."""
        db = self.bot.db
        gid = ctx.guild.id

        if name:
            owned = [
                row
                for row in db.find_characters_by_name(name, guild_id=gid)
                if db.owner_of(gid, row["id"]) == ctx.author.id
            ]
            if not owned:
                await ctx.send(f"You do not own anyone matching `{name}`.")
                return
            character = await choose_character(
                ctx, owned, "Which one?", config.CARD_COLOUR
            )
        else:
            rows = db.harem(gid, ctx.author.id)
            if not rows:
                await ctx.send("You have not claimed anyone yet.")
                return
            view = CharacterPicker(rows, ctx.author.id, "Choose who to let go")
            view.message = await ctx.send(
                embed=discord.Embed(
                    title="Divorce",
                    description="This cannot be undone - they go back in the pool.",
                    colour=config.CARD_COLOUR,
                ),
                view=view,
            )
            await view.wait()
            character = view.chosen

        if not character:
            await ctx.send("Nothing divorced.")
            return
        if not db.divorce(gid, character["id"], ctx.author.id):
            await ctx.send(f"You do not own **{character['name']}**.")
            return
        percent = db.get_setting(gid, "divorce_refund_percent")
        if percent:
            rate = db.get_setting(gid, "karuda_rate")
            # value_with_keys, not karuda_value: what a divorce hands back
            # should be the number on the character's own card, and that one
            # counts the keys spent on them.
            worth = utils.value_with_keys(db, gid, character, rate)
            refund = max(1, worth * percent // 100)
            total = db.add_karuda(gid, ctx.author.id, refund)
            await ctx.send(
                f"{word(db, gid, ctx.author.id, 'divorce_word').title()}"
                f" **{character['name']}**."
                f" +{refund:,} karuda (total: {total:,})."
            )
        else:
            await ctx.send(
                f"{word(db, gid, ctx.author.id, 'divorce_word').title()}"
                f" **{character['name']}**. They are back in the pool."
            )

    @commands.command(name="note", aliases=["notenote", "n"])
    @commands.guild_only()
    async def note(self, ctx, *, args: str = None):
        """`$note` — pick a character, then write the note in a box.

        `$note <name> | <text>` still works in one line.
        """
        db = self.bot.db
        gid = ctx.guild.id

        if args and "|" in args:
            name, _, text = args.partition("|")
            character = db.find_character_by_name(name.strip())
            if not character:
                await ctx.send(f"No character matching `{name.strip()}`.")
                return
            if db.set_note(gid, character["id"], ctx.author.id, text.strip()[:200] or None):
                await ctx.send(f"Note set on **{character['name']}**.")
            else:
                await ctx.send(f"You do not own **{character['name']}**.")
            return

        rows = db.harem(gid, ctx.author.id)
        if not rows:
            await ctx.send("You have not claimed anyone to annotate.")
            return
        view = CharacterPicker(rows, ctx.author.id, "Choose who to annotate")
        view.message = await ctx.send(
            embed=discord.Embed(
                title="Note",
                description="Pick a character, then write the note.",
                colour=config.CARD_COLOUR,
            ),
            view=view,
        )
        await view.wait()
        if not view.chosen:
            return

        # The picker already used up its interaction, so the modal needs a
        # fresh one: one button, which opens the box.
        await ctx.send(
            f"Writing a note for **{view.chosen['name']}**.",
            view=NoteButton(db, gid, ctx.author.id, view.chosen),
        )

    @commands.command(name="top", aliases=["lb", "topserv", "ts"])
    @commands.guild_only()
    async def top(self, ctx):
        """Biggest harems in this server."""
        rows = self.bot.db.top_harems(ctx.guild.id, limit=10)
        if not rows:
            await ctx.send("Nobody has claimed anyone yet.")
            return
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        lines = []
        for i, row in enumerate(rows):
            prefix = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(
                f"{prefix} <@{row['user_id']}> — **{row['owned']}**"
                f" characters • {row['likes']} ♥"
            )
        embed = discord.Embed(
            title=f"Top harems in {ctx.guild.name}",
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Harem(bot))
