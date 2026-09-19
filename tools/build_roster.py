"""Generates data/characters.json.

Kakera value is worked out from two things, not typed in by hand:

  1. How famous the SERIES is. Naruto and One Piece are worth more than
     Steins;Gate, not because they are better, but because more people
     recognise them, so pulling one should feel like a bigger deal.

  2. How central the CHARACTER is to that series. Luffy outranks Chopper.

    base_kakera = series tier + role bonus

Edit the tables or the roster below and re-run this file to regenerate:

    python tools/build_roster.py

Re-running is safe for a live bot: $import matches on name + series, so
existing characters are updated in place and nobody loses a claim.

Art is filled in separately by tools/fetch_art.py.
"""
import hashlib
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
    # ---------------- S tier ----------------
    "Naruto": ("S", [
        ("Naruto Uzumaki", "lead"), ("Sasuke Uchiha", "lead"),
        ("Sakura Haruno", "main"), ("Kakashi Hatake", "main"),
        ("Itachi Uchiha", "main"), ("Hinata Hyuga", "main"),
        ("Jiraiya", "main"), ("Tsunade", "main"), ("Orochimaru", "main"),
        ("Gaara", "support"), ("Madara Uchiha", "support"),
        ("Rock Lee", "support"), ("Shikamaru Nara", "support"),
        ("Neji Hyuga", "support"), ("Minato Namikaze", "support"),
        ("Obito Uchiha", "support"),
    ]),
    "One Piece": ("S", [
        ("Monkey D. Luffy", "lead"),
        ("Roronoa Zoro", "main"), ("Nami", "main"), ("Sanji", "main"),
        ("Nico Robin", "main"), ("Portgas D. Ace", "main"),
        ("Usopp", "main"), ("Franky", "main"), ("Brook", "main"),
        ("Tony Tony Chopper", "support"),
        ("Trafalgar D. Water Law", "support"), ("Boa Hancock", "support"),
        ("Shanks", "support"), ("Sabo", "support"), ("Jinbe", "support"),
        ("Dracule Mihawk", "support"),
    ]),
    "Dragon Ball": ("S", [
        ("Son Goku", "lead"), ("Vegeta", "lead"),
        ("Son Gohan", "main"), ("Piccolo", "main"), ("Bulma", "main"),
        ("Frieza", "main"), ("Trunks", "main"), ("Krillin", "main"),
        ("Beerus", "main"),
        ("Cell", "support"), ("Majin Buu", "support"),
        ("Android 18", "support"), ("Master Roshi", "support"),
        ("Chi-Chi", "support"), ("Tien Shinhan", "support"),
        ("Son Goten", "support"),
    ]),
    "Pokemon": ("S", [
        ("Ash Ketchum", "lead"), ("Pikachu", "lead"),
        ("Misty", "main"), ("Brock", "main"), ("Serena", "main"),
        ("Dawn", "main"), ("May", "main"), ("Gary Oak", "main"),
        ("Jessie", "support"), ("James", "support"), ("Meowth", "support"),
        ("Cynthia", "support"), ("Red", "support"), ("Eevee", "support"),
        ("Charizard", "support"), ("Mewtwo", "support"),
    ]),
    "Attack on Titan": ("S", [
        ("Eren Yeager", "lead"), ("Mikasa Ackerman", "lead"),
        ("Levi Ackerman", "main"), ("Armin Arlert", "main"),
        ("Erwin Smith", "main"), ("Hange Zoe", "main"),
        ("Reiner Braun", "main"), ("Zeke Yeager", "main"),
        ("Historia Reiss", "support"), ("Annie Leonhart", "support"),
        ("Sasha Blouse", "support"), ("Jean Kirstein", "support"),
        ("Connie Springer", "support"), ("Bertholdt Hoover", "support"),
        ("Ymir", "support"), ("Kenny Ackerman", "support"),
    ]),
    "Demon Slayer": ("S", [
        ("Tanjiro Kamado", "lead"), ("Nezuko Kamado", "lead"),
        ("Zenitsu Agatsuma", "main"), ("Inosuke Hashibira", "main"),
        ("Giyu Tomioka", "main"), ("Shinobu Kocho", "main"),
        ("Kyojuro Rengoku", "main"), ("Muzan Kibutsuji", "main"),
        ("Tengen Uzui", "support"), ("Mitsuri Kanroji", "support"),
        ("Obanai Iguro", "support"), ("Sanemi Shinazugawa", "support"),
        ("Gyomei Himejima", "support"), ("Muichiro Tokito", "support"),
        ("Kanao Tsuyuri", "support"), ("Akaza", "support"),
    ]),

    # ---------------- A tier ----------------
    "My Hero Academia": ("A", [
        ("Izuku Midoriya", "lead"),
        ("Katsuki Bakugo", "main"), ("Ochaco Uraraka", "main"),
        ("Shoto Todoroki", "main"), ("All Might", "main"),
        ("Tenya Iida", "main"),
        ("Tsuyu Asui", "support"), ("Himiko Toga", "support"),
        ("Momo Yaoyorozu", "support"), ("Eijiro Kirishima", "support"),
        ("Shota Aizawa", "support"), ("Tomura Shigaraki", "support"),
    ]),
    "Death Note": ("A", [
        ("Light Yagami", "lead"), ("L Lawliet", "lead"),
        ("Misa Amane", "main"), ("Ryuk", "main"), ("Near", "main"),
        ("Mello", "main"),
        ("Soichiro Yagami", "support"), ("Teru Mikami", "support"),
        ("Touta Matsuda", "support"), ("Naomi Misora", "support"),
        ("Watari", "support"), ("Kiyomi Takada", "support"),
    ]),
    "Jujutsu Kaisen": ("A", [
        ("Yuji Itadori", "lead"), ("Satoru Gojo", "lead"),
        ("Megumi Fushiguro", "main"), ("Nobara Kugisaki", "main"),
        ("Ryomen Sukuna", "main"), ("Maki Zenin", "main"),
        ("Kento Nanami", "support"), ("Toge Inumaki", "support"),
        ("Panda", "support"), ("Yuta Okkotsu", "support"),
        ("Suguru Geto", "support"), ("Toji Fushiguro", "support"),
    ]),
    "Fullmetal Alchemist: Brotherhood": ("A", [
        ("Edward Elric", "lead"),
        ("Alphonse Elric", "main"), ("Winry Rockbell", "main"),
        ("Roy Mustang", "main"), ("Riza Hawkeye", "main"), ("Scar", "main"),
        ("Ling Yao", "support"), ("Olivier Mira Armstrong", "support"),
        ("Maes Hughes", "support"), ("Lan Fan", "support"),
        ("Greed", "support"), ("Envy", "support"),
    ]),
    "Bleach": ("A", [
        ("Ichigo Kurosaki", "lead"), ("Rukia Kuchiki", "lead"),
        ("Orihime Inoue", "main"), ("Uryu Ishida", "main"),
        ("Byakuya Kuchiki", "main"), ("Sosuke Aizen", "main"),
        ("Toshiro Hitsugaya", "support"), ("Yoruichi Shihoin", "support"),
        ("Kisuke Urahara", "support"), ("Kenpachi Zaraki", "support"),
        ("Grimmjow Jaegerjaquez", "support"), ("Ulquiorra Cifer", "support"),
    ]),
    "Sailor Moon": ("A", [
        ("Usagi Tsukino", "lead"),
        ("Ami Mizuno", "main"), ("Rei Hino", "main"), ("Makoto Kino", "main"),
        ("Minako Aino", "main"), ("Mamoru Chiba", "main"),
        ("Chibiusa", "support"), ("Hotaru Tomoe", "support"),
        ("Haruka Tenou", "support"), ("Michiru Kaiou", "support"),
        ("Setsuna Meiou", "support"), ("Luna", "support"),
    ]),
    "Neon Genesis Evangelion": ("A", [
        ("Shinji Ikari", "lead"), ("Rei Ayanami", "lead"),
        ("Asuka Langley Soryu", "lead"),
        ("Misato Katsuragi", "main"), ("Kaworu Nagisa", "main"),
        ("Ritsuko Akagi", "main"),
        ("Gendo Ikari", "support"), ("Mari Makinami", "support"),
        ("Toji Suzuhara", "support"), ("Ryoji Kaji", "support"),
        ("Yui Ikari", "support"), ("Kensuke Aida", "support"),
    ]),
    "Spy x Family": ("A", [
        ("Anya Forger", "lead"), ("Loid Forger", "lead"),
        ("Yor Forger", "lead"),
        ("Yuri Briar", "main"), ("Fiona Frost", "main"),
        ("Sylvia Sherwood", "main"),
        ("Bond Forger", "support"), ("Damian Desmond", "support"),
        ("Becky Blackbell", "support"), ("Franky Franklin", "support"),
        ("Henry Henderson", "support"), ("Melinda Desmond", "support"),
    ]),
    "Chainsaw Man": ("A", [
        ("Denji", "lead"), ("Makima", "lead"),
        ("Power", "main"), ("Aki Hayakawa", "main"), ("Kishibe", "main"),
        ("Reze", "main"),
        ("Himeno", "support"), ("Kobeni Higashiyama", "support"),
        ("Pochita", "support"), ("Angel Devil", "support"),
        ("Beam", "support"), ("Quanxi", "support"),
    ]),
    "Hunter x Hunter": ("A", [
        ("Gon Freecss", "lead"), ("Killua Zoldyck", "lead"),
        ("Kurapika", "main"), ("Leorio Paradinight", "main"),
        ("Hisoka Morow", "main"), ("Chrollo Lucilfer", "main"),
        ("Biscuit Krueger", "support"), ("Illumi Zoldyck", "support"),
        ("Meruem", "support"), ("Feitan", "support"),
        ("Machi", "support"), ("Kite", "support"),
    ]),
    "One Punch Man": ("A", [
        ("Saitama", "lead"),
        ("Genos", "main"), ("Tatsumaki", "main"), ("Garou", "main"),
        ("King", "main"), ("Fubuki", "main"),
        ("Bang", "support"), ("Mumen Rider", "support"),
        ("Boros", "support"), ("Metal Bat", "support"),
        ("Child Emperor", "support"), ("Zombieman", "support"),
    ]),
    "JoJo's Bizarre Adventure": ("A", [
        ("Jotaro Kujo", "lead"), ("Dio Brando", "lead"),
        ("Joseph Joestar", "main"), ("Giorno Giovanna", "main"),
        ("Jonathan Joestar", "main"), ("Josuke Higashikata", "main"),
        ("Jolyne Cujoh", "support"), ("Noriaki Kakyoin", "support"),
        ("Bruno Bucciarati", "support"), ("Caesar Zeppeli", "support"),
        ("Yoshikage Kira", "support"), ("Rohan Kishibe", "support"),
    ]),
    "Fairy Tail": ("A", [
        ("Natsu Dragneel", "lead"), ("Lucy Heartfilia", "lead"),
        ("Erza Scarlet", "main"), ("Gray Fullbuster", "main"),
        ("Wendy Marvell", "main"), ("Juvia Lockser", "main"),
        ("Happy", "support"), ("Gajeel Redfox", "support"),
        ("Mirajane Strauss", "support"), ("Levy McGarden", "support"),
        ("Laxus Dreyar", "support"), ("Zeref Dragneel", "support"),
    ]),
    "Tokyo Ghoul": ("A", [
        ("Ken Kaneki", "lead"),
        ("Touka Kirishima", "main"), ("Juuzou Suzuya", "main"),
        ("Rize Kamishiro", "main"), ("Shuu Tsukiyama", "main"),
        ("Kishou Arima", "main"),
        ("Hideyoshi Nagachika", "support"), ("Ayato Kirishima", "support"),
        ("Hinami Fueguchi", "support"), ("Koutarou Amon", "support"),
        ("Uta", "support"), ("Eto Yoshimura", "support"),
    ]),
    "Sword Art Online": ("A", [
        ("Kirito", "lead"), ("Asuna", "lead"),
        ("Sinon", "main"), ("Leafa", "main"), ("Yuuki Konno", "main"),
        ("Alice Zuberg", "main"),
        ("Eugeo", "support"), ("Klein", "support"), ("Agil", "support"),
        ("Silica", "support"), ("Lisbeth", "support"), ("Yui", "support"),
    ]),
    "Haikyuu!!": ("A", [
        ("Shoyo Hinata", "lead"), ("Tobio Kageyama", "lead"),
        ("Kei Tsukishima", "main"), ("Daichi Sawamura", "main"),
        ("Koushi Sugawara", "main"), ("Tooru Oikawa", "main"),
        ("Kenma Kozume", "support"), ("Tetsurou Kuroo", "support"),
        ("Yuu Nishinoya", "support"), ("Asahi Azumane", "support"),
        ("Wakatoshi Ushijima", "support"), ("Koutarou Bokuto", "support"),
    ]),
    "Kaguya-sama: Love is War": ("A", [
        ("Kaguya Shinomiya", "lead"), ("Miyuki Shirogane", "lead"),
        ("Chika Fujiwara", "main"), ("Yu Ishigami", "main"),
        ("Ai Hayasaka", "main"), ("Miko Iino", "main"),
        ("Nagisa Kashiwagi", "support"), ("Tsubame Koyasu", "support"),
        ("Kei Shirogane", "support"), ("Maki Shijo", "support"),
    ]),
    "Frieren: Beyond Journey's End": ("A", [
        ("Frieren", "lead"),
        ("Fern", "main"), ("Stark", "main"), ("Himmel", "main"),
        ("Heiter", "main"), ("Eisen", "main"),
        ("Aura", "support"), ("Serie", "support"), ("Sein", "support"),
        ("Ubel", "support"), ("Denken", "support"), ("Wirbel", "support"),
    ]),
    "Oshi no Ko": ("A", [
        ("Ai Hoshino", "lead"), ("Aqua Hoshino", "lead"),
        ("Ruby Hoshino", "main"), ("Kana Arima", "main"),
        ("Akane Kurokawa", "main"),
        ("Mem-cho", "support"), ("Miyako Saitou", "support"),
    ]),
    "Fate/stay night": ("A", [
        ("Artoria Pendragon", "lead"),
        ("Rin Tohsaka", "main"), ("Shirou Emiya", "main"),
        ("Sakura Matou", "main"), ("Illyasviel von Einzbern", "main"),
        ("Kirei Kotomine", "support"), ("Gilgamesh", "support"),
        ("Taiga Fujimura", "support"), ("Shinji Matou", "support"),
    ]),

    # ---------------- B tier ----------------
    "Cowboy Bebop": ("B", [
        ("Spike Spiegel", "lead"),
        ("Faye Valentine", "main"), ("Jet Black", "main"),
        ("Edward Wong", "main"),
        ("Julia", "support"), ("Ein", "support"), ("Vicious", "support"),
    ]),
    "Steins;Gate": ("B", [
        ("Rintaro Okabe", "lead"), ("Kurisu Makise", "lead"),
        ("Mayuri Shiina", "main"), ("Itaru Hashida", "main"),
        ("Suzuha Amane", "main"),
        ("Faris NyanNyan", "support"), ("Moeka Kiryu", "support"),
        ("Ruka Urushibara", "support"), ("Yugo Tennouji", "support"),
    ]),
    "Code Geass": ("B", [
        ("Lelouch vi Britannia", "lead"), ("C.C.", "lead"),
        ("Suzaku Kururugi", "main"), ("Kallen Stadtfeld", "main"),
        ("Nunnally vi Britannia", "main"),
        ("Euphemia li Britannia", "support"), ("Shirley Fenette", "support"),
        ("Cornelia li Britannia", "support"),
        ("Schneizel el Britannia", "support"),
        ("Rolo Lamperouge", "support"), ("Charles zi Britannia", "support"),
    ]),
    "Re:Zero": ("B", [
        ("Subaru Natsuki", "lead"), ("Rem", "lead"), ("Emilia", "lead"),
        ("Ram", "main"), ("Beatrice", "main"), ("Roswaal L Mathers", "main"),
        ("Felt", "support"), ("Puck", "support"), ("Otto Suwen", "support"),
        ("Crusch Karsten", "support"), ("Reinhard van Astrea", "support"),
        ("Echidna", "support"),
    ]),
    "Mob Psycho 100": ("B", [
        ("Shigeo Kageyama", "lead"),
        ("Arataka Reigen", "main"), ("Ritsu Kageyama", "main"),
        ("Teruki Hanazawa", "main"),
        ("Dimple", "support"), ("Tome Kurata", "support"),
        ("Shou Suzuki", "support"),
    ]),
    "KonoSuba": ("B", [
        ("Kazuma Satou", "lead"),
        ("Aqua", "main"), ("Megumin", "main"), ("Darkness", "main"),
        ("Wiz", "support"), ("Yunyun", "support"), ("Chris", "support"),
    ]),
    "Overlord": ("B", [
        ("Ainz Ooal Gown", "lead"),
        ("Albedo", "main"), ("Shalltear Bloodfallen", "main"),
        ("Demiurge", "main"),
        ("Cocytus", "support"), ("Aura Bella Fiora", "support"),
        ("Mare Bello Fiore", "support"), ("Sebas Tian", "support"),
    ]),
    "Vinland Saga": ("B", [
        ("Thorfinn", "lead"),
        ("Askeladd", "main"), ("Thors", "main"), ("Canute", "main"),
        ("Einar", "support"), ("Bjorn", "support"), ("Thorkell", "support"),
    ]),
    "Dr. Stone": ("B", [
        ("Senku Ishigami", "lead"),
        ("Taiju Ooki", "main"), ("Kohaku", "main"), ("Gen Asagiri", "main"),
        ("Chrome", "support"), ("Yuzuriha Ogawa", "support"),
        ("Tsukasa Shishio", "support"),
    ]),
    "The Promised Neverland": ("B", [
        ("Emma", "lead"),
        ("Norman", "main"), ("Ray", "main"), ("Isabella", "main"),
        ("Gilda", "support"), ("Don", "support"), ("Krone", "support"),
    ]),
    "Toradora!": ("B", [
        ("Taiga Aisaka", "lead"), ("Ryuuji Takasu", "lead"),
        ("Minori Kushieda", "main"), ("Ami Kawashima", "main"),
        ("Yusaku Kitamura", "main"),
        ("Yasuko Takasu", "support"),
    ]),
    "Bocchi the Rock!": ("B", [
        ("Hitori Gotou", "lead"),
        ("Nijika Ijichi", "main"), ("Ryou Yamada", "main"),
        ("Ikuyo Kita", "main"),
        ("Seika Ijichi", "support"), ("Kikuri Hiroi", "support"),
    ]),
    "Blue Lock": ("B", [
        ("Yoichi Isagi", "lead"),
        ("Meguru Bachira", "main"), ("Rin Itoshi", "main"),
        ("Seishiro Nagi", "main"),
        ("Hyoma Chigiri", "support"), ("Reo Mikage", "support"),
        ("Jinpachi Ego", "support"),
    ]),
    "Assassination Classroom": ("B", [
        ("Koro-sensei", "lead"), ("Nagisa Shiota", "lead"),
        ("Karma Akabane", "main"), ("Kaede Kayano", "main"),
        ("Tadaomi Karasuma", "support"), ("Irina Jelavic", "support"),
    ]),
    "Black Clover": ("B", [
        ("Asta", "lead"), ("Yuno", "lead"),
        ("Noelle Silva", "main"), ("Yami Sukehiro", "main"),
        ("Mimosa Vermillion", "support"), ("Luck Voltia", "support"),
        ("Charmy Pappitson", "support"),
    ]),
    "Monogatari": ("B", [
        ("Koyomi Araragi", "lead"),
        ("Hitagi Senjougahara", "main"), ("Shinobu Oshino", "main"),
        ("Mayoi Hachikuji", "main"),
        ("Suruga Kanbaru", "support"), ("Nadeko Sengoku", "support"),
        ("Tsubasa Hanekawa", "support"), ("Karen Araragi", "support"),
    ]),

    # ---------------- C tier ----------------
    "Berserk": ("C", [
        ("Guts", "lead"),
        ("Griffith", "main"), ("Casca", "main"),
        ("Puck", "support"), ("Judeau", "support"), ("Zodd", "support"),
    ]),
}


