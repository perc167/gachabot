"""Backups of the live database, small enough to send by Discord DM.

The database is mostly the shared roster of a hundred thousand characters,
and that roster ships with the bot (data/characters.json), so a backup
leaves it out. Everything else is kept: every player's harem, wishes,
likes, keys and karuda, levels, moderation, settings, Premium, custom and
secret characters, and any roster character something still points at, so
claims keep their ids.

A backup is marked as trimmed. When one is restored the bot sees the mark
at startup and loads the rest of the roster back in (cogs don't need to
know), then clears it.

Restoring: the backup is checked (a real SQLite file, not damaged, with the
bot's tables) and parked beside the database as <db>.restore. On the next
start it's swapped in, and the old database is kept as <db>.before-restore,
so a mistaken restore can be undone the same way.
"""
import gzip
import os
import shutil
import sqlite3
import tempfile
import time

TRIMMED_KEY = "pref:backup_trimmed"
ART_KEY = "pref:art_stamp"
MAX_RESTORE = 200 * 1024 * 1024     # unzipped, bytes
NEEDED_TABLES = {"players", "marriages", "characters", "guild_settings"}

# Every place a roster character's id is kept. Anything listed here survives
# the trim, so nobody's claim, wish, like, key, nickname, soulmate or
# showcase loses its character.
REFERENCES = (
    "SELECT character_id FROM marriages",
    "SELECT character_id FROM wishes",
    "SELECT character_id FROM character_likes",
    "SELECT character_id FROM character_keys",
    "SELECT character_id FROM character_aliases",
    "SELECT soulmate_id FROM players WHERE soulmate_id != 0",
    "SELECT showcase_id FROM players WHERE showcase_id != 0",
)


class BadBackup(Exception):
    """Not a backup this bot can restore."""


def make(db_path: str) -> tuple:
    """(gzipped backup bytes, a line describing it). Reads a consistent
    snapshot, so it's safe while the bot is running."""
    folder = tempfile.mkdtemp()
    copy = os.path.join(folder, "backup.db")
    try:
        source = sqlite3.connect(db_path)
        target = sqlite3.connect(copy)
        with target:
            source.backup(target)       # SQLite's own online backup
        source.close()

        existing = {r[0] for r in target.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        refs = " UNION ".join(q for q in REFERENCES
                              if q.split(" FROM ")[1].split()[0] in existing)
        with target:
            target.execute(
                "DELETE FROM characters WHERE guild_id = 0 AND secret_odds = 0"
                + (f" AND id NOT IN ({refs})" if refs else ""))
            target.execute("DELETE FROM character_images WHERE character_id"
                           " NOT IN (SELECT id FROM characters)")
            if "web_sessions" in existing:
                # Logins don't belong in a backup.
                target.execute("DELETE FROM web_sessions")
            target.execute("DELETE FROM guild_settings WHERE guild_id = 0"
                           " AND key IN (?, ?)", (TRIMMED_KEY, ART_KEY))
            target.execute("INSERT INTO guild_settings (guild_id, key, value)"
                           " VALUES (0, ?, 1)", (TRIMMED_KEY,))
        kept = target.execute("SELECT COUNT(*) FROM characters").fetchone()[0]
        players = target.execute("SELECT COUNT(*) FROM players").fetchone()[0]
        target.execute("VACUUM")
        target.close()
        with open(copy, "rb") as handle:
            data = gzip.compress(handle.read(), 9)
        note = f"{players:,} players, {kept:,} characters kept"
        return data, note
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def check(raw_gz: bytes) -> bytes:
    """The unzipped database, if it's a backup we can restore."""
    try:
        raw = gzip.decompress(raw_gz)
    except (OSError, EOFError):
        raw = raw_gz                    # an unzipped .db is fine too
    if len(raw) > MAX_RESTORE or not raw.startswith(b"SQLite format 3\x00"):
        raise BadBackup("That isn't a Paper backup.")
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "check.db")
    try:
        with open(path, "wb") as handle:
            handle.write(raw)
        con = sqlite3.connect(path)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BadBackup("That backup is damaged.")
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not NEEDED_TABLES <= tables:
                raise BadBackup("That isn't a Paper backup.")
        finally:
            con.close()
    except sqlite3.DatabaseError:
        raise BadBackup("That backup is damaged.")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return raw


def stage(db_path: str, raw: bytes):
    """Park a checked backup to be swapped in at the next start."""
    with open(db_path + ".restore", "wb") as handle:
        handle.write(raw)


def apply_pending(db_path: str) -> bool:
    """At startup, before the database opens: swap in a parked backup."""
    pending = db_path + ".restore"
    if not os.path.exists(pending):
        return False
    if os.path.exists(db_path):
        os.replace(db_path, db_path + ".before-restore")
    for extra in ("-wal", "-shm"):
        # The old database's journals go with it, so the kept copy is whole
        # and they can't be mistaken for the restored one's.
        if os.path.exists(db_path + extra):
            os.replace(db_path + extra, db_path + ".before-restore" + extra)
    os.replace(pending, db_path)
    return True


def stamp() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())
