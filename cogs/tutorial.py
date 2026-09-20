"""`$tuto` — the tutorial, built the way Mudae's is.

Steps hold substeps; substeps can be done in any order; a step is finished
only when all of them are, and finishing pays a reward. Progress comes from
actually using the commands rather than from pressing a button that says "I
have read this", which is the whole idea.

The listener is deliberately narrow: it only ever looks at the substeps of
the step you are currently on. Mudae works this way too, and it matters -
credit for work done before you reached a step would let somebody arrive at
step nine with it already finished and learn nothing.
"""
import discord
from discord.ext import commands

import config
import tutorial

DONE = "✅"
TODO = "⬜"


class Tutorial(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------ progress

    def _state(self, ctx_or_guild, user_id):
        db = self.bot.db
        gid = getattr(ctx_or_guild, "id", ctx_or_guild)
        return db, gid, db.tuto_step(gid, user_id)

    async def _grant(self, channel, guild_id: int, user_id: int, reward: dict):
        """Pay for a finished step."""
        db = self.bot.db
        if reward.get("karuda"):
            db.add_karuda(guild_id, user_id, reward["karuda"])
        if reward.get("item"):
            db.add_item(guild_id, user_id, reward["item"], 1)
        if reward.get("keys"):
            db.add_keys(guild_id, user_id, reward["keys"])
        if reward.get("wish_slot"):
            player = db.get_player(guild_id, user_id)
            db.update_player(
                guild_id, user_id,
                extra_wish_slots=player["extra_wish_slots"] + reward["wish_slot"])
        if reward.get("rolls"):
            self.bot.cooldowns.grant_rolls(guild_id, user_id, reward["rolls"])

    async def _advance(self, channel, guild_id: int, user_id: int, step: int):
        """Finish a step if every substep is done, and pay for it."""
        db = self.bot.db
        entry = tutorial.step(step)
        wanted = {sub["key"] for sub in entry["substeps"]}
        if not wanted <= db.finished_substeps(guild_id, user_id, step):
            return False

        await self._grant(channel, guild_id, user_id, entry["reward"])
        finished = step >= tutorial.TOTAL_STEPS
        db.set_tuto_step(guild_id, user_id, step if finished else step + 1)

        embed = discord.Embed(
            title=f"\U0001f389  Step {step} complete — {entry['title'].title()}",
            description=f"You earned {tutorial.describe_reward(entry['reward'])}.",
            colour=db.get_pref(guild_id, "cardcolour", config.CARD_COLOUR),
        )
        if finished:
            embed.add_field(
                name="That is all of it",
                value="Every step, every challenge. There is nothing left for"
                      " the tutorial to teach you.",
                inline=False,
            )
        else:
            following = tutorial.step(step + 1)
            embed.add_field(
                name=f"Step {step + 1}",
                value=following["title"].title(),
                inline=False,
            )
            embed.set_footer(text=f"{config.PREFIX}tuto for what is next")
        try:
            await channel.send(f"<@{user_id}>", embed=embed)
        except discord.HTTPException:
            pass
        return True

    async def credit(self, ctx, command_name: str):  # noqa: C901
        """Tick off any substep of the current step this command satisfies."""
        if ctx.guild is None:
            return
        db = self.bot.db
        gid = ctx.guild.id
        user = ctx.author.id
        step = db.tuto_step(gid, user)
        if step > tutorial.TOTAL_STEPS:
            return

        done = db.finished_substeps(gid, user, step)
        newly = []
        for sub in tutorial.substeps_for(step):
            if sub["key"] in done:
                continue
            if sub["commands"] and command_name not in sub["commands"]:
                continue
            # Some substeps care how the command was used, not just that it
            # was - "$help" and "$help wish" are different lessons.
            wants = sub.get("wants")
            if wants and not wants(ctx):
                continue
            # A substep with no command of its own rides on its check, and
            # gets looked at whenever anything else happens. "Claim a
            # character" is not a command you type, so nothing else would
            # ever notice it was done.
            check = sub.get("check")
            if check and not check(db, gid, user):
                continue
            if db.finish_substep(gid, user, step, sub["key"]):
                newly.append(sub)

        if newly and not db.tuto_silent(gid, user):
            remaining = len(tutorial.substeps_for(step)) - len(
                db.finished_substeps(gid, user, step))
            for sub in newly:
                tail = (f" · {remaining} left in step {step}" if remaining
                        else "")
                try:
                    await ctx.send(
                        f"{DONE} **Substep complete** — {sub['title'].title()}"
                        f"{tail}",
                        delete_after=25,
                    )
                except discord.HTTPException:
                    pass
        if newly:
            await self._advance(ctx.channel, gid, user, step)

    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        """Every successful command is a chance to tick something off."""
        if ctx.guild is None or ctx.command is None:
            return
        try:
            await self.credit(ctx, ctx.command.qualified_name)
        except Exception:  # noqa: BLE001 - the tutorial must never eat a command
            pass

    # ------------------------------------------------------------ commands

    def _render(self, ctx, number: int) -> discord.Embed:
        db = self.bot.db
        gid = ctx.guild.id
        user = ctx.author.id
        prefix = ctx.prefix or config.PREFIX
        entry = tutorial.step(number)
        done = db.finished_substeps(gid, user, number)
        current = db.tuto_step(gid, user)

        lines = []
        for sub in entry["substeps"]:
            mark = DONE if sub["key"] in done else TODO
            body = sub["text"].format(p=prefix)
            lines.append(f"{mark} **{sub['title']}**\n{body}")

        embed = discord.Embed(
            title=f"Step {number} of {tutorial.TOTAL_STEPS}"
                  f" — {entry['title'].title()}",
            description="\n\n".join(lines)[:4000],
            colour=db.get_pref(gid, "cardcolour", config.CARD_COLOUR),
        )
        embed.add_field(
            name="Reward",
            value=tutorial.describe_reward(entry["reward"]),
            inline=False,
        )
        if number < current:
            embed.set_footer(
                text=f"Already finished · you are on step {current}"
                     f" · {prefix}tuto for that one"
            )
        elif number > current:
            embed.set_footer(text=f"Not reached yet · you are on step {current}")
        else:
            left = len(entry["substeps"]) - len(done)
            embed.set_footer(
                text=(f"{left} substep(s) to go · they can be done in any order"
                      if left else "All done — finishing now")
            )
        return embed

    @commands.command(name="tuto", aliases=["do", "tutorial", "howto"])
    @commands.guild_only()
    async def tuto(self, ctx, number: int = None):
        """The tutorial. `$tuto 3` re-reads an earlier step."""
        db = self.bot.db
        current = db.tuto_step(ctx.guild.id, ctx.author.id)

        if number is None:
            number = min(current, tutorial.TOTAL_STEPS)
        elif not 1 <= number <= tutorial.TOTAL_STEPS:
            await ctx.send(
                f"There are {tutorial.TOTAL_STEPS} steps."
                f" `{ctx.prefix}tuto 1` is the first."
            )
            return
        elif number > current:
            await ctx.send(
                f"You are on step **{current}**. Step {number} opens when you"
                f" get there — `{ctx.prefix}tuto` shows what is next."
            )
            return

        await ctx.send(embed=self._render(ctx, number))

    @commands.command(name="tutoprogress", aliases=["tutostatus"])
    @commands.guild_only()
    async def tutoprogress(self, ctx, member: discord.Member = None):
        """How far through the tutorial somebody is."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        step = db.tuto_step(gid, member.id)
        done = db.tuto_done_count(gid, member.id)
        finished = step >= tutorial.TOTAL_STEPS and not (
            set(s["key"] for s in tutorial.substeps_for(tutorial.TOTAL_STEPS))
            - db.finished_substeps(gid, member.id, tutorial.TOTAL_STEPS))

        embed = discord.Embed(
            title=f"\U0001f4d8  {member.display_name}'s tutorial",
            description=(
                "Finished, every step." if finished else
                f"On step **{step}** of {tutorial.TOTAL_STEPS} —"
                f" *{tutorial.step(step)['title'].title()}*"
            ),
            colour=db.get_pref(gid, "cardcolour", config.CARD_COLOUR),
        )
        embed.add_field(
            name="Substeps",
            value=f"**{done}** of {tutorial.TOTAL_SUBSTEPS} done",
            inline=True,
        )
        embed.add_field(
            name="Main steps",
            value=f"{min(step, tutorial.MAIN_STEPS)} of {tutorial.MAIN_STEPS}"
                  + ("\n*challenges after that*"
                     if step > tutorial.MAIN_STEPS else ""),
            inline=True,
        )
        await ctx.send(embed=embed)

    @commands.command(name="skipsubstep")
    @commands.guild_only()
    async def skipsubstep(self, ctx):
        """Skip a substep this server makes impossible.

        Only ever substeps marked skippable - the ones that need an unclaimed
        character or a soulmate, which a quiet or fully-claimed server may not
        be able to give you.
        """
        db = self.bot.db
        gid = ctx.guild.id
        user = ctx.author.id
        step = db.tuto_step(gid, user)
        done = db.finished_substeps(gid, user, step)
        blocked = [sub for sub in tutorial.substeps_for(step)
                   if sub["key"] not in done and sub.get("skippable")]
        if not blocked:
            await ctx.send(
                "Nothing on this step can be skipped — every one of them is"
                " something you can do here."
            )
            return
        sub = blocked[0]
        db.finish_substep(gid, user, step, sub["key"])
        await ctx.send(f"Skipped **{sub['title'].title()}**.")
        await self._advance(ctx.channel, gid, user, step)

    @commands.command(name="silentstep")
    @commands.guild_only()
    async def silentstep(self, ctx):
        """Stop the bot announcing each finished substep."""
        db = self.bot.db
        quiet = not db.tuto_silent(ctx.guild.id, ctx.author.id)
        db.set_tuto_silent(ctx.guild.id, ctx.author.id, quiet)
        await ctx.send(
            "Substep messages are **off**. Steps still announce themselves."
            if quiet else "Substep messages are **on** again."
        )

    @commands.command(name="skiptuto")
    @commands.guild_only()
    async def skiptuto(self, ctx):
        """Jump to the challenges, if you finished the tutorial elsewhere."""
        db = self.bot.db
        gid = ctx.guild.id
        user = ctx.author.id
        if db.tuto_step(gid, user) > tutorial.MAIN_STEPS:
            await ctx.send("You are already past the main tutorial here.")
            return
        if not db.tuto_finished_anywhere(user, tutorial.MAIN_STEPS):
            await ctx.send(
                "This is for people who have finished the tutorial on another"
                " server. You have not yet — so there is nothing to skip."
            )
            return

        # Every step they are skipping is credited, so the rewards are not
        # quietly lost for having done it once already.
        paid = 0
        for number in range(db.tuto_step(gid, user), tutorial.MAIN_STEPS + 1):
            entry = tutorial.step(number)
            for sub in entry["substeps"]:
                db.finish_substep(gid, user, number, sub["key"])
            await self._grant(ctx.channel, gid, user, entry["reward"])
            paid += entry["reward"].get("karuda", 0)
        db.set_tuto_step(gid, user, tutorial.MAIN_STEPS + 1)
        await ctx.send(
            f"Skipped to the challenges, and paid the **{paid:,}**"
            f" {config.CURRENCY} you had already earned elsewhere."
        )

    @commands.command(name="resettuto", aliases=["tutoreset"])
    @commands.guild_only()
    async def resettuto(self, ctx):
        """Start the tutorial again from step one. Rewards are not taken back."""
        gone = self.bot.db.reset_tutorial(ctx.guild.id, ctx.author.id)
        await ctx.send(
            f"Cleared **{gone}** substeps — back to step 1."
            f" Anything you were paid stays yours."
        )


async def setup(bot):
    await bot.add_cog(Tutorial(bot))
