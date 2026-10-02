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

# Camie's tagger knows ten times as many characters and is sure of none of
# them the way WD is: on 60 frames WD confirmed at 0.85 or better, Camie's
# median was 0.39, and it names the wrong person often enough to matter. So
# it is believed only when it is well above its own median and clearly ahead
# of its own second guess. That keeps about one frame in three, which is
# plenty when a sweep looks at four hundred.
CAMIE_SHORTLIST = 0.25
CAMIE_CONFIRM = 0.60
CAMIE_MARGIN = 0.15

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
# Lettering gets a lower bar than a second person: credits over a face read
# as small, faint text and the model is less sure of them, but an album
# picture with writing across it is wrong either way.
LETTERED = 0.22

# Two shots a second apart are the same picture to somebody flipping
# through an album, so this is generous rather than exact.
SAME_IMAGE_BITS = 12

# What makes a frame worth keeping, beyond being the right person. A frame
# of one eye in the dark passes every identity check and is still a bad
# picture, which is what Emilia's album was full of.
CLOSE_UP = ("close-up", "eye_focus", "extreme_closeup")
GOOD_FRAMING = ("upper_body", "cowboy_shot", "portrait", "looking_at_viewer",
                "full_body", "solo_focus")


# The roster spells a character's danbooru tag the way their name is written
# in English; danbooru does not always agree. A long vowel can be ou, oo, oh
# or nothing - Rin Toosaka is tohsaka_rin there, Joutarou Kuujou is
# kujo_jotaro - and the model only answers to its own spelling, so these nine
# were silently unfindable.
#
# Written out rather than guessed at. Matching names loosely offered three
# more, and all three were wrong: there is a Hanako in Toilet-bound
# Hanako-kun and another in Blue Archive, a Yuno in Black Clover and another
# in Hidamari Sketch, and the Josuke of Diamond is Unbreakable is not the
# Josuke of JoJolion. A table of nine can be read and checked; a rule that
# binds a character to a stranger cannot.
ALIASES = {
    "kuujou_joutarou": "kujo_jotaro",
    "kuujou_jolyne": "kujo_jolyne",
    "kakyouin_noriaki": "kakyoin_noriaki",
    "toosaka_rin": "tohsaka_rin",
    "gotou_hitori_(tsuchinoko)": "gotoh_hitori",
    "yamada_ryou": "yamada_ryo",
    "getou_suguru_(kenjaku)": "getou_suguru",
    "hoshino_ai": "hoshino_ai_(oshi_no_ko)",
    "kirigiri_kyouko": "kirigiri_kyoko",
}


def bare_name(tag: str) -> str:
    """A character tag with its bracketed note and its long vowels removed."""
    name = re.sub(r"_\([^)]*\)$", "", tag).replace("-", "_").lower()
    for long, short in (("ou", "o"), ("oo", "o"), ("uu", "u"), ("ei", "e"),
                        ("oh", "o")):
        name = name.replace(long, short)
    return re.sub(r"[^a-z0-9]", "", name)


def same_person(one: str, other: str) -> bool:
    """Two tags for the same character.

    Danbooru files a character's other forms under their own tags -
    akemi_homura and akemi_homura_(magical_girl) are one girl - and counting
    the second as somebody else in shot would throw the frame away. Only an
    exact match once the brackets are gone, deliberately: uchiha_itachi and
    uchiha_sasuke share a surname and are two different people.
    """
    return one == other or bare_name(one) == bare_name(other)


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

        # What this particular model has to say before it is believed. WD
        # answers 0.96 to 1.00 when it is right, so it is held to 0.85 and
        # needs no margin over its second guess.
        self.label = "WD"
        self.shortlist_at = SHORTLIST
        self.confirm_at = CONFIRM
        self.margin = 0.0

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

    def alone(self, image, tag: str, reading=None) -> bool:
        """Is this a frame of `tag`, by themselves, with no lettering on it?"""
        people, rest = reading if reading else self.read(image)
        mine = people.get(tag, 0.0)
        if mine < self.confirm_at:
            return False
        others = [value for other, value in people.items()
                  if not same_person(other, tag)]
        if any(value >= INTRUDER for value in others):
            return False
        # A model that is only somewhat sure has to be surer of this person
        # than of anybody else it half-recognises.
        if self.margin and mine - max(others, default=0.0) < self.margin:
            return False
        if any(rest.get(word, 0.0) >= BUSY for word in CROWD):
            return False
        if (any(rest.get(word, 0.0) >= BOTH for word in GIRLS)
                and any(rest.get(word, 0.0) >= BOTH for word in BOYS)):
            return False
        if any(rest.get(word, 0.0) >= LETTERED for word in LETTERING):
            return False
        return True


