"""SQLite storage layer. One connection, shared across cogs."""
import random
import logging
import sqlite3
import time
from typing import Optional

import config
import premium

log = logging.getLogger("gacha.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    series      TEXT NOT NULL,
    image_url   TEXT NOT NULL,
    likes       INTEGER NOT NULL DEFAULT 0,
    base_karuda INTEGER NOT NULL DEFAULT 50,
    -- Popularity ranks, 1 = most popular. Lower is better, as in Mudae.
    like_rank   INTEGER NOT NULL DEFAULT 0,
    claim_rank  INTEGER NOT NULL DEFAULT 0,
    -- 0 for the shared pool; a guild id for a character that server invented,
    -- which only rolls there.
    guild_id    INTEGER NOT NULL DEFAULT 0,
    -- AniList favourites, kept so a series added later can be ranked against
    -- everyone already here rather than guessed at.
    favourites  INTEGER NOT NULL DEFAULT 0,
    -- Which API this character came from. AniList means anime or manga;
    -- anything else is a game or a cartoon, which is what lets a server
    -- switch those off without switching off the whole roster.
    source      TEXT NOT NULL DEFAULT '',
    -- What $w and $h sort on. Blank means AniList does not record one, and
    -- roughly half of them do not - those roll under $m only.
    gender      TEXT NOT NULL DEFAULT '',
    UNIQUE (name, series)
);

-- A character can have many images. characters.image_url stays as the primary
-- one (shown on a harem page, and the fallback), while rolls pick at random
-- from the whole album.
CREATE TABLE IF NOT EXISTS character_images (
    character_id INTEGER NOT NULL,
    url          TEXT NOT NULL,
    source       TEXT,
    added_at     INTEGER NOT NULL,
    PRIMARY KEY (character_id, url)
);
CREATE INDEX IF NOT EXISTS idx_images_character
    ON character_images (character_id);


-- Nicknames. A server can teach the bot that "Gojo" means Satoru Gojou, and
-- a player can keep private ones of their own: user_id 0 is the server's,
-- anything else belongs to that person.
CREATE TABLE IF NOT EXISTS character_aliases (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL DEFAULT 0,
    alias        TEXT NOT NULL,
    character_id INTEGER NOT NULL,
    added_at     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, alias)
);
CREATE INDEX IF NOT EXISTS idx_aliases_character
    ON character_aliases (character_id);

-- Things a player holds that are not karuda: teas, mostly. Counted rather
-- than listed, because holding six of the same tea is six of one row.
CREATE TABLE IF NOT EXISTS player_items (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    item     TEXT NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, item)
);

-- One row per substep somebody has finished. Substeps inside a step may be
-- done in any order, so the step itself is only finished when every one of
-- its keys is present.
CREATE TABLE IF NOT EXISTS tutorial_progress (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    step     INTEGER NOT NULL,
    substep  TEXT NOT NULL,
    done_at  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, step, substep)
);

-- Small strings a player chooses for themselves: what to call their harem,
-- whether wish pings come by DM, which character they starred. Text rather
-- than the integer settings table, and per player rather than per server.
CREATE TABLE IF NOT EXISTS player_prefs (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id, key)
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS players (
    guild_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    karuda          INTEGER NOT NULL DEFAULT 0,
    rolls_used      INTEGER NOT NULL DEFAULT 0,
    rolls_reset_at  INTEGER NOT NULL DEFAULT 0,
    claim_ready_at  INTEGER NOT NULL DEFAULT 0,
    karuda_ready_at INTEGER NOT NULL DEFAULT 0,
    daily_ready_at  INTEGER NOT NULL DEFAULT 0,
    rolls_bought    INTEGER NOT NULL DEFAULT 0,
    extra_wish_slots INTEGER NOT NULL DEFAULT 0,
    first_seen      INTEGER NOT NULL DEFAULT 0,
    premium         INTEGER NOT NULL DEFAULT 0,
    tower_floor     INTEGER NOT NULL DEFAULT 0,
    keys            INTEGER NOT NULL DEFAULT 0,
    soulmate_id     INTEGER NOT NULL DEFAULT 0,
    soulmate_set_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

-- A character can be married by at most one user per guild.
CREATE TABLE IF NOT EXISTS marriages (
    guild_id     INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    claimed_at   INTEGER NOT NULL,
    note         TEXT,
    -- A picture pinned to the note, shown on the card instead of the
    -- character's own art when it is set.
    note_image   TEXT,
    PRIMARY KEY (guild_id, character_id)
);
CREATE INDEX IF NOT EXISTS idx_marriages_owner
    ON marriages (guild_id, user_id);

CREATE TABLE IF NOT EXISTS wishes (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, character_id)
);
CREATE INDEX IF NOT EXISTS idx_wishes_character
    ON wishes (guild_id, character_id);

-- Antinuke (cogs/antinuke.py): its settings, and who it trusts and who may
-- change it (kind 'trusted' or 'admin').
CREATE TABLE IF NOT EXISTS antinuke_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, key)
);
CREATE TABLE IF NOT EXISTS antinuke_people (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    kind     TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id, kind)
);

-- The karuda tower (perks.py): one row per floor built, with the perk chosen
-- for it and what it cost, so $destroy can refund exactly.
CREATE TABLE IF NOT EXISTS tower_floors (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    tower    INTEGER NOT NULL,
    perk     INTEGER NOT NULL,
    cost     INTEGER NOT NULL,
    built_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, tower, perk)
);

-- Starwishes (wishes.py): a wish that costs more slots and tilts rolls
-- harder. Not a flag on wishes, because a starwish needs no plain wish.
CREATE TABLE IF NOT EXISTS starwishes (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    added_at     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, character_id)
);
CREATE INDEX IF NOT EXISTS idx_starwishes_character
    ON starwishes (guild_id, character_id);

-- Per-guild prefix. Separate from guild_settings, which only holds numbers.
CREATE TABLE IF NOT EXISTS guild_prefixes (
    guild_id INTEGER PRIMARY KEY,
    prefix   TEXT NOT NULL
);

-- Commands a server has switched off, and channels it has restricted the
-- bot to. No rows for a guild means no restriction.
CREATE TABLE IF NOT EXISTS disabled_commands (
    guild_id INTEGER NOT NULL,
    command  TEXT NOT NULL,
    PRIMARY KEY (guild_id, command)
);
CREATE TABLE IF NOT EXISTS allowed_channels (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- When a server first used the bot. Recorded from the start because
-- grandfathering early adopters is impossible if nobody wrote down who was
-- early; see players.first_seen for the same reason.
CREATE TABLE IF NOT EXISTS guilds (
    guild_id   INTEGER PRIMARY KEY,
    first_seen INTEGER NOT NULL
);

-- Redeemable keys. Nothing is gated yet; this exists so keys handed out now
-- still mean something when something is.
CREATE TABLE IF NOT EXISTS premium_keys (
    key         TEXT PRIMARY KEY,
    note        TEXT,
    created_at  INTEGER NOT NULL,
    redeemed_by INTEGER,
    redeemed_at INTEGER
);

-- Who likes whom. Likes are per server, like everything else, and a like is
-- a vote you can take back - hence a table rather than a counter.
CREATE TABLE IF NOT EXISTS character_likes (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    liked_at     INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, character_id)
);
CREATE INDEX IF NOT EXISTS idx_likes_character
    ON character_likes (guild_id, character_id);

-- How many of each shard type a player has pulled. Flavour and bragging
-- rights; the spendable balance is players.karuda.
-- Badges a player has bought. Perks are looked up from perks.py by key, so
-- rebalancing a badge does not need a migration.
-- A key spent on a character raises their level, which is worth more karuda
-- to whoever owns them. Per guild, like everything else.
CREATE TABLE IF NOT EXISTS character_keys (
    guild_id     INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    level        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, character_id)
);

CREATE TABLE IF NOT EXISTS badges (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    badge    TEXT NOT NULL,
    bought_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, badge)
);

CREATE TABLE IF NOT EXISTS shard_pulls (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    shard    TEXT NOT NULL,
    count    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, shard)
);

-- Staff points, one row per point, so every one keeps who gave it and why.
-- Nothing to do with the gacha: no reset command touches this table.
CREATE TABLE IF NOT EXISTS staff_points (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    given_by INTEGER NOT NULL,
    reason   TEXT NOT NULL DEFAULT '',
    given_at INTEGER NOT NULL
);

-- Every moderation action, one row each. Warnings are cases too, so a
-- member's history is one query rather than several stitched together.
CREATE TABLE IF NOT EXISTS mod_cases (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    mod_id     INTEGER NOT NULL,
    action     TEXT NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    duration   INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

-- The roles and channels $setupmod made. Its own table rather than
-- guild_settings, which $fullreset wipes along with the gacha.
CREATE TABLE IF NOT EXISTS mod_config (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, key)
);

-- Bans that come back: unbanning one of these by hand is undone at once.
CREATE TABLE IF NOT EXISTS hardbans (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    mod_id     INTEGER NOT NULL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- A nickname staff have pinned on someone. Changing it puts it straight back.
CREATE TABLE IF NOT EXISTS forced_nicks (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    nick     TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- Channels "$lockdown all" leaves alone.
CREATE TABLE IF NOT EXISTS lockdown_ignore (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Which roles count as staff: they see the jail and the log, and are what
-- $staffstrip takes away.
CREATE TABLE IF NOT EXISTS staff_roles (
    guild_id INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

-- What happens automatically when someone reaches so many warnings.
CREATE TABLE IF NOT EXISTS warn_punishments (
    guild_id  INTEGER NOT NULL,
    threshold INTEGER NOT NULL,
    action    TEXT NOT NULL,
    duration  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, threshold)
);

-- A server's own wording for what the bot says, or DMs, after an action.
CREATE TABLE IF NOT EXISTS invoke_messages (
    guild_id INTEGER NOT NULL,
    action   TEXT NOT NULL,
    kind     TEXT NOT NULL,
    content  TEXT NOT NULL,
    PRIMARY KEY (guild_id, action, kind)
);

-- Paper Premium, one row per server (billing.py). Premium means `until`
-- is in the future; everything else is for showing and managing billing.
CREATE TABLE IF NOT EXISTS guild_premium (
    guild_id     INTEGER PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT '',
    until        INTEGER NOT NULL DEFAULT 0,
    customer     TEXT NOT NULL DEFAULT '',
    subscription TEXT NOT NULL DEFAULT '',
    buyer_id     INTEGER NOT NULL DEFAULT 0,
    updated_at   INTEGER NOT NULL DEFAULT 0,
    -- One free trial per server, ever.
    trial_used   INTEGER NOT NULL DEFAULT 0,
    -- premium, plus (with the server builder) or lifetime (plus, for good)
    tier         TEXT NOT NULL DEFAULT 'premium'
);

-- Player Premium: one person's own plan, on every server (billing.py).
-- Like guild_premium, it lasts while `until` is in the future.
CREATE TABLE IF NOT EXISTS player_premium (
    user_id      INTEGER PRIMARY KEY,
    status       TEXT NOT NULL DEFAULT '',
    until        INTEGER NOT NULL DEFAULT 0,
    customer     TEXT NOT NULL DEFAULT '',
    subscription TEXT NOT NULL DEFAULT '',
    updated_at   INTEGER NOT NULL DEFAULT 0
);

-- Premium: events an admin schedules. strength is a percent for xp and
-- karuda (200 = double) and a number of extra rolls for rolls.
CREATE TABLE IF NOT EXISTS server_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    strength   INTEGER NOT NULL,
    starts_at  INTEGER NOT NULL,
    ends_at    INTEGER NOT NULL,
    channel_id INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER NOT NULL DEFAULT 0,
    announced  INTEGER NOT NULL DEFAULT 0   -- 1 once started, 2 once ended
);

-- Premium: each member's week, for weekly champions. week counts Mondays
-- (UTC) since 1970; chat is message XP, voice is seconds in voice.
CREATE TABLE IF NOT EXISTS weekly_activity (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    week     INTEGER NOT NULL,
    chat     INTEGER NOT NULL DEFAULT 0,
    voice    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, week)
);

-- XP earned each calendar month (UTC), month as YYYYMM, for the Premium
-- monthly leaderboard. Kept for every server, so it's already full on the
-- day a server upgrades.
-- ---- Server setup: roles on join, welcome and goodbye, reaction roles,
-- auto replies (cogs/serversetup.py). And AFK and reminders (cogs/utility.py).
CREATE TABLE IF NOT EXISTS autoroles (
    guild_id INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

-- kind is 'welcome' or 'goodbye'. channel 0 is off.
CREATE TABLE IF NOT EXISTS greetings (
    guild_id   INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    channel_id INTEGER NOT NULL DEFAULT 0,
    message    TEXT NOT NULL DEFAULT '',
    embed      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (guild_id, kind)
);

CREATE TABLE IF NOT EXISTS reaction_roles (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    emoji      TEXT NOT NULL,
    role_id    INTEGER NOT NULL,
    PRIMARY KEY (message_id, emoji)
);

CREATE TABLE IF NOT EXISTS autoresponders (
    guild_id INTEGER NOT NULL,
    trigger  TEXT NOT NULL,
    response TEXT NOT NULL,
    PRIMARY KEY (guild_id, trigger)
);

CREATE TABLE IF NOT EXISTS autoreacts (
    guild_id INTEGER NOT NULL,
    trigger  TEXT NOT NULL,
    emoji    TEXT NOT NULL,
    PRIMARY KEY (guild_id, trigger, emoji)
);

CREATE TABLE IF NOT EXISTS afk (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    reason   TEXT NOT NULL DEFAULT '',
    since    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    due        INTEGER NOT NULL,
    text       TEXT NOT NULL,
    made       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders (due);

-- Messages and seconds in voice, per person, per channel, per day (UTC days
-- since 1970), for the $level card's chart and top channels. Kept for
-- ACTIVITY_DAYS; the all-time totals live in levels.messages and vc_time.
CREATE TABLE IF NOT EXISTS activity (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    day        INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    messages   INTEGER NOT NULL DEFAULT 0,
    voice      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, day, channel_id)
);

-- Paper's own profile on a server (Premium, botprofile.py): the bio as set,
-- and the hashes Discord gave the pictures. Empty means Paper's own.
CREATE TABLE IF NOT EXISTS bot_profiles (
    guild_id INTEGER PRIMARY KEY,
    bio      TEXT NOT NULL DEFAULT '',
    avatar   TEXT NOT NULL DEFAULT '',
    banner   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS monthly_xp (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    month    INTEGER NOT NULL,
    xp       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id, month)
);

-- Settings for the Premium extras: champions and the staff report.
CREATE TABLE IF NOT EXISTS premium_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, key)
);

-- Automod (cogs/automod.py): switches and numbers, blocked words, and
-- channels it leaves alone.
CREATE TABLE IF NOT EXISTS automod_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS automod_words (
    guild_id INTEGER NOT NULL,
    word     TEXT NOT NULL,
    PRIMARY KEY (guild_id, word)
);

