"""
StudyMatch — the whole app's entry point: login/signup, the intake survey,
the home page, and the admin backend, all operating directly on
data/studymatch.db (no separate app database, no mock data). Ties the three
other parts of the project together:
  ui/        - login/survey/home/admin pages, served straight off disk
  data/      - studymatch.db, add_student.py's insert logic, auth.py's hashing
  algorithm/ - compatibility.py (pair scores), grouping.py (ILP groups),
               placement.py (live remainder policy), clustering.py (GMM archetypes)

Pages:
  GET  /login   -> combined login/signup: one email+password form. Unknown
                    email creates an account; known email checks the
                    password (wrong password is rejected, never silently
                    treated as a new signup).
  GET  /survey  -> entry survey (personality + basic info), gated to a
                    logged-in user who hasn't completed it yet - one-time per
                    account. On submit, the respondent is inserted as a REAL
                    student (source='real'), scored against their
                    course-mates (algorithm/compatibility.py, same formula as
                    everything else), immediately placed into a group by
                    algorithm/placement.py (ILP for a new group, else the
                    best-fitting existing group with room; never
                    blocked on match quality), and their account is linked to
                    the new student_id so they never see the survey again.
  GET  /home    -> gated to a logged-in user who HAS completed the survey:
                    their group, its members, and their course.
  GET  /admin   -> lists every student (fake and real) AND every login
                    account, each with a delete button. Deleting a student
                    removes them everywhere (personality, pairwise scores,
                    group membership, chat, feedback, ...) and un-links any
                    account pointing at them; fake people can be deleted too,
                    same mechanism. Deleting an account only removes login
                    access, not their student/survey data.

Once someone is signed in via the survey, they're permanent - only an admin
delete removes them. data/build_database.py's destructive rebuild already
refuses to run over real (source='real') students or any login account.

Run (from the repo root):
    python app.py
    # -> open http://localhost:8010/login
"""

import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from algorithm.clustering import classify, family_scores, motivation_badge
from algorithm.placement import NOT_IDEAL_THRESHOLD, recompute_or_delete_group, run_placement
from algorithm.scoring import AXES, SURVEY_ITEMS
from data.add_student import add_one
from data.archetype_store import load_model
from data.auth import hash_password, verify_password

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "studymatch.db"
UI_DIR = ROOT / "ui"
SESSION_COOKIE = "session_token"

app = FastAPI(title="StudyMatch")


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────────────────────
#  Auth helpers
# ─────────────────────────────────────────────────────────────

def next_user_id(cur):
    row = cur.execute("SELECT user_id FROM user_account ORDER BY user_id DESC LIMIT 1").fetchone()
    n = int(row[0].split("_")[1]) + 1 if row else 1
    return f"usr_{n:04d}"


