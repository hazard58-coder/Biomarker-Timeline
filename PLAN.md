# Seven-day launch plan

One task per day, each under an hour, ending in a first paid (or
trial-converting-to-paid) job. The whole point of week one is to get *one real
report into one real person's hands* and learn from it — not to build more.

Everything you need already exists in this repo. Don't add features this week.

---

## Day 1 — Run it on yourself (≈45 min)
The most honest test is your own bloodwork.
- [ ] `pip install -e .` in your Codespace (one time).
- [ ] Drop your own lab PDFs into `input/`.
- [ ] Run `biomarker-timeline --name "[Your Name]"`.
- [ ] Open `output/biomarker_timeline.pdf`. Read it as if you paid $79 for it.
- [ ] Write down anything that looks off, wrong, or confusing.

**Done when:** you have a finished report of your own labs and a short list of notes.

---

## Day 2 — Polish from your own notes (≈50 min)
Fix only what made *your* report look unfinished.
- [ ] If a marker didn't extract, check the self-check output and the source PDF.
- [ ] Set your real CTA email in `landing.html` (search for `labs@vitalisforge.example`).
- [ ] Put your real two-line bio / brand promise at the top of the landing page.
- [ ] Regenerate the sample if you changed anything: `python tools/make_sample.py`.

**Done when:** your own report and the sample both look like something you'd pay for.

---

## Day 3 — Send the five messages (≈40 min)
Open `MESSAGES.md`. Pick five real people — one per template.
- [ ] Personalize each message (name, community, how you know them).
- [ ] Send all five. Today. Don't overthink it.
- [ ] Log who you sent to and when, so you can follow up.

**Done when:** five honest, personalized messages are out the door.

---

## Day 4 — Deliver the first trial report (≈45 min)
Someone will say yes and send PDFs. Turn it around fast.
- [ ] Put their PDFs in `input/`, run `biomarker-timeline --name "[Their Name]"`.
- [ ] If the self-check FAILS, open `output/review_needed.txt`, verify the listed
      values against their source PDF, then re-run. Never skip this.
- [ ] Send them the PDF with one line: "Here's yours — tell me honestly what's
      useful and what's missing."

**Done when:** one real person has their report.

---

## Day 5 — Collect feedback and ask for the testimonial (≈30 min)
- [ ] Get on a 10-minute call or a voice note with your first recipient.
- [ ] Ask: would you have paid $79 for this? What would make it a yes?
- [ ] If they liked it, ask for one sentence you can quote (anonymized is fine).

**Done when:** you have one piece of real feedback and, ideally, one quote.

---

## Day 6 — Make the ask for money (≈40 min)
Go back to the warmest of your five contacts.
- [ ] To the trial recipient: "Want me to keep it updated each draw for $29/month?"
- [ ] To the others: share the sample report (or your own) and the $79 price.
- [ ] Send a payment link or just an invoice — keep it frictionless.

**Done when:** at least one clear paid offer is on the table.

---

## Day 7 — Close one and write down the workflow (≈45 min)
- [ ] Follow up on Day 6's offers. Close the first paid (or trial→paid) job.
- [ ] Deliver that paid report the same way: `input/` → run → check → send.
- [ ] Write a 5-line "how I run a job" note for yourself so #2 is faster.

**Done when:** one report is paid for, delivered, and you know exactly how to do
the next one.

---

### Guardrail reminder (every single day)
The report organizes and visualizes data. It never interprets, diagnoses, or
recommends. When a client asks "what does this mean?" — the answer is always
"that's the conversation to have with your physician." The software enforces this
in the self-check; you enforce it in how you talk about it.
