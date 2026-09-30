"""Collects official, solo art for the roster, so an album looks like the show.

    python tools/fetch_official_art.py --top 5000
    python tools/fetch_official_art.py --top 20000 --resume

The first extra-art pass (tools/fetch_extra_art.py) took the most popular
fan art for each character, and fan art is exactly what it sounds like:
group shots, comic strips, crossovers and styles that look nothing like the
series. Players flipping through an album want the character as the show
draws them. So this asks Danbooru for official_art only and then throws out
anything that is not the character alone.

What survives the filter:
  - rated general, so nothing a Discord channel would not want
  - tagged solo, with no other character tagged beside them
  - not a comic, collage, sketch, cover, crossover, cosplay or variant
  - not a child post of something already taken, which is how the same
    poster otherwise turns up twice

Frames from the episodes themselves come first, where the site has any -
about fifteen thousand exist across every series there is, so most
characters have none. The rest is official art ranked for the same look: a
real background and a closer crop first, cut-outs on white last.

Names are resolved through Danbooru's character tags, which are
disambiguated (rem_(re:zero), makima_(chainsaw_man)) and, unlike the old
site's, can be sorted by post count. A tag is only accepted if the posts'
copyright tags or the tag's own parenthetical name the series, or if it is
large and plainly the one meant.

Output replaces data/character_art.json, keyed name + unit separator + series
as before, and records which tag each character resolved to in
data/character_art_tags.json so a later run can skip the lookup. The bot
drops the old fan art and loads this on its next boot.
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
TAGS = os.path.join(ROOT, "data", "character_art_tags.json")
KEY_SEP = "\x1f"

API = "https://danbooru.donmai.us"
UA = {"User-Agent": "gachabot-art/2.0 (official roster art for a Discord bot)"}

# Danbooru allows far more than this. A long sweep should still be a quiet one.
DELAY = 0.75
PER_CHARACTER = 8
FETCH = 100
CANDIDATES = 3

EMBEDDABLE = (".jpg", ".jpeg", ".png", ".gif", ".webp")

# Anything carrying one of these is not "the character, as the show draws
# them": several people, several panels, somebody else's style or outfit,
# unfinished work, or a cover whose title text fills the frame.
REJECT = {
    "comic", "4koma", "multiple_views", "multiple_girls", "multiple_boys",
    "2girls", "3girls", "4girls", "5girls", "6+girls",
    "2boys", "3boys", "4boys", "5boys", "6+boys", "1girl1boy", "group",
    "parody", "crossover", "cosplay", "genderswap", "genderswap_(mtf)",
    "genderswap_(ftm)", "style_parody", "character_sheet", "reference_sheet",
    "sketch", "lineart", "monochrome", "greyscale", "text_focus",
    "cover", "cover_page", "manga_cover", "magazine_cover", "album_cover",
    "novel_cover", "dvd_cover", "game_cover", "copyright_name", "logo",
    "watermark", "sample_watermark", "censored", "scan", "photo_(medium)",
    "real_life", "3d", "pixel_art", "chibi", "variant_set", "collage",
}

# A cut-out on white is a product render, not a picture of somebody in their
# own show. It is what the character looks like, which is why it ranked first
# at one point, but it is not what a card wants.
PLAIN = {"white_background", "simple_background", "transparent_background",
         "grey_background", "gradient_background", "no_background"}

# A real place behind them.
SCENE = {"scenery", "outdoors", "indoors", "sky", "tree", "cloud", "window",
         "night", "sunset", "forest", "city", "street", "room", "classroom",
         "building", "water", "grass", "snow", "rain", "blurry_background",
         "depth_of_field", "bokeh"}

# Framed close, the way a shot from an episode is.
CLOSE = {"portrait", "upper_body", "close-up", "cowboy_shot", "face",
         "looking_at_viewer", "profile"}

# Writing across the picture. Rejected outright: an album of event posters
# and title cards was the thing that looked least like the character, even
# when it left somebody with nothing but their main image.
#
# A signature or a date in the corner is not writing across the picture, so
# artist_name and dated stay allowed, and so does promotional_art - most
# official art of anybody is promotional.
TEXTY = {"english_text", "japanese_text", "chinese_text", "korean_text",
         "thai_text", "russian_text", "character_name", "title",
         "happy_birthday", "happy_new_year", "happy_halloween",
         "merry_christmas", "happy_valentine", "translation_request",
         "speech_bubble", "sign", "poster_(object)", "advertisement",
         "fake_screenshot", "subtitled"}

# Two images whose 8x8 thumbnails differ in this few bits are the same image
# re-uploaded - Makima's poster turned up twice as two unrelated posts.
SAME_IMAGE_BITS = 6

MIN_POSTS = 40
DOMINANCE = 3

STOPWORDS = {
    "the", "and", "not", "season", "movie", "part", "final", "new", "next",
    "story", "wo", "no", "ga", "ni", "wa", "de", "to", "kara", "made",
    "anime", "manga", "series", "tv", "ova", "special", "specials",
}


def slug(text: str) -> str:
    text = re.sub(r"[^\w\s-]", " ", (text or "").lower())
    return "_".join(text.split())


def name_bases(name: str) -> list:
    parts = [p for p in slug(name).split("_") if p]
    if not parts:
        return []
    forward = "_".join(parts)
    reverse = "_".join(reversed(parts))
    return [forward] if forward == reverse else [forward, reverse]


def series_tokens(series: str) -> set:
    words = [w for w in slug(series).split("_") if len(w) >= 4]
    return {w for w in words if w not in STOPWORDS}


def get(path: str, tries: int = 4, **query):
    url = f"{API}/{path}?" + urllib.parse.urlencode(query)
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=40) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            if error.code == 429:          # asked to slow down
                time.sleep(10 * (attempt + 1))
                continue
            if error.code >= 500 and attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            return []
        except (urllib.error.URLError, TimeoutError, ConnectionError,
                OSError, json.JSONDecodeError):
            if attempt == tries - 1:
                return []
            time.sleep(2 ** attempt)
        finally:
            time.sleep(DELAY)
    return []


def character_tags(base: str) -> list:
    """(count, tag) for character tags named base or base_(something)."""
    found = get("tags.json", **{
        "search[name_matches]": base + "*",
        "search[category]": "4",
        "search[order]": "count",
        "limit": "20",
    })
    out = []
    for tag in found or []:
        name = tag.get("name", "")
        if name == base or name.startswith(base + "_("):
            if name.endswith(("_(cosplay)", "_(male)", "_(female)")):
                continue
            out.append((int(tag.get("post_count") or 0), name))
    return out


def official_posts(tag: str) -> list:
    return get("posts.json", tags=f"{tag} official_art", limit=str(FETCH)) or []


def screenshot_posts(tag: str) -> list:
    """Frames lifted from the episodes themselves.

    The best answer to "just photos from the actual anime", and the rarest:
    the whole site holds about fifteen thousand of these across every series
    there is, so two characters in three have none at all.
    """
    return get("posts.json", tags=f"{tag} anime_screenshot", limit=str(FETCH)) or []


def confirms(tag: str, posts, wanted) -> bool:
    """Does the tag's parenthetical, or the posts' copyrights, name the series?"""
    if not wanted:
        return True
    inside = tag[tag.find("(") + 1:tag.rfind(")")] if "(" in tag else ""
    if inside and any(token in inside for token in wanted):
        return True
    copyrights = " ".join(p.get("tag_string_copyright", "") for p in posts)
    return any(token in copyrights for token in wanted)


def fingerprint(url: str):
    """A 64-bit average hash of an image's thumbnail, or None."""
    if not url:
        return None
    try:
        from PIL import Image
        request = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(request, timeout=30) as response:
            image = Image.open(io.BytesIO(response.read()))
            image = image.convert("L").resize((8, 8))
    except Exception:  # noqa: BLE001 - a missing preview only costs the check
        return None
    pixels = list(image.getdata())
    mean = sum(pixels) / len(pixels)
    return sum(1 << i for i, value in enumerate(pixels) if value > mean)


