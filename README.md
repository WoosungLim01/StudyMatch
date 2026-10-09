# StudyMatch — DS440 Capstone

Penn State study-group matching. Students sign up with an email address (verified by a 6-digit code) or with Google, take a 24-item survey once, and get placed into a study group of 4–5 by compatibility. Live at https://studymatch-8qih.onrender.com.

The pipeline is real: a live database, login, survey, matching, and an admin view. The synthetic data is calibrated on real datasets (see [`docs/SYNTHETIC_DATA.md`](docs/SYNTHETIC_DATA.md)).

## Stack

- Python 3.10 (pinned in `.python-version`), FastAPI + uvicorn
- SQLite for local development, Turso (hosted libSQL) in production
- OR-Tools CP-SAT for group formation; scikit-learn for the display-only study types
- Plain HTML/CSS/JS in `ui/`, no frontend framework
- Resend's HTTP API for email; Google OAuth 2.0 for Google sign-in (both use stdlib `urllib`)

## Project structure

```
StudyMatch/
├── app.py                    FastAPI server: auth, survey, home, group chat, account, admin
├── requirements.txt
├── .python-version           3.10
├── algorithm/                matching math (no web framework)
│   ├── scoring.py              24-item bank, reverse-coding, score_axes()
│   ├── compatibility.py        weighted 6-axis similarity between two students
│   ├── grouping.py             ILP group formation (OR-Tools CP-SAT), groups of 4-5
│   ├── placement.py            live signups: ILP for new groups, best fit for the rest
│   ├── clustering.py           4 study types, GMM soft membership (display only)
│   └── quality.py              response-quality flags (admin only)
├── data/                     schema, synthetic data, database access, auth, email
│   ├── schema.sql              full DDL
│   ├── studymatch.db           local development database (production uses Turso)
│   ├── db.py                   local SQLite vs Turso connection
│   ├── migrations.py           additive schema changes, run at app startup
│   ├── make_group.py           put chosen students into one group (e.g. a test group)
│   ├── auth.py                 password hashing (stdlib PBKDF2)
│   ├── email.py                outbound email via Resend
│   ├── archetype_store.py      loads the study-type model
│   ├── generate_sample_data.py synthetic cohort generator
│   ├── build_database.py       sample/*.json → studymatch.db
│   ├── add_student.py          scripted bulk insert of real students
│   ├── refit_archetypes.py     optional refit of the study-type mixture
│   ├── build_viewer.py         rebuilds studymatch-data-browser.html
│   └── README.md               data-layer detail
├── ui/                       six pages, served from disk
│   ├── login.html              login, sign-up, and code entry
│   ├── survey.html             entry survey (one time per account)
│   ├── home.html               your group
│   ├── chat.html               your group's private chat
│   ├── account.html            name, log out, delete account
│   └── admin.html              admin view (see Known limitations)
├── docs/                     see Documentation below
├── references/               survey redesign document
└── questionary_data/         real datasets behind the synthetic data
```

## Running it locally

```bash
pip install -r requirements.txt
python app.py
# -> http://localhost:8010/login    log in / sign up
# -> http://localhost:8010/admin    admin view
```

Local runs use `data/studymatch.db`, which ships in the repo with 36 synthetic students across CMPSC 465 and MATH 230. Without the Turso environment variables, the app never touches Turso.

Without `RESEND_API_KEY`, no email is sent. The verification code is still stored, so for local sign-up read it from the `verify_token` column of `user_account` in `data/studymatch.db`. Local sign-ups write to that committed file, so don't commit the rows they add.

## Deployment

Production runs on Render (web service) with a Turso database.

