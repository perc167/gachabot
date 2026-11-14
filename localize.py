"""localize.py - Paper's messages, put into the reader's language on the way out.

The code writes English everywhere, about a thousand send() calls of it, and
keeps doing so. Instead of wrapping every string in a t() call, this sits
between the bot and Discord: send, edit, interaction replies, follow-ups,
modals. It swaps each English line for the reader's language before the
message leaves.

The translations are looked up, never machine-made at run time:
  * locales/catalog.json is every line the code can say, collected from the
    source by tools/extract_strings.py. An f-string is one entry with its
    {expressions} numbered {0}, {1}..., so "Claimed {0}!" covers every name.
  * locales/strings/<code>.json maps each catalog line to its translation.
A line nobody has translated yet stays English, so the worst case is the
behaviour from before this file existed.

Which language: the person's own choice (/language) > the server's default
> the language their Discord app is set to (interactions carry it) > English.
Commands, names, numbers, mentions and `code` are never touched, so `$roll`
is `$roll` in every language.

Not covered: text drawn into images (rank/profile cards) and text people
wrote themselves (custom commands, greetings), which is theirs.
"""
import contextvars
import copy
import json
import logging
import re
import string
import zlib
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import MISSING

import i18n

log = logging.getLogger("gacha.localize")

LOCALES = Path(__file__).parent / "locales"
CATALOG = LOCALES / "catalog.json"
STRINGS = LOCALES / "strings"

# Paper reads these back off its own messages, so they must stay as written.
KEEP_PREFIXES = ("\U0001f48d Imported",)   # cogs/haremimport.DONE_MARK

FIELD = re.compile(r"(?<!\{)\{(\d+)\}(?!\})")
WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
CODE_BLOCK = re.compile(r"(```.*?```)", re.S)
PARAGRAPH = re.compile(r"(\n[ \t]*\n)")
# Emoji, bullets and markdown wrapped around a line that is otherwise known.
DECOR = (r"[\s*_~>|\u2022\u00b7\-\u2013\u2014\u2500-\u2bff\u2e00-\u2e7f"
         r"\u3000-\u303f\ufe0f\u200d\u20e3\U0001f000-\U0001ffff]*")
DECORATED = re.compile(rf"^({DECOR})(.*?)({DECOR})$", re.S)
# Bits of a line that are never words to translate, which a line is split on
# when nothing matches it whole: first code, mentions and links, then also
# markdown, brackets and separators.
_TOKENS = (r"`[^`\n]+`|<a?:\w+:\d+>|<[@#][!&]?\d+>|</[\w -]+:\d+>|<t:\d+(?::\w)?>"
           r"|https?://\S+")
COARSE = re.compile(f"({_TOKENS})")
PROTECTED = re.compile(
    rf"({_TOKENS}|\*\*|__|\|\||\s[\u00b7\u2022|\u2014\u2013-]\s|\s*[(\[]|[)\]]\s*)")

# Discord's limits, so a longer translation is cut rather than refused.
LIMITS = {"title": 256, "description": 4096, "name": 256, "value": 1024,
          "text": 2048, "label": 80, "placeholder": 150, "option": 100}
MESSAGE_EMBED_TOTAL = 6000

# value -> where in the English template it must sit to be glue, not data:
# a plural ending straight after a letter, or a verb between spaces.
_SUFFIX = r"[A-Za-z]\{%s\}"
_VERB = r"(^|\s)\{%s\}\s"
ENGLISH_GLUE = {"s": _SUFFIX, "es": _SUFFIX, "is": _VERB, "are": _VERB,
                "was": _VERB, "were": _VERB}

current = contextvars.ContextVar("paper_language", default=None)
_seen_locale = {}                  # user id -> language their Discord app uses
_sent = OrderedDict()              # message id -> language it was sent in


# ------------------------------------------------------------ the tables
def _unescape(text: str) -> str:
    return text.replace("{{", "{").replace("}}", "}")


def _fields(template: str) -> set:
    return set(FIELD.findall(template))