def pick(posts, tag: str, want: int) -> list:
    """The usable images from a page of posts, best first."""
    chosen, taken = [], set()
    scored = []
    for post in posts:
        general = set(post.get("tag_string_general", "").split())
        meta = set(post.get("tag_string_meta", "").split())
        people = post.get("tag_string_character", "").split()
        if post.get("rating") != "g":
            continue
        if "solo" not in general or (general | meta) & (REJECT | TEXTY):
            continue
        # Only this character: a second character tag is a crossover, a
        # duo, or a variant like sakura_miku riding on hatsune_miku.
        if people != [tag]:
            continue
        url = post.get("large_file_url") or post.get("file_url") or ""
        if not url.lower().endswith(EMBEDDABLE):
            continue
        # A scene with a background and a closer crop beats a cut-out render.
        rank = ((2 if general & SCENE else 0)
                + (1 if general & CLOSE else 0)
                - (2 if general & PLAIN else 0)
                - (1 if "full_body" in general else 0))
        scored.append((rank, int(post.get("score") or 0), post, url))

    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    prints = []
    for _rank, _score, post, url in scored:
        # Variants of one image are parent and child posts. Keep the first
        # of each family and skip the rest.
        family = post.get("parent_id") or post.get("id")
        if family in taken or post.get("id") in taken:
            continue
        # And the same picture uploaded twice, which no tag records.
        mark = fingerprint(post.get("preview_file_url"))
        if mark is not None and any(
                bin(mark ^ seen).count("1") <= SAME_IMAGE_BITS for seen in prints):
            continue
        taken.update({family, post.get("id")})
        if mark is not None:
            prints.append(mark)
        if url not in chosen:
            chosen.append(url)
        if len(chosen) >= want:
            break
    return chosen


