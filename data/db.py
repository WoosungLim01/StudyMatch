"""
StudyMatch — single source of truth for connecting to studymatch.db, local or Turso.

Local dev (default, no env vars set): plain sqlite3 against data/studymatch.db,
exactly as before.

Production (Turso): set TURSO_DATABASE_URL + TURSO_AUTH_TOKEN env vars (never
commit these - set them on the host, e.g. Render's environment settings).
Uses libsql's embedded-replica mode: data/studymatch.db becomes a local
replica file kept in sync with the remote Turso database. connect() pulls
the latest remote state with sync() before every use (covers hosts where the
local disk doesn't persist across restarts/redeploys - the replica file is
rebuilt from the remote on next connect either way); write() pushes local
changes back up. Both call paths expose the same sqlite3-style API
(execute/executescript/commit/cursor/close), so calling code doesn't branch
on which backend is active.

pip install libsql   # only required when TURSO_DATABASE_URL is set
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "studymatch.db"

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


def connect():
    if TURSO_URL and TURSO_TOKEN:
        import libsql
        con = libsql.connect(str(DB_PATH), sync_url=TURSO_URL, auth_token=TURSO_TOKEN)
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
