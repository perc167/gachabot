"""Fills in image_url for every character in data/characters.json using the
public AniList GraphQL API.

    python tools/fetch_art.py --dry-run      # show what it would do, change nothing
    python tools/fetch_art.py                # fill in anything still missing
    python tools/fetch_art.py --series Naruto
    python tools/fetch_art.py --force        # also replace art already set

It refuses to guess: a match needs the series to line up AND the name to be
close, otherwise the character is reported as unmatched and left alone for you
to handle with $setimage. Wrong art is worse than no art.

Only stdlib, no extra packages. Polite by default - roughly 40 requests a
minute against AniList's 90/min limit, and it backs off when asked to.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

API = "https://graphql.anilist.co"

QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 25) {
    characters(search: $search) {
      id
      name { full native alternative }
      image { large }
      media(sort: POPULARITY_DESC, perPage: 10) {
        nodes { title { romaji english } }
      }
    }
  }
}
"""

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")

# How close a name has to be before we accept it, once the series matches.
NAME_THRESHOLD = 0.72

# Words that mean "someone related to X" rather than X. AniList files minor
# family members this way, which is how Sesshomaru first matched
# "Sesshomaru no Haha" - his mother.
RELATION_WORDS = {
    "haha", "chichi", "hahaue", "chichiue", "okaasan", "otousan",
    "ane", "imouto", "ani", "otouto", "musume", "musuko",
    "tsuma", "otto", "oba", "oji", "sofu", "sobo",
    "mother", "father", "sister", "brother", "daughter", "son",
    "wife", "husband", "mom", "dad", "grandmother", "grandfather",
}

# Honorifics that sit in front of a name. "Colonel Shikishima" is the same
# person as "Shikishima", and "Princess Hibana" the same as "Hibana".
TITLES = {
    "colonel", "captain", "commander", "general", "major", "sergeant",
    "princess", "prince", "queen", "lady", "lord", "sir", "dame",
    "doctor", "dr", "professor", "master", "mister", "mr", "mrs", "miss", "ms",
    "saint", "father", "sister", "chief", "officer", "detective",
}

# Characters AniList files under a different name than we do. Add to this when
# the run reports someone as unmatched.
ALIASES = {
    "Historia Reiss": ["Krista Lenz"],
    "Eto Yoshimura": ["Eto"],
    "Chi-Chi": ["Chichi"],
    "Obito Uchiha": ["Tobi"],  # AniList files him under his masked alias
    "Harlequin": ["King"],  # Seven Deadly Sins: renamed here to avoid a clash
    "Sesshomaru": ["Sesshoumaru"],
    "Bandou": ["Bando"],
    "Makina": ["Kiwako Flugel Makina", "Kiwako Makina"],
    "Chris": ["Eris"],  # KonoSuba: Chris is Eris in disguise
    "Nunnally vi Britannia": ["Nunnally Lamperouge"],
    "Lelouch vi Britannia": ["Lelouch Lamperouge"],
}


def normalise(text: str) -> str:
    """Lowercase, strip accents and punctuation, so 'Pokémon' == 'pokemon'
    and 'SPY x FAMILY' == 'Spy x Family'."""
    if not text:
        return ""
    text = text.replace("×", "x").replace("✕", "x")  # multiplication signs
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", text.lower())


def collapse_long_vowels(text: str) -> str:
    """AniList romanises long vowels as doubled letters: Gokuu, Tanjirou,
    Kyoujurou. Fold those down so they meet our spellings in the middle."""
    text = re.sub(r"ou", "o", text)
    text = re.sub(r"oh(?=[bcdfgjklmnpqrstvwxyz])", "o", text)
    text = re.sub(r"([aeiou])\1+", r"\1", text)
    return text


def name_token_list(name: str) -> list:
    """Words of a name in order, vowel-folded."""
    cleaned = unicodedata.normalize("NFKD", name or "")
    cleaned = "".join(c for c in cleaned if not unicodedata.combining(c))
    parts = re.split(r"[^A-Za-z0-9]+", cleaned.lower())
    return [collapse_long_vowels(p) for p in parts if p]


def name_tokens(name: str) -> frozenset:
    """Word set of a name, vowel-folded. Lets 'Son Goku' meet 'Gokuu Son',
    which AniList writes in the opposite order."""
    return frozenset(name_token_list(name))


def series_matches(wanted: str, titles) -> bool:
    """True if our series name and an AniList title are plausibly the same
    show. Substring either way, because 'Demon Slayer' lives inside
    'Demon Slayer: Kimetsu no Yaiba' and 'Naruto' inside 'Naruto Shippuden'."""
    want = normalise(wanted)
    if not want:
        return False
    for title in titles:
        have = normalise(title)
        if not have:
            continue
        if want in have or have in want:
            return True
    return False