class Template:
    """One catalog line with fields, as a regex that pulls the values out."""
    __slots__ = ("english", "regex", "weight", "loose")

    def __init__(self, english: str):
        self.english = english
        pattern, seen = [], set()
        for literal, field, _spec, _conv in string.Formatter().parse(english):
            pattern.append(re.escape(literal))
            if field is not None:
                if field in seen:
                    pattern.append(f"(?P=f{field})")
                else:
                    seen.add(field)
                    pattern.append(f"(?P<f{field}>.+?)")
        self.regex = re.compile("".join(pattern), re.S)
        # More fixed text = more specific: "{0} claimed {1}!" beats "{0}!".
        self.weight = len(FIELD.sub("", english))
        # One fixed word ("{0} voice", "{0} characters") says too little to
        # be trusted with a value that is itself several words of prose.
        self.loose = len(re.findall(r"[^\W\d_]{2,}", FIELD.sub(" ", english))) < 2


@lru_cache(maxsize=1)
def _templates() -> dict:
    """Catalog lines with fields, filed under their longest word: a line can
    only match a template whose words it contains, so only those are tried."""
    try:
        catalog = json.loads(CATALOG.read_text("utf-8"))
    except (OSError, ValueError):
        log.warning("no %s - Paper will speak English only", CATALOG)
        return {}
    index = {}
    for english in catalog:
        if not FIELD.search(english):
            continue
        # A word glued to a field ("day{1}" -> "days") is not a whole word
        # of the line, so it can't file the template.
        words = [w for w in WORD.findall(_unescape(FIELD.sub("ʘ", english)).lower())
                 if "ʘ" not in w]
        if not words:
            continue
        index.setdefault(max(words, key=len), []).append(Template(english))
    for bucket in index.values():
        bucket.sort(key=lambda t: -t.weight)
    return index


@lru_cache(maxsize=None)
def _table(code: str):
    """(exact, by_template) for one language, or None if it has no file.
    A translation that lost or invented a {field} is dropped, not trusted."""
    path = STRINGS / f"{code}.json"
    if code == i18n.DEFAULT or not path.exists():
        return None
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        log.exception("could not read %s", path)
        return None
    exact, by_template, dropped = {}, {}, 0
    for english, done in data.items():
        if not isinstance(done, str) or not done.strip():
            continue
        if _fields(english) != _fields(done):
            dropped += 1
            continue
        if _fields(english):
            by_template[english] = done
        else:
            exact[_unescape(english)] = _unescape(done)
    if dropped:
        log.warning("%s: dropped %d translations with broken {fields}", code, dropped)
    return exact, by_template


def version() -> bytes:
    """Changes whenever a translation does, so the slash commands re-sync."""
    crc = 0
    for path in sorted(STRINGS.glob("*.json")):
        crc = zlib.crc32(path.read_bytes(), crc)
    return str(crc).encode()


# -------------------------------------------------------- translating text
def _exact(text: str, table):
    exact = table[0]
    found = exact.get(text)
    if found is not None:
        return found
    # help's group listing strips the full stop off a command's first line.
    if text[-1:] not in ".!?:" and text + "." in exact:
        return exact[text + "."].rstrip(".\u3002\u0964")
    return None


def _template(text: str, table, depth: int):
    """`text` as a known line with values in it, or None."""
    by_template = table[1]
    candidates = []
    for word in set(WORD.findall(text.lower())):
        candidates += _templates().get(word, ())
    for template in sorted(candidates, key=lambda t: -t.weight):
        done = by_template.get(template.english)
        if done is None:
            continue
        match = template.regex.fullmatch(text)
        if not match:
            continue
        values = {k[1:]: v for k, v in match.groupdict().items()}
        if template.loose and any(len(re.findall(r"[^\W\d_]{2,}", v)) >= 2
                                  for v in values.values()):
            continue
        for k, v in values.items():
            # English grammar the code fills in itself - the "s" of
            # "day{1}", the "is" of "There {0} only..." - means nothing in
            # another language, whose translation already says it.
            if v in ENGLISH_GLUE and re.search(ENGLISH_GLUE[v] % k, template.english):
                values[k] = ""
        if depth < 2:   # a value can itself be a known line ("harems")
            values = {k: (_line(v, table, depth + 1) if LETTER.search(v) else v)
                      for k, v in values.items()}
        try:
            return done.format(*[values[str(i)] for i in range(len(values))])
        except (IndexError, KeyError, ValueError):
            return None
    return None


