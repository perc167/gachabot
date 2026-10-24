"""Resets, moderation and the admin side of karuda.

Mudae has a long family of $fullreset and $selfreset commands; these are the
same idea. Every one of them says how many rows it actually removed rather
than reporting success and leaving you to go and check, and every destructive
one asks first.

The shared character pool is never touched by any of this. A server can wipe
its own claims, wishes, notes and settings, and can delete characters it
invented, but the hundred thousand characters everybody shares are not one
server's to delete.
"""
import discord
from discord.ext import commands

import config
import utils
from views import Confirm, choose_character

# Card colour presets, so nobody has to know hex to change it.
COLOURS = {
    "babyblue": 0x8CCBF5, "glacier": 0x93C2CC, "purple": 0x7C6BF0,
    "blue": 0x4EA8DE, "green": 0x43B581, "red": 0xE0525F,
    "pink": 0xEE7FA8, "orange": 0xE8894B, "yellow": 0xE5C55A, "grey": 0x99AAB5, "black": 0x23272A,
    "white": 0xFFFFFF,
}


async def confirm(ctx, question: str) -> bool:
    """Ask before doing something that cannot be undone."""
    view = Confirm([ctx.author.id])
    view.message = await ctx.send(question, view=view)
    await view.wait()
    return not view.declined_by and ctx.author.id in view.accepted


