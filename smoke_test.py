"""Smoke test: loads every cog and drives the game logic against a throwaway
database. No Discord connection, no token needed.

    python smoke_test.py
"""
import asyncio
import os
import sys
import tempfile

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
        db.upsert_character(
            entry["name"], entry["series"], entry["image_url"],
            entry.get("likes", 0), entry.get("base_kakera", 50),
        )
    check("seed imports", db.character_count() == len(seed), str(db.character_count()))
    # Re-import must update, not duplicate.
    for entry in seed:
        db.upsert_character(
            entry["name"], entry["series"], entry["image_url"],
            entry.get("likes", 0), entry.get("base_kakera", 50),
        )
    check("re-import is idempotent", db.character_count() == len(seed))

    # 3. Rarity tiers and kakera math.
    import config, utils

    check("mythic tier", config.rarity_for(1820)[0] == "Mythic")
    check("common tier", config.rarity_for(5)[0] == "Common")
    top = db.find_character_by_name("Ren Ashgrove")
    check("name lookup exact", top is not None and top["name"] == "Ren Ashgrove")
    check("name lookup prefix", db.find_character_by_name("Ren Ash") is not None)
    check("kakera scales with rarity",
          utils.kakera_value(top, 100) > top["base_kakera"],
          f"{utils.kakera_value(top, 100)} vs {top['base_kakera']}")
    check("kakera_rate applies",
          utils.kakera_value(top, 200) == utils.kakera_value(top, 100) * 2)

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

    # 6. Kakera economy.
    db.add_kakera(GUILD, ALICE, 500)
    check("kakera added", db.get_player(GUILD, ALICE)["kakera"] == 500)
    db.add_kakera(GUILD, ALICE, -9999)
    check("balance floors at zero", db.get_player(GUILD, ALICE)["kakera"] == 0)
    db.add_kakera(GUILD, ALICE, 300)
    check("daily column exists", "daily_ready_at" in db.get_player(GUILD, ALICE).keys())

    # 7. Wishes.
    second = db.find_character_by_name("Sable Quint")
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
    for order in ("likes", "name", "recent", "kakera"):
        rows = db.harem(GUILD, BOB, order)
        check(f"harem order '{order}'", isinstance(rows, list) and len(rows) == 1)
    check("note set", db.set_note(GUILD, second["id"], BOB, "best girl"))
    check("note stored", db.harem(GUILD, BOB)[0]["note"] == "best girl")
    check("harem leaderboard", db.top_harems(GUILD)[0]["user_id"] == BOB)
    check("kakera leaderboard", db.top_kakera(GUILD)[0]["user_id"] == ALICE)

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
    check("embed has image", bool(embed.image.url))
    check("embed shows owner", any("Belongs to" in f.name for f in embed.fields))
    check("embed under discord limit", len(embed) < 6000, str(len(embed)))

    # 15. Duration formatting.
    check("fmt seconds", utils.fmt_duration(45) == "45s", utils.fmt_duration(45))
    check("fmt minutes", utils.fmt_duration(600) == "10m", utils.fmt_duration(600))
    check("fmt hours", utils.fmt_duration(7200) == "2h 0m", utils.fmt_duration(7200))
    check("fmt negative", utils.fmt_duration(-5) == "0s")

    # 16. Views construct without a live connection.
    import views
    from cogs.rolling import ClaimView, KakeraView

    rolling_cog = b.get_cog("Rolling")
    cv = ClaimView(rolling_cog, GUILD, top, ALICE, [BOB])
    check("ClaimView builds", len(cv.children) == 1)
    check("wish protection armed", cv.protect_until > utils.now())
    cv_nowish = ClaimView(rolling_cog, GUILD, top, ALICE, [])
    check("no protection without wishers", cv_nowish.protect_until <= utils.now())
    kv = KakeraView(rolling_cog, GUILD, top)
    check("KakeraView builds", len(kv.children) == 1)
    pages = views.Paginator([embed, embed], ALICE)
    check("Paginator builds", len(pages.children) == 3)
    check("Paginator labels page", pages.page_label.label == "1/2")
    single = views.Paginator([embed], ALICE)
    check("Paginator hides nav on one page", len(single.children) == 0)
    conf = views.Confirm({ALICE, BOB})
    check("Confirm builds", len(conf.children) == 2)

    await b.close()


asyncio.run(main())

print()
if failures:
    print(f"{len(failures)} FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
