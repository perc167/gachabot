"""Adds characters AniList does not carry: games and Western animation.

    python tools/add_external.py --source overwatch --dry-run
    python tools/add_external.py --source all

AniList is an anime and manga database. Avatar, Overwatch, Undertale,
Deltarune, Doki Doki Literature Club and Fortnite are none of those, and
searching AniList for them returns only coincidental name matches - "Zuko"
finds Nezuko Kamado. So each franchise's names and art come from its own
public API instead, and the records are marked with where they came from.

One honest caveat. Everyone sourced from AniList carries a real favourites
count, which is what decides their rank and therefore their value. Nothing
here has an equivalent anywhere, so their placement is an editorial judgement
rather than measured popularity. The tiers below state that judgement openly,
and they are calibrated against the shipped roster so a lead lands roughly
where a mid-tier anime lead does rather than anywhere near the top.

Art is linked, never copied - the same arrangement the AniList roster uses.
The images stay on each publisher's or wiki's own servers.
"""
import argparse
import importlib.util
import io
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")
MANIFEST = os.path.join(ROOT, "data", "extra_characters.json")

# Calibrated against the 100,000-character roster. These favourites counts
# place a character at about the rank in the comment, which is what sets their
# value. Nothing invented is allowed anywhere near the top of the pool.
LEAD = 746        # about rank 2,000  -> ~136 karuda
SECONDARY = 39    # about rank 15,000 -> ~43 karuda
COSMETIC = 5      # about rank 40,000 -> ~25 karuda, for Fortnite outfits


def fetch(url: str, attempt: int = 0):
    request = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "gachabot-external/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        if attempt < 3:
            time.sleep(2 * (attempt + 1))
            return fetch(url, attempt + 1)
        raise RuntimeError(f"{url}: {error}") from error


def usable_image(url: str) -> str:
    """The URL back if it really serves an image, otherwise nothing.

    Having a link is not the same as being able to show it. Fandom returns
    image URLs through its API perfectly happily and then answers 403 to
    anyone fetching them, Discord included - so trusting the API would ship a
    roster of broken embeds. Every link is therefore fetched once and kept
    only if an image comes back.
    """
    if not url or not url.startswith("http"):
        return ""
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; gachabot/1.0)",
        "Accept": "image/*,*/*",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status == 200 and response.headers.get(
                    "Content-Type", "").startswith("image/"):
                return url
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    return ""


def record(name, series, image_url, favourites, source):
    return {
        "name": name,
        "series": series,
        "image_url": image_url,
        "likes": 0,
        "favourites": favourites,
        "source": source,
    }


# --------------------------------------------------------------------------
# Fandom, for the two sprite games and the visual novel. Its MediaWiki API is
# documented and public; pageimages hands back the page's lead image.
# --------------------------------------------------------------------------

def fandom_image(wiki: str, page: str) -> str:
    url = (f"https://{wiki}.fandom.com/api.php?action=query&format=json"
           f"&prop=pageimages&piprop=original&redirects=1&titles="
           + urllib.parse.quote(page))
    try:
        pages = fetch(url)["query"]["pages"]
    except (RuntimeError, KeyError):
        return ""
    entry = next(iter(pages.values()), {})
    return (entry.get("original") or {}).get("source") or ""


def from_fandom(wiki: str, series: str, leads, rest, source) -> list:
    rows, artless = [], 0
    for names, weight in ((leads, LEAD), (rest, SECONDARY)):
        for name in names:
            image = usable_image(fandom_image(wiki, name))
            if not image:
                artless += 1
            rows.append(record(name, series, image, weight, source))
            time.sleep(0.3)
    if artless:
        print(f"    {artless} of {len(rows)} have no usable art")
    return rows


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

AVATAR_LEADS = ["Aang", "Katara", "Sokka", "Toph Beifong", "Zuko", "Iroh",
                "Azula", "Appa", "Momo"]
AVATAR_REST = ["Suki", "Mai", "Ty Lee", "Ozai", "Zhao", "Yue", "Jet", "Haru",
               "Pakku", "Hakoda", "Bumi", "Long Feng", "Piandao", "Ursa",
               "Kya", "Gyatso", "Teo", "June", "Kanna", "Roku", "Kyoshi",
               "Combustion Man", "Hama", "Jeong Jeong", "Song", "Tui",
               "La", "Wan Shi Tong", "Joo Dee", "Ty Lee"]