def _pair_one(wanted: str, name: str) -> float:
    """Score one of our names against one AniList name."""
    want, have = normalise(wanted), normalise(name)
    if not have or not want:
        return 0.0
    if have == want:
        return 1.0

    want_folded, have_folded = collapse_long_vowels(want), collapse_long_vowels(have)
    want_tokens, have_tokens = name_tokens(wanted), name_tokens(name)

    # "Sesshomaru" is not "Sesshomaru no Haha". If one side adds a relation
    # word the other lacks, it names a relative, not the character.
    if (have_tokens - want_tokens) & RELATION_WORDS:
        return 0.0
    if (want_tokens - have_tokens) & RELATION_WORDS:
        return 0.0

    # Same words in either order: "Son Goku" == "Gokuu Son".
    if want_tokens and have_tokens == want_tokens:
        return 0.98
    # One name sits inside the other: "Edward Wong" within
    # "Edward Wong Hau Pepelu Tivrusky IV", or "Luffy Monkey" within
    # "Monkey D. Luffy".
    if want_tokens and (want_tokens <= have_tokens or have_tokens <= want_tokens):
        if len(want_tokens) == 1 or len(have_tokens) == 1:
            lone = want_tokens if len(want_tokens) == 1 else have_tokens
            longer = name_token_list(name if lone is want_tokens else wanted)
            word = next(iter(lone))
            # A lone GIVEN name is a safe short form: Zeke for Zeke Yeager.
            # A lone SURNAME is not - relatives share it, which is how Eto
            # Yoshimura ended up matched to her father, listed only as
            # "Yoshimura". Score it below the threshold so it is reported
            # rather than guessed.
            if len(longer) > 1 and word == longer[-1] and word != longer[0]:
                return 0.45
        return 0.88
    if have_folded == want_folded:
        return 0.95

    # Both names carry a distinctive word the other lacks. That is usually a
    # DIFFERENT PERSON who happens to share a surname - Levi vs Mikasa
    # Ackerman, Lelouch vs Rolo vi Britannia, Bond vs Loid Forger. A raw
    # string ratio rates those ~0.75 and would wave them through, so they are
    # rejected outright unless the odd words are variants of each other
    # (romanisation, spelling).
    only_want = want_tokens - have_tokens
    only_have = have_tokens - want_tokens
    if only_want and only_have:
        # The escape hatch is for spelling variants of the SAME word, so it
        # only accepts a shared prefix between two substantial words. Plain
        # "is one inside the other" was too generous: the particle "vi" hides
        # inside "Clovis", which let Lelouch vi Britannia match his brother.
        related = any(
            len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a))
            for a in only_want
            for b in only_have
        )
        if not related:
            return 0.0

    if want_folded in have_folded or have_folded in want_folded:
        return 0.85
    return difflib.SequenceMatcher(None, want_folded, have_folded).ratio()


def without_title(name: str) -> str:
    """Drop a leading honorific, if anything is left afterwards."""
    parts = re.split(r"([^A-Za-z0-9]+)", name or "")
    words = [p for p in parts if p.strip()]
    if len(words) > 1 and normalise(words[0]) in TITLES:
        return " ".join(words[1:])
    return ""


def _variants(name: str) -> list:
    """The name, plus a version with any honorific removed."""
    out = [name]
    stripped = without_title(name)
    if stripped:
        out.append(stripped)
    return out


def name_score(wanted, candidate_names) -> float:
    """Best similarity between our name (or any alias of it) and any name
    AniList knows the character by."""
    wanted_names = [wanted] if isinstance(wanted, str) else list(wanted)
    mine_all = [v for n in wanted_names for v in _variants(n)]
    theirs_all = [v for n in candidate_names for v in _variants(n)]
    best = 0.0
    for mine in mine_all:
        for theirs in theirs_all:
            best = max(best, _pair_one(mine, theirs))
            if best >= 1.0:
                return 1.0
    return best


