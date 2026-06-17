# Operations guide — customer & operator flows

How a report actually gets made and delivered, for both the person buying it (the
**customer**) and the person running the business (the **operator** — you). Two
ways to operate: the **hosted web service** and the **local CLI**. Use whichever
fits the moment.

---

## The non-negotiable rule
The report **organizes and visualizes** a client's own lab data. It **never**
interprets, diagnoses, recommends, or advises. When anyone asks "what does this
mean?", the answer is always: *"That's the conversation to have with your
physician."* The software enforces this (the self-check halts on interpretive
language); you enforce it in how you talk about the product.

---

## A. Customer flow — hosted web service

```
 Customer                         System
 ─────────                        ───────
 1. Opens /app  ───────────────▶  Gating check
                                  • open?  → upload form
                                  • Stripe? → paywall ("Pay $79")
                                  • code?   → paywall ("trial code")
 2. Pays via Stripe  ──────────▶  Stripe verifies, returns to /app?session_id=…
        OR enters a trial code ▶  Code checked
                                  → access cookie set (valid 2h)
 3. Uploads lab PDFs  ─────────▶  INTAKE → EXTRACT → SELF-CHECK → OUTPUT
 4a. Self-check PASSES  ───────▶  Branded PDF downloads; the payment is now
                                  marked used (one report per payment)
 4b. Self-check FAILS   ───────▶  "Needs a human first" page; no report shipped;
                                  payment NOT used; they email contact@vitalisforge.com
```

**One report per payment.** A Stripe payment produces exactly one delivered
report. If a paid customer returns and tries to generate a second time, they see
"That payment was already used" with a link to buy another. A payment is only
consumed once a report is actually delivered, so a self-check failure leaves it
intact. Trial-code access is not metered — it lasts the access window so you can
re-run during testing.

What the customer experiences:
1. Goes to the `/app` link you gave them.
2. Pays (Stripe) or enters a trial code.
3. Drags in their lab PDFs (any lab, any number of draws), optional name.
4. A few seconds later, either their report downloads, or they see a clear
   message that their files need a manual look (and your email).

Their files are processed in a temporary folder and **deleted** right after —
nothing is stored on the server.

---

## B. Operator flow — when the web service handles it
When a paying customer's upload **passes** the self-check, you do nothing — they
already have their report. Your job is only the exceptions:

- **A customer hits the "needs a human first" page.** They email you their PDFs.
  Run them through the **local CLI** (section C), read the self-check output,
  verify the flagged values against their source PDFs, and send the finished PDF
  back by email.
- **Refunds / billing questions.** Handle in the Stripe dashboard.
- **Trials.** Hand out `ACCESS_CODES` values to people you want to comp.

---

## C. Operator flow — local CLI (full control)
This is how you make a report by hand: for paid clients who emailed you files,
for trials, or any time the web self-check needs a human.

```bash
# one-time per machine / Codespace
pip install -e .

# 1. put the client's lab PDFs in input/
# 2. run it
biomarker-timeline --name "Client Name"

# 3. read the PASS/FAIL self-check in the terminal
#    • all PASS  → output/biomarker_timeline.pdf is your deliverable
#    • any FAIL  → open output/review_needed.txt, verify each listed value
#                  against the source PDF, fix/confirm, and run again
```

You never send a report that hasn't passed. That's the quality promise.

### What the four stages do (so you can read the output)
1. **INTAKE** — reads every PDF in `input/`.
2. **EXTRACT** — pulls each biomarker (name, value, unit, reference range, draw
   date) with a confidence score; merges synonyms across labs into one trend.
3. **SELF-CHECK** — six checks; prints `PASS`/`FAIL`; halts on any fail.
4. **OUTPUT** — renders the branded PDF.

### Reading a self-check FAIL
`output/review_needed.txt` lists exactly what to verify, e.g.:
- *"value not found in source line"* → the number on the report doesn't match the
  PDF; open the PDF and check it.
- *"confidence 0.62 < 0.80"* → a marker was matched loosely (often an unusual lab
  layout); confirm the name/value/unit are right.
- *"inconsistent units across dates"* → two draws reported the same marker in
  different units; decide how to present it.
- *"banned word in output"* → interpretive language slipped in; it must be
  removed before shipping (this should not happen with the built-in content).

Once you've verified, re-run. When it's all PASS, the PDF is safe to deliver.

---

## D. The money

| Offer | Price | How |
|-------|-------|-----|
| One report | **$79** one-time | Stripe Checkout on `/app`, or invoice manually |
| Keep it updated each draw | **$29 / month** | Handle by subscription/invoice; re-run the tool each new draw |
| Trial (free or half-price) | your call | Hand out an `ACCESS_CODES` code, or just run it on the CLI |

The subscription ($29/mo) isn't automated in the tool — set it up as a Stripe
subscription or recurring invoice, and each time the client sends a new draw,
re-run the pipeline (add the new PDF alongside the old ones in `input/`) and send
the updated report.

---

## E. Day-to-day checklist
- **New paid customer (self-serve):** nothing to do unless they hit the review
  page.
- **Review-page customer / emailed files:** run the CLI, verify, email the PDF.
- **New draw for a subscriber:** drop the new PDF into `input/` with their
  earlier ones, re-run, send the updated report.
- **Giving a trial:** share a code from `ACCESS_CODES`, or run the CLI yourself.
- **Always:** if it didn't pass the self-check, it doesn't go out.

See **STRIPE_SETUP.md** for connecting payments and **README.md** for setup,
deployment, and the gating variables.