class Panel:
    """Both models: whichever one knows a character answers for them.

    WD is sure of the 2,751 characters it was taught, and every threshold in
    this file - crowding, lettering, faces, darkness - was measured against
    its confidence. Camie knows ten times as many characters and is vaguer
    about all of it. So Camie is asked who somebody is, but only when WD has
    never heard of them, and WD is asked what kind of shot it is either way.

    The sweep, the cropper and the audit all ask the same questions of the
    same pair, which is the point: they disagreed before, and the two that
    only knew WD quietly discarded everything the one that knew both found.
    """

    def __init__(self, with_camie: bool = True):
        self.wd = Tagger()
        self.camie = None
        if not with_camie:
            return
        try:
            from camie import CamieTagger

            self.camie = CamieTagger(keep_above=0.20)
            self.camie.label = "Camie"
            self.camie.shortlist_at = CAMIE_SHORTLIST
            self.camie.confirm_at = CAMIE_CONFIRM
            self.camie.margin = CAMIE_MARGIN
        except Exception as error:  # noqa: BLE001 - WD alone still works
            print(f"  (second tagger unavailable: {type(error).__name__})")

    def knows(self, tag: str):
        """(the model that can name them, the name it knows them by)."""
        tag = ALIASES.get(tag, tag)
        if tag in self.wd.characters:
            return self.wd, tag
        if self.camie is not None and tag in self.camie.characters:
            return self.camie, tag
        return None, tag

    def judge(self, image, tag: str) -> tuple:
        """(is it them alone, what kind of shot it is).

        A character neither model knows cannot be checked, and refusing
        every picture of them is worse than letting them through: that is
        how a character ends up with an empty album.
        """
        scene = self.wd.read(image)[1]
        model, tag = self.knows(tag)
        if model is None:
            return True, scene
        if model is self.wd:
            return self.wd.alone(image, tag), scene
        # Camie names them; WD says whether anybody else is in shot.
        people = model.read(image)[0]
        return model.alone(image, tag, (people, scene)), scene


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


def shows_face(tags: dict) -> bool:
    """Is a face visible, by what the tagger can read off it?"""
    return any(value >= FACE_SURE for name, value in tags.items()
               if any(word in name for word in FACE_TAGS))


_cascade = None


def face_finder():
    """The anime face detector, downloaded once."""
    global _cascade
    if _cascade is None:
        import cv2

        download(CASCADE_URL, CASCADE, "face detector")
        _cascade = cv2.CascadeClassifier(CASCADE)
    return _cascade


def biggest_face(image):
    """(x, y, w, h) of the largest face in the picture, or None."""
    import cv2
    import numpy as np

    finder = face_finder()
    if finder.empty():
        return None
    grey = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    found = finder.detectMultiScale(cv2.equalizeHist(grey), 1.08, 4,
                                    minSize=(32, 32))
    if len(found) == 0:
        return None
    return max(found, key=lambda box: box[3])


def face_score(box, image) -> float:
    """How well the face sits in the frame. 0 means do not keep it."""
    if box is None:
        return 0.0
    share = box[3] / image.height
    if not FACE_FLOOR <= share <= FACE_CEILING:
        return 0.0
    low, high = FACE_IDEAL
    if low <= share <= high:
        return 1.0
    if share < low:
        return max(0.2, (share - FACE_FLOOR) / (low - FACE_FLOOR))
    return max(0.2, (FACE_CEILING - share) / (FACE_CEILING - high))


# Dark enough that she is a shape rather than a person. Measured off the
# frames that were complained about: the hooded shot averages 67 of 255 and
# the silhouette 104 with a quarter of it near black, while every frame worth
# keeping sat above 85 with less than a quarter dark. The sky at dusk is
# fine; an unlit room is not.
DIM = 85.0
MOSTLY_DARK = 0.24
NEAR_BLACK = 40


