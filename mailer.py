"""Mailer for subscriber/admin sign-in (magic) links.

Two transports, preferred in this order:
  1. Resend HTTP API  — set RESEND_API_KEY (and MAIL_FROM). Sends over HTTPS:443,
     which avoids PaaS hosts that block outbound SMTP ports (the usual cause of
     "timed out"). This is the recommended setup on Railway.
  2. SMTP             — SMTP_HOST/PORT/USERNAME/PASSWORD/MAIL_FROM.

If neither is configured, mail_configured() is False and the web app degrades
gracefully.

  RESEND_API_KEY  Resend API key (re_...). Enables the HTTP transport.
  MAIL_FROM       From address, e.g. "Vitalis Forge <contact@vitalisforge.com>"
                  (must be a verified Resend domain; or "onboarding@resend.dev"
                  to test before your domain is verified).
  SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD / SMTP_STARTTLS  (SMTP only)
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "").strip()
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "").strip()
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1").strip() != "0"


def transport() -> str:
    if RESEND_API_KEY and (MAIL_FROM or True):
        return "resend-http"
    if SMTP_HOST and MAIL_FROM:
        return "smtp"
    return "none"


def mail_configured() -> bool:
    return transport() != "none"


def missing_config() -> list[str]:
    if RESEND_API_KEY:
        return [] if MAIL_FROM else ["MAIL_FROM"]
    miss = []
    if not SMTP_HOST:
        miss.append("SMTP_HOST (or set RESEND_API_KEY)")
    if not MAIL_FROM:
        miss.append("MAIL_FROM")
    return miss


def diagnostics() -> dict:
    return {
        "configured": mail_configured(),
        "transport": transport(),
        "mail_from": MAIL_FROM or "(unset)",
        "resend_api_key_set": bool(RESEND_API_KEY),
        "smtp_host": SMTP_HOST or "(unset)",
        "smtp_port": SMTP_PORT,
        "smtp_username_set": bool(SMTP_USERNAME),
        "smtp_password_set": bool(SMTP_PASSWORD),
        "starttls": SMTP_STARTTLS,
        "missing": missing_config(),
    }


def send_test(to: str) -> str:
    """Send a test email; return 'OK' or the exact error string."""
    try:
        send_email(to, "Biomarker Timeline — email test",
                   "This is a test email. If you received it, email is working.")
        return "OK"
    except Exception as exc:
        return f"ERROR — {type(exc).__name__}: {exc}"


def _send_via_resend(to: str, subject: str, body: str) -> None:
    payload = json.dumps({
        "from": MAIL_FROM or "Biomarker Timeline <onboarding@resend.dev>",
        "to": [to],
        "subject": subject,
        "text": body,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=payload, method="POST",
        headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"Resend API {resp.status}: {resp.read().decode('utf-8', 'replace')[:400]}")
    except urllib.error.HTTPError as exc:
        # Surface Resend's actual error body (e.g. domain/key/from problem),
        # not just "403 Forbidden".
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise RuntimeError(f"Resend API {exc.code}: {detail or exc.reason}") from None


def _send_via_smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if SMTP_STARTTLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as server:
            server.starttls(context=ssl.create_default_context())
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT,
                              context=ssl.create_default_context(), timeout=20) as server:
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via the configured transport. Raises on failure."""
    t = transport()
    if t == "resend-http":
        _send_via_resend(to, subject, body)
    elif t == "smtp":
        _send_via_smtp(to, subject, body)
    else:
        raise RuntimeError("email is not configured (set RESEND_API_KEY or SMTP_*)")


def send_magic_link(to: str, link: str) -> None:
    body = (
        "Here's your sign-in link for Biomarker Timeline:\n\n"
        f"{link}\n\n"
        "It works for the next 30 minutes. If you didn't request this, you can "
        "ignore this email.\n\n"
        "— Vitalis Forge"
    )
    send_email(to, "Your Biomarker Timeline sign-in link", body)