def source_avatar() -> list:
    """Avatar: The Last Airbender, via the community Last Airbender API.

    Searching by name returns disambiguation entries too - "Aang" also finds
    "Aang (games)" - so an exact name match is preferred over anything
    parenthesised.
    """
    rows, missing, seen = [], [], set()
    for names, weight in ((AVATAR_LEADS, LEAD), (AVATAR_REST, SECONDARY)):
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            url = ("https://last-airbender-api.fly.dev/api/v1/characters?name="
                   + urllib.parse.quote(name))
            try:
                hits = fetch(url)
            except RuntimeError:
                hits = []
            if isinstance(hits, dict):
                hits = [hits]
            exact = [h for h in hits if (h.get("name") or "") == name]
            best = (exact or hits or [None])[0]
            photo = usable_image((best or {}).get("photoUrl") or "")
            if not photo:
                missing.append(name)
            rows.append(record(name, "Avatar: The Last Airbender",
                               photo, weight, "last-airbender-api"))
            time.sleep(0.3)
    if missing:
        print(f"    {len(missing)} of {len(rows)} have no usable art")
    return rows


OVERWATCH_LEADS = {"Tracer", "D.Va", "Genji", "Mercy", "Reinhardt",
                   "Widowmaker", "Hanzo", "Reaper", "Winston", "Soldier: 76"}


def source_overwatch() -> list:
    """Every Overwatch hero, with Blizzard's own portrait art."""
    rows = []
    for hero in fetch("https://overfast-api.tekrop.fr/heroes"):
        portrait = hero.get("portrait") or ""
        if not portrait.startswith("http"):
            continue
        weight = LEAD if hero["name"] in OVERWATCH_LEADS else SECONDARY
        rows.append(record(hero["name"], "Overwatch", portrait, weight,
                           "overfast-api"))
    return rows


UNDERTALE_LEADS = ["Sans", "Papyrus", "Frisk", "Toriel", "Undyne", "Alphys",
                   "Flowey", "Chara", "Asgore Dreemurr", "Mettaton",
                   "Asriel Dreemurr"]
UNDERTALE_REST = ["Napstablook", "Muffet", "Temmie", "Monster Kid", "Grillby",
                  "Gerson", "Bratty", "Catty", "Burgerpants", "Jerry",
                  "Snowdrake", "Aaron", "Woshua", "Doggo", "Lesser Dog",
                  "Greater Dog", "Dogamy", "Dogaressa", "Mad Dummy", "Glyde",
                  "W. D. Gaster", "Shyren", "Onionsan", "Nice Cream Guy"]

DELTARUNE_LEADS = ["Kris", "Susie", "Ralsei", "Lancer", "Noelle Holiday",
                   "Spamton", "Jevil", "Queen", "King", "Berdly"]
DELTARUNE_REST = ["Seam", "Rouxls Kaard", "Catti", "Hathy", "Clover",
                  "Rudolph Holiday", "Dess Holiday", "Malius", "Tenna",
                  "Sweet Cap'n Cakes", "Werewire", "Elnina", "Mike",
                  "Spamton G. Spamton"]

DDLC_LEADS = ["Monika", "Sayori", "Yuri", "Natsuki"]


def source_undertale() -> list:
    return from_fandom("undertale", "Undertale",
                       UNDERTALE_LEADS, UNDERTALE_REST, "undertale.fandom")


def source_deltarune() -> list:
    return from_fandom("deltarune", "Deltarune",
                       DELTARUNE_LEADS, DELTARUNE_REST, "deltarune.fandom")


def source_ddlc() -> list:
    return from_fandom("doki-doki-literature-club",
                       "Doki Doki Literature Club!",
                       DDLC_LEADS, [], "ddlc.fandom")


# Series Epic tags as licensed. Necessary but nowhere near sufficient: plenty
# of collabs carry no series at all.
FORTNITE_COLLAB_SERIES = {"MARVEL SERIES", "DC SERIES", "Star Wars Series",
                          "Gaming Legends Series", "Icon Series"}

# Licensed sets that carry no series tag, read off the data by hand. "Avatar"
# here is the Last Airbender crossover - the real cast is added separately.
FORTNITE_LICENSED_SETS = {
    "adventure time", "avatar", "balenciaga fit", "celebration of hogwarts",
    "cobra kai", "coachella", "dragon ball", "el chapulín colorado",
    "f1 racers", "family guy", "ghostbusters", "guardians of the globe",
    "jujutsu kaisen", "lego ninjago®", "mighty morphin", "my hero academia",
    "mystery inc.", "nba 75", "nike football", "pirates of the caribbean",
    "stranger things", "the simpsons", "three stripe squad", "tmnt",
    "transformers",
}


