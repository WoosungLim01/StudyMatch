# StudyMatch — Current Status

Snapshot of where the project actually stands, updated as of the latest
work on `main`. For deep dives on specific parts, see the other docs linked
throughout — this one is the "what's done, what's live, what's left" view.

## Live deployment

- **App**: https://studymatch-8qih.onrender.com (Render, Python 3.10)
- **Database**: Turso (remote libSQL) — `data/db.py` switches to it automatically
  when `TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN` are set as Render env vars;
  local dev is unaffected (plain `sqlite3` against `data/studymatch.db`)
  when they're not set.
- **Known issue — auto-deploy not triggering**: Render's "Auto-Deploy" is
  on, but pushes to `main` haven't been triggering new deploys. Workaround:
  **Manual Deploy → Deploy latest commit** in Render's dashboard after each
  push. Not yet root-caused — likely either the configured branch doesn't
  match `main`, or the GitHub webhook connection is broken. Check Settings →
  Build & Deploy → Branch, and the service's Events tab, next time this
  comes up.
- Verified live, end-to-end, against the real Turso database (not just
  local): signup → email verification → survey → ILP group placement →
  home page → account editing → admin student/account deletion. All
  passing as of the last check.

## Data collection layer

24-item, 5-point Likert survey (Version 3, MSLQ-informed), 6 axes
(`planning`, `session_mode`, `reliability`, `structure`, `intensity`,
`collaboration`), no default-selected answers. Synthetic demo data is
calibrated on real datasets (a published MSLQ validation study + the IPIP
Big Five dataset), not hand-picked numbers.

Full detail: [`docs/SYNTHETIC_DATA.md`](SYNTHETIC_DATA.md) (datasets, exact
derivation, stated limitations) and [`algorithm/scoring.py`](../algorithm/scoring.py)
(the item bank + reverse-coding, the one source of truth for what's asked).

## Matching algorithm

Real, not a placeholder (was random earlier in development, replaced by
Woosung): groups of 4-5 formed by an OR-Tools CP-SAT **ILP** maximizing
total within-group weighted compatibility over the 6 axes (reliability and
intensity weighted 1.5x). Archetype labels (4 theory-anchored types via a
Gaussian mixture, e.g. "Study Captain") are **display-only** — computed
from 5 of the 6 axes, never fed into matching.

Full detail: [`docs/Woosung.md`](Woosung.md) (written as a handoff, may be
stale on the "what's left" section now that the algorithm is actually
built — the data-layer parts are still accurate).

## Auth & account features

- **Email + password**: sign up requires clicking a mailed verification
  link before the account can log in (enforced server-side, not just a
  nudge). Password reset/complexity rules are minimal on purpose (6-char
  minimum, deferred for later).
- **Google sign-in**: OAuth2 authorization-code flow, implemented with
  stdlib `urllib` (no OAuth framework dependency). Auto-verified on
  creation (Google already confirms the email). Matches/links to an
  existing password account by email rather than creating a duplicate.
  **Credentials obtained** (Cloud Console project + OAuth client, correct
  redirect URIs for both prod and localhost) but **not yet confirmed set**
  as `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GOOGLE_REDIRECT_URI` on
  Render — until they are, the "Continue with Google" button 501s with a
  clear message instead of working.
- **Account page** (`/account`): edit display name, log out, or
  **self-delete** your own account (removes login + any survey/group data
  in one action).
- **Admin page** (`/admin`): delete any student (cascades everywhere) or
  any login account (login-only, keeps survey data), same as before.
- **Deletion notifications**: all three deletion paths (self-service, admin
  delete-student, admin delete-account) email the affected person a
  confirmation.
- **Outbound email** (verification links + deletion notices): Gmail SMTP
  via stdlib `smtplib`, config via `SMTP_EMAIL`/`SMTP_APP_PASSWORD`.
  **Not yet configured** — until it is, these emails are logged
  server-side instead of actually sent, which means **new password
  signups currently cannot complete** (no way to receive the verification
  link). This is the most urgent of the pending setup items.
- **Sessions**: 30-day expiry enforced server-side (not just the cookie's
  client-side `max_age`), swept on each new login.

## Pending — needs your action

1. **Gmail SMTP** (`SMTP_EMAIL`, `SMTP_APP_PASSWORD` on Render) — urgent,
   password signup is broken without it. Steps: turn on 2-Step
   Verification on the sending Google account, generate an App Password at
   myaccount.google.com/apppasswords (16 chars, no spaces when pasting),
   set both env vars.
2. **Confirm Google OAuth env vars are set on Render**
   (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` =
   `https://studymatch-8qih.onrender.com/api/auth/google/callback`) — the
   credentials file already exists locally with the right redirect URIs,
   just needs to actually land in Render's environment settings.
3. **Diagnose auto-deploy** — see "Known issue" above. Manual Deploy works
   as a stopgap in the meantime.

## Known limitations / deliberately deferred

- Password complexity: minimal (6-char minimum), explicitly deferred.
- Synthetic population (36 students) is too small to validate the
  calibrated correlation structure statistically — means check out fine,
  correlations are noisy at this N. See SYNTHETIC_DATA.md.
- `session_mode`/`collaboration` axes are calibrated against a real but
  imperfect proxy dataset (Big Five Extraversion/Agreeableness), not an
  exact construct match — see SYNTHETIC_DATA.md's limitations section.
- No feedback-loop learning (axis weights are still hand-set, not fit from
  real `group_feedback` outcomes) — needs real signups and a feedback
  UI neither of which exist yet.
- "Add a password to a Google-only account" isn't built — only the
  reverse (linking Google to an existing password account) works.

## Quick reference

| Doc | Covers |
|---|---|
| [`SYNTHETIC_DATA.md`](SYNTHETIC_DATA.md) | Real datasets behind the synthetic data, exact derivation |
| [`DATA_GROUNDING.md`](DATA_GROUNDING.md) | What survey-design choices are research-backed vs. invented |
| [`Woosung.md`](Woosung.md) | Data-layer handoff for the matching algorithm (written before the ILP was built) |
| [`ER_DIAGRAM.md`](ER_DIAGRAM.md) | Full schema + design decisions |
| [`SIMULATION_PLAN.md`](SIMULATION_PLAN.md) | Planned (not built) outcome-simulation pipeline |
| `data/db.py` | Turso vs. local connection logic, read its docstring |
| `data/email.py` | Outbound email, read its docstring |
