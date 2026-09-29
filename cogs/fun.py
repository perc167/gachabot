"""The toy box: Mudae's text generators and nonsense commands.

None of this touches the game. It exists because Mudae has it and because a
server that only ever rolls gets dull - these are the commands people use
while they wait for a cooldown.

Everything here is self-contained and cheap: no database, no network, no
state. The word lists are deliberately short and clean.
"""
import random

import discord
from discord.ext import commands

import config

ADJECTIVES = [
    "absurd", "ancient", "anxious", "bashful", "blessed", "brittle", "candid",
    "chaotic", "cheerful", "clumsy", "cosmic", "cranky", "crooked", "cursed",
    "dapper", "dizzy", "doomed", "dubious", "eager", "eerie", "elegant",
    "feral", "fluffy", "forbidden", "frantic", "gentle", "gilded", "gloomy",
    "haunted", "humble", "immortal", "jolly", "lonely", "luminous", "mighty",
    "moody", "nervous", "noble", "obvious", "peculiar", "polite", "radiant",
    "reckless", "restless", "rusty", "savage", "serene", "silly", "sleepy",
    "sly", "solemn", "spiky", "stubborn", "sublime", "sunken", "tragic",
    "unhinged", "velvet", "weary", "wicked", "wistful", "zealous",
]

NOUNS = [
    "anchor", "avalanche", "bakery", "banquet", "beacon", "blizzard", "bridge",
    "cathedral", "cavern", "chandelier", "cipher", "comet", "compass",
    "cottage", "crown", "dagger", "daydream", "delta", "dragon", "echo",
    "ember", "engine", "fortress", "fountain", "gallery", "glacier", "harbour",
    "harvest", "hollow", "horizon", "hurricane", "jigsaw", "kettle", "lantern",
    "library", "lighthouse", "meadow", "mirror", "monsoon", "mountain",
    "orchard", "paradox", "pendulum", "phantom", "piano", "prism", "quarry",
    "railway", "riddle", "rooftop", "sapphire", "shipwreck", "signal",
    "staircase", "statue", "tempest", "thicket", "thunder", "tunnel", "vault",
    "violin", "whirlpool", "window", "zephyr",
]

VERBS = [
    "abandons", "admires", "ambushes", "balances", "befriends", "bargains with",
    "besieges", "borrows", "buries", "carries", "challenges", "collects",
    "conjures", "deciphers", "defends", "devours", "dismantles", "dreams of",
    "escapes", "examines", "forgets", "forgives", "gathers", "guards",
    "haunts", "hoards", "ignores", "inherits", "interrupts", "invents",
    "juggles", "mourns", "negotiates with", "outruns", "paints", "polishes",
    "questions", "rescues", "rewrites", "salutes", "scatters", "sells",
    "sharpens", "shelters", "steals", "studies", "summons", "swallows",
    "tames", "translates", "unearths", "unravels", "wagers", "weaves",
]

ADVERBS = [
    "absently", "abruptly", "bitterly", "bravely", "briskly", "carefully",
    "cheerfully", "clumsily", "coldly", "curiously", "daintily", "desperately",
    "eagerly", "fondly", "furiously", "gently", "gracefully", "grimly",
    "hastily", "hopefully", "instantly", "lazily", "loudly", "patiently",
    "politely", "quietly", "rudely", "sadly", "secretly", "sharply", "slowly",
    "softly", "solemnly", "stubbornly", "suddenly", "sweetly", "tenderly",
    "warily", "wearily", "wildly", "wisely",
]

PLACES = [
    "at the bottom of the sea", "on a rooftop at midnight",
    "in an empty theatre",
    "behind the library", "in the last carriage of the train",
    "under a broken streetlight", "on the wrong side of the river",
    "in a greenhouse in winter", "at the end of the pier",
    "in a lift that will not move", "on the roof of the school",
    "in a town with one traffic light", "at the back of a very long queue",
]

COUNTRIES = [
    "Argentina", "Australia", "Austria", "Bangladesh", "Belgium", "Bolivia",
    "Brazil", "Bulgaria", "Cambodia", "Canada", "Chile", "Colombia",
    "Croatia", "Czechia", "Denmark", "Ecuador", "Egypt", "Estonia",
    "Ethiopia", "Finland", "France", "Georgia", "Germany", "Ghana", "Greece",
    "Hungary", "Iceland", "India", "Indonesia", "Ireland", "Italy", "Japan",
    "Jordan", "Kenya", "Latvia", "Lithuania", "Malaysia", "Mexico", "Mongolia",
    "Morocco", "Nepal", "Netherlands", "New Zealand", "Nigeria", "Norway",
    "Pakistan", "Peru", "Philippines", "Poland", "Portugal", "Romania",
    "Senegal", "Serbia", "Singapore", "Slovakia", "Slovenia", "South Africa",
    "South Korea", "Spain", "Sri Lanka", "Sweden", "Switzerland", "Thailand",
    "Tunisia", "Turkey", "Ukraine", "Uruguay", "Vietnam",
]

