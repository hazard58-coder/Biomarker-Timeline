"""Hosted web service for Biomarker Timeline.

A thin web layer over the exact same four-stage pipeline the CLI uses. A visitor
uploads their lab PDFs in the browser; the pipeline runs server-side; the branded
PDF is streamed back as a download.

The legal guardrail is preserved end to end: the mandatory SELF-CHECK still runs,
and if it fails the service REFUSES to emit a report — it shows what a human must
verify instead. An unreviewed report is never shipped, in the browser or the CLI.

Access: the report tool lives at /app and is intentionally NOT linked from the
public landing page (link-only). Share the URL with clients directly.

Run locally:   python webapp.py          (http://localhost:8080)
Production:    gunicorn webapp:app       (see Dockerfile)
"""

from __future__ import annotations

import io
import re
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from flask import Flask, Response, request, send_file  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402

from biomarker_timeline.pipeline import run_pipeline  # noqa: E402

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # 40 MB total upload cap

LANDING = ROOT / "landing.html"
SAMPLE = ROOT / "samples" / "Marcus_Hale_Biomarker_Timeline_SAMPLE.pdf"

# ---------------------------------------------------------------------------
# Shared page chrome (Vitalis Forge dark theme, matches landing.html)
# ---------------------------------------------------------------------------
_HEAD = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Oswald:wght@600;700&display=swap" rel="stylesheet">
<style>
  :root{{--obsidian:#0E0F12;--charcoal:#1B1E24;--copper:#B87333;--gold:#C9A227;
    --ember:#C8602F;--offwhite:#ECEAE4;--muted:#9AA0A6;--hairline:#2C313A;}}
  *{{box-sizing:border-box;}}
  body{{margin:0;background:var(--obsidian);color:var(--offwhite);
    font-family:'Inter',system-ui,sans-serif;line-height:1.6;font-size:17px;}}
  .wrap{{max-width:680px;margin:0 auto;padding:0 24px;}}
  h1,h2,h3{{font-family:'Oswald',sans-serif;letter-spacing:0.02em;margin:0;}}
  a{{color:var(--gold);}}
  header{{border-bottom:1px solid var(--hairline);padding:22px 0;}}
  .brand{{display:flex;justify-content:space-between;align-items:baseline;}}
  .wordmark{{font-family:'Oswald',sans-serif;font-weight:700;font-size:20px;
    letter-spacing:0.18em;color:var(--copper);text-decoration:none;}}
  .brandtag{{font-family:'Oswald',sans-serif;font-weight:600;font-size:11px;
    letter-spacing:0.2em;color:var(--muted);}}
  .kicker{{font-family:'Oswald',sans-serif;font-weight:600;font-size:13px;
    letter-spacing:0.24em;color:var(--gold);text-transform:uppercase;}}
  h1.title{{font-size:40px;line-height:1.04;font-weight:700;margin:12px 0 16px;}}
  .rule{{border:0;border-top:2px solid var(--copper);margin:26px 0;}}
  .card{{background:var(--charcoal);border:1px solid var(--hairline);
    border-radius:4px;padding:24px 26px;margin:20px 0;}}
  label.fld{{display:block;font-family:'Oswald',sans-serif;font-weight:600;
    font-size:12px;letter-spacing:0.12em;text-transform:uppercase;
    color:var(--muted);margin:0 0 7px;}}
  input[type=text],input[type=file]{{width:100%;background:var(--obsidian);
    color:var(--offwhite);border:1px solid var(--hairline);border-radius:4px;
    padding:12px 14px;font-family:'Inter',sans-serif;font-size:15px;}}
  input[type=file]{{padding:10px 12px;}}
  .hintrow{{color:var(--muted);font-size:13px;margin:6px 0 0;}}
  .btn{{display:inline-block;margin-top:8px;font-family:'Oswald',sans-serif;
    font-weight:600;font-size:18px;letter-spacing:0.04em;color:var(--obsidian);
    background:var(--gold);padding:13px 26px;border:0;border-radius:4px;
    cursor:pointer;text-decoration:none;}}
  .btn:disabled{{opacity:0.6;cursor:default;}}
  .spacer{{height:18px;}}
  .err{{border-left:4px solid var(--ember);}}
  .disclaimer{{background:var(--charcoal);border:1px solid var(--hairline);
    border-top:3px solid var(--ember);border-radius:4px;padding:18px 22px;margin:24px 0 50px;}}
  .disclaimer h3{{font-size:13px;letter-spacing:0.14em;color:var(--ember);
    text-transform:uppercase;font-weight:700;margin-bottom:8px;}}
  .disclaimer p{{font-size:13.5px;color:var(--offwhite);margin:0;}}
  ul.review{{margin:6px 0 0;padding-left:20px;}}
  ul.review li{{font-size:14px;color:var(--offwhite);margin:4px 0;}}
  .mono{{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;color:var(--muted);}}
  footer{{border-top:1px solid var(--hairline);padding:22px 0 60px;color:var(--muted);font-size:13px;}}
</style></head><body>
<header><div class="wrap brand">
  <a class="wordmark" href="/">VITALIS&nbsp;FORGE</a>
  <span class="brandtag">WELLNESS · DATA</span>
</div></header>
<div class="wrap">
"""

_FOOT = """
  <div class="disclaimer">
    <h3>Please read</h3>
    <p>Biomarker Timeline is a data-organization report, not medical advice. It
      transcribes and charts the values from the lab PDFs you provide, next to
      each lab's own printed reference range. It does not interpret those values,
      diagnose any condition, or prescribe any treatment, dose, supplement, or
      action. Review all results with a licensed physician.</p>
  </div>
</div>
<footer><div class="wrap">Biomarker Timeline · a report produced under the Vitalis
  Forge wellness brand · data organization only, not medical advice.</div></footer>
</body></html>"""


def _page(title: str, body: str) -> str:
    return _HEAD.format(title=title) + body + _FOOT


def _upload_form(error: str | None = None) -> str:
    err_html = ""
    if error:
        err_html = f'<div class="card err"><b>{error}</b></div>'
    return _page("Build your Biomarker Timeline", f"""
    <div class="spacer"></div>
    <div class="kicker">Biomarker Timeline</div>
    <h1 class="title">Build your report.</h1>
    <p>Upload the lab PDFs you already have — from any lab, across as many draw
      dates as you've collected. Your files are processed to build your report
      and are not stored.</p>
    <hr class="rule"/>
    {err_html}
    <form class="card" action="/generate" method="post" enctype="multipart/form-data">
      <label class="fld" for="name">Name for the report (optional)</label>
      <input type="text" id="name" name="name" placeholder="e.g. Jane Doe"/>
      <p class="hintrow">If left blank, we'll use the name printed on the labs.</p>
      <div class="spacer"></div>
      <label class="fld" for="labs">Your lab PDFs</label>
      <input type="file" id="labs" name="labs" accept="application/pdf,.pdf" multiple required/>
      <p class="hintrow">Select one or more PDF files (up to 40&nbsp;MB total).</p>
      <div class="spacer"></div>
      <button class="btn" type="submit">Generate my report</button>
      <p class="hintrow">This takes a few seconds while your charts render.</p>
    </form>
    """)


def _review_page(items: list[str]) -> str:
    lis = "".join(f"<li>{_escape(i)}</li>" for i in items) or "<li>(no detail)</li>"
    return _page("Manual review needed", f"""
    <div class="spacer"></div>
    <div class="kicker">Biomarker Timeline</div>
    <h1 class="title">This one needs a human first.</h1>
    <p>Our quality self-check didn't fully pass on these files, so we did
      <b>not</b> generate a report — an unreviewed report is never shipped. The
      items below need to be verified against your source PDFs before a report
      can be produced.</p>
    <div class="card">
      <label class="fld">Items to verify</label>
      <ul class="review">{lis}</ul>
    </div>
    <p>Email your files to <a href="mailto:contact@vitalisforge.com">contact@vitalisforge.com</a>
      and we'll review them by hand and send your report.</p>
    <p><a href="/app">← Try different files</a></p>
    """)


def _error_page(msg: str) -> str:
    return _page("Something went wrong", f"""
    <div class="spacer"></div>
    <h1 class="title">Something went wrong.</h1>
    <div class="card err"><p>{_escape(msg)}</p></div>
    <p><a href="/app">← Back to upload</a></p>
    """)


def _escape(s: str) -> str:
    import html
    return html.escape(str(s))


def _safe_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
    return slug or "Client"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
def landing() -> Response:
    return send_file(str(LANDING))


@app.get("/sample.pdf")
def sample() -> Response:
    if not SAMPLE.exists():
        return Response("Sample not available", status=404)
    return send_file(str(SAMPLE), mimetype="application/pdf")


@app.get("/healthz")
def healthz() -> Response:
    return Response("ok", mimetype="text/plain")


@app.get("/app")
def upload_page() -> Response:
    return Response(_upload_form(), mimetype="text/html")


@app.post("/generate")
def generate() -> Response:
    uploads = [f for f in request.files.getlist("labs")
               if f and f.filename and f.filename.lower().endswith(".pdf")]
    if not uploads:
        return Response(_upload_form("Please choose at least one PDF file."),
                        mimetype="text/html", status=400)

    client_name = (request.form.get("name") or "").strip() or None

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        in_dir = tmp / "input"
        in_dir.mkdir()
        out_pdf = tmp / "out" / "report.pdf"

        for i, f in enumerate(uploads):
            fname = secure_filename(f.filename) or f"upload_{i}.pdf"
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            f.save(str(in_dir / fname))

        try:
            result = run_pipeline(in_dir, out_pdf, client_name=client_name, verbose=False)
        except Exception as exc:  # corrupt PDF, unreadable file, etc.
            return Response(_error_page(
                f"We couldn't read one of those PDFs ({exc}). Make sure each file "
                f"is a real lab PDF and try again."), mimetype="text/html", status=400)

        if not result.passed:
            items: list[str] = []
            if result.review_path and Path(result.review_path).exists():
                text = Path(result.review_path).read_text(encoding="utf-8")
                items = [ln.strip(" -") for ln in text.splitlines()
                         if ln.strip().startswith("-")]
            return Response(_review_page(items), mimetype="text/html", status=422)

        # Success — read the bytes before the temp dir is cleaned up.
        data = out_pdf.read_bytes()

    base = _safe_slug(client_name) if client_name else "Client"
    download_name = f"{base}_Biomarker_Timeline_{date.today().isoformat()}.pdf"
    return send_file(io.BytesIO(data), mimetype="application/pdf",
                     as_attachment=True, download_name=download_name)


@app.errorhandler(413)
def too_large(_e) -> Response:
    return Response(_upload_form("Those files are larger than the 40 MB limit. "
                                 "Try uploading fewer at a time."),
                    mimetype="text/html", status=413)


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
