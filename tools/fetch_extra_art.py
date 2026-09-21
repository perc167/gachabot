"""Collects extra pictures for the roster, so a character is not one image.

    python tools/fetch_extra_art.py --top 5000
    python tools/fetch_extra_art.py --top 20000 --resume

AniList gives exactly one picture per character - that is what
tools/fetch_art.py collects - which is why every card in the bot looks the
same every time. This is the other half: the rest of the album. Safebooru has many, is all-ages only, and
answers an unauthenticated API, so that is where the rest come from. The
result is data/character_art.json, a map of AniList id to extra image URLs,
merged into the roster when the bot loads it.

Two things make the matching honest rather than hopeful:

Name order is guessed both ways and the bigger result wins. Boorus write
Japanese names surname first, and AniList is inconsistent about it - "Satoru
Gojou" is given-first and needs reversing, "Hatsune Miku" is already
surname-first and reversing it finds a junk tag with two posts on it. Taking
whichever order returns more posts settles that without a list of exceptions.

The series has to appear in the tags. Plenty of characters share a name, and
a tag that matches the name but nothing of the series is somebody else.

Every page is fetched at one request a second. The run is resumable, so a
long sweep can be stopped and picked up rather than started again.
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROSTER = os.path.join(ROOT, "data", "characters.json")
OUT = os.path.join(ROOT, "data", "character_art.json")

# Keys are name and series joined by a unit separator, because that pair is
# what the characters table is unique on. Keying by AniList id would read
# nicely and then force the bot to load the 28MB roster on every boot just to
# translate ids back into the rows it already has.
KEY_SEP = "\x1f"

API = "https://safebooru.org/index.php?page=dapi&s=post&q=index&json=1"
TAG_API = "https://safebooru.org/index.php?page=dapi&s=tag&q=index"
UA = {"User-Agent": "gachabot-art/1.0 (roster art for a Discord bot)"}

# One request a second. Safebooru asks for politeness rather than publishing a
# number, and a bot that is about to make tens of thousands of calls should
# err well under whatever the real limit is.
DELAY = 1.0

# How many to keep per character. Past a handful the album is a chore to flip
# through and every extra row is roster file that ships with the bot.
PER_CHARACTER = 8

# How many to ask for. Larger than PER_CHARACTER because some are dropped:
# wrong series, duplicates, formats Discord will not embed.
FETCH = 30

EMBEDDABLE = (".jpg", ".jpeg", ".png", ".gif", ".webp")

# Tag-index paging. The index ignores orderby, so the only way to see the
# popular tag is to take a wide page and sort it here - the first dozen rows
# for "emilia" are all tags with one or two posts on them.
TAG_PAGE = 100

# Pictures of a person dressed as the character, which is not a picture of
# the character.
NOT_THE_CHARACTER = ("_(cosplay)", "_(doll)", "_(figure)", "_plush")

# When the series cannot confirm a tag - the booru files it under the
# Japanese title and the roster carries the English one - a tag is accepted
# only if it is both substantial and the obvious one of its name.
MIN_POSTS = 40
DOMINANCE = 3

# Tokens too common to prove a series matched. "no" and "the" would confirm
# almost anything, and a one-word series like "Monster" is better skipped than
# matched on a word that appears in thousands of unrelated tags.
STOPWORDS = {
    "the", "and", "not", "season", "movie", "part", "final", "new", "next",
    "story", "wo", "no", "ga", "ni", "wa", "de", "to", "kara", "made",
    "anime", "manga", "series", "tv", "ova", "special", "specials",
}


def slug(text: str) -> str:
    """A booru-shaped tag: lowercase, underscores, nothing exotic."""
    text = re.sub(r"[^\w\s-]", " ", (text or "").lower())
    return "_".join(text.split())


def name_tags(name: str) -> list:
    """Candidate tags for a character name, both name orders."""
    parts = [p for p in re.split(r"\s+", slug(name).replace("_", " ")) if p]
    if not parts:
        return []
    if len(parts) == 1:
        return parts
    forward = "_".join(parts)
    reverse = "_".join(reversed(parts))
    return [forward, reverse] if forward != reverse else [forward]


def series_tokens(series: str) -> set:
    """The words that would prove a post belongs to this series."""
    words = [w for w in slug(series).split("_") if len(w) >= 4]
    return {w for w in words if w not in STOPWORDS}


def fetch(tag: str, limit: int, tries: int = 3):
    """One page of posts for a tag, or [] if the tag has none."""
    url = f"{API}&limit={limit}&tags=" + urllib.parse.quote(f"{tag} rating:safe")
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", "replace")
            if not body.strip():
                return []
            found = json.loads(body)
            return found if isinstance(found, list) else []
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError,
                ConnectionError, OSError):
            if attempt == tries - 1:
                return []
            time.sleep(2 ** attempt)
    return []


def index_tags(pattern: str) -> list:
    """(count, tag) for tags matching a LIKE pattern, biggest first."""
    url = f"{TAG_API}&limit={TAG_PAGE}&name_pattern=" + urllib.parse.quote(pattern)
    try:
        request = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return []

    found = []
    for element in re.finditer(r"<tag\b[^>]*>", body):
        text = element.group(0)
        name = re.search(r'name="([^"]*)"', text)
        count = re.search(r'count="(\d+)"', text)
        if name and count:
            found.append((int(count.group(1)), name.group(1)))
    return sorted(found, reverse=True)


def resolve_tag(name: str, series: str) -> str:
    """The booru's own tag for this character, or "".

    Boorus disambiguate a shared name by appending the series - makima is
    makima_(chainsaw_man) - so a plain name search finds nothing at all for
    exactly the characters most likely to have art. This asks the tag index
    what it actually calls them.
    """
    wanted = series_tokens(series)
    candidates = []
    for base in name_tags(name):
        for count, tag in index_tags(base + "%"):
            time.sleep(0)  # the sleep belongs to the caller, one per request
            if tag != base and not tag.startswith(base + "_("):
                continue
            if tag.endswith(NOT_THE_CHARACTER):
                continue
            candidates.append((count, tag))
        time.sleep(DELAY)

    if not candidates:
        return ""
    candidates.sort(reverse=True)

    # A tag whose parenthetical names the series is the answer outright.
    for count, tag in candidates:
        inside = tag[tag.find("(") + 1:tag.rfind(")")] if "(" in tag else ""
        if inside and any(token in inside for token in wanted):
            return tag

    # Otherwise the booru files the series under a title the roster does not
    # have. Take the top tag only when it is big and clearly the one meant.
    top_count, top_tag = candidates[0]
    runner_up = candidates[1][0] if len(candidates) > 1 else 0
    if top_count >= MIN_POSTS and top_count >= max(1, runner_up) * DOMINANCE:
        return top_tag
    return ""


def usable(post) -> str:
    """The image URL, if Discord will actually render it."""
    url = post.get("file_url") or ""
    if not url and post.get("directory") and post.get("image"):
        url = f"https://safebooru.org/images/{post['directory']}/{post['image']}"
    if not url.lower().endswith(EMBEDDABLE):
        return ""
    return url


def art_for(name: str, series: str, want: int) -> tuple:
    """Extra images for one character: (urls, the tag they came from)."""
    wanted = series_tokens(series)
    best, best_tag = [], ""

    for tag in name_tags(name):
        posts = fetch(tag, FETCH)
        time.sleep(DELAY)
        if not posts:
            continue

        # The series has to show up somewhere in the tags, or this is a
        # different person who happens to share a name.
        if wanted:
            tagged = set()
            for post in posts:
                tagged.update(post.get("tags", "").split())
            blob = " ".join(tagged)
            if not any(token in blob for token in wanted):
                continue

        if len(posts) > len(best):
            best, best_tag = posts, tag

    # Nothing under the plain name. Ask the index what the booru calls them.
    if not best:
        tag = resolve_tag(name, series)
        if tag:
            best, best_tag = fetch(tag, FETCH), tag
            time.sleep(DELAY)

    urls = []
    for post in sorted(best, key=lambda p: -int(p.get("score") or 0)):
        url = usable(post)
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= want:
            break
    return urls, best_tag


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=2000,
                        help="how many characters, by claim_rank")
    parser.add_argument("--per-character", type=int, default=PER_CHARACTER)
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--resume", action="store_true",
                        help="keep what is already in the output and skip it")
    parser.add_argument("--every", type=int, default=25,
                        help="save and report every N characters")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    sys.path.insert(0, ROOT)
    import utils

    rows = list(utils.iter_roster(ROSTER))
    rows.sort(key=lambda r: r.get("claim_rank") or 10 ** 9)
    rows = rows[:args.top]

    art = {}
    if args.resume and os.path.exists(args.out):
        with io.open(args.out, encoding="utf-8") as handle:
            art = json.load(handle)
        print(f"resuming: {len(art):,} characters already done")

    def save():
        tmp = args.out + ".tmp"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(art, handle, ensure_ascii=False)
        os.replace(tmp, args.out)

    def key(row):
        return row["name"] + KEY_SEP + (row.get("series") or "")

    todo = [r for r in rows if key(r) not in art]
    print(f"{len(todo):,} to fetch of {len(rows):,} requested")
    started = time.time()
    found = images = 0

    for index, row in enumerate(todo, 1):
        try:
            urls, tag = art_for(row["name"], row.get("series", ""),
                                args.per_character)
        except KeyboardInterrupt:
            save()
            print(f"\nstopped; {len(art):,} saved to {args.out}")
            return 130
        except Exception as error:  # noqa: BLE001 - one character must not end a sweep
            print(f"  {row['name']}: {type(error).__name__}")
            urls, tag = [], ""

        # Recorded either way. An empty list is a real answer - this character
        # has no art on the site - and without it --resume asks again forever.
        art[key(row)] = urls
        if urls:
            found += 1
            images += len(urls)

        if index % args.every == 0 or index == len(todo):
            save()
            rate = index / max(1e-9, time.time() - started)
            left = (len(todo) - index) / max(1e-9, rate)
            print(f"  {index:,}/{len(todo):,} · {found:,} with art ·"
                  f" {images:,} images · {rate * 60:.0f}/min ·"
                  f" {left / 3600:.1f}h left")

    save()
    print(f"\n{len(art):,} characters checked, {found:,} gained art,"
          f" {images:,} images")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