CREATE TABLE IF NOT EXISTS automod_exempt (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- Premium: rank card backgrounds, stored as the finished card-sized JPEG
-- (rankcard.py). user_id 0 is the server's own, for everyone.
CREATE TABLE IF NOT EXISTS rank_backgrounds (
    guild_id   INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    image      BLOB NOT NULL,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- Premium: roles that earn extra XP, as a percentage (150 = 1.5x).
CREATE TABLE IF NOT EXISTS level_boosts (
    guild_id INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    percent  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

-- Dashboard logins. Only a hash of the session key is kept, so a copy of
-- the database can't be used to log in as anybody. guilds is the JSON list
-- of servers Discord said they could manage when they logged in.
CREATE TABLE IF NOT EXISTS web_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    avatar     TEXT,
    guilds     TEXT NOT NULL DEFAULT '[]',
    expires    INTEGER NOT NULL
);

-- Voice: where Join To Create is, and the channels it has made.
CREATE TABLE IF NOT EXISTS vc_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS temp_vcs (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    owner_id   INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

-- Time spent in voice. A session is open while someone is in a channel and
-- is added to their total when they leave.
CREATE TABLE IF NOT EXISTS vc_time (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    seconds  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS vc_sessions (
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);

-- Roles handed out for reaching so many hours in voice.
CREATE TABLE IF NOT EXISTS vc_hour_roles (
    guild_id INTEGER NOT NULL,
    hours    INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, hours)
);

-- Levels. paid_through is the highest level whose karuda has been paid, and
-- a reset leaves it alone, so grinding the same levels twice pays once.
CREATE TABLE IF NOT EXISTS levels (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    xp           INTEGER NOT NULL DEFAULT 0,
    level        INTEGER NOT NULL DEFAULT 0,
    paid_through INTEGER NOT NULL DEFAULT 0,
    voice_day    INTEGER NOT NULL DEFAULT 0,
    voice_today  INTEGER NOT NULL DEFAULT 0,
    messages     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS level_settings (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, key)
);

-- Level settings that are words rather than numbers: the level-up message.
CREATE TABLE IF NOT EXISTS level_texts (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    PRIMARY KEY (guild_id, key)
);

CREATE TABLE IF NOT EXISTS level_roles (
    guild_id INTEGER NOT NULL,
    level    INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, level)
);

CREATE TABLE IF NOT EXISTS level_ignored (
    guild_id   INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    PRIMARY KEY (guild_id, channel_id)
);

-- The roles a jailed member had, so unjailing hands them back. A row here is
-- also what re-jails someone who leaves and rejoins to escape.
CREATE TABLE IF NOT EXISTS jailed (
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    role_ids  TEXT NOT NULL DEFAULT '',
    jailed_at INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
"""


class DuplicateCharacter(Exception):
    """A write would collide with an existing name + series pair."""


# Built after the migrations rather than alongside the tables: an older
# database reaches __init__ without a like_rank column at all, and indexing a
# column that is about to be added fails the whole script.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_characters_rank
    ON characters (like_rank);
-- Partial, so asking "is there a secret character to roll" on every single
-- roll reads a handful of rows rather than scanning a hundred thousand.
CREATE INDEX IF NOT EXISTS idx_characters_secret
    ON characters (secret_odds) WHERE secret_odds != 0;
CREATE INDEX IF NOT EXISTS idx_characters_series
    ON characters (series);
CREATE INDEX IF NOT EXISTS idx_characters_name
    ON characters (name COLLATE NOCASE);
"""


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        # One connection is shared by the bot and by everything it runs in a
        # thread - seeding art, taking a backup, importing a roster. On the
        # default journal every write locks the whole file, so a command that
        # only wants to read waits behind it, and every command reads before
        # it runs. That is felt as the bot being slow at everything rather
        # than slow at the thing actually working.
        #
        # WAL lets the readers carry on while a write is in progress, and the
        # busy timeout replaces "database is locked" with a short wait.
        # NORMAL fsyncs at checkpoints rather than every commit, which is the
        # usual pairing with WAL and safe against anything but power loss.
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
        except sqlite3.DatabaseError:
            # A filesystem that will not do WAL is still a working database.
            pass
        self.conn.executescript(SCHEMA)
        self._migrate()
        self._convert_old_badges()
        self._refund_old_towers()
        self._instant_snipes()
        self._grandfather_ranges()
        self.conn.executescript(INDEXES)
        self.conn.commit()

    # What the floors of the old, climb-in-order tower cost, for refunding it.
    OLD_TOWER_COSTS = (2500, 4000, 6500, 10000, 16000, 25000, 40000, 65000,
                       100000, 160000)

    def _instant_snipes(self):
        """Sniping became instant (both waits default to 0). A server that
        had saved a wait - the dashboard saves every setting at once - is
        put on the new default, once. Admins can set a wait again after."""
        done = self.conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = 0 AND key = ?",
            ("pref:instant_snipes",)).fetchone()
        if done:
            return
        with self.conn:
            self.conn.execute(
                "DELETE FROM guild_settings WHERE key IN"
                " ('wish_protect_seconds', 'dk_protect_seconds')")
            self.conn.execute(
                "INSERT OR REPLACE INTO guild_settings (guild_id, key, value)"
                " VALUES (0, ?, 1)", ("pref:instant_snipes",))

    def _grandfather_ranges(self):
        """The gacha numbers got a range per plan (premium.SETTING_RANGES).
        A server that had already set one outside the free range keeps it:
        its value is written down once as legacy:<key>, and setting_range
        always allows it. Runs once."""
        done = self.conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = 0 AND key = ?",
            ("pref:grandfather_ranges",)).fetchone()
        if done:
            return
        with self.conn:
            for key, ranges in premium.SETTING_RANGES.items():
                low, high = ranges[0]
                self.conn.execute(
                    "INSERT OR IGNORE INTO guild_settings (guild_id, key, value)"
                    " SELECT guild_id, ?, value FROM guild_settings"
                    " WHERE key = ? AND guild_id != 0 AND (value < ? OR value > ?)",
                    (f"legacy:{key}", key, low, high))
            self.conn.execute(
                "INSERT OR REPLACE INTO guild_settings (guild_id, key, value)"
                " VALUES (0, ?, 1)", ("pref:grandfather_ranges",))

    def _refund_old_towers(self):
        """The tower used to be climbed in a fixed order, a set perk per
        floor. Now every floor is a perk you choose, so an old climb can't be
        carried over: whoever climbed it gets back everything they paid and
        builds again as they like. Runs once: a refunded tower is floor 0,
        and a new one always has its floors written down."""
        rows = self.conn.execute(
            "SELECT p.guild_id, p.user_id, p.tower_floor FROM players p"
            " WHERE p.tower_floor > 0 AND NOT EXISTS (SELECT 1 FROM tower_floors t"
            "  WHERE t.guild_id = p.guild_id AND t.user_id = p.user_id)").fetchall()
        with self.conn:
            for row in rows:
                paid = sum(self.OLD_TOWER_COSTS[:row["tower_floor"]])
                self.conn.execute(
                    "UPDATE players SET karuda = karuda + ?, tower_floor = 0"
                    " WHERE guild_id = ? AND user_id = ?",
                    (paid, row["guild_id"], row["user_id"]))

    def _migrate(self):
        """Add columns that landed after someone already had a database."""
        # Added after the roster grew past AniList. Older databases have the
        # table without it, and CREATE TABLE IF NOT EXISTS will not add it.
        for table, column, spec in (
            ("characters", "source", "TEXT NOT NULL DEFAULT ''"),
            ("characters", "gender", "TEXT NOT NULL DEFAULT ''"),
            # 0 for everybody in the ordinary pool. Above 0, a secret
            # character who rolls one time in this many and never through
            # the pool. Below 0, a secret character who no longer rolls.
            ("characters", "secret_odds", "INTEGER NOT NULL DEFAULT 0"),
            # Badges used to be owned or not; now each is climbed to a level.
            ("badges", "level", "INTEGER NOT NULL DEFAULT 1"),
            ("marriages", "note_image", "TEXT"),
            ("players", "harem_sort", "TEXT NOT NULL DEFAULT ''"),
            ("players", "showcase_id", "INTEGER NOT NULL DEFAULT 0"),
            ("players", "tuto_step", "INTEGER NOT NULL DEFAULT 1"),
            ("players", "tuto_silent", "INTEGER NOT NULL DEFAULT 0"),
            ("guild_premium", "trial_used", "INTEGER NOT NULL DEFAULT 0"),
            ("guild_premium", "tier", "TEXT NOT NULL DEFAULT 'premium'"),
            # Every message someone has sent, for the leaderboard.
            ("levels", "messages", "INTEGER NOT NULL DEFAULT 0"),
            # Mudae's $daily: a free rolls reset every 20 hours, banked when
            # your rolls are already full, and $rt's free claim reset.
            ("players", "roll_resets", "INTEGER NOT NULL DEFAULT 0"),
            ("players", "rolls_daily_at", "INTEGER NOT NULL DEFAULT 0"),
            ("players", "rt_ready_at", "INTEGER NOT NULL DEFAULT 0"),
        ):
            existing = {
                row["name"]
                for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if existing and column not in existing:
                self.conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {spec}"
                )
        # kakera was renamed to karuda. Rename in place so existing servers
        # keep their balances rather than starting over.
        renames = [
            ("players", "kakera", "karuda"),
            ("players", "kakera_ready_at", "karuda_ready_at"),
            ("characters", "base_kakera", "base_karuda"),
        ]
        for table, old, new in renames:
            columns = {
                row["name"]
                for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if old in columns and new not in columns:
                self.conn.execute(
                    f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}"
                )
        self.conn.execute(
            "UPDATE OR IGNORE guild_settings SET key = 'karuda_rate'"
            " WHERE key = 'kakera_rate'"
        )
        self.conn.execute(
            "UPDATE OR IGNORE guild_settings"
            " SET key = 'karuda_interval_minutes'"
            " WHERE key = 'kakera_interval_minutes'"
        )

        existing = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(players)").fetchall()
        }
        for column in (
            "daily_ready_at", "rolls_bought", "extra_wish_slots", "first_seen",
            "premium", "tower_floor", "keys", "soulmate_id", "soulmate_set_at",
        ):
            if column not in existing:
                self.conn.execute(
                    f"ALTER TABLE players ADD COLUMN {column}"
                    " INTEGER NOT NULL DEFAULT 0"
                )

        character_columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(characters)").fetchall()
        }
        for column in ("like_rank", "claim_rank", "guild_id", "favourites"):
            if column not in character_columns:
                self.conn.execute(
                    f"ALTER TABLE characters ADD COLUMN {column}"
                    " INTEGER NOT NULL DEFAULT 0"
                )

        # Albums arrived after characters already had a single image_url.
        # Seed the album from it so nothing loses its art.
        empty = self.conn.execute(
            "SELECT COUNT(*) AS c FROM character_images"
        ).fetchone()["c"]
        if not empty:
            self.conn.execute(
                "INSERT OR IGNORE INTO character_images"
                " (character_id, url, source, added_at)"
                " SELECT id, image_url, 'primary', ? FROM characters"
                " WHERE image_url != ''",
                (int(time.time()),),
            )

    def close(self):
        self.conn.close()

    # ---------- staff points ----------

    def add_staff_point(self, guild_id: int, user_id: int, given_by: int,
                        reason: str) -> int:
        """Give one point. Returns its id, which is what removing it takes."""
        cur = self.conn.execute(
            "INSERT INTO staff_points (guild_id, user_id, given_by, reason,"
            " given_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, given_by, reason, int(time.time())),
        )
        self.conn.commit()
        return cur.lastrowid

    def staff_points_of(self, guild_id: int, user_id: int) -> list:
        """Every point one person has here, newest first."""
        return self.conn.execute(
            "SELECT * FROM staff_points WHERE guild_id = ? AND user_id = ?"
            " ORDER BY given_at DESC, id DESC",
            (guild_id, user_id),
        ).fetchall()

    def remove_staff_point(self, guild_id: int, point_id: int):
        """Take one point back. Returns the row it was, or None."""
        row = self.conn.execute(
            "SELECT * FROM staff_points WHERE guild_id = ? AND id = ?",
            (guild_id, point_id),
        ).fetchone()
        if row:
            self.conn.execute("DELETE FROM staff_points WHERE id = ?", (point_id,))
            self.conn.commit()
        return row

    def clear_staff_points(self, guild_id: int, user_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM staff_points WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount

    def top_staff_points(self, guild_id: int, limit: int = 25) -> list:
        return self.conn.execute(
            "SELECT user_id, COUNT(*) AS points FROM staff_points"
            " WHERE guild_id = ? GROUP BY user_id"
            " ORDER BY points DESC, MIN(given_at) LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    # ---------- moderation ----------

    def add_case(self, guild_id: int, user_id: int, mod_id: int, action: str,
                 reason: str = "", duration: int = 0) -> int:
        cur = self.conn.execute(
            "INSERT INTO mod_cases (guild_id, user_id, mod_id, action, reason,"
            " duration, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, mod_id, action, reason, duration,
             int(time.time())),
        )
        self.conn.commit()
        return cur.lastrowid

    def cases_for(self, guild_id: int, user_id: int, action: str = None) -> list:
        """Every case against one member, newest first."""
        sql = "SELECT * FROM mod_cases WHERE guild_id = ? AND user_id = ?"
        args = [guild_id, user_id]
        if action:
            sql += " AND action = ?"
            args.append(action)
        return self.conn.execute(
            sql + " ORDER BY id DESC", args).fetchall()

    def cases_by(self, guild_id: int, mod_id: int) -> list:
        """Every case one moderator has issued, newest first."""
        return self.conn.execute(
            "SELECT * FROM mod_cases WHERE guild_id = ? AND mod_id = ?"
            " ORDER BY id DESC", (guild_id, mod_id)).fetchall()

    def delete_case(self, guild_id: int, case_id: int, action: str):
        """Remove one case of the given kind. Returns the row, or None."""
        row = self.conn.execute(
            "SELECT * FROM mod_cases WHERE guild_id = ? AND id = ? AND action = ?",
            (guild_id, case_id, action)).fetchone()
        if row:
            self.conn.execute("DELETE FROM mod_cases WHERE id = ?", (case_id,))
            self.conn.commit()
        return row

    def clear_cases(self, guild_id: int, user_id: int, action: str) -> int:
        cur = self.conn.execute(
            "DELETE FROM mod_cases WHERE guild_id = ? AND user_id = ?"
            " AND action = ?", (guild_id, user_id, action))
        self.conn.commit()
        return cur.rowcount

    def get_mod_config(self, guild_id: int, key: str) -> int:
        row = self.conn.execute(
            "SELECT value FROM mod_config WHERE guild_id = ? AND key = ?",
            (guild_id, key)).fetchone()
        return row["value"] if row else 0

    def set_mod_config(self, guild_id: int, key: str, value: int):
        self.conn.execute(
            "INSERT INTO mod_config (guild_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value",
            (guild_id, key, int(value)))
        self.conn.commit()

    def jail_record(self, guild_id: int, user_id: int):
        return self.conn.execute(
            "SELECT * FROM jailed WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)).fetchone()

    def save_jail(self, guild_id: int, user_id: int, role_ids: list):
        self.conn.execute(
            "INSERT OR REPLACE INTO jailed (guild_id, user_id, role_ids,"
            " jailed_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, ",".join(str(r) for r in role_ids),
             int(time.time())))
        self.conn.commit()

    def release_jail(self, guild_id: int, user_id: int) -> list:
        """Forget a jailing. Returns the role ids they had before it."""
        row = self.jail_record(guild_id, user_id)
        if not row:
            return []
        self.conn.execute(
            "DELETE FROM jailed WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id))
        self.conn.commit()
        return [int(r) for r in row["role_ids"].split(",") if r]

    def jailed_in(self, guild_id: int) -> list:
        return self.conn.execute(
            "SELECT * FROM jailed WHERE guild_id = ? ORDER BY jailed_at",
            (guild_id,)).fetchall()

    def clear_mod_config(self, guild_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM mod_config WHERE guild_id = ?", (guild_id,))
        self.conn.commit()
        return cur.rowcount

    # A handful of small keyed tables share these rather than each getting
    # four near-identical methods. Table names are fixed strings from this
    # file, never user input.

    def _upsert(self, table: str, row: dict):
        columns = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self.conn.execute(
            f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({marks})",
            tuple(row.values()))
        self.conn.commit()

    def _delete(self, table: str, **where) -> int:
        clause = " AND ".join(f"{column} = ?" for column in where)
        cur = self.conn.execute(
            f"DELETE FROM {table} WHERE {clause}", tuple(where.values()))
        self.conn.commit()
        return cur.rowcount

    def _select(self, table: str, order: str = "rowid", **where) -> list:
        clause = " AND ".join(f"{column} = ?" for column in where)
        return self.conn.execute(
            f"SELECT * FROM {table} WHERE {clause} ORDER BY {order}",
            tuple(where.values())).fetchall()

    def add_hardban(self, guild_id, user_id, mod_id, reason):
        self._upsert("hardbans", {
            "guild_id": guild_id, "user_id": user_id, "mod_id": mod_id,
            "reason": reason, "created_at": int(time.time())})

    def hardban_of(self, guild_id, user_id):
        rows = self._select("hardbans", guild_id=guild_id, user_id=user_id)
        return rows[0] if rows else None

    def hardbans_in(self, guild_id):
        return self._select("hardbans", "created_at", guild_id=guild_id)

    def remove_hardban(self, guild_id, user_id) -> int:
        return self._delete("hardbans", guild_id=guild_id, user_id=user_id)

    def force_nick(self, guild_id, user_id, nick):
        self._upsert("forced_nicks",
                     {"guild_id": guild_id, "user_id": user_id, "nick": nick})

    def forced_nick_of(self, guild_id, user_id):
        rows = self._select("forced_nicks", guild_id=guild_id, user_id=user_id)
        return rows[0]["nick"] if rows else None

    def unforce_nick(self, guild_id, user_id) -> int:
        return self._delete("forced_nicks", guild_id=guild_id, user_id=user_id)

    def ignore_lockdown(self, guild_id, channel_id):
        self._upsert("lockdown_ignore",
                     {"guild_id": guild_id, "channel_id": channel_id})

    def unignore_lockdown(self, guild_id, channel_id) -> int:
        return self._delete("lockdown_ignore", guild_id=guild_id,
                            channel_id=channel_id)

    def lockdown_ignored(self, guild_id) -> list:
        return [row["channel_id"] for row in
                self._select("lockdown_ignore", guild_id=guild_id)]

    def add_staff_role(self, guild_id, role_id):
        self._upsert("staff_roles", {"guild_id": guild_id, "role_id": role_id})

    def remove_staff_role(self, guild_id, role_id) -> int:
        return self._delete("staff_roles", guild_id=guild_id, role_id=role_id)

    def staff_roles_of(self, guild_id) -> list:
        return [row["role_id"] for row in
                self._select("staff_roles", guild_id=guild_id)]

    def set_warn_punishment(self, guild_id, threshold, action, duration=0):
        self._upsert("warn_punishments", {
            "guild_id": guild_id, "threshold": threshold, "action": action,
            "duration": duration})

    def remove_warn_punishment(self, guild_id, threshold) -> int:
        return self._delete("warn_punishments", guild_id=guild_id,
                            threshold=threshold)

    def warn_punishments_of(self, guild_id) -> list:
        return self._select("warn_punishments", "threshold", guild_id=guild_id)

    def set_invoke(self, guild_id, action, kind, content):
        self._upsert("invoke_messages", {
            "guild_id": guild_id, "action": action, "kind": kind,
            "content": content})

    def invoke_of(self, guild_id, action, kind):
        rows = self._select("invoke_messages", guild_id=guild_id,
                            action=action, kind=kind)
        return rows[0]["content"] if rows else None

    def invokes_in(self, guild_id) -> list:
        return self._select("invoke_messages", "action, kind",
                            guild_id=guild_id)

    def reset_invoke(self, guild_id, action, kind=None) -> int:
        if kind:
            return self._delete("invoke_messages", guild_id=guild_id,
                                action=action, kind=kind)
        return self._delete("invoke_messages", guild_id=guild_id, action=action)

    # ---------- premium ----------

    def set_premium(self, guild_id: int, status: str, until: int, customer: str,
                    subscription: str, buyer_id: int = 0, tier: str = None):
        row = self.premium_of(guild_id)
        trial = status == "trialing" or bool(row and row["trial_used"])
        self._upsert("guild_premium", {
            "trial_used": 1 if trial else 0,
            "tier": tier or (row["tier"] if row else "premium"),
            "guild_id": guild_id, "status": status, "until": int(until),
            # A later event may not carry these; don't forget them.
            "customer": customer or (row["customer"] if row else ""),
            "subscription": subscription or (row["subscription"] if row else ""),
            "buyer_id": buyer_id or (row["buyer_id"] if row else 0),
            "updated_at": int(time.time())})

    def premium_of(self, guild_id: int):
        rows = self._select("guild_premium", guild_id=guild_id)
        return rows[0] if rows else None

    def trial_available(self, guild_id: int) -> bool:
        """A server that has never subscribed or trialled gets one free week."""
        row = self.premium_of(guild_id)
        return not row or (not row["subscription"] and not row["trial_used"])

    def is_premium(self, guild_id: int) -> bool:
        row = self.premium_of(guild_id)
        return bool(row and row["until"] > time.time())

    def premium_tier(self, guild_id: int):
        """'premium', 'plus' or 'lifetime' while it lasts, else None."""
        row = self.premium_of(guild_id)
        if not row or row["until"] <= time.time():
            return None
        return "lifetime" if row["status"] == "lifetime" else (row["tier"] or "premium")

    def is_plus(self, guild_id: int) -> bool:
        """Premium Plus or Lifetime: the server builder."""
        return self.premium_tier(guild_id) in ("plus", "lifetime")

    def plan_rank(self, guild_id: int) -> int:
        """0 free, 1 Premium, 2 Plus or Lifetime (premium.RANK)."""
        return premium.RANK.get(self.premium_tier(guild_id) or "free", 0)

    def has_feature(self, guild_id: int, feature: str) -> bool:
        """Does this server's plan include a feature in premium.FEATURES?"""
        return self.plan_rank(guild_id) >= premium.RANK[premium.FEATURES[feature]]

    def set_player_premium(self, user_id: int, status: str, until: int,
                           customer: str = "", subscription: str = ""):
        row = self.player_premium_of(user_id)
        self._upsert("player_premium", {
            "user_id": user_id, "status": status, "until": int(until),
            # A later event may not carry these; don't forget them.
            "customer": customer or (row["customer"] if row else ""),
            "subscription": subscription or (row["subscription"] if row else ""),
            "updated_at": int(time.time())})

    def player_premium_of(self, user_id: int):
        rows = self._select("player_premium", user_id=user_id)
        return rows[0] if rows else None

    def is_player_premium(self, user_id: int) -> bool:
        row = self.player_premium_of(user_id)
        return bool(row and row["until"] > time.time())

    def add_event(self, guild_id: int, kind: str, strength: int, starts_at: int,
                  ends_at: int, channel_id: int, created_by: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO server_events (guild_id, kind, strength, starts_at, ends_at,"
            " channel_id, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, kind, strength, starts_at, ends_at, channel_id, created_by))
        self.conn.commit()
        return cur.lastrowid

    def events_of(self, guild_id: int, include_past: bool = False) -> list:
        sql = "SELECT * FROM server_events WHERE guild_id = ?"
        args = [guild_id]
        if not include_past:
            sql += " AND ends_at > ?"
            args.append(int(time.time()))
        return self.conn.execute(sql + " ORDER BY starts_at", args).fetchall()

    def event(self, guild_id: int, event_id: int):
        rows = self._select("server_events", guild_id=guild_id, id=event_id)
        return rows[0] if rows else None

    def end_event(self, guild_id: int, event_id: int) -> bool:
        """Stop one now: a running one ends, a future one never starts."""
        now = int(time.time())
        cur = self.conn.execute(
            "UPDATE server_events SET ends_at = ?,"
            " starts_at = MIN(starts_at, ?) WHERE guild_id = ? AND id = ? AND ends_at > ?",
            (now, now, guild_id, event_id, now))
        self.conn.commit()
        return cur.rowcount > 0

    def event_strength(self, guild_id: int, kind: str):
        """The strongest event of this kind running now, or None. Only while
        the server has Premium Plus."""
        now = int(time.time())
        row = self.conn.execute(
            "SELECT MAX(strength) AS s FROM server_events WHERE guild_id = ?"
            " AND kind = ? AND starts_at <= ? AND ends_at > ?",
            (guild_id, kind, now, now)).fetchone()
        if not row or row["s"] is None or not self.has_feature(guild_id, "events"):
            return None
        return row["s"]

    def events_to_announce(self) -> list:
        now = int(time.time())
        return self.conn.execute(
            "SELECT * FROM server_events WHERE (announced = 0 AND starts_at <= ?)"
            " OR (announced < 2 AND ends_at <= ?) ORDER BY starts_at", (now, now)).fetchall()

    def mark_event(self, event_id: int, announced: int):
        self.conn.execute("UPDATE server_events SET announced = ? WHERE id = ?",
                          (announced, event_id))
        self.conn.commit()

    def add_weekly(self, guild_id: int, user_id: int, week: int,
                   chat: int = 0, voice: int = 0):
        self.conn.execute(
            "INSERT INTO weekly_activity (guild_id, user_id, week, chat, voice)"
            " VALUES (?, ?, ?, ?, ?) ON CONFLICT (guild_id, user_id, week)"
            " DO UPDATE SET chat = chat + excluded.chat, voice = voice + excluded.voice",
            (guild_id, user_id, week, chat, voice))
        self.conn.commit()

    def weekly_top(self, guild_id: int, week: int, column: str, limit: int = 3) -> list:
        assert column in ("chat", "voice")
        return self.conn.execute(
            f"SELECT user_id, {column} AS amount FROM weekly_activity"
            f" WHERE guild_id = ? AND week = ? AND {column} > 0"
            f" ORDER BY {column} DESC LIMIT ?", (guild_id, week, limit)).fetchall()

    def prune_weekly(self, before_week: int):
        self.conn.execute("DELETE FROM weekly_activity WHERE week < ?", (before_week,))
        self.conn.commit()

    def bot_profile(self, guild_id: int):
        rows = self._select("bot_profiles", guild_id=guild_id)
        return rows[0] if rows else None

    def save_bot_profile(self, guild_id: int, bio: str, avatar: str, banner: str):
        if bio or avatar or banner:
            self._upsert("bot_profiles", {"guild_id": guild_id, "bio": bio,
                                          "avatar": avatar, "banner": banner})
        else:
            self._delete("bot_profiles", guild_id=guild_id)

    def custom_bot_profiles(self) -> list:
        return self.conn.execute("SELECT * FROM bot_profiles").fetchall()

    def add_monthly_xp(self, guild_id: int, user_id: int, month: int, xp: int):
        self.conn.execute(
            "INSERT INTO monthly_xp (guild_id, user_id, month, xp)"
            " VALUES (?, ?, ?, ?) ON CONFLICT (guild_id, user_id, month)"
            " DO UPDATE SET xp = xp + excluded.xp",
            (guild_id, user_id, month, xp))
        self.conn.commit()

    def monthly_top(self, guild_id: int, month: int, limit: int = 100) -> list:
        return self.conn.execute(
            "SELECT user_id, xp FROM monthly_xp WHERE guild_id = ? AND month = ?"
            " AND xp > 0 ORDER BY xp DESC LIMIT ?", (guild_id, month, limit)).fetchall()

    def prune_monthly(self, before_month: int):
        self.conn.execute("DELETE FROM monthly_xp WHERE month < ?", (before_month,))
        self.conn.commit()

    def get_premium_setting(self, guild_id: int, key: str, default: int = 0) -> int:
        rows = self._select("premium_settings", guild_id=guild_id, key=key)
        return rows[0]["value"] if rows else default

    def set_premium_setting(self, guild_id: int, key: str, value: int):
        self._upsert("premium_settings",
                     {"guild_id": guild_id, "key": key, "value": int(value)})

    def cases_between(self, guild_id: int, start: int, end: int) -> list:
        return self.conn.execute(
            "SELECT * FROM mod_cases WHERE guild_id = ? AND created_at >= ?"
            " AND created_at < ?", (guild_id, start, end)).fetchall()

    def points_between(self, guild_id: int, start: int, end: int) -> list:
        return self.conn.execute(
            "SELECT user_id, COUNT(*) AS points FROM staff_points WHERE guild_id = ?"
            " AND given_at >= ? AND given_at < ? GROUP BY user_id",
            (guild_id, start, end)).fetchall()

    def automod_all(self, guild_id: int) -> dict:
        return {r["key"]: r["value"] for r in self._select("automod_settings",
                                                            guild_id=guild_id)}

    def set_automod(self, guild_id: int, key: str, value):
        self._upsert("automod_settings",
                     {"guild_id": guild_id, "key": key, "value": str(value)})

    def automod_words(self, guild_id: int) -> list:
        return [r["word"] for r in self._select("automod_words", "word", guild_id=guild_id)]

    def replace_automod_words(self, guild_id: int, words):
        with self.conn:
            self.conn.execute("DELETE FROM automod_words WHERE guild_id = ?", (guild_id,))
            self.conn.executemany("INSERT OR IGNORE INTO automod_words (guild_id, word)"
                                  " VALUES (?, ?)", [(guild_id, w) for w in words])

    def automod_exempt(self, guild_id: int) -> list:
        return [r["channel_id"] for r in self._select("automod_exempt", guild_id=guild_id)]

    def replace_automod_exempt(self, guild_id: int, channel_ids):
        with self.conn:
            self.conn.execute("DELETE FROM automod_exempt WHERE guild_id = ?", (guild_id,))
            self.conn.executemany("INSERT OR IGNORE INTO automod_exempt (guild_id, channel_id)"
                                  " VALUES (?, ?)", [(guild_id, c) for c in channel_ids])

    def set_rank_background(self, guild_id: int, user_id: int, image):
        """user_id 0 is the server's. None removes it."""
        if image is None:
            self._delete("rank_backgrounds", guild_id=guild_id, user_id=user_id)
        else:
            self._upsert("rank_backgrounds", {
                "guild_id": guild_id, "user_id": user_id, "image": image,
                "updated_at": int(time.time())})

    def rank_background(self, guild_id: int, user_id: int):
        rows = self._select("rank_backgrounds", guild_id=guild_id, user_id=user_id)
        return rows[0]["image"] if rows else None

    def set_level_boost(self, guild_id: int, role_id: int, percent: int):
        self._upsert("level_boosts",
                     {"guild_id": guild_id, "role_id": role_id, "percent": percent})

    def remove_level_boost(self, guild_id: int, role_id: int) -> int:
        return self._delete("level_boosts", guild_id=guild_id, role_id=role_id)

    def level_boosts_of(self, guild_id: int) -> list:
        return self._select("level_boosts", "percent DESC", guild_id=guild_id)

    def replace_level_boosts(self, guild_id: int, pairs):
        with self.conn:
            self.conn.execute("DELETE FROM level_boosts WHERE guild_id = ?",
                              (guild_id,))
            self.conn.executemany(
                "INSERT INTO level_boosts (guild_id, role_id, percent)"
                " VALUES (?, ?, ?)", [(guild_id, r, p) for r, p in pairs])

    # ---------- dashboard logins ----------

    def add_web_session(self, token_hash: str, user_id: int, name: str,
                        avatar, guilds_json: str, expires: int):
        with self.conn:
            self.conn.execute("DELETE FROM web_sessions WHERE expires < ?",
                              (int(time.time()),))
            self.conn.execute(
                "INSERT OR REPLACE INTO web_sessions (token_hash, user_id, name,"
                " avatar, guilds, expires) VALUES (?, ?, ?, ?, ?, ?)",
                (token_hash, user_id, name, avatar, guilds_json, expires))

    def web_session(self, token_hash: str):
        row = self.conn.execute(
            "SELECT * FROM web_sessions WHERE token_hash = ? AND expires > ?",
            (token_hash, int(time.time()))).fetchone()
        return row

    def end_web_session(self, token_hash: str) -> int:
        return self._delete("web_sessions", token_hash=token_hash)

    # ---------- voice ----------

    def get_vc_setting(self, guild_id: int, key: str) -> int:
        rows = self._select("vc_settings", guild_id=guild_id, key=key)
        return rows[0]["value"] if rows else 0

    def set_vc_setting(self, guild_id: int, key: str, value: int):
        self._upsert("vc_settings",
                     {"guild_id": guild_id, "key": key, "value": int(value)})

    def clear_vc_settings(self, guild_id: int) -> int:
        return self._delete("vc_settings", guild_id=guild_id)

    def add_temp_vc(self, guild_id: int, channel_id: int, owner_id: int):
        self._upsert("temp_vcs", {
            "channel_id": channel_id, "guild_id": guild_id,
            "owner_id": owner_id, "created_at": int(time.time())})

    def temp_vc(self, channel_id: int):
        rows = self._select("temp_vcs", channel_id=channel_id)
        return rows[0] if rows else None

    def temp_vc_of(self, guild_id: int, owner_id: int):
        rows = self._select("temp_vcs", guild_id=guild_id, owner_id=owner_id)
        return rows[0] if rows else None

    def temp_vcs_in(self, guild_id: int) -> list:
        return self._select("temp_vcs", guild_id=guild_id)

    def set_temp_vc_owner(self, channel_id: int, owner_id: int):
        self.conn.execute("UPDATE temp_vcs SET owner_id = ? WHERE channel_id = ?",
                          (owner_id, channel_id))
        self.conn.commit()

    def remove_temp_vc(self, channel_id: int) -> int:
        return self._delete("temp_vcs", channel_id=channel_id)

    def start_vc_session(self, guild_id: int, user_id: int, at: int = None):
        """Start counting, unless a session is already open."""
        self.conn.execute(
            "INSERT OR IGNORE INTO vc_sessions (guild_id, user_id, joined_at)"
            " VALUES (?, ?, ?)", (guild_id, user_id, int(time.time()) if at is None else at))
        self.conn.commit()

    def end_vc_session(self, guild_id: int, user_id: int, at: int = None) -> int:
        """Stop counting and bank the time. Returns the seconds added."""
        rows = self._select("vc_sessions", guild_id=guild_id, user_id=user_id)
        if not rows:
            return 0
        spent = max(0, (int(time.time()) if at is None else at)
                    - rows[0]["joined_at"])
        with self.conn:
            self.conn.execute(
                "DELETE FROM vc_sessions WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id))
            self.conn.execute(
                "INSERT INTO vc_time (guild_id, user_id, seconds) VALUES (?, ?, ?)"
                " ON CONFLICT (guild_id, user_id)"
                " DO UPDATE SET seconds = seconds + excluded.seconds",
                (guild_id, user_id, spent))
        return spent

    def drop_vc_session(self, guild_id: int, user_id: int) -> int:
        """Forget an open session without banking it."""
        return self._delete("vc_sessions", guild_id=guild_id, user_id=user_id)

    def vc_sessions_in(self, guild_id: int) -> list:
        return self._select("vc_sessions", guild_id=guild_id)

    def vc_seconds(self, guild_id: int, user_id: int, now: int = None) -> int:
        """Banked time plus the session they're in right now."""
        now = int(time.time()) if now is None else now
        row = self.conn.execute(
            "SELECT COALESCE((SELECT seconds FROM vc_time"
            "  WHERE guild_id = ? AND user_id = ?), 0)"
            " + COALESCE((SELECT ? - joined_at FROM vc_sessions"
            "  WHERE guild_id = ? AND user_id = ?), 0) AS total",
            (guild_id, user_id, now, guild_id, user_id)).fetchone()
        return max(0, row["total"])

    def top_vc(self, guild_id: int, limit: int = 10, now: int = None) -> list:
        now = int(time.time()) if now is None else now
        return self.conn.execute(
            "SELECT user_id, SUM(seconds) AS seconds FROM ("
            "  SELECT user_id, seconds FROM vc_time WHERE guild_id = ?"
            "  UNION ALL"
            "  SELECT user_id, ? - joined_at FROM vc_sessions WHERE guild_id = ?"
            ") GROUP BY user_id HAVING SUM(seconds) > 0"
            " ORDER BY seconds DESC LIMIT ?",
            (guild_id, now, guild_id, limit)).fetchall()

    def set_hour_role(self, guild_id: int, hours: int, role_id: int):
        self._upsert("vc_hour_roles",
                     {"guild_id": guild_id, "hours": hours, "role_id": role_id})

    def remove_hour_role(self, guild_id: int, hours: int) -> int:
        return self._delete("vc_hour_roles", guild_id=guild_id, hours=hours)

    def hour_roles_of(self, guild_id: int) -> list:
        return self._select("vc_hour_roles", "hours", guild_id=guild_id)

    # ---------- levels ----------

    def level_row(self, guild_id: int, user_id: int):
        """One member's levels row, made on first sight."""
        self.conn.execute(
            "INSERT OR IGNORE INTO levels (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id))
        self.conn.commit()
        return self._select("levels", guild_id=guild_id, user_id=user_id)[0]

    def update_level_row(self, guild_id: int, user_id: int, **fields):
        self.level_row(guild_id, user_id)
        sets = ", ".join(f"{column} = ?" for column in fields)
        self.conn.execute(
            f"UPDATE levels SET {sets} WHERE guild_id = ? AND user_id = ?",
            (*fields.values(), guild_id, user_id))
        self.conn.commit()

    def add_messages(self, counts: dict):
        """{(guild_id, user_id): messages} added in one go. The bot counts in
        memory and saves once a minute rather than writing every message."""
        if not counts:
            return
        with self.conn:
            self.conn.executemany(
                "INSERT INTO levels (guild_id, user_id, messages) VALUES (?, ?, ?)"
                " ON CONFLICT (guild_id, user_id)"
                " DO UPDATE SET messages = messages + excluded.messages",
                [(g, u, n) for (g, u), n in counts.items()])

    def add_activity(self, counts: dict):
        """{(guild, user, day, channel): [messages, voice seconds]} added in
        one go, like add_messages."""
        if not counts:
            return
        with self.conn:
            self.conn.executemany(
                "INSERT INTO activity (guild_id, user_id, day, channel_id, messages, voice)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (guild_id, user_id, day, channel_id) DO UPDATE SET"
                " messages = messages + excluded.messages, voice = voice + excluded.voice",
                [(*key, m, v) for key, (m, v) in counts.items()])

    def activity_by_day(self, guild_id: int, user_id: int, since_day: int) -> dict:
        """{day: (messages, voice seconds)} from since_day on."""
        rows = self.conn.execute(
            "SELECT day, SUM(messages) AS m, SUM(voice) AS v FROM activity"
            " WHERE guild_id = ? AND user_id = ? AND day >= ? GROUP BY day",
            (guild_id, user_id, since_day)).fetchall()
        return {r["day"]: (r["m"], r["v"]) for r in rows}

    def top_channels(self, guild_id: int, user_id: int, since_day: int,
                     column: str, limit: int = 3) -> list:
        """[(channel id, amount)] where someone chatted (column 'messages')
        or talked ('voice') the most since since_day."""
        assert column in ("messages", "voice")
        return [(r["channel_id"], r["amount"]) for r in self.conn.execute(
            f"SELECT channel_id, SUM({column}) AS amount FROM activity"
            f" WHERE guild_id = ? AND user_id = ? AND day >= ?"
            f" GROUP BY channel_id HAVING amount > 0 ORDER BY amount DESC LIMIT ?",
            (guild_id, user_id, since_day, limit)).fetchall()]

    # ---------- server setup ----------

    def autoroles_of(self, guild_id: int) -> list:
        return [r["role_id"] for r in self._select("autoroles", guild_id=guild_id)]

    def replace_autoroles(self, guild_id: int, role_ids):
        with self.conn:
            self.conn.execute("DELETE FROM autoroles WHERE guild_id = ?", (guild_id,))
            self.conn.executemany("INSERT INTO autoroles (guild_id, role_id) VALUES (?, ?)",
                                  [(guild_id, r) for r in dict.fromkeys(role_ids)])

    def greeting(self, guild_id: int, kind: str) -> dict:
        rows = self._select("greetings", guild_id=guild_id, kind=kind)
        if rows:
            return dict(rows[0])
        return {"guild_id": guild_id, "kind": kind, "channel_id": 0, "message": "", "embed": 1}

    def set_greeting(self, guild_id: int, kind: str, **fields):
        row = self.greeting(guild_id, kind)
        row.update(fields)
        self._upsert("greetings", row)

    def reaction_roles_of(self, guild_id: int) -> list:
        return self._select("reaction_roles", "message_id", guild_id=guild_id)

    def reaction_role(self, message_id: int, emoji: str):
        rows = self._select("reaction_roles", message_id=message_id, emoji=emoji)
        return rows[0] if rows else None

    def add_reaction_role(self, guild_id, channel_id, message_id, emoji, role_id):
        self._upsert("reaction_roles", {"guild_id": guild_id, "channel_id": channel_id,
                                        "message_id": message_id, "emoji": emoji,
                                        "role_id": role_id})

    def remove_reaction_role(self, guild_id: int, message_id: int, emoji: str = None) -> int:
        if emoji is None:
            return self._delete("reaction_roles", guild_id=guild_id, message_id=message_id)
        return self._delete("reaction_roles", guild_id=guild_id, message_id=message_id,
                            emoji=emoji)

    def autoresponders_of(self, guild_id: int) -> list:
        return self._select("autoresponders", "trigger", guild_id=guild_id)

    def set_autoresponder(self, guild_id: int, trigger: str, response: str):
        self._upsert("autoresponders", {"guild_id": guild_id, "trigger": trigger,
                                        "response": response})

    def remove_autoresponder(self, guild_id: int, trigger: str) -> int:
        return self._delete("autoresponders", guild_id=guild_id, trigger=trigger)

    def autoreacts_of(self, guild_id: int) -> list:
        return self._select("autoreacts", "trigger", guild_id=guild_id)

    def add_autoreact(self, guild_id: int, trigger: str, emoji: str):
        self._upsert("autoreacts", {"guild_id": guild_id, "trigger": trigger, "emoji": emoji})

    def remove_autoreact(self, guild_id: int, trigger: str) -> int:
        return self._delete("autoreacts", guild_id=guild_id, trigger=trigger)

    # ---------- afk and reminders ----------

    def all_afk(self) -> list:
        return self.conn.execute("SELECT * FROM afk").fetchall()

    def set_afk(self, guild_id: int, user_id: int, reason: str, since: int):
        self._upsert("afk", {"guild_id": guild_id, "user_id": user_id, "reason": reason,
                             "since": since})

    def clear_afk(self, guild_id: int, user_id: int) -> int:
        return self._delete("afk", guild_id=guild_id, user_id=user_id)

    def add_reminder(self, guild_id, channel_id, user_id, due, text) -> int:
        cur = self.conn.execute(
            "INSERT INTO reminders (guild_id, channel_id, user_id, due, text, made)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, user_id, due, text, int(time.time())))
        self.conn.commit()
        return cur.lastrowid

    def reminders_of(self, user_id: int) -> list:
        return self._select("reminders", "due", user_id=user_id)

    def due_reminders(self, now: int) -> list:
        return self.conn.execute("SELECT * FROM reminders WHERE due <= ? ORDER BY due",
                                 (now,)).fetchall()

    def remove_reminder(self, reminder_id: int, user_id: int = None) -> int:
        if user_id is None:
            return self._delete("reminders", id=reminder_id)
        return self._delete("reminders", id=reminder_id, user_id=user_id)

    def messages_of(self, guild_id: int) -> dict:
        """{user id: message count} for everyone on the server."""
        return {r["user_id"]: r["messages"] for r in self.conn.execute(
            "SELECT user_id, messages FROM levels WHERE guild_id = ? AND messages > 0",
            (guild_id,)).fetchall()}

    def activity_messages(self, guild_id: int, since_day: int) -> dict:
        """{(user, day, channel): messages} from since_day on."""
        return {(r["user_id"], r["day"], r["channel_id"]): r["messages"]
                for r in self.conn.execute(
                    "SELECT user_id, day, channel_id, messages FROM activity"
                    " WHERE guild_id = ? AND day >= ? AND messages > 0",
                    (guild_id, since_day)).fetchall()}

    def apply_recount(self, guild_id: int, history: dict, before: dict,
                      act_history: dict, act_before: dict):
        """Swap in message counts read from the server's history.

        history is what the channels hold up to the moment the count
        started; before is what the bot had counted at that moment. Each
        total moves by the difference, so whatever was counted live while
        the history was being read is kept rather than lost or doubled."""
        with self.conn:
            for uid in set(history) | set(before):
                delta = history.get(uid, 0) - before.get(uid, 0)
                if delta:
                    self.conn.execute(
                        "INSERT INTO levels (guild_id, user_id, messages) VALUES (?, ?, ?)"
                        " ON CONFLICT (guild_id, user_id)"
                        " DO UPDATE SET messages = MAX(0, messages + ?)",
                        (guild_id, uid, max(0, delta), delta))
            for key in set(act_history) | set(act_before):
                delta = act_history.get(key, 0) - act_before.get(key, 0)
                if delta:
                    self.conn.execute(
                        "INSERT INTO activity (guild_id, user_id, day, channel_id, messages)"
                        " VALUES (?, ?, ?, ?, ?) ON CONFLICT (guild_id, user_id, day, channel_id)"
                        " DO UPDATE SET messages = MAX(0, messages + ?)",
                        (guild_id, *key, max(0, delta), delta))

    def prune_activity(self, before_day: int):
        self.conn.execute("DELETE FROM activity WHERE day < ?", (before_day,))
        self.conn.commit()

    def message_rank(self, guild_id: int, user_id: int) -> int:
        """1 for the most messages on the server. 0 for none at all."""
        mine = self.conn.execute(
            "SELECT messages FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)).fetchone()
        if not mine or mine["messages"] <= 0:
            return 0
        return 1 + self.conn.execute(
            "SELECT COUNT(*) FROM levels WHERE guild_id = ? AND messages > ?",
            (guild_id, mine["messages"])).fetchone()[0]

    def voice_rank(self, guild_id: int, user_id: int, now: int = None) -> int:
        """1 for the most time in voice on the server. 0 for none."""
        now = int(time.time()) if now is None else now
        mine = self.vc_seconds(guild_id, user_id, now)
        if mine <= 0:
            return 0
        return 1 + self.conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT user_id, SUM(seconds) AS seconds FROM ("
            "    SELECT user_id, seconds FROM vc_time WHERE guild_id = ?"
            "    UNION ALL"
            "    SELECT user_id, ? - joined_at FROM vc_sessions WHERE guild_id = ?"
            "  ) GROUP BY user_id) WHERE seconds > ?",
            (guild_id, now, guild_id, mine)).fetchone()[0]

    def top_levels(self, guild_id: int, limit: int = 100) -> list:
        return self.conn.execute(
            "SELECT * FROM levels WHERE guild_id = ? AND xp > 0"
            " ORDER BY xp DESC LIMIT ?", (guild_id, limit)).fetchall()

    def level_rank(self, guild_id: int, user_id: int) -> int:
        """1 for the most XP on the server. 0 for no XP at all."""
        row = self.conn.execute(
            "SELECT xp FROM levels WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)).fetchone()
        if not row or row["xp"] <= 0:
            return 0
        return self.conn.execute(
            "SELECT COUNT(*) + 1 AS r FROM levels WHERE guild_id = ? AND xp > ?",
            (guild_id, row["xp"])).fetchone()["r"]

    def get_level_setting(self, guild_id: int, key: str, default: int) -> int:
        rows = self._select("level_settings", guild_id=guild_id, key=key)
        return rows[0]["value"] if rows else default

    def set_level_setting(self, guild_id: int, key: str, value: int):
        self._upsert("level_settings",
                     {"guild_id": guild_id, "key": key, "value": int(value)})

    def get_level_text(self, guild_id: int, key: str, default: str) -> str:
        rows = self._select("level_texts", guild_id=guild_id, key=key)
        return rows[0]["value"] if rows else default

    def set_level_text(self, guild_id: int, key: str, value):
        """Save a text setting. None goes back to the default."""
        if value is None:
            self._delete("level_texts", guild_id=guild_id, key=key)
        else:
            self._upsert("level_texts",
                         {"guild_id": guild_id, "key": key, "value": value})

    def replace_level_roles(self, guild_id: int, pairs):
        """Swap the whole level-role list at once, as the dashboard saves it."""
        with self.conn:
            self.conn.execute("DELETE FROM level_roles WHERE guild_id = ?",
                              (guild_id,))
            self.conn.executemany(
                "INSERT INTO level_roles (guild_id, level, role_id)"
                " VALUES (?, ?, ?)",
                [(guild_id, level, role_id) for level, role_id in pairs])

    def replace_level_ignored(self, guild_id: int, channel_ids):
        with self.conn:
            self.conn.execute("DELETE FROM level_ignored WHERE guild_id = ?",
                              (guild_id,))
            self.conn.executemany(
                "INSERT INTO level_ignored (guild_id, channel_id) VALUES (?, ?)",
                [(guild_id, channel_id) for channel_id in channel_ids])

    def set_level_role(self, guild_id: int, level: int, role_id: int):
        self._upsert("level_roles",
                     {"guild_id": guild_id, "level": level, "role_id": role_id})

    def remove_level_role(self, guild_id: int, level: int) -> int:
        return self._delete("level_roles", guild_id=guild_id, level=level)

    def level_roles_of(self, guild_id: int) -> list:
        return self._select("level_roles", "level", guild_id=guild_id)

    def ignore_level_channel(self, guild_id: int, channel_id: int):
        self._upsert("level_ignored",
                     {"guild_id": guild_id, "channel_id": channel_id})

    def unignore_level_channel(self, guild_id: int, channel_id: int) -> int:
        return self._delete("level_ignored", guild_id=guild_id,
                            channel_id=channel_id)

    def level_ignored_in(self, guild_id: int) -> list:
        return [row["channel_id"] for row in
                self._select("level_ignored", guild_id=guild_id)]

    # ---------- characters ----------

    def add_character(
        self, name: str, series: str, image_url: str, likes: int, base_karuda: int
    ) -> Optional[int]:
        """Insert a character. Returns its id, or None if it already exists."""
        try:
            cur = self.conn.execute(
                "INSERT INTO characters (name, series, image_url, likes, base_karuda)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, series, image_url, likes, base_karuda),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def upsert_character(
        self, name: str, series: str, image_url: str, likes: int, base_karuda: int
    ) -> int:
        """Insert or update by (name, series). Used by the seed importer."""
        self.conn.execute(
            "INSERT INTO characters (name, series, image_url, likes, base_karuda)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (name, series) DO UPDATE SET"
            "   image_url = excluded.image_url,"
            "   likes = excluded.likes,"
            "   base_karuda = excluded.base_karuda",
            (name, series, image_url, likes, base_karuda),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM characters WHERE name = ? AND series = ?", (name, series)
        ).fetchone()
        # Any path that sets a primary image should put it in the album too,
        # otherwise rolls have nothing to pick from.
        if image_url:
            self.add_image(row["id"], image_url, source="import")
        return row["id"]

    def import_characters(self, entries) -> dict:
        """Bulk import in a single transaction.

        The per-character helpers each commit, which meant a 1000-character
        import did several thousand commits and took minutes. This does one.

        `entries` are dicts with name and series, optionally image_url, likes,
        base_karuda, like_rank, claim_rank and an images list. Returns counts.
        """
        timestamp = int(time.time())
        inserted = updated = images_added = 0

        with self.conn:  # one transaction; rolls back entirely on error
            # One lookup for the whole run rather than a SELECT per row.
            existing = {
                (row["name"], row["series"]): row["id"]
                for row in self.conn.execute("SELECT id, name, series FROM characters")
            }

            album_rows = []
            for entry in entries:
                key = (entry["name"], entry["series"])
                values = (
                    entry.get("image_url", ""),
                    int(entry.get("likes", 0)),
                    int(entry.get("base_karuda", entry.get("base_kakera", 50))),
                    int(entry.get("like_rank", 0)),
                    int(entry.get("claim_rank", 0)),
                    int(entry.get("favourites", 0)),
                    str(entry.get("source", "") or ""),
                    str(entry.get("gender", "") or ""),
                )
                character_id = existing.get(key)
                if character_id is None:
                    cur = self.conn.execute(
                        "INSERT INTO characters"
                        " (name, series, image_url, likes, base_karuda,"
                        "  like_rank, claim_rank, favourites, source, gender)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (entry["name"], entry["series"], *values),
                    )
                    character_id = cur.lastrowid
                    existing[key] = character_id
                    inserted += 1
                else:
                    self.conn.execute(
                        "UPDATE characters SET image_url = ?, likes = ?,"
                        " base_karuda = ?, like_rank = ?, claim_rank = ?,"
                        " favourites = ?, source = ?, gender = ?"
                        " WHERE id = ?",
                        (*values, character_id),
                    )
                    updated += 1

                album = [entry["image_url"]] if entry.get("image_url") else []
                album += list(entry.get("images") or [])
                for url in album:
                    album_rows.append((character_id, url, "import", timestamp))

            if album_rows:
                before = self.conn.execute(
                    "SELECT COUNT(*) AS c FROM character_images"
                ).fetchone()["c"]
                self.conn.executemany(
                    "INSERT OR IGNORE INTO character_images"
                    " (character_id, url, source, added_at) VALUES (?, ?, ?, ?)",
                    album_rows,
                )
                after = self.conn.execute(
                    "SELECT COUNT(*) AS c FROM character_images"
                ).fetchone()["c"]
                images_added = after - before

            # A character with no primary image but a populated album gets one.
            self.conn.execute(
                "UPDATE characters SET image_url = ("
                "  SELECT url FROM character_images"
                "  WHERE character_id = characters.id"
                "  ORDER BY added_at, url LIMIT 1"
                ") WHERE image_url = '' AND EXISTS ("
                "  SELECT 1 FROM character_images WHERE character_id = characters.id"
                ")"
            )

        return {
            "inserted": inserted,
            "updated": updated,
            "images": images_added,
            "total": inserted + updated,
        }

    def delete_character(self, character_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
        self.conn.execute(
            "DELETE FROM marriages WHERE character_id = ?", (character_id,)
        )
        self.conn.execute("DELETE FROM wishes WHERE character_id = ?", (character_id,))
        self.conn.execute("DELETE FROM starwishes WHERE character_id = ?", (character_id,))
        self.conn.execute(
            "DELETE FROM character_images WHERE character_id = ?", (character_id,)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_character(self, character_id: int, **fields) -> bool:
        allowed = {
            "name", "series", "image_url", "likes", "base_karuda",
            "like_rank", "claim_rank",
        }
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not fields:
            return False
        assignments = ", ".join(f"{k} = ?" for k in fields)
        try:
            cur = self.conn.execute(
                f"UPDATE characters SET {assignments} WHERE id = ?",
                (*fields.values(), character_id),
            )
        except sqlite3.IntegrityError as error:
            # Renaming onto a name + series that already exists. Callers can
            # report this properly instead of it surfacing as a crash.
            raise DuplicateCharacter(str(error)) from error
        self.conn.commit()
        return cur.rowcount > 0

    def get_character(self, character_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()

    def character_count(self, guild_id=None) -> int:
        if guild_id is None:
            return self.conn.execute(
                "SELECT COUNT(*) AS c FROM characters"
            ).fetchone()["c"]
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM characters"
            " WHERE guild_id = 0 OR guild_id = ?",
            (guild_id,),
        ).fetchone()["c"]

    def search_characters(self, query: str, limit: int = 25, guild_id=None) -> list:
        like = f"%{query}%"
        scope = "" if guild_id is None else " AND (guild_id = 0 OR guild_id = ?)"
        extra = () if guild_id is None else (guild_id,)
        return self.conn.execute(
            "SELECT * FROM characters WHERE (name LIKE ? OR series LIKE ?)"
            + scope
            + " ORDER BY likes DESC LIMIT ?",
            (like, like, *extra, limit),
        ).fetchall()

    # What a word-prefix match costs, measured in rank. Roughly two percent
    # of the pool: enough that Sans outranks Sanshokuin, small enough that
    # the best-known character in the game still wins on a near-miss spelling.
    PREFIX_HANDICAP = 2000

    def find_character_by_name(self, name: str) -> Optional[sqlite3.Row]:
        """The single best match for a typed name."""
        rows = self.find_characters_by_name(name, limit=1)
        return rows[0] if rows else None

    def find_characters_by_name(self, name: str, limit: int = 25,
                                guild_id=None) -> list:
        """Every plausible match for a typed name, closest first.

        Three things this has to get right, all of which it used to get
        wrong.

        Word order. AniList romanises Japanese names given-name-first, so
        Hatsune Miku is stored as "Miku Hatsune" - and a prefix search for
        "hatsune miku" found nothing at all. Every word of the query must
        appear, but in any order.

        Exact matches must not hide the rest. Ten obscure characters are
        called exactly "Miku" - one from Akikan!, one from a 1994 OVA - and
        returning only those meant "$im miku" never once showed Miku Hatsune.

        Words, not substrings. Matching "rin" anywhere in the text also finds
        Ma-rin Kitagawa, and "sans" finds Sumireko San-shokuin. A query word
        has to begin a word of the name.

        What is left is ranked by fame, and a match that only begins a longer
        word is charged a fixed amount of it. A hard "whole words first" rule
        is too blunt: Satoru Gojou is spelled Gojou, so "gojo" only begins his
        name, and two characters nobody has heard of called "Gojo Shiouji"
        and "Shihesu Gojo" beat the most famous character in the pool. Costing
        a prefix match some fame instead keeps Sans above Sanshokuin without
        burying Gojou.
        """
        query = (name or "").strip()
        words = [word for word in query.lower().split() if word]
        if not words:
            return []

        # A query word begins a word of the name: either the name starts
        # with it, or it follows a space.
        begins, begins_args = [], []
        # A query word IS a word of the name, rather than merely starting a
        # longer one.
        whole, whole_args = [], []
        for word in words:
            begins.append("(name LIKE ? COLLATE NOCASE"
                          " OR name LIKE ? COLLATE NOCASE)")
            begins_args += [f"{word}%", f"% {word}%"]
            whole.append("(name = ? COLLATE NOCASE"
                         " OR name LIKE ? COLLATE NOCASE"
                         " OR name LIKE ? COLLATE NOCASE"
                         " OR name LIKE ? COLLATE NOCASE)")
            whole_args += [word, f"{word} %", f"% {word}", f"% {word} %"]

        scope = "" if guild_id is None else " AND (guild_id = 0 OR guild_id = ?)"
        scope_args = () if guild_id is None else (guild_id,)

        return self.conn.execute(
            "SELECT *, CASE WHEN (" + " AND ".join(whole) + ")"
            " THEN 0 ELSE ? END AS handicap"
            " FROM characters"
            " WHERE (" + " AND ".join(begins) + ")" + scope
            + " ORDER BY handicap + like_rank, like_rank LIMIT ?",
            (*whole_args, self.PREFIX_HANDICAP, *begins_args, *scope_args, limit),
        ).fetchall()

    def excluded_sources(self, guild_id: int) -> list:
        """Which sources this server has switched off.

        Imported here rather than at module scope because cogs import db, and
        db importing a cog back would close the loop.
        """
        from cogs import toggles as toggle_table

        off = []
        if not toggle_table.state(self, guild_id, "western"):
            off += list(toggle_table.WESTERN_SOURCES)
        if not toggle_table.state(self, guild_id, "games"):
            off += list(toggle_table.GAME_SOURCES)
        return off

    # What $wa and $wg mean: the first is anime and manga, the second is
    # everything that came from a game or a cartoon.
    ANIME_SOURCE = "AniList"

    def _roll_scope(self, guild_id: int, include_claimed: bool,
                    gender: str = None, kind: str = None) -> tuple:
        """The FROM and WHERE every roll shares: this guild's view of the pool,
        optionally minus everyone already claimed here, minus any source the
        server has switched off, and narrowed to one gender or one kind of
        source when the command asked for that."""
        blocked = self.excluded_sources(guild_id)
        # Secret characters never come out of the pool. Left in, they would
        # count as unranked - which the bias gives a fair share of rolls - and
        # as "game" characters, since their source is not AniList. Their odds
        # are their own, decided in _secret_roll.
        clause = " AND c.secret_odds = 0"
        extra = ()
        # $limroul: the server can shut off everyone past a claim rank, which
        # is how a big roster is made to feel like a small one. Characters
        # with no rank at all - a server's own, a secret - are never cut,
        # since a rank they do not have cannot be too low.
        limit = self.get_setting(guild_id, "roll_rank_limit")
        if limit > 0:
            clause += " AND (c.claim_rank <= 0 OR c.claim_rank <= ?)"
            extra = (*extra, limit)
        if blocked:
            clause += (" AND c.source NOT IN ("
                       + ",".join("?" * len(blocked)) + ")")
            extra = (*extra, *blocked)
        if gender:
            clause += " AND c.gender = ?"
            extra = (*extra, gender)
        if kind == "anime":
            clause += " AND c.source = ?"
            extra = (*extra, self.ANIME_SOURCE)
        elif kind == "game":
            clause += " AND c.source != ? AND c.source != ''"
            extra = (*extra, self.ANIME_SOURCE)
        if include_claimed:
            return (
                "FROM characters c",
                "WHERE (c.guild_id = 0 OR c.guild_id = ?)" + clause,
                (guild_id, *extra),
            )
        return (
            "FROM characters c"
            " LEFT JOIN marriages m"
            "   ON m.character_id = c.id AND m.guild_id = ?",
            "WHERE m.character_id IS NULL"
            "  AND (c.guild_id = 0 OR c.guild_id = ?)" + clause,
            (guild_id, guild_id, *extra),
        )

    def _secret_roll(self, guild_id: int, include_claimed: bool,
                     gender: str = None) -> Optional[sqlite3.Row]:
        """A secret character, if one of them comes up on this roll.

        Each gets its own independent draw at one in secret_odds, so adding a
        second secret character does not make the first any easier to find.
        A secret character with no gender recorded answers to every roll
        command; one with a gender only to that command and to plain rolls.
        """
        join, claimed = "", ""
        args = [guild_id]
        if not include_claimed:
            join = (" LEFT JOIN marriages m"
                    " ON m.character_id = c.id AND m.guild_id = ?")
            claimed = " AND m.character_id IS NULL"
            args = [guild_id, guild_id]
        rows = self.conn.execute(
            f"SELECT c.* FROM characters c{join}"
            f" WHERE c.secret_odds > 0"
            f"  AND (c.guild_id = 0 OR c.guild_id = ?){claimed}",
            args,
        ).fetchall()
        for row in rows:
            if gender and row["gender"] and row["gender"] != gender:
                continue
            if random.random() * row["secret_odds"] < 1:
                return row
        return None

    def upsert_secret(self, name: str, series: str, images: list,
                      value: int, odds: int, gender: str = "") -> int:
        """Create or update one secret character, album and all.

        The album is replaced rather than added to, so an image somebody asked
        to take down is gone after the next boot, and the first image is the
        cover because that is the order it is inserted in.
        """
        cover = images[0] if images else ""
        self.conn.execute(
            "INSERT INTO characters (name, series, image_url, likes,"
            " base_karuda, like_rank, claim_rank, guild_id, source, gender,"
            " secret_odds)"
            " VALUES (?, ?, ?, 0, ?, 0, 0, 0, 'Secret', ?, ?)"
            " ON CONFLICT (name, series) DO UPDATE SET"
            "   image_url = excluded.image_url,"
            "   base_karuda = excluded.base_karuda,"
            "   source = 'Secret',"
            "   gender = excluded.gender,"
            "   secret_odds = excluded.secret_odds",
            (name, series, cover, int(value), gender or "", int(odds)),
        )
        character_id = self.conn.execute(
            "SELECT id FROM characters WHERE name = ? AND series = ?",
            (name, series),
        ).fetchone()["id"]
        self.conn.execute(
            "DELETE FROM character_images WHERE character_id = ?",
            (character_id,),
        )
        stamp = int(time.time())
        # One second apart, so the album sorts in the order given however the
        # file names happen to compare.
        self.conn.executemany(
            "INSERT OR IGNORE INTO character_images"
            " (character_id, url, source, added_at) VALUES (?, ?, 'secret', ?)",
            [(character_id, url, stamp + n) for n, url in enumerate(images)],
        )
        self.conn.commit()
        return character_id

    def retire_secrets(self, keep) -> int:
        """Stop rolling any secret character that is no longer listed.

        Retired rather than deleted: somebody may have claimed them, and a
        claim should not vanish because the list changed. Negative odds keep
        them out of the pool as well as out of the secret draw.
        """
        keep = list(keep)
        marks = ",".join("?" * len(keep)) or "''"
        changed = self.conn.execute(
            f"UPDATE characters SET secret_odds = -1"
            f" WHERE source = 'Secret' AND secret_odds > 0"
            f"  AND name NOT IN ({marks})",
            keep,
        ).rowcount
        self.conn.commit()
        return changed

    def deepest_rollable(self, guild_id: int) -> int:
        """The lowest claim rank a roll here can reach, 0 when uncapped."""
        limit = self.get_setting(guild_id, "roll_rank_limit")
        if limit <= 0:
            return 0
        row = self.conn.execute(
            "SELECT MAX(claim_rank) AS deepest FROM characters"
            " WHERE claim_rank > 0 AND claim_rank <= ?"
            "   AND (guild_id = 0 OR guild_id = ?) AND secret_odds = 0",
            (limit, guild_id),
        ).fetchone()
        return row["deepest"] or 0

    def random_character(
        self, guild_id: int, include_claimed: bool, bias: int = 0,
        gender: str = None, kind: str = None, secret: bool = False
    ) -> Optional[sqlite3.Row]:
        """One character to roll.

        At bias 0 the pool is flat, and a flat pool punishes size: against a
        hundred thousand characters a famous face turns up once in a thousand
        rolls, which is a lottery rather than a game. Above 0 the pick is
        pulled towards the top of the popularity ranking. Nobody is excluded -
        the whole roster still rolls, just not with equal weight.

        The dial is a percent rather than a curve so it means something to
        whoever sets it: 35 over a hundred thousand characters feels like a
        flat pool of thirty thousand did.
        """
        # Only a real roll can turn up a secret character - not a quiz, not
        # $random - and not a roll narrowed to anime or games, which she is
        # neither of.
        if secret and not kind:
            found = self._secret_roll(guild_id, include_claimed, gender)
            if found is not None:
                return found

        source, where, args = self._roll_scope(
            guild_id, include_claimed, gender, kind)

        if bias <= 0:
            return self.conn.execute(
                f"SELECT c.* {source} {where} ORDER BY RANDOM() LIMIT 1", args
            ).fetchone()

        # Picked by position in this server's own pool, never by rank number.
        # Rank numbers have gaps wherever $limroul, a switched-off source or
        # a claim takes characters out, and a number landing in a gap meant
        # the next character along - past the last one left, the same
        # character on most rolls. Positions have no gaps.
        ranked, unranked = self._pool_counts(
            (guild_id, include_claimed, gender, kind), source, where, args)
        if not ranked + unranked:
            return None

        # No popularity rank means no place in the ranking, so they get
        # exactly their share of the rolls instead. Anything unranked - a
        # server's own character, or one an owner added by hand - would
        # otherwise be unrollable the moment bias is on.
        if unranked and random.random() < unranked / (ranked + unranked):
            row = self.conn.execute(
                f"SELECT c.* {source} {where} AND c.like_rank <= 0"
                f" ORDER BY RANDOM() LIMIT 1",
                args,
            ).fetchone()
            if row is not None or not ranked:
                return row

        exponent = 1.0 + min(100, max(0, bias)) / 100.0
        # random() is below 1, so this runs 0 to ranked - 1: the very last
        # character is reachable and nothing points past the end.
        position = min(ranked - 1, int(ranked * (random.random() ** exponent)))
        row = self.conn.execute(
            f"SELECT c.* {source} {where} AND c.like_rank > 0"
            f" ORDER BY c.like_rank LIMIT 1 OFFSET ?",
            (*args, position),
        ).fetchone()
        if row is None:
            # The count is up to a minute old and the pool has shrunk since:
            # anyone ranked, at random - never one fixed fallback.
            row = self.conn.execute(
                f"SELECT c.* {source} {where} AND c.like_rank > 0"
                f" ORDER BY RANDOM() LIMIT 1",
                args,
            ).fetchone()
        return row

    # Counting a pool walks all of it, so a count is kept this long. Stale by
    # a claim or two it only moves a roll one place; set_setting forgets a
    # server's counts, so $limroul and the like count again at once.
    POOL_COUNT_SECONDS = 60

    def _pool_counts(self, key: tuple, source: str, where: str, args: tuple) -> tuple:
        """(ranked, unranked) characters in a roll's pool."""
        counts = self.__dict__.setdefault("_counts", {})
        now = time.time()
        hit = counts.get(key)
        if hit and hit[0] > now:
            return hit[1], hit[2]
        row = self.conn.execute(
            f"SELECT COALESCE(SUM(c.like_rank > 0), 0) AS r,"
            f" COALESCE(SUM(c.like_rank <= 0), 0) AS u {source} {where}",
            args,
        ).fetchone()
        counts[key] = (now + self.POOL_COUNT_SECONDS, row["r"], row["u"])
        return row["r"], row["u"]

    # ---------- character images ----------

    def add_image(self, character_id: int, url: str, source: str = None) -> bool:
        """Add one image to a character's album. False if already there."""
        try:
            self.conn.execute(
                "INSERT INTO character_images (character_id, url, source, added_at)"
                " VALUES (?, ?, ?, ?)",
                (character_id, url, source, int(time.time())),
            )
        except sqlite3.IntegrityError:
            return False
        # The first image added also becomes the primary one.
        character = self.get_character(character_id)
        if character and not character["image_url"]:
            self.conn.execute(
                "UPDATE characters SET image_url = ? WHERE id = ?",
                (url, character_id),
            )
        self.conn.commit()
        return True

    def add_images(self, character_id: int, urls) -> int:
        """Bulk add. Returns how many were new."""
        return sum(1 for url in urls if url and self.add_image(character_id, url))

    def add_art(self, entries, source: str = "safebooru",
                replace: tuple = ()) -> int:
        """Bulk-add album images, matching characters by name and series.

        `entries` are (name, series, urls). Written as one statement per URL
        that resolves the character in the same query, so a few hundred
        thousand rows do not become a few hundred thousand round trips
        through Python. Rows already present are ignored, which makes this
        safe to run on every boot.
        """
        stamp = int(time.time())
        # Seconds apart within a character, so an album keeps the order the
        # collector ranked it in rather than sorting by URL.
        rows = [
            (url, stamp + n, name, series)
            for name, series, urls in entries
            for n, url in enumerate(urls or [])
            if url
        ]
        if not rows and not replace:
            return 0

        # The shipped art file is the whole truth for the sources it owns.
        # Replacing them, rather than adding beside them, is what lets a
        # better collector take the old images away - and it never touches
        # the primary image or anything a server added by hand.
        if replace:
            marks = ",".join("?" * len(replace))
            self.conn.execute(
                f"DELETE FROM character_images WHERE source IN ({marks})",
                tuple(replace),
            )
        before = self.conn.execute(
            "SELECT COUNT(*) AS c FROM character_images"
        ).fetchone()["c"]
        self.conn.executemany(
            "INSERT OR IGNORE INTO character_images"
            " (character_id, url, source, added_at)"
            f" SELECT id, ?, '{source}', ? FROM characters"
            "  WHERE name = ? AND series = ? AND guild_id = 0",
            rows,
        )
        self.conn.commit()
        after = self.conn.execute(
            "SELECT COUNT(*) AS c FROM character_images"
        ).fetchone()["c"]
        return after - before

    def images_for(self, character_id: int) -> list:
        rows = self.conn.execute(
            "SELECT url FROM character_images WHERE character_id = ?"
            " ORDER BY added_at, url",
            (character_id,),
        ).fetchall()
        return [r["url"] for r in rows]

    def image_count(self, character_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM character_images WHERE character_id = ?",
            (character_id,),
        ).fetchone()["c"]

    def random_image(self, character_id: int) -> str:
        """One image at random from the album, falling back to the primary."""
        row = self.conn.execute(
            "SELECT url FROM character_images WHERE character_id = ?"
            " ORDER BY RANDOM() LIMIT 1",
            (character_id,),
        ).fetchone()
        if row:
            return row["url"]
        character = self.get_character(character_id)
        return character["image_url"] if character else ""

    def remove_image(self, character_id: int, url: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM character_images WHERE character_id = ? AND url = ?",
            (character_id, url),
        )
        if cur.rowcount:
            # If the primary went, promote whatever is left.
            character = self.get_character(character_id)
            if character and character["image_url"] == url:
                remaining = self.images_for(character_id)
                self.conn.execute(
                    "UPDATE characters SET image_url = ? WHERE id = ?",
                    (remaining[0] if remaining else "", character_id),
                )
        self.conn.commit()
        return cur.rowcount > 0

    def album_totals(self) -> tuple:
        """(characters with any image, total images) across the pool."""
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT character_id) AS chars, COUNT(*) AS images"
            " FROM character_images"
        ).fetchone()
        return row["chars"], row["images"]

    # ---------- guild settings ----------

    def get_setting(self, guild_id: int, key: str) -> int:
        default = config.GUILD_SETTINGS[key][0]
        row = self.conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, key),
        ).fetchone()
        value = row["value"] if row else default
        if key in premium.SETTING_RANGES:
            # A plan that lapses takes its wider range with it.
            low, high = self.setting_range(guild_id, key)
            value = max(low, min(high, value))
        # Server events (Plus) lift these two while they run. Everything
        # that reads rolls or grab payouts reads them here, so an event
        # reaches all of it and stops by itself when it ends.
        if key == "roll_limit":
            value += self.event_strength(guild_id, "rolls") or 0
        elif key == "karuda_grab_percent":
            rush = self.event_strength(guild_id, "karuda")
            if rush:
                value = min(100, value * rush // 100)
        return value

    def setting_range(self, guild_id: int, key: str) -> tuple:
        """(low, high) a setting may be set to on this server now: its plan's
        range, widened to take in a value it set before ranges came in."""
        _default, low, high, _text = config.GUILD_SETTINGS[key]
        ranges = premium.SETTING_RANGES.get(key)
        if not ranges:
            return low, high
        low, high = ranges[min(self.plan_rank(guild_id), 2)]
        row = self.conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, f"legacy:{key}")).fetchone()
        if row:
            low, high = min(low, row["value"]), max(high, row["value"])
        return low, high

    def all_settings(self, guild_id: int) -> dict:
        return {k: self.get_setting(guild_id, k) for k in config.GUILD_SETTINGS}

    def set_setting(self, guild_id: int, key: str, value: int):
        # A setting can change who rolls ($limroul): count the pool again.
        counts = self.__dict__.get("_counts", {})
        for cached in [k for k in counts if k[0] == guild_id]:
            del counts[cached]
        self.conn.execute(
            "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value",
            (guild_id, key, value),
        )
        self.conn.commit()

    # ---------- toggles ----------
    #
    # Stored in the same table but under their own "toggle:" keys, and
    # deliberately not in config.GUILD_SETTINGS: there are two dozen of them,
    # and $settings renders one embed field per entry against a hard limit of
    # twenty-five. They get their own listing instead.

    TOGGLE_PREFIX = "toggle:"

    def get_toggle(self, guild_id: int, key: str, default: int = 1) -> int:
        row = self.conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, self.TOGGLE_PREFIX + key),
        ).fetchone()
        return row["value"] if row else default

    def set_toggle(self, guild_id: int, key: str, value: int):
        self.conn.execute(
            "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value",
            (guild_id, self.TOGGLE_PREFIX + key, 1 if value else 0),
        )
        self.conn.commit()

    def flip_toggle(self, guild_id: int, key: str, default: int = 1) -> int:
        """Flip one and return what it is now."""
        new = 0 if self.get_toggle(guild_id, key, default) else 1
        self.set_toggle(guild_id, key, new)
        return new

    def clear_toggles(self, guild_id: int):
        self.conn.execute(
            "DELETE FROM guild_settings WHERE guild_id = ? AND key LIKE ?",
            (guild_id, self.TOGGLE_PREFIX + "%"),
        )
        self.conn.commit()

    # ---------- preferences ----------
    #
    # Integer odds and ends a server can set - embed colours, mostly. Same
    # table, its own "pref:" keys, same reason as the toggles: $settings
    # renders one field per entry and Discord allows twenty-five.

    PREF_PREFIX = "pref:"

    def get_pref(self, guild_id: int, key: str, default: int) -> int:
        row = self.conn.execute(
            "SELECT value FROM guild_settings WHERE guild_id = ? AND key = ?",
            (guild_id, self.PREF_PREFIX + key),
        ).fetchone()
        return row["value"] if row else default

    def set_pref(self, guild_id: int, key: str, value: int):
        self.conn.execute(
            "INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?)"
            " ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value",
            (guild_id, self.PREF_PREFIX + key, int(value)),
        )
        self.conn.commit()

    def clear_prefs(self, guild_id: int):
        self.conn.execute(
            "DELETE FROM guild_settings WHERE guild_id = ? AND key LIKE ?",
            (guild_id, self.PREF_PREFIX + "%"),
        )
        self.conn.commit()

    # ---------- wholesale resets ----------
    #
    # Each returns how many rows went, so the command can say what it did
    # rather than claiming success and leaving you to check.

    def clear_wishes(self, guild_id: int, user_id: int = None) -> int:
        """Wishes and starwishes both. Returns how many went."""
        gone = 0
        for table in ("wishes", "starwishes"):
            if user_id is None:
                cur = self.conn.execute(
                    f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
            else:
                cur = self.conn.execute(
                    f"DELETE FROM {table} WHERE guild_id = ? AND user_id = ?",
                    (guild_id, user_id))
            gone += cur.rowcount
        self.conn.commit()
        return gone

    def clear_disabled(self, guild_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM disabled_commands WHERE guild_id = ?", (guild_id,))
        self.conn.commit()
        return cur.rowcount

    def clear_character_keys(self, guild_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM character_keys WHERE guild_id = ?", (guild_id,))
        self.conn.commit()
        return cur.rowcount

    def clear_custom_characters(self, guild_id: int) -> int:
        """Only ever this guild's own inventions - guild_id 0 is the shared
        pool and is not a server's to delete."""
        if not guild_id:
            return 0
        rows = self.conn.execute(
            "SELECT id FROM characters WHERE guild_id = ?", (guild_id,)
        ).fetchall()
        ids = [row["id"] for row in rows]
        for character_id in ids:
            self.delete_character(character_id)
        return len(ids)

    def clear_notes_everywhere(self, guild_id: int) -> int:
        cur = self.conn.execute(
            "UPDATE marriages SET note = NULL, note_image = NULL"
            " WHERE guild_id = ? AND (note IS NOT NULL OR note_image IS NOT NULL)",
            (guild_id,))
        self.conn.commit()
        return cur.rowcount

    def clear_note_images(self, guild_id: int) -> int:
        cur = self.conn.execute(
            "UPDATE marriages SET note_image = NULL"
            " WHERE guild_id = ? AND note_image IS NOT NULL", (guild_id,))
        self.conn.commit()
        return cur.rowcount

    def reset_player(self, guild_id: int, user_id: int) -> dict:
        """Everything one player has here: claims, wishes, likes, notes,
        balance and timers."""
        counts = {}
        with self.conn:
            for label, statement, args in (
                ("characters",
                 "DELETE FROM marriages WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("wishes",
                 "DELETE FROM wishes WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("starwishes",
                 "DELETE FROM starwishes WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("likes",
                 "DELETE FROM character_likes WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("shards",
                 "DELETE FROM shard_pulls WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("badges",
                 "DELETE FROM badges WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("items",
                 "DELETE FROM player_items WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("tutorial steps",
                 "DELETE FROM tutorial_progress"
                 " WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("preferences",
                 "DELETE FROM player_prefs WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
                ("player",
                 "DELETE FROM players WHERE guild_id = ? AND user_id = ?",
                 (guild_id, user_id)),
            ):
                counts[label] = self.conn.execute(statement, args).rowcount
        return counts

    def reset_guild(self, guild_id: int) -> dict:
        """Everything this server has done. The shared character pool is not
        touched - it is not this server's to delete."""
        counts = {}
        with self.conn:
            for label, table in (
                ("claims", "marriages"),
                ("wishes", "wishes"),
                ("starwishes", "starwishes"),
                ("likes", "character_likes"),
                ("shards", "shard_pulls"),
                ("badges", "badges"),
                ("items", "player_items"),
                ("tutorial steps", "tutorial_progress"),
                ("preferences", "player_prefs"),
                ("keys", "character_keys"),
                ("players", "players"),
                ("settings", "guild_settings"),
                ("disabled commands", "disabled_commands"),
                ("channels", "allowed_channels"),
                ("prefixes", "guild_prefixes"),
            ):
                counts[label] = self.conn.execute(
                    f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,)
                ).rowcount
        counts["custom characters"] = self.clear_custom_characters(guild_id)
        return counts

    def reset_settings(self, guild_id: int):
        # A grandfathered value is the server's to keep, reset or not.
        self.conn.execute("DELETE FROM guild_settings WHERE guild_id = ?"
                          " AND key NOT LIKE 'legacy:%'", (guild_id,))
        self.conn.commit()

    # ---------- players ----------

    def get_player(self, guild_id: int, user_id: int) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM players WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
        if row:
            return row
        self.conn.execute(
            "INSERT INTO players (guild_id, user_id, first_seen) VALUES (?, ?, ?)",
            (guild_id, user_id, int(time.time())),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT * FROM players WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()

    def update_player(self, guild_id: int, user_id: int, **fields):
        allowed = {
            "karuda",
            "rolls_used",
            "rolls_reset_at",
            "claim_ready_at",
            "karuda_ready_at",
            "daily_ready_at",
            "rolls_bought",
            "extra_wish_slots",
            "first_seen",
            "premium",
            "tower_floor",
            "keys",
            "soulmate_id",
            "soulmate_set_at",
            "harem_sort",
            "showcase_id",
            "tuto_step",
            "tuto_silent",
            "roll_resets",
            "rolls_daily_at",
            "rt_ready_at",
        }
        fields = {k: v for k, v in fields.items() if k in allowed}
        if not fields:
            return
        self.get_player(guild_id, user_id)  # make sure the row exists
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE players SET {assignments} WHERE guild_id = ? AND user_id = ?",
            (*fields.values(), guild_id, user_id),
        )
        self.conn.commit()

    def add_karuda(self, guild_id: int, user_id: int, amount: int) -> int:
        player = self.get_player(guild_id, user_id)
        new_total = max(0, player["karuda"] + amount)
        self.update_player(guild_id, user_id, karuda=new_total)
        return new_total

    def top_karuda(self, guild_id: int, limit: int = 10) -> list:
        return self.conn.execute(
            "SELECT user_id, karuda FROM players"
            " WHERE guild_id = ? AND karuda > 0"
            " ORDER BY karuda DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def record_shard(self, guild_id: int, user_id: int, shard: str) -> int:
        """Count one shard pull. Returns the new total for that type."""
        self.conn.execute(
            "INSERT INTO shard_pulls (guild_id, user_id, shard, count)"
            " VALUES (?, ?, ?, 1)"
            " ON CONFLICT (guild_id, user_id, shard)"
            " DO UPDATE SET count = count + 1",
            (guild_id, user_id, shard),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT count FROM shard_pulls"
            " WHERE guild_id = ? AND user_id = ? AND shard = ?",
            (guild_id, user_id, shard),
        ).fetchone()["count"]

    def shards_of(self, guild_id: int, user_id: int) -> dict:
        rows = self.conn.execute(
            "SELECT shard, count FROM shard_pulls WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchall()
        return {row["shard"]: row["count"] for row in rows}

    # ---------- marriages ----------

    def owner_of(self, guild_id: int, character_id: int) -> Optional[int]:
        row = self.conn.execute(
            "SELECT user_id FROM marriages WHERE guild_id = ? AND character_id = ?",
            (guild_id, character_id),
        ).fetchone()
        return row["user_id"] if row else None

    def claim(self, guild_id: int, character_id: int, user_id: int) -> bool:
        """Atomically claim a character. False if someone else got there first."""
        try:
            self.conn.execute(
                "INSERT INTO marriages (guild_id, character_id, user_id, claimed_at)"
                " VALUES (?, ?, ?, ?)",
                (guild_id, character_id, user_id, int(time.time())),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def divorce(self, guild_id: int, character_id: int, user_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM marriages"
            " WHERE guild_id = ? AND character_id = ? AND user_id = ?",
            (guild_id, character_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def transfer(self, guild_id: int, character_id: int, to_user: int):
        self.conn.execute(
            "UPDATE marriages SET user_id = ?, claimed_at = ?"
            " WHERE guild_id = ? AND character_id = ?",
            (to_user, int(time.time()), guild_id, character_id),
        )
        self.conn.commit()

    def harem(self, guild_id: int, user_id: int, order: str = "likes") -> list:
        order_sql = {
            "likes": "c.likes DESC",
            "name": "c.name COLLATE NOCASE ASC",
            "recent": "m.claimed_at DESC",
            "karuda": "c.base_karuda DESC",
        }.get(order, "c.likes DESC")
        return self.conn.execute(
            "SELECT c.*, m.claimed_at, m.note FROM marriages m"
            " JOIN characters c ON c.id = m.character_id"
            f" WHERE m.guild_id = ? AND m.user_id = ? ORDER BY {order_sql}",
            (guild_id, user_id),
        ).fetchall()

    def harem_size(self, guild_id: int, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM marriages WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()["c"]

    def set_note(
        self, guild_id: int, character_id: int, user_id: int, note: str
    ) -> bool:
        cur = self.conn.execute(
            "UPDATE marriages SET note = ?"
            " WHERE guild_id = ? AND character_id = ? AND user_id = ?",
            (note, guild_id, character_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def top_harems(self, guild_id: int, limit: int = 10) -> list:
        return self.conn.execute(
            "SELECT m.user_id, COUNT(*) AS owned, COALESCE(SUM(c.likes), 0) AS likes"
            " FROM marriages m JOIN characters c ON c.id = m.character_id"
            " WHERE m.guild_id = ?"
            " GROUP BY m.user_id ORDER BY owned DESC, likes DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def rank_for_favourites(self, favourites: int) -> tuple:
        """Where a newcomer sits, and how big the pool is.

        Exact rather than approximate: count who already has more. That means
        a series added later slots into the right place without renumbering
        thirty thousand rows.
        """
        row = self.conn.execute(
            "SELECT COUNT(*) AS above FROM characters WHERE favourites > ?",
            (favourites,),
        ).fetchone()
        total = self.character_count()
        return row["above"] + 1, max(total, 1)

    # ---------- custom characters ----------

    def add_custom(self, guild_id: int, name: str, series: str, image_url: str,
                   base_karuda: int = 50):
        """A character only this guild rolls. None if that pair already exists."""
        try:
            cur = self.conn.execute(
                "INSERT INTO characters"
                " (name, series, image_url, likes, base_karuda, guild_id)"
                " VALUES (?, ?, ?, 0, ?, ?)",
                (name, series, image_url, base_karuda, guild_id),
            )
            self.conn.commit()
        except sqlite3.IntegrityError:
            return None
        if image_url:
            self.add_image(cur.lastrowid, image_url, source="custom")
        return cur.lastrowid

    def customs_of(self, guild_id: int) -> list:
        return self.conn.execute(
            "SELECT * FROM characters WHERE guild_id = ? ORDER BY name",
            (guild_id,),
        ).fetchall()

    def custom_count(self, guild_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM characters WHERE guild_id = ?", (guild_id,)
        ).fetchone()["c"]

    def owns_custom(self, guild_id: int, character_id: int) -> bool:
        """True only for a custom this guild made, never for a pool character."""
        row = self.conn.execute(
            "SELECT guild_id FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        return bool(row) and row["guild_id"] == guild_id

    # ---------- server configuration ----------

    def get_prefix(self, guild_id: int):
        row = self.conn.execute(
            "SELECT prefix FROM guild_prefixes WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row["prefix"] if row else None

    def set_prefix(self, guild_id: int, prefix: str):
        self.conn.execute(
            "INSERT INTO guild_prefixes (guild_id, prefix) VALUES (?, ?)"
            " ON CONFLICT (guild_id) DO UPDATE SET prefix = excluded.prefix",
            (guild_id, prefix),
        )
        self.conn.commit()

    def clear_prefix(self, guild_id: int):
        self.conn.execute(
            "DELETE FROM guild_prefixes WHERE guild_id = ?", (guild_id,)
        )
        self.conn.commit()

    def disable_command(self, guild_id: int, command: str) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO disabled_commands (guild_id, command) VALUES (?, ?)",
                (guild_id, command),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def enable_command(self, guild_id: int, command: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM disabled_commands WHERE guild_id = ? AND command = ?",
            (guild_id, command),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def enable_all_commands(self, guild_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM disabled_commands WHERE guild_id = ?", (guild_id,)
        )
        self.conn.commit()
        return cur.rowcount

    def disabled_commands(self, guild_id: int) -> set:
        return {
            row["command"]
            for row in self.conn.execute(
                "SELECT command FROM disabled_commands WHERE guild_id = ?",
                (guild_id,),
            )
        }

    def allow_channel(self, guild_id: int, channel_id: int) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO allowed_channels (guild_id, channel_id) VALUES (?, ?)",
                (guild_id, channel_id),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def unallow_channel(self, guild_id: int, channel_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM allowed_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def allowed_channels(self, guild_id: int) -> set:
        return {
            row["channel_id"]
            for row in self.conn.execute(
                "SELECT channel_id FROM allowed_channels WHERE guild_id = ?",
                (guild_id,),
            )
        }

    def clear_allowed_channels(self, guild_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM allowed_channels WHERE guild_id = ?", (guild_id,)
        )
        self.conn.commit()
        return cur.rowcount

    # ---------- who was here first ----------

    def note_guild(self, guild_id: int) -> int:
        """Record a server the first time it is seen. Returns first_seen."""
        row = self.conn.execute(
            "SELECT first_seen FROM guilds WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        if row:
            return row["first_seen"]
        stamp = int(time.time())
        self.conn.execute(
            "INSERT INTO guilds (guild_id, first_seen) VALUES (?, ?)",
            (guild_id, stamp),
        )
        self.conn.commit()
        return stamp

    def add_key(self, key: str, note: str = None):
        self.conn.execute(
            "INSERT INTO premium_keys (key, note, created_at) VALUES (?, ?, ?)",
            (key, note, int(time.time())),
        )
        self.conn.commit()

    def redeem_key(self, key: str, user_id: int) -> str:
        """Returns 'ok', 'unknown', or 'used'."""
        row = self.conn.execute(
            "SELECT redeemed_by FROM premium_keys WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            return "unknown"
        if row["redeemed_by"]:
            return "used"
        self.conn.execute(
            "UPDATE premium_keys SET redeemed_by = ?, redeemed_at = ? WHERE key = ?",
            (user_id, int(time.time()), key),
        )
        self.conn.commit()
        return "ok"

    def key_holder(self, user_id: int) -> bool:
        return bool(
            self.conn.execute(
                "SELECT 1 FROM premium_keys WHERE redeemed_by = ? LIMIT 1", (user_id,)
            ).fetchone()
        )

    # ---------- keys and soulmates ----------

    def add_keys(self, guild_id: int, user_id: int, amount: int) -> int:
        player = self.get_player(guild_id, user_id)
        total = max(0, player["keys"] + amount)
        self.update_player(guild_id, user_id, keys=total)
        return total

    def key_level(self, guild_id: int, character_id: int) -> int:
        row = self.conn.execute(
            "SELECT level FROM character_keys"
            " WHERE guild_id = ? AND character_id = ?",
            (guild_id, character_id),
        ).fetchone()
        return row["level"] if row else 0

    def raise_key_level(self, guild_id: int, character_id: int) -> int:
        self.conn.execute(
            "INSERT INTO character_keys (guild_id, character_id, level)"
            " VALUES (?, ?, 1)"
            " ON CONFLICT (guild_id, character_id)"
            " DO UPDATE SET level = level + 1",
            (guild_id, character_id),
        )
        self.conn.commit()
        return self.key_level(guild_id, character_id)

    def keyed_characters(self, guild_id: int, user_id: int) -> list:
        """A player's characters that have had keys spent on them."""
        return self.conn.execute(
            "SELECT c.*, k.level FROM character_keys k"
            " JOIN characters c ON c.id = k.character_id"
            " JOIN marriages m"
            "   ON m.character_id = c.id AND m.guild_id = k.guild_id"
            " WHERE k.guild_id = ? AND m.user_id = ? AND k.level > 0"
            " ORDER BY k.level DESC, c.like_rank",
            (guild_id, user_id),
        ).fetchall()

    def set_soulmate(self, guild_id: int, user_id: int, character_id: int):
        self.update_player(
            guild_id,
            user_id,
            soulmate_id=character_id,
            soulmate_set_at=int(time.time()),
        )

    def soulmate_of(self, guild_id: int, user_id: int):
        character_id = self.get_player(guild_id, user_id)["soulmate_id"]
        return self.get_character(character_id) if character_id else None

    def soulmate_holders(self, guild_id: int, character_id: int) -> list:
        return [
            row["user_id"]
            for row in self.conn.execute(
                "SELECT user_id FROM players"
                " WHERE guild_id = ? AND soulmate_id = ?",
                (guild_id, character_id),
            )
        ]

    # The six badges that existed before badges had levels, and the level of
    # the new material that is worth at least as much. Nobody ends up with
    # less than they paid for; Archivist gave a little of two things, so it
    # converts to the first level of both.
    OLD_BADGES = {
        "collector": [("iron", 2)],      # +2 rolls
        "prospector": [("gold", 2)],     # +4% grab -> Gold II is 6%
        "devoted": [("paper", 2)],       # +2 wishlist slots
        "swift": [("opal", 3)],          # 15% off the claim wait
        "lucky": [("emerald", 3)],       # +15% daily -> Emerald III is 18%
        "archivist": [("iron", 1), ("gold", 1)],
    }

    def _convert_old_badges(self):
        """Move anyone holding a pre-levels badge onto the new ladder."""
        names = tuple(self.OLD_BADGES)
        marks = ",".join("?" * len(names))
        rows = self.conn.execute(
            f"SELECT guild_id, user_id, badge, bought_at FROM badges"
            f" WHERE badge IN ({marks})",
            names,
        ).fetchall()
        if not rows:
            return

        for row in rows:
            for key, level in self.OLD_BADGES[row["badge"]]:
                # Somebody holding both Collector and Archivist converts to
                # Iron II and Iron I; the higher one has to win.
                self.conn.execute(
                    "INSERT INTO badges (guild_id, user_id, badge, level,"
                    " bought_at) VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT (guild_id, user_id, badge) DO UPDATE SET"
                    "   level = MAX(level, excluded.level)",
                    (row["guild_id"], row["user_id"], key, level,
                     row["bought_at"]),
                )
        self.conn.execute(
            f"DELETE FROM badges WHERE badge IN ({marks})", names
        )
        self.conn.commit()
        log.info("converted %s old badge(s) to levelled ones", len(rows))

    # ---------- badges and the tower ----------

    def add_badge(self, guild_id: int, user_id: int, badge: str) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO badges (guild_id, user_id, badge, bought_at)"
                " VALUES (?, ?, ?, ?)",
                (guild_id, user_id, badge, int(time.time())),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def badge_levels(self, guild_id: int, user_id: int) -> dict:
        """{badge key: level} for everything this player has climbed."""
        return {
            row["badge"]: row["level"]
            for row in self.conn.execute(
                "SELECT badge, level FROM badges"
                " WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )
        }

    def badge_level(self, guild_id: int, user_id: int, badge: str) -> int:
        row = self.conn.execute(
            "SELECT level FROM badges"
            " WHERE guild_id = ? AND user_id = ? AND badge = ?",
            (guild_id, user_id, badge),
        ).fetchone()
        return row["level"] if row else 0

    def raise_badge(self, guild_id: int, user_id: int, badge: str,
                    level: int) -> bool:
        """Set a badge to `level`. False if they are already there or past it."""
        if self.badge_level(guild_id, user_id, badge) >= level:
            return False
        self.conn.execute(
            "INSERT INTO badges (guild_id, user_id, badge, level, bought_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (guild_id, user_id, badge) DO UPDATE SET"
            "   level = excluded.level, bought_at = excluded.bought_at",
            (guild_id, user_id, badge, level, int(time.time())),
        )
        self.conn.commit()
        return True

    def badges_of(self, guild_id: int, user_id: int) -> list:
        return [
            row["badge"]
            for row in self.conn.execute(
                "SELECT badge FROM badges WHERE guild_id = ? AND user_id = ?"
                " ORDER BY bought_at",
                (guild_id, user_id),
            )
        ]

    def badge_holders(self, guild_id: int, badge: str, level: int = 1) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM badges"
            " WHERE guild_id = ? AND badge = ? AND level >= ?",
            (guild_id, badge, level),
        ).fetchone()["c"]

    def top_towers(self, guild_id: int, limit: int = 10) -> list:
        return self.conn.execute(
            "SELECT user_id, tower_floor FROM players"
            " WHERE guild_id = ? AND tower_floor > 0"
            " ORDER BY tower_floor DESC, karuda DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    # ---------- likes ----------

    def add_like(self, guild_id: int, user_id: int, character_id: int) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO character_likes"
                " (guild_id, user_id, character_id, liked_at) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, character_id, int(time.time())),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_like(self, guild_id: int, user_id: int, character_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM character_likes"
            " WHERE guild_id = ? AND user_id = ? AND character_id = ?",
            (guild_id, user_id, character_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def clear_likes(self, guild_id: int, user_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM character_likes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount

    def like_count(self, guild_id: int, character_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM character_likes"
            " WHERE guild_id = ? AND character_id = ?",
            (guild_id, character_id),
        ).fetchone()["c"]

    def likes_of(self, guild_id: int, user_id: int) -> list:
        return self.conn.execute(
            "SELECT c.* FROM character_likes l"
            " JOIN characters c ON c.id = l.character_id"
            " WHERE l.guild_id = ? AND l.user_id = ?"
            " ORDER BY l.liked_at",
            (guild_id, user_id),
        ).fetchall()

    def most_liked(self, guild_id: int, limit: int = 10) -> list:
        return self.conn.execute(
            "SELECT c.*, COUNT(*) AS votes FROM character_likes l"
            " JOIN characters c ON c.id = l.character_id"
            " WHERE l.guild_id = ?"
            " GROUP BY l.character_id ORDER BY votes DESC, c.like_rank LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def like_position(self, guild_id: int, character_id: int) -> int:
        """Where this character sits on the server's liked list, 0 if unliked."""
        rows = self.conn.execute(
            "SELECT character_id, COUNT(*) AS votes FROM character_likes"
            " WHERE guild_id = ? GROUP BY character_id ORDER BY votes DESC",
            (guild_id,),
        ).fetchall()
        for position, row in enumerate(rows, 1):
            if row["character_id"] == character_id:
                return position
        return 0

    # ---------- harem in bulk ----------

    # ---------- notes ----------

    def notes_of(self, guild_id: int, user_id: int) -> list:
        """Every character this player has written a note on."""
        return self.conn.execute(
            "SELECT c.*, m.note, m.note_image, m.claimed_at FROM marriages m"
            " JOIN characters c ON c.id = m.character_id"
            " WHERE m.guild_id = ? AND m.user_id = ?"
            "   AND m.note IS NOT NULL AND m.note != ''"
            " ORDER BY c.name",
            (guild_id, user_id),
        ).fetchall()

    def clear_notes(self, guild_id: int, user_id: int) -> int:
        """Wipe every note. Returns how many went."""
        cur = self.conn.execute(
            "UPDATE marriages SET note = NULL, note_image = NULL"
            " WHERE guild_id = ? AND user_id = ?"
            "   AND (note IS NOT NULL OR note_image IS NOT NULL)",
            (guild_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount

    def set_note_image(self, guild_id: int, character_id: int, user_id: int,
                       url: str) -> bool:
        cur = self.conn.execute(
            "UPDATE marriages SET note_image = ?"
            " WHERE guild_id = ? AND character_id = ? AND user_id = ?",
            (url or None, guild_id, character_id, user_id),
        )
        self.conn.commit()
        return bool(cur.rowcount)

    def note_of(self, guild_id: int, character_id: int):
        return self.conn.execute(
            "SELECT note, note_image, user_id FROM marriages"
            " WHERE guild_id = ? AND character_id = ?",
            (guild_id, character_id),
        ).fetchone()

    def matching_notes(self, guild_id: int, user_id: int, text: str) -> list:
        """Characters whose note contains this text."""
        return self.conn.execute(
            "SELECT c.*, m.note FROM marriages m"
            " JOIN characters c ON c.id = m.character_id"
            " WHERE m.guild_id = ? AND m.user_id = ?"
            "   AND m.note LIKE ? COLLATE NOCASE"
            " ORDER BY c.name",
            (guild_id, user_id, f"%{text}%"),
        ).fetchall()

    # ---------- tutorial ----------

    def tuto_step(self, guild_id: int, user_id: int) -> int:
        player = self.get_player(guild_id, user_id)
        if "tuto_step" not in player.keys():
            return 1
        return max(1, player["tuto_step"] or 1)

    def set_tuto_step(self, guild_id: int, user_id: int, step: int):
        self.update_player(guild_id, user_id, tuto_step=max(1, step))

    def tuto_silent(self, guild_id: int, user_id: int) -> bool:
        player = self.get_player(guild_id, user_id)
        if "tuto_silent" not in player.keys():
            return False
        return bool(player["tuto_silent"])

    def set_tuto_silent(self, guild_id: int, user_id: int, quiet: bool) -> bool:
        self.update_player(guild_id, user_id, tuto_silent=1 if quiet else 0)
        return quiet

    def finish_substep(self, guild_id: int, user_id: int, step: int,
                       substep: str) -> bool:
        """Mark one substep done. False if it already was."""
        try:
            self.conn.execute(
                "INSERT INTO tutorial_progress"
                " (guild_id, user_id, step, substep, done_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, step, substep, int(time.time())),
            )
        except sqlite3.IntegrityError:
            return False
        self.conn.commit()
        return True

    def finished_substeps(self, guild_id: int, user_id: int, step: int) -> set:
        return {
            row["substep"] for row in self.conn.execute(
                "SELECT substep FROM tutorial_progress"
                " WHERE guild_id = ? AND user_id = ? AND step = ?",
                (guild_id, user_id, step),
            ).fetchall()
        }

    def tuto_done_count(self, guild_id: int, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM tutorial_progress"
            " WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()["c"]

    def reset_tutorial(self, guild_id: int, user_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM tutorial_progress WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        self.conn.commit()
        self.set_tuto_step(guild_id, user_id, 1)
        return cur.rowcount

    def tuto_finished_anywhere(self, user_id: int, last_step: int) -> bool:
        """Whether this player has finished the main tutorial on some other
        server - which is what $skiptuto is for."""
        row = self.conn.execute(
            "SELECT MAX(step) AS deepest FROM tutorial_progress"
            " WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and (row["deepest"] or 0) >= last_step)

    # ---------- harem management ----------

    def harem_filtered(self, guild_id: int, user_id: int, order: str = "likes",
                       gender: str = None) -> list:
        """A harem, optionally narrowed to one gender."""
        rows = self.harem(guild_id, user_id, order)
        if not gender:
            return rows
        return [row for row in rows if (row["gender"] or "") == gender]

    def harem_position(self, guild_id: int, user_id: int, character_id: int,
                       order: str = "likes") -> int:
        """Where a character sits in someone's harem, 1-based. 0 if absent."""
        for position, row in enumerate(self.harem(guild_id, user_id, order), 1):
            if row["id"] == character_id:
                return position
        return 0

    def set_showcase(self, guild_id: int, user_id: int, character_id: int):
        """The one character shown at the top of a profile."""
        self.update_player(guild_id, user_id, showcase_id=character_id)

    def showcase_of(self, guild_id: int, user_id: int):
        player = self.get_player(guild_id, user_id)
        character_id = player["showcase_id"] if "showcase_id" in player.keys() else 0
        if not character_id:
            return None
        # Still theirs? Losing them in a trade should not leave a stranger on
        # the profile.
        if self.owner_of(guild_id, character_id) != user_id:
            return None
        return self.get_character(character_id)

    def set_harem_sort(self, guild_id: int, user_id: int, order: str):
        self.update_player(guild_id, user_id, harem_sort=order)

    def harem_sort_of(self, guild_id: int, user_id: int) -> str:
        player = self.get_player(guild_id, user_id)
        if "harem_sort" not in player.keys():
            return ""
        return player["harem_sort"] or ""

    def claim_info(self, guild_id: int, character_id: int):
        """Who owns a character here, when they got them, and what they wrote."""
        return self.conn.execute(
            "SELECT user_id, claimed_at, note FROM marriages"
            " WHERE guild_id = ? AND character_id = ?",
            (guild_id, character_id),
        ).fetchone()

    # ---------- leaderboards ----------

    def top_characters(self, guild_id: int, limit: int = 10,
                       offset: int = 0, series: str = None) -> list:
        """The pool's most valuable characters, in order.

        Value comes from rank, so this is the global ranking itself rather
        than a per-server one - the answer to "who is worth the most" is the
        same everywhere, which is the point of a shared pool.
        """
        where = "WHERE (guild_id = 0 OR guild_id = ?) AND like_rank > 0"
        args = [guild_id]
        if series:
            where += " AND series LIKE ?"
            args.append(f"%{series}%")
        # By value, then by claim_rank, which is what value is computed from.
        # The tie-break matters because the curve is capped: everyone the
        # boost pushes over the ceiling lands on exactly 1300, and breaking
        # those ties on like_rank ordered the top of the list by AniList
        # popularity instead - so a hand-placed number one showed up third.
        return self.conn.execute(
            f"SELECT * FROM characters {where}"
            f" ORDER BY base_karuda DESC, claim_rank LIMIT ? OFFSET ?",
            (*args, limit, max(0, offset)),
        ).fetchall()

    def count_characters_in(self, guild_id: int, series: str = None) -> int:
        where = "WHERE (guild_id = 0 OR guild_id = ?) AND like_rank > 0"
        args = [guild_id]
        if series:
            where += " AND series LIKE ?"
            args.append(f"%{series}%")
        return self.conn.execute(
            f"SELECT COUNT(*) AS c FROM characters {where}", args
        ).fetchone()["c"]

    def top_harem_value(self, guild_id: int, limit: int = 10) -> list:
        """Whose characters are worth the most, all added up."""
        return self.conn.execute(
            "SELECT m.user_id, COUNT(*) AS owned,"
            "       SUM(c.base_karuda) AS worth"
            " FROM marriages m JOIN characters c ON c.id = m.character_id"
            " WHERE m.guild_id = ?"
            " GROUP BY m.user_id ORDER BY worth DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def top_series(self, guild_id: int, limit: int = 10) -> list:
        """Which series this server has claimed the most of."""
        return self.conn.execute(
            "SELECT c.series, COUNT(*) AS claimed"
            " FROM marriages m JOIN characters c ON c.id = m.character_id"
            " WHERE m.guild_id = ?"
            " GROUP BY c.series ORDER BY claimed DESC, c.series LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def top_wished(self, guild_id: int, limit: int = 10) -> list:
        """Who the most people here are waiting for."""
        return self.conn.execute(
            "SELECT c.name, c.series, COUNT(*) AS wishers"
            " FROM wishes w JOIN characters c ON c.id = w.character_id"
            " WHERE w.guild_id = ?"
            " GROUP BY w.character_id ORDER BY wishers DESC, c.name LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def top_shards(self, guild_id: int, limit: int = 10) -> list:
        """Who has pulled the most shards."""
        return self.conn.execute(
            "SELECT user_id, SUM(count) AS pulled FROM shard_pulls"
            " WHERE guild_id = ? GROUP BY user_id"
            " ORDER BY pulled DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def top_claimers(self, guild_id: int, limit: int = 10) -> list:
        return self.conn.execute(
            "SELECT user_id, COUNT(*) AS owned FROM marriages"
            " WHERE guild_id = ? GROUP BY user_id"
            " ORDER BY owned DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

    def guild_overview(self, guild_id: int) -> dict:
        """A quick picture of how far along a server is."""
        def one(statement, *args):
            row = self.conn.execute(statement, args).fetchone()
            return (row[0] if row and row[0] is not None else 0)

        return {
            "players": one("SELECT COUNT(*) FROM players WHERE guild_id = ?",
                           guild_id),
            "claimed": one("SELECT COUNT(*) FROM marriages WHERE guild_id = ?",
                           guild_id),
            "series": one("SELECT COUNT(DISTINCT c.series) FROM marriages m"
                          " JOIN characters c ON c.id = m.character_id"
                          " WHERE m.guild_id = ?", guild_id),
            "karuda": one("SELECT SUM(karuda) FROM players WHERE guild_id = ?",
                          guild_id),
            "wishes": one("SELECT COUNT(*) FROM wishes WHERE guild_id = ?",
                          guild_id),
            "likes": one("SELECT COUNT(*) FROM character_likes WHERE guild_id = ?",
                         guild_id),
            "customs": one("SELECT COUNT(*) FROM characters WHERE guild_id = ?",
                           guild_id),
            "aliases": one("SELECT COUNT(*) FROM character_aliases"
                           " WHERE guild_id = ?", guild_id),
        }

    # ---------- player preferences ----------

    def get_player_pref(self, guild_id: int, user_id: int, key: str,
                        default: str = "") -> str:
        row = self.conn.execute(
            "SELECT value FROM player_prefs"
            " WHERE guild_id = ? AND user_id = ? AND key = ?",
            (guild_id, user_id, key),
        ).fetchone()
        return row["value"] if row else default

    def set_player_pref(self, guild_id: int, user_id: int, key: str,
                        value: str):
        """An empty value clears it, so one command can both set and unset."""
        if not value:
            self.conn.execute(
                "DELETE FROM player_prefs"
                " WHERE guild_id = ? AND user_id = ? AND key = ?",
                (guild_id, user_id, key),
            )
        else:
            self.conn.execute(
                "INSERT INTO player_prefs (guild_id, user_id, key, value)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (guild_id, user_id, key)"
                " DO UPDATE SET value = excluded.value",
                (guild_id, user_id, key, value),
            )
        self.conn.commit()

    def player_prefs(self, guild_id: int, user_id: int) -> dict:
        return {
            row["key"]: row["value"] for row in self.conn.execute(
                "SELECT key, value FROM player_prefs"
                " WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchall()
        }

    def clear_player_prefs(self, guild_id: int, user_id: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM player_prefs WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount

    # ---------- items ----------

    def add_item(self, guild_id: int, user_id: int, item: str,
                 amount: int = 1) -> int:
        """Give or take. Returns how many they hold afterwards, never below
        zero - a bug that hands somebody minus two teas is worse than one
        that hands them none."""
        self.conn.execute(
            "INSERT INTO player_items (guild_id, user_id, item, count)"
            " VALUES (?, ?, ?, 0) ON CONFLICT DO NOTHING",
            (guild_id, user_id, item),
        )
        self.conn.execute(
            "UPDATE player_items SET count = MAX(0, count + ?)"
            " WHERE guild_id = ? AND user_id = ? AND item = ?",
            (amount, guild_id, user_id, item),
        )
        self.conn.commit()
        return self.item_count(guild_id, user_id, item)

    def item_count(self, guild_id: int, user_id: int, item: str) -> int:
        row = self.conn.execute(
            "SELECT count FROM player_items"
            " WHERE guild_id = ? AND user_id = ? AND item = ?",
            (guild_id, user_id, item),
        ).fetchone()
        return row["count"] if row else 0

    def spend_item(self, guild_id: int, user_id: int, item: str,
                   amount: int = 1) -> bool:
        """Take one only if they have one. False means they did not."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE player_items SET count = count - ?"
                " WHERE guild_id = ? AND user_id = ? AND item = ? AND count >= ?",
                (amount, guild_id, user_id, item, amount),
            )
        return bool(cur.rowcount)

    def items_of(self, guild_id: int, user_id: int) -> dict:
        return {
            row["item"]: row["count"]
            for row in self.conn.execute(
                "SELECT item, count FROM player_items"
                " WHERE guild_id = ? AND user_id = ? AND count > 0",
                (guild_id, user_id),
            ).fetchall()
        }

    # ---------- aliases ----------

    def add_alias(self, guild_id: int, alias: str, character_id: int,
                  user_id: int = 0) -> bool:
        """Teach one nickname. False if that nickname is already taken."""
        alias = (alias or "").strip().lower()
        if not alias:
            return False
        try:
            self.conn.execute(
                "INSERT INTO character_aliases"
                " (guild_id, user_id, alias, character_id, added_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (guild_id, user_id, alias, character_id, int(time.time())),
            )
        except sqlite3.IntegrityError:
            return False
        self.conn.commit()
        return True

    def remove_alias(self, guild_id: int, alias: str, user_id: int = 0) -> bool:
        cur = self.conn.execute(
            "DELETE FROM character_aliases"
            " WHERE guild_id = ? AND user_id = ? AND alias = ?",
            (guild_id, user_id, (alias or "").strip().lower()),
        )
        self.conn.commit()
        return bool(cur.rowcount)

    def resolve_alias(self, guild_id: int, alias: str, user_id: int = 0):
        """The character a nickname points at.

        A player's own nickname wins over the server's, so somebody can call
        their favourite whatever they like without arguing with everyone else.
        """
        alias = (alias or "").strip().lower()
        row = self.conn.execute(
            "SELECT c.* FROM character_aliases a"
            " JOIN characters c ON c.id = a.character_id"
            " WHERE a.guild_id = ? AND a.alias = ? AND a.user_id IN (?, 0)"
            " ORDER BY a.user_id DESC LIMIT 1",
            (guild_id, alias, user_id),
        ).fetchone()
        return row

    def aliases_of(self, guild_id: int, user_id: int = 0) -> list:
        return self.conn.execute(
            "SELECT a.alias, a.user_id, c.name, c.series FROM character_aliases a"
            " JOIN characters c ON c.id = a.character_id"
            " WHERE a.guild_id = ? AND a.user_id = ?"
            " ORDER BY a.alias",
            (guild_id, user_id),
        ).fetchall()

    def aliases_for_character(self, guild_id: int, character_id: int) -> list:
        return [
            row["alias"] for row in self.conn.execute(
                "SELECT alias FROM character_aliases"
                " WHERE guild_id = ? AND character_id = ? ORDER BY alias",
                (guild_id, character_id),
            ).fetchall()
        ]

    def clear_aliases(self, guild_id: int, user_id: int = None) -> int:
        if user_id is None:
            cur = self.conn.execute(
                "DELETE FROM character_aliases WHERE guild_id = ?", (guild_id,))
        else:
            cur = self.conn.execute(
                "DELETE FROM character_aliases WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id))
        self.conn.commit()
        return cur.rowcount

    def find_by_name_or_alias(self, guild_id: int, user_id: int, name: str,
                              limit: int = 25) -> list:
        """Name lookup, but a nickname counts as a name.

        The nickname is tried first and returned on its own when it hits:
        somebody who taught the bot that "best girl" means one character does
        not want a list of everyone whose name happens to contain it.
        """
        hit = self.resolve_alias(guild_id, name, user_id)
        if hit is not None:
            return [hit]
        return self.find_characters_by_name(name, limit=limit, guild_id=guild_id)

    def harem_by_series(self, guild_id: int, user_id: int, series: str) -> list:
        return self.conn.execute(
            "SELECT c.* FROM marriages m JOIN characters c ON c.id = m.character_id"
            " WHERE m.guild_id = ? AND m.user_id = ? AND c.series LIKE ?"
            " ORDER BY c.like_rank",
            (guild_id, user_id, f"%{series}%"),
        ).fetchall()

    def divorce_many(self, guild_id: int, user_id: int, character_ids) -> int:
        ids = list(character_ids)
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self.conn:
            cur = self.conn.execute(
                f"DELETE FROM marriages WHERE guild_id = ? AND user_id = ?"
                f" AND character_id IN ({marks})",
                (guild_id, user_id, *ids),
            )
        return cur.rowcount

    def search_series(self, query: str, limit: int = 25, guild_id=None) -> list:
        # Not "AS cast": CAST is a reserved word in SQLite and the query is a
        # syntax error the moment you order by it.
        scope = "" if guild_id is None else " AND (guild_id = 0 OR guild_id = ?)"
        extra = () if guild_id is None else (guild_id,)
        rows = self.conn.execute(
            "SELECT series, COUNT(*) AS cast_size FROM characters"
            " WHERE series LIKE ?"
            + scope
            + " GROUP BY series ORDER BY cast_size DESC LIMIT ?",
            (f"%{query}%", *extra, limit),
        ).fetchall()
        return [(r["series"], r["cast_size"]) for r in rows]

    def characters_in_series(self, series: str, limit: int = 200,
                             guild_id=None) -> list:
        scope = "" if guild_id is None else " AND (guild_id = 0 OR guild_id = ?)"
        extra = () if guild_id is None else (guild_id,)
        return self.conn.execute(
            "SELECT * FROM characters WHERE series = ?"
            + scope
            + " ORDER BY like_rank LIMIT ?",
            (series, *extra, limit),
        ).fetchall()

    def series_cast(self, guild_id, query: str, limit: int = 200) -> list:
        """The cast of whichever series a typed query best matches.

        characters_in_series wants the exact title; nobody types the exact
        title. This resolves the query to the biggest matching series first,
        which is the same rule $series uses when it offers a choice.
        """
        matches = self.search_series(query, limit=1, guild_id=guild_id)
        if not matches:
            return []
        return self.characters_in_series(matches[0][0], limit=limit,
                                         guild_id=guild_id)

    # ---------- wishes ----------

    def add_wish(self, guild_id: int, user_id: int, character_id: int) -> bool:
        try:
            self.conn.execute(
                "INSERT INTO wishes (guild_id, user_id, character_id) VALUES (?, ?, ?)",
                (guild_id, user_id, character_id),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def remove_wish(self, guild_id: int, user_id: int, character_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM wishes"
            " WHERE guild_id = ? AND user_id = ? AND character_id = ?",
            (guild_id, user_id, character_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def wishes_of(self, guild_id: int, user_id: int) -> list:
        return self.conn.execute(
            "SELECT c.* FROM wishes w JOIN characters c ON c.id = w.character_id"
            " WHERE w.guild_id = ? AND w.user_id = ? ORDER BY c.likes DESC",
            (guild_id, user_id),
        ).fetchall()

    def random_wish(self, guild_id: int, user_id: int,
                    include_claimed: bool) -> Optional[sqlite3.Row]:
        """One character off this player's wishlist, for the Amethyst badge."""
        join, claimed = "", ""
        args = [guild_id, user_id]
        if not include_claimed:
            join = (" LEFT JOIN marriages m"
                    " ON m.character_id = c.id AND m.guild_id = ?")
            claimed = " AND m.character_id IS NULL"
            args = [guild_id, guild_id, user_id]
        return self.conn.execute(
            f"SELECT c.* FROM wishes w"
            f" JOIN characters c ON c.id = w.character_id{join}"
            f" WHERE w.guild_id = ? AND w.user_id = ?{claimed}"
            f" ORDER BY RANDOM() LIMIT 1",
            args,
        ).fetchone()

    def wishers_of(self, guild_id: int, character_id: int) -> list:
        """Everyone waiting on this character: wishes and starwishes."""
        rows = self.conn.execute(
            "SELECT user_id FROM wishes WHERE guild_id = ? AND character_id = ?"
            " UNION SELECT user_id FROM starwishes WHERE guild_id = ? AND character_id = ?",
            (guild_id, character_id, guild_id, character_id),
        ).fetchall()
        return [r["user_id"] for r in rows]

    # ---------- antinuke ----------

    def antinuke_get(self, guild_id: int, key: str, default: int = 0) -> int:
        rows = self._select("antinuke_settings", guild_id=guild_id, key=key)
        return rows[0]["value"] if rows else default

    def antinuke_set(self, guild_id: int, key: str, value: int):
        self._upsert("antinuke_settings", {"guild_id": guild_id, "key": key,
                                           "value": int(value)})

    def antinuke_people(self, guild_id: int, kind: str) -> list:
        return [r["user_id"] for r in self._select("antinuke_people", guild_id=guild_id,
                                                   kind=kind)]

    def antinuke_add_person(self, guild_id: int, user_id: int, kind: str):
        self._upsert("antinuke_people", {"guild_id": guild_id, "user_id": user_id,
                                         "kind": kind})

    def antinuke_remove_person(self, guild_id: int, user_id: int, kind: str) -> int:
        return self._delete("antinuke_people", guild_id=guild_id, user_id=user_id, kind=kind)

    # ---------- the karuda tower ----------

    def tower_floors_of(self, guild_id: int, user_id: int) -> list:
        return self.conn.execute(
            "SELECT * FROM tower_floors WHERE guild_id = ? AND user_id = ?"
            " ORDER BY tower, built_at, perk", (guild_id, user_id)).fetchall()

    def build_floor(self, guild_id: int, user_id: int, tower: int, perk: int,
                    cost: int) -> bool:
        """Pay for and add one floor, in one go. False if they can't afford
        it or already have that perk in this tower."""
        with self.conn:
            player = self.get_player(guild_id, user_id)
            if player["karuda"] < cost:
                return False
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO tower_floors (guild_id, user_id, tower, perk, cost,"
                " built_at) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, user_id, tower, perk, cost, time.time_ns()))
            if not cur.rowcount:
                return False
            self.conn.execute(
                "UPDATE players SET karuda = karuda - ?, tower_floor = tower_floor + 1"
                " WHERE guild_id = ? AND user_id = ?", (cost, guild_id, user_id))
        return True

    def destroy_tower(self, guild_id: int, user_id: int) -> tuple:
        """Pull every floor down and refund what they cost: (floors, karuda)."""
        with self.conn:
            row = self.conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(cost), 0) AS paid FROM tower_floors"
                " WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
            self.conn.execute("DELETE FROM tower_floors WHERE guild_id = ? AND user_id = ?",
                              (guild_id, user_id))
            self.conn.execute(
                "UPDATE players SET karuda = karuda + ?, tower_floor = 0"
                " WHERE guild_id = ? AND user_id = ?", (row["paid"], guild_id, user_id))
        return row["n"], row["paid"]

    # ---------- starwishes ----------

    def starwishes_of(self, guild_id: int, user_id: int) -> list:
        return self.conn.execute(
            "SELECT c.* FROM starwishes s JOIN characters c ON c.id = s.character_id"
            " WHERE s.guild_id = ? AND s.user_id = ? ORDER BY s.added_at",
            (guild_id, user_id),
        ).fetchall()

    def starwish_count(self, guild_id: int, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM starwishes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()["c"]

    def add_starwish(self, guild_id: int, user_id: int, character_id: int) -> bool:
        """Star a character. A plain wish for them is folded in."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO starwishes (guild_id, user_id, character_id, added_at)"
                " VALUES (?, ?, ?, ?)", (guild_id, user_id, character_id, int(time.time())))
            if cur.rowcount:
                self.conn.execute(
                    "DELETE FROM wishes WHERE guild_id = ? AND user_id = ? AND character_id = ?",
                    (guild_id, user_id, character_id))
        return cur.rowcount > 0

    def remove_starwish(self, guild_id: int, user_id: int, character_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM starwishes WHERE guild_id = ? AND user_id = ? AND character_id = ?",
            (guild_id, user_id, character_id))
        self.conn.commit()
        return cur.rowcount > 0

    def wish_candidates(self, guild_id: int, user_id: int, gender: str = None,
                        kind: str = None) -> list:
        """This player's unclaimed wishes and starwishes that this roll could
        turn up, as [(character, starred)]. Only unclaimed: a wish tilts rolls
        towards someone you can still have."""
        starred = {r["character_id"]: 1 for r in self.conn.execute(
            "SELECT character_id FROM starwishes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id))}
        plain = {r["character_id"]: 0 for r in self.conn.execute(
            "SELECT character_id FROM wishes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id))}
        wanted = {**plain, **starred}
        if not wanted:
            return []
        source, where, args = self._roll_scope(guild_id, False, gender, kind)
        marks = ",".join("?" * len(wanted))
        rows = self.conn.execute(
            f"SELECT c.* {source} {where} AND c.id IN ({marks})",
            (*args, *wanted)).fetchall()
        return [(row, wanted[row["id"]]) for row in rows]

    def wish_count(self, guild_id: int, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM wishes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()["c"]