def current_user(request: Request):
    """Returns {"user_id", "email", "student_id"} for a valid session cookie, else None."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    con = db()
    row = con.execute(
        """SELECT u.user_id, u.email, u.student_id FROM session s
           JOIN user_account u ON u.user_id = s.user_id WHERE s.session_token = ?""",
        (token,),
    ).fetchone()
    con.close()
    if row is None:
        return None
    return {"user_id": row[0], "email": row[1], "student_id": row[2]}


def require_user(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(401, "Not logged in")
    return user


# ─────────────────────────────────────────────────────────────
#  Pages
# ─────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login")
    return RedirectResponse("/survey" if user["student_id"] is None else "/home")


@app.get("/login", response_class=HTMLResponse, include_in_schema=False)
def login_page(request: Request):
    user = current_user(request)
    if user is not None:
        return RedirectResponse("/survey" if user["student_id"] is None else "/home")
    return FileResponse(UI_DIR / "login.html")


@app.get("/survey", response_class=HTMLResponse, include_in_schema=False)
def survey_page(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login")
    if user["student_id"] is not None:
        return RedirectResponse("/home")
    return FileResponse(UI_DIR / "survey.html")


@app.get("/home", response_class=HTMLResponse, include_in_schema=False)
def home_page(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login")
    if user["student_id"] is None:
        return RedirectResponse("/survey")
    return FileResponse(UI_DIR / "home.html")


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    return FileResponse(UI_DIR / "admin.html")



# ─────────────────────────────────────────────────────────────
#  Auth API
# ─────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def api_login(body: LoginIn, response: Response):
    email = body.email.strip()
    if not email or not body.password:
        raise HTTPException(400, "Email and password are both required.")

    con = db()
    cur = con.cursor()
    row = cur.execute(
        "SELECT user_id, password_hash, student_id FROM user_account WHERE email = ?", (email,)
    ).fetchone()

    if row is None:
        # Unknown email -> sign up.
        user_id = next_user_id(cur)
        cur.execute(
            "INSERT INTO user_account VALUES (?,?,?,?,?)",
            (user_id, email, hash_password(body.password), now_iso(), None),
        )
        student_id = None
        is_new_account = True
    else:
        user_id, password_hash, student_id = row
        if not verify_password(body.password, password_hash):
            con.close()
            raise HTTPException(401, "Incorrect password for this email.")
        is_new_account = False

    token = secrets.token_urlsafe(32)
    cur.execute("INSERT INTO session VALUES (?,?,?)", (token, user_id, now_iso()))
    con.commit()
    con.close()

    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"is_new_account": is_new_account, "redirect": "/survey" if student_id is None else "/home"}


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        con = db()
        con.execute("DELETE FROM session WHERE session_token = ?", (token,))
        con.commit()
        con.close()
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def api_me(request: Request):
    return require_user(request)


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
    responses: Dict[int, int]   # item id (1-24) -> raw 1-5 Likert answer
    availability: Optional[AvailabilityIn] = None
    academic: Optional[AcademicIn] = None


@app.get("/api/courses")
def api_courses():
    con = db()
    rows = con.execute("SELECT course_id, course_code, course_title FROM course").fetchall()
    con.close()
    return [{"course_id": r[0], "course_code": r[1], "course_title": r[2]} for r in rows]


@app.get("/api/survey/items")
def api_survey_items():
    """24-item Likert survey bank for the survey form to render from — one source of truth."""
    return {"items": SURVEY_ITEMS}


@app.post("/api/survey")
def api_survey(body: SurveyIn, request: Request):
    user = require_user(request)
    if user["student_id"] is not None:
        raise HTTPException(400, "You've already completed the survey — it's one-time per account.")

    missing = [it["id"] for it in SURVEY_ITEMS if it["id"] not in body.responses]
    if missing:
        raise HTTPException(400, f"Missing survey responses for item(s): {missing}")
    out_of_range = sorted(i for i, v in body.responses.items() if not (1 <= v <= 5))
    if out_of_range:
        raise HTTPException(400, f"Survey responses must be 1-5: item(s) {out_of_range}")

    s = {
        "name": body.name, "year": body.year, "gender": body.gender, "major": body.major,
        "course_id": body.course_id, "looking_for_group": True, "source": "real",
        "survey_responses": body.responses,
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
        con.execute("UPDATE user_account SET student_id = ? WHERE user_id = ?", (sid, user["user_id"]))
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
#  Home
# ─────────────────────────────────────────────────────────────

@app.get("/api/home")
def api_home(request: Request):
    user = require_user(request)
    sid = user["student_id"]
    if sid is None:
        raise HTTPException(400, "Survey not completed yet.")

    con = db()
    name = con.execute("SELECT name FROM student WHERE student_id = ?", (sid,)).fetchone()[0]
    course = con.execute(
        """SELECT c.course_code, c.course_title FROM course_membership cm
           JOIN course c ON c.course_id = cm.course_id WHERE cm.student_id = ?""",
        (sid,),
    ).fetchone()

    group = con.execute(
        """SELECT sg.group_id, sg.group_name, sg.group_score FROM group_membership gm
           JOIN study_group sg ON sg.group_id = gm.group_id WHERE gm.student_id = ?""",
        (sid,),
    ).fetchone()

    result = {
        "name": name,
        "email": user["email"],
        "course_code": course[0] if course else None,
        "course_title": course[1] if course else None,
    }

    if group:
        group_id, group_name, group_score = group
        members = [r[0] for r in con.execute(
            """SELECT s.name FROM group_membership gm JOIN student s ON s.student_id = gm.student_id
               WHERE gm.group_id = ? AND gm.student_id != ? ORDER BY s.name""",
            (group_id, sid),
        ).fetchall()]
        result.update({"status": "grouped", "group_name": group_name, "group_score": group_score, "members": members})
    else:
        result["status"] = "pending"

    con.close()
    return result


# ─────────────────────────────────────────────────────────────
#  Admin
# ─────────────────────────────────────────────────────────────

@app.get("/api/admin/students")
def api_admin_students():
    con = db()
    rows = con.execute("""
        SELECT s.student_id, s.name, s.year, s.gender, s.major, s.source,
               c.course_code, pp.archetype_id, a.name AS archetype_name, pp.archetype_strength,
               pp.intensity, pp.response_flag, gm.group_id, sg.group_name
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
            "archetype_id", "archetype_name", "archetype_strength", "intensity", "response_flag",
            "group_id", "group_name"]
    out = []
    for r in rows:
        d = dict(zip(cols, r))
        intensity = d.pop("intensity")
        d["motivation_badge"] = motivation_badge(intensity) if intensity is not None else None
        out.append(d)
    return out


