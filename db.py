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
    base_kakera INTEGER NOT NULL DEFAULT 50,
    UNIQUE (name, series)
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
    kakera          INTEGER NOT NULL DEFAULT 0,
    rolls_used      INTEGER NOT NULL DEFAULT 0,
    rolls_reset_at  INTEGER NOT NULL DEFAULT 0,
    claim_ready_at  INTEGER NOT NULL DEFAULT 0,
    kakera_ready_at INTEGER NOT NULL DEFAULT 0,
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
"""


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self):
        """Add columns that landed after someone already had a database."""
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

    def close(self):
        self.conn.close()

    # ---------- characters ----------

    def add_character(
        self, name: str, series: str, image_url: str, likes: int, base_kakera: int
    ) -> Optional[int]:
        """Insert a character. Returns its id, or None if it already exists."""
        try:
            cur = self.conn.execute(
                "INSERT INTO characters (name, series, image_url, likes, base_kakera)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, series, image_url, likes, base_kakera),
            )
            self.conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None

    def upsert_character(
        self, name: str, series: str, image_url: str, likes: int, base_kakera: int
    ) -> int:
        """Insert or update by (name, series). Used by the seed importer."""
        self.conn.execute(
            "INSERT INTO characters (name, series, image_url, likes, base_kakera)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (name, series) DO UPDATE SET"
            "   image_url = excluded.image_url,"
            "   likes = excluded.likes,"
            "   base_kakera = excluded.base_kakera",
            (name, series, image_url, likes, base_kakera),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT id FROM characters WHERE name = ? AND series = ?", (name, series)
        ).fetchone()
        return row["id"]

    def delete_character(self, character_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM characters WHERE id = ?", (character_id,))
        self.conn.execute(
            "DELETE FROM marriages WHERE character_id = ?", (character_id,)
        )
        self.conn.execute("DELETE FROM wishes WHERE character_id = ?", (character_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def update_character(self, character_id: int, **fields) -> bool:
        allowed = {"name", "series", "image_url", "likes", "base_kakera"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not fields:
            return False
        assignments = ", ".join(f"{k} = ?" for k in fields)
        cur = self.conn.execute(
            f"UPDATE characters SET {assignments} WHERE id = ?",
            (*fields.values(), character_id),
        )
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
            "kakera",
            "rolls_used",
            "rolls_reset_at",
            "claim_ready_at",
            "kakera_ready_at",
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

    def add_kakera(self, guild_id: int, user_id: int, amount: int) -> int:
        player = self.get_player(guild_id, user_id)
        new_total = max(0, player["kakera"] + amount)
        self.update_player(guild_id, user_id, kakera=new_total)
        return new_total

    def top_kakera(self, guild_id: int, limit: int = 10) -> list:
        return self.conn.execute(
            "SELECT user_id, kakera FROM players"
            " WHERE guild_id = ? AND kakera > 0"
            " ORDER BY kakera DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()

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
            "kakera": "c.base_kakera DESC",
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
