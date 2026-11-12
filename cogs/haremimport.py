"""Bring harems over from Mudae.

Mudae has no API and no export file, but it will print a harem as text:
`$mmasi- <user ID>` lists every character under its series, one per line,
the way the community harem sorters read it. The flags matter: `a` groups by
series, `s` sends the list to whoever asked by DM, `i-` leaves the images out
of that DM. Mudae takes a user ID in place of a mention (its own tutorial
says so, "because it's better to not mention someone"), so an admin can pull
everyone's list without pinging anybody - it lands in the admin's DMs.

From there the admin gets it into Paper one of three ways: forward Mudae's
DM messages into a channel and run the command there (Paper reads the
forwards, and any list Mudae posted in the channel itself), attach the list
as a text file, or paste it after the command. Paper only ever reads what
Mudae, a bot, wrote; nobody's account is automated.

A whole server at once: Mudae only prints one harem per command (a role
mention finds nothing) and ignores other bots, so Paper can't ask it for
everyone. But the `o` flag (`$mmasi-o`) writes the owner on every line
("\U0001f49e => name"), so the admin can pull everyone's list, forward or
paste them all into one place, and a single `$haremimport all` sorts each
character to its owner. No need to know how Mudae titles a list.

Matching is the hard part. Mudae and Paper name the same people differently:
Mudae says "Monkey D. Luffy" from "One Piece", Paper (from AniList) says
"Luffy Monkey" from "ONE PIECE", and Mudae's "Dungeon Meshi" is Paper's
"Delicious in Dungeon". So names are compared as a bag of words, in any
order, with accents, punctuation and long vowels (Gojou/Gojo) folded away,
and the series only breaks ties between people who share a name. A match is
"sure" when the name is exact and the series agrees; anything less is a
"guess", shown to the admin before anything changes, who can take the sure
ones only.

Nothing is ever taken from anyone: a character someone here already holds
stays theirs, and running the same import twice adds nothing the second
time. The server's harem cap still applies.
"""
import asyncio
import difflib
import math
import re
import typing
import unicodedata
from collections import defaultdict

import discord
from discord.ext import commands

from cogs.levels import shown_names

MUDAE_IDS = {432610292342587392}
# a: by series, s: by DM, i-: no images in the DM, o: owner on every line
EXPORT_COMMAND = "$mmasi-o"
QUIET = discord.AllowedMentions.none()   # an import never pings anyone
HISTORY_LIMIT = 200          # messages read back looking for Mudae's list
BULK_HISTORY = 1500          # ...and for everyone's lists at once
BULK_WORDS = {"all", "everyone", "server"}
DONE_MARK = "\U0001f48d Imported"   # starts Paper's "import finished" reply
COMMON_TOKEN = 3000          # a word on more characters than this is no clue

SERIES_HEADER = re.compile(r"^(.+?)\s+-\s+\d[\d,]*\s*/\s*\d[\d,]*$")
URL = re.compile(r"<?https?://\S+>?")
OWNER = re.compile(r"\U0001f49e\s*=>\s*(\S+)")
RANK = re.compile(r"^#?[\d,]+\s+-\s+")
VALUES = re.compile(r"\s+[\d][\d,.\s]*\s*(?:ka|sp)\b.*$", re.IGNORECASE)
CUSTOM_EMOJI = re.compile(r"<a?:\w+:\d+>")
TEXT_EMOJI = re.compile(r":\w+:")
TAGS = re.compile(r"\(\s*\$[^)]*\)")
TRAILING_META = re.compile(r"\s*\((?:#[0-9a-f]{6}|\d+)\)\s*$", re.IGNORECASE)
MARKDOWN = re.compile(r"\*\*|__|~~|`|\\(?=\W)")
WORD = re.compile(r"[a-z0-9]+")


def is_mudae(user) -> bool:
    """Mudae itself, or one of its Mudamaid helper bots."""
    if not getattr(user, "bot", False):
        return False
    name = (getattr(user, "name", "") or "").lower()
    return user.id in MUDAE_IDS or name.startswith(("mudae", "mudamaid"))


def message_text(message) -> str:
    """What Mudae wrote in a message, whether as text or in an embed. Works
    on a forwarded message's snapshot too: it has the same two parts."""
    parts = [message.content or ""]
    for embed in message.embeds:
        parts.append(embed.description or "")
        for field in embed.fields:
            parts.append(f"{field.name}\n{field.value}")
    return "\n".join(p for p in parts if p)