@app.get("/api/admin/type-map")
def api_admin_type_map():
    """
    Everything the study-type diagram needs: the stored type model (each
    type's mixture component over the 2 family scores) and every student's
    position + soft membership in that same space.
    """
    con = db()
    model = load_model(con.cursor())
    if model is None:
        con.close()
        raise HTTPException(503, "No study-type model stored yet - run data/refit_archetypes.py")
    counts = dict(con.execute("SELECT archetype_id, COUNT(*) FROM personality_profile GROUP BY archetype_id").fetchall())
    rows = con.execute(f"""
        SELECT s.student_id, s.name, s.source, c.course_code, {','.join('pp.' + a for a in AXES)},
               pp.response_flag, sg.group_name
        FROM personality_profile pp
        JOIN student s ON s.student_id = pp.student_id
        JOIN course c ON c.course_id = pp.course_id
        LEFT JOIN group_membership gm ON gm.student_id = s.student_id
        LEFT JOIN study_group sg ON sg.group_id = gm.group_id AND sg.course_id = pp.course_id
        ORDER BY s.source DESC, s.name
    """).fetchall()
    con.close()

    students = []
    for sid, name, source, course_code, *rest in rows:
        traits = dict(zip(AXES, rest[:len(AXES)]))
        flag, group_name = rest[len(AXES):]
        result = classify(traits, model)
        x, y = family_scores(traits)
        students.append({
            "student_id": sid, "name": name, "source": source, "course_code": course_code,
            "self_regulation": round(float(x), 3), "social": round(float(y), 3),
            "archetype_id": result["archetype_id"], "strength": result["strength"],
            "membership": result["membership"], "motivation_badge": result["badge"],
            "response_flag": flag, "group_name": group_name,
        })
    return {
        "model": {k: model.get(k) for k in ("source", "n_fit", "note", "fitted_at")},
        "types": [
            {"archetype_id": c["archetype_id"], "name": c["name"], "description": c["description"],
             "weight": c["weight"], "mean": c["mean"], "covariance": c["covariance"],
             "member_count": counts.get(c["archetype_id"], 0)}
            for c in model["components"]
        ],
        "students": students,
    }


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

    # Un-link any account pointing at this student - deleting the student
    # shouldn't leave a login account permanently stuck thinking it already
    # completed the survey with a student_id that no longer exists.
    cur.execute("UPDATE user_account SET student_id = NULL WHERE student_id=?", (student_id,))

    cur.execute("DELETE FROM group_feedback WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM match_data WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM group_membership WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM course_chat_message WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM pairwise_compatibility WHERE student_a=? OR student_b=?", (student_id, student_id))
    cur.execute("DELETE FROM academic_profile WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM availability_block WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM availability WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM survey_response WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM personality_profile WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM course_membership WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM student WHERE student_id=?", (student_id,))

    for group_id, course_id in affected:
        recompute_or_delete_group(cur, group_id, course_id)

    con.commit()
    con.close()
    return {"deleted": student_id}


@app.get("/api/admin/accounts")
def api_admin_accounts():
    con = db()
    rows = con.execute("""
        SELECT u.user_id, u.email, u.created_at, u.student_id, s.name
        FROM user_account u LEFT JOIN student s ON s.student_id = u.student_id
        ORDER BY u.created_at DESC
    """).fetchall()
    con.close()
    cols = ["user_id", "email", "created_at", "student_id", "student_name"]
    return [dict(zip(cols, r)) for r in rows]


@app.delete("/api/admin/accounts/{user_id}")
def api_admin_delete_account(user_id: str):
    """Removes login access only - does NOT touch their student/survey data,
    which (if any) stays exactly as it was, just no longer reachable via login."""
    con = db()
    if not con.execute("SELECT 1 FROM user_account WHERE user_id=?", (user_id,)).fetchone():
        con.close()
        raise HTTPException(404, "Account not found")
    con.execute("DELETE FROM session WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM user_account WHERE user_id=?", (user_id,))
    con.commit()
    con.close()
    return {"deleted": user_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8010, reload=True)