FORTUNES = [
    "Yes, but not yet.", "No, and you already knew that.",
    "Ask again when you are less invested in the answer.",
    "Almost certainly.", "Only if you stop checking.",
    "The answer is boring and you will not like that.",
    "Yes, twice.", "Not today. Tomorrow is negotiable.",
    "It already happened; you were not paying attention.",
    "No, and it is a good thing.", "Yes, expensively.",
    "That depends entirely on you, which is the worst news possible.",
]

# One-line reactions. Kept as text rather than links so nothing here can rot.
REACTIONS = {
    "lol": ["\U0001f602 that got me", "\U0001f606 alright, that was good",
            "\U0001f923 unwell about it"],
    "omg": ["\U0001f631 absolutely not", "\U0001f628 no no no no",
            "\U0001f62e you cannot be serious"],
    "lmfao": ["\U0001f480 i am deceased", "\U0001f602\U0001f44c perfect",
              "\U0001f923\U0001f4a5 done, finished, over"],
    "pervert": ["\U0001f440 behave", "\U0001f6b6 walking away now",
                "\U0001f621 reported to the authorities"],
    "beam": ["✨ *beams you somewhere better* ✨",
             "\U0001f4ab zap. you are elsewhere now."],
    "bear": ["\U0001f43b *bear hug*", "\U0001f43b‍❄️ a polar one, even"],
    "bitesthedust": ["\U0001f3b8 *another one bites the dust*",
                     "\U0001f480 and another one gone"],
    "chocoshark": ["\U0001f988\U0001f36b the chocolate shark approves",
                   "\U0001f988 chomp"],
    "kirby": ["\U0001f38a (❀◠‿◠) poyo",
              "\U0001f338 kirby says hello"],
    "kirchoco": ["\U0001f38a\U0001f36b kirby has the chocolate now",
                 "(❀◠‿◠)\U0001f36b mine"],
    "nanachi": ["\U0001f430 nanaa~", "\U0001f430 *ears twitch*"],
    "takach": ["✨ taka! ✨", "\U0001f64c taka taka"],
    "takawai": ["\U0001f97a too cute, genuinely", "\U0001f496 unbearably soft"],
    "eater": ["\U0001f37d️ *eats it, whatever it was*",
              "\U0001f374 gone. no notes."],
    "destroy": ["\U0001f4a5 destroyed", "\U0001f525 reduced to atoms"],
}