def _clean_name(line: str) -> str:
    """The character's name out of one line of Mudae's list."""
    name = URL.sub("", line)
    for stop in ("\U0001f49e", "·", "|"):
        name = name.split(stop, 1)[0]
    name = VALUES.sub("", name)
    name = RANK.sub("", name.strip())
    name = TAGS.sub("", CUSTOM_EMOJI.sub("", name))
    name = TEXT_EMOJI.sub("", name)
    name = TRAILING_META.sub("", name)
    name = re.sub(r"^\d+\.\s+", "", name.strip())
    # Emoji Mudae hangs on a name (\U0001f6ab for disabled, sparkles...) and
    # the dash before the image link.
    return "".join(c for c in name if unicodedata.category(c)[0] != "S"
                   ).strip(" -–—\t")


def parse_mudae(text: str) -> list:
    """[(name, series, owner), ...] from Mudae's harem list, in its order.

    Series headers look like "One Piece - 302/524". A line is a character if
    it sits under a header or carries an image link; the harem's title and
    total above the first header are neither. When the list has image links
    at all, only lines with one count: several people's lists pasted one
    after another put the next title and total under the last header. Owner
    is the name after \U0001f49e => when Mudae shows one, else "".
    """
    out, seen, series = [], set(), None
    linked = bool(URL.search(text or ""))
    for raw in (text or "").splitlines():
        line = MARKDOWN.sub("", raw).replace("​", "").strip()
        if not line:
            continue
        header = SERIES_HEADER.match(line)
        if header and not URL.search(line):
            series = header.group(1).strip()
            continue
        if (series is None or linked) and not URL.search(line):
            continue
        owner = OWNER.search(line)
        name = _clean_name(line)
        if not name or len(name) > 80:
            continue
        entry = (name, series or "", owner.group(1).strip() if owner else "")
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def fold(text: str) -> str:
    """Lowercase, no accents, long vowels shortened: Gojou and Gojo agree."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return text.replace("ou", "o").replace("uu", "u").replace("oo", "o")


def words(text: str) -> frozenset:
    """A name as a bag of words. One-letter words (the D. in Monkey D.
    Luffy) are dropped unless they're all there is."""
    every = WORD.findall(fold(text))
    core = [w for w in every if len(w) > 1]
    return frozenset(core or every or [fold(text).strip()])


def series_likeness(a: str, b: str) -> float:
    """0 to 1: how likely two series names are the same show."""
    a, b = fold(a), fold(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    wa, wb = set(WORD.findall(a)), set(WORD.findall(b))
    joined_a, joined_b = " ".join(sorted(wa)), " ".join(sorted(wb))
    shared = len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0
    inside = 0.9 if (a in b or b in a) else 0.0
    return max(shared, inside, difflib.SequenceMatcher(None, a, b).ratio(),
               difflib.SequenceMatcher(None, joined_a, joined_b).ratio())


class Roster:
    """Paper's characters indexed by the words of their names."""

    def __init__(self, rows):
        self.by_key = defaultdict(list)
        self.by_word = defaultdict(list)
        for row in rows:
            key = words(row["name"])
            self.by_key[key].append(row)
            for w in key:
                self.by_word[w].append((key, row))

    def nearby(self, key: frozenset) -> list:
        """(key, row) for characters sharing a telling word with this name."""
        pool, seen = [], set()
        for w in key:
            group = self.by_word.get(w, ())
            if len(group) > COMMON_TOKEN:
                continue
            for k, row in group:
                if row["id"] not in seen:
                    seen.add(row["id"])
                    pool.append((k, row))
        return pool

    def match(self, name: str, series: str):
        """(row, sure) for the best Paper character for a Mudae entry, or
        (None, False)."""
        key = words(name)
        kind, candidates = "exact", list(self.by_key.get(key, ()))
        if not candidates:
            kind = "close"
            joined = " ".join(sorted(key))
            for k, row in self.nearby(key):
                smaller = min(len(k), len(key))
                if smaller >= 2 and (k <= key or key <= k):
                    candidates.append(row)
                elif difflib.SequenceMatcher(
                        None, joined, " ".join(sorted(k))).ratio() >= 0.86:
                    candidates.append(row)
        if not candidates:
            return None, False

        def score(row):
            fame = min(math.log10((row["favourites"] or 0) + 1), 5) * 0.03
            return series_likeness(series, row["series"]) + fame

        ranked = sorted(candidates, key=score, reverse=True)
        best = ranked[0]
        likeness = series_likeness(series, best["series"])
        if not series:
            return best, kind == "exact" and len(ranked) == 1
        if kind != "exact" and likeness < 0.45:
            # A near-miss name from a different show is a different person.
            return None, False
        runner_up = score(ranked[1]) if len(ranked) > 1 else -1.0
        sure = (kind == "exact" and likeness >= 0.45
                and (len(ranked) == 1 or score(best) - runner_up >= 0.15))
        return best, sure


def match_all(entries: list, rows) -> list:
    """[(entry, row or None, sure), ...]. Pure, so it can run off the event
    loop: indexing a hundred thousand names takes a moment."""
    roster = Roster(rows)
    return [(entry, *roster.match(entry[0], entry[1])) for entry in entries]


class ImportChoice(discord.ui.View):
    """Import everything matched, only the sure matches, or nothing."""

    def __init__(self, author_id: int, everything: int, sure: int):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.choice = None
        self.message = None
        self.all_button.label = f"Import {everything}"
        if sure == everything:
            self.remove_item(self.sure_button)
        else:
            self.sure_button.label = f"Only sure ones ({sure})"
            self.sure_button.disabled = sure == 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only whoever started this import can answer it.", ephemeral=True)
            return False
        return True

    async def _pick(self, interaction, choice):
        self.choice = choice
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Import", style=discord.ButtonStyle.success)
    async def all_button(self, interaction, _button):
        await self._pick(interaction, "all")

    @discord.ui.button(label="Only sure ones", style=discord.ButtonStyle.primary)
    async def sure_button(self, interaction, _button):
        await self._pick(interaction, "sure")

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction, _button):
        await self._pick(interaction, None)

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


