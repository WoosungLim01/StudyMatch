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
  GET  /login   -> combined login/signup, two methods:
                    - email+password: unknown email creates an account but
                      does NOT log in yet - a 6-digit code is emailed
                      (data/email.py) and entered on the same page, with the
                      password, via POST /api/auth/verify-code. Known email checks
                      the password (wrong password rejected, never silently
                      treated as a new signup; a Google-only account's NULL
                      password_hash is rejected the same clear way).
                    - Google sign-in (GET /api/auth/google/login ->
                      consent screen -> /api/auth/google/callback):
                      auto-verified (Google already confirmed the email),
                      matched/linked to an existing account by email if one
                      exists. Both methods create the same session row.
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
  GET  /account -> same gating as /home. Edit your display name, log out,
                    or delete your own account (DELETE /api/account - removes
                    your student/survey data AND login access in one action,
                    unlike the two separate admin delete endpoints below;
                    sends a confirmation email either way).
  GET  /admin   -> lists every student (fake and real) AND every login
                    account, each with a delete button. Deleting a student
                    removes them everywhere (personality, pairwise scores,
                    group membership, chat, feedback, ...) and un-links any
                    account pointing at them; fake people can be deleted too,
                    same mechanism. Deleting an account only removes login
                    access, not their student/survey data. Both send the
                    affected person a notification email if they have one.

Once someone is signed in via the survey, they're permanent - only an admin
delete (or their own self-service delete) removes them. data/build_database.py's
destructive rebuild already refuses to run over real (source='real')
students or any login account.

Run (from the repo root):
    python app.py
    # -> open http://localhost:8010/login
"""

import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
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
from data.db import connect as db
from data.db import write as db_write
from data.email import send_account_deleted_email, send_verification_code

ROOT = Path(__file__).parent
UI_DIR = ROOT / "ui"
SESSION_COOKIE = "session_token"
SESSION_TTL = timedelta(days=30)

# Google sign-in - unset until GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI are
# configured (Google Cloud Console credentials, set as env vars, never
# committed - same pattern as TURSO_DATABASE_URL/TURSO_AUTH_TOKEN).
# /api/auth/google/login 501s with a clear message until all three are set.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")
OAUTH_STATE_COOKIE = "google_oauth_state"

app = FastAPI(title="StudyMatch")


def now_iso(offset=timedelta(0)):
    return (datetime.now(timezone.utc) + offset).strftime("%Y-%m-%dT%H:%M:%SZ")


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
           JOIN user_account u ON u.user_id = s.user_id
           WHERE s.session_token = ? AND s.expires_at > ?""",
        (token, now_iso()),
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


@app.get("/account", response_class=HTMLResponse, include_in_schema=False)
def account_page(request: Request):
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login")
    if user["student_id"] is None:
        return RedirectResponse("/survey")
    return FileResponse(UI_DIR / "account.html")


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    return FileResponse(UI_DIR / "admin.html")



# ─────────────────────────────────────────────────────────────
#  Auth API
# ─────────────────────────────────────────────────────────────

class LoginIn(BaseModel):
    email: str
    password: str


def _create_session(cur, user_id):
    """Shared by password login and Google sign-in - same session row either way."""
    token = secrets.token_urlsafe(32)
    cur.execute("DELETE FROM session WHERE expires_at <= ?", (now_iso(),))
    cur.execute("INSERT INTO session VALUES (?,?,?,?)", (token, user_id, now_iso(), now_iso(SESSION_TTL)))
    return token


def _set_session_cookie(response, token):
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                         max_age=int(SESSION_TTL.total_seconds()))


CODE_SENT_MESSAGE = "We emailed you a 6-digit code. Enter it below to finish signing up."
CODE_MAX_WRONG_ATTEMPTS = 5
_wrong_code_attempts: Dict[str, int] = {}


def _new_verify_code():
    return f"{secrets.randbelow(10**6):06d}"


class VerifyCodeIn(BaseModel):
    email: str
    password: str
    code: str


