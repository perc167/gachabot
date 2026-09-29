"""Finds real frames of each character, out of the episodes themselves.

    python tools/fetch_episode_frames.py --top 500
    python tools/fetch_episode_frames.py --top 2000 --resume

Booru sites index perhaps fifteen thousand anime screenshots in total, across
every series ever made, which left twelve of your top hundred with a single
frame. Episode screenshots do exist in bulk - fancaps.net holds millions,
filed by series and episode - but nobody has tagged who is in them. So this
tags them itself.

How it works, per series rather than per character, because one pass over an
episode answers for everybody in it:

  1. Find the series on fancaps and list its episodes.
  2. Sample frames evenly across them - the opening minutes of episode one
     are not the show.
  3. Run an anime tagger over each frame's thumbnail. The model predicts
     Danbooru tags, and data/character_art_tags.json already says which
     Danbooru tag each of our characters is, so a prediction is an answer.
  4. Shortlist the confident ones, then confirm each at full resolution. A
     250x140 thumbnail is enough to reject a frame quickly and not enough to
     accept one.
  5. Keep the best few per character: only them in shot, no near-duplicates.

What it cannot do: the tagger knows about 2,750 characters, so anyone it has
never heard of gets nothing. It says so at the start rather than pretending.

The model is about 380MB and is not in the repo. It downloads on first run to
.cache/, which .gitignore covers.

Needs onnxruntime, numpy and Pillow:  pip install onnxruntime numpy Pillow
"""
import argparse
import csv
import difflib
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
TAGS = os.path.join(ROOT, "data", "character_art_tags.json")
OUT = os.path.join(ROOT, "data", "character_frames.json")
SERIES_CACHE = os.path.join(ROOT, "data", "fancaps_series.json")
CACHE_DIR = os.path.join(ROOT, ".cache")
MODEL = os.path.join(CACHE_DIR, "wd-vit-tagger-v3.onnx")
LABELS = os.path.join(CACHE_DIR, "wd-vit-tagger-v3.csv")

MODEL_URL = ("https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/"
             "resolve/main/model.onnx")
LABELS_URL = ("https://huggingface.co/SmilingWolf/wd-vit-tagger-v3/"
              "resolve/main/selected_tags.csv")

SITE = "https://fancaps.net"
THUMB = "https://ant.fancaps.net/{}.jpg"
FULL = "https://cdni.fancaps.net/file/fancaps-animeimages/{}.jpg"
UA = {"User-Agent": "gachabot-frames/1.0 (character art for a Discord bot)"}

KEY_SEP = "\x1f"
DELAY = 0.2

# How much of a series to look at. Spread across episodes rather than deep
# into one, so an album is not six frames of the same scene.
EPISODES = 5
FRAMES_PER_EPISODE = 60
PER_CHARACTER = 6

# On the thumbnail, enough to be worth a closer look. On the full frame,
# enough to keep - and high, because the model answers 0.96 to 1.00 when it
# is genuinely right: at 0.72 a blond stranger got into Gojou's album and
# somebody else into Hitagi's.
SHORTLIST = 0.45
CONFIRM = 0.85
# Somebody else in shot. The whole point is frames of them alone.
INTRUDER = 0.40

# The model counts people whether or not it can name them, which is what
# catches the second person in a frame when that person is nobody it knows -
# Tadano beside Komi, Ritsu beside Mio.
CROWD = ("2girls", "3girls", "4girls", "5girls", "6+girls", "multiple_girls",
         "2boys", "3boys", "4boys", "5boys", "6+boys", "multiple_boys")

# There is no tag for "a boy and a girl": the model says 1girl and 1boy at
# once, which is how Tadano stood beside Komi in a frame that passed every
# other check. One of each is still two people.
GIRLS = ("1girl", "2girls", "3girls", "4girls", "5girls", "6+girls")
BOYS = ("1boy", "2boys", "3boys", "4boys", "5boys", "6+boys")
BOTH = 0.50

# Credits, title cards and subtitled frames: text, not a picture of anybody.
LETTERING = ("credits", "subtitled", "text_focus", "english_text",
             "japanese_text", "character_name", "copyright_name", "logo",
             "watermark")
BUSY = 0.35

SAME_IMAGE_BITS = 8


def fetch(url: str, tries: int = 3, timeout: int = 40):
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == tries - 1:
                return b""
            time.sleep(1.5 * (attempt + 1))
        finally:
            time.sleep(DELAY)
    return b""


