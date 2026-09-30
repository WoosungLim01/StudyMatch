# StudyMatch — DS440 Capstone

Penn State study-group matching. Students log in, take a personality survey
once, and get placed into a 5-person study group by compatibility —
synthetic data for now, but the pipeline is real: a live SQLite database, a
working login/survey/home flow, and an admin view, not just a demo script.

## Stack

Python 3.10+, FastAPI, SQLite, scikit-learn (Gaussian mixture), OR-Tools
(CP-SAT ILP). No frontend framework —
plain HTML/CSS/JS served straight off disk.

## Project structure

```
StudyMatch/
├── app.py                    the server — ties everything below together
├── requirements.txt
├── algorithm/                the matching math (no framework)
│   ├── scoring.py              the 24-item survey bank + Likert scoring
│   ├── clustering.py           4 fixed study types, GMM soft membership (display only)
│   ├── quality.py              survey response-quality flags (admin only)
│   ├── compatibility.py        weighted 6-axis similarity between two students
│   ├── grouping.py             ILP group formation (OR-Tools CP-SAT), groups of 4-5
│   └── placement.py            live signups: ILP for new groups, best-fit for the rest
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
repo, pre-populated with 36 synthetic students across 2 courses (CMPSC 465,
MATH 230) and their study groups.

## How it works

1. **Login / signup** (`ui/login.html`) — one email+password form. Unknown
   email creates an account; known email checks the password (wrong password
   is rejected outright, never silently treated as a new signup). A
   brand-new account is routed to the survey; an account that's already
   completed it goes straight to the home page.
2. **Survey** (`ui/survey.html`) — one-time per account. Name, course,
   year/gender/major, and a fixed 24-item, 5-point Likert questionnaire
   (Strongly Disagree - Strongly Agree, blank by default, no pre-selected
   option), plus optional availability/academic sections (off by default —
   nothing recorded unless switched on). The 24 raw answers score into 6
   study-behavior axes (`algorithm/scoring.py`); submitting links the account
   to the new student record, so it can never be seen (or re-taken) again
   from that account.
3. **Study type** (`algorithm/clustering.py`), a **display layer only**
   (types never feed into who groups with whom).
   - **Four types, fixed by theory**: the survey follows MSLQ's split, so
     the axes form two style families. Self-regulation is planning +
     structure + reliability; social mode is session_mode + collaboration.
     Their 2x2 gives Study Captain (organized, collaborative), Focused
     Architect (organized, independent), Collaborative Explorer (flexible,
     collaborative) and Independent Sprinter (flexible, independent).
   - **Motivation badge**: intensity is shown separately ("High Drive" /
     "Steady Pace"), since it's a level, not a style.
   - **Membership**: a Gaussian mixture over the two family scores,
     anchored at the theory centers, gives a soft membership such as
     "Study Captain 72%". Students near a boundary get split percentages
     rather than flipping on a 0.02 difference.
   - **Fitting**: below 200 students the theory model is used as-is.
     Beyond that, `python data/refit_archetypes.py` fits the mixture on a
     sample (≤20k) so the boundaries follow real (usually high-skewed)
     answers. A fit that would change what a type means is rejected.
   - **New signups** are classified against the stored model, with no
     re-fit.
   - **Response quality** (`algorithm/quality.py`): same answer everywhere,
     contradictory answers to reverse-worded pairs, or a profile that fits
     no type is flagged on the admin page. The flag never affects signup
     or matching.
4. **Compatibility** (`algorithm/compatibility.py`) — weighted similarity of
   two students' raw 6-axis vectors, 0-100. The motivation axes
   (reliability, intensity) weigh 1.5x the four study-style axes. Matching is
   homogeneous on purpose: StudyMatch is opt-in, for people who want
   classmates who study like them.
5. **Group formation** (`algorithm/grouping.py`, `algorithm/placement.py`) —
   an ILP (OR-Tools CP-SAT) splits a course's unassigned students into
   groups of **4-5** that maximize total within-group compatibility (only
   same-course students ever share a group). It's deterministic (same input,
   same groups) and never worse than a greedy+local-search warm start; it
   reports its optimality bound. Existing groups are never reshuffled when
   someone signs up. Whoever can't be split into 4s and 5s (a pool of 1-3,
   6, 7 or 11) joins the existing group with room where they fit best, or
   waits on the list until enough people arrive. Signup is never blocked: a
   below-65 match still gets signed in, just with a warning.
   On the sample data the ILP gets an average pair compatibility of ~90
   (CMPSC 465) vs ~75 for random groups of the same sizes;
   `python data/generate_sample_data.py` prints the comparison.
6. **Home** (`ui/home.html`) — where a returning, already-matched account
   lands: their group, its members, their course. Shows a plain "you're on
   the waiting list" message instead of a broken group section if they
   haven't been placed yet.
7. **Persistence** (`data/studymatch.db`) — every submission is permanent.
   Nothing is deleted automatically; the only way to remove someone (real or
   synthetic student, or a login account) is the admin page's delete button,
   which cascades cleanly across every table that references them. Deleting
   a student un-links any account pointing at them; deleting an account only
   removes login access, leaving their student/survey data untouched.

Full schema + the normalization decisions behind it: [`docs/ER_DIAGRAM.md`](docs/ER_DIAGRAM.md).
Data generation, reproducibility, and the remainder-policy math in detail: [`data/README.md`](data/README.md).
A planned (not yet built) semester-length outcome simulation, for validating the
matching algorithm without waiting on real semester-long feedback: [`docs/SIMULATION_PLAN.md`](docs/SIMULATION_PLAN.md).
What real research backs (and doesn't yet back) the synthetic data's design: [`docs/DATA_GROUNDING.md`](docs/DATA_GROUNDING.md).

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
- **No per-student axis importance yet** — axis weights are fixed
  (motivation 1.5x); students can't mark an axis as more/less important or
  as a dealbreaker.
- **Response-quality flags are partial** — straight-lining and contradictory
  answers are caught; genuinely random clicking mostly isn't (~3% flagged).
  "Fits no type well" also fires for extreme-but-honest profiles.
- **Study-type fit needs real data** — with the 38 current students the theory
  model is used; the synthetic cohort is too artificially clustered to
  calibrate a mixture on.
- **Feedback loop not built** — `group_feedback` is collected but doesn't yet
  update compatibility for the next matching round.
- **Deploying with persistent storage**: `python app.py` writes directly to
  `data/studymatch.db` on local disk. Most PaaS platforms (Railway, Render,
  Heroku free tiers, etc.) use an *ephemeral* filesystem — every real
  student added would be silently wiped on the next redeploy/restart unless
  the database is moved to a persistent volume or an external Postgres/SQLite
  host. Not solved here; flagging it before anyone actually deploys this.
