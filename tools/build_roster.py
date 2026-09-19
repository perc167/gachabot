"""Generates data/characters.json.

Kakera value is worked out from two things, not typed in by hand:

  1. How famous the SERIES is. Naruto and One Piece are worth more than
     Steins;Gate, not because they are better, but because more people
     recognise them, so pulling one should feel like a bigger deal.

  2. How central the CHARACTER is to that series. Luffy outranks Chopper.

    base_kakera = series tier + role bonus

Edit the tables or the roster below and re-run this file to regenerate:

    python tools/build_roster.py

Art is deliberately left blank. Fill it in per character with $setimage,
using images you have the right to use. $missingart lists what still needs it.
"""
import json
import os

# How widely known the series is. Nothing to do with quality.
TIER_BASE = {
    "S": 80,  # household names, recognised well outside anime fandom
    "A": 64,  # very popular, instantly known inside the fandom
    "B": 50,  # well loved, more of a fandom pick
    "C": 40,  # niche or older
}

# How central the character is to their own series.
ROLE_BONUS = {
    "lead": 35,  # the story is about them
    "main": 18,  # core cast, on the poster
    "support": 6,  # recurring, memorable, not the focus
}

# series -> (fame tier, [(character, role), ...])
ROSTER = {
    "Naruto": ("S", [
        ("Naruto Uzumaki", "lead"), ("Sasuke Uchiha", "lead"),
        ("Sakura Haruno", "main"), ("Kakashi Hatake", "main"),
        ("Itachi Uchiha", "main"), ("Hinata Hyuga", "main"),
        ("Jiraiya", "main"), ("Gaara", "support"),
        ("Madara Uchiha", "support"), ("Rock Lee", "support"),
    ]),
    "One Piece": ("S", [
        ("Monkey D. Luffy", "lead"), ("Roronoa Zoro", "main"),
        ("Nami", "main"), ("Sanji", "main"),
        ("Nico Robin", "main"), ("Portgas D. Ace", "main"),
        ("Tony Tony Chopper", "support"), ("Trafalgar D. Water Law", "support"),
        ("Boa Hancock", "support"), ("Shanks", "support"),
    ]),
    "Dragon Ball": ("S", [
        ("Son Goku", "lead"), ("Vegeta", "lead"),
        ("Son Gohan", "main"), ("Piccolo", "main"),
        ("Bulma", "main"), ("Frieza", "main"),
        ("Trunks", "support"), ("Krillin", "support"),
    ]),
    "Pokemon": ("S", [
        ("Ash Ketchum", "lead"), ("Pikachu", "lead"),
        ("Misty", "main"), ("Brock", "main"),
        ("Jessie", "support"), ("James", "support"),
        ("Gary Oak", "support"), ("Serena", "support"),
    ]),
    "Attack on Titan": ("S", [
        ("Eren Yeager", "lead"), ("Mikasa Ackerman", "lead"),
        ("Levi Ackerman", "main"), ("Armin Arlert", "main"),
        ("Erwin Smith", "support"), ("Historia Reiss", "support"),
        ("Annie Leonhart", "support"), ("Sasha Blouse", "support"),
    ]),
    "Demon Slayer": ("S", [
        ("Tanjiro Kamado", "lead"), ("Nezuko Kamado", "lead"),
        ("Zenitsu Agatsuma", "main"), ("Inosuke Hashibira", "main"),
        ("Giyu Tomioka", "main"), ("Shinobu Kocho", "main"),
        ("Kyojuro Rengoku", "main"), ("Mitsuri Kanroji", "support"),
    ]),
    "My Hero Academia": ("A", [
        ("Izuku Midoriya", "lead"), ("Katsuki Bakugo", "main"),
        ("Ochaco Uraraka", "main"), ("Shoto Todoroki", "main"),
        ("All Might", "main"), ("Tsuyu Asui", "support"),
        ("Himiko Toga", "support"), ("Momo Yaoyorozu", "support"),
    ]),
    "Death Note": ("A", [
        ("Light Yagami", "lead"), ("L Lawliet", "lead"),
        ("Misa Amane", "main"), ("Ryuk", "main"),
        ("Near", "support"), ("Mello", "support"),
    ]),
    "Jujutsu Kaisen": ("A", [
        ("Yuji Itadori", "lead"), ("Satoru Gojo", "lead"),
        ("Megumi Fushiguro", "main"), ("Nobara Kugisaki", "main"),
        ("Ryomen Sukuna", "main"), ("Kento Nanami", "support"),
        ("Maki Zenin", "support"), ("Toge Inumaki", "support"),
    ]),
    "Fullmetal Alchemist: Brotherhood": ("A", [
        ("Edward Elric", "lead"), ("Alphonse Elric", "main"),
        ("Winry Rockbell", "main"), ("Roy Mustang", "main"),
        ("Riza Hawkeye", "main"), ("Ling Yao", "support"),
        ("Olivier Mira Armstrong", "support"),
    ]),
    "Bleach": ("A", [
        ("Ichigo Kurosaki", "lead"), ("Rukia Kuchiki", "lead"),
        ("Orihime Inoue", "main"), ("Uryu Ishida", "main"),
        ("Byakuya Kuchiki", "main"), ("Sosuke Aizen", "main"),
        ("Toshiro Hitsugaya", "support"), ("Yoruichi Shihoin", "support"),
    ]),
    "Sailor Moon": ("A", [
        ("Usagi Tsukino", "lead"), ("Ami Mizuno", "main"),
        ("Rei Hino", "main"), ("Makoto Kino", "main"),
        ("Minako Aino", "main"), ("Mamoru Chiba", "main"),
        ("Chibiusa", "support"), ("Hotaru Tomoe", "support"),
    ]),
    "Neon Genesis Evangelion": ("A", [
        ("Shinji Ikari", "lead"), ("Rei Ayanami", "lead"),
        ("Asuka Langley Soryu", "lead"), ("Misato Katsuragi", "main"),
        ("Kaworu Nagisa", "support"), ("Gendo Ikari", "support"),
        ("Mari Makinami", "support"),
    ]),
    "Spy x Family": ("A", [
        ("Anya Forger", "lead"), ("Loid Forger", "lead"),
        ("Yor Forger", "lead"), ("Bond Forger", "support"),
        ("Yuri Briar", "support"), ("Damian Desmond", "support"),
    ]),
    "Chainsaw Man": ("A", [
        ("Denji", "lead"), ("Makima", "lead"),
        ("Power", "main"), ("Aki Hayakawa", "main"),
        ("Himeno", "support"), ("Reze", "support"),
        ("Kobeni Higashiyama", "support"),
    ]),
    "Hunter x Hunter": ("A", [
        ("Gon Freecss", "lead"), ("Killua Zoldyck", "lead"),
        ("Kurapika", "main"), ("Leorio Paradinight", "main"),
        ("Hisoka Morow", "main"), ("Chrollo Lucilfer", "support"),
        ("Biscuit Krueger", "support"),
    ]),
    "Cowboy Bebop": ("B", [
        ("Spike Spiegel", "lead"), ("Faye Valentine", "main"),
        ("Jet Black", "main"), ("Edward Wong", "main"),
        ("Julia", "support"), ("Ein", "support"),
    ]),
    "Steins;Gate": ("B", [
        ("Rintaro Okabe", "lead"), ("Kurisu Makise", "lead"),
        ("Mayuri Shiina", "main"), ("Suzuha Amane", "support"),
        ("Itaru Hashida", "support"), ("Faris NyanNyan", "support"),
    ]),
    "Code Geass": ("B", [
        ("Lelouch vi Britannia", "lead"), ("C.C.", "lead"),
        ("Suzaku Kururugi", "main"), ("Kallen Stadtfeld", "main"),
        ("Nunnally vi Britannia", "support"),
        ("Euphemia li Britannia", "support"),
    ]),
    "Re:Zero": ("B", [
        ("Subaru Natsuki", "lead"), ("Rem", "lead"),
        ("Emilia", "lead"), ("Ram", "main"),
        ("Beatrice", "main"), ("Felt", "support"),
        ("Roswaal L Mathers", "support"),
    ]),
}


def build():
    characters = []
    for series, (tier, cast) in ROSTER.items():
        for name, role in cast:
            characters.append({
                "name": name,
                "series": series,
                "image_url": "",  # fill in with $setimage
                "likes": 0,
                "base_kakera": TIER_BASE[tier] + ROLE_BONUS[role],
            })
    characters.sort(key=lambda c: (-c["base_kakera"], c["series"], c["name"]))
    return characters


def main():
    characters = build()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "data", "characters.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(characters, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    print(f"Wrote {len(characters)} characters from {len(ROSTER)} series to {out}")
    spread = {}
    for character in characters:
        spread.setdefault(character["base_kakera"], 0)
        spread[character["base_kakera"]] += 1
    print("\nkakera value  characters")
    for value in sorted(spread, reverse=True):
        print(f"{value:>12}  {'#' * spread[value]} ({spread[value]})")


if __name__ == "__main__":
    main()