def download(url: str, path: str, label: str):
    if os.path.exists(path) and os.path.getsize(path) > 1024:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    print(f"  downloading {label} (once) ...", flush=True)
    request = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(request, timeout=900) as response, \
            open(path, "wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    print(f"  {label}: {os.path.getsize(path) / 1e6:.0f} MB")


class Tagger:
    """SmilingWolf's WD tagger: a picture in, Danbooru tags out."""

    def __init__(self):
        import numpy as np
        import onnxruntime as ort

        download(LABELS_URL, LABELS, "tag list")
        download(MODEL_URL, MODEL, "tagger model")

        self.np = np
        self.session = ort.InferenceSession(
            MODEL, providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0]
        self.size = self.input.shape[1]

        rows = list(csv.DictReader(io.open(LABELS, encoding="utf-8")))
        self.names = [row["name"] for row in rows]
        self.characters = {row["name"] for row in rows if row["category"] == "4"}
        self.character_index = [n for n, row in enumerate(rows)
                                if row["category"] == "4"]
        self.general_index = [n for n, row in enumerate(rows)
                              if row["category"] == "0"]

    def prepare(self, image):
        from PIL import Image

        image = image.convert("RGBA")
        ground = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(ground, image).convert("RGB")
        width, height = image.size
        side = max(width, height)
        square = Image.new("RGB", (side, side), (255, 255, 255))
        square.paste(image, ((side - width) // 2, (side - height) // 2))
        square = square.resize((self.size, self.size), Image.BICUBIC)
        # The model wants BGR, which is what its own code feeds it.
        array = self.np.asarray(square, dtype=self.np.float32)[:, :, ::-1]
        return self.np.expand_dims(array, 0)

    def read(self, image) -> tuple:
        """(characters, other tags) the model sees, each with a confidence."""
        probs = self.session.run(
            None, {self.input.name: self.prepare(image)})[0][0]
        people = {self.names[n]: float(probs[n]) for n in self.character_index
                  if probs[n] >= 0.25}
        rest = {self.names[n]: float(probs[n])
                for n in self.general_index if probs[n] >= 0.25}
        return people, rest

    def characters_in(self, image) -> dict:
        """{character tag: confidence} for everyone the model sees."""
        return self.read(image)[0]

    def alone(self, image, tag: str) -> bool:
        """Is this a frame of `tag`, by themselves, with no lettering on it?"""
        people, rest = self.read(image)
        if people.get(tag, 0.0) < CONFIRM:
            return False
        if any(other != tag and value >= INTRUDER
               for other, value in people.items()):
            return False
        if any(rest.get(word, 0.0) >= BUSY for word in CROWD):
            return False
        if (any(rest.get(word, 0.0) >= BOTH for word in GIRLS)
                and any(rest.get(word, 0.0) >= BOTH for word in BOYS)):
            return False
        if any(rest.get(word, 0.0) >= BUSY for word in LETTERING):
            return False
        return True


def image_from(data: bytes):
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
        return image
    except Exception:  # noqa: BLE001 - a bad frame is just a skipped frame
        return None


def fingerprint(image):
    """An 8x8 average hash, to notice the same shot twice."""
    small = image.convert("L").resize((8, 8))
    pixels = list(small.getdata())
    mean = sum(pixels) / len(pixels)
    return sum(1 << n for n, value in enumerate(pixels) if value > mean)


def alike(one: int, two: int) -> bool:
    return bin(one ^ two).count("1") <= SAME_IMAGE_BITS


def dull(image) -> bool:
    """A black frame, a white flash, or a title card: not a picture of anyone."""
    small = image.convert("L").resize((32, 32))
    pixels = list(small.getdata())
    mean = sum(pixels) / len(pixels)
    spread = (sum((p - mean) ** 2 for p in pixels) / len(pixels)) ** 0.5
    return spread < 18 or mean < 24 or mean > 238


# --------------------------------------------------------------------------
# fancaps: search, episodes, frames
# --------------------------------------------------------------------------
CATALOGUE = os.path.join(ROOT, "data", "fancaps_catalogue.json")


def simple(title: str) -> str:
    """A title with its punctuation and its noise words taken out."""
    text = (title or "").lower()
    for curly, plain in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", ""),
                         ("\u201d", ""), ("\u2013", " "), ("\u2014", " ")):
        text = text.replace(curly, plain)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    drop = {"the", "a", "an", "tv", "season", "series", "part", "anime"}
    return " ".join(word for word in text.split() if word not in drop)


def catalogue() -> dict:
    """Every anime the site carries: {simplified title: path}.

    Taken once from its A-Z listing and cached. The site's own search is not
    usable for this: it answers "Naruto" with Kiff and Yu-Gi-Oh, and taking
    its first result would have bound characters to the wrong show.
    """
    if os.path.exists(CATALOGUE):
        with io.open(CATALOGUE, encoding="utf-8") as handle:
            return json.load(handle)

    index = {}
    for letter in "0abcdefghijklmnopqrstuvwxyz":
        page = fetch(SITE + "/anime/showList.php?" + letter).decode(
            "utf-8", "replace")
        for path in set(re.findall(r'showimages\.php\?(\d+-[^"&]+)', page)):
            name = path.split("-", 1)[1].replace("_", " ")
            index.setdefault(simple(name), path)
        print("  catalogue {}: {:,} series so far".format(letter, len(index)),
              flush=True)

    with io.open(CATALOGUE, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=0)
    return index


def find_series(title: str, cache: dict) -> str:
    """The site's path for a series, or "" if it does not carry it.

    Matched against the catalogue and scored, so a near miss is rejected
    rather than quietly becoming the wrong series.
    """
    if title in cache:
        return cache[title]

    index = catalogue()
    wanted = simple(title)
    best, score = "", 0.0
    for name, path in index.items():
        if not name:
            continue
        if name == wanted:
            best, score = path, 1.0
            break
        # A show and its sequels share a prefix - "frieren beyond journey s
        # end" against the same plus "2" - so one containing the other from
        # the start counts, scaled by how much is left over.
        if name.startswith(wanted) or wanted.startswith(name):
            overlap = min(len(name), len(wanted)) / max(len(name), len(wanted))
            ratio = 0.80 + 0.19 * overlap
        else:
            ratio = difflib.SequenceMatcher(None, wanted, name).ratio()
        if ratio > score:
            best, score = path, ratio

    cache[title] = best if score >= 0.82 else ""
    return cache[title]


def episodes(series_path: str) -> list:
    page = fetch(f"{SITE}/anime/showimages.php?{series_path}").decode(
        "utf-8", "replace")
    found = re.findall(r"episodeimages\.php\?(\d+-[A-Za-z0-9_]+/[A-Za-z0-9_]+)",
                       page)
    # Keep the order the site lists them in, without the repeats its markup
    # produces for each thumbnail.
    seen, out = set(), []
    for path in found:
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def frame_ids(episode_path: str, pages: int = 3) -> list:
    ids, seen = [], set()
    for page_number in range(1, pages + 1):
        url = f"{SITE}/anime/episodeimages.php?{episode_path}"
        if page_number > 1:
            url += f"&page={page_number}"
        page = fetch(url).decode("utf-8", "replace")
        found = re.findall(r"ant\.fancaps\.net/(\d+)\.jpg", page)
        if not found:
            break
        for one in found:
            if one not in seen:
                seen.add(one)
                ids.append(one)
    return ids


def spread(items: list, count: int) -> list:
    """`count` items spaced evenly through the list, not the first `count`."""
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    return [items[int(n * step)] for n in range(count)]


def prefetch(urls, ahead: int = 4):
    """Yield images in order, with several downloads in flight.

    Tagging a frame costs about as long as fetching one, and doing them in
    turn wastes half the clock. Each image carries the url it came from, so
    a caller can record it without keeping a parallel list.
    """
    from concurrent.futures import ThreadPoolExecutor

    urls = list(urls)
    if not urls:
        return
    with ThreadPoolExecutor(max_workers=ahead) as pool:
        for url, data in zip(urls, pool.map(lambda one: fetch(one, tries=2),
                                            urls)):
            image = image_from(data)
            if image is not None:
                image.url = url
            yield image


def series_plan(top: int) -> tuple:
    """Which series to sweep, and which characters each one is being swept for."""
    sys.path.insert(0, ROOT)
    import utils

    tags = json.load(io.open(TAGS, encoding="utf-8")) if os.path.exists(TAGS) else {}
    rows = sorted(utils.iter_roster(ROSTER),
                  key=lambda r: r.get("claim_rank") or 10 ** 9)[:top]

    plan, unknown = {}, 0
    for row in rows:
        key = row["name"] + KEY_SEP + (row.get("series") or "")
        tag = tags.get(key, "")
        if not tag:
            unknown += 1
            continue
        plan.setdefault(row.get("series") or "", []).append((key, tag, row))
    return plan, unknown


def harvest(tagger, series: str, wanted: list, budget: int) -> dict:
    """Frames for the characters of one series: {key: [urls]}."""
    cache = {}
    if os.path.exists(SERIES_CACHE):
        cache = json.load(io.open(SERIES_CACHE, encoding="utf-8"))
    path = find_series(series, cache)
    with io.open(SERIES_CACHE, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(cache, handle, ensure_ascii=False)
    if not path:
        return {}

    wanted_tags = {tag: key for key, tag, _row in wanted}
    shortlist = {tag: [] for tag in wanted_tags}

    for episode in spread(episodes(path), EPISODES):
        for frame in spread(frame_ids(episode), FRAMES_PER_EPISODE):
            thumb = image_from(fetch(THUMB.format(frame), tries=1, timeout=20))
            if thumb is None or dull(thumb):
                continue
            seen = tagger.characters_in(thumb)
            for tag in wanted_tags:
                score = seen.get(tag, 0.0)
                if score < SHORTLIST:
                    continue
                # Somebody else in shot rules it out before it costs a
                # full-size download.
                if any(other != tag and value >= INTRUDER
                       for other, value in seen.items()):
                    continue
                shortlist[tag].append((score, frame))
            budget -= 1
            if budget <= 0:
                break
        if budget <= 0:
            break

    # Confirm the best of them at full size, where the model can be trusted.
    found = {}
    for tag, key in wanted_tags.items():
        candidates = sorted(shortlist[tag], reverse=True)[:PER_CHARACTER * 4]
        kept, prints = [], []
        for _score, frame in candidates:
            image = image_from(fetch(FULL.format(frame), tries=2))
            if image is None or dull(image):
                continue
            if not tagger.alone(image, tag):
                continue
            mark = fingerprint(image)
            if any(alike(mark, other) for other in prints):
                continue
            prints.append(mark)
            kept.append(FULL.format(frame))
            if len(kept) >= PER_CHARACTER:
                break
        if kept:
            found[key] = kept
    return found


def verify(out_path: str):
    """Re-check saved frames against the current rules, dropping the failures."""
    import json as _json

    with io.open(out_path, encoding="utf-8") as handle:
        frames = _json.load(handle)
    tags = _json.load(io.open(TAGS, encoding="utf-8"))
    tagger = Tagger()

    checked = dropped = 0
    for key, urls in list(frames.items()):
        tag = tags.get(key, "")
        if not tag:
            continue
        kept = []
        for image in prefetch(urls):
            checked += 1
            if image is None or dull(image):
                dropped += 1
                continue
            if tagger.alone(image, tag):
                kept.append(image.url)
            else:
                dropped += 1
        if kept:
            frames[key] = kept
        else:
            del frames[key]
        with io.open(out_path, "w", encoding="utf-8", newline="\n") as handle:
            _json.dump(frames, handle, ensure_ascii=False)

    print(f"checked {checked:,} frames, dropped {dropped:,};"
          f" {len(frames):,} characters keep"
          f" {sum(len(v) for v in frames.values()):,}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--top", type=int, default=500)
    parser.add_argument("--out", default=OUT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verify", action="store_true",
                        help="re-check the frames already saved against the"
                             " current rules instead of sweeping again")
    parser.add_argument("--budget", type=int, default=EPISODES * FRAMES_PER_EPISODE,
                        help="most thumbnails to scan per series")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.verify:
        return verify(args.out)

    plan, unknown = series_plan(args.top)
    tagger = Tagger()

    # Anyone the model has never heard of cannot be found this way. Said
    # once, up front, rather than discovered halfway through.
    known = {}
    strangers = 0
    for series, people in plan.items():
        keep = [(key, tag, row) for key, tag, row in people
                if tag in tagger.characters]
        strangers += len(people) - len(keep)
        if keep:
            known[series] = keep
    total_people = sum(len(v) for v in known.values())
    print(f"{total_people:,} of the top {args.top:,} can be recognised,"
          f" across {len(known):,} series")
    print(f"  {strangers:,} are not in the tagger's vocabulary,"
          f" {unknown:,} have no tag at all\n")

    frames = {}
    if args.resume and os.path.exists(args.out):
        frames = json.load(io.open(args.out, encoding="utf-8"))
        print(f"resuming with {len(frames):,} already found")

    done = json.load(io.open(args.out + ".series", encoding="utf-8")) \
        if args.resume and os.path.exists(args.out + ".series") else []
    done = set(done)

    started, scanned = time.time(), 0
    order = sorted(known.items(),
                   key=lambda item: min(r.get("claim_rank") or 10 ** 9
                                        for _k, _t, r in item[1]))
    for number, (series, people) in enumerate(order, 1):
        if series in done:
            continue
        try:
            got = harvest(tagger, series, people, args.budget)
        except KeyboardInterrupt:
            break
        except Exception as error:  # noqa: BLE001 - one series must not end a sweep
            print(f"  {series}: {type(error).__name__}")
            got = {}

        frames.update(got)
        done.add(series)
        scanned += 1
        with io.open(args.out, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(frames, handle, ensure_ascii=False)
        with io.open(args.out + ".series", "w", encoding="utf-8",
                     newline="\n") as handle:
            json.dump(sorted(done), handle, ensure_ascii=False)

        rate = scanned / max(1e-9, (time.time() - started) / 60)
        print(f"  [{number}/{len(order)}] {series[:38]:38}"
              f" {len(got):>2} found · {len(frames):,} total ·"
              f" {rate:.1f} series/min", flush=True)

    print(f"\n{len(frames):,} characters have episode frames,"
          f" {sum(len(v) for v in frames.values()):,} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