def visible(image, tags: dict) -> bool:
    """Can you see who this is, or only that somebody is there?"""
    # An eye filling the card is a bright, sharp, certain picture of nobody.
    if any(tags.get(word, 0.0) >= 0.5 for word in TOO_CLOSE):
        return False
    grey = image.convert("L").resize((96, 96))
    pixels = list(grey.getdata())
    mean = sum(pixels) / len(pixels)
    if mean < DIM:
        return False
    dark = sum(1 for p in pixels if p < NEAR_BLACK) / len(pixels)
    return dark <= MOSTLY_DARK


def quality(image, tags: dict) -> float:
    """How good a picture this is, apart from who is in it.

    Sharpness and contrast off the pixels, framing off the tagger. A frame
    that is dark, blurred, or a single eye filling the screen scores low even
    when the model is certain whose eye it is.
    """
    small = image.convert("L").resize((96, 96))
    pixels = list(small.getdata())
    mean = sum(pixels) / len(pixels)
    spread = (sum((p - mean) ** 2 for p in pixels) / len(pixels)) ** 0.5

    # Edge energy as a stand-in for focus: a blurred or foggy frame has
    # little of it, a crisp one has plenty.
    rows = [pixels[n * 96:(n + 1) * 96] for n in range(96)]
    edges = 0
    for row in rows[::4]:
        edges += sum(abs(row[n + 1] - row[n]) for n in range(0, 95, 2))
    sharpness = edges / (24 * 48)

    score = 0.0
    score += min(spread, 70) / 70                 # contrast, capped
    score += min(sharpness, 30) / 30              # focus, capped
    # Mid brightness is best: dusk scenes are fine, pitch black is not.
    score += 1.0 - min(abs(mean - 130), 110) / 110
    if any(tags.get(word, 0.0) >= 0.4 for word in GOOD_FRAMING):
        score += 0.6
    if any(tags.get(word, 0.0) >= 0.4 for word in CLOSE_UP):
        score -= 0.8
    return score


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
FACES = os.path.join(ROOT, "data", "frame_faces.json")
CASCADE = os.path.join(CACHE_DIR, "lbpcascade_animeface.xml")
CASCADE_URL = ("https://raw.githubusercontent.com/nagadomi/"
               "lbpcascade_animeface/master/lbpcascade_animeface.xml")

# A frame has to show the face. The obvious way to check - an anime face
# cascade - finds one in only a fifth of frames that plainly have one, so it
# cannot be a gate. The tagger can: it reports eye colour, an expression, a
# mouth, only when there is a face to read them off. On frames known to be
# good it agrees 20 times out of 21, and it rejected both of the shots that
# were complained about.
FACE_TAGS = ("_eyes", "eyelashes", "smile", "open_mouth", "closed_eyes",
             "blush", "teeth", "tongue", "looking_at_viewer", "portrait",
             "face", "mouth", "eyebrows")
FACE_SURE = 0.40

# An eye filling the screen is a face too, and still a poor picture.
TOO_CLOSE = ("close-up", "eye_focus")

# How many frames one episode may give. Six frames of one scene is not an
# album, however good each of them is.
PER_EPISODE = 2


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


def matching_series(title: str, limit: int = 4) -> list:
    """Every season of a series, the earliest first.

    The catalogue lists seasons separately, and taking the best single match
    picked Re:Zero season two - where Emilia is scarce and Rem is asleep -
    over the season she is actually in. A character is in their whole show,
    so the whole show is what gets swept.
    """
    index = catalogue()
    wanted = simple(title)
    if not wanted:
        return []

    found = []
    for name, path in index.items():
        if not name:
            continue
        if name == wanted or name.startswith(wanted + " "):
            # "re zero starting life in another world s02" begins with the
            # base title; an unrelated show sharing a first word does not.
            found.append((len(name), name, path))
        elif wanted.startswith(name + " ") and len(name) >= 12:
            found.append((len(name), name, path))

    if not found:
        one = find_series(title, {})
        return [one] if one else []

    found.sort()
    return [path for _length, _name, path in found[:limit]]


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


