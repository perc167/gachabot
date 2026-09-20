"""SQLite storage layer. One connection, shared across cogs."""
import random
import sqlite3
import time
from typing import Optional

import config

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
"""


class DuplicateCharacter(Exception):
    """A write would collide with an existing name + series pair."""


# Built after the migrations rather than alongside the tables: an older
# database reaches __init__ without a like_rank column at all, and indexing a
# column that is about to be added fails the whole script.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_characters_rank
    ON characters (like_rank);
CREATE INDEX IF NOT EXISTS idx_characters_series
    ON characters (series);
CREATE INDEX IF NOT EXISTS idx_characters_name
    ON characters (name COLLATE NOCASE);
"""


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.executescript(INDEXES)
        self.conn.commit()

    def _migrate(self):
        """Add columns that landed after someone already had a database."""
        # Added after the roster grew past AniList. Older databases have the
        # table without it, and CREATE TABLE IF NOT EXISTS will not add it.
        for table, column, spec in (
            ("characters", "source", "TEXT NOT NULL DEFAULT ''"),
            ("marriages", "note_image", "TEXT"),
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
                )
                character_id = existing.get(key)
                if character_id is None:
                    cur = self.conn.execute(
                        "INSERT INTO characters"
                        " (name, series, image_url, likes, base_karuda,"
                        "  like_rank, claim_rank, favourites, source)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (entry["name"], entry["series"], *values),
                    )
                    character_id = cur.lastrowid
                    existing[key] = character_id
                    inserted += 1
                else:
                    self.conn.execute(
                        "UPDATE characters SET image_url = ?, likes = ?,"
                        " base_karuda = ?, like_rank = ?, claim_rank = ?,"
                        " favourites = ?, source = ?"
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

    def find_character_by_name(self, name: str) -> Optional[sqlite3.Row]:
        """Exact match first, then the most-liked name that starts with it."""
        row = self.conn.execute(
            "SELECT * FROM characters WHERE name = ? COLLATE NOCASE", (name,)
        ).fetchone()
        if row:
            return row
        return self.conn.execute(
            "SELECT * FROM characters WHERE name LIKE ? COLLATE NOCASE"
            " ORDER BY likes DESC LIMIT 1",
            (f"{name}%",),
        ).fetchone()

    def find_characters_by_name(self, name: str, limit: int = 25,
                                guild_id=None) -> list:
        """Every plausible match for a typed name, best known first.

        find_character_by_name picks one arbitrarily, which is wrong when two
        characters share a name - there are several Shiros. Callers use this
        and ask which one was meant.
        """
        scope = "" if guild_id is None else " AND (guild_id = 0 OR guild_id = ?)"
        extra = () if guild_id is None else (guild_id,)
        exact = self.conn.execute(
            "SELECT * FROM characters WHERE name = ? COLLATE NOCASE"
            + scope
            + " ORDER BY like_rank LIMIT ?",
            (name, *extra, limit),
        ).fetchall()
        if exact:
            return exact
        return self.conn.execute(
            "SELECT * FROM characters WHERE name LIKE ? COLLATE NOCASE"
            + scope
            + " ORDER BY like_rank LIMIT ?",
            (f"{name}%", *extra, limit),
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

    def _roll_scope(self, guild_id: int, include_claimed: bool) -> tuple:
        """The FROM and WHERE every roll shares: this guild's view of the pool,
        optionally minus everyone already claimed here, minus any source the
        server has switched off."""
        blocked = self.excluded_sources(guild_id)
        clause = ""
        extra = ()
        if blocked:
            clause = (" AND c.source NOT IN ("
                      + ",".join("?" * len(blocked)) + ")")
            extra = tuple(blocked)
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

    def random_character(
        self, guild_id: int, include_claimed: bool, bias: int = 0
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
        source, where, args = self._roll_scope(guild_id, include_claimed)

        if bias <= 0:
            return self.conn.execute(
                f"SELECT c.* {source} {where} ORDER BY RANDOM() LIMIT 1", args
            ).fetchone()

        # Deliberately not counted through the join: at a hundred thousand
        # rows that is a full scan on every single roll. The depth of the
        # ranking is the same for everyone, and an index knows it instantly.
        deepest = self.conn.execute(
            "SELECT MAX(like_rank) AS deepest FROM characters"
        ).fetchone()["deepest"] or 0
        if not deepest:
            return self.conn.execute(
                f"SELECT c.* {source} {where} ORDER BY RANDOM() LIMIT 1", args
            ).fetchone()
        # Counted over exactly the same set the branch below picks from.
        # Anything unranked - a server's own character, or one an owner added
        # by hand - would otherwise be unrollable the moment bias is on.
        unranked = self.conn.execute(
            f"SELECT COUNT(*) AS c {source} {where} AND c.like_rank <= 0", args
        ).fetchone()["c"]
        total = deepest + unranked

        # No popularity rank means a rank window would shut them out
        # completely, so give them exactly their share of the rolls instead.
        if unranked and random.random() < unranked / total:
            return self.conn.execute(
                f"SELECT c.* {source} {where} AND c.like_rank <= 0"
                f" ORDER BY RANDOM() LIMIT 1",
                args,
            ).fetchone()

        exponent = 1.0 + min(100, max(0, bias)) / 100.0
        target = max(1, int(deepest * (random.random() ** exponent)))
        row = self.conn.execute(
            f"SELECT c.* {source} {where} AND c.like_rank >= ?"
            f" ORDER BY c.like_rank LIMIT 1",
            (*args, target),
        ).fetchone()
        if row is None:
            # Everyone past the target is claimed; fall back up the ranking.
            row = self.conn.execute(
                f"SELECT c.* {source} {where} AND c.like_rank > 0"
                f" ORDER BY c.like_rank DESC LIMIT 1",
                args,
            ).fetchone()
        return row

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
        return row["value"] if row else default

    def all_settings(self, guild_id: int) -> dict:
        return {k: self.get_setting(guild_id, k) for k in config.GUILD_SETTINGS}

    def set_setting(self, guild_id: int, key: str, value: int):
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
        if user_id is None:
            cur = self.conn.execute(
                "DELETE FROM wishes WHERE guild_id = ?", (guild_id,))
        else:
            cur = self.conn.execute(
                "DELETE FROM wishes WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id))
        self.conn.commit()
        return cur.rowcount

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
                ("likes", "character_likes"),
                ("shards", "shard_pulls"),
                ("badges", "badges"),
                ("items", "player_items"),
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
        self.conn.execute("DELETE FROM guild_settings WHERE guild_id = ?", (guild_id,))
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

    def badges_of(self, guild_id: int, user_id: int) -> list:
        return [
            row["badge"]
            for row in self.conn.execute(
                "SELECT badge FROM badges WHERE guild_id = ? AND user_id = ?"
                " ORDER BY bought_at",
                (guild_id, user_id),
            )
        ]

    def badge_holders(self, guild_id: int, badge: str) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM badges WHERE guild_id = ? AND badge = ?",
            (guild_id, badge),
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

    # ---------- leaderboards ----------

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

    def wishers_of(self, guild_id: int, character_id: int) -> list:
        rows = self.conn.execute(
            "SELECT user_id FROM wishes WHERE guild_id = ? AND character_id = ?",
            (guild_id, character_id),
        ).fetchall()
        return [r["user_id"] for r in rows]

    def wish_count(self, guild_id: int, user_id: int) -> int:
        return self.conn.execute(
            "SELECT COUNT(*) AS c FROM wishes WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()["c"]