- **Build:** `pip install -r requirements.txt`. **Start:** `python app.py`. The app reads `PORT` from the environment and turns off auto-reload when it's set.
- **Environment variables** (set in Render's Environment tab, never committed):

| Variable | Purpose |
|---|---|
| `TURSO_DATABASE_URL` | Turso database URL (`libsql://...`). Set together with the token to use Turso |
| `TURSO_AUTH_TOKEN` | Turso auth token (secret) |
| `RESEND_API_KEY` | Resend API key (secret). Without it, email is logged, not sent |
| `RESEND_FROM_EMAIL` | Sender address on a domain verified in Resend, e.g. `noreply@studymatch.us` |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret (secret) |
| `GOOGLE_REDIRECT_URI` | `https://studymatch-8qih.onrender.com/api/auth/google/callback`, matching the Google Cloud Console entry |

Google sign-in returns 501 until all three Google variables are set.

- **Deploying:** auto-deploy on push to `main` has not been triggering. Use **Manual Deploy → Deploy latest commit** in Render, or the service's Deploy Hook URL (Settings tab). Treat the Deploy Hook as a secret. The root cause is not yet confirmed.
- **Turso:** `data/db.py` keeps a local replica at `data/.turso_replica.db` (gitignored), syncs before each connection, and pushes after each write.
- **Python:** `.python-version` pins 3.10 because Render's default (3.14) has no prebuilt wheels for the pinned numpy, scikit-learn, and ortools versions.

## How it works

1. **Sign-up and login** (`ui/login.html`). One email and password form.
   - New email: an unverified account is created and a 6-digit code is emailed.
   - Known email, wrong password: rejected. It is never treated as a new sign-up.
   - Verified account, right password: logged in.
   - Unverified account, right password: a new code is emailed.
   - The code is entered on the same page with the password (`POST /api/auth/verify-code`). Five wrong codes lock the account until a new code is requested. Success starts the session directly, so there's no second login.
   - Google sign-in (`/api/auth/google/login`) creates a verified account, or links to an existing account with the same email.
2. **Survey** (`ui/survey.html`). Name, course, year, gender, major, and 24 statements on a 5-point Likert scale with nothing pre-selected. Availability and academic sections are optional and off by default.
   - Raw answers are stored exactly as clicked. Reverse-worded items are flipped with `6 − raw` only at scoring time, then the four items per axis are averaged. The six axes are `planning`, `session_mode`, `reliability`, `structure`, `intensity`, and `collaboration`. The item bank and reverse flags are in `algorithm/scoring.py`.
   - Submitting places you in a group right away. The survey is one time per account.
3. **Study type** (`algorithm/clustering.py`), display only. Four types from a 2×2 of self-regulation (planning, structure, reliability) and social mode (session_mode, collaboration): Study Captain, Focused Architect, Collaborative Explorer, and Independent Sprinter. Intensity is shown as a separate badge. Below 200 students the theory model is used as-is. Above that, `python data/refit_archetypes.py` fits the mixture on a sample so the boundaries follow real answers.
   - Response-quality flags (`algorithm/quality.py`) appear on the admin page. They never affect sign-up or matching.
4. **Compatibility** (`algorithm/compatibility.py`). `100 ×` the weighted mean of `1 − |a − b| / 4` across the six axes. Reliability and intensity weigh 1.5×. Matching is similarity-only on purpose: StudyMatch is for people who want classmates who study like them.
5. **Groups** (`algorithm/grouping.py`, `algorithm/placement.py`). An OR-Tools CP-SAT model splits each course's unplaced students into groups of 4–5 to maximize within-group compatibility. It is deterministic and reports its optimality bound. Existing groups are never reshuffled. Leftover pools of 1–3, 6, 7, or 11 join the best-fitting group with room, or wait until enough people arrive. Sign-up is never blocked; a match below 65 signs in with a warning.
6. **Home** (`ui/home.html`). Your group, its members, and your course. Students not yet placed see a waiting-list message. Clicking the group card opens the group chat.
7. **Group chat** (`ui/chat.html`, `/chat?group=<group_id>`). A private chat for the group's members, with text and attachments.
   - The page polls `GET /api/groups/{id}/messages?after=<last id>` every 3 seconds and pauses while the tab is hidden. There are no websockets, so Render's free-tier sleep and redeploys need no reconnect logic. Text is sent with `POST /api/groups/{id}/messages`.
   - **Attachments:** the paperclip button attaches one photo, video or file per message, with an optional caption. It uploads as multipart to `POST /api/groups/{id}/attachments`, with a progress percentage. The limit is 10 MB per file (`ATTACHMENT_MAX_BYTES` in `app.py`), checked in the browser and again on the server.
   - PNG, JPEG, GIF and WebP show as images. MP4, WebM and QuickTime show as playable video. Everything else, including SVG and HTML, appears as a download card and is served as `application/octet-stream`, so an upload can never run as a page.
   - Files are stored in Turso, not on disk, because Render's disk is wiped on every redeploy. Each file is split into 512 KB rows (`group_chat_attachment_chunk`) so no single statement carries a large blob. Downloads support byte ranges, which iPhone Safari needs to play video at all.
   - Every chat endpoint, downloads included, checks that you belong to the group: non-members get 403. Messages are 1–1000 characters. Enter sends, Shift+Enter adds a line, and Enter while a Korean (or other IME) composition is in progress does not send.
   - `data/migrations.py` creates the chat tables, and adds the attachment column to existing ones, on startup, so deploying is all the live database needs. Deleting a student deletes their messages and uploads, and a group's chat and files are deleted with the group.
   - Message text, names and filenames are rendered as text, never as HTML.
   - To put specific students into one group for testing, run `python data/make_group.py 0037 0045 ...`. It prints a dry run first and only writes with `--apply`; see the script's docstring.
8. **Account** (`ui/account.html`). Change your display name, log out, or delete your account. Deleting removes login access and your survey and group data, and sends a confirmation email.
9. **Admin** (`ui/admin.html`). Lists students and login accounts. Deleting a student removes them from every table and unlinks their account. Deleting an account removes login access only. Both send a notification email when the person has an address. The admin page has no login check; see Known limitations.
10. **Email** (`data/email.py`). Verification codes and deletion notices go through Resend's HTTP API. The sender domain must be verified in Resend.

## Documentation

| File | What it covers |
|---|---|
| `docs/STATUS.md` | Current state: what's live and what's pending |
| `docs/ER_DIAGRAM.md` | Database schema and design decisions |
| `docs/SYNTHETIC_DATA.md` | Real datasets behind the synthetic data, and how it was derived |
| `docs/DATA_GROUNDING.md` | What's backed by research and what isn't |
| `docs/SIMULATION_PLAN.md` | Planned, not built: a semester-length outcome simulation |
| `Design.md` | UI design system. Every page in `ui/` follows it |
| `data/README.md` | Data layer: sample data, reproducibility, group-size remainder policy |
| `references/` | Survey redesign document |

**Conventions:** the product name is **StudyMatch** everywhere. Don't use "StudyNest," which came from an early brief. Don't use Penn State's logo, wordmark, seal, or Nittany Lion marks.

## Known limitations

- **The admin page has no authentication.** `/admin` and the `/api/admin/*` endpoints, including delete, can be reached by anyone who knows the URL. That's acceptable for local development, but the site is public, so an admin login needs to be added before relying on it.
- **Admin page renders names as raw HTML.** `ui/home.html` and `ui/chat.html` escape user-controlled names, but `ui/admin.html` doesn't yet, so a display name containing HTML runs as script on the admin page. Fix it together with admin authentication.
- Group chat has no read receipts, notifications, editing, or deleting your own messages. There's no per-user send or upload rate limit, and each poll syncs with Turso, which is fine at the current scale.
- Attachments are capped at 10 MB, which fits photos and short clips but not most phone videos. Every upload also counts against the Turso plan's storage. Larger files would need object storage such as Cloudflare R2.
- No forgot-password flow, and no way to change a password. The 6-character minimum is deliberate.
- Survey answers can't be retaken or edited after submission.
- Verification codes don't expire. A code stays valid until it's used or replaced. The wrong-code lockout is kept in memory and resets when the server restarts.
- Matching is homogeneous by design, which can create echo-chamber effects over time. This is tracked as a future outcome metric rather than constrained away.
- No balancing across groups, and no per-student axis weights or dealbreakers.
- Response-quality flags catch straight-lining and contradictory answers, but not random clicking (about 3% of responses are flagged).
- The feedback loop is not built. `group_feedback` is collected but doesn't change matching.
- `session_mode` and `collaboration` are calibrated against Big Five proxies, not measures of those constructs. See [`docs/SYNTHETIC_DATA.md`](docs/SYNTHETIC_DATA.md).