def person_lines(members: dict, plan: dict) -> list:
    """One preview line per person, most characters to add first."""
    counts = {mid: defaultdict(int) for mid in members}
    for kind in ("sure", "guess", "already", "taken", "full"):
        for who, _entry, _row in plan[kind]:
            counts[who.id][kind] += 1
    for who, _entry in plan["missing"]:
        counts[who.id]["missing"] += 1

    def adding(mid):
        return counts[mid]["sure"] + counts[mid]["guess"]

    out = []
    for mid in sorted(members, key=lambda m: (-adding(m), members[m].display_name)):
        c = counts[mid]
        extra = [f"{c[k]:,} {label}" for k, label in (
            ("guess", "guesses"), ("already", "already theirs"),
            ("taken", "held by others"), ("full", "over the cap"),
            ("missing", "not in roster")) if c[k]]
        out.append(f"\u3000**{members[mid].display_name}**: {adding(mid):,} to add"
                   + (f" ({', '.join(extra)})" if extra else ""))
    return out


async def collect_mudae(history, everything: bool = False, stop=None) -> str:
    """Mudae's most recent run of messages, from newest-first history.

    Skip anything until Mudae's first message, then collect until a person
    spoke - that's whoever asked Mudae for the list. Other bots' replies in
    between don't count. A forwarded message counts as Mudae's: `$mmasi-`
    sends the list by DM, so it reaches a channel as forwards, under the
    name of whoever forwarded it. Forwards carry no original author, but
    the admin sees every match before anything changes.

    With `everything`, people talking in between doesn't end it: every list
    back to the last finished import here (`stop` says which message that
    is) counts, so the admin can forward a whole server's lists, asking
    Mudae for each in between.
    """
    chunks = []
    async for message in history:
        if stop is not None and stop(message):
            break
        forwarded = getattr(message, "message_snapshots", None) or []
        if is_mudae(message.author):
            chunks.append(message_text(message))
        elif forwarded:
            # Newest first, like the history: the whole list is flipped at the end.
            chunks.extend(message_text(s) for s in reversed(forwarded))
        elif not message.author.bot and chunks and not everything:
            break
    return "\n".join(reversed(chunks))


def plan_import(db, guild_id: int, assigned: list, cap: int) -> dict:
    """Decide what an import would do, changing nothing.

    `assigned` is [(member, entry, row, sure), ...]. Returns lists of
    (member, entry, row) under: sure, guess, already (theirs here), taken
    (someone else's here), full (over the harem cap), and missing
    [(member, entry)] for names Paper's roster doesn't have.
    """
    plan = {k: [] for k in ("sure", "guess", "already", "taken", "full", "missing")}
    claimed = set()
    room = {}
    # Sure matches get the room first, so a cap never trades one for a guess.
    for want_sure in (True, False):
        for member, entry, row, sure in assigned:
            if row is None:
                if want_sure:
                    plan["missing"].append((member, entry))
                continue
            if sure != want_sure:
                continue
            owner = db.owner_of(guild_id, row["id"])
            if owner == member.id:
                plan["already"].append((member, entry, row))
                continue
            if owner is not None or row["id"] in claimed:
                plan["taken"].append((member, entry, row))
                continue
            if cap:
                if member.id not in room:
                    room[member.id] = max(cap - db.harem_size(guild_id, member.id), 0)
                if room[member.id] <= 0:
                    plan["full"].append((member, entry, row))
                    continue
                room[member.id] -= 1
            claimed.add(row["id"])
            plan["sure" if sure else "guess"].append((member, entry, row))
    return plan