class Fun(commands.Cog):
    """Text toys. Nothing here changes the game."""

    def __init__(self, bot):
        self.bot = bot

    async def _react(self, ctx, key: str):
        await ctx.send(random.choice(REACTIONS[key]))

    # ------------------------------------------------------------ reactions

    @commands.command(name="lol", aliases=["haha"])
    async def lol(self, ctx):
        """Laugh."""
        await self._react(ctx, "lol")

    @commands.command(name="omg")
    async def omg(self, ctx):
        """Be appalled."""
        await self._react(ctx, "omg")

    @commands.command(name="lmfao", aliases=["lmao"])
    async def lmfao(self, ctx):
        """Laugh harder."""
        await self._react(ctx, "lmfao")

    @commands.command(name="pervert")
    async def pervert(self, ctx):
        """Judge someone."""
        await self._react(ctx, "pervert")

    @commands.command(name="beam")
    async def beam(self, ctx):
        """Beam somewhere else."""
        await self._react(ctx, "beam")

    @commands.command(name="bear")
    async def bear(self, ctx):
        """A bear hug."""
        await self._react(ctx, "bear")

    @commands.command(name="bitesthedust", aliases=["btd"])
    async def bitesthedust(self, ctx):
        """Another one gone."""
        await self._react(ctx, "bitesthedust")

    @commands.command(name="chocoshark")
    async def chocoshark(self, ctx):
        """The chocolate shark."""
        await self._react(ctx, "chocoshark")

    @commands.command(name="kirby")
    async def kirby(self, ctx):
        """Poyo."""
        await self._react(ctx, "kirby")

    @commands.command(name="kirchoco")
    async def kirchoco(self, ctx):
        """Kirby, with chocolate."""
        await self._react(ctx, "kirchoco")

    @commands.command(name="nanachi")
    async def nanachi(self, ctx):
        """Nanaa~"""
        await self._react(ctx, "nanachi")

    @commands.command(name="takach")
    async def takach(self, ctx):
        """Taka."""
        await self._react(ctx, "takach")

    @commands.command(name="takawai")
    async def takawai(self, ctx):
        """Too cute."""
        await self._react(ctx, "takawai")

    @commands.command(name="eater")
    async def eater(self, ctx):
        """Eat it."""
        await self._react(ctx, "eater")

    @commands.command(name="smash")
    async def destroy(self, ctx, *, thing: str = None):
        """Destroy something."""
        if thing:
            await ctx.send(f"\U0001f4a5 **{thing[:120]}** has been destroyed.")
            return
        await self._react(ctx, "destroy")

    # ----------------------------------------------------------- generators

    @commands.command(name="noun")
    async def noun(self, ctx):
        """A random noun."""
        await ctx.send(f"**{random.choice(NOUNS)}**")

    @commands.command(name="adject", aliases=["adjective"])
    async def adject(self, ctx):
        """A random adjective."""
        await ctx.send(f"**{random.choice(ADJECTIVES)}**")

    @commands.command(name="adverb")
    async def adverb(self, ctx):
        """A random adverb."""
        await ctx.send(f"**{random.choice(ADVERBS)}**")

    @commands.command(name="vrb", aliases=["verb"])
    async def vrb(self, ctx):
        """A random verb."""
        await ctx.send(f"**{random.choice(VERBS)}**")

    @commands.command(name="phrase")
    async def phrase(self, ctx):
        """A random sentence."""
        await ctx.send(
            f"The {random.choice(ADJECTIVES)} {random.choice(NOUNS)} "
            f"{random.choice(ADVERBS)} {random.choice(VERBS)} "
            f"the {random.choice(ADJECTIVES)} {random.choice(NOUNS)}."
        )

    @commands.command(name="poem")
    async def poem(self, ctx):
        """Four lines of something."""
        lines = [
            f"The {random.choice(ADJECTIVES)} {random.choice(NOUNS)} "
            f"{random.choice(VERBS)} the {random.choice(NOUNS)},",
            f"{random.choice(ADVERBS)}, {random.choice(PLACES)}.",
            f"I {random.choice(VERBS)} the {random.choice(ADJECTIVES)} "
            f"{random.choice(NOUNS)}",
            f"and it {random.choice(VERBS)} me back.",
        ]
        await ctx.send(
            embed=discord.Embed(
                description="\n".join(f"*{line}*" for line in lines),
                colour=config.CARD_COLOUR,
            )
        )

    @commands.command(name="invent")
    async def invent(self, ctx):
        """Invent something nobody asked for."""
        await ctx.send(
            f"\U0001f4a1 **the {random.choice(ADJECTIVES)} "
            f"{random.choice(NOUNS)}** — it {random.choice(VERBS)} "
            f"your {random.choice(NOUNS)} {random.choice(ADVERBS)}."
        )

    @commands.command(name="craft")
    async def build(self, ctx):
        """Build something out of nothing."""
        await ctx.send(
            f"\U0001f528 You have built a {random.choice(ADJECTIVES)} "
            f"{random.choice(NOUNS)} out of a {random.choice(NOUNS)} "
            f"and a {random.choice(NOUNS)}."
        )

    @commands.command(name="date")
    async def date(self, ctx, member: discord.Member = None):
        """Where the date is, and how it goes."""
        who = member.display_name if member else "you"
        await ctx.send(
            f"\U0001f4c5 A date with **{who}**: {random.choice(PLACES)}, "
            f"{random.choice(ADVERBS)}. "
            f"{random.choice(['It goes well.', 'It does not go well.', 'It goes strangely.'])}"
        )

    @commands.command(name="fate", aliases=["fortune", "8ball"])
    async def fate(self, ctx, *, question: str = None):
        """Ask fate a question."""
        if question:
            await ctx.send(f"> {question[:180]}\n\U0001f52e {random.choice(FORTUNES)}")
            return
        await ctx.send(f"\U0001f52e {random.choice(FORTUNES)}")

    @commands.command(name="quote")
    async def quote(self, ctx):
        """Something that sounds wiser than it is."""
        await ctx.send(
            f"> *\"Never {random.choice(VERBS)} a {random.choice(ADJECTIVES)} "
            f"{random.choice(NOUNS)} {random.choice(ADVERBS)}.\"*"
        )

    @commands.command(name="say", aliases=["echo"])
    async def say(self, ctx, *, text: str = None):
        """Repeat something back, safely."""
        if not text:
            await ctx.send(f"Give me something to say — `{ctx.prefix}say hello`.")
            return
        # No mentions: a bot that can be made to ping @everyone is a bot that
        # will be made to ping @everyone.
        await ctx.send(
            text[:400],
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.command(name="rdmcountry", aliases=["randomcountry"])
    async def rdmcountry(self, ctx):
        """A random country."""
        await ctx.send(f"\U0001f30d **{random.choice(COUNTRIES)}**")

    @commands.command(name="secret", aliases=["sec"])
    async def secret(self, ctx):
        """A secret, told quietly."""
        try:
            await ctx.author.send(
                f"\U0001f92b The {random.choice(ADJECTIVES)} "
                f"{random.choice(NOUNS)} {random.choice(VERBS)} the "
                f"{random.choice(NOUNS)}. Tell nobody."
            )
        except discord.Forbidden:
            await ctx.send("Your DMs are closed, so the secret stays with me.")
            return
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention} \U0001f92b sent you a secret.")

    @commands.command(name="avatar", aliases=["pfp"])
    async def avatar(self, ctx, member: discord.Member = None):
        """Someone's avatar, full size."""
        member = member or ctx.author
        embed = discord.Embed(title=member.display_name, colour=config.CARD_COLOUR)
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Fun(bot))
