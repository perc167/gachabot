"""Fills in gender for the characters AniList does not carry.

    python tools/set_gender.py --dry-run

tools/fetch_gender.py asks AniList, which knows nothing about Overwatch,
Avatar, Undertale, Deltarune or DDLC. Without this those 2,040 characters
have no gender at all, so $wg and $hg - roll a girl or a guy from a game -
find nobody and look broken.

Only characters whose gender is not in question are listed. Kris, Frisk and
Chara are written as ambiguous on purpose and stay blank; so do the Fortnite
outfits, which are costumes rather than people. Blank means "rolls under $m
only", which is the honest answer for all of them.
"""
import argparse
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "characters.json")
MANIFEST = os.path.join(ROOT, "data", "extra_characters.json")

FEMALE = {
    "Overwatch": [
        "Ana", "Ashe", "Brigitte", "D.Va", "Echo", "Illari", "Juno", "Kiriko",
        "Mei", "Mercy", "Moira", "Orisa", "Pharah", "Sojourn", "Sombra",
        "Symmetra", "Tracer", "Widowmaker", "Zarya", "Junker Queen", "Freja",
    ],
    "Avatar: The Last Airbender": [
        "Katara", "Toph Beifong", "Azula", "Suki", "Mai", "Ty Lee", "Yue",
        "Ursa", "Kya", "Kanna", "Hama", "Song", "Joo Dee", "Kyoshi", "June",
    ],
    "Undertale": [
        "Toriel", "Undyne", "Alphys", "Muffet", "Bratty", "Catty", "Shyren",
    ],
    "Deltarune": [
        "Susie", "Noelle Holiday", "Queen", "Catti", "Hathy", "Clover",
        "Dess Holiday",
    ],
    "Doki Doki Literature Club!": ["Monika", "Sayori", "Yuri", "Natsuki"],
    "Disco Elysium": [
        "Klaasje", "Joyce Messier", "Cunoesse", "Sylvie", "Ruby", "Lena",
        "Acele", "Soona", "Annette", "Plaisance", "Judit Minot",
        "Dolores Dei",
    ],
    # The twelve sinners, plus the two who are not in question. Dante is
    # written as ambiguous on purpose and stays blank.
    "Limbus Company": [
        "Faust", "Don Quixote", "Ry\u014dsh\u016b", "Ishmael", "Rodion",
        "Outis", "Charon",
    ],
}

MALE = {
    "Overwatch": [
        "Baptiste", "Cassidy", "Doomfist", "Genji", "Hanzo", "Hazard",
        "Junkrat", "Lifeweaver", "Lúcio", "Mauga", "Ramattra", "Reaper",
        "Reinhardt", "Roadhog", "Sigma", "Soldier: 76", "Torbjörn", "Winston",
        "Zenyatta",
    ],
    "Avatar: The Last Airbender": [
        "Aang", "Sokka", "Zuko", "Iroh", "Ozai", "Zhao", "Jet", "Haru",
        "Pakku", "Hakoda", "Bumi", "Long Feng", "Piandao", "Gyatso", "Teo",
        "Roku", "Combustion Man", "Jeong Jeong", "Wan Shi Tong", "Appa",
        "Momo",
    ],
    "Undertale": [
        "Sans", "Papyrus", "Asgore Dreemurr", "Flowey", "Asriel Dreemurr",
        "Mettaton", "Grillby", "Gerson", "Burgerpants", "W. D. Gaster",
        "Doggo", "Lesser Dog", "Greater Dog", "Dogamy", "Snowdrake", "Aaron",
        "Woshua", "Onionsan",
    ],
    "Deltarune": [
        "Ralsei", "Lancer", "King", "Berdly", "Spamton", "Jevil", "Seam",
        "Rouxls Kaard", "Rudolph Holiday", "Mike", "Spamton G. Spamton",
    ],
    "Disco Elysium": [
        "Harry Du Bois", "Kim Kitsuragi", "Cuno", "Measurehead",
        "Evrart Claire", "Edgar Claire", "Garte", "Titus Hardie",
        "Gaston Martin", "Siileng", "Steban", "Ulixes Richaud",
        "Idiot Doom Spiral", "Trant Heidelstam", "Jean Vicquemare", "Morell",
    ],
    "Limbus Company": [
        "Yi Sang", "Meursault", "Hong Lu", "Heathcliff", "Sinclair",
        "Gregor", "Vergilius",
    ],
}


def build() -> dict:
    wanted = {}
    for table, gender in ((FEMALE, "Female"), (MALE, "Male")):
        for series, names in table.items():
            for name in names:
                wanted[(name, series)] = gender
    return wanted


def write(rows, path):
    tmp = path + ".writing"
    with io.open(tmp, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("[\n")
        handle.write(",\n".join(
            json.dumps(r, ensure_ascii=False, separators=(",", ":"))
            for r in rows))
        handle.write("\n]\n")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    sys.path.insert(0, ROOT)
    import utils  # noqa: E402

    wanted = build()
    print(f"{len(wanted)} characters to set\n")

    unmatched = set(wanted)
    for path in (DATA, MANIFEST):
        if not os.path.exists(path):
            continue
        rows = list(utils.iter_roster(path))
        changed = 0
        for row in rows:
            key = (row["name"], row["series"])
            if key in wanted and row.get("gender") != wanted[key]:
                row["gender"] = wanted[key]
                changed += 1
            unmatched.discard(key)
        print(f"  {os.path.basename(path)}: {changed} updated")
        if not args.dry_run and changed:
            write(rows, path)

    if unmatched:
        print(f"\n{len(unmatched)} names matched nothing in the roster:")
        for name, series in sorted(unmatched):
            print(f"   {name} ({series})")
    if args.dry_run:
        print("\nDry run, nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
