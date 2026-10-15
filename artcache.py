"""Art the bot has sent before, kept so Discord stops fetching it again.

A linked picture goes out as a URL and Discord fetches it when it draws the
embed. That fetch is the pause between a roll appearing and its picture
filling in, and it happens again whenever Discord's own copy has aged out -
which, picking at random from ten thousand pictures, is most rolls.

A picture the bot has on disk goes out as an attachment instead, and arrives
with the message. So: the first roll of a picture links it, the way it
always did, and asks for a copy in the background. Every roll after that
attaches the copy.

The folder has a cap and the least recently used go first, so it fills with
whoever a server actually rolls rather than with the whole roster. All of
them would be about a gigabyte; a server's own few hundred is tens of
megabytes.

Set ART_CACHE=0 to turn the whole thing off and go back to linking.
"""
import hashlib
import os
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.environ.get("ART_CACHE_DIR") or os.path.join(HERE, "data",
                                                            "artcache")
ENABLED = str(os.environ.get("ART_CACHE", "1")).lower() not in ("0", "off",
                                                                "no", "false")
CAP_BYTES = int(os.environ.get("ART_CACHE_MB", "500")) * 1024 * 1024

# One picture. Past this it is a wallpaper somebody linked, and uploading it
# on every roll would cost more than the fetch it saves.
BIGGEST = 8 * 1024 * 1024
KINDS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
UA = {"User-Agent": "Mozilla/5.0 (compatible; PaperBot/1.0; +https://discord.com)"}

# Asked for, not yet fetched. A plain list and a set beside it: the set is
# what stops the same picture being queued by every server that rolls it in
# the same minute.
_wanted = []
_asked = set()
MOST_QUEUED = 4000


def name_for(url: str) -> str:
    """What a picture is called on disk.

    The URL hashed, not any part of its path: two sites both serving
    4.jpg are not the same picture, and a name out of a URL is a name
    chosen by somebody else.
    """
    ending = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if ending not in KINDS:
        ending = ".jpg"
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ending


def path_for(url: str) -> str:
    return os.path.join(CACHE_DIR, name_for(url))


def worth_keeping(url) -> bool:
    """Is this a picture we could hold a copy of?"""
    url = str(url or "")
    return bool(ENABLED and url.startswith(("http://", "https://")))


def cached(url):
    """The copy on disk, or None.

    Touches it on the way past, so the sweep measures how recently a
    picture was rolled rather than when it was downloaded.
    """
    if not worth_keeping(url):
        return None
    path = path_for(str(url))
    try:
        os.utime(path, None)
    except OSError:
        return None
    return path


def want(url):
    """Ask for a copy of this, whenever the keeper next runs."""
    url = str(url or "")
    if not worth_keeping(url) or url in _asked:
        return
    if len(_asked) >= MOST_QUEUED:
        return
    _asked.add(url)
    _wanted.append(url)


def waiting(limit: int = 12) -> list:
    """The next few to fetch, taken off the queue."""
    out = _wanted[:limit]
    del _wanted[:limit]
    for url in out:
        _asked.discard(url)
    return out


def queued() -> int:
    return len(_wanted)


def fetch(url: str, timeout: int = 20) -> bytes:
    """The bytes behind a URL. Blocking: callers hand it to a thread."""
    try:
        request = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > BIGGEST:
                return b""
            return response.read(BIGGEST + 1)
    except (urllib.error.URLError, OSError, ValueError):
        return b""


def store(url: str, data: bytes) -> bool:
    """Keep a copy. Written beside and moved into place, so a half-written
    file is never the one an embed points at."""
    if not data or len(data) > BIGGEST:
        return False
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = path_for(url)
        part = path + ".part"
        with open(part, "wb") as handle:
            handle.write(data)
        os.replace(part, path)
    except OSError:
        return False
    return True


def sweep(cap: int = None) -> int:
    """Drop the least recently rolled until the folder is under its cap."""
    cap = CAP_BYTES if cap is None else cap
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return 0
    files = []
    for name in names:
        path = os.path.join(CACHE_DIR, name)
        try:
            files.append((os.path.getmtime(path), os.path.getsize(path), path))
        except OSError:
            continue
    total = sum(size for _when, size, _path in files)
    if total <= cap:
        return 0
    files.sort()                       # least recently touched first
    dropped = 0
    for _when, size, path in files:
        if total <= cap:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        dropped += 1
    return dropped


def holding() -> tuple:
    """(how many pictures, how many bytes) are kept right now."""
    try:
        names = os.listdir(CACHE_DIR)
    except OSError:
        return (0, 0)
    count = size = 0
    for name in names:
        try:
            size += os.path.getsize(os.path.join(CACHE_DIR, name))
            count += 1
        except OSError:
            continue
    return (count, size)