# Set by --only-screenshots: frames from the episodes and nothing else, even
# when that leaves a character with none.
SCREENSHOTS_ONLY = False


def images_for_tag(tag: str, want: int) -> list:
    """Screenshots first, then official art to fill the album up."""
    found = pick(screenshot_posts(tag), tag, want)
    if SCREENSHOTS_ONLY:
        return found[:want]
    if len(found) < want:
        for url in pick(official_posts(tag), tag, want - len(found)):
            if url not in found:
                found.append(url)
    return found[:want]


def art_for(name: str, series: str, want: int, known_tag: str = "") -> tuple:
    """(urls, tag) for one character. Empty when nothing clean exists."""
    wanted = series_tokens(series)

    if known_tag:
        return images_for_tag(known_tag, want), known_tag

    candidates = []
    for base in name_bases(name):
        candidates += character_tags(base)
    if not candidates:
        return [], ""
    candidates = sorted(set(candidates), reverse=True)

    for _count, tag in candidates[:CANDIDATES]:
        posts = official_posts(tag)
        if posts and confirms(tag, posts, wanted):
            return images_for_tag(tag, want), tag

    # The booru files the series under a title the roster does not carry -
    # Maomao is kusuriya_no_hitorigoto, not The Apothecary Diaries. Accept the
    # top tag only when it is big and nothing else of that name comes close.
    top_count, top_tag = candidates[0]
    runner_up = candidates[1][0] if len(candidates) > 1 else 0
    if top_count >= MIN_POSTS and top_count >= max(1, runner_up) * DOMINANCE:
        return images_for_tag(top_tag, want), top_tag
    return [], ""


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--top", type=int, default=2000)
    parser.add_argument("--per-character", type=int, default=PER_CHARACTER)
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--tags", default=TAGS)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--only-screenshots", action="store_true",
                        help="frames from the episodes and nothing else - no"
                             " official art to fill the gaps")
    parser.add_argument("--refilter", action="store_true",
                        help="keep the tags already resolved and only fetch"
                             " and re-filter their images, which skips two"
                             " lookups per character")
    parser.add_argument("--every", type=int, default=100)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    global SCREENSHOTS_ONLY
    SCREENSHOTS_ONLY = args.only_screenshots

    sys.path.insert(0, ROOT)
    import utils

    rows = list(utils.iter_roster(ROSTER))
    rows.sort(key=lambda r: r.get("claim_rank") or 10 ** 9)
    rows = rows[:args.top]

    def key(row):
        return row["name"] + KEY_SEP + (row.get("series") or "")

    art, tags = {}, {}
    if args.resume:
        for path, target in ((args.out, art), (args.tags, tags)):
            if os.path.exists(path):
                with io.open(path, encoding="utf-8") as handle:
                    target.update(json.load(handle))
        # Resume means resume THIS collector. Keys written by the fan-art
        # pass have no entry in the tag file and are fetched again.
        art = {k: v for k, v in art.items() if k in tags}
        print(f"resuming: {len(art):,} characters already done")

    def save():
        for path, data in ((args.out, art), (args.tags, tags)):
            tmp = path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False)
            os.replace(tmp, path)

    if args.refilter:
        if not tags:
            with io.open(args.tags, encoding="utf-8") as handle:
                tags.update(json.load(handle))
        # Characters whose name matched no tag last time will not match one
        # now either; leave them empty rather than paying for the lookup.
        wanted_keys = {key(r) for r in rows}
        art = {k: [] for k, tag in tags.items()
               if not tag and k in wanted_keys}
        todo = [r for r in rows if tags.get(key(r))]
        print(f"re-filtering {len(todo):,} characters with a known tag")
    else:
        todo = [r for r in rows if key(r) not in art]
    print(f"{len(todo):,} to fetch of {len(rows):,} requested")
    started, found, images = time.time(), 0, 0

    for index, row in enumerate(todo, 1):
        try:
            urls, tag = art_for(row["name"], row.get("series", ""),
                                args.per_character,
                                known_tag=tags.get(key(row), "")
                                if args.refilter else "")
        except KeyboardInterrupt:
            save()
            print(f"\nstopped; {len(art):,} saved")
            return 130
        except Exception as error:  # noqa: BLE001 - one character must not end a sweep
            print(f"  {row['name']}: {type(error).__name__}")
            urls, tag = [], ""

        art[key(row)] = urls
        tags[key(row)] = tag
        if urls:
            found += 1
            images += len(urls)

        if index % args.every == 0 or index == len(todo):
            save()
            rate = index / max(1e-9, time.time() - started)
            left = (len(todo) - index) / max(1e-9, rate)
            print(f"  {index:,}/{len(todo):,} · {found:,} with art ·"
                  f" {images:,} images · {rate * 60:.0f}/min ·"
                  f" {left / 3600:.1f}h left", flush=True)

    save()
    print(f"\n{len(art):,} characters, {sum(1 for v in art.values() if v):,}"
          f" with official art, {sum(len(v) for v in art.values()):,} images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
