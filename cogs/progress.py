"""Badges and the karuda tower.

Two long-term karuda sinks. Badges are seven materials of four levels each,
climbed one level at a time; the tower is a ladder of floors. Both feed the
same perks table, so a player sees one combined effect rather than having to
add things up themselves.

A badge level replaces the one below it rather than stacking on it, so the
number shown beside a badge is what it is worth, not what it adds.
"""
import discord
from discord.ext import commands

import config
import perks
from views import Confirm
import utils


class Progress(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _icon(self):
        return utils.shard_icon(config.SHARD_TYPES[0][0])

    def _badge_icon(self, badge, level: int = 1):
        """The badge's icon at that level, or the plain one for now."""
        return utils.badge_icon(badge.key, badge.fallback, level)

    @commands.command(name="badges", aliases=["badge", "badgelist"])
    @commands.guild_only()
    async def badges(self, ctx, member: discord.Member = None):
        """Every badge, the level you have, and what the next one costs."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        levels = db.badge_levels(gid, member.id)
        balance = db.get_player(gid, member.id)["karuda"]
        icon = self._icon()
        mine = member.id == ctx.author.id

        lines = [f"You have **{balance:,}** {icon} !", "",
                 "Melt your karuda into power badges:"]
        owned_levels = 0
        for badge in perks.BADGES:
            level = levels.get(badge.key, 0)
            owned_levels += level
            mark = self._badge_icon(badge, level)

            if not perks.unlocked(levels, badge):
                # Locked badges keep their name back, the way Mudae's do -
                # the list should read as something to uncover.
                lines.append(f"**???** · Prerequisites: {perks.requirement(badge)}")
                continue

            head = f"{mark} **{badge.name} {level}**"
            if level >= perks.LEVELS:
                lines.append(f"{head} · **maxed** · {badge.describe(level)}")
                continue

            price = perks.badge_price(db, gid, member.id, badge, level + 1)
            full = badge.price(level + 1)
            cost = f"**{price:,}** {icon}"
            if price < full:
                cost += f" ~~{full:,}~~"
            lines.append(f"{head} · Next level: {cost}  {badge.describe(level + 1)}")

        top = perks.LEVELS * len(perks.BADGES)
        lines += ["", f"**Karuda tower:** {ctx.prefix}tower",
                  f"**Buy a level:** {ctx.prefix}buybadge <name>"
                  if mine else f"**Badges:** {owned_levels}/{top} levels"]

        embed = discord.Embed(
            description="\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        embed.set_author(
            name=f"{member.display_name} — {owned_levels}/{top} badge levels",
            icon_url=member.display_avatar.url if member.display_avatar else None,
        )
        await ctx.send(embed=embed)

    @commands.command(name="buybadge", aliases=["bb", "upgradebadge"])
    @commands.guild_only()
    async def buybadge(self, ctx, *, name: str):
        """Climb a badge one level. `$buybadge gold`"""
        db = self.bot.db
        gid = ctx.guild.id
        wanted = name.strip().lower()
        badge = next(
            (b for b in perks.BADGES
             if b.key == wanted or b.name.lower() == wanted),
            None,
        )
        if not badge:
            names = ", ".join(b.name for b in perks.BADGES)
            await ctx.send(f"No badge called `{name}`. There is: {names}.")
            return

        levels = db.badge_levels(gid, ctx.author.id)
        level = levels.get(badge.key, 0)
        mark = self._badge_icon(badge, level)
        if not perks.unlocked(levels, badge):
            await ctx.send(
                f"**{badge.name}** is still locked. You need"
                f" {perks.requirement(badge)}."
            )
            return
        if level >= perks.LEVELS:
            await ctx.send(
                f"{mark} **{badge.name} {perks.ROMAN[-1]}** is as high as"
                f" it goes, and you are there."
            )
            return

        price = perks.badge_price(db, gid, ctx.author.id, badge, level + 1)
        balance = db.get_player(gid, ctx.author.id)["karuda"]
        if balance < price:
            await ctx.send(
                f"{mark} **{badge.name} {perks.ROMAN[level]}** costs"
                f" {price:,}; you have {balance:,}."
            )
            return

        db.add_karuda(gid, ctx.author.id, -price)
        db.raise_badge(gid, ctx.author.id, badge.key, level + 1)
        earned = perks.effective(db, gid, ctx.author.id)

        embed = discord.Embed(
            title=f"{self._badge_icon(badge, level + 1)}  "
                  f"{badge.name} {perks.ROMAN[level]}",
            description=f"{badge.describe(level + 1)}"
                        f"\n\nYour perks: _{perks.describe(earned)}_",
            colour=config.CARD_COLOUR,
        )
        nxt = badge.price(level + 2)
        embed.set_footer(
            text=f"-{price:,} karuda"
                 + (f" · {perks.ROMAN[level + 1]} costs {nxt:,}" if nxt else
                    " · maxed")
        )
        await ctx.send(embed=embed)

    def tower_embed(self, ctx, member) -> discord.Embed:
        """$kt, laid out the way Mudae lays it out."""
        db = self.bot.db
        gid = ctx.guild.id
        p = ctx.prefix
        icon = self._icon()
        rows = db.tower_floors_of(gid, member.id)
        tower, built, total = perks.tower_layout(rows)
        balance = db.get_player(gid, member.id)["karuda"]
        lines = [
            f"Spend your {icon} to build the {perks.PER_TOWER} floors of the tower:",
            "- Choose a different perk each time you build a floor",
            f"- The next floor is more expensive (+{perks.FLOOR_STEP:,} per floor,"
            f" {p}towervalue)",
            f"- You can restart your tower and be refunded with {p}destroy",
            f"- The construction might be infinite: if you manage to build the"
            f" {perks.PER_TOWER} floors, you can build an additional tower with lower"
            f" bonuses (the cost keeps increasing)",
            "",
        ]
        if tower > 1:
            lines.append(f"You're building tower **{tower}**: its bonuses are"
                         f" **{round(perks.tower_scale(tower) * 100)}%** of the first's.")
        lines += [
            f"Your current level is **{total}**",
            f"The next level costs **{perks.floor_cost(total):,}** {icon}",
            f"You have **{balance:,}** {icon}",
            "",
            f"Build a floor by using **{p}build <perk number>**",
            "",
            "List of perks and their corresponding numbers:",
            "",
        ]
        for number in perks.TOWER_PERKS:
            text = perks.perk_text(number, tower)
            lines.append(f"~~**{number}** = {text}~~ \u2705" if number in built
                         else f"**{number}** = {text}")
        lines += ["", f"4, 5 and 6 give keys: spend them with {p}key to raise a"
                      " character's value."]
        embed = discord.Embed(description="\n".join(lines)[:4096], colour=config.CARD_COLOUR)
        if member != ctx.author:
            embed.set_author(name=f"{member.display_name}'s tower",
                             icon_url=member.display_avatar.url)
        return embed

    @commands.command(name="tower", aliases=["kt", "karudatower"])
    @commands.guild_only()
    async def tower(self, ctx, member: discord.Member = None):
        """The karuda tower: build floors, a perk of your choice on each."""
        await ctx.send(embed=self.tower_embed(ctx, member or ctx.author))

    @commands.command(name="build", aliases=["ktup", "towerup", "climb", "kakeraup"])
    @commands.guild_only()
    async def build(self, ctx, perk: int = None):
        """`$build <perk number>`: build the next floor of your tower with
        that perk. `$kt` lists them."""
        db = self.bot.db
        gid, uid = ctx.guild.id, ctx.author.id
        if perk is None:
            await ctx.send(embed=self.tower_embed(ctx, ctx.author))
            return
        if perk not in perks.TOWER_PERKS:
            await ctx.send(f"Pick a perk from 1 to {perks.PER_TOWER}: `{ctx.prefix}kt` lists them.")
            return
        tower, built, total = perks.tower_layout(db.tower_floors_of(gid, uid))
        if perk in built:
            await ctx.send(f"You already have perk **{perk}** in this tower. Choose a"
                           " different one.")
            return
        cost = perks.floor_cost(total)
        balance = db.get_player(gid, uid)["karuda"]
        if balance < cost:
            await ctx.send(f"The next level costs **{cost:,}** {self._icon()}; you have"
                           f" **{balance:,}**.")
            return
        if not db.build_floor(gid, uid, tower, perk, cost):
            await ctx.send("That didn't go through. Try again.")
            return
        level = total + 1
        note = ""
        if level % perks.PER_TOWER == 0:
            note = (f"\n\n\U0001f3f0 Tower {tower} is finished! The next floor starts"
                    f" tower {tower + 1}, with bonuses at"
                    f" {round(perks.tower_scale(tower + 1) * 100)}%.")
        await ctx.send(
            f"\U0001f3d7\ufe0f **Level {level}** built: {perks.perk_text(perk, tower)}."
            f"\n-{cost:,} {self._icon()} · the next level costs"
            f" **{perks.floor_cost(level):,}**.{note}")

    @commands.command(name="destroy", aliases=["towerreset", "ktdestroy"])
    @commands.guild_only()
    async def destroy(self, ctx):
        """Pull your whole tower down and get back every karuda it cost."""
        db = self.bot.db
        gid, uid = ctx.guild.id, ctx.author.id
        rows = db.tower_floors_of(gid, uid)
        if not rows:
            await ctx.send("You haven't built anything yet.")
            return
        paid = sum(r["cost"] for r in rows)
        view = Confirm({uid})
        view.message = await ctx.send(
            f"Destroy all **{len(rows)}** levels of your tower? You'll get back"
            f" **{paid:,}** {self._icon()} and lose every perk it gives.", view=view)
        await view.wait()
        if not view.accepted or view.declined_by:
            await ctx.send("Your tower is still standing.")
            return
        floors, refund = db.destroy_tower(gid, uid)
        await ctx.send(f"\U0001f4a5 Tower destroyed: {floors} levels down,"
                       f" **{refund:,}** {self._icon()} refunded.")

    @commands.command(name="towervalue", aliases=["ktvalue", "towercost"])
    @commands.guild_only()
    async def towervalue(self, ctx):
        """What your tower has cost so far, and what the next floors cost."""
        db = self.bot.db
        rows = db.tower_floors_of(ctx.guild.id, ctx.author.id)
        total = len(rows)
        spent = sum(r["cost"] for r in rows)
        upcoming = "\n".join(f"Level {total + n + 1}: **{perks.floor_cost(total + n):,}**"
                              for n in range(5))
        await ctx.send(embed=discord.Embed(
            title="Tower value",
            description=f"Your tower is level **{total}** and has cost **{spent:,}**"
                        f" {self._icon()} (all of it back with `{ctx.prefix}destroy`).\n\n"
                        f"Each level costs {perks.FLOOR_STEP:,} more than the last:\n{upcoming}",
            colour=config.CARD_COLOUR))

    @commands.command(name="perks", aliases=["myperks", "bonuses"])
    @commands.guild_only()
    async def myperks(self, ctx, member: discord.Member = None):
        """Everything your badges and tower add up to."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        earned = perks.effective(db, gid, member.id)
        owned = db.badge_levels(gid, member.id)
        floor = len(db.tower_floors_of(gid, member.id))

        base_rolls = db.get_setting(gid, "roll_limit")
        base_grab = db.get_setting(gid, "karuda_grab_percent")
        base_claim = db.get_setting(gid, "claim_interval_minutes")
        claim_now = int(base_claim * (100 - earned["claim_percent"]) / 100)

        embed = discord.Embed(
            title=f"{member.display_name}'s perks", colour=config.CARD_COLOUR
        )
        embed.add_field(
            name="Rolls",
            value=f"{base_rolls + earned['rolls']} per window"
                  + (f"  (+{earned['rolls']})" if earned["rolls"] else ""),
            inline=True,
        )
        embed.add_field(
            name="Grab",
            value=f"{base_grab + earned['grab_percent']}% of value"
                  + (f"  (+{earned['grab_percent']})" if earned["grab_percent"] else ""),
            inline=True,
        )
        embed.add_field(
            name="Claim wait",
            value=f"{claim_now} min"
                  + (f"  (-{earned['claim_percent']}%)" if earned["claim_percent"] else ""),
            inline=True,
        )
        marks = " ".join(
            perks.BADGES_BY_KEY[key][1] for key in owned if key in perks.BADGES_BY_KEY
        )
        embed.add_field(
            name="From",
            value=f"Tower level {floor}"
                  + (f"\n{marks}" if marks else "\nno badges yet"),
            inline=False,
        )
        await ctx.send(embed=embed)

    @commands.command(name="toptower", aliases=["topkt", "towertop"])
    @commands.guild_only()
    async def toptower(self, ctx):
        """Who has climbed highest here."""
        rows = self.bot.db.top_towers(ctx.guild.id)
        if not rows:
            await ctx.send(f"Nobody has climbed yet. Try `{ctx.prefix}kt`.")
            return
        medals = ["\U0001f947", "\U0001f948", "\U0001f949"]
        lines = [
            f"{medals[i] if i < 3 else f'`{i + 1}.`'} <@{row['user_id']}>"
            f" — level **{row['tower_floor']}**"
            for i, row in enumerate(rows)
        ]
        await ctx.send(
            embed=discord.Embed(
                title=f"Tallest towers in {ctx.guild.name}",
                description="\n".join(lines),
                colour=config.CARD_COLOUR,
            )
        )


async def setup(bot):
    await bot.add_cog(Progress(bot))
