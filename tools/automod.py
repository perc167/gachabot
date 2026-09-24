"""Builds a Discord AutoMod rule that keeps commands in one channel.

    python tools/automod.py

The bot already has $channelallow, which makes it ignore commands outside the
channels you pick. AutoMod does the other half: it deletes the message, so a
stray $w in general never appears at all rather than sitting there being
ignored.

Two ways to write the rule, and they trade precision against upkeep.

A keyword list blocks exactly the commands that exist and nothing else, so
"$5" and "it cost $20" are untouched. It goes stale every time a command is
added, which is why this is a script rather than a file somebody typed once.
All 593 names fit inside Discord's limit of a thousand, so this is the one to
use.

A catch-all regex never goes stale but blocks anything shaped like $word.
Listing the commands individually as regex would take 22 patterns and Discord
allows 10, so the exact-list version is a keyword list or nothing.

Discord's limits, which the output respects: 1,000 keywords per rule at 60
characters each, or 10 regex patterns at 260 characters each.
"""
import argparse
import asyncio
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "automod.txt")

MAX_KEYWORDS = 1000
MAX_KEYWORD_LEN = 60
MAX_PATTERN_LEN = 260
MAX_PATTERNS = 10


async def every_name() -> list:
    """Every command name and alias the bot answers to."""
    os.environ.setdefault("DISCORD_TOKEN", "unused-for-listing")
    sys.path.insert(0, ROOT)
    import discord
    from discord.ext import commands as dcmd
    import db as dbmod
    import bot as botmod
    import tempfile

    client = dcmd.Bot(command_prefix="$", intents=discord.Intents.default())
    client.db = dbmod.Database(os.path.join(tempfile.mkdtemp(), "listing.db"))
    client.remove_command("help")
    for cog in botmod.COGS:
        await client.load_extension(cog)
    names = set()
    for command in client.walk_commands():
        # Staff commands ($jail, $ban...) have to work in every channel, so
        # they are never blocked.
        if getattr(command.cog, "staff_cog", False):
            continue
        names.add(command.name.lower())
        names.update(alias.lower() for alias in command.aliases)
    await client.close()
    return sorted(names)


def patterns(names, prefix: str) -> list:
    """Regex alternations, packed to Discord's per-pattern length limit."""
    # Longest first: without it, "w" matches before "wishlist" and the rest of
    # the word is left dangling outside the match.
    ordered = sorted(names, key=len, reverse=True)
    head, tail = f"(?i)(?:^|\\s){prefix}(?:", r")\b"
    room = MAX_PATTERN_LEN - len(head) - len(tail)

    out, current = [], []
    for name in ordered:
        candidate = "|".join(current + [name])
        if len(candidate) > room and current:
            out.append(head + "|".join(current) + tail)
            current = [name]
        else:
            current.append(name)
    if current:
        out.append(head + "|".join(current) + tail)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="\\$",
                        help="escaped for regex; $ by default")
    parser.add_argument("--out", default=OUT)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    names = asyncio.run(every_name())
    plain = args.prefix.replace("\\", "")

    keywords = [f"{plain}{name}" for name in names
                if len(name) + len(plain) <= MAX_KEYWORD_LEN]
    regexes = patterns(names, args.prefix)

    lines = []
    lines.append("DISCORD AUTOMOD — keep commands in one channel")
    lines.append("=" * 58)
    lines.append("")
    lines.append("Server Settings -> AutoMod -> Create your own")
    lines.append("  Trigger:  Custom Keywords")
    lines.append("  Action:   Block Message  (and Send Alert if you want a log)")
    lines.append("  Exempt:   your bot channel, under 'Allow specific channels'")
    lines.append("")
    lines.append("Anyone with Administrator bypasses AutoMod, so test it on an")
    lines.append("account that is not you.")
    lines.append("")
    lines.append("")
    fits = len(keywords) <= MAX_KEYWORDS
    lines.append(f"OPTION 1 — keywords ({len(keywords)} of {MAX_KEYWORDS}"
                 f" allowed){'' if fits else ' — TOO MANY, use option 2'}")
    lines.append("-" * 58)
    lines.append("Paste the block below into 'Keywords'. It blocks exactly the")
    lines.append("commands this bot has and nothing else, so \"$5\" and \"it")
    lines.append("cost $20\" still go through, and so does somebody saying")
    lines.append("\"$w\" is not a word.")
    lines.append("")
    lines.append("Re-run this script whenever commands are added, or the new")
    lines.append("ones will work everywhere.")
    lines.append("")
    lines.append(", ".join(keywords))
    lines.append("")
    lines.append("")
    lines.append("OPTION 2 — one regex (never goes stale)")
    lines.append("-" * 58)
    lines.append("Paste into 'Regex Patterns'. One line, and it covers every")
    lines.append("command including ones added later:")
    lines.append("")
    lines.append(f"(?i)(?:^|\\s){args.prefix}[a-z]{{1,24}}\\b")
    lines.append("")
    lines.append("It blocks anything shaped like $word, which means it also")
    lines.append("stops people typing a command while explaining one. In a")
    lines.append("channel where commands are banned that is usually the point.")
    lines.append("")
    lines.append(f"Listing every command as its own pattern would take"
                 f" {len(regexes)} patterns and Discord allows"
                 f" {MAX_PATTERNS}, which is why this is a catch-all rather")
    lines.append("than an exact list.")
    lines.append("")

    with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines))

    print(f"{len(names)} command names")
    print(f"  keywords: {len(keywords)} of {MAX_KEYWORDS}"
          + ("  <- use this" if len(keywords) <= MAX_KEYWORDS
             else "  !! too many, use the regex"))
    print(f"  exact regex would need {len(regexes)} patterns of"
          f" {MAX_PATTERNS} allowed, so option 2 is a catch-all")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