def _line(text: str, table, depth: int = 0) -> str:
    """One line, with its edges (spaces, emoji, markdown) kept as they were."""
    core = text.strip()
    if not core or not LETTER.search(core) or core.startswith(KEEP_PREFIXES):
        return text
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    edges = DECORATED.match(core)
    inner = edges.group(2) if edges and edges.group(2) != core else ""
    # Every exact match before any template: a loose template ("{0}
    # characters") would otherwise swallow the emoji of "✨ Your own characters".
    def wrapped(found):
        return None if found is None else edges.group(1) + found + edges.group(3)

    done = _exact(core, table)
    if done is None and inner:
        done = wrapped(_exact(inner, table))
    if done is None:
        done = _template(core, table, depth)
    if done is None and inner:
        done = wrapped(_template(inner, table, depth))
    if done is None and depth == 0:
        # "`$cmd` what it does": the description whole, `code` in it and all.
        lead_code = re.match(r"(`[^`\n]+`\s*(?:[·—-]\s*)?)(.+)", core, re.S)
        if lead_code:
            rest = _line(lead_code.group(2), table, 1)
            if rest != lead_code.group(2):
                done = lead_code.group(1) + rest
    if done is None and depth == 0:
        done = _pieces(core, table, COARSE)
    return text if done is None else lead + done + trail


def _pieces(core: str, table, splitter):
    """Several strings glued together: translate the pieces between the code
    and mentions that hold them together, and failing that between the
    markdown, brackets and separators too. None if nothing changed."""
    pieces = splitter.split(core)
    changed = False
    for i in range(0, len(pieces), 2):
        if LETTER.search(pieces[i]):
            found = _line(pieces[i], table, 1)
            if found == pieces[i] and splitter is COARSE:
                found = _pieces(pieces[i], table, PROTECTED) or found
            changed |= found != pieces[i]
            pieces[i] = found
    return "".join(pieces) if changed else None


@lru_cache(maxsize=8192)
def _text(text: str, code: str) -> str:
    table = _table(code)
    if table is None:
        return text
    out = []
    for i, chunk in enumerate(CODE_BLOCK.split(text)):
        if i % 2:                       # ```code``` stays as it is
            out.append(chunk)
            continue
        for j, para in enumerate(PARAGRAPH.split(chunk)):
            if j % 2 or not para:
                out.append(para)
                continue
            # A command's help paragraph is stored reflowed onto one line.
            core = para.strip()
            if "\n" in core:
                joined = " ".join(r.strip() for r in core.splitlines())
                if joined in table[0]:
                    lead = para[:len(para) - len(para.lstrip())]
                    out.append(lead + table[0][joined] + para[len(para.rstrip()):])
                    continue
            out.append("\n".join(_line(row, table) for row in para.split("\n")))
    return "".join(out)


def text(value, code: str):
    """`value` in language `code`; anything that isn't text comes back as is."""
    if not isinstance(value, str) or not value or code in (None, i18n.DEFAULT):
        return value
    return _text(value, code)


def _cut(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit - 1] + "\u2026"


def embed(original: discord.Embed, code: str) -> discord.Embed:
    """A translated copy; the original is left alone, since code reuses them."""
    if code in (None, i18n.DEFAULT) or not isinstance(original, discord.Embed):
        return original
    # Deep: to_dict() shares its field/footer dicts with the original.
    data = copy.deepcopy(original.to_dict())

    def swap(holder, key, limit):
        if holder.get(key):
            holder[key] = _cut(text(holder[key], code), limit)

    swap(data, "title", LIMITS["title"])
    swap(data, "description", LIMITS["description"])
    for part, key in (("footer", "text"), ("author", "name")):
        if part in data:
            swap(data[part], key, LIMITS["text"] if key == "text" else LIMITS["name"])
    for field in data.get("fields", ()):
        swap(field, "name", LIMITS["name"])
        swap(field, "value", LIMITS["value"])
    return discord.Embed.from_dict(data)


def _items(container):
    """Every component in a view or modal, rows and containers included."""
    for item in getattr(container, "children", ()):
        yield item
        yield from _items(item)