# Kakera range. Mudae-ish: a nobody is worth a pittance, a top-rank character
# is worth a few hundred rolls of grinding.
KAKERA_MIN, KAKERA_MAX = 20, 1300

# Ranks run 1 (most popular) to RANK_MAX, as in Mudae.
RANK_MAX = 10000

# How sharply value falls off with rank. Higher = more top-heavy, so the
# difference between rank 1 and rank 50 is dramatic and the long tail is flat.
KAKERA_CURVE = 2.4


def fame_score(tier: str, role: str) -> int:
    """Raw popularity, used only to order characters before ranking."""
    return TIER_BASE[tier] + ROLE_BONUS[role]


def spread_rank(position: int, total: int) -> int:
    """Map position 1..total onto the 1..RANK_MAX rank scale."""
    if total <= 1:
        return 1
    return round(1 + (position - 1) * (RANK_MAX - 1) / (total - 1))


def jitter_rank(rank: int, name: str) -> int:
    """A character's claim rank is close to their like rank but not identical:
    some are loved and rarely claimed, some the reverse. Derived from the name
    so it is stable across regenerations rather than random each run."""
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    offset = (digest[0] / 255 - 0.5) * 0.30  # +/- 15%
    return max(1, min(RANK_MAX, round(rank * (1 + offset))))


