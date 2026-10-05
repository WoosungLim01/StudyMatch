"""
StudyMatch — single source of truth for connecting to studymatch.db, local or Turso.

Local dev (default, no env vars set): plain sqlite3 against data/studymatch.db,
exactly as before.

Production (Turso): set TURSO_DATABASE_URL + TURSO_AUTH_TOKEN env vars (never
commit these - set them on the host, e.g. Render's environment settings).
Uses libsql's embedded-replica mode, with its OWN local cache file
(REPLICA_PATH) - deliberately NOT data/studymatch.db, the plain SQLite file
committed to the repo for local dev. libsql's replica format needs a
companion metadata file alongside the local cache; pointed at the committed
plain file, it finds a .db with no matching metadata and refuses it
("invalid local state: db file exists but metadata file does not") - a real
failure hit on first deploy. A separate, gitignored path means there's never
a pre-existing file there for libsql to be confused by; connect() pulls the
latest remote state with sync() before every use (covers hosts where local
disk doesn't persist across restarts/redeploys - the replica is rebuilt from
the remote on next connect either way); write() pushes local changes back
up. Both call paths expose the same sqlite3-style API
(execute/executescript/commit/cursor/close), so calling code doesn't branch
on which backend is active.

pip install libsql   # only required when TURSO_DATABASE_URL is set

API gap patched here, deliberately in one place rather than at every call
site: sqlite3's Cursor supports `for row in cur.execute(...)` directly;
libsql's doesn't ("'builtins.Cursor' object is not iterable") - hit for
real on first deploy, in code (add_student.py, algorithm/placement.py,
data/archetype_store.py, app.py) that relies on that sqlite3 behavior.
Patching __iter__ onto libsql's Cursor class once, here, makes it behave
like sqlite3's everywhere, present and future call sites alike, instead of
fixing each one (and re-fixing every new one written later) by hand.
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "studymatch.db"
REPLICA_PATH = Path(__file__).parent / ".turso_replica.db"

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

_libsql_patched = False


def _patch_libsql_cursor(libsql):
    global _libsql_patched
    if _libsql_patched:
        return
    libsql.Cursor.__iter__ = lambda self: iter(self.fetchall())
    _libsql_patched = True


def connect():
    if TURSO_URL and TURSO_TOKEN:
        import libsql
        _patch_libsql_cursor(libsql)
        con = libsql.connect(str(REPLICA_PATH), sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
        con.sync()
    else:
        con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def write(con):
    """Use instead of con.commit() after any INSERT/UPDATE/DELETE - commits
    locally and, when Turso is configured, pushes the change to the remote."""
    con.commit()
    if TURSO_URL and TURSO_TOKEN:
        con.sync()