def source_fortnite(existing_names) -> list:
    """Epic's own outfits, with the crossovers taken out.

    Three filters, because one is not enough. Epic's own "series" tag catches
    Marvel, DC, Star Wars and the rest, but a great many crossovers carry no
    tag at all - Naruto, Gojo, Eren and Mikasa all sail straight through it.
    So licensed sets are excluded by name as well, and finally any outfit
    whose name already belongs to somebody in the anime roster is dropped:
    almost always that is the crossover skin of that very character, and even
    when it is not, a second Kong in the pool helps nobody.
    """
    data = fetch("https://fortnite-api.com/v2/cosmetics/br")["data"]
    rows, seen = [], set()
    dropped = {"series": 0, "set": 0, "duplicate name": 0, "no art": 0}
    for item in data:
        if (item.get("type") or {}).get("value") != "outfit":
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        if ((item.get("series") or {}).get("value") or "") in FORTNITE_COLLAB_SERIES:
            dropped["series"] += 1
            continue
        if ((item.get("set") or {}).get("value") or "").strip().lower() \
                in FORTNITE_LICENSED_SETS:
            dropped["set"] += 1
            continue
        if name.lower() in existing_names or name.lower() in seen:
            dropped["duplicate name"] += 1
            continue
        images = item.get("images") or {}
        art = images.get("icon") or images.get("featured") or images.get("smallIcon")
        if not art or not str(art).startswith("http"):
            dropped["no art"] += 1
            continue
        art = str(art)
        seen.add(name.lower())
        rows.append(record(name, "Fortnite", art, COSMETIC, "fortnite-api"))
    print("    dropped: " + ", ".join(f"{v:,} {k}" for k, v in dropped.items()))
    return rows


SOURCES = {
    "avatar": source_avatar,
    "overwatch": source_overwatch,
    "undertale": source_undertale,
    "deltarune": source_deltarune,
    "ddlc": source_ddlc,
    "fortnite": source_fortnite,
}


def load_rerank():
    """Borrow the ranking from add_series so both tools agree exactly."""
    path = os.path.join(ROOT, "tools", "add_series.py")
    spec = importlib.util.spec_from_file_location("add_series", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.rerank


def write_roster(rows, path):
    tmp = path + ".writing"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("[\n")
        handle.write(",\n".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":"))
            for row in rows))
        handle.write("\n]\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="all",
                        help="one of: " + ", ".join(SOURCES) + ", or all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--data", default=DATA)
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    wanted = list(SOURCES) if args.source == "all" else args.source.split(",")
    unknown = [s for s in wanted if s not in SOURCES]
    if unknown:
        print(f"Unknown source(s): {', '.join(unknown)}")
        return 1

    sys.path.insert(0, ROOT)
    import utils  # noqa: E402  - needs ROOT on the path first

    rows = list(utils.iter_roster(args.data))
    pairs = {(r["name"], r["series"]) for r in rows}
    names = {r["name"].lower() for r in rows}
    print(f"Pool holds {len(rows):,} characters\n")

    added = []
    for name in wanted:
        print(f"  {name}:")
        fetched = (SOURCES[name](names) if name == "fortnite"
                   else SOURCES[name]())
        fresh = [r for r in fetched if (r["name"], r["series"]) not in pairs]
        for row in fresh:
            pairs.add((row["name"], row["series"]))
        skipped = len(fetched) - len(fresh)
        print(f"    {len(fresh):,} new"
              + (f", {skipped:,} already in" if skipped else ""))
        added.extend(fresh)

    if not added:
        print("\nNothing new to add.")
        return 0

    by_series = {}
    for row in added:
        by_series[row["series"]] = by_series.get(row["series"], 0) + 1
    print(f"\n{len(added):,} characters to add:")
    for series, count in sorted(by_series.items(), key=lambda kv: -kv[1]):
        print(f"   {count:>5,}  {series}")

    if args.dry_run:
        print("\nDry run, nothing written.")
        return 0

    # A manifest of everything sourced outside AniList, so a full roster
    # re-fetch - which rewrites characters.json from scratch - can put them
    # back rather than losing them.
    manifest = []
    if os.path.exists(MANIFEST):
        manifest = list(utils.iter_roster(MANIFEST))
    known = {(r["name"], r["series"]) for r in manifest}
    manifest.extend(r for r in added if (r["name"], r["series"]) not in known)
    write_roster(manifest, MANIFEST)

    rows.extend(added)
    load_rerank()(rows)
    write_roster(rows, args.data)

    print(f"\nWrote {len(rows):,} characters to {args.data}")
    print(f"  manifest of non-AniList additions: {len(manifest):,}"
          f" in {MANIFEST}")
    placed = sorted(added, key=lambda r: r["like_rank"])
    print("\n  where they landed:")
    for row in placed[:6]:
        print(f"   #{row['like_rank']:>6,}  {row['base_karuda']:>4} karuda  "
              f"{row['name']} ({row['series']})"[:72])
    print("   ...")
    for row in placed[-3:]:
        print(f"   #{row['like_rank']:>6,}  {row['base_karuda']:>4} karuda  "
              f"{row['name']} ({row['series']})"[:72])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
