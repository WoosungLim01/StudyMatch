"""
StudyMatch — add a real student to studymatch.db WITHOUT touching anything
that already exists.

Unlike build_database.py (which deletes and rebuilds the whole database from
sample/*.json every run), this script only ever INSERTs. What it does for
each new student:

  1. Insert their raw data as given: student, course_membership,
     personality_profile, and availability/academic_profile if provided.
  2. Assign an archetype_id by nearest EXISTING centroid (matching_lib.
     nearest_archetype) — does NOT re-run KMeans, so no other student's
     archetype_id can change.
  3. Compute pairwise_compatibility against every other student already in
     the same course (matching_lib.pair_compatibility — the exact same
     formula generate_sample_data.py used).
  4. Rank existing under-capacity groups in their course by average
     compatibility with current members, and insert up to 3 match_data
     recruiting recommendations (accepted=False) — same as the "still
     looking for group" step in generate_sample_data.py.

It never touches study_group, group_membership, or any other student's row.
New students are tagged source='real' by default (see schema.sql) so they
stay distinguishable from — and safely coexist with — the synthetic ones.
Run build_database.py again later and it will refuse (see --force) rather
than silently wipe these.

Usage:
    python add_student.py new_students.json
    python add_student.py new_students.json --db studymatch.db

Input file shape — a list of student objects (see README.md for the full
field reference, or new_students.example.json in this folder for a working
example):

[
  {
    "student_id": "stu_1001",              // optional, auto-generated if omitted
    "name": "Jordan Lee",
    "year": "Sophomore", "gender": "Man", "major": "Computer Science",
    "course_id": "psu-cmpsc465-001-fa26",
    "section": "001", "semester": "Fall 2026",
    "looking_for_group": true,
    "source": "real",                       // optional, defaults to "real"
    "personality": { "seriousness": 4, "structure": 4, ... all 14 traits ... },
    "availability": {                       // optional
      "blocks": [{"day": "Mon", "start_time": "18:00", "end_time": "21:00"}],
      "preferred_study_period": "Evening", "preferred_session_duration": 90,
      "preferred_sessions_per_week": 2, "preferred_location": "Library",
      "online_vs_in_person_preference": "in_person"
    },
    "academic": { "course_confidence": 4, "target_grade": "A-" }  // optional
  }
]
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from matching_lib import TRAITS, pair_compatibility, preferred_role_for, nearest_archetype

HERE = Path(__file__).parent


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_student_id(cur):
    row = cur.execute(
        "SELECT student_id FROM student WHERE student_id LIKE 'stu\\_%' ESCAPE '\\' ORDER BY student_id DESC LIMIT 1"
    ).fetchone()
    n = int(row[0].split("_")[1]) + 1 if row else 1
    return f"stu_{n:04d}"


def next_match_id(cur):
    row = cur.execute("SELECT match_id FROM match_data ORDER BY match_id DESC LIMIT 1").fetchone()
    n = int(row[0].split("_")[1]) + 1 if row else 1
    return f"match_{n:04d}"


def add_one(con, s):
    cur = con.cursor()

    if not cur.execute("SELECT 1 FROM course WHERE course_id=?", (s["course_id"],)).fetchone():
        raise ValueError(f"Unknown course_id {s['course_id']!r} — check `course` table first.")

    missing = [t for t in TRAITS if t not in s["personality"]]
    if missing:
        raise ValueError(f"{s.get('name', '?')}: missing personality traits {missing}")

    sid = s.get("student_id") or next_student_id(cur)
    if cur.execute("SELECT 1 FROM student WHERE student_id=?", (sid,)).fetchone():
        raise ValueError(f"student_id {sid!r} already exists")

    source = s.get("source", "real")
    cur.execute(
        "INSERT INTO student VALUES (?,?,?,?,?,?)",
        (sid, s["name"], s.get("year"), s.get("gender"), s.get("major"), source),
    )
    cur.execute(
        "INSERT INTO course_membership VALUES (?,?,?,?,?)",
        (sid, s["course_id"], s.get("section"), s.get("semester"), int(bool(s.get("looking_for_group", True)))),
    )

    # ── personality + archetype (nearest existing centroid, no re-clustering) ──
    traits = {t: s["personality"][t] for t in TRAITS}
    archetypes = [
        {"archetype_id": row[0], "centroid_traits_1to5": {t: row[i + 1] for i, t in enumerate(TRAITS)}}
        for row in cur.execute(
            f"SELECT archetype_id, {','.join('c_' + t for t in TRAITS)} FROM archetype"
        ).fetchall()
    ]
    archetype_id = nearest_archetype(traits, archetypes) if archetypes else None
    preferred_role = s.get("preferred_role") or preferred_role_for(traits)
    cur.execute(
        f"INSERT INTO personality_profile VALUES (?,?,{','.join('?' * len(TRAITS))},?,?)",
        (sid, s["course_id"], *[traits[t] for t in TRAITS], archetype_id, preferred_role),
    )

    # ── availability (optional; defaults keep pair_compatibility computable) ──
    av = s.get("availability") or {}
    availability = {
        "blocks": av.get("blocks", []),
        "preferred_study_period": av.get("preferred_study_period", "Evening"),
        "preferred_session_duration": av.get("preferred_session_duration", 90),
        "preferred_sessions_per_week": av.get("preferred_sessions_per_week", 2),
        "preferred_location": av.get("preferred_location", "Library"),
        "online_vs_in_person_preference": av.get("online_vs_in_person_preference", "hybrid"),
    }
    cur.execute(
        "INSERT INTO availability VALUES (?,?,?,?,?,?,?)",
        (sid, s["course_id"], availability["preferred_study_period"], availability["preferred_session_duration"],
         availability["preferred_sessions_per_week"], availability["preferred_location"],
         availability["online_vs_in_person_preference"]),
    )
    for b in availability["blocks"]:
        cur.execute(
            "INSERT INTO availability_block (student_id, course_id, day, start_time, end_time) VALUES (?,?,?,?,?)",
            (sid, s["course_id"], b["day"], b["start_time"], b["end_time"]),
        )

    # ── academic profile (optional) ──────────────────────────────────────
    ac = s.get("academic") or {}
    cur.execute(
        "INSERT INTO academic_profile VALUES (?,?,?,?)",
        (sid, s["course_id"], ac.get("course_confidence"), ac.get("target_grade")),
    )

    # ── pairwise_compatibility against every existing student in this course ──
    coursemates = cur.execute(
        "SELECT student_id FROM course_membership WHERE course_id=? AND student_id != ?",
        (s["course_id"], sid),
    ).fetchall()
    new_scores = {}
    for (other_id,) in coursemates:
        other_traits = dict(zip(
            TRAITS,
            cur.execute(
                f"SELECT {','.join(TRAITS)} FROM personality_profile WHERE student_id=? AND course_id=?",
                (other_id, s["course_id"]),
            ).fetchone(),
        ))
        other_av_row = cur.execute(
            "SELECT preferred_session_duration, preferred_location, online_vs_in_person_preference "
            "FROM availability WHERE student_id=? AND course_id=?",
            (other_id, s["course_id"]),
        ).fetchone()
        other_av = {
            "preferred_session_duration": other_av_row[0], "preferred_location": other_av_row[1],
            "online_vs_in_person_preference": other_av_row[2],
            "blocks": [
                {"day": d, "start_time": st, "end_time": et}
                for d, st, et in cur.execute(
                    "SELECT day, start_time, end_time FROM availability_block WHERE student_id=? AND course_id=?",
                    (other_id, s["course_id"]),
                ).fetchall()
            ],
        }
        score, overlap, breakdown = pair_compatibility(traits, other_traits, availability, other_av)
        a, b = sorted((sid, other_id))
        cur.execute(
            "INSERT INTO pairwise_compatibility VALUES (?,?,?,?,?,?,?,?)",
            (a, b, s["course_id"], score, breakdown["similarity"], int(overlap > 0), overlap,
             breakdown["study_style"]),
        )
        new_scores[other_id] = score

    # ── recruiting recommendations into existing under-capacity groups ──────
    if s.get("looking_for_group", True):
        candidates = cur.execute(
            "SELECT group_id, max_members FROM study_group WHERE course_id=?", (s["course_id"],)
        ).fetchall()
        ranked = []
        for gid, max_members in candidates:
            members = [r[0] for r in cur.execute(
                "SELECT student_id FROM group_membership WHERE group_id=?", (gid,)
            ).fetchall()]
            if len(members) >= max_members:
                continue
            avg = mean(new_scores[m] for m in members if m in new_scores)
            ranked.append((gid, round(avg, 1)))
        ranked.sort(key=lambda x: -x[1])
        for gid, score in ranked[:3]:
            cur.execute(
                "INSERT INTO match_data VALUES (?,?,?,?,?,?,?)",
                (next_match_id(cur), sid, gid, score, 0, 0, now_iso()),
            )

    return sid


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit("Usage: python add_student.py new_students.json [--db studymatch.db]")
    input_path = Path(args[0])
    db_path = HERE / "studymatch.db"
    if "--db" in sys.argv:
        db_path = Path(sys.argv[sys.argv.index("--db") + 1])

    payload = json.loads(input_path.read_text(encoding="utf-8"))
    students = payload if isinstance(payload, list) else payload.get("students", [payload])

    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        added = [add_one(con, s) for s in students]
    except Exception:
        con.rollback()
        raise
    con.commit()
    con.close()

    print(f"Added {len(added)} student(s) to {db_path.name}: {', '.join(added)}")


if __name__ == "__main__":
    main()
