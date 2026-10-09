"""
StudyMatch — additive, idempotent schema changes for databases built before
a table or column existed. The live Turso database is never rebuilt from
schema.sql, so this is how it picks up new tables on deploy (app.py runs it
at startup) and how one-off scripts make sure the tables they touch exist.
Mirror every change here in data/schema.sql, which fresh builds use.
"""


def migrate(con):
    con.execute("""CREATE TABLE IF NOT EXISTS admin_group (
        group_id      TEXT PRIMARY KEY REFERENCES study_group(group_id),
        created_at    TEXT NOT NULL
    )""")

    con.execute("""CREATE TABLE IF NOT EXISTS group_chat_message (
        message_id    INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id      TEXT NOT NULL REFERENCES study_group(group_id),
        student_id    TEXT NOT NULL REFERENCES student(student_id),
        text          TEXT NOT NULL,
        created_at    TEXT NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_group_chat_message_group ON group_chat_message(group_id, message_id)")

    con.execute("""CREATE TABLE IF NOT EXISTS group_chat_attachment (
        attachment_id TEXT PRIMARY KEY,
        group_id      TEXT NOT NULL REFERENCES study_group(group_id),
        student_id    TEXT NOT NULL REFERENCES student(student_id),
        filename      TEXT NOT NULL,
        content_type  TEXT NOT NULL,
        kind          TEXT NOT NULL CHECK (kind IN ('image', 'video', 'file')),
        size_bytes    INTEGER NOT NULL,
        created_at    TEXT NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_group_chat_attachment_group ON group_chat_attachment(group_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_group_chat_attachment_student ON group_chat_attachment(student_id)")
    con.execute("""CREATE TABLE IF NOT EXISTS group_chat_attachment_chunk (
        attachment_id TEXT NOT NULL REFERENCES group_chat_attachment(attachment_id),
        seq           INTEGER NOT NULL,
        data          BLOB NOT NULL,
        PRIMARY KEY (attachment_id, seq)
    )""")

    columns = [r[1] for r in con.execute("PRAGMA table_info(group_chat_message)").fetchall()]
    if "attachment_id" not in columns:
        con.execute(
            "ALTER TABLE group_chat_message ADD COLUMN attachment_id TEXT "
            "REFERENCES group_chat_attachment(attachment_id)"
        )
