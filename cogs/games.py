"""Minigames.

Three of them, each doing a different job. The quiz is a faucet that rewards
knowing the roster; slots are a sink with a house edge; duels move karuda
between players without creating any.
"""
import asyncio
import random
import re
import unicodedata

import discord
from discord.ext import commands

import config
import utils
from views import Confirm

QUIZ_SECONDS = 45
# Only reasonably well-known characters, or nobody ever gets one right.
QUIZ_RANK_CEILING = 4000

SLOT_MIN_BET = 50
SLOT_MAX_BET = 10000
# Six symbols, evenly weighted. Three of a kind pays 10x, three of the last
# symbol pays 25x, two of a kind returns 1.4x. That works out at roughly a
# 7% house edge, so the table is a sink rather than a second income.
SLOT_SYMBOLS = ["dust", "verdite", "aurum", "ember", "azure", "obsidian"]
SLOT_TRIPLE = 10
SLOT_JACKPOT = 25
SLOT_PAIR = 1.4


def simplify(text: str) -> str:
    """Lowercase, strip accents and punctuation, for comparing answers."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9 ]", "", text.lower())
    # Collapse runs of spaces too, or "satoru  gojou" is marked wrong for a
    # stray keystroke.
    return re.sub(r"\s+", " ", text).strip()


def answer_matches(guess: str, name: str) -> bool:
    """Accept the full name, or any single distinctive part of it.

    'Gojou' should count for 'Satoru Gojou' - making people type the exact
    romanisation would turn a guessing game into a spelling test.
    """
    guess, target = simplify(guess), simplify(name)
    if not guess:
        return False
    if guess == target:
        return True
    parts = [p for p in target.split() if len(p) > 2]
    return guess in parts


class Games(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.running = set()  # channels with a quiz in flight

    # ------------------------------------------------------------- quiz

    @commands.command(name="quiz", aliases=["q", "guess"])
    @commands.guild_only()
    async def quiz(self, ctx):
        """Name the character in the picture. First correct answer wins."""
        if ctx.channel.id in self.running:
            await ctx.send("A quiz is already running here.")
            return

        db = self.bot.db
        gid = ctx.guild.id
        character = None
        for _ in range(40):
            candidate = db.random_character(gid, include_claimed=True)
            if (
                candidate
                and candidate["image_url"]
                and candidate["like_rank"]
                and candidate["like_rank"] <= QUIZ_RANK_CEILING
            ):
                character = candidate
                break
        if not character:
            await ctx.send("No suitable character to ask about.")
            return

        rate = db.get_setting(gid, "karuda_rate")
        # Obscurer characters pay more, since they are harder to name.
        reward = 40 + int(utils.karuda_value(character, rate) * 0.25)

        embed = discord.Embed(
            title="Who is this?",
            description=f"From **{character['series']}**\n"
                        f"Type the name. {QUIZ_SECONDS} seconds.",
            colour=config.CARD_COLOUR,
        )
        embed.set_image(url=character["image_url"])
        embed.set_footer(text=f"Worth {reward:,} karuda")
        await ctx.send(embed=embed)

        self.running.add(ctx.channel.id)
        try:
            def is_answer(message):
                return (
                    message.channel.id == ctx.channel.id
                    and not message.author.bot
                    and answer_matches(message.content, character["name"])
                )

            try:
                winner = await self.bot.wait_for(
                    "message", check=is_answer, timeout=QUIZ_SECONDS
                )
            except asyncio.TimeoutError:
                await ctx.send(
                    f"Time. It was **{character['name']}** ·"
                    f" {character['series']}."
                )
                return

            total = db.add_karuda(gid, winner.author.id, reward)
            await ctx.send(
                f"{winner.author.mention} got it — **{character['name']}**."
                f" +{reward:,} karuda (total {total:,})."
            )
        finally:
            self.running.discard(ctx.channel.id)

    # ------------------------------------------------------------ slots

    @commands.command(name="slots", aliases=["slot", "spin", "pokeslot"])
    @commands.guild_only()
    async def slots(self, ctx, bet: int = SLOT_MIN_BET):
        """Bet karuda on three reels."""
        db = self.bot.db
        gid = ctx.guild.id
        balance = db.get_player(gid, ctx.author.id)["karuda"]

        if not SLOT_MIN_BET <= bet <= SLOT_MAX_BET:
            await ctx.send(
                f"Bets run from {SLOT_MIN_BET:,} to {SLOT_MAX_BET:,}."
            )
            return
        if balance < bet:
            await ctx.send(f"You have {balance:,}, not {bet:,}.")
            return

        reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
        icons = " ".join(utils.shard_icon(key) for key in reels)

        if len(set(reels)) == 1:
            multiplier = (
                SLOT_JACKPOT if reels[0] == SLOT_SYMBOLS[-1] else SLOT_TRIPLE
            )
            verdict = f"Three {config.shard(reels[0])[1]}"
        elif len(set(reels)) == 2:
            multiplier = SLOT_PAIR
            verdict = "A pair"
        else:
            multiplier = 0
            verdict = "Nothing"

        payout = int(bet * multiplier)
        net = payout - bet
        total = db.add_karuda(gid, ctx.author.id, net)

        embed = discord.Embed(
            title=icons,
            description=f"**{verdict}**\n"
                        + (f"+{net:,} karuda" if net > 0 else
                           f"{net:,} karuda" if net else "broke even"),
            colour=config.CLAIMED_COLOUR if net > 0 else config.CARD_COLOUR,
        )
        embed.set_footer(text=f"Bet {bet:,} · balance {total:,}")
        await ctx.send(embed=embed)

    # ------------------------------------------------------------ duels

    @commands.command(name="duel", aliases=["fight", "pokeduel"])
    @commands.guild_only()
    async def duel(self, ctx, member: discord.Member, bet: int = 100):
        """Put your best character against someone else's."""
        db = self.bot.db
        gid = ctx.guild.id
        if member.bot or member.id == ctx.author.id:
            await ctx.send("Pick a different person.")
            return
        if bet < 10:
            await ctx.send("Bet at least 10.")
            return

        rate = db.get_setting(gid, "karuda_rate")
        mine = db.harem(gid, ctx.author.id, "karuda")
        theirs = db.harem(gid, member.id, "karuda")
        if not mine or not theirs:
            await ctx.send("Both of you need at least one character.")
            return
        for who, balance in ((ctx.author, db.get_player(gid, ctx.author.id)["karuda"]),
                             (member, db.get_player(gid, member.id)["karuda"])):
            if balance < bet:
                await ctx.send(f"{who.display_name} cannot cover {bet:,}.")
                return

        champion, rival = mine[0], theirs[0]
        my_power = utils.value_with_keys(db, gid, champion, rate)
        their_power = utils.value_with_keys(db, gid, rival, rate)

        view = Confirm({member.id})
        view.message = await ctx.send(
            f"{member.mention} — {ctx.author.display_name} challenges you for"
            f" **{bet:,}** karuda.\n"
            f"**{champion['name']}** ({my_power:,}) vs"
            f" **{rival['name']}** ({their_power:,})",
            view=view,
        )
        await view.wait()
        if view.declined_by or not view.accepted:
            await ctx.send("Duel declined.")
            return

        # Balances can move while the offer sits there.
        if (
            db.get_player(gid, ctx.author.id)["karuda"] < bet
            or db.get_player(gid, member.id)["karuda"] < bet
        ):
            await ctx.send("Somebody can no longer cover the bet. Duel off.")
            return

        # Value tilts the odds without deciding them, so an underdog can win.
        roll = random.uniform(0, my_power + their_power)
        challenger_wins = roll < my_power
        winner, loser = (
            (ctx.author, member) if challenger_wins else (member, ctx.author)
        )
        star = champion if challenger_wins else rival

        db.add_karuda(gid, winner.id, bet)
        db.add_karuda(gid, loser.id, -bet)
        odds = 100 * (my_power if challenger_wins else their_power) / (
            my_power + their_power
        )

        embed = discord.Embed(
            title=f"{star['name']} takes it",
            description=f"{winner.mention} wins **{bet:,}** karuda from"
                        f" {loser.mention}.",
            colour=config.CLAIMED_COLOUR,
        )
        if star["image_url"]:
            embed.set_thumbnail(url=star["image_url"])
        embed.set_footer(text=f"{odds:.0f}% favourite")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Games(bot))
