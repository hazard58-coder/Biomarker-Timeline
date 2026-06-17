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

## 5. (Optional) Use a saved Price instead of the inline $79
Only if you'd rather manage the price in Stripe's catalog:
1. **Product catalog → Add product**, set a **one-time** price of $79.
2. Copy the **Price ID** (`price_…`).
3. Add Railway variable `STRIPE_PRICE_ID` = that `price_…`.

## 6. Go live
1. Flip the dashboard from **Test** to **Live** and finish account activation
   (business details + bank account for payouts).
2. Copy your **live** secret key (`sk_live_…`) from **Developers → API keys** in
   live mode.
3. In Railway, replace `STRIPE_SECRET_KEY` with the `sk_live_…` key (and
   `STRIPE_PRICE_ID` with the live Price ID if you used one — test and live IDs
   differ).
4. Make one real $79 purchase to confirm, then refund it from the dashboard if
   you like.

---

## Free / half-price trials (no Stripe needed)
Set a Railway variable `ACCESS_CODES` to comma-separated codes, e.g.
`TRIAL50,FRIEND`. Give a client a code; they enter it under **"Have a trial
code?"** on `/app` and skip payment. Codes and Stripe can run at the same time.

## Good to know
- **Access lasts 2 hours per payment** (a signed cookie — no database), so one
  payment can generate more than one report in that window. Fine to start; strict
  one-report-per-payment would need a small datastore.
- All gating variables are summarized in the README's
  "Gating the tool" table.

## Quick reference — all gating variables

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `STRIPE_SECRET_KEY` | for payments | Enables Stripe Checkout |
| `GATE_SECRET` | yes in production | Signs the access cookie |
| `APP_BASE_URL` | recommended | Public origin for Stripe return URLs |
| `STRIPE_PRICE_ID` | optional | Use a catalog Price instead of inline $79 |
| `REPORT_PRICE_CENTS` | optional | Inline price in cents (default `7900`) |
| `ACCESS_CODES` | optional | Comp/trial codes |
| `ACCESS_TTL_SECONDS` | optional | Access window length (default `7200`) |
