"""
StudyMatch — create (or remove) an admin group: a hand-picked set of
students in an extra group of their own, e.g. so the team can test group
chat together.

Nobody's matched group is touched. Matching ignores admin groups (see the
admin_group table in schema.sql): no one is ever placed into one, being in
one doesn't count as being placed, and members may come from different
courses. Each member's home page keeps their matched group and gains a link
to the admin group's chat.

Runs against whatever data/db.py connects to: the local data/studymatch.db,
or the live Turso database when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are
set. The app creates the admin_group table at startup, so deploy (or start
the app once locally) before running this. Without --apply it only prints
what it would do.

Usage (from the repo root):
    python data/make_group.py 0037 0045 0041 0039 0044
    python data/make_group.py 0037 0045 0041 0039 0044 --apply
    python data/make_group.py stu_0037 stu_0045 --name "Chat Test" --apply
    python data/make_group.py --remove grp_010 --apply
"""

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algorithm.placement import _next_group_id
from data.db import connect, write

DEFAULT_NAME = "Admin Test Group"
NO_TABLE = ("This database has no admin_group table yet. Deploy the latest code "
            "(or start the app once locally) first; the app creates it on startup.")


def normalize_id(raw):
    raw = raw.strip()
    return f"stu_{raw}" if raw.isdigit() else raw


def _has_admin_table(cur):
    return cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='admin_group'"
    ).fetchone() is not None


def plan_group(cur, student_ids, name):
    """-> (course_id, [(student_id, name, course_id, course_code)]), or raises ValueError."""
    if not student_ids:
        raise ValueError("Give at least one student id.")
    if len(set(student_ids)) != len(student_ids):
        raise ValueError("A student id is listed twice.")
    if not _has_admin_table(cur):
        raise ValueError(NO_TABLE)
    if cur.execute(
        "SELECT 1 FROM admin_group ag JOIN study_group sg ON sg.group_id = ag.group_id WHERE sg.group_name = ?",
        (name,),
    ).fetchone():
        raise ValueError(f"An admin group named {name!r} already exists. Pick another name with --name.")

    rows, missing = [], []
    for sid in student_ids:
        row = cur.execute(
            """SELECT s.name, cm.course_id, c.course_code FROM student s
               LEFT JOIN course_membership cm ON cm.student_id = s.student_id
               LEFT JOIN course c ON c.course_id = cm.course_id
               WHERE s.student_id = ?""",
            (sid,),
        ).fetchone()
        if row is None:
            missing.append(sid)
        else:
            rows.append((sid, *row))
    if missing:
        raise ValueError(f"No such student: {', '.join(missing)}")
    courses = Counter(course_id for _, _, course_id, _ in rows if course_id)
    if not courses:
        raise ValueError("None of these students is enrolled in a course.")
    # study_group.course_id is required, so use the most common course (first listed on a tie).
    return courses.most_common(1)[0][0], rows


def make_admin_group(con, student_ids, name=DEFAULT_NAME, now_iso=None):
    """Creates the admin group and returns its group_id. Commit is the caller's job."""
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = con.cursor()
    course_id, rows = plan_group(cur, student_ids, name)
    group_id = _next_group_id(cur)
    cur.execute(
        """INSERT INTO study_group (group_id, course_id, group_name, max_members, current_members,
                                    created_at, group_score, avg_pairwise, worst_pairwise)
           VALUES (?,?,?,?,?,?,NULL,NULL,NULL)""",
        (group_id, course_id, name, len(rows), len(rows), now_iso),
    )
    cur.execute("INSERT INTO admin_group VALUES (?,?)", (group_id, now_iso))
    for sid, *_ in rows:
        cur.execute(
            "INSERT INTO group_membership VALUES (?,?,?,?)",
            (group_id, sid, now_iso, "Flexible/No Preference"),
        )
    return group_id


def remove_admin_group(con, group_id):
    """Deletes an admin group with its memberships and chat. Refuses matched groups."""
    cur = con.cursor()
    if not _has_admin_table(cur):
        raise ValueError(NO_TABLE)
    if not cur.execute("SELECT 1 FROM admin_group WHERE group_id=?", (group_id,)).fetchone():
        raise ValueError(f"{group_id} is not an admin group, so it isn't touched.")
    cur.execute("DELETE FROM group_chat_message WHERE group_id=?", (group_id,))
    cur.execute(
        "DELETE FROM group_chat_attachment_chunk WHERE attachment_id IN "
        "(SELECT attachment_id FROM group_chat_attachment WHERE group_id=?)",
        (group_id,),
    )
    cur.execute("DELETE FROM group_chat_attachment WHERE group_id=?", (group_id,))
    cur.execute("DELETE FROM group_membership WHERE group_id=?", (group_id,))
    cur.execute("DELETE FROM admin_group WHERE group_id=?", (group_id,))
    cur.execute("DELETE FROM study_group WHERE group_id=?", (group_id,))


def main():
    parser = argparse.ArgumentParser(description="Create or remove an admin group outside matching.")
    parser.add_argument("students", nargs="*", help="student ids, e.g. 0037 or stu_0037")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"group name (default: {DEFAULT_NAME!r})")
    parser.add_argument("--remove", metavar="GROUP_ID", help="delete this admin group and its chat instead")
    parser.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    args = parser.parse_args()

    con = connect()
    try:
        cur = con.cursor()
        if args.remove:
            row = cur.execute("SELECT group_name, current_members FROM study_group WHERE group_id=?",
                              (args.remove,)).fetchone()
            if row is None:
                raise SystemExit(f"Not changed: no group {args.remove}.")
            print(f"Remove {args.remove} ({row[0]!r}, {row[1]} members) and its chat history.")
            if not args.apply:
                print("\nDry run, nothing written. Re-run with --apply to make the change.")
                return
            try:
                remove_admin_group(con, args.remove)
            except ValueError as e:
                raise SystemExit(f"Not changed: {e}")
            write(con)
            print("Removed.")
            return

        student_ids = [normalize_id(s) for s in args.students]
        try:
            course_id, rows = plan_group(cur, student_ids, args.name)
        except ValueError as e:
            raise SystemExit(f"Not changed: {e}")
        print(f"New admin group {args.name!r} with {len(rows)} members. Matched groups are not touched.")
        for sid, student_name, _, course_code in rows:
            print(f"  {sid}  {student_name:<24} {course_code or 'no course'}")
        print(f"Stored under course {course_id} (required by the schema; matching ignores admin groups).")
        if not args.apply:
            print("\nDry run, nothing written. Re-run with --apply to make the change.")
            return

        group_id = make_admin_group(con, student_ids, args.name)
        write(con)
        print(f"\nCreated {group_id}. Each member's home page now links to its chat.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
