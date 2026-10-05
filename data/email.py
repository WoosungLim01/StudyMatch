"""
StudyMatch — outbound email (verification links, account-deletion notices).

Resend's HTTP API (https://api.resend.com/emails), not SMTP: Render's free
tier unconditionally firewall-blocks outbound traffic to every SMTP port
(25, 465, 587) at the network level - confirmed via Render's own changelog
after Gmail SMTP from data/email.py's first version produced "Network is
unreachable", then (after forcing IPv4) a silent TimeoutError - both are
exactly what a dropped-not-refused packet looks like. An HTTP API call on
port 443 sidesteps this entirely (same reason Turso and Google OAuth above
already work fine - both are HTTPS too), so this is implemented the same
way as the Google OAuth token exchange: a plain stdlib urllib POST, no SDK.

Config via env vars (same pattern as TURSO_*/GOOGLE_*, never committed):

    RESEND_API_KEY     from resend.com (free: 3,000 emails/month, 100/day)
    RESEND_FROM_EMAIL  optional, defaults to onboarding@resend.dev (Resend's
                        built-in test sender - works immediately, no domain
                        verification needed; swap in a verified domain's
                        address here once you have one, no code change)

If RESEND_API_KEY is unset, send_email() logs a warning and returns False
instead of raising - local dev and not-yet-configured deployments keep
working, same graceful-degradation pattern as Google sign-in's 501.
"""

import json
import os
import urllib.error
import urllib.request

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
RESEND_URL = "https://api.resend.com/emails"


def send_email(to, subject, body):
    """Returns True if sent, False if email isn't configured or sending failed
    (logged, never raised - a notification email bouncing shouldn't break the
    request that triggered it, e.g. an account deletion)."""
    if not RESEND_API_KEY:
        print(f"[email] not configured - would have sent to {to!r}: {subject!r}")
        return False
    payload = json.dumps({
        "from": RESEND_FROM_EMAIL,
        "to": [to],
        "subject": subject,
        "text": body,
    }).encode()
    req = urllib.request.Request(
        RESEND_URL, data=payload, method="POST",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except urllib.error.HTTPError as e:
        print(f"[email] send to {to!r} failed: HTTP {e.code} {e.read().decode(errors='replace')}")
        return False
    except urllib.error.URLError as e:
        print(f"[email] send to {to!r} failed: {e}")
        return False


def send_verification_email(to, verify_url):
    send_email(
        to,
        "Verify your StudyMatch account",
        f"Welcome to StudyMatch!\n\n"
        f"Click the link below to verify your email and finish signing in:\n\n"
        f"{verify_url}\n\n"
        f"If you didn't sign up for StudyMatch, you can ignore this email.",
    )


def send_account_deleted_email(to, deleted_by):
    who = "an admin" if deleted_by == "admin" else "you"
    send_email(
        to,
        "Your StudyMatch account was deleted",
        f"This confirms your StudyMatch account and any associated survey/group data "
        f"was deleted by {who}.\n\n"
        f"If you didn't expect this, or believe it was done in error, reply to this "
        f"email or contact your course staff.",
    )
