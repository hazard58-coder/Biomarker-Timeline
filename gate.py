"""Access / payment gating for the hosted /app tool.

Two ways in, both optional and configured by environment variables:

  1. Stripe Checkout — a one-time payment for a report. Set STRIPE_SECRET_KEY
     (and optionally STRIPE_PRICE_ID; otherwise an inline $79 price is used).
  2. Comp / trial codes — set ACCESS_CODES to a comma-separated list. Hand these
     to clients for the free or half-price trial reports.

If NEITHER is configured, gating is OFF and /app is open — so a fresh deploy
works immediately, and you switch gating on just by setting env vars.

No database: access is granted via a signed, time-limited cookie (itsdangerous).
A paid Checkout session or a valid code mints a token good for ACCESS_TTL_SECONDS.
"""

from __future__ import annotations

import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "bt_access"

# --- configuration (read once at import) ---
REPORT_PRICE_CENTS = int(os.environ.get("REPORT_PRICE_CENTS", "7900"))  # $79.00
ACCESS_CODES = {c.strip() for c in os.environ.get("ACCESS_CODES", "").split(",") if c.strip()}
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "").strip()
ACCESS_TTL_SECONDS = int(os.environ.get("ACCESS_TTL_SECONDS", str(2 * 60 * 60)))  # 2 hours
_GATE_SECRET = (os.environ.get("GATE_SECRET")
                or os.environ.get("SECRET_KEY")
                or "dev-insecure-secret-change-me-in-production")

_serializer = URLSafeTimedSerializer(_GATE_SECRET, salt="biomarker-timeline-access")


def gating_enabled() -> bool:
    """True if any access path is configured. If False, /app is open."""
    return bool(STRIPE_SECRET_KEY or ACCESS_CODES)


def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def codes_configured() -> bool:
    return bool(ACCESS_CODES)


def price_display() -> str:
    dollars = REPORT_PRICE_CENTS / 100
    return f"${dollars:,.0f}" if dollars == int(dollars) else f"${dollars:,.2f}"


# --- access tokens (signed cookie) ---
def issue_token(kind: str, ref: str) -> str:
    """Mint an access token. `kind` is 'stripe' or 'code'; `ref` is the session
    id or code label, recorded for traceability."""
    return _serializer.dumps({"k": kind, "ref": ref})


def token_is_valid(token: str | None) -> bool:
    return read_token(token) is not None


def read_token(token: str | None) -> dict | None:
    """Return the token payload {'k': kind, 'ref': ref} if valid, else None."""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=ACCESS_TTL_SECONDS)
        return data if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired):
        return None


def code_is_valid(code: str | None) -> bool:
    return bool(code) and code.strip() in ACCESS_CODES


# --- Stripe Checkout ---
def create_checkout_session(base_url: str) -> str:
    """Create a Stripe Checkout Session and return its hosted URL.

    `base_url` is the public origin (e.g. https://yourapp.up.railway.app), used
    to build the success/cancel return URLs.
    """
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    if STRIPE_PRICE_ID:
        line_item = {"price": STRIPE_PRICE_ID, "quantity": 1}
    else:
        line_item = {
            "quantity": 1,
            "price_data": {
                "currency": "usd",
                "unit_amount": REPORT_PRICE_CENTS,
                "product_data": {
                    "name": "Biomarker Timeline — one report",
                    "description": "A single data-organization report from your lab PDFs.",
                },
            },
        }
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[line_item],
        success_url=f"{base_url}/app?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/app?canceled=1",
    )
    return session.url


def session_is_paid(session_id: str) -> bool:
    """Verify a returned Checkout Session was actually paid (live API call)."""
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return False
    return session.get("payment_status") == "paid"