@app.post("/api/auth/login")
def api_login(body: LoginIn, response: Response):
    email = body.email.strip()
    if not email or not body.password:
        raise HTTPException(400, "Email and password are both required.")

    con = db()
    cur = con.cursor()
    row = cur.execute(
        "SELECT user_id, password_hash, student_id, verified_at FROM user_account WHERE email = ?", (email,)
    ).fetchone()

    if row is None:
        user_id = next_user_id(cur)
        code = _new_verify_code()
        cur.execute(
            "INSERT INTO user_account VALUES (?,?,?,?,?,?,?,?)",
            (user_id, email, hash_password(body.password), None, now_iso(), None, None, code),
        )
        db_write(con)
        con.close()
        _wrong_code_attempts.pop(email, None)
        send_verification_code(email, code)
        return {"status": "code_sent", "message": CODE_SENT_MESSAGE}

    user_id, password_hash, student_id, verified_at = row
    if password_hash is None:
        con.close()
        raise HTTPException(401, "This email uses Google sign-in - use the Google button instead.")
    if not verify_password(body.password, password_hash):
        con.close()
        raise HTTPException(401, "Incorrect password for this email.")
    if verified_at is None:
        code = _new_verify_code()
        cur.execute("UPDATE user_account SET verify_token = ? WHERE user_id = ?", (code, user_id))
        db_write(con)
        con.close()
        _wrong_code_attempts.pop(email, None)
        send_verification_code(email, code)
        return {"status": "code_sent", "message": CODE_SENT_MESSAGE}

    token = _create_session(cur, user_id)
    db_write(con)
    con.close()

    _set_session_cookie(response, token)
    return {"is_new_account": False, "redirect": "/survey" if student_id is None else "/home"}


@app.post("/api/auth/verify-code")
def api_verify_code(body: VerifyCodeIn, response: Response):
    email = body.email.strip()
    con = db()
    cur = con.cursor()
    row = cur.execute(
        "SELECT user_id, password_hash, student_id, verify_token FROM user_account "
        "WHERE email = ? AND verified_at IS NULL",
        (email,),
    ).fetchone()
    if row is None or row[1] is None or not verify_password(body.password, row[1]):
        con.close()
        raise HTTPException(401, "Incorrect email or password.")

    user_id, _, student_id, stored_code = row
    if _wrong_code_attempts.get(email, 0) >= CODE_MAX_WRONG_ATTEMPTS:
        con.close()
        raise HTTPException(429, "Too many wrong codes. Log in again to get a new one.")
    if stored_code is None or body.code.strip() != stored_code:
        _wrong_code_attempts[email] = _wrong_code_attempts.get(email, 0) + 1
        con.close()
        raise HTTPException(400, "That code isn't right. Check the email and try again.")

    _wrong_code_attempts.pop(email, None)
    cur.execute("UPDATE user_account SET verified_at = ?, verify_token = NULL WHERE user_id = ?", (now_iso(), user_id))
    token = _create_session(cur, user_id)
    db_write(con)
    con.close()

    _set_session_cookie(response, token)
    return {"redirect": "/survey" if student_id is None else "/home"}


@app.get("/api/auth/google/login", include_in_schema=False)
def api_google_login():
    if not (GOOGLE_CLIENT_ID and GOOGLE_REDIRECT_URI):
        raise HTTPException(501, "Google sign-in isn't configured yet.")
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    redirect = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params))
    redirect.set_cookie(OAUTH_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600)
    return redirect


@app.get("/api/auth/google/callback", include_in_schema=False)
def api_google_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None,
                         error: Optional[str] = None):
    def failure(message):
        return RedirectResponse("/login?error=" + urllib.parse.quote(message))

    if error:
        return failure("Google sign-in was cancelled.")
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not code or not state or not cookie_state or state != cookie_state:
        return failure("Google sign-in failed - please try again.")

    token_body = urllib.parse.urlencode({
        "code": code, "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
    }).encode()
    try:
        with urllib.request.urlopen(
            urllib.request.Request("https://oauth2.googleapis.com/token", data=token_body, method="POST"),
            timeout=10,
        ) as resp:
            access_token = json.loads(resp.read()).get("access_token")
        if not access_token:
            raise ValueError("no access_token in Google's response")
        with urllib.request.urlopen(
            urllib.request.Request(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            ),
            timeout=10,
        ) as resp:
            info = json.loads(resp.read())
    except (urllib.error.URLError, ValueError):
        return failure("Could not reach Google - please try again.")

    if not info.get("email_verified"):
        return failure("Your Google email is not verified.")
    email = info["email"].strip()
    google_sub = info["sub"]

    con = db()
    cur = con.cursor()
    row = cur.execute(
        "SELECT user_id, student_id FROM user_account WHERE email = ? OR google_sub = ?", (email, google_sub)
    ).fetchone()
    if row is None:
        # Google already confirmed this email (checked above via
        # email_verified) - auto-verified, no separate email needed.
        user_id = next_user_id(cur)
        cur.execute(
            "INSERT INTO user_account VALUES (?,?,?,?,?,?,?,?)",
            (user_id, email, None, google_sub, now_iso(), None, now_iso(), None),
        )
        student_id = None
    else:
        # Covers both a returning Google user and a password account signing
        # in with Google for the first time under the same email - either
        # way it's one person, one account, matched by email. Signing in
        # with Google also verifies the account if it wasn't already
        # (Google re-proves ownership of the email regardless of how the
        # account started).
        user_id, student_id = row
        cur.execute(
            "UPDATE user_account SET google_sub = ?, verified_at = COALESCE(verified_at, ?), verify_token = NULL "
            "WHERE user_id = ?",
            (google_sub, now_iso(), user_id),
        )

    token = _create_session(cur, user_id)
    db_write(con)
    con.close()

    redirect = RedirectResponse("/survey" if student_id is None else "/home")
    redirect.delete_cookie(OAUTH_STATE_COOKIE)
    _set_session_cookie(redirect, token)
    return redirect


