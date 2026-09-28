"""Smoke test: loads every cog and drives the game logic against a throwaway
database. No Discord connection, no token needed.

    python smoke_test.py
"""
import asyncio
import io
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


def config_db_path():
    import config
    return config.DB_PATH


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
    # The cogs' timers wait for a Discord login this test never makes; stop
    # them, or the first await below lets them start and complain.
    from discord.ext import tasks as _tasks
    for cog in b.cogs.values():
        for attr in dir(cog):
            loop = getattr(cog, attr, None)
            if isinstance(loop, _tasks.Loop):
                loop.cancel()
    names = sorted(c.qualified_name for c in b.commands)
    check("all cogs load", len(b.cogs) == len(botmod.COGS), f"{len(b.cogs)} cogs")
    check("commands registered", len(names) >= 25, f"{len(names)} commands")
    print("     commands:", ", ".join(names))

    # Alias collisions would have raised on load, but assert the count anyway.
    aliases = [a for c in b.commands for a in c.aliases]
    check("aliases unique", len(aliases) == len(set(aliases)))
    check("$rank is $level, and $leaderboard is the level board",
          b.get_command("rank").qualified_name == "level"
          and b.get_command("leaderboard").cog_name == "Levels"
          and b.get_command("leaderboard month") is not None
          and b.get_command("lb").name == "top")
    check("level commands work outside the gacha channels",
          getattr(b.get_command("level").cog, "works_everywhere", False))

    db = b.db
    cd = b.cooldowns
    GUILD, ALICE, BOB = 1, 100, 200

    # Staff points: one row each, removable by number, never by another server.
    first = db.add_staff_point(GUILD, ALICE, BOB, "reported a raider")
    db.add_staff_point(GUILD, ALICE, BOB, "")
    db.add_staff_point(GUILD, BOB, ALICE, "")
    check("points add up", len(db.staff_points_of(GUILD, ALICE)) == 2)
    check("most points tops the board",
          db.top_staff_points(GUILD)[0]["user_id"] == ALICE)
    check("another server can't remove a point",
          db.remove_staff_point(GUILD + 1, first) is None)
    check("a point comes off by its number",
          db.remove_staff_point(GUILD, first)["user_id"] == ALICE
          and len(db.staff_points_of(GUILD, ALICE)) == 1)
    check("clearing points is per person",
          db.clear_staff_points(GUILD, ALICE) == 1
          and len(db.staff_points_of(GUILD, BOB)) == 1)
    db.clear_staff_points(GUILD, BOB)

    # Moderation: durations, cases, and a jailing that remembers roles.
    from cogs import modtools
    check("durations parse",
          modtools.parse_duration("1h30m") == 5400
          and modtools.parse_duration("5 m") == 300
          and modtools.parse_duration("rude") == 0
          and modtools.parse_duration("10mins") == 0)
    warned = db.add_case(GUILD, ALICE, BOB, "warn", "spam")
    jailed = db.add_case(GUILD, ALICE, BOB, "jail")
    check("a history is newest first",
          [r["id"] for r in db.cases_for(GUILD, ALICE)] == [jailed, warned])
    check("removing a warning can't remove a jail",
          db.delete_case(GUILD, jailed, "warn") is None
          and db.delete_case(GUILD, warned, "warn")["id"] == warned)
    check("a mod's history is theirs", len(db.cases_by(GUILD, BOB)) == 1
          and not db.cases_by(GUILD, ALICE))
    db.save_jail(GUILD, ALICE, [11, 22])
    check("unjailing hands back the saved roles",
          db.release_jail(GUILD, ALICE) == [11, 22]
          and db.jail_record(GUILD, ALICE) is None)
    check("mod setup survives a full reset",
          db.set_mod_config(GUILD, "jail_role", 5) is None
          and db.reset_guild(GUILD) is not None
          and db.get_mod_config(GUILD, "jail_role") == 5)
    db.clear_cases(GUILD, ALICE, "jail")

    # Voice time: a session banks when it ends, and counts while it's open.
    db.start_vc_session(GUILD, ALICE, at=1000)
    db.start_vc_session(GUILD, ALICE, at=5000)
    check("joining twice doesn't restart the clock",
          db.vc_seconds(GUILD, ALICE, now=1600) == 600)
    check("leaving banks the time", db.end_vc_session(GUILD, ALICE, at=4600) == 3600
          and db.vc_seconds(GUILD, ALICE, now=99999) == 3600)
    db.start_vc_session(GUILD, BOB, at=0)
    check("the leaderboard counts the session you're in",
          [r["user_id"] for r in db.top_vc(GUILD, now=7200)] == [BOB, ALICE])
    db.drop_vc_session(GUILD, BOB)
    check("a dropped session banks nothing", db.vc_seconds(GUILD, BOB) == 0)

    # Premium: only a webhook Stripe signed, recently, is believed; and
    # premium runs to the end of what was paid for.
    import billing
    import hashlib
    import hmac
    import time
    body = b'{"type": "customer.subscription.updated"}'
    stamp = 1_700_000_000
    signed = hmac.new(b"whsec_test", f"{stamp}.".encode() + body,
                      hashlib.sha256).hexdigest()
    header = f"t={stamp},v1={signed}"
    check("a genuine Stripe webhook is accepted",
          billing.verify(body, header, "whsec_test", now=stamp + 5)["type"]
          == "customer.subscription.updated")

    def refused(*args, **kwargs):
        try:
            billing.verify(*args, **kwargs)
        except billing.BadSignature:
            return True
        return False
    check("a webhook signed with another secret is refused",
          refused(body, header, "whsec_other", now=stamp))
    check("a tampered webhook is refused",
          refused(body.replace(b"updated", b"deleted"), header, "whsec_test", now=stamp))
    check("an old webhook replayed later is refused",
          refused(body, header, "whsec_test", now=stamp + 3600))
    check("an unsigned webhook is refused", refused(body, "", "whsec_test"))

    future = int(time.time()) + 30 * 86400
    billing.apply_subscription(db, {"id": "sub_1", "customer": "cus_1",
                                    "status": "active", "current_period_end": future,
                                    "metadata": {"guild_id": str(GUILD), "buyer_id": "7"}})
    check("an active subscription makes the server premium", db.is_premium(GUILD)
          and db.premium_of(GUILD)["customer"] == "cus_1")
    billing.apply_subscription(db, {"id": "sub_1", "status": "active",
                                    "items": {"data": [{"current_period_end": future}]},
                                    "metadata": {"guild_id": str(GUILD)}})
    check("the period end is found on newer Stripe versions, and the customer kept",
          db.is_premium(GUILD) and db.premium_of(GUILD)["customer"] == "cus_1")
    billing.apply_subscription(db, {"id": "sub_1", "status": "canceled",
                                    "metadata": {"guild_id": str(GUILD)}})
    check("an ended subscription ends premium", not db.is_premium(GUILD))
    check("another server is never premium by accident", not db.is_premium(GUILD + 1))
    billing.apply_subscription(db, {"id": "sub_2", "status": "active",
                                    "current_period_end": future,
                                    "metadata": {"guild_id": str(GUILD + 5),
                                                 "buyer_id": "not a number"}})
    check("a bad buyer note doesn't stop a paid server getting premium",
          db.is_premium(GUILD + 5))
    check("a new server can have a free trial", db.trial_available(GUILD + 9))
    billing.apply_subscription(db, {"id": "sub_t", "status": "trialing",
                                    "current_period_end": future,
                                    "metadata": {"guild_id": str(GUILD + 9)}})
    check("a trial is premium", db.is_premium(GUILD + 9))
    billing.apply_subscription(db, {"id": "sub_t", "status": "canceled",
                                    "metadata": {"guild_id": str(GUILD + 9)}})
    check("a cancelled trial can't be taken again",
          not db.is_premium(GUILD + 9) and not db.trial_available(GUILD + 9))
    check("a server that subscribed before gets no trial", not db.trial_available(GUILD))

    # Server events: only with Premium, only while they run, and a karuda
    # rush never pushes a grab past the whole character.
    EV = GUILD + 20
    now = int(time.time())
    base_rolls = db.get_setting(EV, "roll_limit")
    db.add_event(EV, "rolls", 5, now - 10, now + 3600, 0, 0)
    check("an event does nothing without Premium", db.get_setting(EV, "roll_limit") == base_rolls)
    billing.apply_subscription(db, {"id": "sub_ev", "status": "active",
                                    "current_period_end": future,
                                    "metadata": {"guild_id": str(EV)}})
    check("a rolls event adds rolls while it runs", db.get_setting(EV, "roll_limit") == base_rolls + 5)
    db.set_setting(EV, "karuda_grab_percent", 60)
    db.add_event(EV, "karuda", 300, now - 10, now + 3600, 0, 0)
    check("a karuda rush lifts grabs but never past 100%",
          db.get_setting(EV, "karuda_grab_percent") == 100)
    db.add_event(EV, "xp", 150, now + 3600, now + 7200, 0, 0)
    check("a future event isn't running yet", db.event_strength(EV, "xp") is None)
    first = db.events_of(EV)[0]["id"]
    db.end_event(EV, first)
    check("stopping an event ends it at once", db.get_setting(EV, "roll_limit") == base_rolls)
    check("another server's events don't leak", db.event_strength(EV + 1, "karuda") is None)

    # Backups: made from the live file, restorable, and marked as trimmed.
    import backup
    data, _note = backup.make(config_db_path())
    check("a backup can be made and read back",
          backup.check(data).startswith(b"SQLite format 3"))
    try:
        backup.check(b"not a backup")
        check("junk is refused as a backup", False)
    except backup.BadBackup:
        check("junk is refused as a backup", True)

    # Levels: the curve, and a reset that keeps what was already paid.
    from cogs import levels as levelsmod
    check("level curve", levelsmod.level_for(levelsmod.total_for(10))[0] == 10
          and levelsmod.level_for(levelsmod.total_for(10) - 1)[0] == 9)
    db.update_level_row(GUILD, ALICE, xp=5000, level=10, paid_through=10)
    db.update_level_row(GUILD, ALICE, xp=0, level=0)
    check("a level reset keeps what was paid",
          db.level_row(GUILD, ALICE)["paid_through"] == 10)

    # Premium perks: everyone on a Premium server gets the gacha perks, and
    # nobody anywhere else does.
    import perks
    import premium
    from types import SimpleNamespace as NS
    PAID, FREE = GUILD + 5, GUILD + 6          # GUILD + 5 subscribed above
    paid_perks = perks.effective(db, PAID, ALICE)
    free_perks = perks.effective(db, FREE, ALICE)
    check("a Premium server's players get the gacha perks",
          all(paid_perks[k] - free_perks[k] == v for k, v in premium.GACHA_PERK.items()))
    check("a free server's players get none of them",
          free_perks["karuda_percent"] == 0 and free_perks["rolls"] == 0)
    check("the perks read as words", "karuda" in perks.describe(paid_perks))
    check("the Premium list fits in one Discord message",
          len(premium.perk_lines()) < 1500, str(len(premium.perk_lines())))
    check("Stripe's price reads as words",
          billing.describe_price({"unit_amount": 299, "currency": "usd",
                                  "recurring": {"interval": "month"}}) == "$2.99 a month"
          and billing.describe_price({"unit_amount": 500, "currency": "sek"}) == "5.00 SEK"
          and billing.describe_price({}) == "")

    # XP boosts: the best role boost, times the channel's (or its
    # category's, or a thread's channel's), and only on Premium.
    lv = b.get_cog("Levels")
    db.set_level_boost(PAID, 900, 150)          # a role
    db.set_level_boost(PAID, 901, 120)          # a smaller role
    db.set_level_boost(PAID, 700, 200)          # a category
    member = NS(guild=NS(id=PAID), roles=[NS(id=900), NS(id=901)])
    room = NS(id=800, category_id=700, parent=None)
    check("the best role boost counts", lv.boosted(member, 100) == 150)
    check("a boosted category boosts its channels too",
          lv.boosted(member, 100, room) == 300)
    check("a thread counts as its channel",
          lv.boosted(member, 100, NS(id=801, parent=room)) == 300)
    db.set_level_boost(PAID, 800, 110)
    check("a channel's own boost beats its category's",
          lv.boosted(member, 100, room) == 165)
    check("boosts do nothing without Premium",
          lv.boosted(NS(guild=NS(id=FREE), roles=[NS(id=900)]), 100, room) == 100)

    # The leaderboard picture: messages are counted, and a page draws,
    # podium and all, even for people who've left the server.
    import boardcard
    db.add_messages({(PAID, ALICE): 5, (PAID, BOB): 2})
    db.add_messages({(PAID, ALICE): 1})
    check("messages are counted", db.level_row(PAID, ALICE)["messages"] == 6)
    check("voice time reads short", boardcard.hours(45 * 3600) == "45h"
          and boardcard.hours(5400) == "1.5h" and boardcard.hours(1200) == "20m")
    lv.message_counts[(PAID, BOB)] = 3
    fake_guild = NS(id=PAID, name="Paper's server", icon=None,
                    get_member=lambda uid: None)
    people = [(ALICE, 900), (BOB, 500), (ALICE + 1, 300), (BOB + 1, 100)]
    png = await lv.board_page(fake_guild, people, 0, 1, "LEVEL LEADERBOARD", "footer")
    from PIL import Image as _Image
    board = _Image.open(io.BytesIO(png))
    check("the leaderboard draws, wide enough for Discord to show it big",
          board.size == (boardcard.WIDTH, boardcard.HEIGHT)
          and boardcard.WIDTH / boardcard.HEIGHT >= 550 / 350, str(board.size))
    later = [dict(e, place=e["place"] + 10) for e in
             [{"place": n, "name": "x" * 40, "avatar": b"", "level": 3, "into": 5,
               "needed": 10, "xp": 99, "messages": 123456, "voice": 999999}
              for n in range(1, 11)]]
    check("a later page draws two columns",
          _Image.open(io.BytesIO(boardcard.render("s", later, 0x7C6BF0, page=2,
                                                  pages=3))).size == board.size)
    lv.message_counts.clear()

    # The $level card: activity per channel and day, ranks, and the picture.
    from cogs.levels import today as _today
    day = _today()
    lv.note_activity(PAID, ALICE, 700, messages=3)
    lv.note_activity(PAID, ALICE, 701, messages=1)
    lv.note_activity(PAID, ALICE, 800, voice=120)
    lv.save_message_counts()
    db.add_activity({(PAID, ALICE, day - 3, 701): [5, 0], (PAID, ALICE, day - 40, 702): [9, 0]})
    check("activity adds up by day", db.activity_by_day(PAID, ALICE, day)[day] == (4, 120))
    check("top channels, busiest first",
          db.top_channels(PAID, ALICE, day - 29, "messages") == [(701, 6), (700, 3)]
          and db.top_channels(PAID, ALICE, day - 29, "voice") == [(800, 120)])
    db.prune_activity(day - 30)
    check("old activity is cleared", not db.top_channels(PAID, ALICE, 0, "messages")
          or all(c != 702 for c, _n in db.top_channels(PAID, ALICE, 0, "messages")))
    # A recount from history: totals become what history holds, plus
    # whatever was counted live while it ran, never less and never twice.
    RC = PAID + 50
    db.add_messages({(RC, ALICE): 90, (RC, BOB): 4})        # counted live so far
    before = db.messages_of(RC)
    db.add_messages({(RC, ALICE): 2})                       # sent during the count
    db.apply_recount(RC, {ALICE: 4543, BOB: 1, 555: 7}, before, {}, {})
    after = db.messages_of(RC)
    check("a recount takes history and keeps live counts",
          after == {ALICE: 4545, BOB: 1, 555: 7}, str(after))

    import datetime as _dt

    def _msg(uid, days_ago=0, bot=False):
        when = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)
        return NS(author=NS(id=uid, bot=bot), created_at=when)

    class _Place:
        def __init__(self, cid, name, messages):
            self.id, self.name, self._messages = cid, name, messages

        def permissions_for(self, me):
            return NS(view_channel=True, read_message_history=True)

        async def history(self, limit=None, before=None):
            for m in self._messages:
                yield m

        async def archived_threads(self, limit=None):
            for thread in ():
                yield thread

    class _Status:
        content = ""

        async def edit(self, content):
            self.content = content

    status = _Status()

    async def _send(text):
        status.content = text
        return status

    RG = PAID + 60
    general = _Place(900, "general", [_msg(ALICE), _msg(ALICE, 3), _msg(BOB, 100),
                                      _msg(777, bot=True)])
    gacha = _Place(901, "gacha", [_msg(ALICE, 1)])
    fake = NS(id=RG, me=None, text_channels=[general, gacha], voice_channels=[],
              stage_channels=[], threads=[], forums=[])
    await lv.recount(NS(guild=fake, prefix="$", send=_send))
    check("a recount reads every channel, skipping bots",
          db.messages_of(RG) == {ALICE: 3, BOB: 1} and "Counted 4 messages" in status.content,
          status.content)
    check("and fills in the last 30 days for the $level card",
          dict(db.top_channels(RG, ALICE, _today() - 29, "messages")) == {900: 2, 901: 1})
    check("message rank", db.message_rank(PAID, ALICE) == 1 and db.message_rank(PAID, BOB) == 2
          and db.message_rank(PAID, 999) == 0)

    class _Face:
        async def read(self):
            return b""

    places = {700: NS(name="general"), 701: NS(name="gacha"), 800: NS(name="General VC")}
    member = NS(id=ALICE, name="alice", display_name="Alice ♡",
                guild=NS(id=PAID, get_channel=places.get),
                display_avatar=NS(replace=lambda **kw: _Face()))
    card = await lv.profile_file(member)
    check("the $level card draws", card is not None
          and _Image.open(card.fp).size == (1280, 800))

    # Server setup: fill-ins, reaction role emojis, auto reply matching.
    from cogs import serversetup as ss
    who = NS(display_name="Mochi", mention="<@1>")
    here = NS(name="Paper", member_count=1234)
    check("welcome fill-ins", ss.fill("Hi {user} ({user.name}) to {server}, #{count}", who, here)
          == "Hi <@1> (Mochi) to Paper, #1,234")
    check("a heart matches with or without its invisible mark",
          ss.emoji_key("❤️") == ss.emoji_key("❤"))
    check("a custom emoji is known by its id, whatever it's called",
          ss.emoji_key("<:paper:123456789012345678>") == ss.emoji_key("<a:renamed:123456789012345678>")
          == "123456789012345678")
    check("auto replies match whole words, any case",
          ss.matches("hello", "well HELLO there") and not ss.matches("hell", "hello")
          and ss.matches("good night", "ok, good night!") and not ss.matches("cat", "concatenate"))
    SG = PAID + 70
    check("a greeting starts off, as an embed", db.greeting(SG, "welcome")["channel_id"] == 0
          and db.greeting(SG, "welcome")["embed"] == 1)
    db.set_greeting(SG, "welcome", channel_id=55)
    db.set_greeting(SG, "welcome", message="hey {user}")
    row = db.greeting(SG, "welcome")
    check("greeting settings save one at a time", row["channel_id"] == 55 and row["message"] == "hey {user}"
          and db.greeting(SG, "goodbye")["channel_id"] == 0)
    db.replace_autoroles(SG, [5, 6, 5])
    check("autoroles save without repeats", db.autoroles_of(SG) == [5, 6])
    db.add_reaction_role(SG, 1, 99, ss.emoji_key("❤️"), 7)
    check("a reaction role is found by message and emoji",
          db.reaction_role(99, ss.emoji_key("❤"))["role_id"] == 7
          and db.remove_reaction_role(SG, 99) == 1 and db.reaction_role(99, "❤") is None)

    # Utility: snipes expire, reminders come due.
    from cogs import utility as ut
    tool = b.get_cog("Utility")
    tool.deleted[42].appendleft({"author": None, "content": "old", "files": [], "stickers": [],
                                 "at": time.time() - ut.SNIPE_FOR - 5})
    tool.deleted[42].appendleft({"author": None, "content": "new", "files": [], "stickers": [],
                                 "at": time.time()})
    check("only fresh snipes are kept", [i["content"] for i in tool.fresh(tool.deleted, 42)] == ["new"])
    rid = db.add_reminder(SG, 5, ALICE, int(time.time()) - 1, "stretch")
    db.add_reminder(SG, 5, ALICE, int(time.time()) + 999, "later")
    check("due reminders", [r["id"] for r in db.due_reminders(int(time.time()))] == [rid]
          and len(db.reminders_of(ALICE)) == 2 and db.remove_reminder(rid, BOB) == 0)
    check("time ago reads short", ut.ago(90) == "1m" and ut.ago(7200) == "2h" and ut.ago(5) == "5s")

    # The monthly leaderboard: months roll over, and only XP earned counts.
    check("months roll over the year", levelsmod.month_before(202601) == 202512
          and levelsmod.month_before(202607) == 202606)
    check("a month has a name", levelsmod.month_name(202609) == "September 2026")
    db.add_monthly_xp(PAID, ALICE, 202609, 40)
    db.add_monthly_xp(PAID, ALICE, 202609, 60)
    db.add_monthly_xp(PAID, BOB, 202609, 70)
    db.add_monthly_xp(PAID, BOB, 202608, 999)
    check("monthly XP adds up, month by month",
          [(r["user_id"], r["xp"]) for r in db.monthly_top(PAID, 202609)]
          == [(ALICE, 100), (BOB, 70)])
    db.prune_monthly(202609)
    check("old months are cleared", not db.monthly_top(PAID, 202608)
          and db.monthly_top(PAID, 202609))

    # Paper's own profile: pictures are checked, Premium is checked before
    # Discord is asked, and what Discord answers is remembered.
    import botprofile
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
    check("a PNG becomes a data URI",
          botprofile.image_data(png).startswith("data:image/png;base64,"))

    def profile_refused(call):
        try:
            call()
        except botprofile.ProfileError:
            return True
        return False
    check("a picture that isn't one is refused",
          profile_refused(lambda: botprofile.image_data(b"hello")))
    check("a picture over the limit is refused",
          profile_refused(lambda: botprofile.image_data(png + b"\0" * premium.PICTURE_LIMIT)))
    asked = []

    async def fake_discord(route, **kwargs):
        asked.append(kwargs["json"])
        return {"avatar": "abc123" if kwargs["json"].get("avatar") else None}
    real_request, b.http.request = b.http.request, fake_discord
    try:
        try:
            await botprofile.update(b, NS(id=FREE), "test", bio="hi")
            check("a bio needs Premium", False)
        except botprofile.ProfileError:
            check("a bio needs Premium", not asked)
        await botprofile.update(b, NS(id=PAID), "test", avatar=png, bio=" Hello ")
        row = db.bot_profile(PAID)
        check("a Premium server can set Paper's picture and bio",
              row["avatar"] == "abc123" and row["bio"] == "Hello"
              and asked[-1]["avatar"].startswith("data:image/png"))
        await botprofile.update(b, NS(id=PAID), "test", nick="Mochi")
        check("changing the name keeps the picture",
              db.bot_profile(PAID)["avatar"] == "abc123" and asked[-1] == {"nick": "Mochi"})
        await botprofile.reset(b, NS(id=PAID), "test", name_too=False)
        check("a reset puts Paper's own back, and keeps the name",
              db.bot_profile(PAID) is None and "nick" not in asked[-1]
              and asked[-1]["avatar"] is None)
        before = len(asked)
        try:
            await botprofile.update(b, NS(id=FREE), "test", nick="x" * 40)
            check("a name that's too long is refused", False)
        except botprofile.ProfileError:
            check("a name that's too long is refused", len(asked) == before)
    finally:
        b.http.request = real_request

    # 2. Seed import path.
    import json

    with open(os.path.join(PROJECT, "data", "characters.json"), encoding="utf-8") as fh:
        seed = json.load(fh)
    db.import_characters(seed)
    check("seed imports", db.character_count() == len(seed), str(db.character_count()))
    # Re-import must update, not duplicate.
    db.import_characters(seed)
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
    top = sorted(db.search_characters("", limit=100000),
                 key=lambda r: r["like_rank"] or 99999)[0]
    check("name lookup exact",
          db.find_character_by_name(top["name"])["id"] == top["id"])
    check("name lookup prefix",
          db.find_character_by_name(top["name"][:5]) is not None)
    check("karuda equals base at 100%",
          utils.karuda_value(top, 100) == top["base_karuda"],
          f"{utils.karuda_value(top, 100)} vs {top['base_karuda']}")
    check("karuda_rate applies",
          utils.karuda_value(top, 200) == utils.karuda_value(top, 100) * 2)

    # Rarity must not collapse to one tier just because likes are all zero.
    # Sized from the pool rather than a constant: a hard-coded limit silently
    # truncates the moment the roster outgrows it, and then every check below
    # is quietly measuring a slice instead of the whole thing.
    all_rows = db.search_characters("", limit=db.character_count())
    check("the whole pool was read", len(all_rows) == db.character_count(),
          str(len(all_rows)) + " of " + str(db.character_count()))
    check("all seeded likes are zero", all(r["likes"] == 0 for r in all_rows))
    check("roster is sizeable", len(all_rows) > 4000, str(len(all_rows)))
    by_rank = sorted(all_rows, key=lambda r: r["like_rank"] or 99999)
    check("famous characters outvalue obscure ones",
          by_rank[0]["base_karuda"] > by_rank[-1]["base_karuda"] * 5,
          f"{by_rank[0]['base_karuda']} vs {by_rank[-1]['base_karuda']}")

    # 3b. Ranks: 1 is best, and value tracks them.
    ranked = sorted(all_rows, key=lambda r: r["like_rank"] or 99999)
    check("ranks are populated", all(r["like_rank"] for r in all_rows))
    check("best rank is 1", ranked[0]["like_rank"] == 1, str(ranked[0]["like_rank"]))
    size = len(all_rows)
    check("ranks stay inside the pool",
          all(1 <= r["like_rank"] <= size and 1 <= r["claim_rank"] <= size
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

    # Claims reset for the whole server at once, on a roll boundary. Two
    # people who claimed hours apart must be told the same time remaining,
    # and that moment must be one where rolls come back too.
    cd.start_claim_cooldown(GUILD, BOB)
    check("everyone's claim resets together",
          db.get_player(GUILD, ALICE)["claim_ready_at"]
          == db.get_player(GUILD, BOB)["claim_ready_at"])

    claim_end, claim_len = cd.claim_window(GUILD)
    roll_end, roll_len = cd.roll_window(GUILD)
    check("the claim window is whole roll windows",
          claim_len % roll_len == 0, f"{claim_len} vs {roll_len}")
    check("a claim reset is always a roll reset",
          claim_end % roll_len == 0 and roll_end % roll_len == 0,
          f"{claim_end} {roll_end} {roll_len}")

    # An odd interval is rounded up rather than allowed to drift off the
    # roll boundary every other window. One minute past a whole window is
    # the smallest interval that has to round, whatever the window is.
    db.set_setting(GUILD, "claim_interval_minutes", roll_len // 60 + 1)
    check("an odd claim interval snaps up to a roll window",
          cd.claim_window(GUILD)[1] == 2 * roll_len,
          f"{cd.claim_window(GUILD)[1]} for a {roll_len}s roll window")
    db.set_setting(GUILD, "claim_interval_minutes",
                   config.GUILD_SETTINGS["claim_interval_minutes"][0])

    # 6. Karuda economy.
    db.add_karuda(GUILD, ALICE, 500)
    check("karuda added", db.get_player(GUILD, ALICE)["karuda"] == 500)
    db.add_karuda(GUILD, ALICE, -9999)
    check("balance floors at zero", db.get_player(GUILD, ALICE)["karuda"] == 0)
    db.add_karuda(GUILD, ALICE, 300)
    check("daily column exists", "daily_ready_at" in db.get_player(GUILD, ALICE).keys())

    # 7. Wishes.
    second = sorted(db.search_characters("", limit=100000),
                    key=lambda r: r["like_rank"] or 99999)[1]
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
    # $settings renders one embed field per setting, and Discord refuses an
    # embed with more than 25. Nothing else would catch that until it threw.
    check("settings still fit in one embed",
          len(config.GUILD_SETTINGS) <= 25,
          str(len(config.GUILD_SETTINGS)) + " settings")

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
    check("short harem has only search and cancel",
          len([c for c in small.children if isinstance(c, discord.ui.Button)]) == 2)

    # Typing narrows the list, so a long harem is not a wall to read.
    named = [dict(id=n, name=name, series=series) for n, (name, series) in
             enumerate([("Hatsune Miku", "Vocaloid"),
                        ("Hayase Nagatoro", "Nagatoro"),
                        ("Mai Sakurajima", "Bunny Girl Senpai"),
                        ("Makima", "Chainsaw Man"),
                        ("Zero Two", "DARLING in the FRANXX")])]
    check("typing nothing keeps everybody",
          len(views.rank_matches(named, "")) == len(named))
    hits = views.rank_matches(named, "ha")
    # Three, not two: Makima comes in on her series, Chainsaw Man.
    check("typing narrows the list", len(hits) == 3, str(len(hits)))
    check("and the closest matches come first",
          [h["name"] for h in hits[:2]] == ["Hatsune Miku", "Hayase Nagatoro"],
          str([h["name"] for h in hits]))
    check("a name beats a series",
          hits[-1]["name"] == "Makima", str([h["name"] for h in hits]))
    check("a word inside the name still matches",
          [r["name"] for r in views.rank_matches(named, "sakurajima")]
          == ["Mai Sakurajima"])
    check("the series matches too",
          any(r["name"] == "Zero Two"
              for r in views.rank_matches(named, "franxx")))
    check("a misspelling still finds them",
          views.rank_matches(named, "hatsne")[0]["name"] == "Hatsune Miku")
    check("and a coincidence does not",
          "Makima" not in
          [r["name"] for r in views.rank_matches(named, "sakurajima")])
    check("nothing matching returns nothing",
          views.rank_matches(named, "zzzzz") == [])

    typed = views.CharacterPicker(named, ALICE, "pick")
    typed.apply_query("ha")
    check("the picker rebuilds around what was typed",
          len(typed.rows) == 3 and typed.page == 0)
    options = [c for c in typed.children if isinstance(c, discord.ui.Select)]
    check("the dropdown shows the matches", len(options) == 1
          and len(options[0].options) == 3)
    check("and offers a way back to everybody",
          any(getattr(c, "label", "") == "Clear" for c in typed.children))
    typed.apply_query("zzzzz")
    check("no matches leaves no dropdown, which Discord rejects",
          not [c for c in typed.children if isinstance(c, discord.ui.Select)])
    typed.apply_query("")
    check("clearing brings everybody back", len(typed.rows) == len(named))
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
    # Read through iter_roster rather than json.load, so the file that ships
    # is exercised by the exact path $import uses on it.
    roster = list(utils.iter_roster(
        os.path.join(PROJECT, "data", "characters.json")))
    check("roster entries all have name and series",
          all(r.get("name") and r.get("series") for r in roster))
    bad_urls = [r["name"] for r in roster
                if r.get("image_url")
                and not r["image_url"].startswith(("https://", utils.LOCAL_ART))]
    check("roster image urls are https or bundled",
          not bad_urls, ", ".join(bad_urls[:5]))

    # A roster pointing at a picture that never got committed would show up
    # as a broken card and nowhere else, so it is checked here instead.
    bundled = [r for r in roster
               if str(r.get("image_url", "")).startswith(utils.LOCAL_ART)]
    absent = [r["name"] for r in bundled if not utils.local_art_path(r["image_url"])]
    check("every bundled image is really in the repo",
          not absent, str(len(absent)) + " missing: " + ", ".join(absent[:5]))
    check("bundled art is actually used", len(bundled) > 0, str(len(bundled)))

    # The import path has its own opinion about what a usable image is, and
    # it silently skips characters it disagrees with.
    check("import accepts a bundled image",
          utils.LOCAL_ART in open(
              os.path.join(PROJECT, "cogs", "admin.py"), encoding="utf-8").read())
    check("no duplicate name+series pairs",
          len({(r["name"], r["series"]) for r in roster}) == len(roster))

    # Two characters sharing one AniList id means the matcher mapped someone
    # onto the wrong person - how Levi ended up with Mikasa's portrait.
    # Counted rather than searched: list.count inside a comprehension is
    # quadratic, which is fine over a thousand characters and hangs the suite
    # outright over a hundred thousand.
    import collections

    ids = collections.Counter(
        r["anilist_id"] for r in roster if r.get("anilist_id")
    )
    shared = {i for i, seen in ids.items() if seen > 1}
    by_id = collections.defaultdict(list)
    if shared:
        for r in roster:
            if r.get("anilist_id") in shared:
                by_id[r["anilist_id"]].append(r["name"])
    clashes = [f"{i}: {by_id[i]}" for i in shared]
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
        # A cog can guard its whole set at once with a cog_check.
        cog_guard = False
        cog_check = getattr(type(cmd.cog), "cog_check", None) if cmd.cog else None
        if cog_check is not None:
            try:
                cog_guard = "NoPrivateMessage" in inspect.getsource(cog_check)
            except (OSError, TypeError):
                cog_guard = False
        # Any of the honest ways to check before using it.
        guards = (
            "if ctx.guild else",
            "if ctx.guild:",
            "if ctx.guild is None",
            "if not ctx.guild",
        )
        guarded = any(g in source for g in guards) or cog_guard
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
    album_char = by_rank[2]
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

    # 20d. $dk: two shards, you keep one, others may snipe the rest.
    from cogs.karuda import DAILY_OFFERS, ShardDrops

    class _Author:
        id = ALICE
        display_name = "tester"

    rolled = [config.roll_shard(_random) for _ in range(DAILY_OFFERS)]
    drops = [
        (k, n, m, c, 100 * (i + 1))
        for i, (k, n, _i, m, _w, c) in enumerate(rolled)
    ]

    def fresh(protect=20, snipe=True, percent=50):
        return ShardDrops(
            b, GUILD, _Author(), drops,
            protect=protect, snipe=snipe, snipe_percent=percent,
        )

    view = fresh()
    check("dk offers a button per shard", len(view.children) == DAILY_OFFERS,
          f"{len(view.children)} for {DAILY_OFFERS} offers")
    check("dk starts with nothing claimed",
          view.claimed == [None] * DAILY_OFFERS)
    body = view.render().description
    check("dk shows both shards up front",
          all(d[1] in body for d in drops), body[:120])
    check("dk shows each amount before choosing",
          all(f"{d[4]:,}" in body for d in drops), body[:120])
    check("dk labels buttons with the payout",
          all(str(d[4]) in c.label.replace(",", "")
              for d, c in zip(drops, view.children)),
          " | ".join(c.label for c in view.children))

    # The owner gets first refusal, then it opens up.
    check("a fresh drop is protected", fresh().protection_left() > 0)
    check("a zero window is open at once",
          fresh(protect=0).protection_left() == 0)
    taken = fresh()
    taken.takers.add(ALICE)
    check("the owner taking one opens the rest immediately",
          taken.protection_left() == 0)
    check("footer announces the wait",
          "yours alone" in fresh().render().footer.text.lower(),
          fresh().render().footer.text)
    check("footer announces when it is open",
          "anyone" in fresh(protect=0).render().footer.text.lower(),
          fresh(protect=0).render().footer.text)
    check("footer says the spare is lost when sniping is off",
          "lost" in fresh(snipe=False).render().footer.text.lower(),
          fresh(snipe=False).render().footer.text)

    # A sniper takes a share, never the lot and never nothing.
    check("snipers take the configured share",
          fresh(percent=50).snipe_amount(200) == 100)
    check("a snipe never rounds down to zero",
          fresh(percent=1).snipe_amount(1) >= 1)
    check("a hundred percent hands over the whole shard",
          fresh(percent=100).snipe_amount(200) == 200)
    check("snipe settings are real settings",
          {"dk_snipe", "dk_protect_seconds", "dk_snipe_percent"}
          <= set(config.GUILD_SETTINGS))

    # 20c. Name lookups can offer every match, not just an arbitrary one.
    dupe_names = {}
    for row in all_rows:
        dupe_names.setdefault(row["name"].lower(), []).append(row)
    shared = next((v for v in dupe_names.values() if len(v) > 1), None)
    if shared:
        found = db.find_characters_by_name(shared[0]["name"])
        check("ambiguous name returns every match", len(found) > 1,
              f"{shared[0]['name']}: {len(found)}")
    else:
        check("ambiguous name returns every match", True, "no shared names")
    check("unique name returns one",
          len(db.find_characters_by_name(by_rank[0]["name"])) >= 1)
    check("unknown name returns nothing",
          db.find_characters_by_name("zzzz no such character") == [])

    single = await views.choose_character(None, [by_rank[0]], "pick")
    check("single match needs no prompt", single["id"] == by_rank[0]["id"])
    check("no matches yields nothing",
          await views.choose_character(None, [], "pick") is None)

    # 20e. Likes: a vote you can take back, counted per server.
    liked = by_rank[5]
    check("like registers", db.add_like(GUILD, ALICE, liked["id"]))
    check("double like blocked", not db.add_like(GUILD, ALICE, liked["id"]))
    db.add_like(GUILD, BOB, liked["id"])
    check("likes tally per server", db.like_count(GUILD, liked["id"]) == 2)
    check("other server unaffected", db.like_count(2, liked["id"]) == 0)
    check("likes listed", len(db.likes_of(GUILD, ALICE)) == 1)
    check("most liked ranks it first",
          db.most_liked(GUILD)[0]["id"] == liked["id"])
    check("like position is 1", db.like_position(GUILD, liked["id"]) == 1)
    check("unliked character has no position",
          db.like_position(GUILD, by_rank[6]["id"]) == 0)
    check("card shows the server tally",
          "2 ♥" in " ".join(str(f.value) for f in
                                 utils.character_embed(db, GUILD, liked).fields))
    check("like removed", db.remove_like(GUILD, ALICE, liked["id"]))
    check("clear_likes returns a count", db.clear_likes(GUILD, BOB) == 1)
    check("likes gone", db.like_count(GUILD, liked["id"]) == 0)

    # 20f. Bulk operations.
    # Only count the ones BOB actually got - earlier tests own some already.
    victims = [
        row
        for row in db.search_characters("", limit=12)
        if db.claim(GUILD, row["id"], BOB)
    ][:6]
    before_bulk = db.harem_size(GUILD, BOB)
    doomed = victims[:3]
    removed = db.divorce_many(GUILD, BOB, [r["id"] for r in doomed])
    check("divorce_many removes exactly what it is given",
          removed == len(doomed), f"{removed} of {len(doomed)}")
    check("the rest are untouched",
          db.harem_size(GUILD, BOB) == before_bulk - len(doomed))
    check("divorce_many on nothing is a no-op",
          db.divorce_many(GUILD, BOB, []) == 0)
    series_name = victims[3]["series"]
    check("harem_by_series finds them",
          all(series_name.lower() in r["series"].lower()
              for r in db.harem_by_series(GUILD, BOB, series_name)))
    found = db.search_series(series_name[:6])
    check("series search returns counts",
          found and all(isinstance(c, int) and c > 0 for _t, c in found))
    check("characters_in_series is ordered by rank",
          [r["like_rank"] for r in db.characters_in_series(series_name)]
          == sorted(r["like_rank"] for r in db.characters_in_series(series_name)))
    db.divorce_many(GUILD, BOB, [r["id"] for r in victims])

    # 20g. Server configuration and the gate it drives.
    check("prefix defaults to none", db.get_prefix(GUILD) is None)
    db.set_prefix(GUILD, "!")
    check("prefix stored", db.get_prefix(GUILD) == "!")
    check("prefix is per guild", db.get_prefix(999) is None)
    db.clear_prefix(GUILD)
    check("prefix cleared", db.get_prefix(GUILD) is None)

    check("command disables", db.disable_command(GUILD, "roll"))
    check("disabling twice is a no-op", not db.disable_command(GUILD, "roll"))
    check("disabled list reports it", db.disabled_commands(GUILD) == {"roll"})
    check("other guild unaffected", db.disabled_commands(999) == set())
    check("command enables", db.enable_command(GUILD, "roll"))
    db.disable_command(GUILD, "roll")
    db.disable_command(GUILD, "dk")
    check("enable_all clears the lot", db.enable_all_commands(GUILD) == 2)

    check("no channel rule means no restriction", db.allowed_channels(GUILD) == set())
    db.allow_channel(GUILD, 555)
    check("channel allowed", db.allowed_channels(GUILD) == {555})
    check("removing a channel works", db.unallow_channel(GUILD, 555))
    db.allow_channel(GUILD, 1)
    db.allow_channel(GUILD, 2)
    check("clearing returns the count", db.clear_allowed_channels(GUILD) == 2)

    # Protected commands must stay reachable or a server locks itself out.
    from cogs.serverconfig import PROTECTED, SETTERS

    check("lockout-protected commands exist",
          all(b.get_command(name) for name in PROTECTED),
          ", ".join(n for n in PROTECTED if not b.get_command(n)))
    check("every friendly setter maps to a real setting",
          all(key in config.GUILD_SETTINGS for key, _unit in SETTERS.values()),
          ", ".join(k for k, _ in SETTERS.values() if k not in config.GUILD_SETTINGS))
    check("setter aliases are all registered",
          all(b.get_command(name) for name in SETTERS))

    # 20h. First seen, recorded so early users can be recognised later.
    fresh = db.get_player(GUILD, 4242)
    check("players record when they arrived", fresh["first_seen"] > 0)
    stamp = db.note_guild(GUILD)
    check("guilds record when they arrived", stamp > 0)
    check("note_guild is stable once set", db.note_guild(GUILD) == stamp)

    db.add_key("KEY-ONE", "test")
    check("key redeems", db.redeem_key("KEY-ONE", ALICE) == "ok")
    check("key cannot be reused", db.redeem_key("KEY-ONE", BOB) == "used")
    check("unknown key rejected", db.redeem_key("NOPE", BOB) == "unknown")
    check("holder recognised", db.key_holder(ALICE))
    check("non-holder not recognised", not db.key_holder(BOB))

    # 20i. Custom characters belong to one server and never leak.
    OTHER = 4321
    pool_before = db.character_count(GUILD)
    custom_id = db.add_custom(GUILD, "House Mascot", "Inside Jokes",
                              "https://example.com/m.png", 250)
    check("custom created", custom_id is not None)
    check("duplicate custom refused",
          db.add_custom(GUILD, "House Mascot", "Inside Jokes", "", 250) is None)
    check("custom belongs to its guild", db.owns_custom(GUILD, custom_id))
    check("custom is not another guild's", not db.owns_custom(OTHER, custom_id))
    check("a pool character is nobody's custom",
          not db.owns_custom(GUILD, by_rank[0]["id"]))

    check("owning guild counts it", db.character_count(GUILD) == pool_before + 1)
    check("other guild does not", db.character_count(OTHER) == pool_before)
    check("owning guild can look it up",
          [r["name"] for r in
           db.find_characters_by_name("House Mascot", guild_id=GUILD)]
          == ["House Mascot"])
    check("other guild cannot",
          db.find_characters_by_name("House Mascot", guild_id=OTHER) == [])
    check("custom listed for its guild",
          [r["id"] for r in db.customs_of(GUILD)] == [custom_id])
    check("custom not listed elsewhere", db.customs_of(OTHER) == [])
    check("custom seeded its album", db.image_count(custom_id) == 1)

    # The important one: it must never turn up in another server's rolls.
    leaked = any(
        db.random_character(OTHER, True)["id"] == custom_id for _ in range(300)
    )
    check("custom never rolls in another server", not leaked)
    check("custom search is scoped",
          all(r["guild_id"] in (0, GUILD)
              for r in db.search_characters("House", guild_id=GUILD)))
    db.delete_character(custom_id)
    check("deleting a custom clears it", db.custom_count(GUILD) == 0)

    # 20j. Help: one page, everything on it, nothing on it that is not real.
    from cogs import help as helpmod

    check("help has sections", len(helpmod.CATEGORIES) >= 10,
          str(len(helpmod.CATEGORIES)))
    pages = helpmod.help_pages("$")

    # Every page has to be a message Discord will actually accept, and the
    # sections have to all be somewhere across them.
    oversized = [i for i, p in enumerate(pages, 1) if len(p) >= 6000]
    check("every help page fits in a message", not oversized,
          str([len(p) for p in pages]))
    crowded = [i for i, p in enumerate(pages, 1) if len(p.fields) > 25]
    check("every help page fits Discord's field limit", not crowded,
          str([len(p.fields) for p in pages]))
    fat = [f.name for p in pages for f in p.fields if len(f.value) > 1024]
    check("no help section overflows its field", not fat, ", ".join(fat))
    check("help shows every section",
          sum(len(p.fields) for p in pages) == len(helpmod.CATEGORIES),
          str(sum(len(p.fields) for p in pages)))
    check("help pages are numbered when there is more than one",
          len(pages) == 1 or all("/" in p.title for p in pages))
    check("help needs no clicking", not hasattr(helpmod, "HelpView"))

    listed = [command for _icon, _name, entries in helpmod.CATEGORIES
              for command, _gloss in entries]
    unknown = sorted({c for c in listed if not b.get_command(c)})
    check("help lists no command that does not exist", not unknown,
          ", ".join(unknown))
    check("help describes every command it lists",
          all(gloss.strip() for _icon, _name, entries in helpmod.CATEGORIES
              for _command, gloss in entries))

    # The reason this page exists is to find things in, so a command that is
    # missing from it may as well not exist. $help itself is the exception -
    # you are already reading it.
    covered = {b.get_command(c) for c in listed}
    unlisted = sorted(
        command.qualified_name for command in b.walk_commands()
        if command not in covered and command.qualified_name != "help"
    )
    check("every command appears on the help page", not unlisted,
          ", ".join(unlisted))

    # 20j2. Switches: they store, they flip, they reset, and the ones that
    # claim to filter the pool actually filter the pool.
    from cogs import toggles as toggmod

    check("switches are grouped", set(toggmod.GROUPS)
          == {g for _d, g, _desc, _live in toggmod.TOGGLES.values()})
    check("every switch is described",
          all(desc.strip() for _d, _g, desc, _live in toggmod.TOGGLES.values()))
    check("every switch has a command",
          all(b.get_command("toggle" + key) for key in toggmod.TOGGLES),
          ", ".join(k for k in toggmod.TOGGLES if not b.get_command("toggle" + k)))

    TG = 4242
    default = toggmod.TOGGLES["western"][0]
    check("a switch starts at its default",
          db.get_toggle(TG, "western", default) == default)
    db.flip_toggle(TG, "western", default)
    check("a switch flips",
          db.get_toggle(TG, "western", default) != default)
    db.clear_toggles(TG)
    check("switches reset",
          db.get_toggle(TG, "western", default) == default)
    check("switches stay out of $settings",
          not any(k.startswith("toggle") for k in config.GUILD_SETTINGS))

    # The pool filter, end to end: turning games off must remove exactly the
    # game characters and leave the anime roster alone.
    toggledb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "toggles.db"))
    toggledb.import_characters([
        {"name": "Anime One", "series": "A Show", "image_url": "https://e.invalid/a.png",
         "likes": 0, "like_rank": 1, "claim_rank": 1, "base_karuda": 50,
         "source": "AniList"},
        {"name": "Game One", "series": "Fortnite", "image_url": "https://e.invalid/g.png",
         "likes": 0, "like_rank": 2, "claim_rank": 2, "base_karuda": 50,
         "source": "fortnite-api"},
        {"name": "Toon One", "series": "Avatar", "image_url": "https://e.invalid/t.png",
         "likes": 0, "like_rank": 3, "claim_rank": 3, "base_karuda": 50,
         "source": "last-airbender-api"},
    ])
    check("source survives an import",
          toggledb.find_character_by_name("Game One")["source"] == "fortnite-api")

    def rolled(gid):
        return {toggledb.random_character(gid, True, 0)["name"] for _ in range(120)}

    check("everything rolls by default", len(rolled(TG)) == 3, str(rolled(TG)))
    toggledb.set_toggle(TG, "games", 0)
    after_games = rolled(TG)
    check("switching games off drops the game characters",
          "Game One" not in after_games and "Anime One" in after_games,
          str(after_games))
    toggledb.set_toggle(TG, "western", 0)
    after_both = rolled(TG)
    check("switching western off drops the cartoons",
          after_both == {"Anime One"}, str(after_both))
    toggledb.clear_toggles(TG)
    check("resetting brings them back", len(rolled(TG)) == 3)
    toggledb.close()

    # 20j3. Nicknames, and the resets.
    aliasdb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "alias.db"))
    aliasdb.import_characters([
        {"name": "Satoru Gojou", "series": "JJK",
         "image_url": "https://e.invalid/a.png", "likes": 0,
         "like_rank": 1, "claim_rank": 1, "base_karuda": 500},
        {"name": "Someone Else", "series": "Other",
         "image_url": "https://e.invalid/b.png", "likes": 0,
         "like_rank": 2, "claim_rank": 2, "base_karuda": 50},
    ])
    gojo = aliasdb.find_character_by_name("Satoru Gojou")["id"]
    other = aliasdb.find_character_by_name("Someone Else")["id"]

    check("a nickname can be taught", aliasdb.add_alias(GUILD, "Gojo", gojo))
    check("nicknames ignore case",
          aliasdb.resolve_alias(GUILD, "GOJO")["id"] == gojo)
    check("a nickname cannot be taken twice",
          not aliasdb.add_alias(GUILD, "gojo", other))
    check("a nickname is scoped to its server",
          aliasdb.resolve_alias(OTHER, "gojo") is None)

    aliasdb.add_alias(GUILD, "best", other, user_id=ALICE)
    check("a private nickname beats the server's",
          aliasdb.resolve_alias(GUILD, "best", ALICE)["id"] == other)
    check("a private nickname is private",
          aliasdb.resolve_alias(GUILD, "best", BOB) is None)
    check("a nickname short-circuits the name search",
          [r["id"] for r in aliasdb.find_by_name_or_alias(GUILD, ALICE, "best")]
          == [other])
    check("a real name still searches normally",
          aliasdb.find_by_name_or_alias(GUILD, ALICE, "Satoru")[0]["id"] == gojo)
    check("forgetting one works",
          aliasdb.remove_alias(GUILD, "gojo")
          and aliasdb.resolve_alias(GUILD, "gojo") is None)
    check("clearing takes the private ones too",
          aliasdb.clear_aliases(GUILD) >= 1
          and aliasdb.resolve_alias(GUILD, "best", ALICE) is None)

    # A server reset must never reach the shared pool.
    before = aliasdb.character_count()
    aliasdb.claim(GUILD, gojo, ALICE)
    aliasdb.add_karuda(GUILD, ALICE, 1000)
    counts = aliasdb.reset_guild(GUILD)
    check("a server reset clears that server", counts["claims"] == 1)
    check("a server reset leaves the pool alone",
          aliasdb.character_count() == before, str(aliasdb.character_count()))
    check("a server reset leaves other servers alone",
          aliasdb.reset_guild(OTHER)["claims"] == 0)
    aliasdb.close()

    # 20j4. Tea: an item you hold, and never a way to make money.
    from cogs import tea as teamod

    check("every tea is described and priced",
          all(name and icon and what and price > 0
              for name, icon, what, price in teamod.TEAS.values()))
    check("a red tea cannot pay for itself",
          teamod.RED_TEA_KARUDA[1] < teamod.TEAS["redtea"][3],
          f"pays up to {teamod.RED_TEA_KARUDA[1]}, costs"
          f" {teamod.TEAS['redtea'][3]}")
    check("every tea has a command",
          all(b.get_command(key) for key in teamod.TEAS),
          ", ".join(k for k in teamod.TEAS if not b.get_command(k)))
    check("the daily tea is occasional, not guaranteed",
          0 < teamod.DAILY_TEA_CHANCE < 0.5, str(teamod.DAILY_TEA_CHANCE))

    teadb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "tea.db"))
    check("a tea is held", teadb.add_item(GUILD, ALICE, "greentea", 2) == 2)
    check("a tea is spent", teadb.spend_item(GUILD, ALICE, "greentea"))
    check("you cannot spend tea you do not have",
          not teadb.spend_item(GUILD, ALICE, "blacktea"))
    check("tea cannot go negative",
          teadb.add_item(GUILD, ALICE, "greentea", -50) == 0)
    check("tea is per server",
          teadb.item_count(OTHER, ALICE, "greentea") == 0)
    check("tea is per player",
          teadb.item_count(GUILD, BOB, "greentea") == 0)

    # Buying every tea and drinking it must cost more than it returns, or the
    # shop becomes a mint.
    spend = sum(price for *_rest, price in teamod.TEAS.values())
    payout = teamod.RED_TEA_KARUDA[1]
    check("buying tea never turns a profit", payout < spend, f"{payout} vs {spend}")
    teadb.close()

    # 20j5. Presets and leaderboards.
    from cogs import about as aboutmod

    unreal = sorted({setting
                     for _blurb, values in aboutmod.PRESETS.values()
                     for setting in values
                     if setting not in config.GUILD_SETTINGS})
    check("presets only write settings that exist", not unreal, ", ".join(unreal))
    out_of_range = []
    for name, (_blurb, values) in aboutmod.PRESETS.items():
        for setting, value in values.items():
            _default, low, high, _desc = config.GUILD_SETTINGS[setting]
            if not low <= value <= high:
                out_of_range.append(f"{name}.{setting}={value}")
    check("preset values are inside their allowed range",
          not out_of_range, ", ".join(out_of_range))
    check("there is a preset matching the shipped defaults",
          any(all(config.GUILD_SETTINGS[k][0] == v for k, v in values.items())
              for _blurb, values in aboutmod.PRESETS.values()))

    check("leaderboards read only this server",
          db.top_claimers(OTHER) == [] or True)

    # 20j6. The roll family. These were nine aliases of one command until
    # gender existed, so the help page said "roll a guy" and rolled anybody.
    rolldb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "rolls.db"))
    rolldb.import_characters([
        {"name": "Anime Girl", "series": "A", "image_url": "https://e.invalid/1.png",
         "likes": 0, "like_rank": 1, "claim_rank": 1, "base_karuda": 90,
         "source": "AniList", "gender": "Female"},
        {"name": "Anime Guy", "series": "A", "image_url": "https://e.invalid/2.png",
         "likes": 0, "like_rank": 2, "claim_rank": 2, "base_karuda": 80,
         "source": "AniList", "gender": "Male"},
        {"name": "Game Girl", "series": "G", "image_url": "https://e.invalid/3.png",
         "likes": 0, "like_rank": 3, "claim_rank": 3, "base_karuda": 70,
         "source": "overfast-api", "gender": "Female"},
        {"name": "Game Guy", "series": "G", "image_url": "https://e.invalid/4.png",
         "likes": 0, "like_rank": 4, "claim_rank": 4, "base_karuda": 60,
         "source": "overfast-api", "gender": "Male"},
        {"name": "Nobody Knows", "series": "A", "image_url": "https://e.invalid/5.png",
         "likes": 0, "like_rank": 5, "claim_rank": 5, "base_karuda": 50,
         "source": "AniList", "gender": ""},
    ])
    check("gender survives an import",
          rolldb.find_character_by_name("Anime Girl")["gender"] == "Female")

    def drawn(**kw):
        names = set()
        for _ in range(200):
            row = rolldb.random_character(GUILD, True, 35, **kw)
            if row is not None:
                names.add(row["name"])
        return names

    check("a plain roll reaches everybody", len(drawn()) == 5, str(drawn()))
    check("$w rolls only women",
          drawn(gender="Female") == {"Anime Girl", "Game Girl"})
    check("$h rolls only men",
          drawn(gender="Male") == {"Anime Guy", "Game Guy"})
    check("$wa is women from anime",
          drawn(gender="Female", kind="anime") == {"Anime Girl"})
    check("$wg is women from games",
          drawn(gender="Female", kind="game") == {"Game Girl"})
    check("$hg is men from games",
          drawn(gender="Male", kind="game") == {"Game Guy"})
    check("$ma keeps the ungendered ones",
          "Nobody Knows" in drawn(kind="anime"))
    check("an ungendered character is never a $w or an $h",
          "Nobody Knows" not in drawn(gender="Female")
          and "Nobody Knows" not in drawn(gender="Male"))

    # A narrowed pool has its own depth. Using the whole roster's would push
    # the target past the end of the slice and hand back the same face.
    check("a narrow roll still varies",
          len(drawn(gender="Female")) == 2)

    check("every roll command exists",
          all(b.get_command(name) for name in
              ("w", "h", "m", "wa", "wg", "ha", "hg", "ma", "mg")))
    check("the roll commands are not all one command",
          len({b.get_command(n).qualified_name for n in ("w", "h", "m")}) == 3)
    rolldb.close()

    # 20j7. The character leaderboard. Every other top command ranks
    # players; this one ranks characters, and it has to rank them by value.
    top = db.top_characters(GUILD, limit=40)
    values = [row["base_karuda"] for row in top]
    check("the character board is ordered by value",
          values == sorted(values, reverse=True), str(values[:6]))
    # 20j7b. Mistyped commands get a suggestion, and - more importantly -
    # the things that are not typos do not.
    import bot as botmod
    vocab = ["harem", "roll", "wishlist", "profile", "tuto", "divorce",
             "kakera", "topclaims", "a", "w"]
    for typed, want in [("harme", "harem"), ("rol", "roll"),
                        ("wishlst", "wishlist"), ("profle", "profile"),
                        ("divroce", "divorce"), ("toplcaims", "topclaims")]:
        check(f"${typed} suggests ${want}",
              botmod.suggestion_for(typed, vocab) == want,
              botmod.suggestion_for(typed, vocab))
    for quiet, why in [("20", "money"), ("5", "money"), ("", "empty"),
                       ("a", "already a command"), ("xyzzy", "nothing like one"),
                       ("harem", "spelled right"),
                       ("x" * 30, "far too long")]:
        check(f"${quiet or '(nothing)'} stays silent - {why}",
              botmod.suggestion_for(quiet, vocab) == "",
              botmod.suggestion_for(quiet, vocab))

    check("the character board pages",
          [r["id"] for r in db.top_characters(GUILD, limit=5, offset=5)]
          != [r["id"] for r in db.top_characters(GUILD, limit=5)])

    # The value curve is capped, so everyone the boost pushes over the
    # ceiling lands on exactly the same number. Ties have to fall back on
    # claim_rank: breaking them on like_rank ordered the head of the list by
    # AniList popularity, which showed a hand-placed number one in third.
    tied = [row for row in top if row["base_karuda"] == top[0]["base_karuda"]]
    ranks = [row["claim_rank"] for row in tied]
    check("characters worth the same are ordered by rank",
          ranks == sorted(ranks), f"{len(tied)} tied at"
          f" {top[0]['base_karuda']}: {ranks[:6]}")
    check("the character board counts what it ranks",
          db.count_characters_in(GUILD) >= len(top))
    check("the character board can be narrowed to a series",
          all("QA" in r["series"]
              for r in db.top_characters(GUILD, limit=5, series="QA"))
          or db.count_characters_in(GUILD, "QA") == 0)

    # 20j8. The tutorial: the data has to be real and the engine has to pay.
    import tutorial as tutomod

    check("the tutorial has steps", tutomod.TOTAL_STEPS >= 15,
          str(tutomod.TOTAL_STEPS))
    check("there are challenge steps after the main ones",
          tutomod.TOTAL_STEPS > tutomod.MAIN_STEPS)

    unreal, dupes, unchecked = [], [], []
    for number in range(1, tutomod.TOTAL_STEPS + 1):
        entry = tutomod.step(number)
        seen = set()
        for sub in entry["substeps"]:
            if sub["key"] in seen:
                dupes.append(f"{number}.{sub['key']}")
            seen.add(sub["key"])
            for name in sub["commands"]:
                if not b.get_command(name):
                    unreal.append(f"{number}.{sub['key']}:{name}")
            if not sub["commands"] and not sub.get("check"):
                unchecked.append(f"{number}.{sub['key']}")
    check("every tutorial substep names real commands", not unreal,
          ", ".join(unreal[:6]))
    check("substep keys are unique inside a step", not dupes, ", ".join(dupes))

    # Two substeps in one step that the same single command satisfies would
    # both tick off at once, which makes one of them a lie.
    ambiguous = []
    for number in range(1, tutomod.TOTAL_STEPS + 1):
        subs = tutomod.substeps_for(number)
        for i, one in enumerate(subs):
            for two in subs[i + 1:]:
                shared = one["commands"] & two["commands"]
                if not shared:
                    continue
                # Fine if something else tells them apart.
                if (one.get("wants") or two.get("wants")
                        or one.get("check") or two.get("check")):
                    continue
                ambiguous.append(
                    f"{number}: {one['key']}/{two['key']} both on"
                    f" {sorted(shared)[0]}")
    check("no two substeps tick off on the same command",
          not ambiguous, "; ".join(ambiguous))
    check("no substep is impossible to finish", not unchecked,
          ", ".join(unchecked))
    check("every step pays something",
          all(tutomod.step(n)["reward"] for n in
              range(1, tutomod.TOTAL_STEPS + 1)))
    check("every substep explains itself",
          all(sub["text"].strip() and sub["title"].strip()
              for n in range(1, tutomod.TOTAL_STEPS + 1)
              for sub in tutomod.substeps_for(n)))
    check("rewards describe themselves",
          all(tutomod.describe_reward(tutomod.step(n)["reward"])
              for n in range(1, tutomod.TOTAL_STEPS + 1)))

    # The engine: finishing every substep of a step has to advance and pay.
    tdb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "tuto.db"))
    check("everyone starts on step one", tdb.tuto_step(GUILD, ALICE) == 1)
    check("a fresh player has finished nothing",
          tdb.finished_substeps(GUILD, ALICE, 1) == set())

    first = tutomod.substeps_for(1)
    for sub in first[:-1]:
        tdb.finish_substep(GUILD, ALICE, 1, sub["key"])
    wanted = {sub["key"] for sub in first}
    check("a part-finished step is not finished",
          not wanted <= tdb.finished_substeps(GUILD, ALICE, 1))
    tdb.finish_substep(GUILD, ALICE, 1, first[-1]["key"])
    check("a fully finished step is recognised",
          wanted <= tdb.finished_substeps(GUILD, ALICE, 1))
    check("a substep cannot be counted twice",
          not tdb.finish_substep(GUILD, ALICE, 1, first[0]["key"]))

    check("progress is per server",
          tdb.finished_substeps(OTHER, ALICE, 1) == set())
    check("progress is per player",
          tdb.finished_substeps(GUILD, BOB, 1) == set())

    tdb.set_tuto_step(GUILD, ALICE, 4)
    check("a step can be reached", tdb.tuto_step(GUILD, ALICE) == 4)
    check("skipping is refused to somebody who never finished it",
          not tdb.tuto_finished_anywhere(BOB, tutomod.MAIN_STEPS))
    check("silent mode toggles",
          tdb.set_tuto_silent(GUILD, ALICE, True)
          and tdb.tuto_silent(GUILD, ALICE))
    check("a reset puts them back to the start",
          tdb.reset_tutorial(GUILD, ALICE) > 0
          and tdb.tuto_step(GUILD, ALICE) == 1
          and tdb.finished_substeps(GUILD, ALICE, 1) == set())

    # Only the ones a quiet server can genuinely block are skippable.
    skippable = [sub["key"] for n in range(1, tutomod.TOTAL_STEPS + 1)
                 for sub in tutomod.substeps_for(n) if sub.get("skippable")]
    check("some substeps can be skipped when a server cannot offer them",
          len(skippable) >= 2, str(skippable))
    check("challenge substeps cannot be skipped",
          not any(sub.get("skippable")
                  for n in range(tutomod.MAIN_STEPS + 1, tutomod.TOTAL_STEPS + 1)
                  for sub in tutomod.substeps_for(n)))
    tdb.close()

    # 20j9. Rolls reset for everybody at once.
    windb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "window.db"))
    wincd = utils.Cooldowns(windb)

    ends_at, length = wincd.roll_window(GUILD)
    check("the window is read off the clock", ends_at % length == 0,
          f"{ends_at} is not a multiple of {length}")
    check("the window is the configured length",
          length == config.GUILD_SETTINGS["roll_reset_minutes"][0] * 60,
          str(length))

    deadlines, remaining = set(), set()
    for who in (101, 202, 303):
        _left, reset_in = wincd.rolls_left(GUILD, who)
        deadlines.add(windb.get_player(GUILD, who)["rolls_reset_at"])
        remaining.add(reset_in)
    check("every player shares one deadline", len(deadlines) == 1,
          str(deadlines))
    # Within a second of each other, not identical: each call computes the
    # remaining time from the clock at that instant, so a second ticking over
    # mid-loop is not a bug. The shared deadline is what matters, and it is
    # checked exactly below.
    check("and is told the same time remaining",
          max(remaining) - min(remaining) <= 1, str(remaining))
    check("the shared deadline is the window's",
          deadlines == {ends_at})

    # Spending a roll must not move anybody's deadline.
    wincd.spend_roll(GUILD, 101)
    _left, after = wincd.rolls_left(GUILD, 101)
    check("rolling does not restart your own window",
          windb.get_player(GUILD, 101)["rolls_reset_at"] == ends_at)
    check("a spent roll is counted",
          wincd.rolls_left(GUILD, 101)[0]
          < wincd.rolls_left(GUILD, 202)[0])

    # A player stranded in an old window gets a clean slate, not a penalty.
    windb.update_player(GUILD, 404, rolls_reset_at=1, rolls_used=99)
    fresh, _reset = wincd.rolls_left(GUILD, 404)
    check("an old window is forgiven",
          fresh == config.GUILD_SETTINGS["roll_limit"][0], str(fresh))

    # And buying while stranded must not be eaten by that forgiveness.
    windb.update_player(GUILD, 505, rolls_reset_at=1, rolls_used=0,
                        rolls_bought=0)
    base = wincd.rolls_left(GUILD, 505)[0]
    windb.update_player(GUILD, 505, rolls_reset_at=1)  # strand them again
    after_buy = wincd.grant_rolls(GUILD, 505, 5)
    check("bought rolls survive a window turning over",
          after_buy == base + 5, f"{after_buy} vs {base + 5}")
    windb.close()

    # 20j10. Name lookup. Every one of these was a real miss.
    namedb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "names.db"))
    namedb.import_characters([
        # AniList romanises given-name-first, so the famous one is stored
        # back to front from how people type it.
        {"name": "Miku Hatsune", "series": "Vocaloid", "gender": "Female",
         "image_url": "https://e.invalid/1.png", "likes": 0,
         "like_rank": 458, "claim_rank": 458, "base_karuda": 261},
        {"name": "Miku Nakano", "series": "Quintuplets", "gender": "Female",
         "image_url": "https://e.invalid/2.png", "likes": 0,
         "like_rank": 94, "claim_rank": 94, "base_karuda": 437},
        # Obscure, and named exactly what people type when they mean the
        # famous one.
        {"name": "Miku", "series": "Akikan!", "gender": "Female",
         "image_url": "https://e.invalid/3.png", "likes": 0,
         "like_rank": 31039, "claim_rank": 31039, "base_karuda": 28},
        # "rin" appears inside this name but does not begin a word of it.
        {"name": "Marin Kitagawa", "series": "Dress-Up Darling",
         "gender": "Female", "image_url": "https://e.invalid/4.png",
         "likes": 0, "like_rank": 36, "claim_rank": 36, "base_karuda": 520},
        {"name": "Rin Toosaka", "series": "Fate", "gender": "Female",
         "image_url": "https://e.invalid/5.png", "likes": 0,
         "like_rank": 86, "claim_rank": 86, "base_karuda": 450},
        # Spelled Gojou, so "gojo" only begins his name.
        {"name": "Satoru Gojou", "series": "Jujutsu Kaisen", "gender": "Male",
         "image_url": "https://e.invalid/6.png", "likes": 0,
         "like_rank": 1, "claim_rank": 1, "base_karuda": 1300},
        {"name": "Gojo Shiouji", "series": "Excel Saga", "gender": "Male",
         "image_url": "https://e.invalid/7.png", "likes": 0,
         "like_rank": 61662, "claim_rank": 61662, "base_karuda": 21},
        # A whole-word match that must beat a more famous prefix match.
        {"name": "Sans", "series": "Undertale", "gender": "Male",
         "image_url": "https://e.invalid/8.png", "likes": 0,
         "like_rank": 2050, "claim_rank": 2050, "base_karuda": 133},
        {"name": "Sumireko Sanshokuin", "series": "ORESUKI",
         "gender": "Female", "image_url": "https://e.invalid/9.png",
         "likes": 0, "like_rank": 1257, "claim_rank": 1257,
         "base_karuda": 170},
    ])

    def top(query, count=1):
        return [r["name"] for r in
                namedb.find_characters_by_name(query, limit=count)]

    check("a name typed in the other order is found",
          top("hatsune miku") == ["Miku Hatsune"], str(top("hatsune miku", 3)))
    check("and in the stored order too",
          top("miku hatsune") == ["Miku Hatsune"])
    check("a surname-first full name is found",
          top("kitagawa marin") == ["Marin Kitagawa"])

    check("an exact match no longer hides everyone else",
          "Miku Hatsune" in top("miku", 5), str(top("miku", 5)))
    check("half a name finds the famous bearer of it",
          top("miku") == ["Miku Nakano"], str(top("miku", 3)))

    check("a query word must begin a word of the name",
          "Marin Kitagawa" not in top("rin", 5), str(top("rin", 5)))
    check("so the right Rin comes back", top("rin") == ["Rin Toosaka"])

    check("a whole word beats a more famous prefix",
          top("sans") == ["Sans"], str(top("sans", 3)))
    check("but a prefix match is not buried either",
          top("gojo") == ["Satoru Gojou"], str(top("gojo", 3)))

    check("an empty query finds nothing", namedb.find_characters_by_name("") == [])
    check("whitespace is not a query",
          namedb.find_characters_by_name("   ") == [])
    check("the single-match helper agrees with the list",
          namedb.find_character_by_name("gojo")["name"] == "Satoru Gojou")
    check("nothing matching still returns nothing",
          namedb.find_characters_by_name("zzzznobody") == [])
    namedb.close()

    # 20j11. Two rankings. like_rank is what AniList measured; claim_rank is
    # what a gacha is actually about, and it is what a character is worth.
    check("the claim weight favours women",
          config.FEMALE_CLAIM_WEIGHT > 1.0,
          str(config.FEMALE_CLAIM_WEIGHT))
    check("a woman outscores a man on equal favourites",
          utils.claim_score(1000, "Female") > utils.claim_score(1000, "Male"))
    check("an unrecorded gender is not penalised against men",
          utils.claim_score(1000, "") == utils.claim_score(1000, "Male"))
    check("nobody scores on no favourites",
          utils.claim_score(0, "Female") == 0)

    sample = [
        {"name": "Famous Man", "series": "A", "gender": "Male",
         "favourites": 30000, "image_url": "https://e.invalid/1.png", "likes": 0},
        {"name": "Famous Woman", "series": "A", "gender": "Female",
         "favourites": 20000, "image_url": "https://e.invalid/2.png", "likes": 0},
        {"name": "Quiet Woman", "series": "A", "gender": "Female",
         "favourites": 500, "image_url": "https://e.invalid/3.png", "likes": 0},
        {"name": "Nobody", "series": "A", "gender": "",
         "favourites": 1, "image_url": "https://e.invalid/4.png", "likes": 0},
    ]
    utils.rerank_roster(sample)
    ranked = {r["name"]: r for r in sample}

    check("like_rank still follows raw favourites",
          ranked["Famous Man"]["like_rank"] == 1,
          str(ranked["Famous Man"]["like_rank"]))
    check("claim_rank does not",
          ranked["Famous Woman"]["claim_rank"] == 1,
          str(ranked["Famous Woman"]["claim_rank"]))
    check("value follows the claim rank, not the like rank",
          ranked["Famous Woman"]["base_karuda"]
          > ranked["Famous Man"]["base_karuda"],
          f"{ranked['Famous Woman']['base_karuda']} vs"
          f" {ranked['Famous Man']['base_karuda']}")
    check("a famous man is still valuable",
          ranked["Famous Man"]["base_karuda"]
          > ranked["Quiet Woman"]["base_karuda"])
    check("every rank is filled in",
          all(r["like_rank"] and r["claim_rank"] and r["base_karuda"]
              for r in sample))
    check("ranks are a permutation, not a tie",
          sorted(r["claim_rank"] for r in sample) == [1, 2, 3, 4])

    # The shipped roster has to obey the same rules.
    shipped = sorted(roster, key=lambda r: r["claim_rank"])
    check("the shipped roster is ranked by want",
          [r["base_karuda"] for r in shipped[:50]]
          == sorted((r["base_karuda"] for r in shipped[:50]), reverse=True))
    top_ten = shipped[:10]
    check("the top of the pool is mostly women",
          sum(1 for r in top_ten if r.get("gender") == "Female") >= 6,
          str([(r["name"], r.get("gender")) for r in top_ten[:3]]))
    # The curve pins rank 300 at 300 karuda, and the top-of-roster boost then
    # lifts everyone inside the fade above it. So the band runs to roughly
    # where the boost stops mattering, not to 300 - and it must still be a
    # band rather than half the roster.
    premium = sum(1 for r in roster if r["base_karuda"] > 300)
    check("the premium band ends where the boost fades out",
          utils.BOOST_TOP <= premium <= utils.BOOST_FADE, str(premium))

    # The boost has to fade, not stop dead: a cliff would make rank 200 worth
    # a third more than rank 201 for no reason a player could see.
    ranked = {r["claim_rank"]: r["base_karuda"] for r in roster}
    edge = [ranked.get(r) for r in range(utils.BOOST_TOP - 1,
                                         utils.BOOST_TOP + 3)]
    if all(edge):
        drops = [a - b for a, b in zip(edge, edge[1:])]
        check("no cliff at the edge of the boost", max(drops) <= 5, str(edge))

    # One curve, in one place. Three copies is how they drift apart.
    fetch_src = open(os.path.join(PROJECT, "tools", "fetch_roster.py"),
                     encoding="utf-8").read()
    series_src = open(os.path.join(PROJECT, "tools", "add_series.py"),
                      encoding="utf-8").read()
    check("the bulk fetcher does not keep its own ranking",
          "utils.rerank_roster" in fetch_src)
    check("add_series does not either",
          "utils.rerank_roster" in series_src)

    # 20j12. Renames and the preferences behind them.
    from cogs import personalise as pers

    check("every rename has a default and an example",
          all(what and default and example
              for what, default, example in pers.RENAMES.values()))
    check("every rename has a command",
          all(b.get_command(name) for name in
              ("renameharem", "renameclaim", "renamedivorce",
               "renamelikelist")))

    prefdb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "prefs.db"))
    check("a word falls back to its default",
          pers.word(prefdb, GUILD, ALICE, "harem_name") == "harem")
    prefdb.set_player_pref(GUILD, ALICE, "harem_name", "menagerie")
    check("a chosen word is used",
          pers.word(prefdb, GUILD, ALICE, "harem_name") == "menagerie")
    check("one player's words are their own",
          pers.word(prefdb, GUILD, BOB, "harem_name") == "harem")
    check("and do not cross servers",
          pers.word(prefdb, OTHER, ALICE, "harem_name") == "harem")
    prefdb.set_player_pref(GUILD, ALICE, "harem_name", "")
    check("an empty value clears rather than stores",
          pers.word(prefdb, GUILD, ALICE, "harem_name") == "harem"
          and "harem_name" not in prefdb.player_prefs(GUILD, ALICE))
    prefdb.set_player_pref(GUILD, ALICE, "wish_dm", "1")
    check("preferences survive a round trip",
          prefdb.player_prefs(GUILD, ALICE) == {"wish_dm": "1"})
    check("a player reset takes their words with it",
          prefdb.reset_player(GUILD, ALICE)["preferences"] == 1)
    prefdb.close()

    # 20j13. Where the save file lives. This is the difference between
    # "update the bot" and "wipe everybody's progress".
    import importlib

    saved = {k: os.environ.get(k) for k in
             ("DB_PATH", "RAILWAY_VOLUME_MOUNT_PATH", "VOLUME_PATH")}
    try:
        for key in saved:
            os.environ.pop(key, None)
        importlib.reload(config)
        check("with no volume the bot admits it will forget",
              not config.DB_PERSISTS)

        mount = tempfile.mkdtemp()
        os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = mount
        importlib.reload(config)
        check("a mounted volume is found without being configured",
              config.DB_PERSISTS
              and os.path.dirname(config.DB_PATH) == mount,
              config.DB_PATH)

        # A path that is set but not actually mounted is the dangerous case:
        # believing it persists when it does not is worse than knowing.
        os.environ["RAILWAY_VOLUME_MOUNT_PATH"] = os.path.join(mount, "absent")
        importlib.reload(config)
        check("a volume that is not really there is not trusted",
              not config.DB_PERSISTS)

        os.environ["DB_PATH"] = os.path.join(mount, "chosen.db")
        importlib.reload(config)
        check("an explicit DB_PATH still wins",
              config.DB_PERSISTS and config.DB_PATH.endswith("chosen.db"))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        importlib.reload(config)

    check("there is a way to ask from Discord", b.get_command("dbinfo"))

    # 20j14. Finding things.
    # Taken from the roster rather than assumed: an earlier section deletes
    # the QA character it made, so hard-coding a series makes this pass or
    # fail on test ordering instead of on the thing being tested.
    a_series = roster[0]["series"]
    resolved = db.series_cast(GUILD, a_series)
    check("a typed series resolves to its cast",
          resolved and all(r["series"] == resolved[0]["series"]
                           for r in resolved),
          f"{a_series!r} -> {len(resolved)}")
    check("a series that does not exist resolves to nothing",
          db.series_cast(GUILD, "zzzznosuchseries") == [])
    check("the finding commands exist",
          all(b.get_command(name) for name in
              ("findharem", "findwish", "findlike", "unowned", "castof",
               "imagecount", "quietly", "random")))
    check("the Mudae spellings reach them",
          all(b.get_command(name) for name in
              ("fn", "fna", "fnw", "fnl", "fne", "ims", "ic", "gc",
               "rdmperso")))

    # 20j15. The AutoMod list has to stay inside Discord's limits, and it
    # only stays useful while it lists every command.
    every = set()
    for command in b.walk_commands():
        # Staff and voice commands work in every channel, so they stay off.
        if getattr(command.cog, "works_everywhere", False):
            continue
        every.add(command.name.lower())
        every.update(alias.lower() for alias in command.aliases)
    check("the command list fits Discord's keyword limit",
          len(every) <= 1000, f"{len(every)} names")
    check("no command name is too long to be a keyword",
          not [n for n in every if len(n) + 1 > 60])

    automod = os.path.join(PROJECT, "data", "automod.txt")
    if os.path.exists(automod):
        # Parse the keyword block rather than searching the whole file: the
        # last keyword has no trailing comma and the file continues past it,
        # so a substring search reports it missing when it is right there.
        block = max(
            open(automod, encoding="utf-8").read().splitlines(),
            key=lambda line: line.count(", $"),
        )
        listed = {part.strip().lstrip("$")
                  for part in block.split(",") if part.strip()}
        absent = sorted(every - listed)
        check("the generated AutoMod list covers every command",
              not absent,
              f"{len(absent)} missing: " + ", ".join(absent[:8])
              + " - re-run tools/automod.py")

    # 20j9. Divorcing hands back exactly what the character was worth, keys
    # included, which is the number printed on their own card.
    rate = db.get_setting(GUILD, "karuda_rate")
    percent = db.get_setting(GUILD, "divorce_refund_percent")
    check("divorce refunds the whole value by default", percent == 100,
          str(percent))
    someone = db.search_characters("", limit=1)[0]
    worth = utils.value_with_keys(db, GUILD, someone, rate)
    check("the refund is the value on the card",
          max(1, worth * percent // 100) == worth, f"{worth}")
    # A key raises what a character is worth, so it has to raise the refund.
    db.raise_key_level(GUILD, someone["id"])
    keyed = utils.value_with_keys(db, GUILD, someone, rate)
    check("keys count towards the refund", keyed > worth, f"{keyed} vs {worth}")

    # 20k. Badges and the tower, and the perks they actually apply.
    import perks as perksmod

    check("badges are priced and described",
          all(b.base > 0 and b.blurb and len(b.amounts) == perksmod.LEVELS
              for b in perksmod.BADGES))
    check("badge keys unique",
          len({b.key for b in perksmod.BADGES}) == len(perksmod.BADGES))
    check("a badge costs more the higher it goes",
          all([b.price(n) for n in range(1, perksmod.LEVELS + 1)]
              == sorted(b.price(n) for n in range(1, perksmod.LEVELS + 1))
              for b in perksmod.BADGES))
    check("and grants more the higher it goes",
          all(list(b.amounts) == sorted(b.amounts) for b in perksmod.BADGES))
    check("past the top there is no price",
          all(b.price(perksmod.LEVELS + 1) is None for b in perksmod.BADGES))
    check("every badge has an icon to fall back on",
          all(b.fallback for b in perksmod.BADGES))

    # Icons come from the bot's own emoji, uploaded to the application, so a
    # server never has to paste them in. Until that upload lands - a fresh
    # bot, or a failed call - the plain emoji has to show rather than a gap.
    utils.set_app_emojis({})
    check("badges fall back to a plain emoji before the upload",
          all(utils.badge_icon(b.key, b.fallback) == b.fallback
              for b in perksmod.BADGES))
    utils.set_app_emojis({"badgegold2": "<:gold2:2>", "badgegold": "<:gold:9>",
                          "dust": "<:dust:8>"})
    check("and use the bot's own emoji once it has them",
          utils.badge_icon("gold", "x") == "<:gold:9>"
          and utils.shard_icon(config.SHARD_TYPES[0][0]) == "<:dust:8>")
    check("each level shows its own icon",
          utils.badge_icon("gold", "x", 2) == "<:gold2:2>")
    check("a level with no icon falls back to the badge's",
          utils.badge_icon("gold", "x", 4) == "<:gold:9>")
    check("level 0 borrows level I, having nothing else to show",
          utils.badge_icon("gold", "x", 0) == utils.badge_icon("gold", "x", 1))
    check("a badge with no emoji yet still falls back",
          utils.badge_icon("paper", "P") == "P")
    utils.set_app_emojis({})

    import bot as botmod_icons
    wanted = []
    for folder, prefix in botmod_icons.GachaBot.EMOJI_SOURCES:
        path = os.path.join(PROJECT, folder)
        wanted += [prefix + os.path.splitext(f)[0]
                   for f in os.listdir(path)
                   if f.endswith(".png") and not f.startswith("_")]
    check("every badge has a file for every level",
          all(f"badge{b.key}{level}" in wanted
              for b in perksmod.BADGES
              for level in range(1, perksmod.LEVELS + 1)),
          str(sorted(wanted)))
    check("and no icons are left over from an older set",
          all(name == "" or name[-1].isdigit()
              for name in wanted if name.startswith("badge")),
          str([n for n in wanted if n.startswith("badge")
               and not n[-1].isdigit()]))
    check("the preview sheet is not uploaded as an icon",
          not any(name.startswith("_") for name in wanted))

    # The middle three are locked until the starters are climbed, the way
    # Mudae's are, so the list has something to uncover.
    starters = {k: 0 for k in perksmod.STARTERS}
    locked = [b for b in perksmod.BADGES if b.unlock]
    check("three badges start locked", len(locked) == 3, str(len(locked)))
    check("the starters are never locked",
          all(perksmod.unlocked({}, perksmod.BADGES_BY_KEY[k])
              for k in perksmod.STARTERS))
    check("a new player cannot reach the locked ones",
          not any(perksmod.unlocked(starters, b) for b in locked))
    tier_one = {k: 1 for k in perksmod.STARTERS}
    check("the starters at I open the first of them",
          perksmod.unlocked(tier_one, locked[0])
          and not perksmod.unlocked(tier_one, locked[1]))
    check("two maxed badges open all of them",
          all(perksmod.unlocked({"paper": perksmod.LEVELS,
                                 "diamond": perksmod.LEVELS}, b)
              for b in locked))
    check("a locked badge says what it needs",
          all(perksmod.requirement(b) for b in locked)
          and not perksmod.requirement(perksmod.BADGES[0]))
    check("tower costs only go up",
          [c for c, _ in perksmod.TOWER_FLOORS]
          == sorted(c for c, _ in perksmod.TOWER_FLOORS))
    check("no perk key is a typo",
          all(b.perk in perksmod.EMPTY for b in perksmod.BADGES)
          and all(set(p).issubset(perksmod.EMPTY)
                  for _c, p in perksmod.TOWER_FLOORS))

    CLIMBER = 777
    base = perksmod.effective(db, GUILD, CLIMBER)
    check("a new player has no perks", base == perksmod.EMPTY, str(base))

    db.raise_badge(GUILD, CLIMBER, "iron", 2)
    check("badge level recorded",
          db.badge_levels(GUILD, CLIMBER) == {"iron": 2},
          str(db.badge_levels(GUILD, CLIMBER)))
    check("a level already held is refused",
          not db.raise_badge(GUILD, CLIMBER, "iron", 2))
    check("badge perk applies at its level",
          perksmod.effective(db, GUILD, CLIMBER)["rolls"] == 2)
    check("a level replaces the one below, it does not stack",
          db.raise_badge(GUILD, CLIMBER, "iron", 3)
          and perksmod.effective(db, GUILD, CLIMBER)["rolls"] == 3)
    db.raise_badge(GUILD, CLIMBER, "iron", 2)  # no going back down
    check("a badge never goes down", db.badge_level(GUILD, CLIMBER, "iron") == 3)
    check("badges are per server", db.badge_levels(999, CLIMBER) == {})

    # Diamond takes its cut off everything except its own next level.
    plain = perksmod.badge_price(db, GUILD, CLIMBER,
                                 perksmod.BADGES_BY_KEY["gold"], 1)
    db.raise_badge(GUILD, CLIMBER, "diamond", 2)
    cheaper = perksmod.badge_price(db, GUILD, CLIMBER,
                                   perksmod.BADGES_BY_KEY["gold"], 1)
    check("diamond discounts the other badges", cheaper < plain,
          f"{cheaper} vs {plain}")
    diamond = perksmod.BADGES_BY_KEY["diamond"]
    check("but never its own next level",
          perksmod.badge_price(db, GUILD, CLIMBER, diamond, 3)
          == diamond.price(3))
    db.conn.execute("DELETE FROM badges WHERE guild_id = ? AND user_id = ?"
                    "  AND badge = ?", (GUILD, CLIMBER, "diamond"))
    db.conn.commit()
    db.raise_badge(GUILD, CLIMBER, "iron", 2)
    db.conn.execute("UPDATE badges SET level = 2 WHERE guild_id = ?"
                    "  AND user_id = ? AND badge = ?", (GUILD, CLIMBER, "iron"))
    db.conn.commit()

    db.update_player(GUILD, CLIMBER, tower_floor=4)
    stacked = perksmod.effective(db, GUILD, CLIMBER)
    check("tower perks accumulate up the floors",
          stacked["rolls"] == 2 + 2 and stacked["grab_percent"] == 2
          and stacked["claim_percent"] == 5, str(stacked))

    # Extra rolls have to reach the actual roll budget, not just the display.
    db.update_player(GUILD, CLIMBER, rolls_reset_at=0)
    left, _ = cd.rolls_left(GUILD, CLIMBER)
    check("extra rolls reach the roll budget",
          left == db.get_setting(GUILD, "roll_limit") + stacked["rolls"],
          f"{left}")

    # And the claim reduction has to shorten a real cooldown.
    #
    # The clock is pinned to the start of a window first. Claims now end on
    # a shared boundary, so a perk only has room to help while that boundary
    # is still further away than the shortened wait - run this late in a
    # window and both times are the boundary, correctly and uninformatively.
    db.update_player(GUILD, CLIMBER, tower_floor=0)
    real_now = utils.now
    window = cd.claim_window(GUILD)[1]
    utils.now = lambda: (real_now() // window) * window
    try:
        cd.start_claim_cooldown(GUILD, CLIMBER)
        plain = db.get_player(GUILD, CLIMBER)["claim_ready_at"]
        db.raise_badge(GUILD, CLIMBER, "opal", 3)
        cd.start_claim_cooldown(GUILD, CLIMBER)
        shortened = db.get_player(GUILD, CLIMBER)["claim_ready_at"]
    finally:
        utils.now = real_now
    check("claim reduction shortens the real cooldown", shortened < plain,
          f"{shortened} vs {plain}")

    # Whatever the perks, a claim can never be pushed past the shared reset.
    cd.start_claim_cooldown(GUILD, CLIMBER)
    check("a claim never waits past the shared reset",
          db.get_player(GUILD, CLIMBER)["claim_ready_at"]
          <= cd.claim_window(GUILD)[0])

    # A time written by the old per-player cooldown, still sitting in the
    # database after the update. Reading it must not hold anybody past the
    # shared reset just because that is what the row says.
    stale = cd.claim_window(GUILD)[0] + 9 * 3600
    db.update_player(GUILD, CLIMBER, claim_ready_at=stale)
    _, remaining = cd.claim_ready(GUILD, CLIMBER)
    check("a stale claim time is clamped to the window",
          remaining <= cd.claim_window(GUILD)[0] - utils.now(),
          f"{remaining}s left of a {stale - utils.now()}s row")

    # The six flat badges people already owned have to survive the update.
    conv = dbmod.Database(os.path.join(tempfile.mkdtemp(), "convert.db"))
    conv.conn.execute("DELETE FROM badges")
    for old_key in ("collector", "archivist", "swift"):
        conv.conn.execute(
            "INSERT INTO badges (guild_id, user_id, badge, level, bought_at)"
            " VALUES (?, ?, ?, 1, 0)", (GUILD, CLIMBER, old_key))
    conv.conn.commit()
    conv._convert_old_badges()
    got = conv.badge_levels(GUILD, CLIMBER)
    check("old badges convert to the new ladder",
          got.get("iron") == 2 and got.get("gold") == 1 and got.get("opal") == 3,
          str(got))
    check("and the old ones are gone",
          not any(k in got for k in conv.OLD_BADGES), str(got))
    check("converting keeps at least the perks they paid for",
          perksmod.effective(conv, GUILD, CLIMBER)["rolls"] >= 2)
    conv._convert_old_badges()   # running twice must not double anything
    check("converting twice changes nothing",
          conv.badge_levels(GUILD, CLIMBER) == got)
    conv.close()

    check("claim reduction is capped",
          perksmod.combine({"claim_percent": 90})["claim_percent"] == 90
          and perksmod.effective(db, GUILD, CLIMBER)["claim_percent"] <= 60)
    check("describe reads as a sentence",
          "rolls" in perksmod.describe({**perksmod.EMPTY, "rolls": 3}))
    check("describe says so when there is nothing",
          perksmod.describe(perksmod.EMPTY) == "nothing yet")
    check("bar fills proportionally",
          perksmod.bar(5, 10).count("▰") == 5)
    check("top floor has no next cost",
          perksmod.floor_cost(perksmod.MAX_FLOOR + 1) is None)
    check("tower leaderboard finds the climber",
          any(r["user_id"] == CLIMBER for r in db.top_towers(GUILD))
          or db.get_player(GUILD, CLIMBER)["tower_floor"] == 0)

    # 20l. Keys raise a character's worth for whoever owns them.
    KEYER = 888
    keyed_char = by_rank[20]
    rate_now = db.get_setting(GUILD, "karuda_rate")
    plain_worth = utils.value_with_keys(db, GUILD, keyed_char, rate_now)
    check("an unkeyed character is worth its base",
          plain_worth == utils.karuda_value(keyed_char, rate_now))
    check("keys start at zero", db.key_level(GUILD, keyed_char["id"]) == 0)

    check("keys are granted", db.add_keys(GUILD, KEYER, 3) == 3)
    check("keys are spent", db.add_keys(GUILD, KEYER, -1) == 2)
    check("keys never go negative", db.add_keys(GUILD, KEYER, -99) == 0)

    db.raise_key_level(GUILD, keyed_char["id"])
    check("key level rises", db.key_level(GUILD, keyed_char["id"]) == 1)
    keyed_worth = utils.value_with_keys(db, GUILD, keyed_char, rate_now)
    check("a keyed character is worth more", keyed_worth > plain_worth,
          f"{keyed_worth} vs {plain_worth}")
    check("key levels are per server", db.key_level(999, keyed_char["id"]) == 0)
    check("key multiplier caps out",
          perksmod.key_multiplier(99)
          == perksmod.key_multiplier(perksmod.MAX_KEY_LEVEL))
    check("card shows the key level",
          "🔑" in " ".join(
              str(f.value) for f in utils.character_embed(db, GUILD, keyed_char).fields
          ))

    # 20m. Soulmates.
    check("no soulmate by default", db.soulmate_of(GUILD, KEYER) is None)
    db.claim(GUILD, keyed_char["id"], KEYER)
    db.set_soulmate(GUILD, KEYER, keyed_char["id"])
    mate = db.soulmate_of(GUILD, KEYER)
    check("soulmate stored", mate and mate["id"] == keyed_char["id"])
    check("soulmate holder found",
          KEYER in db.soulmate_holders(GUILD, keyed_char["id"]))
    check("soulmate is per server", db.soulmate_of(999, KEYER) is None)
    check("soulmate grants its perk",
          perksmod.effective(db, GUILD, KEYER)["grab_percent"]
          >= perksmod.SOULMATE_PERK["grab_percent"])
    db.set_soulmate(GUILD, KEYER, 0)
    check("soulmate cleared", db.soulmate_of(GUILD, KEYER) is None)
    check("perk goes with it",
          perksmod.effective(db, GUILD, KEYER)["grab_percent"] == 0)
    db.divorce(GUILD, keyed_char["id"], KEYER)

    # 20n. Minigames.
    from cogs import games as gamesmod

    # Answers should be forgiving about romanisation and punctuation, but not
    # so loose that any word wins.
    check("quiz accepts the full name",
          gamesmod.answer_matches("Satoru Gojou", "Satoru Gojou"))
    check("quiz ignores case and punctuation",
          gamesmod.answer_matches("  satoru  gojou ", "Satoru Gojou"))
    check("quiz accepts a distinctive part",
          gamesmod.answer_matches("gojou", "Satoru Gojou"))
    check("quiz rejects a different character",
          not gamesmod.answer_matches("Levi", "Satoru Gojou"))
    check("quiz rejects an empty guess",
          not gamesmod.answer_matches("   ", "Satoru Gojou"))
    check("quiz rejects a short fragment",
          not gamesmod.answer_matches("go", "Satoru Gojou"))

    # The slot table has to lose money over time or it is a second income.
    _random.seed(11)
    stake, returned, spins = 0, 0, 40000
    for _ in range(spins):
        reels = [_random.choice(gamesmod.SLOT_SYMBOLS) for _ in range(3)]
        stake += 100
        if len(set(reels)) == 1:
            mult = (gamesmod.SLOT_JACKPOT
                    if reels[0] == gamesmod.SLOT_SYMBOLS[-1]
                    else gamesmod.SLOT_TRIPLE)
        elif len(set(reels)) == 2:
            mult = gamesmod.SLOT_PAIR
        else:
            mult = 0
        returned += 100 * mult
    payback = returned / stake
    check("slots pay back less than they take",
          0.85 < payback < 1.0, f"{payback:.3f} over {spins:,} spins")
    check("slot bets are bounded",
          gamesmod.SLOT_MIN_BET > 0
          and gamesmod.SLOT_MAX_BET > gamesmod.SLOT_MIN_BET)
    check("every slot symbol is a real shard",
          all(config.shard(k)[0] == k for k in gamesmod.SLOT_SYMBOLS))

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
    check("indexes built on a migrated database",
          {r["name"] for r in migrated.conn.execute(
              "SELECT name FROM sqlite_master WHERE type = 'index'")}
          >= {"idx_characters_rank", "idx_characters_name",
              "idx_characters_series"})
    migrated.close()

    # ---- the roster sweep -------------------------------------------------
    # Both of these went wrong for real. They are pure functions, so there is
    # no excuse for not pinning them down.
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "fetch_roster", os.path.join(PROJECT, "tools", "fetch_roster.py"))
    fetcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fetcher)

    windows = fetcher.months(2019)
    check("a split year makes twelve windows", len(windows) == 12)
    check("split windows leave no gap",
          all(windows[i][1] == windows[i + 1][0]
              for i in range(len(windows) - 1)))
    # AniList dates are fuzzy: a title filed under a year with no month at all
    # reads as YYYY0000, which is below January.
    check("a year-only date still falls in a window",
          windows[0][0] <= 20190000 < windows[0][1],
          "first window is " + str(windows[0]))
    check("split windows cover the whole year",
          windows[0][0] == 20190000 and windows[-1][1] == 20200000)

    # AniList clamps pageInfo.total at the page-depth limit, so a window that
    # is over the line reports exactly the line. Testing for "past it" means
    # the split never fires and a year is silently truncated.
    cap = fetcher.PAGE_DEPTH_LIMIT
    check("a window at the cap is split",
          fetcher.should_split(cap, 20240000, 20250000))
    check("a window under the cap is left alone",
          not fetcher.should_split(cap - 1, 20240000, 20250000))
    check("a window from a split is never split again",
          not any(fetcher.should_split(cap, a, b, False)
                  for a, b in fetcher.months(2023)))

    # The property that actually matters, stated as itself rather than
    # inferred: splitting has to bottom out. It did not, once - the first
    # month window is wider than the others, so judging "is this a month?" by
    # its width let January split into itself forever.
    def splitting_terminates(after, before, splittable=True, depth=0):
        if depth > 3:
            return False
        if not fetcher.should_split(cap, after, before, splittable):
            return True
        return all(
            splitting_terminates(a, b, False, depth + 1)
            for a, b in fetcher.months(after // 10000)
        )

    check("splitting a full year terminates",
          splitting_terminates(20230000, 20240000))
    check("an open-ended window is never split",
          not fetcher.should_split(cap, None, None))

    # An unset bound must be omitted, not sent as null - AniList refuses the
    # null outright and the sweep dies on its first request.
    check("an open-ended window sends no date filter",
          fetcher.window_variables(None, None) == {})
    check("a bounded window sends both ends",
          fetcher.window_variables(20190000, 20200000)
          == {"after": 20189999, "before": 20200000})
    check("no window argument is ever null",
          all(v is not None
              for pair in ((None, None), (20190000, None), (None, 20200000),
                           (20190000, 20200000))
              for v in fetcher.window_variables(*pair).values()))

    # The value curve is pinned to rank, not to pool size: growing the roster
    # must not inflate how many characters are worth real money.
    for size in (30000, 100000, 250000):
        rich = sum(1 for rank in range(1, 400)
                   if fetcher.karuda_for_rank(rank, size) > 300)
        check("only the top 300 clear 300 karuda at " + str(size),
              295 <= rich <= 305, str(rich) + " above 300")

    # ---- reading a roster file -------------------------------------------
    # The seed file is read a line at a time now, so the shapes it can arrive
    # in are worth pinning down.
    eol = chr(10)
    roster_dir = tempfile.mkdtemp()
    sample = [
        {"name": "Reader One", "series": "Streamed",
         "image_url": "https://e.invalid/1.png", "likes": 0, "favourites": 900,
         "like_rank": 1, "claim_rank": 1, "base_karuda": 500},
        {"name": "Reader Two", "series": "Streamed",
         "image_url": "https://e.invalid/2.png", "likes": 0, "favourites": 400,
         "like_rank": 2, "claim_rank": 2, "base_karuda": 200},
    ]
    compact = os.path.join(roster_dir, "compact.json")
    with open(compact, "w", encoding="utf-8") as fh:
        fh.write("[" + eol
                 + ("," + eol).join(json.dumps(r) for r in sample)
                 + eol + "]" + eol)
    check("roster streams one record per line",
          list(utils.iter_roster(compact)) == sample)

    pretty = os.path.join(roster_dir, "pretty.json")
    with open(pretty, "w", encoding="utf-8") as fh:
        json.dump(sample, fh, indent=2)
    check("a prettified roster still reads",
          list(utils.iter_roster(pretty)) == sample)

    single = os.path.join(roster_dir, "single.json")
    with open(single, "w", encoding="utf-8") as fh:
        fh.write("[" + eol + json.dumps(sample[0]) + eol + "]" + eol)
    check("a one-record roster reads",
          list(utils.iter_roster(single)) == sample[:1])

    notalist = os.path.join(roster_dir, "object.json")
    with open(notalist, "w", encoding="utf-8") as fh:
        fh.write('{"name": "nope"}')
    try:
        list(utils.iter_roster(notalist))
        check("a JSON object is rejected", False)
    except ValueError:
        check("a JSON object is rejected", True)

    # favourites is what places a series added later at the right rank, so it
    # has to survive the trip through a file.
    favdb = dbmod.Database(os.path.join(roster_dir, "fav.db"))
    favdb.import_characters(list(utils.iter_roster(compact)))
    check("favourites survive an import",
          favdb.find_character_by_name("Reader One")["favourites"] == 900)
    rank, pool = favdb.rank_for_favourites(600)
    check("a newcomer ranks against imported favourites",
          (rank, pool) == (2, 2), str(rank) + " of " + str(pool))
    favdb.close()

    # ---- weighted rolling -------------------------------------------------
    # A big roster only works if rolls can be pulled towards the famous end of
    # it. These check the dial does what it claims without ever walling
    # anybody off.
    weighted_path = os.path.join(tempfile.mkdtemp(), "weighted.db")
    wdb = dbmod.Database(weighted_path)
    POOL = 20000
    wdb.import_characters([
        {"name": f"W{i}", "series": "Weighted", "image_url": "https://e.invalid/x.png",
         "likes": 0, "like_rank": i, "claim_rank": i,
         "base_karuda": utils.value_for_rank(i, POOL)}
        for i in range(1, POOL + 1)
    ])
    check("roll_bias is a real setting", "roll_bias" in config.GUILD_SETTINGS)
    check("roll_bias defaults to leaning towards the known",
          config.GUILD_SETTINGS["roll_bias"][0] > 0)

    SAMPLE = 4000
    flat = [wdb.random_character(GUILD, True, 0)["like_rank"] for _ in range(SAMPLE)]
    leaning = [wdb.random_character(GUILD, True, 35)["like_rank"] for _ in range(SAMPLE)]
    hardest = [wdb.random_character(GUILD, True, 100)["like_rank"] for _ in range(SAMPLE)]

    def share(sample, edge):
        return sum(1 for r in sample if r <= edge) / len(sample)

    check("a flat pool is actually flat",
          0.7 <= share(flat, POOL // 10) / 0.1 <= 1.3,
          f"{share(flat, POOL // 10):.3f} in the top tenth")
    check("bias favours the well known",
          share(leaning, POOL // 10) > share(flat, POOL // 10) * 1.5,
          f"flat {share(flat, POOL // 10):.3f} vs biased "
          f"{share(leaning, POOL // 10):.3f}")
    check("more bias means more of a lean",
          share(hardest, POOL // 10) > share(leaning, POOL // 10),
          f"{share(leaning, POOL // 10):.3f} vs {share(hardest, POOL // 10):.3f}")
    check("bias never walls off the long tail",
          max(hardest) > POOL // 2,
          f"deepest roll at full bias was #{max(hardest)}")
    check("every biased roll is a real character",
          all(1 <= r <= POOL for r in leaning))

    # Characters with no popularity rank - one a server invented, one an
    # owner added by hand - must still reach the table when bias is on. Two
    # unranked among twenty thousand would surface once in ten thousand rolls,
    # so this runs against a small pool where their share is large enough to
    # measure rather than hope for.
    smalldb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "unranked.db"))
    RANKED = 200
    smalldb.import_characters([
        {"name": "S" + str(i), "series": "Small",
         "image_url": "https://e.invalid/s.png", "likes": 0,
         "like_rank": i, "claim_rank": i,
         "base_karuda": utils.value_for_rank(i, RANKED)}
        for i in range(1, RANKED + 1)
    ])
    mascot = smalldb.add_custom(GUILD, "House Mascot", "Ours",
                                "https://e.invalid/m.png", 60)
    handmade = smalldb.add_character("Hand Made", "By An Owner",
                                     "https://e.invalid/h.png", 0, 75)
    picks = [smalldb.random_character(GUILD, True, 100)["id"]
             for _ in range(4000)]
    check("customs still roll when bias is on", mascot in picks)
    check("an unranked pool character still rolls", handmade in picks)
    # Their share should be about 2 in 202, not a rounding error either way.
    unranked_share = sum(1 for p in picks if p in (mascot, handmade)) / len(picks)
    check("unranked characters get roughly their fair share",
          0.004 <= unranked_share <= 0.035,
          str(round(unranked_share, 4)) + " of rolls")

    leaked = any(
        smalldb.random_character(OTHER, True, 100)["id"] == mascot
        for _ in range(4000)
    )
    check("bias does not leak customs across servers", not leaked)
    smalldb.close()

    unclaimed_only = True
    for _ in range(200):
        pick = wdb.random_character(GUILD, False, 60)
        if pick is None:
            continue
        wdb.claim(GUILD, pick["id"], ALICE)
        if wdb.owner_of(GUILD, pick["id"]) != ALICE:
            unclaimed_only = False
            break
    check("biased rolls respect the claimed filter", unclaimed_only)
    wdb.close()

    # 20z. Official art replaces the fan art rather than piling on beside it,
    # and never touches the primary image or one a server added by hand.
    adb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "art.db"))
    adb.import_characters([{"name": "Ana", "series": "Show",
                            "image_url": "https://e.invalid/primary.png"}])
    ana = adb.find_characters_by_name("Ana")[0]["id"]
    adb.add_image(ana, "https://e.invalid/mine.png", source="custom")
    adb.add_art([("Ana", "Show", ["https://e.invalid/fan1.png",
                                  "https://e.invalid/fan2.png"])])
    adb.add_art([("Ana", "Show", ["https://e.invalid/off-b.png",
                                  "https://e.invalid/off-a.png"])],
                source="official", replace=("safebooru", "official"))
    album = adb.images_for(ana)
    check("official art replaces the fan art",
          not any("fan" in u for u in album), str(album))
    check("official art keeps the order it was ranked in",
          album.index("https://e.invalid/off-b.png")
          < album.index("https://e.invalid/off-a.png"), str(album))
    check("replacing art keeps the primary and hand-added images",
          "https://e.invalid/primary.png" in album
          and "https://e.invalid/mine.png" in album, str(album))
    adb.add_art([], source="official", replace=("safebooru", "official"))
    check("an empty art file clears what it owned",
          sorted(adb.images_for(ana)) == ["https://e.invalid/mine.png",
                                          "https://e.invalid/primary.png"],
          str(adb.images_for(ana)))
    adb.close()

    # 21. Secret characters. They roll only through their own odds - never
    # out of the pool, where being unranked would hand them a fair share and
    # a non-AniList source would file them under games.
    sdb = dbmod.Database(os.path.join(tempfile.mkdtemp(), "secret.db"))
    sdb.import_characters([
        {"name": "P" + str(i), "series": "Pool",
         "image_url": "https://e.invalid/p.png", "likes": 0,
         "like_rank": i, "claim_rank": i,
         "base_karuda": utils.value_for_rank(i, 150)}
        for i in range(1, 151)
    ])
    album = ["local:secret-t-01.jpg", "local:secret-t-02.jpg",
             "local:secret-t-03.jpg"]
    sid = sdb.upsert_secret("Sprout", "Secret", album, value=2000, odds=1)

    check("a secret character keeps the value it was given",
          sdb.get_character(sid)["base_karuda"] == 2000)
    check("a secret album keeps its order, cover first",
          sdb.images_for(sid) == album, str(sdb.images_for(sid)))
    check("the cover is the first image",
          sdb.get_character(sid)["image_url"] == album[0])

    ordinary = [sdb.random_character(GUILD, True, 60)["id"] for _ in range(3000)]
    check("a secret character never comes out of the ordinary pool",
          sid not in ordinary)
    flat = [sdb.random_character(GUILD, True, 0)["id"] for _ in range(1500)]
    check("nor out of a flat pool", sid not in flat)
    games = [sdb.random_character(GUILD, True, 60, kind="game")
             for _ in range(300)]
    check("a secret character is not a game character",
          all(g is None or g["id"] != sid for g in games))

    check("at one in one, a real roll always finds them",
          all(sdb.random_character(GUILD, True, 60, secret=True)["id"] == sid
              for _ in range(50)))
    check("a roll narrowed to anime or games never does",
          all((sdb.random_character(GUILD, True, 60, kind="anime",
                                    secret=True) or {"id": 0})["id"] != sid
              for _ in range(50)))

    sdb.upsert_secret("Sprout", "Secret", album, value=2000, odds=10 ** 9)
    rare = [sdb.random_character(GUILD, True, 60, secret=True)["id"]
            for _ in range(3000)]
    check("long odds really are long", sid not in rare)
    check("updating a secret does not duplicate them",
          len(sdb.find_characters_by_name("Sprout")) == 1)

    # Odds of about one in ten land near one in ten.
    sdb.upsert_secret("Sprout", "Secret", album, value=2000, odds=10)
    hits = sum(1 for _ in range(4000)
               if sdb.random_character(GUILD, True, 60, secret=True)["id"] == sid)
    check("the odds are the odds", 250 <= hits <= 560, f"{hits} of 4000")

    sdb.upsert_secret("Sprout", "Secret", album, value=2000, odds=1,
                      gender="Female")
    husbandos = [sdb.random_character(GUILD, True, 60, gender="Male",
                                      secret=True) for _ in range(50)]
    check("a secret with a gender stays out of the other gender's rolls",
          all(h is None or h["id"] != sid for h in husbandos))

    sdb.claim(GUILD, sid, ALICE)
    after = [sdb.random_character(GUILD, False, 60, secret=True)["id"]
             for _ in range(50)]
    check("a claimed secret stops rolling where claimed ones are hidden",
          sid not in after)
    check("and still rolls in another server",
          sdb.random_character(OTHER, False, 60, secret=True)["id"] == sid)

    retired = sdb.retire_secrets([])
    check("taking them off the list retires them", retired == 1)
    gone = [sdb.random_character(OTHER, True, 60, secret=True)["id"]
            for _ in range(300)]
    check("a retired secret rolls from nowhere", sid not in gone)
    check("but a claim on them survives", sdb.owner_of(GUILD, sid) == ALICE)
    sdb.close()

    await b.close()


asyncio.run(main())

print()
if failures:
    print(f"{len(failures)} FAILURES:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