def harvest(groups, series: str, budget: int,
            episodes_wanted: int = EPISODES, scene_reader=None) -> dict:
    """Frames for the characters of one series: {key: [urls]}.

    `groups` pairs a model with the people it is being asked about, because
    no one model knows everybody. A frame is downloaded once and shown to
    whichever models are waiting on it.

    `scene_reader` is the model whose ordinary tags are trusted - whether
    anybody else is in shot, whether there is writing over it, whether a
    face is visible. Every threshold here was measured against WD, so WD
    reads the scene even for a character only Camie can name.
    """
    paths = matching_series(series)
    if not paths:
        return {}

    groups = [(tagger, people) for tagger, people in groups if people]
    if not groups:
        return {}

    owner = {}                       # tag -> the model that knows them
    wanted_tags = {}                 # tag -> roster key
    for tagger, people in groups:
        for key, tag, _row in people:
            wanted_tags[tag] = key
            owner[tag] = tagger
    shortlist = {tag: [] for tag in wanted_tags}
    faces = {}
    episode_of = {}

    # Spread the sample across the seasons as well as the episodes, so a
    # show with four of them is not represented by its first.
    each = max(1, episodes_wanted // len(paths))
    schedule = []
    for path in paths:
        schedule += spread(episodes(path), each)

    for episode in schedule:
        for frame in spread(frame_ids(episode), FRAMES_PER_EPISODE):
            episode_of[frame] = episode
            thumb = image_from(fetch(THUMB.format(frame), tries=1, timeout=20))
            if thumb is None or dull(thumb):
                continue
            for tagger, people in groups:
                seen = tagger.characters_in(thumb)
                for _key, tag, _row in people:
                    score = seen.get(tag, 0.0)
                    if score < tagger.shortlist_at:
                        continue
                    # Somebody else in shot rules it out before it costs a
                    # full-size download.
                    if any(value >= INTRUDER for other, value in seen.items()
                           if not same_person(other, tag)):
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
        tagger = owner[tag]
        candidates = sorted(shortlist[tag], reverse=True)[:PER_CHARACTER * 4]
        kept, prints = [], []
        scored = []
        for _score, frame in candidates:
            image = image_from(fetch(FULL.format(frame), tries=2))
            if image is None or dull(image):
                continue
            reading = tagger.read(image)
            # Who it is, from the model that knows them; what kind of shot
            # it is, from the model the bars were set against.
            if scene_reader is not None and tagger is not scene_reader:
                reading = (reading[0], scene_reader.read(image)[1])
            rest = reading[1]
            if not tagger.alone(image, tag, reading):
                continue
            # No face, no picture: this rules out the shot of a shoulder
            # against a curtain, and the one where she is a dot in a field.
            if not shows_face(rest):
                continue
            # Right person, on her own, face in shot - and still unusable if
            # the room is unlit or the shot is one eye.
            if not visible(image, rest):
                continue
            # The cascade is unreliable as a gate but useful as a hint: when
            # it does find a face, the crop can be built around it.
            box = biggest_face(image)
            scored.append((
                quality(image, rest),
                fingerprint(image),
                FULL.format(frame),
                episode_of.get(frame, ""),
                ([int(v) for v in box] + [image.width, image.height])
                if box is not None else None,
            ))

        # Best first, then drop repeats, and stop one episode filling the
        # album with a single scene.
        from collections import Counter

        per_episode = Counter()
        for _rank, mark, url, episode, box in sorted(scored,
                                                     key=lambda row: -row[0]):
            if any(alike(mark, other) for other in prints):
                continue
            if episode and per_episode[episode] >= PER_EPISODE:
                continue
            per_episode[episode] += 1
            prints.append(mark)
            kept.append(url)
            if box:
                faces[url] = box
            if len(kept) >= PER_CHARACTER:
                break
        if kept:
            found[key] = kept

    # Where each face sits, so the crop is built around it rather than
    # guessed at.
    if faces:
        known = {}
        if os.path.exists(FACES):
            with io.open(FACES, encoding="utf-8") as handle:
                known = json.load(handle)
        known.update(faces)
        with io.open(FACES, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(known, handle, ensure_ascii=False)
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
    parser.add_argument("--one-model", action="store_true",
                        help="WD only, skipping the characters it cannot name")
    parser.add_argument("--skip-swept", action="store_true",
                        help="carry on an interrupted top-up rather than"
                             " starting it over from the first series")
    parser.add_argument("--need", type=int, default=0,
                        help="only look for characters who have fewer than"
                             " this many frames already")
    parser.add_argument("--series", default="",
                        help="only this series, matched loosely")
    parser.add_argument("--episodes", type=int, default=EPISODES,
                        help="how many episodes to spread the sample across")
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

    # Whoever WD knows is WD's: it is quicker and it is sure of itself. The
    # rest go to Camie, which knows ten times as many characters and is less
    # certain of each, so it is held to a higher bar in return. Camie is only
    # loaded if somebody actually needs it - it is 856MB.
    second = None
    if not args.one_model:
        try:
            from camie import CamieTagger
            second = CamieTagger(keep_above=0.20)
            second.label = "Camie"
            second.shortlist_at = CAMIE_SHORTLIST
            second.confirm_at = CAMIE_CONFIRM
            second.margin = CAMIE_MARGIN
        except Exception as error:  # noqa: BLE001 - WD alone still works
            print(f"  (second tagger unavailable: {type(error).__name__})")

    known = {}
    strangers = extra = 0
    for series, people in plan.items():
        mine, theirs = [], []
        for key, tag, row in people:
            tag = ALIASES.get(tag, tag)
            if tag in tagger.characters:
                mine.append((key, tag, row))
            elif second is not None and tag in second.characters:
                theirs.append((key, tag, row))
            else:
                strangers += 1
        extra += len(theirs)
        if mine or theirs:
            known[series] = [(tagger, mine), (second, theirs)]
    total_people = sum(len(p) for groups in known.values()
                       for _t, p in groups)
    print(f"{total_people:,} of the top {args.top:,} can be recognised,"
          f" across {len(known):,} series")
    print(f"  {total_people - extra:,} by WD, {extra:,} only by Camie")
    print(f"  {strangers:,} are in neither vocabulary,"
          f" {unknown:,} have no tag at all\n")

    # Always built on top of what is already there. A sweep of one series
    # used to write a file holding that one series, which quietly threw away
    # every frame found before it - and the file is the only record of them.
    frames = {}
    if os.path.exists(args.out):
        frames = json.load(io.open(args.out, encoding="utf-8"))
        print(f"building on {len(frames):,} characters already found")

    if args.need:
        # A top-up: keep only the people still short, and the series they are
        # in. A series where everybody is full is not worth opening again.
        short = {}
        for series, groups in known.items():
            wanting = [(tagger, [(key, tag, row) for key, tag, row in people
                                 if len(frames.get(key) or []) < args.need])
                       for tagger, people in groups]
            if any(people for _tagger, people in wanting):
                short[series] = wanting
        known = short
        waiting = sum(len(p) for groups in known.values() for _t, p in groups)
        print(f"topping up {waiting:,} characters"
              f" who have fewer than {args.need}, across {len(known):,} series")

    if args.series:
        wanted = args.series.lower()
        known = {series: people for series, people in known.items()
                 if wanted in series.lower()}
        print(f"limited to {len(known)} series matching {args.series!r}")

    done = json.load(io.open(args.out + ".series", encoding="utf-8")) \
        if args.resume and os.path.exists(args.out + ".series") else []
    # A top-up is deliberately going back over swept series, so the record of
    # what has been done is not a reason to skip - unless this is the same
    # top-up carrying on after being interrupted, which is what --skip-swept
    # says. A long sweep gets stopped to let the frames it has already found
    # be cropped and shipped, and starting it from the top each time means
    # the back half of the roster is never reached.
    if args.skip_swept:
        done = set(done)
    else:
        done = set() if (args.need or args.series) else set(done)

    started, scanned = time.time(), 0
    order = sorted(known.items(),
                   key=lambda item: min([r.get("claim_rank") or 10 ** 9
                                         for _tagger, people in item[1]
                                         for _k, _t, r in people]
                                        or [10 ** 9]))
    for number, (series, people) in enumerate(order, 1):
        if series in done:
            continue
        try:
            got = harvest(people, series, args.budget,
                          args.episodes, scene_reader=tagger)
        except KeyboardInterrupt:
            break
        except Exception as error:  # noqa: BLE001 - one series must not end a sweep
            print(f"  {series}: {type(error).__name__}")
            got = {}

        for key, urls in got.items():
            existing = frames.get(key) or []
            merged = existing + [url for url in urls if url not in existing]
            frames[key] = merged[:PER_CHARACTER]
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
