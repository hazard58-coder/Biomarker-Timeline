# Connecting your Stripe account

The hosted tool only needs your Stripe **secret key**. Everything else is
optional. You can do all of this in **Test mode** first (toggle, top-right of the
Stripe dashboard), then flip to Live when you're ready to take real money.

---

## 1. Create / log into Stripe
Go to <https://dashboard.stripe.com>, sign up or log in. Keep the dashboard in
**Test mode** until step 6.

## 2. Get your secret key
1. **Developers → API keys** (<https://dashboard.stripe.com/test/apikeys>).
2. Under **Secret key**, click **Reveal** and copy it.
   - Test key starts with `sk_test_…`
   - Live key starts with `sk_live_…`
3. Treat it like a password. **Never** paste it into code, commits, or chat —
   only into Railway's Variables (next step). The app reads it from the
   environment; it is never stored in the repo.

That one key is enough — the tool builds an inline **$79 one-time** charge.

## 3. Add the variables in Railway
Railway project → your service → **Variables** tab → add:

| Variable | Value |
|----------|-------|
| `STRIPE_SECRET_KEY` | your `sk_test_…` key |
| `GATE_SECRET` | a long random string (signs the access cookie) |
| `APP_BASE_URL` | your public URL, e.g. `https://your-service.up.railway.app` |

Generate a `GATE_SECRET`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Railway redeploys when you save. Once `STRIPE_SECRET_KEY` is set, `/app` shows a
**"Pay $79 & continue"** button instead of being open.

> **`APP_BASE_URL` matters.** After paying, Stripe returns the customer to
> `…/app?session_id=…`, where the app verifies the payment. Set it to the exact
> domain Railway gave you (**Settings → Networking → Generate Domain**).

## 4. Test it (test mode)
1. Open `https://your-service.up.railway.app/app`.
2. Click **Pay $79 & continue**.
3. On Stripe's page use test card **`4242 4242 4242 4242`**, any future expiry,
   any CVC, any ZIP.
4. You're redirected back to `/app` with the upload form. Upload labs and confirm
   a report downloads. (No real money moves in test mode.)

## 5. (Optional) Use saved Prices instead of the inline amounts
Only if you'd rather manage prices in Stripe's catalog:
1. **Product catalog → Add product.**
   - For the one-time report, add a **one-time** $79 price → copy its `price_…`
     into Railway as `STRIPE_PRICE_ID`.
   - For the subscription, add a **recurring / monthly** $29 price → copy its
     `price_…` into Railway as `STRIPE_SUBSCRIPTION_PRICE_ID`.
2. Without these, the app uses inline prices (`REPORT_PRICE_CENTS` /
   `SUBSCRIPTION_PRICE_CENTS`, default $79 / $29).

### The two plans on `/app`
With Stripe configured, the paywall offers both: **Pay $79** (one-time, one
report) and **Subscribe $29/mo** (recurring, ongoing updates). The monthly plan
uses Stripe's subscription mode, so you're billed monthly automatically. The
one-time plan is metered to one report; the subscription is not.

## 5b. Subscriber sign-in & the billing portal
So monthly subscribers can come back and generate reports on their own:

1. **Enable the Stripe Billing customer portal** (one time):
   **Settings → Billing → Customer portal** → activate it (allow customers to
   cancel/update). This is what `/portal` opens.
2. **Set up email** so the app can send sign-in links. Add these Railway
   variables (any SMTP provider — Gmail app password, Resend, SendGrid SMTP, etc.):
   - `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USERNAME`, `SMTP_PASSWORD`
   - `MAIL_FROM`, e.g. `Vitalis Forge <contact@vitalisforge.com>`

How it works: a subscriber returns within 30 days → `/app` re-checks Stripe and
just lets them in. On a new device or later, they go to `/login`, enter their
email, and get a magic link (valid 30 min) that signs them in after the app
re-confirms their subscription is active. They manage or cancel at `/portal`.
Without SMTP configured, sign-in links can't be sent and returning subscribers
are told to email you — everything else still works.

## 6. Go live
1. Flip the dashboard from **Test** to **Live** and finish account activation
   (business details + bank account for payouts).
2. Copy your **live** secret key (`sk_live_…`) from **Developers → API keys** in
   live mode.
3. In Railway, replace `STRIPE_SECRET_KEY` with the `sk_live_…` key (and, if you
   used saved Prices, replace `STRIPE_PRICE_ID` / `STRIPE_SUBSCRIPTION_PRICE_ID`
   with their live `price_…` IDs — test and live IDs differ).
4. Make one real $79 purchase to confirm, then refund it from the dashboard if
   you like.

---

## Free / half-price trials (no Stripe needed)
Set a Railway variable `ACCESS_CODES` to comma-separated codes, e.g.
`TRIAL50,FRIEND`. Give a client a code; they enter it under **"Have a trial
code?"** on `/app` and skip payment. Codes and Stripe can run at the same time.

## Good to know
- **One report per payment.** Each payment yields exactly one delivered report.
  Stripe is the source of truth for whether a session was paid, and a small
  SQLite store (`ENTITLEMENT_DB`) records which paid sessions were used. A payment
  is only marked used *after* a report is successfully delivered, so a self-check
  failure never burns a customer's payment.
- **Make it durable on Railway.** The container filesystem is ephemeral. To keep
  the consumed-record across redeploys, add a **Volume** to the service and set
  `ENTITLEMENT_DB` to a path on it (e.g. `/data/entitlements.db`). Without a
  volume, a paid entitlement is still never lost — at worst a customer could
  regenerate a report they already got after a redeploy.
- All gating variables are summarized in the README's "Gating the tool" table.

## Quick reference — all gating variables

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `STRIPE_SECRET_KEY` | for payments | Enables Stripe Checkout |
| `GATE_SECRET` | yes in production | Signs the access cookie |
| `APP_BASE_URL` | recommended | Public origin for Stripe return URLs |
| `STRIPE_PRICE_ID` | optional | Catalog Price for the one-time report (else inline $79) |
| `REPORT_PRICE_CENTS` | optional | Inline one-time price in cents (default `7900`) |
| `STRIPE_SUBSCRIPTION_PRICE_ID` | optional | Recurring Price for the $29/mo plan (else inline) |
| `SUBSCRIPTION_PRICE_CENTS` | optional | Inline monthly price in cents (default `2900`) |
| `ACCESS_CODES` | optional | Comp/trial codes |
| `ACCESS_TTL_SECONDS` | optional | Access cookie length (default `7200`) |
| `ENTITLEMENT_DB` | optional | SQLite path for consumed-payment records (default `data/entitlements.db`; point at a Railway volume for durability) |
