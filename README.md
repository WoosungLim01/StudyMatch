# StudyMatch — DS440 Capstone

Penn State study-group matching. Students log in, take a personality survey
once, and get placed into a 5-person study group by compatibility —
synthetic data for now, but the pipeline is real: a live SQLite database, a
working login/survey/home flow, and an admin view, not just a demo script.

## Stack

Python 3.10+, FastAPI, SQLite, scikit-learn (KMeans). No frontend framework —
plain HTML/CSS/JS served straight off disk.

## Project structure

```
StudyMatch/
├── app.py                    the server — ties everything below together
├── requirements.txt
├── algorithm/                the matching math (no I/O, no framework)
│   ├── compatibility.py        personality-similarity scoring
│   └── placement.py            the group-size remainder policy
├── data/                      the schema, the synthetic dataset, the live DB
│   ├── schema.sql
│   ├── studymatch.db           ← the actual database
│   ├── auth.py                  password hashing (stdlib only)
│   ├── generate_sample_data.py batch-generates the synthetic cohort
│   ├── add_student.py          scripted/bulk real-student insert
│   ├── build_database.py       sample/*.json → studymatch.db
│   └── README.md                data-layer detail
├── ui/                        the four pages
│   ├── login.html                combined login/signup
│   ├── survey.html               entry survey (one-time per account)
│   ├── home.html                 your group, once you've taken the survey
│   └── admin.html                admin: view + delete anyone/any account
└── docs/
    └── ER_DIAGRAM.md          schema diagram + design decisions
```

Each piece works standalone (you can regenerate `data/` without touching
`algorithm/`, or read the schema without running anything), but `app.py` is
what wires a real survey submission through `algorithm/` and into `data/`.

## Running it

```bash
pip install -r requirements.txt
python app.py
# -> http://localhost:8010/login    log in / sign up
# -> http://localhost:8010/admin    admin view (search, filter, delete)
```

That's it — no separate database setup. `data/studymatch.db` ships in the
repo, pre-populated with 34 synthetic students across 2 courses (CMPSC 465,
MATH 230) and their study groups.

## How it works

1. **Login / signup** (`ui/login.html`) — one email+password form. Unknown
   email creates an account; known email checks the password (wrong password
   is rejected outright, never silently treated as a new signup). A
   brand-new account is routed to the survey; an account that's already
   completed it goes straight to the home page.
2. **Survey** (`ui/survey.html`) — one-time per account. Name, course,
   year/gender/major, and a 14-trait personality questionnaire (1-5 scale),
   plus optional availability/academic sections (off by default — nothing
   recorded unless switched on). Submitting it links the account to the new
   student record, so it can never be seen (or re-taken) again from that
   account.
3. **Scoring** (`algorithm/compatibility.py`) — compatibility between two
   students is their average closeness across all 14 traits. Purely
   similarity-based, no "opposites attract" term.
4. **Placement** (`algorithm/placement.py`) — groups target exactly 5.
   Whoever's unassigned in a course gets peeled into full 5-groups where
   possible; a 1-2 person remainder joins the best existing under-capacity
   group; a 3-4 person remainder becomes its own new group. Never blocks
   signup on a bad match — a below-threshold match still gets signed in, just
   with a warning instead of a plain success message.
5. **Home** (`ui/home.html`) — where a returning, already-matched account
   lands: their group, its members, their course. Shows a plain "you're on
   the waiting list" message instead of a broken group section if they
   haven't been placed yet.
6. **Persistence** (`data/studymatch.db`) — every submission is permanent.
   Nothing is deleted automatically; the only way to remove someone (real or
   synthetic student, or a login account) is the admin page's delete button,
   which cascades cleanly across every table that references them. Deleting
   a student un-links any account pointing at them; deleting an account only
   removes login access, leaving their student/survey data untouched.

Full schema + the normalization decisions behind it: [`docs/ER_DIAGRAM.md`](docs/ER_DIAGRAM.md).
Data generation, reproducibility, and the remainder-policy math in detail: [`data/README.md`](data/README.md).
A planned (not yet built) semester-length outcome simulation, for validating the
matching algorithm without waiting on real semester-long feedback: [`docs/SIMULATION_PLAN.md`](docs/SIMULATION_PLAN.md).

## Known limitations / out of scope (v1)

- **Authentication is real but minimal** — email+password with hashed storage
  (stdlib PBKDF2, see `data/auth.py`) and proper session cookies, but no
  email verification, no forgot-password flow, and no way to retake/edit
  survey answers once submitted. There's also no way for a student to change
  their own password.
- **Admin has no auth of its own** — anyone who can reach `/admin` can view
  and delete anyone. Fine for local development, not something to expose
  publicly as-is.
- **Homogeneous matching** — compatibility rewards similarity only, which can
  create echo-chamber dynamics over time (high performers keep grouping with
  high performers). Tracked as a future outcome metric, not constrained away.
- **Inter-group fairness** — matching only maximizes intra-group compatibility;
  no balancing across groups.
- **Deploying with persistent storage**: `python app.py` writes directly to
  `data/studymatch.db` on local disk. Most PaaS platforms (Railway, Render,
  Heroku free tiers, etc.) use an *ephemeral* filesystem — every real
  student added would be silently wiped on the next redeploy/restart unless
  the database is moved to a persistent volume or an external Postgres/SQLite
  host. Not solved here; flagging it before anyone actually deploys this.
