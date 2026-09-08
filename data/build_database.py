"""
StudyMatch — builds the actual sample database (SQLite) from sample/*.json.

Loads schema.sql into a fresh studymatch.db, then inserts every row from
sample/*.json, normalizing one list-valued field into a proper child table
along the way: availability.blocks -> availability_block.

Everything else is a straight column-for-column load. See schema.sql for the
full normalized schema and ER-relevant design notes.

Run:
    python build_database.py            # regenerates sample/*.json first, then builds studymatch.db
    python build_database.py --no-regen # builds studymatch.db from whatever's already in sample/
    python build_database.py --force    # rebuild even if studymatch.db has real (non-synthetic) people in it

This script is DESTRUCTIVE — it deletes studymatch.db and rebuilds it from
scratch every run. If you've added real students via add_student.py, running
this without --force will refuse rather than silently wipe them; see
add_student.py's docstring for the incremental (non-destructive) alternative.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
SAMPLE_DIR = HERE / "sample"
SCHEMA = HERE / "schema.sql"
DB_PATH = HERE / "studymatch.db"


def load(name):
    return json.loads((SAMPLE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def regenerate():
    print("Regenerating sample data (generate_sample_data.py)...", flush=True)
    subprocess.run([sys.executable, str(HERE / "generate_sample_data.py")], check=True, cwd=HERE)


def build(force=False):
    if DB_PATH.exists():
        if not force:
            probe = sqlite3.connect(DB_PATH)
            try:
                (real_count,) = probe.execute(
                    "SELECT COUNT(*) FROM student WHERE source != 'synthetic'"
                ).fetchone()
            except sqlite3.OperationalError:
                real_count = 0  # no student table / no source column yet - nothing to protect
            probe.close()
            if real_count:
                raise SystemExit(
                    f"Refusing to rebuild: studymatch.db has {real_count} real (non-synthetic) "
                    f"student row(s) that would be lost. Re-run with --force to rebuild anyway, "
                    f"or use add_student.py to add people without touching the rest of the DB."
                )
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    cur = con.cursor()

    university = load("university")
    courses = load("courses")
    students = load("students")
    course_membership = load("course_membership")
    personality = load("personality_profiles")
    archetypes = load("archetypes")
    availability = load("availability")
    academic = load("academic_profiles")
    pairwise = load("pairwise_compatibility")
    groups = load("groups")
    group_membership = load("group_membership")
    match_data = load("match_data")
    chat = load("course_chat_messages")
    feedback = load("group_feedback")

    # ── university / course ────────────────────────────────────────────
    cur.execute(
        "INSERT INTO university VALUES (?,?,?)",
        (university["university_id"], university["name"], university["location"]),
    )
    for c in courses:
        cur.execute(
            "INSERT INTO course VALUES (?,?,?,?,?,?)",
            (c["course_id"], c["university_id"], c["course_code"], c["course_title"], c["section"], c["semester"]),
        )

    # ── student (drop the redundant course/course_section - that's course_membership's job) ──
    looking_for_group_by_id = {}
    for s in students:
        cur.execute(
            "INSERT INTO student VALUES (?,?,?,?,?,?)",
            (s["student_id"], s["name"], s["year"], s["gender"], s["major"], "synthetic"),
        )
        looking_for_group_by_id[s["student_id"]] = s.get("looking_for_group", False)

    for m in course_membership:
        cur.execute(
            "INSERT INTO course_membership VALUES (?,?,?,?,?)",
            (
                m["student_id"], m["course_id"], m["section"], m["semester"],
                int(bool(looking_for_group_by_id.get(m["student_id"], False))),
            ),
        )

    # ── archetype ────────────────────────────────────────────────────────
    TRAITS = [
        "seriousness", "structure", "accountability", "social_preference",
        "communication_frequency", "competitiveness", "preparation",
        "leadership", "talkativeness", "assertiveness", "helpfulness",
        "collaboration", "study_pace", "patience",
    ]
    for a in archetypes:
        centroid = a["centroid_traits_1to5"]
        cur.execute(
            f"INSERT INTO archetype VALUES (?,?,?,?,{','.join('?' * len(TRAITS))})",
            (a["archetype_id"], a["name"], a["description"], a["member_count"], *[centroid[t] for t in TRAITS]),
        )

    # ── personality_profile ─────────────────────────────────────────────
    for p in personality:
        cur.execute(
            f"INSERT INTO personality_profile VALUES (?,?,{','.join('?' * len(TRAITS))},?,?)",
            (
                p["student_id"], p["course_id"], *[p[t] for t in TRAITS],
                p.get("archetype_id"), p.get("preferred_role"),
            ),
        )

    # ── availability / availability_block ───────────────────────────────
    for av in availability:
        cur.execute(
            "INSERT INTO availability VALUES (?,?,?,?,?,?,?)",
            (
                av["student_id"], av["course_id"], av["preferred_study_period"],
                av["preferred_session_duration"], av["preferred_sessions_per_week"],
                av["preferred_location"], av["online_vs_in_person_preference"],
            ),
        )
        for b in av["blocks"]:
            cur.execute(
                "INSERT INTO availability_block (student_id, course_id, day, start_time, end_time) VALUES (?,?,?,?,?)",
                (av["student_id"], av["course_id"], b["day"], b["start_time"], b["end_time"]),
            )

    # ── academic_profile ──────────────────────────────────────────────────
    for ac in academic:
        cur.execute(
            "INSERT INTO academic_profile VALUES (?,?,?,?)",
            (ac["student_id"], ac["course_id"], ac["course_confidence"], ac["target_grade"]),
        )

    # ── pairwise_compatibility ───────────────────────────────────────────
    course_by_student = {m["student_id"]: m["course_id"] for m in course_membership}
    for pw in pairwise:
        b = pw["breakdown"]
        cur.execute(
            "INSERT INTO pairwise_compatibility VALUES (?,?,?,?,?,?,?,?)",
            (
                pw["student_a"], pw["student_b"], course_by_student[pw["student_a"]],
                pw["compatibility_score"], b["similarity"],
                int(pw["schedule_compatible"]), pw["weekly_overlap_minutes"],
                b["study_style"],
            ),
        )

    # ── study_group / group_membership ──────────────────────────────────
    for g in groups:
        cur.execute(
            "INSERT INTO study_group VALUES (?,?,?,?,?,?,?,?,?)",
            (
                g["group_id"], g["course_id"], g["group_name"], g["max_members"], g["current_members"],
                g["created_at"], g["group_score"], g["avg_pairwise"], g["worst_pairwise"],
            ),
        )
    for gm in group_membership:
        cur.execute(
            "INSERT INTO group_membership VALUES (?,?,?,?)",
            (gm["group_id"], gm["student_id"], gm["joined_at"], gm["group_role"]),
        )

    # ── match_data ────────────────────────────────────────────────────────
    for md in match_data:
        cur.execute(
            "INSERT INTO match_data VALUES (?,?,?,?,?,?,?)",
            (
                md["match_id"], md["student_id"], md["recommended_group_id"], md["compatibility_score"],
                int(md["accepted"]), int(md["rejected"]), md["timestamp"],
            ),
        )

    # ── course_chat_message ─────────────────────────────────────────────
    for m in chat:
        cur.execute(
            "INSERT INTO course_chat_message VALUES (?,?,?,?,?,?,?)",
            (m["message_id"], m["course_id"], m["student_id"], m["type"], m["text"], m["upvotes"], m["timestamp"]),
        )

    # ── group_feedback ───────────────────────────────────────────────────
    for f in feedback:
        cur.execute(
            """INSERT INTO group_feedback
               (group_id, student_id, satisfaction_score, meetings_attended, meetings_per_week,
                weeks_in_group, left_group, would_match_again, perceived_personality_fit,
                group_productivity, group_chat_activity, peer_helpfulness_rating,
                peer_reliability_rating, timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                f["group_id"], f["student_id"], f["satisfaction_score"], f["meetings_attended"],
                f["meetings_per_week"], f["weeks_in_group"], int(f["left_group"]), int(f["would_match_again"]),
                f["perceived_personality_fit"], f["group_productivity"], f["group_chat_activity"],
                f["peer_helpfulness_rating"], f["peer_reliability_rating"], f["timestamp"],
            ),
        )

    con.commit()

    print(f"Wrote {DB_PATH} ({DB_PATH.stat().st_size / 1024:.0f} KB)")
    table_names = [row[0] for row in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()]
    for name in table_names:
        (n,) = cur.execute(f"SELECT COUNT(*) FROM {name}").fetchone()
        print(f"  {name:<26} {n} rows")
    con.close()


if __name__ == "__main__":
    if "--no-regen" not in sys.argv:
        regenerate()
    build(force="--force" in sys.argv)
