"""Keys and early-adopter status.

Nothing is gated today - every feature is free. This exists so that when
something is gated, the people who were here first can be told apart from
people who arrive afterwards, and so keys handed out now still work then.

That distinction cannot be reconstructed later, which is why first_seen is
recorded from the start rather than added when it is needed.
"""
import secrets
import time

import discord
from discord.ext import commands

import config
from cogs.admin import is_bot_owner

KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no look-alike characters


def make_key() -> str:
    blocks = ["".join(secrets.choice(KEY_ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(blocks)


class Access(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="access", aliases=["premium", "myaccess"])
    @commands.guild_only()
    async def access(self, ctx, member: discord.Member = None):
        """What you have access to, and since when."""
        member = member or ctx.author
        db = self.bot.db
        player = db.get_player(ctx.guild.id, member.id)
        founder = bool(
            player["first_seen"]
            and (
                not config.FOUNDER_CUTOFF
                or player["first_seen"] < config.FOUNDER_CUTOFF
            )
        )
        has_key = db.key_holder(member.id)

        embed = discord.Embed(
            title=f"{member.display_name}'s access", colour=config.CARD_COLOUR
        )
        embed.description = (
            "Everything is free at the moment — nothing here is switched off."
        )
        if player["first_seen"]:
            since = time.strftime("%d %b %Y", time.localtime(player["first_seen"]))
            embed.add_field(name="Playing since", value=since, inline=True)
        embed.add_field(
            name="Early player", value="yes" if founder else "no", inline=True
        )
        embed.add_field(name="Key redeemed", value="yes" if has_key else "no", inline=True)
        if founder or has_key:
            embed.set_footer(
                text="Kept for free if paid features arrive later."
            )
        await ctx.send(embed=embed)

    @commands.command(name="redeem")
    async def redeem(self, ctx, key: str):
        """Redeem a key. One use each, tied to you from then on."""
        result = self.bot.db.redeem_key(key.strip().upper(), ctx.author.id)
        if result == "ok":
            await ctx.send(
                f"{ctx.author.mention} key redeemed. It stays attached to your"
                " account."
            )
        elif result == "used":
            await ctx.send("That key has already been redeemed.")
        else:
            await ctx.send("No such key.")

    @commands.command(name="genkey")
    @is_bot_owner()
    async def genkey(self, ctx, count: int = 1, *, note: str = None):
        """Mint keys. Sent by DM so they do not sit in a channel."""
        if not 1 <= count <= 50:
            await ctx.send("Between 1 and 50 at a time.")
            return
        keys = []
        for _ in range(count):
            key = make_key()
            self.bot.db.add_key(key, note)
            keys.append(key)

        listing = "\n".join(f"`{key}`" for key in keys)
        try:
            await ctx.author.send(
                f"**{count} key(s)**"
                + (f" — {note}" if note else "")
                + f"\n{listing}"
            )
            await ctx.send(f"Sent **{count}** key(s) to your DMs.")
        except discord.Forbidden:
            # DMs closed: say so rather than posting keys where anyone can grab them.
            await ctx.send(
                f"Made **{count}** key(s), but your DMs are closed so I have not"
                " posted them. Open DMs and run it again, or read them out of"
                " the premium_keys table."
            )

    @commands.command(name="keys")
    @is_bot_owner()
    async def keys(self, ctx):
        """How many keys exist and how many are spent."""
        rows = self.bot.db.conn.execute(
            "SELECT COUNT(*) AS total,"
            " SUM(CASE WHEN redeemed_by IS NOT NULL THEN 1 ELSE 0 END) AS used"
            " FROM premium_keys"
        ).fetchone()
        total, used = rows["total"], rows["used"] or 0
        players = self.bot.db.conn.execute(
            "SELECT COUNT(*) AS c FROM players WHERE first_seen > 0"
        ).fetchone()["c"]
        guilds = self.bot.db.conn.execute(
            "SELECT COUNT(*) AS c FROM guilds"
        ).fetchone()["c"]
        embed = discord.Embed(title="Keys", colour=config.CARD_COLOUR)
        embed.add_field(name="Minted", value=f"{total}", inline=True)
        embed.add_field(name="Redeemed", value=f"{used}", inline=True)
        embed.add_field(name="Unused", value=f"{total - used}", inline=True)
        embed.add_field(
            name="Recorded so far",
            value=f"{players} players across {guilds} servers",
            inline=False,
        )
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Access(bot))