def _swap_components(container, code: str):
    """Translate a view's or modal's labels in place; returns the undo.

    In place because discord.py reads them off the very objects at send
    time, and undone straight after because those objects live on (a
    paginator re-sends itself) and may be shown to someone else next."""
    saved = []

    def swap(obj, attr, limit):
        old = getattr(obj, attr, None)
        if isinstance(old, str) and old:
            new = _cut(text(old, code), limit)
            if new != old:
                try:
                    setattr(obj, attr, new)
                    saved.append((obj, attr, old))
                except (AttributeError, TypeError, ValueError):
                    pass

    if container is None or container is MISSING or code in (None, i18n.DEFAULT):
        return lambda: None
    if isinstance(container, discord.ui.Modal):
        swap(container, "title", 45)
    for item in _items(container):
        swap(item, "label", LIMITS["label"] if isinstance(item, discord.ui.Button) else 45)
        swap(item, "placeholder", LIMITS["placeholder"])
        swap(item, "content", 4000)         # text displays in newer layouts
        for option in getattr(item, "options", None) or ():
            if isinstance(option, discord.SelectOption):
                swap(option, "label", LIMITS["option"])
                swap(option, "description", LIMITS["option"])

    def undo():
        for obj, attr, old in reversed(saved):
            try:
                setattr(obj, attr, old)
            except (AttributeError, TypeError, ValueError):
                pass
    return undo


def _payload(code: str, kwargs: dict):
    """Translate send/edit keyword arguments in place; returns the undo."""
    if "content" in kwargs:
        kwargs["content"] = text(kwargs["content"], code)
    one = kwargs.get("embed")
    many = kwargs.get("embeds")
    new_one = embed(one, code) if isinstance(one, discord.Embed) else one
    new_many = [embed(e, code) for e in many] if isinstance(many, list) else many
    total = sum(len(e) for e in ([new_one] if isinstance(new_one, discord.Embed) else [])
                + (new_many if isinstance(new_many, list) else []))
    if total <= MESSAGE_EMBED_TOTAL:    # too long translated: English beats refused
        if "embed" in kwargs:
            kwargs["embed"] = new_one
        if "embeds" in kwargs:
            kwargs["embeds"] = new_many
    else:
        log.warning("translation to %s too long for one message; sent in English", code)
    return _swap_components(kwargs.get("view"), code)


# --------------------------------------------------------- whose language
def from_locale(locale) -> str:
    """A Discord app language ("es-ES", "pt-BR", "zh-TW") as one of ours."""
    value = str(getattr(locale, "value", locale) or "").lower()
    if not value:
        return None
    if value in i18n.LANGUAGES:
        return value
    base = value.split("-")[0]
    return base if base in i18n.LANGUAGES else None


def language_for(user=None, guild=None, locale=None) -> str:
    if i18n._db is None:
        return i18n.DEFAULT
    try:
        own = user is not None and i18n.get_user_lang(user.id)
        server = guild is not None and i18n.get_guild_lang(guild.id)
    except Exception:  # noqa: BLE001 - a language lookup must never stop a reply
        log.exception("language lookup failed")
        return i18n.DEFAULT
    app = from_locale(locale) or (user is not None and _seen_locale.get(user.id))
    return own or server or app or i18n.DEFAULT


def for_interaction(interaction) -> str:
    seen = from_locale(getattr(interaction, "locale", None))
    if seen and interaction.user is not None:
        _seen_locale[interaction.user.id] = seen
    code = language_for(interaction.user, interaction.guild, seen)
    current.set(code)
    return code


def for_context(ctx) -> str:
    """The language for a commands.Context (what i18n.lang_of does, plus the
    app language an interaction-backed context carries)."""
    if getattr(ctx, "interaction", None) is not None:
        return for_interaction(ctx.interaction)
    code = language_for(getattr(ctx, "author", None), getattr(ctx, "guild", None))
    current.set(code)
    return code


def _for_target(target) -> str:
    if isinstance(target, commands.Context):
        return for_context(target)
    if isinstance(target, (discord.User, discord.Member)):
        own = i18n._db is not None and i18n.get_user_lang(target.id)
        return own or current.get() or language_for(target, getattr(target, "guild", None))
    if current.get():
        return current.get()
    if isinstance(target, discord.DMChannel):
        return language_for(target.recipient)
    return language_for(None, getattr(target, "guild", None))


def _remember(message, code):
    if message is not None and getattr(message, "id", None):
        _sent[message.id] = code
        while len(_sent) > 5000:
            _sent.popitem(last=False)


