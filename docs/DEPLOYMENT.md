# Running and deploying StudyMatch

## Running it locally

```bash
pip install -r requirements.txt
python app.py
# -> http://localhost:8010/login    log in / sign up
# -> http://localhost:8010/admin    admin view (password 1234 unless ADMIN_PASSWORD is set)
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
| `ADMIN_PASSWORD` | Shared admin password (secret). **Until it is set, the admin password is the temporary `1234` from `app.py`, which anyone reading this repo can see. Set it as soon as someone has Render access.** Use a long random value, and change it when someone leaves the team: that logs every admin out |

Google sign-in returns 501 until all three Google variables are set.

- **Deploying:** auto-deploy on push to `main` has not been triggering. Use **Manual Deploy → Deploy latest commit** in Render, or the service's Deploy Hook URL (Settings tab). Treat the Deploy Hook as a secret. The root cause is not yet confirmed.
- **Turso:** `data/db.py` keeps a local replica at `data/.turso_replica.db` (gitignored), syncs before each connection, and pushes after each write.
- **Python:** `.python-version` pins 3.10 because Render's default (3.14) has no prebuilt wheels for the pinned numpy, scikit-learn, and ortools versions.
