# StudyMatch — Current Status

Snapshot of where the project stands on `main`. For setup and how the system works, see the [repo README](../README.md). This document is the "what's live, what's done, what's left" view.

## Live deployment

- **App**: https://studymatch-8qih.onrender.com (Render, Python 3.10)
- **Database**: Turso (hosted libSQL). `data/db.py` uses it when `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are set. Local runs use `data/studymatch.db` when they aren't.
- **Auto-deploy is not triggering.** Pushes to `main` don't start a deploy. Workaround: **Manual Deploy → Deploy latest commit** in Render, or the service's **Deploy Hook** URL (Settings tab), which works with a plain GET or POST and can be shared without giving dashboard access. Root cause not yet confirmed. Next time, check Settings → Build & Deploy → Branch and the Events tab.
- **Latest change on `main`**: `883b316`, which replaces the emailed verification link with a 6-digit code. Tested locally; not yet tested on the live site.
- Verified live end-to-end (before the code change): sign-up, email verification, survey, ILP group placement, home, account editing, admin deletion.
- **Group chat is on `dev_woojoo`, not `main` yet** (commit `e953396`), so it isn't live. See Group chat below and Pending.

## Data collection layer

24-item, 5-point Likert survey (Version 3, MSLQ-informed), 6 axes (`planning`, `session_mode`, `reliability`, `structure`, `intensity`, `collaboration`), no default-selected answers. Synthetic demo data is calibrated on real datasets (a published MSLQ validation study and the IPIP Big Five dataset), not hand-picked numbers.

Full detail: [`SYNTHETIC_DATA.md`](SYNTHETIC_DATA.md) (datasets, derivation, limitations) and [`algorithm/scoring.py`](../algorithm/scoring.py) (the item bank and reverse-coding, the one source of truth for what's asked).

## Matching algorithm

Real, not a placeholder (built by Woosung): groups of 4–5 are formed by an OR-Tools CP-SAT **ILP** that maximizes total within-group compatibility over the 6 axes, with reliability and intensity weighted 1.5×. Study-type labels (4 types, from a Gaussian mixture, e.g. "Study Captain") are **display-only**. They're computed from 5 of the 6 axes and never fed into matching.

Full detail: [`README.md`](../README.md#how-it-works) and the code in `algorithm/`.

## Auth and account features

- **Email + password**: sign-up creates an unverified account. A 6-digit code is emailed and entered on the login page together with the password. The account can't log in until it's verified (enforced server-side). Five wrong codes lock it until a new code is requested. Password rules are minimal on purpose (6-character minimum).
- **Google sign-in**: OAuth2 authorization-code flow, implemented with stdlib `urllib`. Google accounts are auto-verified. They match an existing password account by email rather than creating a duplicate. Needs `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` set on Render. Until they are, the button returns 501 with a clear message. The credentials and redirect URIs exist; confirmation that they're set on Render is pending.
- **Account page** (`/account`): edit display name, log out, or delete your own account (removes login and any survey and group data in one action).
- **Admin page** (`/admin`): delete a student (cascades everywhere) or a login account (login-only, keeps survey data). **No authentication yet**; see Known limitations.
- **Deletion notifications**: all three deletion paths email the affected person a confirmation.
- **Sessions**: 30-day expiry, enforced server-side and swept on each login.

## Group chat

On `dev_woojoo`; not merged or deployed yet.

- **What it does**: clicking your group card on `/home` opens `/chat?group=<group_id>`, a private text-only chat for that group's members. Messages show sender, time, and day separators, and consecutive messages from one person are grouped.
- **How it updates**: the page polls for messages newer than the last one it has every 3 seconds and pauses while the tab is hidden. No websockets, so Render's free-tier sleep and redeploys don't break anything.
- **Access control**: every chat endpoint (`/api/groups/{id}`, `/api/groups/{id}/messages`) checks group membership on each request. Non-members get 403, logged-out users 401.
- **Database**: new `group_chat_message` table. `app.py` creates it on startup if it's missing, so the live Turso database needs no manual migration; deploying is enough. A deleted student's messages, and a deleted group's chat, are removed with them.
- **Security fix shipped with it**: `ui/home.html` now HTML-escapes names, emails, and group names. Display names are editable on `/account`, and before this fix a name containing HTML ran as script in every groupmate's browser.
- **Tested locally** against a copy of the database: sending and polling, member-only access (403/401/404), input limits, the startup migration on an old database, deletion cleanup, escaping of HTML in names, and a double Enter or an IME-composition Enter not producing extra messages. **Not yet tested on the live site.**

## Outbound email

- Sent through **Resend's HTTP API** over HTTPS (port 443). Gmail SMTP was dropped because Render's free tier blocks SMTP ports 25, 465, and 587.
- The sending domain `studymatch.us` is verified in Resend. DNS is managed in Cloudflare: the SPF and DKIM records, plus an MX record that keeps receiving enabled. Receiving is harmless because nothing reads inbound mail.
- **Required on Render**: `RESEND_API_KEY` and `RESEND_FROM_EMAIL=noreply@studymatch.us`. Without `RESEND_API_KEY`, emails are logged instead of sent, and sign-up can't finish.
- Resend's log showing **delivered** means the recipient's mail server accepted the message. If it isn't in the inbox, check spam and the recipient's other folders.

## Pending: needs action

1. **Confirm the Render environment variables** `RESEND_API_KEY` and `RESEND_FROM_EMAIL` are saved and the deploy has finished.
2. **Test sign-up end-to-end** on the live site with an address you can read, including the 6-digit code step.
3. **Confirm the Google environment variables** are set on Render.
4. **Add authentication to the admin page** and to `/api/admin/*`. Both are currently public.
5. **Diagnose auto-deploy** (see Live deployment).
6. **Merge group chat into `main` and deploy** (`dev_woojoo`, commit `e953396`), then test it live with two accounts in the same group. Turso must be reachable when the app starts, because startup creates the chat table.
7. **Escape names on the admin page.** `ui/admin.html` still inserts names as raw HTML (see Known limitations). Do it together with item 4.

## Known limitations and deliberately deferred

- Password rules: 6-character minimum, deliberately minimal.
- Admin page: no authentication, and it renders student names as raw HTML, so a display name containing HTML runs as script there (see Pending).
- Group chat: text only. No read receipts, attachments, notifications, or editing or deleting messages. No per-user send rate limit. Each 3-second poll syncs with Turso, which is fine at the current scale but worth revisiting (a longer interval or a lighter read path) with many concurrent users.
- Verification codes don't expire, and the wrong-code lockout is kept in memory. Codes are stored in a column with a UNIQUE constraint, so if two unverified accounts ever receive the same code (about 1 in a million per pair), the second sign-up fails with a server error.
- The synthetic population (36 students) is too small to validate its correlations statistically. Means check out; correlations are noisy at this sample size. See `SYNTHETIC_DATA.md`.
- `session_mode` and `collaboration` are calibrated against Big Five proxies, not exact constructs. See `SYNTHETIC_DATA.md`.
- No feedback-loop learning. Axis weights are hand-set until there are real `group_feedback` outcomes.
- No way to add a password to a Google-only account. Only the reverse (linking Google to an existing password account) works.

## Quick reference

| Doc | Covers |
|---|---|
| [`../README.md`](../README.md) | Setup, deployment, environment variables, how the system works, documentation index |
| [`SYNTHETIC_DATA.md`](SYNTHETIC_DATA.md) | Real datasets behind the synthetic data, and the exact derivation |
| [`DATA_GROUNDING.md`](DATA_GROUNDING.md) | What's backed by research and what isn't |
| [`ER_DIAGRAM.md`](ER_DIAGRAM.md) | Full schema and design decisions |
| [`SIMULATION_PLAN.md`](SIMULATION_PLAN.md) | Planned, not built: outcome simulation |
| `data/db.py` | Turso vs. local connection logic (read its docstring) |
| `data/email.py` | Outbound email (read its docstring) |
