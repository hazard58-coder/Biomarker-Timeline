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
REPORT_PRICE_CENTS = int(os.environ.get("REPORT_PRICE_CENTS", "7900"))  # $79.00 one-time
SUBSCRIPTION_PRICE_CENTS = int(os.environ.get("SUBSCRIPTION_PRICE_CENTS", "2900"))  # $29.00/mo
ACCESS_CODES = {c.strip() for c in os.environ.get("ACCESS_CODES", "").split(",") if c.strip()}
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "").strip()  # one-time Price (optional)
STRIPE_SUBSCRIPTION_PRICE_ID = os.environ.get("STRIPE_SUBSCRIPTION_PRICE_ID", "").strip()  # recurring Price (optional)
ACCESS_TTL_SECONDS = int(os.environ.get("ACCESS_TTL_SECONDS", str(2 * 60 * 60)))  # 2 hours
ACCOUNT_TTL_SECONDS = int(os.environ.get("ACCOUNT_TTL_SECONDS", str(30 * 24 * 60 * 60)))  # 30 days
MAGIC_LINK_TTL_SECONDS = int(os.environ.get("MAGIC_LINK_TTL_SECONDS", str(30 * 60)))  # 30 min
_GATE_SECRET = (os.environ.get("GATE_SECRET")
                or os.environ.get("SECRET_KEY")
                or "dev-insecure-secret-change-me-in-production")

_serializer = URLSafeTimedSerializer(_GATE_SECRET, salt="biomarker-timeline-access")
_account_serializer = URLSafeTimedSerializer(_GATE_SECRET, salt="biomarker-timeline-account")
_magic_serializer = URLSafeTimedSerializer(_GATE_SECRET, salt="biomarker-timeline-magic")


def gating_enabled() -> bool:
    """True if any access path is configured. If False, /app is open."""
    return bool(STRIPE_SECRET_KEY or ACCESS_CODES)


def stripe_configured() -> bool:
    return bool(STRIPE_SECRET_KEY)


def codes_configured() -> bool:
    return bool(ACCESS_CODES)


def _money(cents: int) -> str:
    dollars = cents / 100
    return f"${dollars:,.0f}" if dollars == int(dollars) else f"${dollars:,.2f}"


def price_display() -> str:
    return _money(REPORT_PRICE_CENTS)


def subscription_price_display() -> str:
    return _money(SUBSCRIPTION_PRICE_CENTS)


# --- access tokens (signed cookie) ---
def issue_token(kind: str, ref: str, plan: str | None = None) -> str:
    """Mint an access token. `kind` is 'stripe' or 'code'; `ref` is the session
    id or code label; `plan` is 'once' or 'sub' for Stripe access (None for codes)."""
    return _serializer.dumps({"k": kind, "ref": ref, "plan": plan})


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


# --- subscriber accounts (signed cookie; Stripe is the source of truth) ---
def issue_account_token(customer_id: str, email: str) -> str:
    return _account_serializer.dumps({"cust": customer_id, "email": email})


def read_account_token(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        data = _account_serializer.loads(token, max_age=ACCOUNT_TTL_SECONDS)
        return data if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired):
        return None


def issue_magic_token(email: str) -> str:
    return _magic_serializer.dumps({"email": email})


def read_magic_token(token: str | None) -> str | None:
    if not token:
        return None
    try:
        data = _magic_serializer.loads(token, max_age=MAGIC_LINK_TTL_SECONDS)
        return data.get("email") if isinstance(data, dict) else None
    except (BadSignature, SignatureExpired):
        return None


# --- Stripe Checkout ---
def create_checkout_session(base_url: str, plan: str = "once") -> str:
    """Create a Stripe Checkout Session and return its hosted URL.

    `plan` is 'once' (one-time $79 report) or 'monthly' (recurring $29/mo).
    `base_url` is the public origin, used to build the success/cancel URLs.
    """
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    if plan == "monthly":
        mode = "subscription"
        if STRIPE_SUBSCRIPTION_PRICE_ID:
            line_item = {"price": STRIPE_SUBSCRIPTION_PRICE_ID, "quantity": 1}
        else:
            line_item = {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": SUBSCRIPTION_PRICE_CENTS,
                    "recurring": {"interval": "month"},
                    "product_data": {
                        "name": "Biomarker Timeline — monthly",
                        "description": "Keep your timeline updated with each new draw.",
                    },
                },
            }
    else:
        mode = "payment"
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
        mode=mode,
        line_items=[line_item],
        success_url=f"{base_url}/app?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/app?canceled=1",
    )
    return session.url


def subscription_active(customer_id: str) -> bool:
    """True if the Stripe customer has an active or trialing subscription."""
    if not customer_id:
        return False
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    for status in ("active", "trialing"):
        try:
            subs = stripe.Subscription.list(customer=customer_id, status=status, limit=1)
        except Exception:
            return False
        if subs.get("data"):
            return True
    return False


def find_active_subscription_customer(email: str) -> str | None:
    """Find a Stripe customer with the given email that has an active subscription.
    Returns the customer id, or None. Used for returning-subscriber sign-in."""
    if not email:
        return None
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    try:
        customers = stripe.Customer.list(email=email.strip(), limit=10)
    except Exception:
        return None
    for cust in customers.get("data", []):
        if subscription_active(cust.get("id")):
            return cust.get("id")
    return None


def create_billing_portal_session(customer_id: str, return_url: str) -> str:
    """Create a Stripe Billing customer-portal session and return its URL."""
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    session = stripe.billing_portal.Session.create(
        customer=customer_id, return_url=return_url)
    return session.url


def checkout_session_info(session_id: str) -> dict:
    """Verify a returned Checkout Session and return details.

    Returns {active, plan, customer, email}. `plan` is 'once' or 'sub'.
    """
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return {"active": False, "plan": "once", "customer": None, "email": None}

    customer = session.get("customer")
    email = (session.get("customer_details") or {}).get("email")

    if session.get("mode") == "subscription":
        active = session.get("payment_status") == "paid" and bool(session.get("subscription"))
        if active:
            sub_id = session.get("subscription")
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                active = sub.get("status") in ("active", "trialing")
            except Exception:
                pass
        return {"active": active, "plan": "sub", "customer": customer, "email": email}

    return {"active": session.get("payment_status") == "paid",
            "plan": "once", "customer": customer, "email": email}


def checkout_session_status(session_id: str) -> tuple[bool, str]:
    """Verify a returned Checkout Session (live API call).

    Returns (active, plan) where plan is 'once' or 'sub'. For one-time payments,
    active means the payment is paid. For subscriptions, active means the first
    invoice is paid and the subscription is in an active/trialing state.
    """
    import stripe

    stripe.api_key = STRIPE_SECRET_KEY
    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return False, "once"

    if session.get("mode") == "subscription":
        if session.get("payment_status") != "paid":
            return False, "sub"
        sub_id = session.get("subscription")
        if not sub_id:
            return False, "sub"
        try:
            sub = stripe.Subscription.retrieve(sub_id)
            return sub.get("status") in ("active", "trialing"), "sub"
        except Exception:
            # First invoice paid but couldn't load the subscription — treat as active.
            return True, "sub"

    return session.get("payment_status") == "paid", "once"
