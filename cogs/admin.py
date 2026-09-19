"""Character pool management: add, edit, delete, bulk import/export.

Restricted to the bot's owner(s) — these commands change the pool for every
server the bot is in.
"""
import asyncio
import io
import json
import os
import time

import discord
from discord.ext import commands

import anilist
import config
import utils
from db import DuplicateCharacter
from views import Paginator

SEED_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "characters.json")
FIELDS = ("name", "series", "image_url", "likes", "base_karuda")


def is_bot_owner():
    async def predicate(ctx):
        if ctx.author.id in config.OWNERS:
            return True
        if await ctx.bot.is_owner(ctx.author):
            return True
        raise commands.NotOwner()

    return commands.check(predicate)


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="addchar")
    @is_bot_owner()
    async def addchar(self, ctx, *, args: str):
        """`$addchar Name | Series | image_url | likes | base_karuda`

        likes and base_karuda are optional (default 0 / 50).
        """
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 2:
            await ctx.send(
                f"Usage: `{ctx.prefix}addchar Name | Series | image_url"
                " | likes | base_karuda`\nEverything after Series is optional."
            )
            return
        name, series = parts[0], parts[1]
        image_url = parts[2] if len(parts) > 2 else ""
        if image_url.lower() in ("none", "-", "n/a"):
            image_url = ""
        try:
            likes = int(parts[3]) if len(parts) > 3 and parts[3] else 0
            base_karuda = int(parts[4]) if len(parts) > 4 and parts[4] else 50
        except ValueError:
            await ctx.send("likes and base_karuda must be whole numbers.")
            return
        if image_url and not image_url.startswith(("http://", "https://")):
            await ctx.send("image_url must be an http(s) link, or left out.")
            return

        char_id = self.bot.db.add_character(name, series, image_url, likes, base_karuda)
        if char_id is None:
            await ctx.send(f"**{name}** ({series}) is already in the pool.")
            return
        await ctx.send(f"Added **{name}** ({series}) as ID `{char_id}`.")

    @commands.command(name="editchar")
    @is_bot_owner()
    async def editchar(self, ctx, character_id: int, field: str, *, value: str):
        """`$editchar <id> <field> <value>` — field is one of name, series,
        image_url, likes, base_karuda."""
        field = field.lower()
        if field not in FIELDS:
            await ctx.send(f"Field must be one of: {', '.join(FIELDS)}.")
            return
        if not self.bot.db.get_character(character_id):
            await ctx.send(f"No character with ID `{character_id}`.")
            return
        if field in ("likes", "base_karuda"):
            try:
                value = int(value)
            except ValueError:
                await ctx.send(f"{field} must be a whole number.")
                return
        try:
            self.bot.db.update_character(character_id, **{field: value})
        except DuplicateCharacter:
            current = self.bot.db.get_character(character_id)
            name = value if field == "name" else current["name"]
            series = value if field == "series" else current["series"]
            await ctx.send(
                f"**{name}** already exists in **{series}**. A name can only"
                " appear once per series — rename the other entry, or use"
                f" `{ctx.prefix}delchar` if it is a duplicate."
            )
            return
        await ctx.send(f"Updated `{character_id}`: {field} = {value}")

    @commands.command(name="setimage", aliases=["setart", "img"])
    @is_bot_owner()
    async def setimage(self, ctx, character_id: int, url: str = None):
        """`$setimage <id> <url>` — attach art to a character.

        You can also attach an image file to the message instead of a URL,
        though Discord's own attachment links expire, so a permanent host is
        better for anything you want to keep.
        """
        character = self.bot.db.get_character(character_id)
        if not character:
            await ctx.send(f"No character with ID `{character_id}`.")
            return

        if url is None and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        if not url:
            await ctx.send(
                f"Give me a link: `{ctx.prefix}setimage {character_id} https://...`"
            )
            return
        if not url.startswith(("http://", "https://")):
            await ctx.send("That is not an http(s) link.")
            return

        self.bot.db.update_character(character_id, image_url=url)
        self.bot.db.add_image(character_id, url, source="setimage")
        # Usable in a DM, so guild-specific bits fall back to defaults.
        preview_guild = ctx.guild.id if ctx.guild else 0
        embed = utils.character_embed(
            self.bot.db, preview_guild, self.bot.db.get_character(character_id)
        )
        await ctx.send(f"Art set for **{character['name']}**.", embed=embed)

    @commands.command(name="addimage", aliases=["addart", "ai"])
    @is_bot_owner()
    async def addimage(self, ctx, character_id: int, *urls: str):
        """`$addimage <id> <url> [url ...]` — add images to a character's album.

        Rolls pick one at random from the album, so the same character can
        show up with different art each time. Attachments work too.
        """
        character = self.bot.db.get_character(character_id)
        if not character:
            await ctx.send(f"No character with ID `{character_id}`.")
            return

        candidates = list(urls) + [a.url for a in ctx.message.attachments]
        good = [u for u in candidates if u.startswith(("http://", "https://"))]
        rejected = len(candidates) - len(good)
        if not good:
            await ctx.send(
                f"Give me one or more http(s) links:"
                f" `{ctx.prefix}addimage {character_id} https://... https://...`"
            )
            return

        added = self.bot.db.add_images(character_id, good)
        total = self.bot.db.image_count(character_id)
        note = f" ({len(good) - added} already in the album)" if added < len(good) else ""
        if rejected:
            note += f" ({rejected} ignored, not http links)"
        await ctx.send(
            f"Added **{added}** image(s) to **{character['name']}**{note}."
            f" Album is now {total}."
        )

    @commands.command(name="album", aliases=["images", "mu"])
    async def album(self, ctx, *, name: str):
        """Flip through every image a character has."""
        character = self.bot.db.find_character_by_name(name)
        if not character:
            await ctx.send(f"No character matching `{name}`.")
            return
        urls = self.bot.db.images_for(character["id"])
        if not urls:
            await ctx.send(
                f"**{character['name']}** has no images yet."
                f" Add some with `{ctx.prefix}addimage {character['id']} <url>`."
            )
            return

        guild_id = ctx.guild.id if ctx.guild else 0
        embeds = []
        for index, url in enumerate(urls, 1):
            embed = utils.character_embed(
                ctx.bot.db, guild_id, character, image_url=url,
                footer=f"Image {index} of {len(urls)} • ID {character['id']}",
            )
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="delimage", aliases=["rmimage"])
    @is_bot_owner()
    async def delimage(self, ctx, character_id: int, number: int):
        """`$delimage <id> <n>` — drop image n, as numbered by `$album`."""
        character = self.bot.db.get_character(character_id)
        if not character:
            await ctx.send(f"No character with ID `{character_id}`.")
            return
        urls = self.bot.db.images_for(character_id)
        if not 1 <= number <= len(urls):
            await ctx.send(
                f"**{character['name']}** has {len(urls)} image(s);"
                f" pick a number between 1 and {len(urls)}."
            )
            return
        self.bot.db.remove_image(character_id, urls[number - 1])
        await ctx.send(
            f"Removed image {number} from **{character['name']}**."
            f" {self.bot.db.image_count(character_id)} left."
        )

    @commands.command(name="missingart", aliases=["noart"])
    async def missingart(self, ctx, *, series: str = None):
        """Which characters still have no image. Optionally filter by series."""
        db = self.bot.db
        if series:
            rows = db.conn.execute(
                "SELECT * FROM characters WHERE image_url = ''"
                " AND series LIKE ? ORDER BY base_karuda DESC LIMIT 40",
                (f"%{series}%",),
            ).fetchall()
        else:
            rows = db.conn.execute(
                "SELECT * FROM characters WHERE image_url = ''"
                " ORDER BY base_karuda DESC LIMIT 40"
            ).fetchall()

        total = db.conn.execute(
            "SELECT COUNT(*) AS c FROM characters WHERE image_url = ''"
        ).fetchone()["c"]
        if not total:
            await ctx.send("Every character has art. Nice.")
            return
        if not rows:
            await ctx.send(f"No characters without art match `{series}`.")
            return

        lines = [
            f"`{r['id']:>4}` **{r['name']}** • {r['series']}" for r in rows
        ]
        embed = discord.Embed(
            title=f"{total} characters still need art",
            description="\n".join(lines),
            colour=0x8D99AE,
        )
        embed.set_footer(
            text=f"Showing {len(rows)}. Add one with {ctx.prefix}setimage <id> <url>"
        )
        await ctx.send(embed=embed)

    @commands.command(name="delchar")
    @is_bot_owner()
    async def delchar(self, ctx, character_id: int):
        """Remove a character, and any marriages or wishes pointing at it."""
        character = self.bot.db.get_character(character_id)
        if not character:
            await ctx.send(f"No character with ID `{character_id}`.")
            return
        self.bot.db.delete_character(character_id)
        await ctx.send(f"Deleted **{character['name']}** ({character['series']}).")

    @commands.command(name="import")
    @is_bot_owner()
    async def import_(self, ctx, path: str = None):
        """Bulk load characters from JSON.

        Attach a .json file, or pass a path. Defaults to data/characters.json.
        Existing entries (matched on name + series) are updated, not duplicated.
        """
        try:
            if ctx.message.attachments:
                raw = await ctx.message.attachments[0].read()
                payload = json.loads(raw.decode("utf-8"))
                source = ctx.message.attachments[0].filename
            else:
                source = path or SEED_PATH
                with open(source, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
        except FileNotFoundError:
            await ctx.send(f"No file at `{path or SEED_PATH}`.")
            return
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            await ctx.send(f"That file is not valid JSON: {error}")
            return

        if not isinstance(payload, list):
            await ctx.send("Expected a JSON list of character objects.")
            return

        clean, skipped = [], []
        for index, entry in enumerate(payload):
            try:
                name = str(entry["name"]).strip()
                series = str(entry["series"]).strip()
                image_url = str(entry.get("image_url", "")).strip()
            except (KeyError, TypeError):
                skipped.append(f"#{index}: missing name or series")
                continue
            if not (name and series):
                skipped.append(f"#{index} ({name or 'unnamed'}): blank name or series")
                continue
            if image_url and not image_url.startswith(("http://", "https://")):
                skipped.append(f"#{index} ({name}): image_url is not an http link")
                continue

            record = {
                "name": name,
                "series": series,
                "image_url": image_url,
                "likes": int(entry.get("likes", 0) or 0),
                "base_karuda": int(entry.get("base_karuda", 50) or 50),
                "like_rank": int(entry.get("like_rank", 0) or 0),
                "claim_rank": int(entry.get("claim_rank", 0) or 0),
                "images": [
                    str(u).strip()
                    for u in (entry.get("images") or [])
                    if str(u).strip().startswith(("http://", "https://"))
                ],
            }
            clean.append(record)

        if not clean:
            await ctx.send("Nothing importable in that file.")
            return

        # A thousand characters is a lot of writes; do them in one transaction
        # off the event loop so the bot keeps responding meanwhile.
        notice = await ctx.send(f"Importing {len(clean)} characters...")
        started = time.perf_counter()
        try:
            result = await asyncio.to_thread(self.bot.db.import_characters, clean)
        except Exception as error:  # a bad file should not kill the cog
            await notice.edit(content=f"Import failed, nothing changed: {error}")
            raise
        elapsed = time.perf_counter() - started

        message = (
            f"Imported **{result['total']}** characters from `{source}`"
            f" in {elapsed:.1f}s"
            f" ({result['inserted']} new, {result['updated']} updated,"
            f" {result['images']} new images)."
            f"\nPool is now {self.bot.db.character_count()}."
        )
        if skipped:
            message += f"\nSkipped {len(skipped)}:\n" + "\n".join(skipped[:10])
        await notice.edit(content=message[:1900])

    @commands.command(name="addseries", aliases=["importseries"])
    @is_bot_owner()
    async def addseries(self, ctx, *, search: str):
        """Pull one series in from AniList, however niche.

        The bulk roster stops at the popular end, so anything further down
        never arrives on its own. This fetches a named series and slots its
        cast in at the rank their favourites earn them.
        """
        notice = await ctx.send(f"Looking up **{search}** on AniList...")
        try:
            title, cast = await asyncio.to_thread(anilist.find_series, search)
        except anilist.AniListError as error:
            await notice.edit(content=f"AniList did not answer: {error}")
            return
        if not cast:
            await notice.edit(content=f"Nothing usable found for `{search}`.")
            return

        db = self.bot.db
        before = db.character_count()
        records, already = [], 0
        for entry in cast:
            matches = db.find_characters_by_name(entry["name"])
            if any(row["series"] == title for row in matches):
                already += 1
                continue
            rank, pool = db.rank_for_favourites(entry["favourites"])
            record = dict(entry)
            record["like_rank"] = rank
            record["claim_rank"] = rank
            record["base_karuda"] = utils.value_for_rank(rank, pool)
            records.append(record)

        if not records:
            await notice.edit(
                content=f"**{title}** is already in the pool ({already} characters)."
            )
            return

        result = await asyncio.to_thread(db.import_characters, records)
        lines = [
            f"**{row['name']}** · #{row['like_rank']:,} · {row['base_karuda']:,}"
            for row in sorted(records, key=lambda r: r["like_rank"])[:12]
        ]
        embed = discord.Embed(
            title=title, description="\n".join(lines), colour=config.CARD_COLOUR
        )
        embed.set_footer(
            text=f"Added {result['inserted']} · pool {before:,} to"
                 f" {db.character_count():,}"
                 + (f" · {already} already in" if already else "")
        )
        await notice.edit(content=None, embed=embed)

    @commands.command(name="export")
    @is_bot_owner()
    async def export(self, ctx):
        """Dump the whole pool back out as JSON."""
        rows = self.bot.db.search_characters("", limit=100000)
        payload = [
            {
                "name": row["name"],
                "series": row["series"],
                "image_url": row["image_url"],
                "likes": row["likes"],
                "base_karuda": row["base_karuda"],
                "like_rank": row["like_rank"],
                "claim_rank": row["claim_rank"],
                "images": self.bot.db.images_for(row["id"]),
            }
            for row in rows
        ]
        buffer = io.BytesIO(json.dumps(payload, indent=2).encode("utf-8"))
        await ctx.send(
            f"{len(payload)} characters.",
            file=discord.File(buffer, filename="characters.json"),
        )

    @commands.command(name="pool")
    @commands.guild_only()
    async def pool(self, ctx):
        """Pool size and the most popular characters."""
        db = self.bot.db
        total = db.character_count(ctx.guild.id)
        top = db.conn.execute(
            "SELECT name, series, likes FROM characters ORDER BY likes DESC LIMIT 5"
        ).fetchall()
        claimed = db.conn.execute(
            "SELECT COUNT(*) AS c FROM marriages WHERE guild_id = ?", (ctx.guild.id,)
        ).fetchone()["c"]

        embed = discord.Embed(title="Character pool", colour=0x8D99AE)
        embed.add_field(name="Total", value=str(total), inline=True)
        embed.add_field(name="Claimed here", value=str(claimed), inline=True)
        if top:
            embed.add_field(
                name="Most liked",
                value="\n".join(
                    f"**{r['name']}** • {r['series']} • {r['likes']} ♥"
                    for r in top
                ),
                inline=False,
            )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Admin(bot))