@app.post("/api/auth/logout")
def api_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        con = db()
        con.execute("DELETE FROM session WHERE session_token = ?", (token,))
        db_write(con)
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
        db_write(con)
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
#  Account
# ─────────────────────────────────────────────────────────────

class AccountIn(BaseModel):
    name: str


@app.get("/api/account")
def api_account(request: Request):
    user = require_user(request)
    if user["student_id"] is None:
        raise HTTPException(400, "Survey not completed yet.")
    con = db()
    name = con.execute("SELECT name FROM student WHERE student_id = ?", (user["student_id"],)).fetchone()[0]
    con.close()
    return {"name": name, "email": user["email"]}


@app.post("/api/account")
def api_account_update(body: AccountIn, request: Request):
    user = require_user(request)
    if user["student_id"] is None:
        raise HTTPException(400, "Survey not completed yet.")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Name cannot be empty.")
    con = db()
    con.execute("UPDATE student SET name = ? WHERE student_id = ?", (name, user["student_id"]))
    db_write(con)
    con.close()
    return {"name": name}


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


def _delete_student_cascade(cur, student_id):
    """Removes a student and everywhere they're referenced (personality,
    pairwise scores, group membership, chat, feedback, ...), recomputing any
    group they were in. Shared by the admin delete and self-service account
    deletion - un-linking user_account is the one caller's job, not this
    helper's, since the two callers want different follow-up behavior."""
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
    cur.execute("DELETE FROM survey_response WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM personality_profile WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM course_membership WHERE student_id=?", (student_id,))
    cur.execute("DELETE FROM student WHERE student_id=?", (student_id,))
    for group_id, course_id in affected:
        recompute_or_delete_group(cur, group_id, course_id)


@app.delete("/api/account")
def api_account_delete(request: Request, response: Response):
    """Self-service: a logged-in user deletes their own account AND their
    student/survey data (if any) in one action, unlike the admin endpoints
    below which separate the two. Sends a confirmation email and clears the
    session so the response is also effectively a logout."""
    user = require_user(request)
    con = db()
    cur = con.cursor()
    # user_account.student_id references student - must be cleared (deleting
    # the account row does this) before the student row itself can be
    # deleted, same ordering constraint the admin path handles with an
    # explicit UPDATE ... SET student_id = NULL first.
    cur.execute("DELETE FROM session WHERE user_id=?", (user["user_id"],))
    cur.execute("DELETE FROM user_account WHERE user_id=?", (user["user_id"],))
    if user["student_id"] is not None:
        _delete_student_cascade(cur, user["student_id"])
    db_write(con)
    con.close()

    send_account_deleted_email(user["email"], deleted_by="self")
    response.delete_cookie(SESSION_COOKIE)
    return {"deleted": user["user_id"]}


@app.delete("/api/admin/students/{student_id}")
def api_admin_delete_student(student_id: str):
    con = db()
    if not con.execute("SELECT 1 FROM student WHERE student_id=?", (student_id,)).fetchone():
        con.close()
        raise HTTPException(404, "Student not found")

    cur = con.cursor()
    # Look up the linked account's email (if any) before un-linking it - the
    # notification needs it, and the un-link below would lose the trail.
    notify_email = cur.execute(
        "SELECT email FROM user_account WHERE student_id=?", (student_id,)
    ).fetchone()

    # Un-link any account pointing at this student - deleting the student
    # shouldn't leave a login account permanently stuck thinking it already
    # completed the survey with a student_id that no longer exists.
    cur.execute("UPDATE user_account SET student_id = NULL WHERE student_id=?", (student_id,))
    _delete_student_cascade(cur, student_id)

    db_write(con)
    con.close()

    if notify_email:
        send_account_deleted_email(notify_email[0], deleted_by="admin")
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
    row = con.execute("SELECT email FROM user_account WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        con.close()
        raise HTTPException(404, "Account not found")
    con.execute("DELETE FROM session WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM user_account WHERE user_id=?", (user_id,))
    db_write(con)
    con.close()
    send_account_deleted_email(row[0], deleted_by="admin")
    return {"deleted": user_id}


if __name__ == "__main__":
    import os

    import uvicorn

    port = int(os.environ.get("PORT", 8010))
    # reload=True only locally - hosting platforms set PORT, so its absence
    # is also the local-dev signal.
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload="PORT" not in os.environ)
