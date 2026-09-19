"""Badges and the karuda tower.

Two long-term karuda sinks. Badges are one-off purchases with a fixed perk;
the tower is a ladder you climb a floor at a time, each costing more than the
last. Both feed the same perks table, so a player sees one combined effect
rather than having to add things up themselves.
"""
import discord
from discord.ext import commands

import config
import perks
import utils


class Progress(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _icon(self):
        return utils.shard_icon(config.SHARD_TYPES[0][0])

    @commands.command(name="badges", aliases=["badge", "badgelist"])
    @commands.guild_only()
    async def badges(self, ctx, member: discord.Member = None):
        """Badges you can buy, and the ones you have."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        owned = set(db.badges_of(gid, member.id))
        balance = db.get_player(gid, member.id)["karuda"]
        icon = self._icon()

        lines = []
        for key, mark, name, price, description, _perk in perks.BADGES:
            if key in owned:
                lines.append(f"{mark}  **{name}** ✓\n　{description}")
            else:
                affordable = "" if balance >= price else "  *(too dear for now)*"
                lines.append(
                    f"{mark}  **{name}** — {icon} {price:,}{affordable}"
                    f"\n　{description}"
                )

        embed = discord.Embed(
            title="Badges",
            description="\n\n".join(lines),
            colour=config.CARD_COLOUR,
        )
        embed.set_footer(
            text=f"{len(owned)}/{len(perks.BADGES)} owned · "
                 f"{balance:,} karuda · {ctx.prefix}buybadge <name>"
        )
        await ctx.send(embed=embed)

    @commands.command(name="buybadge", aliases=["bb"])
    @commands.guild_only()
    async def buybadge(self, ctx, *, name: str):
        """Buy a badge by name."""
        db = self.bot.db
        gid = ctx.guild.id
        wanted = name.strip().lower()
        match = next(
            (
                entry
                for entry in perks.BADGES
                if entry[0] == wanted or entry[2].lower() == wanted
            ),
            None,
        )
        if not match:
            names = ", ".join(entry[2] for entry in perks.BADGES)
            await ctx.send(f"No badge called `{name}`. There is: {names}.")
            return

        key, mark, badge_name, price, description, _perk = match
        if key in db.badges_of(gid, ctx.author.id):
            await ctx.send(f"You already have {mark} **{badge_name}**.")
            return
        balance = db.get_player(gid, ctx.author.id)["karuda"]
        if balance < price:
            await ctx.send(
                f"{mark} **{badge_name}** costs {price:,};"
                f" you have {balance:,}."
            )
            return

        db.add_karuda(gid, ctx.author.id, -price)
        db.add_badge(gid, ctx.author.id, key)
        earned = perks.effective(db, gid, ctx.author.id)
        embed = discord.Embed(
            title=f"{mark}  {badge_name}",
            description=f"{description}\n\nYour perks: _{perks.describe(earned)}_",
            colour=config.CARD_COLOUR,
        )
        embed.set_footer(text=f"-{price:,} karuda")
        await ctx.send(embed=embed)

    @commands.command(name="tower", aliases=["kt", "karudatower"])
    @commands.guild_only()
    async def tower(self, ctx, member: discord.Member = None):
        """Your tower: how high you have climbed and what is next."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, member.id)
        floor = player["tower_floor"]
        icon = self._icon()

        embed = discord.Embed(
            title=f"{member.display_name}'s tower",
            description=f"**Floor {floor}** of {perks.MAX_FLOOR}\n"
                        f"{perks.bar(floor, perks.MAX_FLOOR)}",
            colour=config.CARD_COLOUR,
        )
        embed.add_field(
            name="Perks so far",
            value=perks.describe(perks.tower_perks(floor)),
            inline=False,
        )

        cost = perks.floor_cost(floor + 1)
        if cost is None:
            embed.add_field(name="Next", value="The top. Nothing above you.", inline=False)
        else:
            gain = perks.describe(perks.floor_perk(floor + 1))
            balance = player["karuda"]
            short = "" if balance >= cost else f"  ({cost - balance:,} short)"
            embed.add_field(
                name=f"Floor {floor + 1}",
                value=f"{icon} **{cost:,}**{short}\ngrants {gain}",
                inline=False,
            )
            embed.set_footer(text=f"{balance:,} karuda · {ctx.prefix}ktup to climb")
        await ctx.send(embed=embed)

    @commands.command(name="ktup", aliases=["towerup", "climb", "kakeraup"])
    @commands.guild_only()
    async def ktup(self, ctx):
        """Climb one floor."""
        db = self.bot.db
        gid = ctx.guild.id
        player = db.get_player(gid, ctx.author.id)
        floor = player["tower_floor"]
        nxt = floor + 1
        cost = perks.floor_cost(nxt)

        if cost is None:
            await ctx.send(
                f"You are on the top floor ({perks.MAX_FLOOR}). Nothing above you."
            )
            return
        if player["karuda"] < cost:
            await ctx.send(
                f"Floor {nxt} costs {cost:,};"
                f" you have {player['karuda']:,}."
            )
            return

        db.add_karuda(gid, ctx.author.id, -cost)
        db.update_player(gid, ctx.author.id, tower_floor=nxt)
        keys_held = db.add_keys(gid, ctx.author.id, 1)  # a key per floor
        earned = perks.effective(db, gid, ctx.author.id)

        embed = discord.Embed(
            title=f"Floor {nxt}",
            description=f"{perks.bar(nxt, perks.MAX_FLOOR)}\n\n"
                        f"Gained **{perks.describe(perks.floor_perk(nxt))}**",
            colour=config.CARD_COLOUR,
        )
        embed.add_field(name="All your perks", value=perks.describe(earned), inline=False)
        embed.add_field(
            name="Key", value=f"\U0001f511 +1  (you hold {keys_held})", inline=False
        )
        following = perks.floor_cost(nxt + 1)
        embed.set_footer(
            text=f"-{cost:,} karuda"
            + (f" · floor {nxt + 1} costs {following:,}" if following else " · top floor")
        )
        await ctx.send(embed=embed)

    @commands.command(name="perks", aliases=["myperks", "bonuses"])
    @commands.guild_only()
    async def myperks(self, ctx, member: discord.Member = None):
        """Everything your badges and tower add up to."""
        member = member or ctx.author
        db = self.bot.db
        gid = ctx.guild.id
        earned = perks.effective(db, gid, member.id)
        owned = db.badges_of(gid, member.id)
        floor = db.get_player(gid, member.id)["tower_floor"]

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
            value=f"Tower floor {floor}/{perks.MAX_FLOOR}"
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
            f" — floor **{row['tower_floor']}**"
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
