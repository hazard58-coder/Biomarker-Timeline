"""Minimal SMTP mailer for subscriber sign-in (magic) links.

Configured by environment variables; if SMTP isn't configured, mail_configured()
returns False and the web app degrades gracefully (it tells returning subscribers
to email the operator instead of silently failing).

  SMTP_HOST       e.g. smtp.gmail.com
  SMTP_PORT       default 587
  SMTP_USERNAME   SMTP auth user (often the full email address)
  SMTP_PASSWORD   SMTP auth password / app password
  MAIL_FROM       From address, e.g. "Vitalis Forge <contact@vitalisforge.com>"
  SMTP_STARTTLS   "1" (default) to use STARTTLS on SMTP_PORT, "0" for SMTP_SSL
"""

from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage

SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "").strip()
SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1").strip() != "0"


def mail_configured() -> bool:
    return bool(SMTP_HOST and MAIL_FROM)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises on failure."""
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


def send_magic_link(to: str, link: str) -> None:
    body = (
        "Here's your sign-in link for Biomarker Timeline:\n\n"
        f"{link}\n\n"
        "It works for the next 30 minutes. If you didn't request this, you can "
        "ignore this email.\n\n"
        "— Vitalis Forge"
    )
    send_email(to, "Your Biomarker Timeline sign-in link", body)