# ----------------------------------------------------------- the patches
def _wrap_send(original):
    async def send(self, content=None, **kwargs):
        code = _for_target(self)
        if code == i18n.DEFAULT:
            return await original(self, content, **kwargs)
        kwargs["content"] = content
        undo = _payload(code, kwargs)
        try:
            message = await original(self, kwargs.pop("content"), **kwargs)
        finally:
            undo()
        _remember(message, code)
        return message
    return send


def _wrap_kwargs(original, language):
    """For methods that take everything by keyword (edits, replies)."""
    async def method(self, *args, **kwargs):
        code = language(self)
        if code == i18n.DEFAULT:
            return await original(self, *args, **kwargs)
        if args and isinstance(args[0], str) and "content" not in kwargs:
            kwargs["content"], args = args[0], args[1:]
        undo = _payload(code, kwargs)
        try:
            result = await original(self, *args, **kwargs)
        finally:
            undo()
        _remember(result, code)
        return result
    return method


def _wrap_modal(original):
    async def send_modal(self, modal, /):
        undo = _swap_components(modal, for_interaction(self._parent))
        try:
            return await original(self, modal)
        finally:
            undo()
    return send_modal


def _wrap_defer(original):
    async def defer(self, *args, **kwargs):
        for_interaction(self._parent)   # so the follow-ups know the language
        return await original(self, *args, **kwargs)
    return defer


def _message_language(message) -> str:
    return (current.get() or _sent.get(message.id)
            or language_for(None, getattr(message, "guild", None)))


_installed = False


def patch() -> None:
    """Route every way Paper speaks through the translator. Idempotent."""
    global _installed
    if _installed:
        return
    _installed = True
    discord.abc.Messageable.send = _wrap_send(discord.abc.Messageable.send)
    response = discord.InteractionResponse
    by_interaction = lambda r: for_interaction(r._parent)  # noqa: E731
    response.send_message = _wrap_kwargs(response.send_message, by_interaction)
    response.edit_message = _wrap_kwargs(response.edit_message, by_interaction)
    response.send_modal = _wrap_modal(response.send_modal)
    response.defer = _wrap_defer(response.defer)
    discord.Interaction.edit_original_response = _wrap_kwargs(
        discord.Interaction.edit_original_response, for_interaction)
    by_task = lambda _w: current.get() or i18n.DEFAULT  # noqa: E731
    discord.Webhook.send = _wrap_kwargs(discord.Webhook.send, by_task)
    discord.Webhook.edit_message = _wrap_kwargs(discord.Webhook.edit_message, by_task)
    discord.Message.edit = _wrap_kwargs(discord.Message.edit, _message_language)


# ------------------------------------------------------- slash commands
class SlashTranslator(app_commands.Translator):
    """Descriptions in the command picker, in the language of the app.
    Command and option names stay English, the same as the $ commands."""

    def __init__(self, bot):
        super().__init__()
        self.bot = bot

    async def translate(self, string, locale, context):
        code = from_locale(locale)
        if code in (None, i18n.DEFAULT) or _table(code) is None:
            return None
        where = context.location
        source = string.message
        if where is app_commands.TranslationContextLocation.command_description:
            # The slash text is the $ command's help with the `code` marks
            # stripped, so translate the help itself and strip it the same way.
            name = getattr(context.data, "extras", {}).get("prefix_command")
            command = self.bot.get_command(name) if name else None
            if command is not None and command.help:
                from cogs.slash import describe  # late: that cog imports this
                paragraph = re.split(r"\n\s*\n", command.help.strip())[0]
                joined = " ".join(r.strip() for r in paragraph.splitlines())
                done = text(joined, code)
                if done != joined:
                    return describe(SimpleNamespace(
                        help=done, short_doc="", qualified_name=command.qualified_name))
        elif where not in (app_commands.TranslationContextLocation.group_description,
                           app_commands.TranslationContextLocation.parameter_description,
                           app_commands.TranslationContextLocation.choice_name):
            return None
        done = text(source, code)
        return _cut(done, 100) if done != source else None


async def install(bot) -> None:
    patch()
    await bot.tree.set_translator(SlashTranslator(bot))

    # A prefix command's language is known before it says anything, so a
    # channel.send() inside it (not ctx.send) is in the right language too.
    @bot.before_invoke
    async def _language_first(ctx):
        for_context(ctx)
