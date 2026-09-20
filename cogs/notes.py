"""Notes: the scribbles you keep on the characters you own.

`$note` itself lives with the harem commands, because writing one is part of
owning somebody. Everything here is what you do with notes afterwards -
listing them, searching them, clearing them, and the two commands that act on
a whole series or on whatever a note says.
"""
import discord
from discord.ext import commands

import config
import utils
from views import Confirm, Paginator, choose_character


class Notes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="notelist", aliases=["notepage", "notes", "nl"])
    @commands.guild_only()
    async def notelist(self, ctx, member: discord.Member = None):
        """Every note you have written, a page at a time."""
        member = member or ctx.author
        rows = self.bot.db.notes_of(ctx.guild.id, member.id)
        if not rows:
            who = "You have" if member == ctx.author else f"{member.display_name} has"
            await ctx.send(
                f"{who} not written any notes. `{ctx.prefix}note` starts one."
            )
            return

        pages = utils.paginate(
            [f"**{row['name']}** · {row['series']}\n　*{row['note']}*"
             for row in rows],
            per_page=8,
        )
        embeds = []
        for number, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"\U0001f4dd  {member.display_name}'s notes",
                description="\n\n".join(page),
                colour=config.CARD_COLOUR,
            )
            embed.set_footer(text=f"Page {number}/{len(pages)} · {len(rows)} notes")
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="notesearch", aliases=["findnote"])
    @commands.guild_only()
    async def notesearch(self, ctx, *, text: str):
        """Find your notes containing some text."""
        rows = self.bot.db.matching_notes(ctx.guild.id, ctx.author.id, text)
        if not rows:
            await ctx.send(f"No note of yours mentions `{text}`.")
            return
        lines = [f"**{row['name']}** · {row['series']}\n　*{row['note']}*"
                 for row in rows[:15]]
        embed = discord.Embed(
            title=f"Notes mentioning “{text}”"[:256],
            description="\n\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        if len(rows) > 15:
            embed.set_footer(text=f"…and {len(rows) - 15} more")
        await ctx.send(embed=embed)

    @commands.command(name="clearnotes", aliases=["noteremoveall"])
    @commands.guild_only()
    async def clearnotes(self, ctx):
        """Wipe every note you have written here."""
        db = self.bot.db
        rows = db.notes_of(ctx.guild.id, ctx.author.id)
        if not rows:
            await ctx.send("You have no notes to clear.")
            return

        view = Confirm([ctx.author.id])
        view.message = await ctx.send(
            f"Clear all **{len(rows)}** of your notes? The characters stay,"
            " only the writing goes.",
            view=view,
        )
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Left alone.")
            return
        gone = db.clear_notes(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Cleared **{gone}** notes.")

    @commands.command(name="noteseries", aliases=["ns"])
    @commands.guild_only()
    async def noteseries(self, ctx, *, args: str):
        """`$noteseries <series> | <text>` — note everyone you own from it."""
        if "|" not in args:
            await ctx.send(
                f"Use `{ctx.prefix}noteseries <series> | <what to write>`."
            )
            return
        series, _, text = args.partition("|")
        series, text = series.strip(), text.strip()[:200]
        db = self.bot.db
        rows = db.harem_by_series(ctx.guild.id, ctx.author.id, series)
        if not rows:
            await ctx.send(f"You do not own anyone from **{series}**.")
            return
        for row in rows:
            db.set_note(ctx.guild.id, row["id"], ctx.author.id, text or None)
        verb = "Cleared the note on" if not text else "Noted"
        await ctx.send(f"{verb} **{len(rows)}** characters from **{series}**.")

    @commands.command(name="noteimg", aliases=["noteimage"])
    @commands.guild_only()
    async def noteimg(self, ctx, *, args: str = None):
        """`$noteimg <name> | <url>` — pin a picture to your note."""
        db = self.bot.db
        gid = ctx.guild.id
        url = ""
        name = args or ""
        if args and "|" in args:
            name, _, url = args.partition("|")
            name, url = name.strip(), url.strip()

        if url and not url.startswith(("http://", "https://")):
            await ctx.send("That does not look like a link.")
            return

        rows = [row for row in db.find_characters_by_name(name, guild_id=gid)
                if db.owner_of(gid, row["id"]) == ctx.author.id] if name else []
        if not rows:
            await ctx.send(
                "Name one of your own characters —"
                f" `{ctx.prefix}noteimg <name> | <url>`."
            )
            return
        character = await choose_character(
            ctx, rows, "Which one?", config.CARD_COLOUR
        )
        if not character:
            return
        db.set_note_image(gid, character["id"], ctx.author.id, url)
        if url:
            embed = discord.Embed(
                title=character["name"],
                description=f"> {character['series']}",
                colour=config.CARD_COLOUR,
            )
            embed.set_image(url=url)
            await ctx.send("Pinned to your note.", embed=embed)
        else:
            await ctx.send(f"Took the picture off **{character['name']}**.")

    @commands.command(name="noteimglist", aliases=["noteimages"])
    @commands.guild_only()
    async def noteimglist(self, ctx):
        """Which of your notes have a picture pinned."""
        rows = [row for row in self.bot.db.notes_of(ctx.guild.id, ctx.author.id)
                if row["note_image"]]
        if not rows:
            await ctx.send(
                f"No note of yours has a picture. `{ctx.prefix}noteimg` pins one."
            )
            return
        embed = discord.Embed(
            title="\U0001f5bc️  Notes with a picture",
            description="\n".join(
                f"**{row['name']}** · [image]({row['note_image']})" for row in rows[:20]
            ),
            colour=config.CARD_COLOUR,
        )
        await ctx.send(embed=embed)

    @commands.command(name="divorcenote", aliases=["dn"])
    @commands.guild_only()
    async def divorcenote(self, ctx, *, text: str):
        """Let go of everyone whose note contains some text."""
        db = self.bot.db
        rows = db.matching_notes(ctx.guild.id, ctx.author.id, text)
        if not rows:
            await ctx.send(f"No note of yours mentions `{text}`.")
            return

        view = Confirm([ctx.author.id])
        preview = ", ".join(row["name"] for row in rows[:6])
        if len(rows) > 6:
            preview += f", and {len(rows) - 6} more"
        view.message = await ctx.send(
            f"Divorce **{len(rows)}** characters whose note mentions"
            f" `{text}`?\n{preview}",
            view=view,
        )
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Nobody was divorced.")
            return
        gone = db.divorce_many(ctx.guild.id, ctx.author.id,
                               [row["id"] for row in rows])
        await ctx.send(f"Divorced **{gone}**.")


async def setup(bot):
    await bot.add_cog(Notes(bot))
