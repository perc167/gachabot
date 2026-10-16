"""Working out what language something is in, and putting it into another.

The translator is MyMemory, which is free, public and documented, and wants
no key. What it will not do is work out the source language for itself - it
answers "PLEASE SELECT TWO DISTINCT LANGUAGES" and nothing else - so that
part is done here.

Two passes, because the two cases are not alike. Anything not written in the
Latin alphabet gives itself away by its letters: Arabic, Greek, Hebrew, the
kana, Hangul, Cyrillic and the rest each sit in their own block, and one
look at the characters is enough. Languages that do share our alphabet need
the words looked at, so a short list of the ones each uses constantly is
scored against the text.

It is a guess and it says so. `$translate es ...` names the language
outright for when the guess is wrong, which it will be on three words of
something that could be Spanish or Portuguese.
"""
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.mymemory.translated.net/get"
UA = {"User-Agent": "PaperBot/1.0 (Discord bot translate command)"}
LONGEST = 480          # MyMemory takes 500 bytes a go; leave room for escapes

# What the letters alone can settle.
BY_SCRIPT = (
    ("ARABIC", "ar"), ("HEBREW", "he"), ("CYRILLIC", "ru"), ("GREEK", "el"),
    ("THAI", "th"), ("HANGUL", "ko"), ("HIRAGANA", "ja"), ("KATAKANA", "ja"),
    ("DEVANAGARI", "hi"), ("BENGALI", "bn"), ("TAMIL", "ta"),
    ("TELUGU", "te"), ("GEORGIAN", "ka"), ("ARMENIAN", "hy"),
    ("ETHIOPIC", "am"), ("KHMER", "km"), ("LAO", "lo"), ("MYANMAR", "my"),
    ("SINHALA", "si"), ("CJK", "zh"),
)

# And for the alphabet we share, the words each language cannot do without.
BY_WORD = {
    "es": "el la los las de que y en un una por con para no es se su del al"
          " como pero más este esta muy qué sí hola gracias porque",
    "fr": "le la les des de que et en un une pour avec pas est ce cette qui"
          " dans sur plus mais vous je tu nous bonjour merci parce",
    # Longer than the others on purpose. German shares "es" with Spanish and
    # "die" with nothing useful, so on a short sentence it lost to Spanish on
    # one word. The way out is more of the words it cannot write without.
    "de": "der die das den dem und ist nicht ein eine mit für auf von zu"
          " sich auch aber wie ich du wir sie hallo danke weil geht guten"
          " dir mir mich dich euch ihr sehr gut bitte noch schon war hat"
          " wird kann muss heute morgen was wer wo warum nein",
    "pt": "o a os as de que e em um uma por com para não é se do da no na"
          " mais mas muito você eu olá obrigado porque",
    "it": "il lo la i gli le di che e in un una per con non è si del della"
          " più ma molto io tu noi ciao grazie perché",
    "nl": "de het een en van is dat niet op met voor zijn je ik we maar ook"
          " deze die hoe hallo dank omdat",
    "pl": "nie tak jest to w na z do się że i co jak ale bardzo dla przez"
          " jestem cześć dzięki ponieważ",
    "tr": "bir ve bu için ile de da ne var yok çok ama gibi daha sen ben biz"
          " değil evet hayır merhaba teşekkür çünkü",
    "sv": "och att det som en är på av för med inte den har jag du vi men"
          " mycket hej tack eftersom",
    "id": "yang dan di ke dari untuk dengan tidak ini itu adalah saya kamu"
          " kami apa bagaimana halo terima kasih karena",
    "vi": "của và là không có được cho với những này một người trong tôi bạn"
          " chúng rất xin chào cảm ơn vì",
    "en": "the and is are to of in that it you for with not this but have"
          " was on at as be hello thanks because",
}
WORDS = {code: set(words.split()) for code, words in BY_WORD.items()}

NAMES = {
    "ar": "Arabic", "he": "Hebrew", "ru": "Russian", "el": "Greek",
    "th": "Thai", "ko": "Korean", "ja": "Japanese", "hi": "Hindi",
    "bn": "Bengali", "ta": "Tamil", "te": "Telugu", "ka": "Georgian",
    "hy": "Armenian", "am": "Amharic", "km": "Khmer", "lo": "Lao",
    "my": "Burmese", "si": "Sinhala", "zh": "Chinese", "es": "Spanish",
    "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "sv": "Swedish",
    "id": "Indonesian", "vi": "Vietnamese", "en": "English",
    "ja-JP": "Japanese", "uk": "Ukrainian", "ro": "Romanian",
    "cs": "Czech", "da": "Danish", "fi": "Finnish", "no": "Norwegian",
    "hu": "Hungarian", "bg": "Bulgarian", "ms": "Malay", "fa": "Persian",
    "ur": "Urdu", "sw": "Swahili", "tl": "Filipino",
}

WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def name_of(code: str) -> str:
    return NAMES.get((code or "").lower(), (code or "?").upper())


def code_for(word: str):
    """A language code from "es" or from "spanish", or None if it is neither.

    So `$translate es hello` and `$translate spanish hello` both work, and
    `$translate hello` is not mistaken for a request to translate nothing
    into Hello.
    """
    word = (word or "").strip().lower().strip(".,")
    if not word:
        return None
    if word in NAMES:
        return word
    for code, full in NAMES.items():
        if full.lower() == word:
            return code
    return None


def by_letters(text: str):
    """The language its alphabet gives away, or None if it is ours."""
    seen = {}
    for letter in text:
        if not letter.isalpha():
            continue
        try:
            block = unicodedata.name(letter)
        except ValueError:
            continue
        for marker, code in BY_SCRIPT:
            if marker in block:
                seen[code] = seen.get(code, 0) + 1
                break
    if not seen:
        return None
    # Japanese writes kanji among its kana, so any kana at all settles it.
    if "ja" in seen and "zh" in seen:
        seen["ja"] += seen.pop("zh")
    return max(seen, key=seen.get)


def by_words(text: str) -> str:
    """The best guess among the languages that share our alphabet."""
    words = [w.lower() for w in WORD.findall(text)]
    if not words:
        return "en"
    scores = {code: sum(1 for w in words if w in common)
              for code, common in WORDS.items()}
    best = max(scores, key=scores.get)
    # Nothing matched anything: say English rather than invent a language.
    return best if scores[best] else "en"


def detect(text: str) -> str:
    return by_letters(text) or by_words(text)


def fetch(url: str, timeout: int = 15) -> str:
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def translate(text: str, into: str = "en", source: str = None) -> tuple:
    """(the translation, the language it came from, what went wrong).

    Blocking on purpose: the caller hands it to a thread, the way the rest
    of the bot's outward calls are done.
    """
    text = (text or "").strip()
    if not text:
        return ("", "", "there was nothing to translate")
    if len(text) > LONGEST:
        text = text[:LONGEST]
    came_from = (source or detect(text)).lower()
    into = (into or "en").lower()
    if came_from == into:
        return ("", came_from, f"that is already {name_of(into)}")

    query = urllib.parse.urlencode({
        "q": text, "langpair": f"{came_from}|{into}"})
    try:
        body = json.loads(fetch(f"{API}?{query}"))
    except (urllib.error.URLError, OSError, ValueError):
        return ("", came_from, "the translator did not answer")

    if str(body.get("responseStatus")) != "200":
        detail = (body.get("responseDetails") or "").strip()
        return ("", came_from, detail or "the translator refused that")
    done = (body.get("responseData") or {}).get("translatedText") or ""
    if not done.strip():
        return ("", came_from, "the translator sent nothing back")
    return (done, came_from, "")
