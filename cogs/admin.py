"""Character pool management: add, edit, delete, bulk import/export.

Restricted to the bot's owner(s) — these commands change the pool for every
server the bot is in.
"""
import io
import json
import os

import discord
from discord.ext import commands

import config
import utils
from db import DuplicateCharacter

SEED_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "characters.json")
FIELDS = ("name", "series", "image_url", "likes", "base_kakera")


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
        """`$addchar Name | Series | image_url | likes | base_kakera`

        likes and base_kakera are optional (default 0 / 50).
        """
        parts = [p.strip() for p in args.split("|")]
        if len(parts) < 2:
            await ctx.send(
                f"Usage: `{ctx.prefix}addchar Name | Series | image_url"
                " | likes | base_kakera`\nEverything after Series is optional."
            )
            return
        name, series = parts[0], parts[1]
        image_url = parts[2] if len(parts) > 2 else ""
        if image_url.lower() in ("none", "-", "n/a"):
            image_url = ""
        try:
            likes = int(parts[3]) if len(parts) > 3 and parts[3] else 0
            base_kakera = int(parts[4]) if len(parts) > 4 and parts[4] else 50
        except ValueError:
            await ctx.send("likes and base_kakera must be whole numbers.")
            return
        if image_url and not image_url.startswith(("http://", "https://")):
            await ctx.send("image_url must be an http(s) link, or left out.")
            return

        char_id = self.bot.db.add_character(name, series, image_url, likes, base_kakera)
        if char_id is None:
            await ctx.send(f"**{name}** ({series}) is already in the pool.")
            return
        await ctx.send(f"Added **{name}** ({series}) as ID `{char_id}`.")

    @commands.command(name="editchar")
    @is_bot_owner()
    async def editchar(self, ctx, character_id: int, field: str, *, value: str):
        """`$editchar <id> <field> <value>` — field is one of name, series,
        image_url, likes, base_kakera."""
        field = field.lower()
        if field not in FIELDS:
            await ctx.send(f"Field must be one of: {', '.join(FIELDS)}.")
            return
        if not self.bot.db.get_character(character_id):
            await ctx.send(f"No character with ID `{character_id}`.")
            return
        if field in ("likes", "base_kakera"):
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
        # Usable in a DM, so guild-specific bits fall back to defaults.
        preview_guild = ctx.guild.id if ctx.guild else 0
        embed = utils.character_embed(
            self.bot.db, preview_guild, self.bot.db.get_character(character_id)
        )
        await ctx.send(f"Art set for **{character['name']}**.", embed=embed)

    @commands.command(name="missingart", aliases=["noart"])
    async def missingart(self, ctx, *, series: str = None):
        """Which characters still have no image. Optionally filter by series."""
        db = self.bot.db
        if series:
            rows = db.conn.execute(
                "SELECT * FROM characters WHERE image_url = ''"
                " AND series LIKE ? ORDER BY base_kakera DESC LIMIT 40",
                (f"%{series}%",),
            ).fetchall()
        else:
            rows = db.conn.execute(
                "SELECT * FROM characters WHERE image_url = ''"
                " ORDER BY base_kakera DESC LIMIT 40"
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

        added = 0
        skipped = []
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
            self.bot.db.upsert_character(
                name,
                series,
                image_url,
                int(entry.get("likes", 0)),
                int(entry.get("base_kakera", 50)),
            )
            added += 1

        message = f"Imported **{added}** characters from `{source}`."
        message += f" Pool is now {self.bot.db.character_count()}."
        if skipped:
            message += f"\nSkipped {len(skipped)}:\n" + "\n".join(skipped[:10])
        await ctx.send(message[:1900])

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
                "base_kakera": row["base_kakera"],
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
        total = db.character_count()
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
