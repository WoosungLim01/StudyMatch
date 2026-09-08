"""
StudyMatch — the actual intake survey + admin backend, operating directly on
studymatch.db (no separate app database, no mock data).

Two pages:
  GET  /survey  -> entry survey (personality + basic info); on submit, the
                    respondent is inserted as a REAL student (source='real'),
                    scored against their course-mates (matching_lib.py, same
                    formula as everything else), and immediately placed into
                    a group per the remainder policy in group_placement.py -
                    they always get an answer (a group, or "pending" if truly
                    no room), never blocked on match quality.
  GET  /admin    -> lists every student (fake and real) with a delete button.
                    Deleting removes them everywhere (personality, pairwise
                    scores, group membership, chat, feedback, ...) - fake
                    people can be deleted too, same mechanism.

Once someone is signed in via the survey, they're permanent - only an admin
delete removes them. build_database.py's destructive rebuild already refuses
to run over real (source='real') rows.

Run:
    python webapp.py
    # -> open http://localhost:8010/survey  and  http://localhost:8010/admin
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from add_student import add_one
from group_placement import NOT_IDEAL_THRESHOLD, recompute_or_delete_group, run_placement
from matching_lib import TRAITS

HERE = Path(__file__).parent
DB_PATH = HERE / "studymatch.db"

app = FastAPI(title="StudyMatch Intake")


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────
#  Pages
# ─────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/survey")


@app.get("/survey", response_class=HTMLResponse, include_in_schema=False)
def survey_page():
    return FileResponse(HERE / "survey.html")


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    return FileResponse(HERE / "admin.html")


# ─────────────────────────────────────────────────────────────
#  Survey
# ─────────────────────────────────────────────────────────────

class AvailabilityIn(BaseModel):
    blocks: list = Field(default_factory=list)
    preferred_study_period: Optional[str] = None
    preferred_session_duration: Optional[int] = None
    preferred_sessions_per_week: Optional[int] = None
    preferred_location: Optional[str] = None
    online_vs_in_person_preference: Optional[str] = None


class AcademicIn(BaseModel):
    course_confidence: Optional[int] = None
    target_grade: Optional[str] = None


class SurveyIn(BaseModel):
    name: str
    year: Optional[str] = None
    gender: Optional[str] = None
    major: Optional[str] = None
    course_id: str
    personality: Dict[str, int]
    availability: Optional[AvailabilityIn] = None
    academic: Optional[AcademicIn] = None


@app.get("/api/courses")
def api_courses():
    con = db()
    rows = con.execute("SELECT course_id, course_code, course_title FROM course").fetchall()
    con.close()
    return [{"course_id": r[0], "course_code": r[1], "course_title": r[2]} for r in rows]


@app.get("/api/survey/traits")
def api_traits():
    """Trait list for the survey form to render sliders from — one source of truth."""
    return {"traits": TRAITS}


@app.post("/api/survey")
def api_survey(body: SurveyIn):
    missing = [t for t in TRAITS if t not in body.personality]
    if missing:
        raise HTTPException(400, f"Missing personality traits: {missing}")

    s = {
        "name": body.name, "year": body.year, "gender": body.gender, "major": body.major,
        "course_id": body.course_id, "looking_for_group": True, "source": "real",
        "personality": body.personality,
    }
    # exclude_none: unset optional fields must be ABSENT, not present-with-None -
    # add_student.py's dict.get(key, default) only falls back on a missing key.
    if body.availability:
        s["availability"] = body.availability.model_dump(exclude_none=True)
    if body.academic:
        s["academic"] = body.academic.model_dump(exclude_none=True)

    con = db()
    if not con.execute("SELECT 1 FROM course WHERE course_id=?", (body.course_id,)).fetchone():
        con.close()
        raise HTTPException(400, f"Unknown course_id {body.course_id!r}")

    try:
        sid = add_one(con, s, recommend=False)
        outcomes = run_placement(con, body.course_id, now_iso())
        con.commit()
    except Exception as e:
        con.rollback()
        con.close()
        raise HTTPException(500, str(e))

    outcome = outcomes.get(sid)
    if outcome is None:
        con.close()
        return {
            "student_id": sid, "status": "pending", "not_ideal": False,
            "message": "You're signed in! No group had room right now — "
                       "you'll be matched as more students join.",
        }

    group_id = outcome["group_id"]
    group_name = con.execute("SELECT group_name FROM study_group WHERE group_id=?", (group_id,)).fetchone()[0]
    con.close()

    score = outcome["member_avg_score"]
    not_ideal = score < NOT_IDEAL_THRESHOLD
    if not_ideal:
        message = (
            f"You're signed in! Heads up — your best available match ({group_name}, "
            f"compatibility {score}) isn't a great fit, but we've added you to the "
            f"group anyway so you're not left out."
        )
    else:
        message = f"You're signed in and matched into {group_name} (compatibility {score})."

    return {
        "student_id": sid, "status": "grouped", "group_id": group_id, "group_name": group_name,
        "score": score, "not_ideal": not_ideal, "message": message,
    }


# ─────────────────────────────────────────────────────────────
#  Admin
# ─────────────────────────────────────────────────────────────

@app.get("/api/admin/students")
def api_admin_students():
    con = db()
    rows = con.execute("""
        SELECT s.student_id, s.name, s.year, s.gender, s.major, s.source,
               c.course_code, pp.archetype_id, a.name AS archetype_name,
               gm.group_id, sg.group_name
        FROM student s
        JOIN course_membership cm ON cm.student_id = s.student_id
        JOIN course c ON c.course_id = cm.course_id
        LEFT JOIN personality_profile pp ON pp.student_id = s.student_id AND pp.course_id = cm.course_id
        LEFT JOIN archetype a ON a.archetype_id = pp.archetype_id
        LEFT JOIN group_membership gm ON gm.student_id = s.student_id
        LEFT JOIN study_group sg ON sg.group_id = gm.group_id AND sg.course_id = cm.course_id
        ORDER BY s.source DESC, c.course_code, s.name
    """).fetchall()
    con.close()
    cols = ["student_id", "name", "year", "gender", "major", "source", "course_code",
            "archetype_id", "archetype_name", "group_id", "group_name"]
    return [dict(zip(cols, r)) for r in rows]


@app.delete("/api/admin/students/{student_id}")
def api_admin_delete_student(student_id: str):
    con = db()
    if not con.execute("SELECT 1 FROM student WHERE student_id=?", (student_id,)).fetchone():
        con.close()
        raise HTTPException(404, "Student not found")

    cur = con.cursor()
    affected = [(r[0], r[1]) for r in cur.execute(
        """SELECT gm.group_id, sg.course_id FROM group_membership gm
           JOIN study_group sg ON sg.group_id = gm.group_id WHERE gm.student_id=?""",
        (student_id,),
    ).fetchall()]

    cur.execute("DELETE FROM group_feedback WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM match_data WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM group_membership WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM course_chat_message WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM pairwise_compatibility WHERE student_a=? OR student_b=?", (student_id, student_id))
    cur.execute("DELETE FROM academic_profile WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM availability_block WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM availability WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM personality_profile WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM course_membership WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM student WHERE student_id=?", (student_id,))

    for group_id, course_id in affected:
        recompute_or_delete_group(cur, group_id, course_id)

    con.commit()
    con.close()
    return {"deleted": student_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webapp:app", host="0.0.0.0", port=8010, reload=True)