def kakera_for_rank(rank: int) -> int:
    """Rank -> kakera, front-loaded so the top of the list is genuinely rare."""
    share = 1 - (rank - 1) / (RANK_MAX - 1)
    return round(KAKERA_MIN + (KAKERA_MAX - KAKERA_MIN) * share**KAKERA_CURVE)


def build():
    characters = []
    for series, (tier, cast) in ROSTER.items():
        for name, role in cast:
            characters.append({
                "name": name,
                "series": series,
                "image_url": "",  # filled in by tools/fetch_art.py
                "likes": 0,
                "_fame": fame_score(tier, role),
            })

    # Most famous first; ties broken deterministically so ranks are stable.
    characters.sort(key=lambda c: (-c["_fame"], c["series"], c["name"]))

    total = len(characters)
    for position, character in enumerate(characters, 1):
        like_rank = spread_rank(position, total)
        claim_rank = jitter_rank(like_rank, character["name"])
        character["like_rank"] = like_rank
        character["claim_rank"] = claim_rank
        # Value reflects both how liked and how claimed they are.
        character["base_kakera"] = kakera_for_rank((like_rank + claim_rank) // 2)
        del character["_fame"]

    characters.sort(key=lambda c: (c["like_rank"], c["name"]))
    return characters


def merge_existing(characters, path):
    """Keep art and ids already fetched for characters we still have."""
    if not os.path.exists(path):
        return characters, 0
    with open(path, encoding="utf-8") as handle:
        old = {(c["name"], c["series"]): c for c in json.load(handle)}
    kept = 0
    for character in characters:
        previous = old.get((character["name"], character["series"]))
        if previous and previous.get("image_url"):
            character["image_url"] = previous["image_url"]
            if previous.get("images"):
                character["images"] = previous["images"]
            for field in ("source", "anilist_id"):
                if previous.get(field):
                    character[field] = previous[field]
            kept += 1
    return characters, kept


def main():
    characters = build()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "data", "characters.json")

    characters, kept = merge_existing(characters, out)

    with open(out, "w", encoding="utf-8") as handle:
        json.dump(characters, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    missing = sum(1 for c in characters if not c["image_url"])
    print(f"Wrote {len(characters)} characters from {len(ROSTER)} series to {out}")
    print(f"kept existing art for {kept}, {missing} still need art")

    spread = {}
    for character in characters:
        spread.setdefault(character["base_kakera"], 0)
        spread[character["base_kakera"]] += 1
    print("\nkakera value  characters")
    for value in sorted(spread, reverse=True):
        print(f"{value:>12}  {'#' * min(spread[value], 60)} ({spread[value]})")


if __name__ == "__main__":
    main()
