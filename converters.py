"""Forgiving argument types for commands.

FuzzyRole finds a role the way a person would say it. Role names on a lot of
servers are decorated, 「 ✦ Mod ✦ 」 or -ˏˋ ✶ ˊˎ- staff -ˏˋ ✶ ˊˎ-, and nobody
wants to type that out, so `mod` should find it, and so should `Mod`,
`moder` or a typo like `moderater`. A mention or an id still works exactly.
"""
import difflib
import unicodedata

import discord
from discord.ext import commands


def plain(name: str) -> str:
    """Letters and digits only, lower case, words kept apart:
    「 ✦ Co-owner ✦ 」 -> 'co owner'. Modifier letters like the ˏˋ in
    -ˏˋ ✶ ˊˎ- dividers count as decoration, not letters."""
    kept = "".join(c if unicodedata.category(c)[0] in "LN"
                   and unicodedata.category(c) != "Lm" else " " for c in name.lower())
    return " ".join(kept.split())


def score(query: str, name: str) -> float:
    """How well a role name fits what was typed. 0 is not at all."""
    if query.strip() == name:
        return 1000.0
    q, n = plain(query), plain(name)
    if not q or not n:
        return 0.0
    qs, ns = q.replace(" ", ""), n.replace(" ", "")
    if ns == qs:
        return 100.0
    if ns.startswith(qs):
        return 80.0 - (len(ns) - len(qs)) * 0.1      # the shorter, the closer
    if any(word.startswith(q) for word in n.split()):
        return 70.0 - (len(ns) - len(qs)) * 0.1
    if qs in ns:
        return 60.0 - (len(ns) - len(qs)) * 0.1
    ratio = difflib.SequenceMatcher(None, qs, ns).ratio()
    return 40.0 * ratio if ratio >= 0.6 else 0.0


def closest_role(guild, query: str):
    """The role that best fits what was typed, or None. On a tie, a role
    Paper can actually hand out wins, then the higher one."""
    top = guild.me.top_role if guild.me else None
    best, best_key = None, None
    for role in guild.roles:
        if role.is_default():
            continue
        fit = score(query, role.name)
        if not fit:
            continue
        usable = not role.managed and (top is None or role < top)
        key = (fit, usable, role.position)
        if best_key is None or key > best_key:
            best, best_key = role, key
    return best


class NoSuchRole(commands.BadArgument):
    """Nothing close enough; the message says what was looked for."""


class FuzzyRole(commands.Converter):
    async def convert(self, ctx, argument: str) -> discord.Role:
        try:
            return await commands.RoleConverter().convert(ctx, argument)
        except commands.BadArgument:
            pass
        role = closest_role(ctx.guild, argument)
        if role is None:
            raise NoSuchRole(f"I couldn't find a role like **{discord.utils.escape_markdown(argument[:50])}**.")
        return role
