# Biomarker Timeline

**A report produced under the Vitalis Forge wellness brand.**

You get bloodwork every 8–12 weeks. The results land in different PDFs, in
different patient portals, from different labs — and you can never actually
*see* your own trend. Biomarker Timeline takes a folder of your own lab PDFs and
turns them into one clean, printable report that trends every biomarker over
time, side by side with each lab's own reference range.

It is a **data-organization** tool. It does not interpret your results. See
[The legal guardrail](#the-legal-guardrail).

---

## The offer

- **Product name:** Biomarker Timeline (a report produced under the founder's
  wellness brand, Vitalis Forge)
- **Buyer:** People on TRT/HRT/peptide protocols who get bloodwork every 8–12
  weeks and can't see their own progress over time.
- **Deliverable:** A single polished PDF report that extracts every biomarker
  from the client's own uploaded lab PDFs (across multiple draw dates) and
  trends each one over time — clean charts, a master data table, and clear flags
  wherever a value falls outside the lab's OWN printed reference range. Designed
  to be printed and handed to their own doctor.
- **Price:** **$79 one-time per report**, or **$29/month** to keep it updated
  each draw.

---

## The legal guardrail

This report **ORGANIZES and VISUALIZES the client's own data. It does NOT
interpret, diagnose, recommend, or advise.**

- It may state a value and the lab's own printed reference range, and factually
  flag "outside the lab's stated range." That is transcription.
- It will **never** say what a value means for the person, suggest a cause,
  recommend a dose, supplement, or action, or use judgment words.
- Every page footer and a full first-page disclaimer state: this is a
  data-organization report, not medical advice, and the client should review all
  results with a licensed physician.

This guardrail is enforced in software: the **self-check stage scans the entire
rendered report for banned interpretive words and halts the build if any are
found** (see [Stage 3](#stage-3--self-check-mandatory)).

---

## What's in the box

```
Biomarker-Timeline/
├── README.md                  ← you are here
├── OPERATIONS.md              ← customer & operator flow guide (how a report gets made/delivered)
├── STRIPE_SETUP.md            ← step-by-step: connect your Stripe account
├── PLAN.md                    ← 7-day launch plan
├── MESSAGES.md                ← 5 first-contact message templates
├── landing.html               ← single-file landing page
├── webapp.py                  ← hosted web service: upload PDFs in a browser, download the report
├── Dockerfile / railway.json  ← Railway deploy config (web service)
├── requirements.txt
├── pyproject.toml
├── input/                     ← put a client's lab PDFs here
├── output/                    ← finished report lands here
├── samples/                   ← the complete worked example (committed)
│   ├── source_labs/           ← synthetic LabCorp/Quest source PDFs (4 draws)
│   └── Marcus_Hale_Biomarker_Timeline_SAMPLE.pdf   ← the finished sample report
├── src/biomarker_timeline/    ← the pipeline
│   ├── intake.py              ← Stage 1: read PDFs
│   ├── extract.py             ← Stage 2: pull biomarkers, build time series
│   ├── selfcheck.py           ← Stage 3: mandatory quality gate
│   ├── report.py              ← Stage 4: render the branded PDF
│   ├── charts.py              ← trend charts (matplotlib)
│   ├── markers.py             ← canonical markers + synonym normalization
│   ├── theme.py               ← Vitalis Forge palette + embedded fonts
│   └── assets/fonts/          ← vendored Oswald + Inter (no network needed)
└── tools/
    ├── make_sample.py         ← regenerates the sample end to end
    └── build_fonts.py         ← re-vendors the fonts (rarely needed)
```

---

## How to run it (step by step)

This is a command-line script. It works on Mac, Windows, Linux, and **GitHub
Codespaces**. Every command below is copy-pasteable. You do **not** need to know
how to code.

### One-time setup

In Codespaces, open the terminal (the panel at the bottom; if you don't see it,
press <kbd>Ctrl</kbd>+<kbd>`</kbd>). Then paste this and press Enter:

```bash
pip install -e .
```

That installs everything the tool needs. You only do this once per Codespace.

> If WeasyPrint reports a missing system library, run:
> `sudo apt-get update && sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev`
> (Codespaces usually already has these.)

### Make a report for a client

1. **Put the client's lab PDFs in the `input/` folder.** Drag them in. They can
   be from LabCorp, Quest, or any lab, across as many draw dates as you have.

2. **Run the tool.** Paste this and press Enter:

   ```bash
   biomarker-timeline
   ```

3. **Read the self-check.** The tool prints a `PASS`/`FAIL` line for six quality
   checks. If everything passes, your report appears at
   `output/biomarker_timeline.pdf`.

That's it. Open the PDF, and you have the deliverable.

### Useful variations

```bash
# Put the client's name on the cover (otherwise it's auto-detected):
biomarker-timeline --name "Jane Doe"

# Choose where the report is saved:
biomarker-timeline input/ -o output/jane_doe_report.pdf

# If `biomarker-timeline` isn't found for any reason, this always works:
python -m biomarker_timeline
```

### See the worked example without any setup

A finished sample report is already in the repo:
`samples/Marcus_Hale_Biomarker_Timeline_SAMPLE.pdf`. To regenerate it from
scratch (synthetic labs → full pipeline → finished PDF):

```bash
python tools/make_sample.py
```

---

## The hosted web service (upload in a browser)

Besides the local CLI, the tool can run as a hosted web service so a client can
**upload their lab PDFs in a browser and download the finished report** — the
same four-stage pipeline runs server-side. It's deployed on **Railway** (not
Vercel or Supabase), built from the `Dockerfile`.

Routes:

| Route | What it is |
|-------|------------|
| `/` | the public landing page (`landing.html`) |
| `/app` | the upload tool — pick PDFs, optional name, get a report |
| `/login` · `/verify` | subscriber sign-in via emailed magic link |
| `/portal` | Stripe Billing customer portal (manage/cancel subscription) |
| `/sample.pdf` | the finished sample report (so prospects can see a real one) |
| `/healthz` | health check for Railway |

**The site shares one sticky nav** (Pricing · FAQ · Sign in · Get started) across
the landing page and the app pages, so it reads as a single product. The landing
page's "Get started" buttons go to `/app`; access there is controlled by the
paywall/gating (below), not by hiding the link.

**The guardrail still holds in the browser:** the mandatory self-check runs on
every upload. If it fails, the service does **not** return a report — it shows
the items a human must verify and points the visitor to your email. An
unreviewed report is never shipped, on the web or the CLI.

### Gating the tool (payment + trial codes)

By default `/app` is **open** so a fresh deploy works immediately. You switch on
gating purely with environment variables — no code change, no database. Access is
granted with a signed, time-limited cookie.

| Variable | What it does |
|----------|--------------|
| `STRIPE_SECRET_KEY` | Enables Stripe Checkout. Visitors pay before they can upload. |
| `STRIPE_PRICE_ID` | *(optional)* Use a specific Stripe Price for the one-time report; otherwise an inline `$79` price is used. |
| `REPORT_PRICE_CENTS` | *(optional)* Inline one-time price in cents (default `7900` = $79). |
| `STRIPE_SUBSCRIPTION_PRICE_ID` | *(optional)* Use a specific recurring Stripe Price for the `$29/mo` plan; otherwise an inline monthly price is used. |
| `SUBSCRIPTION_PRICE_CENTS` | *(optional)* Inline monthly price in cents (default `2900` = $29). |
| `ACCESS_CODES` | Comma-separated comp/trial codes (e.g. `TRIAL50,FRIEND`). Hand these out for the free or half-price trial reports. |
| `APP_BASE_URL` | *(optional)* Public origin for Stripe return URLs, e.g. `https://yourapp.up.railway.app`. Auto-derived from the request if unset. |
| `GATE_SECRET` | Secret used to sign access cookies. **Set this in production** to a long random string. |
| `ACCESS_TTL_SECONDS` | *(optional)* How long the access cookie lasts after payment/unlock (default `7200` = 2 h). |
| `ENTITLEMENT_DB` | *(optional)* Path to the SQLite store that records consumed payments (default `data/entitlements.db`). |
| `ACCOUNT_TTL_SECONDS` | *(optional)* How long a signed-in account stays signed in (default `2592000` = 30 days). |
| `LOGIN_REQUIRED` | *(optional)* Set to `1` for **account-first mode**: visitors sign in (email magic link) before buying or generating. Off by default (guest checkout). Requires email (SMTP) configured. |
| `DEV_SHOW_MAGIC_LINK` | *(testing only)* Set to `1` to show the sign-in link on screen when SMTP isn't configured, so you can test account mode without email. **Never enable in production** — it lets anyone sign in as any email. |
| `ADMIN_EMAILS` | Comma-separated admin emails with unlimited free access once signed in (default `hazard58@gmail.com`). |
| `MAGIC_LINK_TTL_SECONDS` | *(optional)* How long a sign-in link is valid (default `1800` = 30 min). |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `MAIL_FROM` | Email settings for sending subscriber sign-in links. Without these, subscriber email sign-in is disabled (they're told to email you). |

- Set **`STRIPE_SECRET_KEY`** to charge for reports, **`ACCESS_CODES`** to hand out
  trials, or **both** (the paywall shows the Pay options *and* a code field).
- Set **neither** and `/app` stays open.
- With Stripe configured, `/app` offers **both** plans: a one-time **$79** report
  and a recurring **$29/mo** subscription. The one-time plan is metered to one
  report (above); the subscription is **not** metered — it covers ongoing updates.

> **Returning subscribers self-serve.** A subscriber stays signed in via a signed
> account cookie for `ACCOUNT_TTL_SECONDS` (30 days) — when they come back, `/app`
> re-checks their subscription live with Stripe and lets them generate again.
> After that, or on a new device, they sign in at `/login`: they enter their email
> and get a magic link (needs SMTP configured). They can manage or cancel the plan
> at `/portal` (Stripe's Billing customer portal — enable it once in the Stripe
> dashboard, see `STRIPE_SETUP.md`). Stripe is the source of truth for "is this
> subscription active," so there are still no passwords or user database.

> **Strict one report per payment.** Each Stripe payment yields exactly one
> delivered report. Stripe is the source of truth for whether a session was paid
> (re-verified live, so a paid entitlement survives any redeploy), and a small
> SQLite store records which paid sessions have been *consumed*. A payment is
> consumed only after a report is successfully delivered — a self-check failure
> never burns a customer's payment. (Trial-code access is operator-controlled and
> not metered.)
>
> The consumed-record lives at `ENTITLEMENT_DB`. Railway's container filesystem
> is ephemeral, so for durability across redeploys, add a **Volume** to the
> service and set `ENTITLEMENT_DB` to a path on it (e.g. `/data/entitlements.db`).
> Without a volume, the only downside is a customer could regenerate a report they
> already received after a redeploy — a paid entitlement is never lost.

### Two access models

- **Guest checkout (default).** Visitor pays → gets their report → can buy another.
  Identity is a short-lived cookie; one-time payments are metered by the SQLite
  store. Simplest; nothing to configure beyond Stripe.
- **Account-first (`LOGIN_REQUIRED=1`).** Visitor signs in with an **email magic
  link**, then buys or subscribes. Purchases attach to their **account**: each
  one-time payment is a **report credit**, a subscription is unlimited while
  active, and they can return anytime and sign back in. This is the durable model
  for repeat customers. It needs **SMTP configured** (to send sign-in links); for
  testing without email, set `DEV_SHOW_MAGIC_LINK=1`. Stripe stays the source of
  truth for subscriptions; the store tracks one-time credits per email.

Both keep the legal guardrail identical — the self-check runs on every report
regardless of how access was granted.

### Coupon / discount codes

Stripe's checkout page shows an **"Add promotion code"** field automatically. You
create the actual codes in the **Stripe Dashboard → Product catalog → Coupons**:
make a coupon (e.g. *15% off*, *25% off*, *50% off*, *100% off*), then add a
**promotion code** (the text customers type, e.g. `SAVE15`). Stripe validates and
redeems them — no app changes needed. A 100%-off code makes the report free
through normal checkout (it still becomes a report credit for that account).

### Admin access

Emails in `ADMIN_EMAILS` (default `hazard58@gmail.com`) get **unlimited free
access** once signed in — sign in at `/login` with that email, and `/app`/
`/generate` work with no payment. Use it for yourself and comped accounts.

In Railway, add these under the service's **Variables** tab.

**Report & extraction settings** (optional, apply to the CLI and the web service):

| Variable | What it does |
|----------|--------------|
| `CONFIDENCE_REVIEW_THRESHOLD` | Extraction-accuracy gate (default `0.80`). Values read below this confidence are routed to human review. This is the accuracy knob — it does **not** relax the legal no-interpretation guardrail. |
| `COACHING_HANDOFF` | Text for the closing-page "separate option" coaching handoff. Leave unset for the default wording, or set to `off` to hide it. The handoff describes a separate service only — the report itself never interprets. |
| `ANTHROPIC_API_KEY` | Enables the **AI extraction fallback** (Claude). When set, layouts the regex parser misses are read by Claude — transcription only. Leave unset for regex-only. |
| `AI_EXTRACT_MODEL` | *(optional)* Claude model for the fallback (default `claude-sonnet-4-6`). |
| `AI_EXTRACT` | *(optional)* Set to `0` to disable the AI fallback even when a key is present. |
| `AI_KNOWN_ONLY` | *(optional)* Set to `1` so the AI fallback only fills markers in the curated dictionary (no "Other" markers like sodium/BUN) — keeps the report to your panel. Default includes everything found. |

### AI extraction fallback & coverage

With `ANTHROPIC_API_KEY` set, regex runs first (fast, free, deterministic) and
Claude fills the gaps — reading any lab layout and the long tail of markers,
strictly as **transcription**. The mandatory self-check still re-verifies every
value against the source text and scans for banned words, so the AI can't invent
a number or smuggle in interpretation. Every run also writes
`output/coverage.txt`: per file, how many markers were captured and which
result-looking lines were **not** — so nothing is silently dropped.

### Run the web service locally

```bash
pip install -e .            # if you haven't already
pip install flask gunicorn  # web-only deps (also in requirements.txt)
python webapp.py            # then open http://localhost:8080
```

### Deploy on Railway

1. Push this repo to GitHub (already done if you're reading this on GitHub).
2. In [Railway](https://railway.app), create a new project →
   **Deploy from GitHub repo** → pick this repo.
3. Railway reads `railway.json`, builds the `Dockerfile` (which installs the
   system libraries WeasyPrint needs), and starts `gunicorn webapp:app`. No
   environment variables are required — Railway provides `PORT`.
4. Under **Settings → Networking**, click **Generate Domain** for a public URL.
   Your landing page is at `/`; hand clients the `…/app` link to upload labs.

> Prefer the Railway CLI? `npm i -g @railway/cli`, then `railway login` and
> `railway up` from this folder.

> **Privacy:** uploaded files are written to a temporary folder, processed, and
> deleted as soon as the report is returned. Nothing is persisted on the server.

> **Memory:** the `Dockerfile` runs 2 gunicorn workers, which suits a
> personal-scale tool. If your Railway plan is memory-constrained, drop to
> `--workers 1` in the `Dockerfile` `CMD`.

---

## The pipeline (the repeatable workflow)

The deliverable is produced by four explicit stages. This is the workflow you
repeat for every client.

### Stage 1 — INTAKE
Reads every PDF in `input/`. Handles multiple labs from multiple draw dates.

### Stage 2 — EXTRACT
For each lab, pulls every biomarker as `{name, value, unit, reference_range,
draw_date}` with a **per-value confidence score**. Synonyms are normalized to a
single canonical marker (e.g. "Testosterone, Total" / "Total Testosterone" /
"TESTOSTERONE,TOTAL" → one marker), and a time series is built per marker across
all dates.

### Stage 3 — SELF-CHECK (mandatory)
Runs **before any report is generated** and prints `PASS`/`FAIL` for each item:

1. Every extracted value re-verified against the source text; no invented markers or numbers.
2. Any value with low extraction confidence is flagged for human review, not silently included.
3. Every draw date parsed and ordered correctly.
4. Units consistent within each marker across dates (mismatches flagged).
5. Each marker's reference range captured where printed.
6. No interpretive language anywhere in the output (scans for banned judgment words).

**If any check FAILs, the build halts and writes `output/review_needed.txt`
listing exactly what a human must verify. An unreviewed report is never
shipped.**

### Stage 4 — OUTPUT
Renders the branded PDF: a cover page with the full disclaimer, one trend chart
per biomarker (value over time with the reference band shaded), a master data
table, and a closing "bring this to your physician" page.

---

## Notes for the operator

- **Privacy:** `input/` and `output/` are git-ignored, so real client PDFs and
  generated reports are never committed. Only the synthetic `samples/` are.
- **The sample is fictional.** "Marcus Hale" and every value in `samples/` are
  invented for demonstration and carry no medical meaning.
- **When the self-check fails, that's the tool working.** Open
  `output/review_needed.txt`, verify the listed values against the source PDF,
  and re-run. Never hand a client a report that hasn't passed.