def query_anilist(search: str, attempt: int = 0):
    """One search request, with backoff on rate limits and server errors."""
    body = json.dumps({"query": QUERY, "variables": {"search": search}}).encode()
    request = urllib.request.Request(
        API,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "gachabot-art-fetcher/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if "errors" in payload and not payload.get("data"):
            raise RuntimeError(payload["errors"])
        return payload["data"]["Page"]["characters"]
    except urllib.error.HTTPError as error:
        if error.code in (429, 500, 502, 503, 504) and attempt < 4:
            wait = int(error.headers.get("Retry-After") or 0) or (5 * (attempt + 1))
            print(f"    rate limited, waiting {wait}s...")
            time.sleep(wait)
            return query_anilist(search, attempt + 1)
        raise
    except (urllib.error.URLError, TimeoutError) as error:
        if attempt < 3:
            time.sleep(3 * (attempt + 1))
            return query_anilist(search, attempt + 1)
        raise RuntimeError(f"network: {error}")


def best_match(character, results):
    """Pick the candidate whose series lines up and whose name is closest."""
    best, best_score = None, 0.0
    for candidate in results:
        titles = []
        for node in (candidate.get("media") or {}).get("nodes") or []:
            title = node.get("title") or {}
            titles.extend([title.get("romaji"), title.get("english")])
        if not series_matches(character["series"], [t for t in titles if t]):
            continue

        names = [candidate["name"].get("full"), candidate["name"].get("native")]
        names.extend(candidate["name"].get("alternative") or [])
        wanted = [character["name"]] + ALIASES.get(character["name"], [])
        score = name_score(wanted, [n for n in names if n])
        if score > best_score:
            best, best_score = candidate, score

    if best and best_score >= NAME_THRESHOLD:
        return best, best_score
    return None, best_score


def search_terms(character):
    """What to type into AniList search, best guess first.

    The full name usually works. When it does not - often a romanisation
    difference like Tanjiro/Tanjirou - fall back to individual words, since
    searching 'Kamado' still finds him.
    """
    name = character["name"]
    terms = [name] + ALIASES.get(name, [])
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", name) if len(p) > 2]
    # Longest word first: family names are more distinctive than 'Son' or 'D.'
    for part in sorted(parts, key=len, reverse=True):
        if part.lower() != name.lower():
            terms.append(part)
    return terms[:4]


def find_match(character, delay: float):
    """Try each search term until one gives a confident match."""
    best, best_score, queries = None, 0.0, 0
    for index, term in enumerate(search_terms(character)):
        if index:
            time.sleep(delay)
        queries += 1
        results = query_anilist(term)
        match, score = best_match(character, results)
        best_score = max(best_score, score)
        if match:
            return match, score, queries
    return best, best_score, queries


def main():
    # Character names carry macrons and kana; the Windows console default
    # encoding cannot print them and would crash the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change, write nothing")
    parser.add_argument("--force", action="store_true",
                        help="also replace image_url values that are already set")
    parser.add_argument("--series", help="only characters whose series contains this")
    parser.add_argument("--limit", type=int, help="stop after this many lookups")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="seconds between requests (default 1.5)")
    args = parser.parse_args()

    with open(DATA, encoding="utf-8") as handle:
        characters = json.load(handle)

    targets = []
    for character in characters:
        if character.get("image_url") and not args.force:
            continue
        if args.series and normalise(args.series) not in normalise(character["series"]):
            continue
        targets.append(character)
    if args.limit:
        targets = targets[: args.limit]

    if not targets:
        print("Nothing to do - every selected character already has art.")
        return 0

    print(f"Looking up {len(targets)} of {len(characters)} characters on AniList")
    print(f"{'(dry run - nothing will be written)' if args.dry_run else ''}\n")

    filled, unmatched, errors = 0, [], []
    for index, character in enumerate(targets, 1):
        label = f"{character['name']} ({character['series']})"
        try:
            match, score, _ = find_match(character, args.delay)
        except Exception as error:  # network, API shape, anything
            errors.append((label, str(error)[:120]))
            print(f"  {index:>3}/{len(targets)} !! {label} - {str(error)[:60]}")
            continue

        if not match:
            unmatched.append((label, score))
            print(f"  {index:>3}/{len(targets)} -- {label} - no confident match"
                  f" (best {score:.2f})")
        else:
            url = (match.get("image") or {}).get("large") or ""
            if not url:
                unmatched.append((label, score))
                print(f"  {index:>3}/{len(targets)} -- {label} - matched but no image")
            else:
                character["image_url"] = url
                character["source"] = "AniList"
                character["anilist_id"] = match["id"]
                filled += 1
                print(f"  {index:>3}/{len(targets)} ok {label}"
                      f" -> {match['name']['full']} ({score:.2f})")

        if index < len(targets):
            time.sleep(args.delay)

    print(f"\nmatched {filled}   unmatched {len(unmatched)}   errors {len(errors)}")

    if unmatched:
        print("\nLeft alone - add these by hand with $setimage:")
        for label, score in unmatched:
            print(f"  {label}  (best score {score:.2f})")
    if errors:
        print("\nFailed outright - safe to re-run, it only touches what is missing:")
        for label, message in errors:
            print(f"  {label}  {message}")

    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0
    if not filled:
        print("\nNothing matched, file unchanged.")
        return 0

    backup = DATA + ".bak"
    with open(backup, "w", encoding="utf-8") as handle:
        json.dump(json.load(open(DATA, encoding="utf-8")), handle, indent=2,
                  ensure_ascii=False)
    with open(DATA, "w", encoding="utf-8") as handle:
        json.dump(characters, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"\nWrote {DATA}\nPrevious version kept at {backup}")
    print("Run $import in Discord to push the new art to the bot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
