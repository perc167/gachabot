"""Soulmates and character keys.

A soulmate is one character you single out. Keys are spent to raise a
character's level, which is worth more karuda to whoever owns them.

Both attach to a character you already own, so neither is a way to get
characters — they are ways to care about the ones you have.
"""
import discord
from discord.ext import commands

import config
import perks
import utils
from views import CharacterPicker, Paginator, choose_character


class Bonds(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _pick_owned(self, ctx, prompt: str, title: str, note: str):
        """Choose from the characters the caller owns."""
        rows = self.bot.db.harem(ctx.guild.id, ctx.author.id, "karuda")
        if not rows:
            await ctx.send("You have not claimed anyone yet.")
            return None
        view = CharacterPicker(rows, ctx.author.id, prompt)
        view.message = await ctx.send(
            embed=discord.Embed(
                title=title, description=note, colour=config.CARD_COLOUR
            ),
            view=view,
        )
        await view.wait()
        return view.chosen

    # ---------------------------------------------------------- soulmates

    @commands.command(name="soulmate", aliases=["sm", "soul"])
    @commands.guild_only()
    async def soulmate(self, ctx, member: discord.Member = None):
        """Your soulmate, or somebody else's."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        character = db.soulmate_of(gid, member.id)

        if not character:
            if member == ctx.author:
                await ctx.send(
                    f"You have not named a soulmate. `{ctx.prefix}setsoulmate`"
                    " picks one from your harem."
                )
            else:
                await ctx.send(f"{member.display_name} has not named a soulmate.")
            return

        rate = db.get_setting(gid, "karuda_rate")
        embed = utils.character_embed(db, gid, character, show_owner=False)
        embed.title = f"\U0001f496  {character['name']}"
        embed.set_footer(
            text=f"{member.display_name}'s soulmate · "
                 f"{perks.describe({**perks.EMPTY, **perks.SOULMATE_PERK})}"
        )
        # Still owned? Losing them in a trade should be visible here.
        if db.owner_of(gid, character["id"]) != member.id:
            embed.add_field(
                name="⚠️",
                value="No longer in their harem — the bond is only a memory.",
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="setsoulmate", aliases=["smset", "makesoulmate"])
    @commands.guild_only()
    async def setsoulmate(self, ctx):
        """Name one of your characters as your soulmate."""
        db = self.bot.db
        gid = ctx.guild.id
        current = db.soulmate_of(gid, ctx.author.id)
        note = "Pick one of yours. You can change it whenever you like."
        if current:
            note = f"Currently **{current['name']}**. Picking again replaces them."

        chosen = await self._pick_owned(
            ctx, "Choose your soulmate", "\U0001f496  Soulmate", note
        )
        if not chosen:
            return
        db.set_soulmate(gid, ctx.author.id, chosen["id"])
        await ctx.send(
            f"{ctx.author.mention} — **{chosen['name']}** · {chosen['series']}"
            f" is your soulmate. \U0001f496"
            f"\n_{perks.describe({**perks.EMPTY, **perks.SOULMATE_PERK})}_"
        )

    @commands.command(name="unsoulmate", aliases=["clearsoulmate"])
    @commands.guild_only()
    async def unsoulmate(self, ctx):
        """Let the bond go."""
        db = self.bot.db
        current = db.soulmate_of(ctx.guild.id, ctx.author.id)
        if not current:
            await ctx.send("You have not named a soulmate.")
            return
        db.set_soulmate(ctx.guild.id, ctx.author.id, 0)
        await ctx.send(f"**{current['name']}** is no longer your soulmate.")

    @commands.command(name="soulmates", aliases=["smlist"])
    @commands.guild_only()
    async def soulmates(self, ctx):
        """Who everyone here has chosen."""
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.conn.execute(
            "SELECT user_id, soulmate_id FROM players"
            " WHERE guild_id = ? AND soulmate_id != 0",
            (gid,),
        ).fetchall()
        if not rows:
            await ctx.send(
                f"Nobody has named a soulmate yet. `{ctx.prefix}setsoulmate`"
                " is how."
            )
            return
        lines = []
        for row in rows[:25]:
            character = db.get_character(row["soulmate_id"])
            if character:
                lines.append(
                    f"<@{row['user_id']}> \U0001f496 **{character['name']}**"
                    f" · {character['series']}"
                )
        await ctx.send(
            embed=discord.Embed(
                title=f"Soulmates in {ctx.guild.name}",
                description="\n".join(lines),
                colour=config.CARD_COLOUR,
            )
        )

    # --------------------------------------------------------------- keys

    @commands.command(name="keys", aliases=["mykeys"])
    @commands.guild_only()
    async def keys(self, ctx, member: discord.Member = None):
        """Keys you hold, and the characters you have spent them on."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        held = db.get_player(gid, member.id)["keys"]
        keyed = db.keyed_characters(gid, member.id)
        rate = db.get_setting(gid, "karuda_rate")

        embed = discord.Embed(
            title=f"\U0001f511  {member.display_name}",
            description=f"Holding **{held}** key(s).\n"
                        f"Climb a tower floor to earn one — `{ctx.prefix}kt`.",
            colour=config.CARD_COLOUR,
        )
        if keyed:
            lines = [
                f"**{row['name']}** · {row['series']}\n"
                f"　\U0001f511 ×{row['level']} · worth"
                f" {utils.value_with_keys(db, gid, row, rate):,}"
                for row in keyed[:10]
            ]
            embed.add_field(
                name=f"Keyed characters ({len(keyed)})",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.set_footer(
                text=f"Spend one with {ctx.prefix}key — each level is"
                     f" +{perks.KEY_STEP_PERCENT}% value, up to {perks.MAX_KEY_LEVEL}"
            )
        await ctx.send(embed=embed)

    @commands.command(name="key", aliases=["usekey", "keyup"])
    @commands.guild_only()
    async def key(self, ctx, *, name: str = None):
        """Spend a key on one of your characters, raising their value."""
        db = self.bot.db
        gid = ctx.guild.id
        held = db.get_player(gid, ctx.author.id)["keys"]
        if held <= 0:
            await ctx.send(
                "You have no keys. One comes with every tower floor —"
                f" `{ctx.prefix}ktup`."
            )
            return

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
            character = await self._pick_owned(
                ctx,
                "Choose who to key",
                "\U0001f511  Spend a key",
                f"You hold **{held}**. Each level is"
                f" +{perks.KEY_STEP_PERCENT}% value, up to"
                f" {perks.MAX_KEY_LEVEL}.",
            )
        if not character:
            return

        level = db.key_level(gid, character["id"])
        if level >= perks.MAX_KEY_LEVEL:
            await ctx.send(
                f"**{character['name']}** is already at the top key level"
                f" ({perks.MAX_KEY_LEVEL})."
            )
            return

        rate = db.get_setting(gid, "karuda_rate")
        before = utils.value_with_keys(db, gid, character, rate)
        db.add_keys(gid, ctx.author.id, -1)
        new_level = db.raise_key_level(gid, character["id"])
        after = utils.value_with_keys(db, gid, character, rate)

        embed = utils.character_embed(db, gid, character, show_owner=False)
        embed.title = f"\U0001f511  {character['name']}"
        embed.add_field(
            name="Key level",
            value=f"{new_level}/{perks.MAX_KEY_LEVEL}  "
                  f"{perks.bar(new_level, perks.MAX_KEY_LEVEL, width=5)}",
            inline=True,
        )
        embed.add_field(
            name="Worth", value=f"{before:,} → **{after:,}**", inline=True
        )
        embed.set_footer(
            text=f"{db.get_player(gid, ctx.author.id)['keys']} key(s) left"
        )
        await ctx.send(embed=embed)

    @commands.command(name="keyed", aliases=["keylist"])
    @commands.guild_only()
    async def keyed(self, ctx, member: discord.Member = None):
        """Every character someone has spent keys on."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.keyed_characters(gid, member.id)
        if not rows:
            await ctx.send(f"{member.display_name} has not keyed anyone.")
            return
        rate = db.get_setting(gid, "karuda_rate")
        lines = [
            f"\U0001f511 ×{row['level']}  **{row['name']}** · {row['series']}"
            f" · {utils.value_with_keys(db, gid, row, rate):,}"
            for row in rows
        ]
        pages = utils.paginate(lines, 10)
        embeds = []
        for number, page in enumerate(pages, 1):
            embed = discord.Embed(
                title=f"{member.display_name}'s keyed characters",
                description="\n".join(page),
                colour=config.CARD_COLOUR,
            )
            embed.set_footer(text=f"Page {number}/{len(pages)} · {len(rows)} keyed")
            embeds.append(embed)
        await Paginator(embeds, ctx.author.id).start(ctx)


async def setup(bot):
    await bot.add_cog(Bonds(bot))
