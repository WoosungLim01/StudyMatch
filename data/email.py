"""
StudyMatch — outbound email (verification links, account-deletion notices).

Gmail SMTP via stdlib smtplib, not a third-party email API: no new
dependency, no new service account to create - reuses the same Google
account from the OAuth setup. Config via env vars (same pattern as
TURSO_*/GOOGLE_*, never committed):

    SMTP_EMAIL          the Gmail address to send from
    SMTP_APP_PASSWORD   a Gmail App Password (NOT the account password -
                         generate one at myaccount.google.com/apppasswords;
                         requires 2-Step Verification to be on)

If either is unset, send_email() logs a warning and returns False instead
of raising - local dev and not-yet-configured deployments keep working,
same graceful-degradation pattern as Google sign-in's 501.
"""

import os
import smtplib
from email.mime.text import MIMEText

SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
SMTP_APP_PASSWORD = os.environ.get("SMTP_APP_PASSWORD")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(to, subject, body):
    """Returns True if sent, False if email isn't configured or sending failed
    (logged, never raised - a notification email bouncing shouldn't break the
    request that triggered it, e.g. an account deletion)."""
    if not (SMTP_EMAIL and SMTP_APP_PASSWORD):
        print(f"[email] not configured - would have sent to {to!r}: {subject!r}")
        return False
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_EMAIL
    msg["To"] = to
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_APP_PASSWORD)
            server.sendmail(SMTP_EMAIL, [to], msg.as_string())
        return True
    except smtplib.SMTPException as e:
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
