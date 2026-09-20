"""Downloads art for the characters no public CDN will serve us.

    python tools/fetch_local_art.py --dry-run
    python tools/fetch_local_art.py

Fandom hands out image URLs through its API and then answers 403 to anything
fetching them from elsewhere - that is hotlink protection, and it is why
Avatar, Undertale, Deltarune and DDLC came in without pictures. A request
carrying the wiki's own Referer, which is what a browser sends when you read
the page, is served normally.

So the art is fetched once, shrunk, and kept in assets/characters/. The bot
attaches those files to its messages rather than linking them: nothing is
re-hosted anywhere public, and the images travel with the bot.

Stored as "local:<filename>" in the roster, which utils.character_embed turns
into an attachment reference.
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
DATA = os.path.join(ROOT, "data", "characters.json")
MANIFEST = os.path.join(ROOT, "data", "extra_characters.json")
ART = os.path.join(ROOT, "assets", "characters")

# Which wiki holds each series. Anything not listed is left alone.
WIKIS = {
    "Avatar: The Last Airbender": "avatar",
    "Undertale": "undertale",
    "Deltarune": "deltarune",
    "Doki Doki Literature Club!": "doki-doki-literature-club",
    "Disco Elysium": "discoelysium",
    "Limbus Company": "limbuscompany",
}

BROWSER = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
           " (KHTML, like Gecko) Chrome/125.0 Safari/537.36")

# Sprites are small already; portraits are not. Anything wider than this is
# scaled down, which keeps the repository sane without a visible difference
# on a Discord card.
MAX_WIDTH = 512


def slug(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "character"


def api(wiki: str, params: dict):
    url = (f"https://{wiki}.fandom.com/api.php?"
           + urllib.parse.urlencode({"format": "json", **params}))
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "User-Agent": "gachabot-art/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {}


def page_image(wiki: str, title: str) -> str:
    """The lead image of a character's page, if it has one."""
    data = api(wiki, {"action": "query", "prop": "pageimages",
                      "piprop": "original", "redirects": "1", "titles": title})
    pages = (data.get("query") or {}).get("pages") or {}
    entry = next(iter(pages.values()), {})
    return (entry.get("original") or {}).get("source") or ""


def search_page(wiki: str, name: str) -> str:
    """Fall back to searching the wiki when the exact title has no page."""
    data = api(wiki, {"action": "query", "list": "search", "srlimit": "1",
                      "srsearch": name})
    hits = ((data.get("query") or {}).get("search") or [])
    return hits[0]["title"] if hits else ""


def download(url: str, wiki: str) -> bytes:
    """Fetch an image the way a reader of that wiki does.

    Without the Referer the CDN answers 403: that is the hotlink protection,
    and it is aimed at other sites embedding the image, not at reading it.
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": BROWSER,
        "Accept": "image/avif,image/webp,image/png,*/*",
        "Referer": f"https://{wiki}.fandom.com/",
    })
    with urllib.request.urlopen(request, timeout=60) as response:
        if not response.headers.get("Content-Type", "").startswith("image/"):
            raise ValueError("not an image")
        return response.read()


def shrink(raw: bytes, name: str) -> tuple:
    """Scale a large image down. Returns (bytes, extension)."""
    try:
        from PIL import Image
    except ImportError:
        return raw, os.path.splitext(name)[1] or ".png"

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:  # noqa: BLE001 - a file we cannot read is a file we skip
        return raw, os.path.splitext(name)[1] or ".png"

    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")
    if image.width > MAX_WIDTH:
        height = round(image.height * MAX_WIDTH / image.width)
        image = image.resize((MAX_WIDTH, height), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue(), ".png"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data", default=DATA)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    sys.path.insert(0, ROOT)
    import utils  # noqa: E402

    rows = list(utils.iter_roster(args.data))
    wanted = [r for r in rows
              if not r.get("image_url") and r["series"] in WIKIS]
    print(f"{len(wanted)} characters need art\n")
    if not args.dry_run:
        os.makedirs(ART, exist_ok=True)

    found, missing, total_bytes = {}, [], 0
    for row in wanted:
        wiki = WIKIS[row["series"]]
        url = page_image(wiki, row["name"])
        if not url:
            title = search_page(wiki, f"{row['name']}")
            if title:
                url = page_image(wiki, title)
        if not url:
            missing.append(f"{row['name']} ({row['series']})")
            continue

        filename = f"{slug(row['series'])}-{slug(row['name'])}"
        try:
            raw = download(url, wiki)
            raw, ext = shrink(raw, url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
                ValueError, OSError) as error:
            missing.append(f"{row['name']} ({type(error).__name__})")
            continue

        filename += ext
        total_bytes += len(raw)
        found[(row["name"], row["series"])] = filename
        print(f"  {len(found):>3}. {row['name']:<24} {len(raw) / 1024:>6.0f} KB"
              f"  {filename}")
        if not args.dry_run:
            with open(os.path.join(ART, filename), "wb") as handle:
                handle.write(raw)
        time.sleep(0.25)

    print(f"\n{len(found)} downloaded, {total_bytes / 1e6:.1f} MB total")
    if missing:
        print(f"{len(missing)} still without art:")
        for note in missing:
            print(f"   {note}")

    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0
    if not found:
        return 0

    # Point the roster at the local files. The bot turns "local:" into an
    # attachment when it builds the card.
    for path in (args.data, MANIFEST):
        if not os.path.exists(path):
            continue
        entries = list(utils.iter_roster(path))
        changed = 0
        for row in entries:
            key = (row["name"], row["series"])
            if key in found and not row.get("image_url"):
                row["image_url"] = "local:" + found[key]
                changed += 1
        tmp = path + ".writing"
        with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("[\n")
            handle.write(",\n".join(
                json.dumps(r, ensure_ascii=False, separators=(",", ":"))
                for r in entries))
            handle.write("\n]\n")
        os.replace(tmp, path)
        print(f"  updated {changed:,} rows in {os.path.basename(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
