"""Smoke test: loads every cog and drives the game logic against a throwaway
database. No Discord connection, no token needed.

    python smoke_test.py
"""
import asyncio
import os
import sys
import tempfile

import discord

PROJECT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

DB_FILE = os.path.join(tempfile.mkdtemp(), "smoke.db")
os.environ["DB_PATH"] = DB_FILE
os.environ["DISCORD_TOKEN"] = "fake-token-for-import-only"

failures = []


def check(label, condition, detail=""):
    status = "ok  " if condition else "FAIL"
    if not condition:
        failures.append(f"{label} {detail}")
    print(f"{status} {label}{(' -- ' + detail) if detail and not condition else ''}")


async def main():
    import bot as botmod

    # 1. Every cog loads and registers its commands.
    b = botmod.GachaBot()
    for cog in botmod.COGS:
        await b.load_extension(cog)
    names = sorted(c.qualified_name for c in b.commands)
    check("all cogs load", len(b.cogs) == len(botmod.COGS), f"{len(b.cogs)} cogs")
    check("commands registered", len(names) >= 25, f"{len(names)} commands")
    print("     commands:", ", ".join(names))

    # Alias collisions would have raised on load, but assert the count anyway.
    aliases = [a for c in b.commands for a in c.aliases]
    check("aliases unique", len(aliases) == len(set(aliases)))

    db = b.db
    cd = b.cooldowns
    GUILD, ALICE, BOB = 1, 100, 200

    # 2. Seed import path.
    import json

    with open(os.path.join(PROJECT, "data", "characters.json"), encoding="utf-8") as fh:
        seed = json.load(fh)
    for entry in seed:
        cid_ = db.upsert_character(
            entry["name"], entry["series"], entry["image_url"],
            entry.get("likes", 0), entry.get("base_karuda", 50),
        )
        db.update_character(cid_, like_rank=entry.get("like_rank"),
                            claim_rank=entry.get("claim_rank"))
    check("seed imports", db.character_count() == len(seed), str(db.character_count()))
    # Re-import must update, not duplicate.
    for entry in seed:
        db.upsert_character(
            entry["name"], entry["series"], entry["image_url"],
            entry.get("likes", 0), entry.get("base_karuda", 50),
        )
    check("re-import is idempotent", db.character_count() == len(seed))

    # 3. Rarity tiers and karuda math.
    import config, utils

    check("rarity tiers are gone", not hasattr(config, "RARITY_TIERS"))
    check("eight shard types", len(config.SHARD_TYPES) == 8,
          str(len(config.SHARD_TYPES)))
    check("shard keys unique",
          len({s[0] for s in config.SHARD_TYPES}) == len(config.SHARD_TYPES))
    check("shards get rarer as they get richer",
          [s[3] for s in config.SHARD_TYPES]
          == sorted(s[3] for s in config.SHARD_TYPES)
          and [s[4] for s in config.SHARD_TYPES]
          == sorted((s[4] for s in config.SHARD_TYPES), reverse=True))
    check("every shard has an icon", all(s[2].strip() for s in config.SHARD_TYPES))
    import random as _random
    pulls = [config.roll_shard(_random)[0] for _ in range(4000)]
    check("roll_shard only returns known shards",
          set(pulls) <= {s[0] for s in config.SHARD_TYPES})
    check("the basic shard is the most common",
          max(set(pulls), key=pulls.count) == config.SHARD_TYPES[0][0])
    check("the rarest shard is actually rare",
          pulls.count(config.SHARD_TYPES[-1][0]) < pulls.count(config.SHARD_TYPES[0][0]) / 10)
    check("shard() falls back for an unknown key",
          config.shard("nonsense") == config.SHARD_TYPES[0])
    top = db.find_character_by_name("Naruto Uzumaki")
    check("name lookup exact", top is not None and top["name"] == "Naruto Uzumaki")
    check("name lookup prefix", db.find_character_by_name("Naruto Uz") is not None)
    check("karuda equals base at 100%",
          utils.karuda_value(top, 100) == top["base_karuda"],
          f"{utils.karuda_value(top, 100)} vs {top['base_karuda']}")
    check("karuda_rate applies",
          utils.karuda_value(top, 200) == utils.karuda_value(top, 100) * 2)

    # Rarity must not collapse to one tier just because likes are all zero.
    all_rows = db.search_characters("", limit=1000)
    check("all seeded likes are zero", all(r["likes"] == 0 for r in all_rows))
    leads = [r for r in all_rows if r["name"] in ("Naruto Uzumaki", "Monkey D. Luffy")]
    minor = [r for r in all_rows if r["name"] in ("Ein", "Felt")]
    check("famous leads outvalue minor characters",
          leads and minor and min(r["base_karuda"] for r in leads)
          > max(r["base_karuda"] for r in minor))

    # 3b. Ranks: 1 is best, and value tracks them.
    ranked = sorted(all_rows, key=lambda r: r["like_rank"] or 99999)
    check("ranks are populated", all(r["like_rank"] for r in all_rows))
    check("best rank is 1", ranked[0]["like_rank"] == 1, str(ranked[0]["like_rank"]))
    check("ranks stay inside 1..10000",
          all(1 <= r["like_rank"] <= 10000 and 1 <= r["claim_rank"] <= 10000
              for r in all_rows))
    check("claim rank differs from like rank for most",
          sum(1 for r in all_rows if r["claim_rank"] != r["like_rank"]) > len(all_rows) // 2)
    check("karuda spans the intended 20..1300 range",
          min(r["base_karuda"] for r in all_rows) == 20
          and max(r["base_karuda"] for r in all_rows) == 1300,
          f"{min(r['base_karuda'] for r in all_rows)}..{max(r['base_karuda'] for r in all_rows)}")
    check("better rank is worth more karuda",
          ranked[0]["base_karuda"] > ranked[-1]["base_karuda"])
    rank_embed = utils.character_embed(db, GUILD, ranked[0])
    blob = " ".join(f.value for f in rank_embed.fields)
    check("card shows claim and like rank",
          "claim **#" in blob and "like **#" in blob, blob[:120])

    # 4. Roll budget.
    limit = db.get_setting(GUILD, "roll_limit")
    left, _ = cd.rolls_left(GUILD, ALICE)
    check("starts with full rolls", left == limit, f"{left}/{limit}")
    for _ in range(limit):
        cd.spend_roll(GUILD, ALICE)
    left, reset_in = cd.rolls_left(GUILD, ALICE)
    check("rolls run out", left == 0, str(left))
    check("reset timer set", 0 < reset_in <= db.get_setting(GUILD, "roll_reset_minutes") * 60)

    # 5. Claiming: first writer wins, per-guild.
    check("claim succeeds", db.claim(GUILD, top["id"], ALICE))
    check("double claim blocked", not db.claim(GUILD, top["id"], BOB))
    check("owner recorded", db.owner_of(GUILD, top["id"]) == ALICE)
    check("other guild unaffected", db.owner_of(2, top["id"]) is None)
    check("claim is in harem", db.harem_size(GUILD, ALICE) == 1)

    cd.start_claim_cooldown(GUILD, ALICE)
    ready, remaining = cd.claim_ready(GUILD, ALICE)
    check("claim cooldown starts", not ready and remaining > 0, f"{remaining}s")
    check("bob can still claim", cd.claim_ready(GUILD, BOB)[0])

    # 6. Karuda economy.
    db.add_karuda(GUILD, ALICE, 500)
    check("karuda added", db.get_player(GUILD, ALICE)["karuda"] == 500)
    db.add_karuda(GUILD, ALICE, -9999)
    check("balance floors at zero", db.get_player(GUILD, ALICE)["karuda"] == 0)
    db.add_karuda(GUILD, ALICE, 300)
    check("daily column exists", "daily_ready_at" in db.get_player(GUILD, ALICE).keys())

    # 7. Wishes.
    second = db.find_character_by_name("Rukia Kuchiki")
    check("wish added", db.add_wish(GUILD, BOB, second["id"]))
    check("duplicate wish blocked", not db.add_wish(GUILD, BOB, second["id"]))
    check("wishers listed", db.wishers_of(GUILD, second["id"]) == [BOB])
    check("wish limit counted", db.wish_count(GUILD, BOB) == 1)
    check("wish removed", db.remove_wish(GUILD, BOB, second["id"]))
    check("wishers empty after", db.wishers_of(GUILD, second["id"]) == [])

    # 8. Trading / transfer.
    db.claim(GUILD, second["id"], BOB)
    db.transfer(GUILD, top["id"], BOB)
    check("transfer moves owner", db.owner_of(GUILD, top["id"]) == BOB)
    check("old owner lost it", db.harem_size(GUILD, ALICE) == 0)
    check("new owner gained it", db.harem_size(GUILD, BOB) == 2)

    # 9. Divorce.
    check("divorce works", db.divorce(GUILD, top["id"], BOB))
    check("wrong owner cannot divorce", not db.divorce(GUILD, second["id"], ALICE))
    check("character freed", db.owner_of(GUILD, top["id"]) is None)

    # 10. Harem ordering + notes + leaderboards.
    for order in ("likes", "name", "recent", "karuda"):
        rows = db.harem(GUILD, BOB, order)
        check(f"harem order '{order}'", isinstance(rows, list) and len(rows) == 1)
    check("note set", db.set_note(GUILD, second["id"], BOB, "best girl"))
    check("note stored", db.harem(GUILD, BOB)[0]["note"] == "best girl")
    check("harem leaderboard", db.top_harems(GUILD)[0]["user_id"] == BOB)
    check("karuda leaderboard", db.top_karuda(GUILD)[0]["user_id"] == ALICE)

    # 11. Settings round-trip and rejection of unknown keys.
    db.set_setting(GUILD, "roll_limit", 42)
    check("setting persists", db.get_setting(GUILD, "roll_limit") == 42)
    check("other guild keeps default",
          db.get_setting(999, "roll_limit") == config.GUILD_SETTINGS["roll_limit"][0])
    db.reset_settings(GUILD)
    check("settings reset",
          db.get_setting(GUILD, "roll_limit") == config.GUILD_SETTINGS["roll_limit"][0])
    check("all_settings covers table",
          set(db.all_settings(GUILD)) == set(config.GUILD_SETTINGS))

    # 12. Random roll respects the claimed filter.
    db.claim(GUILD, top["id"], ALICE)
    for _ in range(40):
        pick = db.random_character(GUILD, include_claimed=False)
        if pick is not None and db.owner_of(GUILD, pick["id"]) is not None:
            check("unclaimed-only roll", False, f"returned claimed {pick['name']}")
            break
    else:
        check("unclaimed-only roll", True)
    check("include_claimed roll returns something",
          db.random_character(GUILD, include_claimed=True) is not None)

    # 13. Character admin ops.
    new_id = db.add_character("Test Dummy", "QA", "https://example.com/x.png", 5, 10)
    check("addchar works", new_id is not None)
    check("duplicate addchar blocked",
          db.add_character("Test Dummy", "QA", "https://example.com/x.png", 5, 10) is None)
    db.update_character(new_id, likes=999)
    check("editchar works", db.get_character(new_id)["likes"] == 999)
    db.claim(GUILD, new_id, ALICE)
    db.add_wish(GUILD, BOB, new_id)
    db.delete_character(new_id)
    check("delchar removes character", db.get_character(new_id) is None)
    check("delchar cascades marriage", db.owner_of(GUILD, new_id) is None)
    check("delchar cascades wish", db.wishers_of(GUILD, new_id) == [])

    # 14. Embed builder actually produces a valid embed.
    embed = utils.character_embed(db, GUILD, top, footer="smoke")
    check("embed has title", embed.title == top["name"])
    # Explicitly drive both states rather than relying on what the roster ships.
    db.update_character(top["id"], image_url="")
    without_art = utils.character_embed(db, GUILD, db.get_character(top["id"]))
    check("embed handles missing art", not without_art.image.url
          and "no image yet" in without_art.description)
    db.update_character(top["id"], image_url="https://example.com/art.png")
    with_art = utils.character_embed(db, GUILD, db.get_character(top["id"]))
    check("embed shows art when present",
          with_art.image.url == "https://example.com/art.png"
          and "no image yet" not in with_art.description)
    check("embed shows owner", any("Belongs to" in f.name for f in embed.fields))
    check("embed under discord limit", len(embed) < 6000, str(len(embed)))

    # 15. Duration formatting.
    check("fmt seconds", utils.fmt_duration(45) == "45s", utils.fmt_duration(45))
    check("fmt minutes", utils.fmt_duration(600) == "10m", utils.fmt_duration(600))
    check("fmt hours", utils.fmt_duration(7200) == "2h 0m", utils.fmt_duration(7200))
    check("fmt negative", utils.fmt_duration(-5) == "0s")

    # 16. Views construct without a live connection.
    import views
    from cogs.rolling import ClaimView, KarudaView

    rolling_cog = b.get_cog("Rolling")
    cv = ClaimView(rolling_cog, GUILD, top, ALICE, [BOB])
    check("ClaimView builds", len(cv.children) == 1)
    check("wish protection armed", cv.protect_until > utils.now())
    cv_nowish = ClaimView(rolling_cog, GUILD, top, ALICE, [])
    check("no protection without wishers", cv_nowish.protect_until <= utils.now())
    kv = KarudaView(rolling_cog, GUILD, top)
    check("KarudaView builds", len(kv.children) == 1)
    pages = views.Paginator([embed, embed], ALICE)
    check("Paginator builds", len(pages.children) == 3)
    check("Paginator labels page", pages.page_label.label == "1/2")
    single = views.Paginator([embed], ALICE)
    check("Paginator hides nav on one page", len(single.children) == 0)
    # The trade picker: a dropdown of a harem, paged at Discord's 25 limit.
    many = db.search_characters("", limit=60)
    picker = views.CharacterPicker(many, ALICE, "pick")
    selects = [c for c in picker.children if isinstance(c, discord.ui.Select)]
    check("picker shows a dropdown", len(selects) == 1)
    check("picker caps a page at 25 options", len(selects[0].options) == 25,
          str(len(selects[0].options)))
    check("picker pages a long harem", picker.pages == 3, str(picker.pages))
    check("picker has nav on a long harem", len(picker.children) >= 5)
    check("picker starts with nothing chosen", picker.chosen is None)
    small = views.CharacterPicker(many[:4], ALICE, "pick")
    check("short harem is one page", small.pages == 1)
    check("short harem has no nav",
          len([c for c in small.children if isinstance(c, discord.ui.Button)]) == 1)
    check("picker option carries the character id",
          selects[0].options[0].value == str(many[0]["id"]))

    conf = views.Confirm({ALICE, BOB})
    check("Confirm builds", len(conf.children) == 2)

    # 17. Art fetcher name matching. Every one of the "reject" cases is a real
    # wrong match this matcher made at some point: characters who share a
    # surname are the trap.
    sys.path.insert(0, os.path.join(PROJECT, "tools"))
    import fetch_art

    MATCH_CASES = [
        # (our name, AniList name, should it be accepted?)
        ("Levi Ackerman", "Mikasa Ackerman", False),
        ("Lelouch vi Britannia", "Rolo Vi Britannia", False),
        ("Lelouch vi Britannia", "Clovis la Britannia", False),
        ("Bond Forger", "Loid Forger", False),
        ("Sasuke Uchiha", "Itachi Uchiha", False),
        ("Ram", "Rem", False),
        # A bare SURNAME may be a relative: Yoshimura is Eto's father.
        ("Eto Yoshimura", "Yoshimura", False),
        # A bare GIVEN name is a safe short form, so these must still pass.
        ("Zeke Yeager", "Zeke", True),
        ("Zeref Dragneel", "Zeref", True),
        ("Tsunade", "Tsunade Senju", True),
        ("Machi", "Machi Komacine", True),
        ("Aqua Hoshino", "Aquamarine Hoshino", True),
        ("Eto Yoshimura", "Eto", True),          # via ALIASES
        ("Obito Uchiha", "Tobi", True),          # via ALIASES
        ("Chris", "Eris", True),                 # via ALIASES
        ("Levi Ackerman", "Levi", True),
        ("Bond Forger", "Bond", True),
        ("Son Goku", "Gokuu Son", True),            # reversed name order
        ("Tanjiro Kamado", "Tanjirou Kamado", True),  # long-vowel spelling
        ("Shinobu Kocho", "Shinobu Kochou", True),
        ("Monkey D. Luffy", "Luffy Monkey", True),
        ("Portgas D. Ace", "Ace Portgas", True),
        ("Mari Makinami", "Mari Makinami Illustrious", True),
        ("Edward Wong", "Edward Wong Hau Pepelu Tivrusky IV", True),
        ("Historia Reiss", "Krista Lenz", True),     # via ALIASES
        ("Nunnally vi Britannia", "Nunnally Lamperouge", True),
    ]
    wrong = []
    for ours, theirs, should_accept in MATCH_CASES:
        wanted = [ours] + fetch_art.ALIASES.get(ours, [])
        accepted = fetch_art.name_score(wanted, [theirs]) >= fetch_art.NAME_THRESHOLD
        if accepted != should_accept:
            wrong.append(f"{ours} vs {theirs}")
    check("art matcher accepts and rejects correctly", not wrong, "; ".join(wrong))

    check("series matcher handles romanised titles",
          fetch_art.series_matches("Demon Slayer", ["Demon Slayer: Kimetsu no Yaiba"])
          and fetch_art.series_matches("Spy x Family", ["SPY×FAMILY"])
          and fetch_art.series_matches("Pokemon", ["Pokémon"])
          and not fetch_art.series_matches("Naruto", ["Bleach"]))

    # Every character in the shipped roster should be usable by the bot.
    with open(os.path.join(PROJECT, "data", "characters.json"), encoding="utf-8") as fh:
        roster = json.load(fh)
    check("roster entries all have name and series",
          all(r.get("name") and r.get("series") for r in roster))
    bad_urls = [r["name"] for r in roster
                if r.get("image_url") and not r["image_url"].startswith("https://")]
    check("roster image urls are https", not bad_urls, ", ".join(bad_urls[:5]))
    check("no duplicate name+series pairs",
          len({(r["name"], r["series"]) for r in roster}) == len(roster))

    # Two characters sharing one AniList id means the matcher mapped someone
    # onto the wrong person - how Levi ended up with Mikasa's portrait.
    ids = [r["anilist_id"] for r in roster if r.get("anilist_id")]
    shared = {i for i in ids if ids.count(i) > 1}
    clashes = [
        f"{i}: {[r['name'] for r in roster if r.get('anilist_id') == i]}"
        for i in shared
    ]
    check("no two characters share an AniList id", not clashes, "; ".join(clashes))

    # 18. Regressions from the code review.

    # (a) Commands that read ctx.guild must either be guild_only or guard for
    # None, or they raise AttributeError when someone DMs the bot.
    import inspect
    import re as _re

    import db as dbmod

    unsafe = []
    for cmd in b.commands:
        source = inspect.getsource(cmd.callback)
        if not _re.search(r"ctx\.guild\b", source):
            continue
        guild_only = any(
            "guild_only" in getattr(chk, "__qualname__", "") for chk in cmd.checks
        )
        guarded = "if ctx.guild else" in source
        if not guild_only and not guarded:
            unsafe.append(cmd.name)
    check("no command crashes when used in a DM", not unsafe, ", ".join(unsafe))

    # (b) Renaming onto an existing name+series is reported, not a crash.
    dup_a = db.add_character("Dupe Test", "QA Series", "", 0, 50)
    dup_b = db.add_character("Other Name", "QA Series", "", 0, 50)
    raised = False
    try:
        db.update_character(dup_b, name="Dupe Test")
    except dbmod.DuplicateCharacter:
        raised = True
    check("duplicate rename raises DuplicateCharacter", raised)
    check("failed rename left the character alone",
          db.get_character(dup_b)["name"] == "Other Name")
    check("a normal rename still works",
          db.update_character(dup_b, name="Renamed Fine")
          and db.get_character(dup_b)["name"] == "Renamed Fine")
    db.delete_character(dup_a)
    db.delete_character(dup_b)

    # (c) The DM preview path: guild 0 has no settings, owner or wishers.
    dm_embed = utils.character_embed(db, 0, db.get_character(top["id"]))
    check("embed builds outside a guild", dm_embed.title == top["name"])

    # (d) Files that must never be committed.
    with open(os.path.join(PROJECT, ".gitignore"), encoding="utf-8") as fh:
        ignored = {line.strip() for line in fh}
    check("gitignore covers secrets, database and backups",
          {".env", "*.db", "*.bak"} <= ignored,
          f"missing {sorted({'.env', '*.db', '*.bak'} - ignored)}")

    # 19. Character albums: rolls pick a random image from the album.
    album_char = db.find_character_by_name("Nami")
    cid = album_char["id"]
    seeded = db.image_count(cid)
    check("import seeds the album", seeded >= 1, f"{seeded}")
    check("add_image adds", db.add_image(cid, "https://example.com/a.png"))
    check("add_image dedupes", not db.add_image(cid, "https://example.com/a.png"))
    db.add_images(cid, ["https://example.com/b.png", "https://example.com/c.png"])
    check("album counts all images", db.image_count(cid) == seeded + 3,
          str(db.image_count(cid)))
    picks = {db.random_image(cid) for _ in range(60)}
    check("random_image spreads across the album", len(picks) > 1, f"{len(picks)} distinct")
    check("random_image only returns album members",
          picks <= set(db.images_for(cid)))

    # A character with no album falls back to its primary image_url.
    bare = db.add_character("Album Test", "QA", "https://example.com/solo.png", 0, 50)
    check("primary used when album empty",
          db.random_image(bare) == "https://example.com/solo.png")
    # First image added becomes the primary for an art-less character.
    blank = db.add_character("Blank Test", "QA", "", 0, 50)
    db.add_image(blank, "https://example.com/first.png")
    check("first image becomes primary",
          db.get_character(blank)["image_url"] == "https://example.com/first.png")
    # Removing the primary promotes another.
    db.add_image(blank, "https://example.com/second.png")
    db.remove_image(blank, "https://example.com/first.png")
    check("removing primary promotes a survivor",
          db.get_character(blank)["image_url"] == "https://example.com/second.png")
    db.remove_image(blank, "https://example.com/second.png")
    check("emptying the album clears the primary",
          db.get_character(blank)["image_url"] == "")
    db.delete_character(blank)
    db.delete_character(bare)
    check("delete_character cascades to images", db.image_count(bare) == 0)

    roll_embed = utils.character_embed(db, GUILD, db.get_character(cid), random_art=True)
    check("roll embed uses an album image",
          roll_embed.image.url in db.images_for(cid))
    check("embed shows album size",
          any("images" in str(f.value) for f in roll_embed.fields),
          " | ".join(str(f.value) for f in roll_embed.fields))

    # 20. Batched import: one transaction, idempotent, all-or-nothing.
    before_count = db.character_count()
    batch = [
        {"name": "Batch One", "series": "Batch QA", "image_url":
         "https://example.com/1.png", "base_karuda": 700,
         "like_rank": 42, "claim_rank": 51,
         "images": ["https://example.com/2.png", "https://example.com/3.png"]},
        {"name": "Batch Two", "series": "Batch QA", "base_karuda": 90},
    ]
    result = db.import_characters(batch)
    check("batched import inserts", result["inserted"] == 2, str(result))
    check("batched import adds albums", result["images"] == 3, str(result))
    one = db.find_character_by_name("Batch One")
    check("batched import carries ranks",
          one["like_rank"] == 42 and one["claim_rank"] == 51)
    check("batched import builds the album", db.image_count(one["id"]) == 3)
    two = db.find_character_by_name("Batch Two")
    check("art-less entry still imports", two is not None and two["image_url"] == "")

    again = db.import_characters(batch)
    check("re-import inserts nothing", again["inserted"] == 0, str(again))
    check("re-import re-adds no images", again["images"] == 0, str(again))
    check("re-import does not duplicate",
          db.character_count() == before_count + 2)

    # A bad row must roll the whole batch back, not half-apply it.
    poisoned = [
        {"name": "Batch Three", "series": "Batch QA", "base_karuda": 100},
        {"series": "Batch QA", "base_karuda": 100},  # no name -> KeyError
    ]
    count_before_failure = db.character_count()
    blew_up = False
    try:
        db.import_characters(poisoned)
    except (KeyError, TypeError):
        blew_up = True
    check("a bad row raises", blew_up)
    check("failed import rolls back entirely",
          db.character_count() == count_before_failure,
          f"{db.character_count()} vs {count_before_failure}")
    check("no partial row survived rollback",
          db.find_character_by_name("Batch Three") is None)

    for name in ("Batch One", "Batch Two"):
        row = db.find_character_by_name(name)
        if row:
            db.delete_character(row["id"])

    # 20b. Icon lookup falls back cleanly and prefers uploaded emoji.
    check("icon falls back to unicode with no bot",
          utils.shard_icon("dust") == config.shard("dust")[2])
    check("unknown shard still yields an icon", utils.shard_icon("nope"))

    class _FakeEmoji:
        def __init__(self, name):
            self.name = name

        def __str__(self):
            return f"<:{self.name}:42>"

    class _FakeBot:
        emojis = [_FakeEmoji("dust"), _FakeEmoji("prism")]

    utils.use_emoji_from(_FakeBot())
    check("uploaded emoji is preferred", utils.shard_icon("dust") == "<:dust:42>")
    check("missing upload still falls back",
          utils.shard_icon("aurum") == config.shard("aurum")[2])
    card = utils.character_embed(db, GUILD, top)
    check("card uses the uploaded icon",
          "<:dust:42>" in str(card.fields[0].value), str(card.fields[0].value))
    utils.use_emoji_from(None)

    # 21. Shard pulls are recorded per player.
    check("shard pull records", db.record_shard(GUILD, ALICE, "prism") == 1)
    check("shard pull increments", db.record_shard(GUILD, ALICE, "prism") == 2)
    db.record_shard(GUILD, ALICE, "dust")
    check("shards_of reports the collection",
          db.shards_of(GUILD, ALICE) == {"prism": 2, "dust": 1},
          str(db.shards_of(GUILD, ALICE)))
    check("shards are per player", db.shards_of(GUILD, BOB) == {})

    # 22. A database from before the rename keeps its balances.
    import sqlite3 as _sqlite3
    legacy_path = os.path.join(tempfile.mkdtemp(), "legacy.db")
    legacy = _sqlite3.connect(legacy_path)
    legacy.executescript("""
        CREATE TABLE characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            series TEXT NOT NULL, image_url TEXT NOT NULL,
            likes INTEGER NOT NULL DEFAULT 0,
            base_kakera INTEGER NOT NULL DEFAULT 50,
            UNIQUE (name, series));
        CREATE TABLE players (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            kakera INTEGER NOT NULL DEFAULT 0,
            rolls_used INTEGER NOT NULL DEFAULT 0,
            rolls_reset_at INTEGER NOT NULL DEFAULT 0,
            claim_ready_at INTEGER NOT NULL DEFAULT 0,
            kakera_ready_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (guild_id, user_id));
        CREATE TABLE guild_settings (
            guild_id INTEGER NOT NULL, key TEXT NOT NULL,
            value INTEGER NOT NULL, PRIMARY KEY (guild_id, key));
        INSERT INTO characters (name, series, image_url, likes, base_kakera)
            VALUES ('Legacy Hero', 'Old Show', 'https://example.com/x.png', 7, 321);
        INSERT INTO players (guild_id, user_id, kakera) VALUES (1, 100, 4242);
        INSERT INTO guild_settings VALUES (1, 'kakera_rate', 150);
    """)
    legacy.commit()
    legacy.close()

    migrated = dbmod.Database(legacy_path)
    player_columns = {
        r["name"] for r in migrated.conn.execute("PRAGMA table_info(players)")
    }
    check("legacy kakera column renamed",
          "karuda" in player_columns and "kakera" not in player_columns,
          str(sorted(player_columns)))
    check("legacy balance survived the rename",
          migrated.get_player(1, 100)["karuda"] == 4242)
    check("legacy base_kakera renamed",
          migrated.find_character_by_name("Legacy Hero")["base_karuda"] == 321)
    check("legacy setting key renamed",
          migrated.get_setting(1, "karuda_rate") == 150,
          str(migrated.get_setting(1, "karuda_rate")))
    check("legacy image seeded an album",
          migrated.image_count(migrated.find_character_by_name("Legacy Hero")["id"]) == 1)
    migrated.close()

    await b.close()


asyncio.run(main())

print()
if failures:
    print(f"{len(failures)} FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
