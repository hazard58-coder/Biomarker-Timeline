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
├── PLAN.md                    ← 7-day launch plan
├── MESSAGES.md                ← 5 first-contact message templates
├── landing.html               ← single-file landing page
├── serve.py                   ← stdlib static server for the landing page (Railway)
├── railway.json / nixpacks.toml / Procfile  ← Railway deploy config
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

## Deploy the landing page (Railway)

The report tool is a local CLI script — it runs on your machine, not a server.
The only web-facing piece is `landing.html`, and it's deployed on **Railway**
(not Vercel or Supabase). It's served by `serve.py` using only the Python
standard library — no web framework, no database, consistent with the rest of
the project.

**One-time deploy:**

1. Push this repo to GitHub (already done if you're reading this on GitHub).
2. In [Railway](https://railway.app), create a new project →
   **Deploy from GitHub repo** → pick this repo.
3. Railway reads `railway.json` / `nixpacks.toml` automatically, builds, and
   starts `python serve.py`. No environment variables are required (Railway
   provides `PORT`).
4. Under the service's **Settings → Networking**, click **Generate Domain** to
   get a public URL.

That's it. The landing page is live, and the finished sample report is available
at `/sample.pdf` so prospects can see a real example before they buy.

> Prefer the Railway CLI? `npm i -g @railway/cli`, then `railway login` and
> `railway up` from this folder.

Run it locally first to check it:

```bash
python serve.py            # then open http://localhost:8080
```

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