def tally(counts: dict) -> str:
    kept = [f"**{value:,}** {label}" for label, value in counts.items() if value]
    return ", ".join(kept) if kept else "nothing — it was already empty"


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------- server-wide resets

    @commands.command(name="fullreset")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullreset(self, ctx):
        """Wipe everything this server has done. Not the character pool."""
        if not await confirm(
            ctx,
            f"**Wipe everything in {ctx.guild.name}?**\nClaims, wishes, likes,"
            " notes, balances, badges, settings and any characters this server"
            " invented. The shared character pool is left alone. This cannot"
            " be undone."
        ):
            await ctx.send("Left alone.")
            return
        counts = self.bot.db.reset_guild(ctx.guild.id)
        await ctx.send(f"Wiped {tally(counts)}.")

    @commands.command(name="fullresetwishes")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetwishes(self, ctx):
        """Clear every wishlist on this server."""
        if not await confirm(ctx, "Clear **every** wishlist here?"):
            await ctx.send("Left alone.")
            return
        gone = self.bot.db.clear_wishes(ctx.guild.id)
        await ctx.send(f"Cleared **{gone:,}** wishes.")

    @commands.command(name="fullresetkeys")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetkeys(self, ctx):
        """Undo every key spent on a character here."""
        if not await confirm(ctx, "Undo **every** key spent on a character here?"):
            await ctx.send("Left alone.")
            return
        gone = self.bot.db.clear_character_keys(ctx.guild.id)
        await ctx.send(f"Undid **{gone:,}** keyed characters.")

    @commands.command(name="fullresetnotes", aliases=["fullresetnote"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetnotes(self, ctx):
        """Clear every note on this server."""
        if not await confirm(ctx, "Clear **every** note here?"):
            await ctx.send("Left alone.")
            return
        gone = self.bot.db.clear_notes_everywhere(ctx.guild.id)
        await ctx.send(f"Cleared **{gone:,}** notes.")

    @commands.command(name="fullresetnoteimg")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetnoteimg(self, ctx):
        """Unpin every picture from every note, keeping the writing."""
        gone = self.bot.db.clear_note_images(ctx.guild.id)
        await ctx.send(f"Unpinned **{gone:,}** pictures. The notes stay.")

    @commands.command(name="fullresetdisable", aliases=["antienableall"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetdisable(self, ctx):
        """Switch every disabled command back on."""
        gone = self.bot.db.clear_disabled(ctx.guild.id)
        await ctx.send(f"Switched **{gone}** commands back on.")

    @commands.command(name="fullresetchannelperms", aliases=["channelunrestrict"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetchannelperms(self, ctx):
        """Let the bot answer in every channel again."""
        gone = self.bot.db.clear_allowed_channels(ctx.guild.id)
        await ctx.send(
            f"Cleared **{gone}** channel rules — the bot answers everywhere now."
        )

    @commands.command(name="fullresetcustimg", aliases=["fullresetcustom"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetcustom(self, ctx):
        """Delete every character this server invented."""
        count = self.bot.db.custom_count(ctx.guild.id)
        if not count:
            await ctx.send("This server has not invented any characters.")
            return
        if not await confirm(
            ctx, f"Delete all **{count}** characters this server invented?"
        ):
            await ctx.send("Left alone.")
            return
        gone = self.bot.db.clear_custom_characters(ctx.guild.id)
        await ctx.send(f"Deleted **{gone}** custom characters.")

    @commands.command(name="fullresettoggles", aliases=["fullresetembedcolor"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def fullresetprefs(self, ctx):
        """Put the switches and the card colour back to their defaults."""
        self.bot.db.clear_toggles(ctx.guild.id)
        self.bot.db.clear_prefs(ctx.guild.id)
        await ctx.send("Switches and colours are back to their defaults.")

    # -------------------------------------------------------- self resets

    @commands.command(name="selfreset")
    @commands.guild_only()
    async def selfreset(self, ctx):
        """Wipe your own everything on this server."""
        if not await confirm(
            ctx,
            "**Wipe your own data here?** Your characters, wishes, likes,"
            " notes, shards, badges and balance. This cannot be undone."
        ):
            await ctx.send("Left alone.")
            return
        counts = self.bot.db.reset_player(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Wiped {tally(counts)}.")

    @commands.command(name="selfresetwishes")
    @commands.guild_only()
    async def selfresetwishes(self, ctx):
        """Clear your own wishlist."""
        gone = self.bot.db.clear_wishes(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Cleared **{gone}** of your wishes.")

    @commands.command(name="selfresetlikes")
    @commands.guild_only()
    async def selfresetlikes(self, ctx):
        """Clear your own likes."""
        gone = self.bot.db.clear_likes(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Cleared **{gone}** of your likes.")

    @commands.command(name="selfresetnotes")
    @commands.guild_only()
    async def selfresetnotes(self, ctx):
        """Clear your own notes."""
        gone = self.bot.db.clear_notes(ctx.guild.id, ctx.author.id)
        await ctx.send(f"Cleared **{gone}** of your notes.")

    # ---------------------------------------------------- cleaning a user

    @commands.command(name="modclean", aliases=["cleanuser"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def modclean(self, ctx, member: discord.Member):
        """Wipe one player's data on this server."""
        if not await confirm(
            ctx, f"Wipe everything **{member.display_name}** has here?"
        ):
            await ctx.send("Left alone.")
            return
        counts = self.bot.db.reset_player(ctx.guild.id, member.id)
        await ctx.send(f"Wiped {tally(counts)} from {member.display_name}.")

    @commands.command(name="cleanself")
    @commands.guild_only()
    async def cleanself(self, ctx):
        """The same as $selfreset, under the name you may be used to."""
        await self.selfreset(ctx)

    @commands.command(name="forcedivorce", aliases=["moddivorce"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def forcedivorce(self, ctx, member: discord.Member, *, name: str):
        """Take one character off somebody."""
        db = self.bot.db
        gid = ctx.guild.id
        owned = [row for row in db.find_characters_by_name(name, guild_id=gid)
                 if db.owner_of(gid, row["id"]) == member.id]
        if not owned:
            await ctx.send(f"{member.display_name} does not own anyone called `{name}`.")
            return
        character = await choose_character(
            ctx, owned, "Which one?", config.CARD_COLOUR
        )
        if not character:
            return
        db.divorce_many(gid, member.id, [character["id"]],
                        reason="forcedivorce")
        await ctx.send(
            f"**{character['name']}** is no longer {member.display_name}'s."
        )

    @commands.command(name="wipeharems", aliases=["resetharems",
                                                  "wipeclaims"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def wipeharems(self, ctx):
        """Free every character on this server back into the pool.

        For starting a season over. Everybody keeps their karuda, badges,
        wishes and notes - this is only the claims.
        """
        db = self.bot.db
        gid = ctx.guild.id
        claims = db.claims_in(gid)
        if not claims:
            await ctx.send("Nobody on this server has claimed anyone.")
            return
        people = len({row["user_id"] for row in claims})
        view = Confirm([ctx.author.id])
        view.message = await ctx.send(
            f"**Free all {len(claims):,} claims in {ctx.guild.name}?**\n"
            f"That is every character {people:,}"
            f" {'person has' if people == 1 else 'people have'} claimed,"
            " back into the pool. Nobody is paid for them: this is a reset,"
            " not everybody divorcing at once. Karuda, badges, wishes and"
            " notes are untouched. There is no undo.",
            view=view)
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Nothing was wiped.")
            return

        by_person = {}
        for row in claims:
            by_person.setdefault(row["user_id"], []).append(row["character_id"])
        freed = 0
        for user_id, ids in by_person.items():
            freed += db.divorce_many(gid, user_id, ids, reason="wipeharems")
        await ctx.send(
            f"Freed **{freed:,}** characters from **{people:,}**"
            f" {'harem' if people == 1 else 'harems'}."
            f" `{ctx.prefix}divorcelog` has the record of it.")

    # -------------------------------------------------------- divorces

    @commands.command(name="divorcelog", aliases=["divorces", "dlog"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def divorcelog(self, ctx, member: discord.User = None,
                         days: int = 30):
        """Who let go of what, and what they were paid for it."""
        db = self.bot.db
        since = utils.now() - max(1, days) * 86400
        rows = db.divorces_by(ctx.guild.id, member.id if member else None,
                              since, limit=25)
        if not rows:
            who = f" by {member.display_name}" if member else ""
            await ctx.send(f"No divorces{who} in the last {days} days.")
            return
        lines = []
        for row in rows:
            paid = f"+{row['refunded']:,}" if row["refunded"] else "**nothing**"
            lines.append(
                f"<t:{row['at']}:R> <@{row['user_id']}> — {row['name']}"
                f" ({paid}){' · ' + row['reason'] if row['reason'] else ''}")
        embed = discord.Embed(
            title="Divorces", colour=config.CARD_COLOUR,
            description="\n".join(lines)[:4000])
        totals = db.divorce_totals(ctx.guild.id, since)
        if not member and totals:
            embed.add_field(
                name=f"In {days} days",
                value="\n".join(
                    f"<@{t['user_id']}> — {t['gone']:,} let go,"
                    f" {t['paid'] or 0:,} paid" for t in totals[:10]),
                inline=False)
        embed.set_footer(text="Paid nothing? $kakeraadm @them <amount> puts"
                              " it right.")
        await ctx.send(embed=embed,
                       allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="divorceuser", aliases=["divorceall@", "dvu"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def divorceuser(self, ctx, user: discord.User):
        """Free everything somebody owns back into the pool.

        Takes an ID as well as a mention, so it still works on somebody who
        has already left - which is the usual reason to want it.
        """
        db = self.bot.db
        gid = ctx.guild.id
        rows = db.harem(gid, user.id)
        if not rows:
            await ctx.send(f"**{user.display_name}** owns nobody here.")
            return
        here = ctx.guild.get_member(user.id)
        standing = "" if here else " They have left the server."
        view = Confirm([ctx.author.id])
        view.message = await ctx.send(
            f"Free all **{len(rows)}** of **{user.display_name}**'s"
            f" characters back into the pool?{standing}"
            " They are paid nothing: this is not their divorce.",
            view=view)
        await view.wait()
        if view.declined_by or ctx.author.id not in view.accepted:
            await ctx.send("Nobody was freed.")
            return
        gone = db.divorce_many(gid, user.id, [r["id"] for r in rows],
                               reason="divorceuser")
        await ctx.send(f"Freed **{gone}** of **{user.display_name}**'s"
                       " characters back into the pool.")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Free a leaver's harem, for the servers that want that.

        Off by default. People leave and come back, and coming back to an
        empty harem is worse than a server having to run $divorceuser.
        """
        db = self.bot.db
        if member.bot or not db.get_toggle(member.guild.id, "freeonleave", 0):
            return
        rows = db.harem(member.guild.id, member.id)
        if rows:
            db.divorce_many(member.guild.id, member.id,
                            [r["id"] for r in rows], reason="left the server")

    # ------------------------------------------------------- karuda admin

    @commands.command(name="kakeraadm", aliases=["karudaadm", "givekarudaadm"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def kakeraadm(self, ctx, member: discord.Member, amount: int):
        """Give or take karuda. A negative amount takes."""
        if not -1_000_000 <= amount <= 1_000_000:
            await ctx.send("Keep it within a million either way.")
            return
        now = self.bot.db.add_karuda(ctx.guild.id, member.id, amount)
        verb = "Gave" if amount >= 0 else "Took"
        await ctx.send(
            f"{verb} **{abs(amount):,}** {config.CURRENCY}"
            f" {'to' if amount >= 0 else 'from'} {member.display_name}."
            f" They now have **{now:,}**."
        )

    @commands.command(name="kakerareward", aliases=["karudareward"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def kakerareward(self, ctx, amount: int, *members: discord.Member):
        """Hand the same amount to several people at once."""
        if not members:
            await ctx.send("Name at least one person to reward.")
            return
        if not 0 < amount <= 1_000_000:
            await ctx.send("Pick an amount between 1 and a million.")
            return
        for member in members:
            self.bot.db.add_karuda(ctx.guild.id, member.id, amount)
        await ctx.send(
            f"Gave **{amount:,}** {config.CURRENCY} to"
            f" **{len(members)}** people."
        )

    @commands.command(name="kakeraremoveall", aliases=["karudaremoveall"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def kakeraremoveall(self, ctx):
        """Set every balance on this server back to zero."""
        if not await confirm(ctx, f"Zero **every** {config.CURRENCY} balance here?"):
            await ctx.send("Left alone.")
            return
        cur = self.bot.db.conn.execute(
            "UPDATE players SET karuda = 0 WHERE guild_id = ? AND karuda != 0",
            (ctx.guild.id,),
        )
        self.bot.db.conn.commit()
        await ctx.send(f"Zeroed **{cur.rowcount}** balances.")

    # ------------------------------------------------------------- colour

    @commands.command(name="embedcolor", aliases=["embedcolour", "color", "colour"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def embedcolor(self, ctx, value: str = None):
        """Set the colour of character cards. A name, or a hex code."""
        if not value:
            current = self.bot.db.get_pref(
                ctx.guild.id, "cardcolour", config.CARD_COLOUR)
            embed = discord.Embed(
                title="Card colour",
                description=f"Currently `#{current:06X}`.\nNames you can use:\n"
                            + ", ".join(f"`{name}`" for name in COLOURS),
                colour=current,
            )
            await ctx.send(embed=embed)
            return

        key = value.strip().lstrip("#").lower()
        if key in COLOURS:
            colour = COLOURS[key]
        else:
            try:
                colour = int(key, 16)
            except ValueError:
                await ctx.send("Give me a colour name or a hex code like `7C6BF0`.")
                return
            if not 0 <= colour <= 0xFFFFFF:
                await ctx.send("A hex colour is six digits, `000000` to `FFFFFF`.")
                return
        self.bot.db.set_pref(ctx.guild.id, "cardcolour", colour)
        await ctx.send(
            embed=discord.Embed(
                title="Card colour set",
                description=f"Cards here are now `#{colour:06X}`.",
                colour=colour,
            )
        )

    @commands.command(name="resetembedcolor", aliases=["resetcolor"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def resetembedcolor(self, ctx):
        """Put the card colour back to the default."""
        self.bot.db.set_pref(ctx.guild.id, "cardcolour", config.CARD_COLOUR)
        await ctx.send("Card colour is back to the default.")


async def setup(bot):
    await bot.add_cog(Moderation(bot))
