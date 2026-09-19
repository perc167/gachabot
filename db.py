"""SQLite storage layer. One connection, shared across cogs."""
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
    PRIMARY KEY (guild_id, user_id)
);

-- A character can be married by at most one user per guild.
CREATE TABLE IF NOT EXISTS marriages (
    guild_id     INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    claimed_at   INTEGER NOT NULL,
    note         TEXT,
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

-- How many of each shard type a player has pulled. Flavour and bragging
-- rights; the spendable balance is players.karuda.
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


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Add columns that landed after someone already had a database."""
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
        for column in ("daily_ready_at",):
            if column not in existing:
                self.conn.execute(
                    f"ALTER TABLE players ADD COLUMN {column}"
                    " INTEGER NOT NULL DEFAULT 0"
                )

        character_columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(characters)").fetchall()
        }
        for column in ("like_rank", "claim_rank"):
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
                )
                character_id = existing.get(key)
                if character_id is None:
                    cur = self.conn.execute(
                        "INSERT INTO characters"
                        " (name, series, image_url, likes, base_karuda,"
                        "  like_rank, claim_rank)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (entry["name"], entry["series"], *values),
                    )
                    character_id = cur.lastrowid
                    existing[key] = character_id
                    inserted += 1
                else:
                    self.conn.execute(
                        "UPDATE characters SET image_url = ?, likes = ?,"
                        " base_karuda = ?, like_rank = ?, claim_rank = ?"
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

    def character_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) AS c FROM characters").fetchone()["c"]

    def search_characters(self, query: str, limit: int = 25) -> list:
        like = f"%{query}%"
        return self.conn.execute(
            "SELECT * FROM characters WHERE name LIKE ? OR series LIKE ?"
            " ORDER BY likes DESC LIMIT ?",
            (like, like, limit),
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

    def random_character(
        self, guild_id: int, include_claimed: bool
    ) -> Optional[sqlite3.Row]:
        if include_claimed:
            return self.conn.execute(
                "SELECT * FROM characters ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
        return self.conn.execute(
            "SELECT c.* FROM characters c"
            " LEFT JOIN marriages m"
            "   ON m.character_id = c.id AND m.guild_id = ?"
            " WHERE m.character_id IS NULL"
            " ORDER BY RANDOM() LIMIT 1",
            (guild_id,),
        ).fetchone()

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
            "INSERT INTO players (guild_id, user_id) VALUES (?, ?)", (guild_id, user_id)
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
