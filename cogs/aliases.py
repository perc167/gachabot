"""Nicknames for characters, and the commands that manage their artwork.

Two separate ideas that Mudae keeps next to each other, so they live together
here.

Nicknames: nobody wants to type "Shinomiya Kaguya" when "kaguya" would do.
A server can teach the bot a nickname everyone shares, and a player can keep
private ones that only they see - a personal nickname wins over the server's,
so one person calling somebody "best girl" does not argue with anyone else.

Artwork: adding a picture to a character in the shared pool changes it for
every server at once, so those commands ask for Manage Server. The personal
equivalent is `$noteimg`, which pins a picture to your own claim and touches
nobody else.
"""
import discord
from discord.ext import commands

import config
import utils
from views import Confirm, Paginator, choose_character


class Aliases(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _pick(self, ctx, name: str):
        rows = self.bot.db.find_by_name_or_alias(
            ctx.guild.id, ctx.author.id, name)
        if not rows:
            await ctx.send(f"No character matching `{name}`.")
            return None
        return await choose_character(ctx, rows, "Which one?", config.CARD_COLOUR)

    # ---------------------------------------------------------- nicknames

    @commands.command(name="alias", aliases=["setalias"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def alias(self, ctx, *, args: str = None):
        """`$alias <character> | <nickname>` — a nickname everyone here shares."""
        if not args or "|" not in args:
            await ctx.send(
                f"Use `{ctx.prefix}alias <character> | <nickname>`."
            )
            return
        name, _, nickname = args.partition("|")
        nickname = nickname.strip()[:40]
        if not nickname:
            await ctx.send("Give me a nickname to teach it.")
            return

        character = await self._pick(ctx, name.strip())
        if not character:
            return
        if self.bot.db.add_alias(ctx.guild.id, nickname, character["id"]):
            await ctx.send(
                f"`{ctx.prefix}im {nickname}` now finds"
                f" **{character['name']}** · {character['series']}."
            )
            return
        taken = self.bot.db.resolve_alias(ctx.guild.id, nickname)
        await ctx.send(
            f"`{nickname}` is already taken"
            + (f" by **{taken['name']}**." if taken else ".")
        )

    @commands.command(name="myalias", aliases=["alias2", "personalalias"])
    @commands.guild_only()
    async def myalias(self, ctx, *, args: str = None):
        """`$myalias <character> | <nickname>` — a nickname only you see."""
        if not args or "|" not in args:
            await ctx.send(f"Use `{ctx.prefix}myalias <character> | <nickname>`.")
            return
        name, _, nickname = args.partition("|")
        nickname = nickname.strip()[:40]
        if not nickname:
            await ctx.send("Give me a nickname to teach it.")
            return

        character = await self._pick(ctx, name.strip())
        if not character:
            return
        if self.bot.db.add_alias(ctx.guild.id, nickname, character["id"],
                                 user_id=ctx.author.id):
            await ctx.send(
                f"Just for you: `{nickname}` now means **{character['name']}**."
            )
            return
        await ctx.send(f"You already use `{nickname}` for somebody.")

    @commands.command(name="alist", aliases=["aliaslist"])
    @commands.guild_only()
    async def alist(self, ctx):
        """Every nickname this server has taught the bot."""
        rows = self.bot.db.aliases_of(ctx.guild.id)
        if not rows:
            await ctx.send(
                f"No nicknames here yet. `{ctx.prefix}alias <character> |"
                f" <nickname>` teaches one."
            )
            return
        lines = [f"`{row['alias']}` → **{row['name']}** · {row['series']}"
                 for row in rows]
        pages = utils.paginate(lines, 12)
        embeds = []
        for number, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"Nicknames in {ctx.guild.name}",
                description="\n".join(page),
                colour=config.CARD_COLOUR,
            )
            embed.set_footer(text=f"Page {number}/{len(pages)} · {len(rows)} nicknames")
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)

    @commands.command(name="myalist", aliases=["a2list", "myaliaslist"])
    @commands.guild_only()
    async def myalist(self, ctx):
        """Every nickname only you can see."""
        rows = self.bot.db.aliases_of(ctx.guild.id, ctx.author.id)
        if not rows:
            await ctx.send(
                f"You have no private nicknames. `{ctx.prefix}myalias` makes one."
            )
            return
        await ctx.send(
            embed=discord.Embed(
                title="Your nicknames",
                description="\n".join(
                    f"`{row['alias']}` → **{row['name']}** · {row['series']}"
                    for row in rows[:25]
                ),
                colour=config.CARD_COLOUR,
            )
        )

    @commands.command(name="aliasdel", aliases=["adl", "delalias", "unalias"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def aliasdel(self, ctx, *, nickname: str):
        """Forget one of this server's nicknames."""
        if self.bot.db.remove_alias(ctx.guild.id, nickname):
            await ctx.send(f"Forgot `{nickname.strip().lower()}`.")
            return
        await ctx.send(f"No nickname `{nickname}` here.")

    @commands.command(name="myaliasdel", aliases=["a2l", "delmyalias"])
    @commands.guild_only()
    async def myaliasdel(self, ctx, *, nickname: str):
        """Forget one of your own nicknames."""
        if self.bot.db.remove_alias(ctx.guild.id, nickname, ctx.author.id):
            await ctx.send(f"Forgot your `{nickname.strip().lower()}`.")
            return
        await ctx.send(f"You do not use `{nickname}` for anybody.")

    @commands.command(name="resetalias", aliases=["fullresetalias"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def resetalias(self, ctx):
        """Forget every nickname on this server, private ones included."""
        view = Confirm([ctx.author.id])
        view.message = await ctx.send("Forget every nickname here?", view=view)
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Left alone.")
            return
        gone = self.bot.db.clear_aliases(ctx.guild.id)
        await ctx.send(f"Forgot **{gone}** nicknames.")

    @commands.command(name="selfresetalias", aliases=["selfresetalias2"])
    @commands.guild_only()
    async def selfresetalias(self, ctx):
        """Forget every nickname of your own."""
        gone = self.bot.db.clear_aliases(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Forgot **{gone}** of your nicknames.")

    # ------------------------------------------------------------ artwork

    @commands.command(name="imglist", aliases=["addimglist", "images2"])
    @commands.guild_only()
    async def imglist(self, ctx, *, name: str):
        """Every picture a character has, as links."""
        character = await self._pick(ctx, name)
        if not character:
            return
        urls = self.bot.db.images_for(character["id"])
        if not urls:
            await ctx.send(f"**{character['name']}** has no pictures.")
            return
        lines = []
        for index, url in enumerate(urls, 1):
            if str(url).startswith(utils.LOCAL_ART):
                lines.append(f"`{index}.` bundled — `{url}`")
            else:
                lines.append(f"`{index}.` [link]({url})")
        await ctx.send(
            embed=discord.Embed(
                title=f"{character['name']} — {len(urls)} pictures",
                description="\n".join(lines)[:4000],
                colour=config.CARD_COLOUR,
            )
        )

    @commands.command(name="imglink", aliases=["imageurl"])
    @commands.guild_only()
    async def imglink(self, ctx, *, name: str):
        """The link to a character's main picture."""
        character = await self._pick(ctx, name)
        if not character:
            return
        url = character["image_url"]
        if not url:
            await ctx.send(f"**{character['name']}** has no picture.")
        elif str(url).startswith(utils.LOCAL_ART):
            await ctx.send(
                f"**{character['name']}**'s picture ships with the bot"
                f" (`{url}`) — there is no link to give you."
            )
        else:
            await ctx.send(f"**{character['name']}**\n{url}")

    @commands.command(name="randomimg", aliases=["rimg"])
    @commands.guild_only()
    async def randomimg(self, ctx, *, name: str):
        """One of a character's pictures, picked at random."""
        character = await self._pick(ctx, name)
        if not character:
            return
        url = self.bot.db.random_image(character["id"])
        if not url:
            await ctx.send(f"**{character['name']}** has no pictures.")
            return
        embed, art = utils.character_card(
            self.bot.db, ctx.guild.id, character, image_url=url
        )
        await ctx.send(embed=embed, **art)

    @commands.command(name="addimg", aliases=["addart2"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def addimg(self, ctx, *, args: str = None):
        """`$addimg <character> | <url>` — add a picture to the shared pool.

        Manage Server, because the pool is shared: a picture added here shows
        up on every server the bot is in. `$noteimg` is the personal one.
        """
        if not args or "|" not in args:
            await ctx.send(f"Use `{ctx.prefix}addimg <character> | <url>`.")
            return
        name, _, url = args.partition("|")
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            await ctx.send("That does not look like a link.")
            return
        character = await self._pick(ctx, name.strip())
        if not character:
            return
        if not self.bot.db.add_image(character["id"], url, source="addimg"):
            await ctx.send("That picture is already on them.")
            return
        count = self.bot.db.image_count(character["id"])
        embed, art = utils.character_card(
            self.bot.db, ctx.guild.id, character, image_url=url
        )
        await ctx.send(
            f"Added — **{character['name']}** now has {count} pictures.",
            embed=embed, **art,
        )

    @commands.command(name="changeimg", aliases=["setmainimg", "c"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def changeimg(self, ctx, *, args: str = None):
        """`$changeimg <character> | <number>` — pick which picture leads.

        Mudae's `$c Rem$2` works too."""
        if args and "|" not in args and "$" in args:
            args = "|".join(args.rsplit("$", 1))
        if not args or "|" not in args:
            await ctx.send(f"Use `{ctx.prefix}changeimg <character> | <number>`.")
            return
        name, _, number = args.partition("|")
        character = await self._pick(ctx, name.strip())
        if not character:
            return
        urls = self.bot.db.images_for(character["id"])
        try:
            index = int(number.strip())
        except ValueError:
            await ctx.send(f"Give me a number from 1 to {len(urls)}.")
            return
        if not 1 <= index <= len(urls):
            await ctx.send(f"They have {len(urls)} pictures, so 1 to {len(urls)}.")
            return
        self.bot.db.update_character(character["id"], image_url=urls[index - 1])
        embed, art = utils.character_card(
            self.bot.db, ctx.guild.id, self.bot.db.get_character(character["id"])
        )
        await ctx.send(f"Picture {index} leads now.", embed=embed, **art)


async def setup(bot):
    await bot.add_cog(Aliases(bot))