class HaremImport(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def read_mudae(self, ctx, everything: bool = False) -> str:
        """Mudae's list as posted (or forwarded) in this channel or thread,
        walking back from the command. With `everything`, every list since
        the last import Paper finished here."""
        before = discord.Object(id=ctx.message.id) if getattr(ctx.message, "id", None) else None
        me = getattr(self.bot.user, "id", None)

        def finished_import(message):
            return (message.author.id == me
                    and (message.content or "").startswith(DONE_MARK))

        try:
            return await collect_mudae(
                ctx.channel.history(limit=BULK_HISTORY if everything else HISTORY_LIMIT,
                                    before=before),
                everything=everything, stop=finished_import if everything else None)
        except discord.HTTPException:
            return ""

    @commands.command(name="haremimport", aliases=["importharem", "mudaeimport"])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def haremimport(self, ctx, member: typing.Optional[discord.Member] = None,
                          *, text: str = ""):
        """Bring Mudae harems over without pinging anyone. Run
        `$mmasi-o <their user ID>` and Mudae DMs you their list. Forward
        those DMs here (or attach them as a text file), then run this with
        their user ID, username or @mention - or `all` to import every
        list forwarded here at once. Shows every match before it changes
        anything."""
        db = self.bot.db
        gid = ctx.guild.id
        first, _sep, rest = text.strip().partition(" ")
        if member is None and first.lower() in BULK_WORDS:
            text = rest
        source = "your file"
        if ctx.message.attachments:
            raw = [await a.read() for a in ctx.message.attachments[:5]]
            text = "\n".join(r.decode("utf-8-sig", errors="replace") for r in raw)
        elif not text.strip():
            # Nobody named: every list since the last import, each line
            # going to the owner Mudae wrote on it.
            text = await self.read_mudae(ctx, everything=member is None)
            source = "Mudae's lists here" if member is None else "Mudae's messages here"
        else:
            source = "what you pasted"

        entries = parse_mudae(text)
        how_to_id = ("To copy a user ID: turn on Developer Mode (User Settings,"
                     " Advanced), then right-click them and pick Copy User ID.")
        word = text.strip()
        if not entries and member is None and word.startswith("<@&"):
            await ctx.send(
                "That's a role - Mudae and Paper both take one person at a time."
                f" For everyone: pull each list with `{EXPORT_COMMAND} <user ID>`,"
                f" forward them here, then `{ctx.prefix}haremimport all`.\n{how_to_id}",
                allowed_mentions=QUIET)
            return
        if not entries and member is None and word and "\n" not in word and len(word) <= 40:
            # One short word that isn't a list: a name or ID that matched
            # nobody here, which the member lookup handed on as text.
            await ctx.send(
                f"I couldn't find `{word[:40]}` in this server. Name them by user ID"
                " (it never pings), @mention or username - a name with spaces goes"
                f" in quotes.\n{how_to_id}", allowed_mentions=QUIET)
            return
        if not entries:
            await ctx.send(
                f"I couldn't find a Mudae harem list in {source}.\n"
                f"1. Get each list without pinging anyone: `{EXPORT_COMMAND} <their"
                " user ID>` - one person per command, not a role. Mudae sends it to"
                " your DMs (`s` means DM, `o` writes the owner on every line)."
                " `$tsv id` lists everyone's IDs.\n"
                "2. Forward Mudae's DM messages into this channel, then run"
                f" `{ctx.prefix}haremimport all` here for everyone at once (or"
                f" `{ctx.prefix}haremimport <their user ID>` for one person). Or copy"
                " the lists into a text file and attach it to the command.\n"
                + how_to_id, allowed_mentions=QUIET)
            return

        # Whose harem is whose: the member named, or the owner Mudae printed
        # on each line when it printed one.
        people = [m for m in ctx.guild.members if not m.bot]
        by_name = {m.name.lower(): m for m in people}
        by_shown = shown_names(people)
        unowned = set()
        owned = []
        for entry in entries:
            who = member
            if who is None and entry[2]:
                key = entry[2].lower()
                who = by_name.get(key) or by_shown.get(key)
            if who is None:
                unowned.add(entry[2] or "")
                continue
            owned.append((who, entry))
        if not owned:
            await ctx.send(
                "Mudae's list doesn't say whose it is. Name them:"
                f" `{ctx.prefix}haremimport <their user ID>`. Or pull lists with"
                f" `{EXPORT_COMMAND} <user ID>` - the `o` writes the owner on every"
                f" line, so `{ctx.prefix}haremimport all` can sort everyone's at once."
                + (f" I couldn't find {', '.join(f'`{n}`' for n in sorted(unowned) if n)}"
                   " here." if any(unowned) else ""),
                allowed_mentions=QUIET)
            return

        working = await ctx.send(f"Matching {len(owned):,} characters against"
                                 " Paper's roster...", allowed_mentions=QUIET)
        rows = db.roster_for_matching(gid)
        matched = await asyncio.to_thread(match_all, [e for _m, e in owned], rows)
        assigned = [(who, entry, row, sure)
                    for (who, _e), (entry, row, sure) in zip(owned, matched)]
        cap = db.get_setting(gid, "max_marriages")
        plan = plan_import(db, gid, assigned, cap)
        try:
            await working.delete()
        except discord.HTTPException:
            pass

        members = {who.id: who for who, *_rest in assigned}
        whose = (members[next(iter(members))].display_name if len(members) == 1
                 else f"{len(members)} people")
        sure, guess = plan["sure"], plan["guess"]
        lines = [f"From {source}: **{len(entries):,}** characters in {whose}'s"
                 " Mudae harem."]
        lines.append(f"✅ **{len(sure):,}** sure matches")
        if guess:
            lines.append(f"\U0001f914 **{len(guess):,}** guesses - check these:")
            for _who, entry, row in guess[:12]:
                lines.append(f"　{entry[0]} ({entry[1] or '?'}) →"
                             f" **{row['name']}** ({row['series']})")
            if len(guess) > 12:
                lines.append(f"　...and {len(guess) - 12:,} more")
        if plan["already"]:
            lines.append(f"↩️ **{len(plan['already']):,}** already theirs here")
        if plan["taken"]:
            shown = ", ".join(
                f"{row['name']} (<@{db.owner_of(gid, row['id']) or who.id}>)"
                for who, _e, row in plan["taken"][:8])
            more = f" and {len(plan['taken']) - 8:,} more" if len(plan["taken"]) > 8 else ""
            lines.append(f"\U0001f512 **{len(plan['taken']):,}** held by someone else"
                         f" here, left with them: {shown}{more}")
        if plan["full"]:
            lines.append(f"\U0001f4e6 **{len(plan['full']):,}** over the harem cap of"
                         f" {cap:,}, left out")
        if plan["missing"]:
            shown = ", ".join(f"`{e[0]}`" for _who, e in plan["missing"][:25])
            more = (f" and {len(plan['missing']) - 25:,} more"
                    if len(plan["missing"]) > 25 else "")
            lines.append(f"❓ **{len(plan['missing']):,}** not in Paper's roster:"
                         f" {shown}{more}")
        if len(members) > 1:
            lines.append("\n**Per person**")
            lines.extend(person_lines(members, plan)[:15])
            if len(members) > 15:
                lines.append(f"\u3000...and {len(members) - 15:,} more people")
        if any(unowned):
            lines.append("❓ Not members here: "
                         + ", ".join(f"`{n}`" for n in sorted(unowned) if n)[:900])
        if "" in unowned:
            nameless = sum(1 for e in entries if not e[2])
            lines.append(f"❓ **{nameless:,}** lines don't say whose they are - pull"
                         f" lists with `{EXPORT_COMMAND}` so every line names its owner")
        lines.append("\nNobody loses a character they hold here, and running this"
                     " again only adds what's new.")

        embed = discord.Embed(title="Mudae harem import",
                              description="\n".join(lines)[:4000],
                              colour=discord.Colour.blurple())
        if not sure and not guess:
            await ctx.send(embed=embed, allowed_mentions=QUIET)
            return
        view = ImportChoice(ctx.author.id, len(sure) + len(guess), len(sure))
        view.message = await ctx.send(embed=embed, view=view,
                                      allowed_mentions=QUIET)
        await view.wait()
        if view.choice is None:
            await ctx.send("Left alone. Nothing was imported.", allowed_mentions=QUIET)
            return
        chosen = sure + (guess if view.choice == "all" else [])
        added = db.import_marriages(gid, [(who.id, row["id"]) for who, _e, row in chosen])
        skipped = len(chosen) - added
        await ctx.send(
            f"{DONE_MARK} **{added:,}** characters into {whose}'s"
            f" {'harem' if len(members) == 1 else 'harems'}."
            + (f" {skipped:,} were claimed by someone in the meantime." if skipped else ""),
            allowed_mentions=QUIET)


async def setup(bot):
    await bot.add_cog(HaremImport(bot))
