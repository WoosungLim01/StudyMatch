"""
StudyMatch — put a hand-picked set of students into one study group, e.g. a
test group for trying out group chat.

Each student is taken out of whatever group they're in now (that group's
scores are recomputed, or it's deleted if it ends up empty, same as an admin
delete), then all of them join one new group. All students must be in the
same course, because a group belongs to one course and matching only looks
at a student's own course. At most 5 students (a full group, so the matcher
never adds anyone else to it).

Runs against whatever data/db.py connects to: the local data/studymatch.db,
or the live Turso database when TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are
set. Without --apply it only prints what it would do.

Usage (from the repo root):
    python data/make_group.py 0037 0045 0041 0039 0044
    python data/make_group.py 0037 0045 0041 0039 0044 --apply
    python data/make_group.py stu_0037 stu_0045 --name "Admin Test Group" --apply
"""

import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from algorithm.grouping import GROUP_MAX
from algorithm.placement import _insert_group, _pair_score_fn, recompute_or_delete_group
from data.db import connect, write
from data.migrations import migrate

DEFAULT_NAME = "Admin Test Group"


def normalize_id(raw):
    raw = raw.strip()
    return f"stu_{raw}" if raw.isdigit() else raw


def plan_group(cur, student_ids):
    """-> (course_id, {student_id: (name, [current group ids])}), or raises ValueError."""
    if not student_ids:
        raise ValueError("Give at least one student id.")
    if len(set(student_ids)) != len(student_ids):
        raise ValueError("A student id is listed twice.")
    if len(student_ids) > GROUP_MAX:
        raise ValueError(f"A group holds at most {GROUP_MAX} students; got {len(student_ids)}.")

    students, courses, problems = {}, {}, []
    for sid in student_ids:
        row = cur.execute("SELECT name FROM student WHERE student_id=?", (sid,)).fetchone()
        if row is None:
            problems.append(f"{sid}: no such student")
            continue
        enrolled = [r[0] for r in cur.execute(
            "SELECT course_id FROM course_membership WHERE student_id=?", (sid,)
        ).fetchall()]
        if len(enrolled) != 1:
            problems.append(f"{sid} ({row[0]}): enrolled in {len(enrolled)} courses, expected 1")
            continue
        groups = [r[0] for r in cur.execute(
            """SELECT gm.group_id FROM group_membership gm
               JOIN study_group sg ON sg.group_id = gm.group_id
               WHERE gm.student_id=? AND sg.course_id=?""",
            (sid, enrolled[0]),
        ).fetchall()]
        students[sid] = (row[0], groups)
        courses[sid] = enrolled[0]
    if problems:
        raise ValueError("; ".join(problems))
    if len(set(courses.values())) > 1:
        detail = ", ".join(f"{sid} -> {cid}" for sid, cid in courses.items())
        raise ValueError(f"Students are in different courses ({detail}). A group belongs to one course.")
    return next(iter(courses.values())), students


def make_group(con, student_ids, name=DEFAULT_NAME, now_iso=None):
    """Moves the students into one new group. Returns (group_id, touched old group ids)."""
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cur = con.cursor()
    course_id, students = plan_group(cur, student_ids)
    old_groups = sorted({g for _, groups in students.values() for g in groups})

    for sid, (_, groups) in students.items():
        for gid in groups:
            cur.execute("DELETE FROM match_data WHERE student_id=? AND recommended_group_id=?", (sid, gid))
            cur.execute("DELETE FROM group_membership WHERE student_id=? AND group_id=?", (sid, gid))
    for gid in old_groups:
        recompute_or_delete_group(cur, gid, course_id)

    pair_score = _pair_score_fn(cur, course_id)
    group_id = _insert_group(cur, course_id, list(student_ids), pair_score, now_iso, name=name)
    return group_id, old_groups


def main():
    parser = argparse.ArgumentParser(description="Put the given students into one new study group.")
    parser.add_argument("students", nargs="+", help="student ids, e.g. 0037 or stu_0037")
    parser.add_argument("--name", default=DEFAULT_NAME, help=f"group name (default: {DEFAULT_NAME!r})")
    parser.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    args = parser.parse_args()
    student_ids = [normalize_id(s) for s in args.students]

    con = connect()
    try:
        cur = con.cursor()
        try:
            course_id, students = plan_group(cur, student_ids)
        except ValueError as e:
            raise SystemExit(f"Not changed: {e}")

        leaving = Counter(g for _, groups in students.values() for g in groups)
        if len(leaving) == 1:
            (gid, n), = leaving.items()
            size = cur.execute("SELECT current_members FROM study_group WHERE group_id=?", (gid,)).fetchone()[0]
            if n == len(students) == size:
                raise SystemExit(f"Not changed: these students already make up {gid} on their own.")

        print(f"Course: {course_id}")
        print(f"New group: {args.name!r} with {len(students)} members")
        for sid, (student_name, groups) in students.items():
            where = ", ".join(groups) if groups else "no group (pending)"
            print(f"  {sid}  {student_name:<24} leaves {where}")
        print("Groups they leave:" if leaving else "")
        for gid, n in sorted(leaving.items()):
            size = cur.execute("SELECT current_members FROM study_group WHERE group_id=?", (gid,)).fetchone()[0]
            print(f"  {gid}: {size} -> {size - n} members" if size > n
                  else f"  {gid}: deleted, along with its chat history")
        if not args.apply:
            print("\nDry run, nothing written. Re-run with --apply to make the change.")
            return

        migrate(con)
        group_id, old_groups = make_group(con, student_ids, args.name)
        write(con)
        print(f"\nCreated {group_id}.")
        for gid in old_groups:
            row = cur.execute("SELECT current_members FROM study_group WHERE group_id=?", (gid,)).fetchone()
            print(f"  {gid}: " + (f"now {row[0]} members" if row else "deleted (no members left)"))
    finally:
        con.close()


if __name__ == "__main__":
    main()
