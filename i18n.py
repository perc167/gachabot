"""i18n.py - Paper's own messages, in the player's language.

Not to be confused with translator.py, which translates text people type
into $translate. This is for the bot's own words: embeds, buttons, errors.

Goes next to db.py (top level), so any cog can `import i18n`.

No schema change needed. It reuses player_prefs, the way character_aliases
uses user_id 0 for "the server's own":
    a player's language  -> player_prefs (guild_id 0, user_id, "language")
    a server's default   -> player_prefs (guild_id,   user_id 0, "language")

Order of choice: the player's own > the server's default > English.
"""
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("gacha.i18n")

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT = "en"
KEY = "language"

# Native names. The first PICKER_SIZE go in the dropdown (Discord allows 25
# options and one is kept for "More languages"); the rest are reachable only
# through /language autocomplete. A language with no locale file falls back
# to English message by message, so adding one here is always safe.
LANGUAGES = {
    "en": "English", "es": "Español", "pt": "Português (BR)", "fr": "Français",
    "de": "Deutsch", "it": "Italiano", "fil": "Filipino", "id": "Bahasa Indonesia",
    "vi": "Tiếng Việt", "th": "ไทย", "ja": "日本語", "ko": "한국어",
    "zh": "简体中文", "zh-tw": "繁體中文", "ru": "Русский", "tr": "Türkçe",
    "ar": "العربية", "hi": "हिन्दी", "pl": "Polski", "nl": "Nederlands",
    "uk": "Українська", "ms": "Bahasa Melayu", "ro": "Română",
    # autocomplete only:
    "sv": "Svenska", "el": "Ελληνικά", "he": "עברית", "fa": "فارسی",
    "bn": "বাংলা", "cs": "Čeština", "hu": "Magyar",
}
PICKER_SIZE = 23

_db = None
_cache: dict = {}


def init(database) -> None:
    """Hand it the shared Database once, from the cog's setup()."""
    global _db
    _db = database


# ---------------------------------------------------------------- choosing
def get_user_lang(user_id: int) -> Optional[str]:
    code = _db.get_player_pref(0, user_id, KEY)
    return code if code in LANGUAGES else None


def set_user_lang(user_id: int, code: str) -> None:
    _db.set_player_pref(0, user_id, KEY, code)


def get_guild_lang(guild_id: int) -> Optional[str]:
    code = _db.get_player_pref(guild_id, 0, KEY)
    return code if code in LANGUAGES else None


def set_guild_lang(guild_id: int, code: str) -> None:
    _db.set_player_pref(guild_id, 0, KEY, code)


def resolve_language(user_id: int, guild_id: Optional[int] = None) -> str:
    return (get_user_lang(user_id)
            or (guild_id and get_guild_lang(guild_id))
            or DEFAULT)


def lang_of(source) -> str:
    """The language for a commands.Context or a discord.Interaction."""
    user = getattr(source, "author", None) or getattr(source, "user", None)
    guild = getattr(source, "guild", None)
    return resolve_language(user.id, guild.id if guild else None)


# ------------------------------------------------------------- translating
def _load(code: str) -> dict:
    if code not in _cache:
        path = LOCALES_DIR / f"{code}.json"
        try:
            _cache[code] = json.loads(path.read_text("utf-8")) if path.exists() else {}
        except (OSError, ValueError):
            log.exception("could not read %s", path)
            _cache[code] = {}
    return _cache[code]


def t(code: str, key: str, **kwargs) -> str:
    """The message `key` in `code`; English if it is missing; the key if not
    even English has it, so a typo shows up on screen instead of crashing."""
    text = _load(code).get(key) or _load(DEFAULT).get(key) or key
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text
