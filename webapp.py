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
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from flask import (  # noqa: E402
    Flask, Response, make_response, redirect, request, send_file,
)
import logging  # noqa: E402

from werkzeug.utils import secure_filename  # noqa: E402

import gate  # noqa: E402
import mailer  # noqa: E402
import store  # noqa: E402
from biomarker_timeline.pipeline import gather, run_pipeline  # noqa: E402
from biomarker_timeline.intake import intake  # noqa: E402
from biomarker_timeline import coach_review  # noqa: E402

ACCOUNT_COOKIE = "bt_account"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024  # 40 MB total upload cap


@app.after_request
def _security_headers(resp: Response) -> Response:
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Railway terminates TLS at the proxy, so check the forwarded proto too.
    if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


# /login sends real email on every POST; without a limit it's an open relay for
# magic-link spam (burning Resend quota and the domain's sending reputation).
# In-memory is enough: one gunicorn worker, and the worst case after a restart
# is a fresh window.
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_PER_WINDOW = 5
_login_attempts: dict[str, list[float]] = {}


def _login_rate_limited(*keys: str) -> bool:
    now = time.time()
    if len(_login_attempts) > 5000:  # bound memory under address-rotation abuse
        _login_attempts.clear()
    limited = False
    for key in keys:
        if not key:
            continue
        recent = [t for t in _login_attempts.get(key, [])
                  if now - t < _LOGIN_WINDOW_SECONDS]
        if len(recent) >= _LOGIN_MAX_PER_WINDOW:
            limited = True
        recent.append(now)
        _login_attempts[key] = recent
    return limited


def _client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr) or ""

LANDING = ROOT / "landing.html"
SAMPLE = ROOT / "samples" / "Marcus_Hale_Biomarker_Timeline_SAMPLE.pdf"

# ---------------------------------------------------------------------------
# Shared page chrome (Vitalis Forge dark theme, matches landing.html)
# ---------------------------------------------------------------------------
_HEAD = """<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%230E0F12'/%3E%3Cpath d='M12 44 L26 30 L36 38 L52 20' stroke='%23B87333' stroke-width='6' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E"/>
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
  header{{position:sticky;top:0;z-index:50;background:rgba(14,15,18,0.92);
    border-bottom:1px solid var(--hairline);padding:13px 0;}}
  .brand{{display:flex;justify-content:space-between;align-items:center;}}
  .wordmark{{font-family:'Oswald',sans-serif;font-weight:700;font-size:19px;
    letter-spacing:0.18em;color:var(--copper);text-decoration:none;}}
  .navlinks{{display:flex;align-items:center;gap:20px;}}
  .navlinks a{{color:var(--muted);font-family:'Oswald',sans-serif;font-weight:600;
    font-size:12.5px;letter-spacing:0.08em;text-transform:uppercase;text-decoration:none;}}
  .navlinks a:hover{{color:var(--offwhite);}}
  .nav-cta{{color:var(--obsidian)!important;background:var(--gold);
    padding:8px 16px;border-radius:4px;}}
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
  <nav class="navlinks">
    <a href="/#pricing">Pricing</a>
    <a href="/#faq">FAQ</a>
    <a href="/login">Sign in</a>
    <a class="nav-cta" href="/app">Get started</a>
  </nav>
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
    email = _account_email()
    acct_bar = ""
    if email:
        who = f"{_escape(email)}{' (admin)' if gate.is_admin(email) else ''}"
        acct_bar = (f'<p class="hintrow">Signed in as {who} · '
                    f'<a href="/portal">Manage subscription</a> · '
                    f'<a href="/logout">Sign out</a></p>')
    portal_link = acct_bar
    return _page("Build your Biomarker Timeline", f"""
    <div class="spacer"></div>
    <div class="kicker">Biomarker Timeline</div>
    <h1 class="title">Build your report.</h1>
    <p>Upload the lab PDFs you already have — from any lab, across as many draw
      dates as you've collected. Your files are processed to build your report
      and are not stored.</p>
    <hr class="rule"/>
    {err_html}
    <form id="genform" class="card" action="/generate" method="post" enctype="multipart/form-data">
      <label class="fld" for="name">Name for the report (optional)</label>
      <input type="text" id="name" name="name" placeholder="e.g. Jane Doe"/>
      <p class="hintrow">If left blank, we'll use the name printed on the labs.</p>
      <div class="spacer"></div>
      <label class="fld" for="labs">Your lab PDFs</label>
      <input type="file" id="labs" name="labs" accept="application/pdf,.pdf" multiple required/>
      <p class="hintrow">Select one or more PDF files (up to 40&nbsp;MB total).</p>
      <div class="spacer"></div>
      <button class="btn" type="submit">Generate my report</button>
      <p class="hintrow">Scanned reports can take up to a minute — keep this page open.</p>
    </form>
    {portal_link}
    {_GEN_OVERLAY}
    """)


# Loading experience shown while a report generates (the POST can take ~30-60s
# for scanned reports read by AI vision). Submits via fetch so we control the
# overlay, trigger the PDF download, or swap in an error/review page.
_GEN_OVERLAY = """
<div id="gen-overlay">
  <div class="gen-box">
    <div class="gen-spinner" id="gen-spinner"></div>
    <div class="gen-bar" id="gen-bar"><div class="gen-bar-fill"></div></div>
    <div class="gen-msg" id="gen-msg">Reading your lab PDFs…</div>
    <div class="gen-sub" id="gen-sub">Working hard on your report — please keep this page open.</div>
  </div>
</div>
<style>
#gen-overlay{position:fixed;inset:0;background:rgba(14,15,18,.96);z-index:200;
  display:none;align-items:center;justify-content:center;text-align:center;padding:24px;}
#gen-overlay.show{display:flex;}
.gen-box{max-width:460px;}
.gen-spinner{width:54px;height:54px;margin:0 auto 22px;border-radius:50%;
  border:4px solid #2C313A;border-top-color:#B87333;animation:gen-spin .9s linear infinite;}
@keyframes gen-spin{to{transform:rotate(360deg);}}
.gen-bar{height:6px;background:#1B1E24;border-radius:4px;overflow:hidden;margin:0 auto 18px;max-width:320px;}
.gen-bar-fill{height:100%;width:38%;background:linear-gradient(90deg,#B87333,#C9A227);border-radius:4px;
  animation:gen-slide 1.5s ease-in-out infinite;}
@keyframes gen-slide{0%{transform:translateX(-110%);}100%{transform:translateX(290%);}}
.gen-msg{font-family:'Oswald',sans-serif;font-weight:600;font-size:18px;color:#ECEAE4;
  letter-spacing:.02em;min-height:26px;transition:opacity .3s;}
.gen-sub{color:#9AA0A6;font-size:13px;margin-top:12px;}
</style>
<script>
(function(){
  var form=document.getElementById('genform'); if(!form) return;
  var overlay=document.getElementById('gen-overlay'), msgEl=document.getElementById('gen-msg');
  var msgs=["Reading your lab PDFs…","Finding every biomarker…","Reading scanned pages with AI…",
    "Lining up your draws by date…","Charting your trends…",
    "Double-checking every value against the source…","Building your branded report…",
    "Adding the finishing touches…","Good things take a moment — hang tight.",
    "Your report is on its way."];
  var idx=0,timer=null;
  function rotate(){idx=(idx+1)%msgs.length;msgEl.style.opacity=0;
    setTimeout(function(){msgEl.textContent=msgs[idx];msgEl.style.opacity=1;},300);}
  function fname(r){var cd=r.headers.get('Content-Disposition')||'';
    var m=cd.match(/filename="?([^"]+)"?/);return m?m[1]:'Biomarker_Timeline.pdf';}
  function done(t,s){clearInterval(timer);
    document.getElementById('gen-spinner').style.display='none';
    document.getElementById('gen-bar').style.display='none';
    msgEl.textContent=t; document.getElementById('gen-sub').textContent=s;}
  form.addEventListener('submit',function(e){
    e.preventDefault();
    overlay.classList.add('show'); idx=0; msgEl.textContent=msgs[0];
    timer=setInterval(rotate,3000);
    fetch(form.action,{method:'POST',body:new FormData(form)}).then(function(resp){
      var ct=resp.headers.get('Content-Type')||'';
      if(ct.indexOf('application/pdf')!==-1){
        var dn=fname(resp);
        return resp.blob().then(function(b){
          var u=URL.createObjectURL(b),a=document.createElement('a');
          a.href=u;a.download=dn;document.body.appendChild(a);a.click();a.remove();
          setTimeout(function(){URL.revokeObjectURL(u);},5000);
          done('Your report is ready ✓','It just downloaded — check your downloads. You can build another anytime.');
        });
      }
      return resp.text().then(function(h){clearInterval(timer);
        document.open();document.write(h);document.close();});
    }).catch(function(err){
      done('Connection interrupted','Please check your connection and try again. ('+err+')');
    });
  });
})();
</script>
"""


def _paywall(canceled: bool = False, error: str | None = None,
             used: bool = False) -> str:
    cancel_html = ('<div class="card err"><b>Payment canceled — you have not been '
                   'charged. You can try again whenever you\'re ready.</b></div>'
                   if canceled else "")
    used_html = ('<div class="card"><b>Your previous report is complete.</b> Each '
                 'one-time payment covers one report — purchase another below to run '
                 'a new one, or subscribe to keep your timeline updated.</div>'
                 if used else "")
    err_html = f'<div class="card err"><b>{_escape(error)}</b></div>' if error else ""

    pay_block = ""
    if gate.stripe_configured():
        pay_block = f"""
        <div class="card">
          <label class="fld">One report — {gate.price_display()} one-time</label>
          <p style="margin:2px 0 14px;font-size:15px;">A single Biomarker Timeline
            report built from the lab PDFs you upload.</p>
          <form action="/checkout" method="post" style="margin:0;">
            <input type="hidden" name="plan" value="once"/>
            <button class="btn" type="submit">Pay {gate.price_display()} &amp; continue</button>
          </form>
        </div>
        <div class="card">
          <label class="fld">Keep it updated — {gate.subscription_price_display()} / month</label>
          <p style="margin:2px 0 14px;font-size:15px;">A subscription that keeps your
            timeline updated with each new draw. Cancel anytime.</p>
          <form action="/checkout" method="post" style="margin:0;">
            <input type="hidden" name="plan" value="monthly"/>
            <button class="btn" type="submit">Subscribe {gate.subscription_price_display()}/mo &amp; continue</button>
          </form>
          <p class="hintrow">Secure checkout via Stripe. You'll come right back here
            to upload your labs.</p>
        </div>
        <p class="hintrow">Have a coupon? Add it in the <b>promotion code</b> field
          on the checkout page.</p>"""

    code_block = ""
    if gate.codes_configured():
        code_block = """
        <div class="card">
          <label class="fld" for="code">Have a trial code?</label>
          <form action="/unlock" method="post" style="margin:0;">
            <input type="text" id="code" name="code" placeholder="Enter your code"/>
            <div class="spacer"></div>
            <button class="btn" type="submit">Unlock with code</button>
          </form>
        </div>"""

    signin = ""
    if gate.stripe_configured():
        signin = ('<p class="hintrow">Already on the monthly plan? '
                  '<a href="/login">Sign in →</a></p>')

    no_purchase = ""
    if not gate.stripe_configured():
        no_purchase = ('<p>To purchase a report, email '
                       '<a href="mailto:contact@vitalisforge.com">contact@vitalisforge.com</a>.</p>')

    return _page("Get your Biomarker Timeline", f"""
    <div class="spacer"></div>
    <div class="kicker">Biomarker Timeline</div>
    <h1 class="title">Get your report.</h1>
    <p>Build one report from your own lab PDFs — charts for every biomarker over
      time, with each lab's own reference range. {gate.price_display()} one-time.</p>
    <p><a href="/sample.pdf">See a finished sample report →</a></p>
    <hr class="rule"/>
    {used_html}{cancel_html}{err_html}
    {pay_block}
    {code_block}
    {signin}
    {no_purchase}
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


def _already_used_page() -> str:
    return _page("Payment already used", f"""
    <div class="spacer"></div>
    <div class="kicker">Biomarker Timeline</div>
    <h1 class="title">That payment was already used.</h1>
    <p>Each payment covers one report, and a report has already been generated for
      this one. If you have a new draw to add or need another report, you can buy
      another below.</p>
    <p><a class="btn" href="/app">Get another report</a></p>
    <div class="spacer"></div>
    <p class="hintrow">If you think this is a mistake, email
      <a href="mailto:contact@vitalisforge.com">contact@vitalisforge.com</a>.</p>
    """)


def _signin_form(error: str | None = None, start: bool = False) -> str:
    err_html = f'<div class="card err"><b>{_escape(error)}</b></div>' if error else ""
    if start:
        heading = "Sign in to get started."
        blurb = ("Enter your email and we'll send you a sign-in link. New here? "
                 "You'll choose a report or subscription right after you sign in.")
        footer = ""
    else:
        heading = "Sign in."
        blurb = ("Enter your email and we'll send you a sign-in link.")
        footer = '<p class="hintrow">New here? <a href="/app">Get started →</a></p>'
    return _page("Sign in — Biomarker Timeline", f"""
    <div class="spacer"></div>
    <div class="kicker">Biomarker Timeline</div>
    <h1 class="title">{heading}</h1>
    <p>{blurb}</p>
    <hr class="rule"/>
    {err_html}
    <form class="card" action="/login" method="post">
      <label class="fld" for="email">Your email</label>
      <input type="text" id="email" name="email" placeholder="you@example.com" required/>
      <div class="spacer"></div>
      <button class="btn" type="submit">Email me a sign-in link</button>
    </form>
    {footer}
    """)


def _info_page(title: str, message: str) -> str:
    return _page(title, f"""
    <div class="spacer"></div>
    <div class="kicker">Biomarker Timeline</div>
    <h1 class="title">{_escape(title)}</h1>
    <p>{_escape(message)}</p>
    <p><a href="/app">← Back</a></p>
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


def _base_url() -> str:
    """Public origin for Stripe return URLs. Prefer APP_BASE_URL; otherwise derive
    from the request, forcing https for non-local hosts (Railway sits behind a
    TLS-terminating proxy)."""
    import os
    env = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if env:
        return env
    root = request.host_url.rstrip("/")
    if root.startswith("http://") and not any(
            h in root for h in ("localhost", "127.0.0.1")):
        root = "https://" + root[len("http://"):]
    return root


def _access_payload() -> dict | None:
    """Return the access-cookie payload if it CURRENTLY grants access, else None.

    A one-time Stripe payment that has already produced its report no longer
    grants access (so the visitor is sent back to the paywall to buy another,
    instead of being stuck on the upload form).
    """
    if not gate.gating_enabled():
        return {"k": "open"}
    payload = gate.read_token(request.cookies.get(gate.COOKIE_NAME))
    if not payload:
        return None
    if (payload.get("k") == "stripe" and payload.get("plan") != "sub"
            and store.is_consumed(payload.get("ref", ""))):
        return None
    return payload


def _spent_oncetime_cookie() -> bool:
    """True if the current cookie is a one-time payment that's already been used."""
    payload = gate.read_token(request.cookies.get(gate.COOKIE_NAME))
    return bool(payload and payload.get("k") == "stripe"
               and payload.get("plan") != "sub"
               and store.is_consumed(payload.get("ref", "")))


def _has_access() -> bool:
    """True if the visitor may use /app and /generate."""
    return _access_payload() is not None


def _grant_cookie(resp: Response, kind: str, ref: str, plan: str | None = None) -> Response:
    secure = _base_url().startswith("https")
    resp.set_cookie(
        gate.COOKIE_NAME, gate.issue_token(kind, ref, plan),
        max_age=gate.ACCESS_TTL_SECONDS, httponly=True, secure=secure, samesite="Lax",
    )
    return resp


def _set_account_cookie(resp: Response, customer_id: str, email: str) -> Response:
    secure = _base_url().startswith("https")
    resp.set_cookie(
        ACCOUNT_COOKIE, gate.issue_account_token(customer_id, email),
        max_age=gate.ACCOUNT_TTL_SECONDS, httponly=True, secure=secure, samesite="Lax",
    )
    return resp


def _read_account() -> dict | None:
    return gate.read_account_token(request.cookies.get(ACCOUNT_COOKIE))


def _account_email() -> str | None:
    acct = _read_account()
    if not acct:
        return None
    email = (acct.get("email") or "").strip().lower()
    return email or None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip()))


def _is_admin() -> bool:
    return gate.is_admin(_account_email())


def _entitlement(email: str) -> str | None:
    """What the signed-in account may do right now: 'admin' (unlimited, free),
    'subscription' (unlimited), 'credit' (>=1 unused report credit), or None."""
    if not email:
        return None
    if gate.is_admin(email):
        return "admin"
    if gate.stripe_configured() and gate.email_has_active_subscription(email):
        return "subscription"
    if store.available_credits(email) > 0:
        return "credit"
    return None


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


def _app_account_mode() -> Response:
    """Account-first /app: sign in, then buy/subscribe, then generate."""
    email = _account_email()

    # Returning from Stripe Checkout — record the purchase against the account.
    session_id = request.args.get("session_id")
    if session_id and gate.stripe_configured() and email:
        try:
            info = gate.checkout_session_info(session_id)
        except Exception:
            app.logger.exception("checkout return failed for session %s", session_id)
            return Response(_info_page(
                "We're confirming your payment",
                "Your payment went through, but we hit a snag confirming it. Please "
                "refresh in a moment, or email contact@vitalisforge.com with your "
                "receipt."), mimetype="text/html", status=503)
        if info["active"] and info["plan"] == "once":
            store.add_credit(session_id, email)  # one report credit for this account
        elif info["active"] and info["plan"] == "sub":
            # Stripe is the source of truth; just drop the cached "no subscription"
            # so the brand-new subscriber gets access on this very request.
            gate.bust_subscription_cache(email)

    if not email:
        return Response(_signin_form(start=True), mimetype="text/html")

    ent = _entitlement(email)
    if ent:
        return Response(_upload_form(), mimetype="text/html")
    return Response(_paywall(canceled=bool(request.args.get("canceled"))),
                    mimetype="text/html")


@app.get("/app")
def upload_page() -> Response:
    # Admin accounts (signed in) get straight through, in any mode.
    if _is_admin():
        return Response(_upload_form(), mimetype="text/html")
    if gate.LOGIN_REQUIRED:
        return _app_account_mode()

    # Open tool if no gating configured.
    if not gate.gating_enabled():
        return Response(_upload_form(), mimetype="text/html")

    # Already holds a valid access cookie.
    if _has_access():
        return Response(_upload_form(), mimetype="text/html")

    # Returning from a successful Stripe Checkout.
    session_id = request.args.get("session_id")
    if session_id and gate.stripe_configured():
        try:
            info = gate.checkout_session_info(session_id)
        except Exception:
            app.logger.exception("checkout return failed for session %s", session_id)
            return Response(_info_page(
                "We're confirming your payment",
                "Your payment went through, but we hit a snag confirming it just now. "
                "Please refresh in a moment. If it persists, email "
                "contact@vitalisforge.com with your receipt and we'll sort it out."),
                mimetype="text/html", status=503)
        if info["active"]:
            resp = make_response(_upload_form())
            _grant_cookie(resp, "stripe", session_id, info["plan"])
            # Subscribers get an account cookie so they can return + self-serve.
            if info["plan"] == "sub" and info.get("customer"):
                _set_account_cookie(resp, info["customer"], info.get("email") or "")
            return resp

    # Returning subscriber with a still-valid account cookie + active subscription.
    acct = _read_account()
    if acct and gate.stripe_configured() and gate.subscription_active(acct.get("cust")):
        resp = make_response(_upload_form())
        return _grant_cookie(resp, "stripe", f"acct:{acct.get('cust')}", "sub")

    # Signed-in account holding an unspent report credit — the recovery path for
    # a buyer whose payment was recorded by the Stripe webhook but who never
    # made it back through the redirect (closed tab, dropped connection). They
    # sign in with the email they paid with and their report is waiting.
    email = _account_email()
    if email and _entitlement(email):
        return Response(_upload_form(), mimetype="text/html")

    # Otherwise show the paywall. If the visitor's last one-time payment was
    # already used, say so (and clear the spent cookie so it's a clean slate).
    used = _spent_oncetime_cookie()
    resp = make_response(_paywall(canceled=bool(request.args.get("canceled")), used=used))
    if used:
        resp.delete_cookie(gate.COOKIE_NAME)
    return resp


@app.post("/webhook/stripe")
def stripe_webhook() -> Response:
    """Server-to-server payment record from Stripe.

    The redirect back to /app is the happy path, but a buyer who closes the tab
    on Stripe's receipt page never triggers it — before this endpoint, that
    payment was collected and no credit was ever recorded. Stripe retries
    webhook delivery for days, so the credit lands even through a redeploy.
    """
    if not gate.webhook_configured():
        return Response("webhook not configured", status=501)
    try:
        event = gate.verify_webhook(
            request.get_data(), request.headers.get("Stripe-Signature", ""))
    except Exception:
        app.logger.warning("stripe webhook: bad signature rejected")
        return Response("bad signature", status=400)

    etype = gate._sg(event, "type") or ""
    if etype in ("checkout.session.completed",
                 "checkout.session.async_payment_succeeded"):
        session = gate._sg(gate._sg(event, "data"), "object")
        sid = gate._sg(session, "id")
        details = gate._sg(session, "customer_details")
        email = (gate._sg(details, "email") if details is not None else None) \
            or gate._sg(session, "customer_email")
        if gate._sg(session, "mode") == "payment":
            if gate._sg(session, "payment_status") == "paid" and sid and email:
                store.add_credit(sid, email)  # idempotent with the redirect path
                app.logger.info("stripe webhook: credit recorded for session %s", sid)
        elif gate._sg(session, "mode") == "subscription" and email:
            # Stripe stays the source of truth; just drop any cached
            # "no subscription" so the new subscriber isn't held at the paywall.
            gate.bust_subscription_cache(email)
    return Response("ok", mimetype="text/plain")


@app.post("/checkout")
def checkout() -> Response:
    if not gate.stripe_configured():
        return Response(_paywall(error="Online payment isn't configured yet."),
                        mimetype="text/html", status=400)
    # In account mode you must be signed in first, so the purchase ties to you.
    if gate.LOGIN_REQUIRED and not _account_email():
        return redirect("/login", code=303)
    plan = "monthly" if request.form.get("plan") == "monthly" else "once"
    try:
        url = gate.create_checkout_session(_base_url(), plan,
                                           customer_email=_account_email() or "")
    except Exception as exc:
        return Response(_paywall(error=f"Couldn't start checkout ({exc})."),
                        mimetype="text/html", status=502)
    return redirect(url, code=303)


@app.post("/unlock")
def unlock() -> Response:
    code = request.form.get("code", "")
    if gate.code_is_valid(code):
        resp = make_response(redirect("/app", code=303))
        return _grant_cookie(resp, "code", code.strip())
    return Response(_paywall(error="That code wasn't recognized."),
                    mimetype="text/html", status=403)


@app.get("/login")
def login_page() -> Response:
    return Response(_signin_form(), mimetype="text/html")


@app.post("/login")
def login() -> Response:
    email = (request.form.get("email") or "").strip()
    if not _valid_email(email):
        return Response(_signin_form("Please enter a valid email address.",
                                     start=gate.LOGIN_REQUIRED),
                        mimetype="text/html", status=400)
    if _login_rate_limited(f"em:{email.lower()}", f"ip:{_client_ip()}"):
        return Response(_signin_form(
            "Too many sign-in requests. Please wait a few minutes and try again.",
            start=gate.LOGIN_REQUIRED), mimetype="text/html", status=429)

    link = f"{_base_url()}/verify?token={gate.issue_magic_token(email)}"

    # Testing aid: when email isn't configured, show the link on screen.
    if gate.DEV_SHOW_MAGIC_LINK and not mailer.mail_configured():
        return Response(_info_page(
            "Dev sign-in link",
            "Email isn't configured, so here's your one-time sign-in link "
            "(testing only). It works for 30 minutes:")
            .replace("</p>", f'</p><div class="card"><a href="{link}">{link}</a></div>', 1),
            mimetype="text/html")

    if mailer.mail_configured():
        try:
            mailer.send_magic_link(email, link)
        except Exception as exc:
            app.logger.exception("failed to send sign-in link to %s", email)
            # Surface the real SMTP error to an admin (who can't sign in to /diag
            # while email is broken); stay generic for everyone else.
            if gate.is_admin(email):
                return Response(_info_page(
                    "Email send failed",
                    f"Error sending to {email}: {exc}  —  A 'timed out' error means "
                    f"the host is blocking outbound SMTP. Fix: set RESEND_API_KEY "
                    f"(your re_... key) and MAIL_FROM, and the app will send via "
                    f"Resend's HTTPS API instead of SMTP. For plain SMTP, check the "
                    f"SMTP_* variables and that MAIL_FROM's domain is verified."),
                    mimetype="text/html", status=500)
        return Response(_info_page(
            "Check your email",
            "If that address is valid, a sign-in link is on its way. It works for "
            "30 minutes."), mimetype="text/html")

    # Not configured.
    if gate.is_admin(email):
        miss = ", ".join(mailer.missing_config()) or "(none — but mail still off)"
        return Response(_info_page(
            "Email isn't set up yet",
            f"Missing SMTP settings: {miss}. Set SMTP_HOST, SMTP_PORT, "
            f"SMTP_USERNAME, SMTP_PASSWORD, and MAIL_FROM in Railway."),
            mimetype="text/html")
    return Response(_info_page(
        "Email isn't set up yet",
        "Sign-in links are sent by email, which isn't configured yet. Email "
        "contact@vitalisforge.com and we'll help you in."), mimetype="text/html")


@app.get("/verify")
def verify() -> Response:
    email = gate.read_magic_token(request.args.get("token"))
    if not email:
        return Response(_info_page(
            "Link expired",
            "That sign-in link is invalid or has expired. Request a new one."),
            mimetype="text/html", status=400)
    # Any verified email is a valid account. Entitlement (subscription/credits)
    # is checked at /app — signing in by itself grants no paid access.
    cid = gate.customer_id_for_email(email) if gate.stripe_configured() else None
    resp = make_response(redirect("/app", code=303))
    _set_account_cookie(resp, cid or "", email)
    return resp


@app.get("/diag")
def diag() -> Response:
    """Admin-only diagnostics — shows whether the AI fallback can actually reach
    Claude (and why not, if it can't)."""
    if not _is_admin():
        return redirect("/login", code=303)
    from biomarker_timeline import ai_extract

    def _tbl(d: dict) -> str:
        return "<div class='card'><table>" + "".join(
            f"<tr><td class='muted' style='padding:4px 12px 4px 0'>{_escape(k)}</td>"
            f"<td><code>{_escape(str(v))}</code></td></tr>"
            for k, v in d.items()) + "</table></div>"

    email = _account_email()
    mail = mailer.diagnostics()
    test_email_html = ""
    if request.args.get("test_email") and email:
        result = mailer.send_test(email)
        test_email_html = (f'<div class="card"><b>Test email to {_escape(email)}:</b> '
                           f'<code>{_escape(result)}</code></div>')

    return Response(_page("Diagnostics", f"""
    <div class="spacer"></div>
    <div class="kicker">Admin</div>
    <h1 class="title">Diagnostics</h1>

    <h2 style="color:var(--copper);font-size:14px;letter-spacing:.1em;margin-top:18px;">EMAIL (SMTP)</h2>
    <p>If sign-in links aren't arriving, check this. {('<a class="btn" href="/diag?test_email=1">Send a test email to ' + _escape(email) + '</a>') if email else ''}</p>
    {test_email_html}
    {_tbl(mail)}

    <h2 style="color:var(--copper);font-size:14px;letter-spacing:.1em;margin-top:22px;">AI EXTRACTION</h2>
    <p>If <code>test_call</code> isn't <code>OK</code>, that's why the AI fallback
      isn't adding markers (wrong model, bad/restricted key, or blocked network).</p>
    {_tbl(ai_extract.diagnostics())}
    <p class="hintrow"><a href="/app">← Back</a></p>
    """), mimetype="text/html")


@app.get("/logout")
def logout() -> Response:
    resp = make_response(redirect("/", code=303))
    resp.delete_cookie(ACCOUNT_COOKIE)
    resp.delete_cookie(gate.COOKIE_NAME)
    return resp


@app.get("/portal")
def portal() -> Response:
    email = _account_email()
    cid = gate.customer_id_for_email(email) if (email and gate.stripe_configured()) else None
    if not cid:
        return redirect("/login", code=303)
    try:
        url = gate.create_billing_portal_session(cid, f"{_base_url()}/app")
    except Exception:
        return Response(_info_page(
            "Couldn't open the billing portal",
            "Please try again, or email contact@vitalisforge.com."),
            mimetype="text/html", status=502)
    return redirect(url, code=303)


def _coach_upload_form(error: str | None = None) -> str:
    err_html = f'<div class="card err"><b>{_escape(error)}</b></div>' if error else ""
    ai_ok = coach_review.enabled()
    ai_note = ("" if ai_ok else
               '<div class="card err"><b>ANTHROPIC_API_KEY is not set — Coach Randy '
               'cannot run without it.</b></div>')
    return _page("Coach Randy — Functional Review (admin)", f"""
    <div class="spacer"></div>
    <div class="kicker">Admin · Coach Randy</div>
    <h1 class="title">Functional Review.</h1>
    <p>This is a <b>separate, interpretive</b> product from the Biomarker Timeline
      data report. Coach Randy reads the same extracted numbers and adds a
      functional ("optimal") range and plain-language educational notes next to
      each lab's own standard range. It is <b>not</b> run through the no-advice
      self-check, and it is wrapped in heavy "educational, not medical advice"
      disclaimers. Admin-only until a clinician / counsel signs off on the output.</p>
    <hr class="rule"/>
    {err_html}{ai_note}
    <form id="coachform" class="card" action="/coach/generate" method="post"
          enctype="multipart/form-data">
      <label class="fld" for="cname">Name for the review (optional)</label>
      <input type="text" id="cname" name="name" placeholder="e.g. Jane Doe"/>
      <div class="spacer"></div>
      <label class="fld" for="clabs">Lab PDFs</label>
      <input type="file" id="clabs" name="labs" accept="application/pdf,.pdf" multiple required/>
      <p class="hintrow">Same PDFs you'd use for the data report (up to 40&nbsp;MB total).</p>
      <div class="spacer"></div>
      <button class="btn" type="submit">Generate functional review</button>
      <p class="hintrow">This calls Claude and can take a minute — keep this page open.</p>
    </form>
    <p class="hintrow"><a href="/app">← Data report</a> · <a href="/diag">Diagnostics</a></p>
    {_GEN_OVERLAY.replace("genform", "coachform")}
    """)


@app.get("/coach")
def coach_page() -> Response:
    if not _is_admin():
        return redirect("/login", code=303)
    return Response(_coach_upload_form(), mimetype="text/html")


@app.post("/coach/generate")
def coach_generate() -> Response:
    if not _is_admin():
        return redirect("/login", code=303)

    uploads = [f for f in request.files.getlist("labs")
               if f and f.filename and f.filename.lower().endswith(".pdf")]
    if not uploads:
        return Response(_coach_upload_form("Please choose at least one PDF file."),
                        mimetype="text/html", status=400)
    if not coach_review.enabled():
        return Response(_coach_upload_form(
            "ANTHROPIC_API_KEY is not set — Coach Randy can't run."),
            mimetype="text/html", status=400)

    client_name = (request.form.get("name") or "").strip() or None

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        in_dir = tmp / "input"
        in_dir.mkdir()
        for i, f in enumerate(uploads):
            fname = secure_filename(f.filename) or f"upload_{i}.pdf"
            if not fname.lower().endswith(".pdf"):
                fname += ".pdf"
            f.save(str(in_dir / fname))

        try:
            docs = intake(in_dir)
            if not docs:
                raise RuntimeError("No readable PDF pages were found in that upload.")
            series, _readings, _warnings = gather(docs)
            name = client_name or "Client"
            review = coach_review.generate_review(series, name)
            out_pdf = tmp / "out" / "coach_review.pdf"
            coach_review.render_pdf(review, out_pdf)
            data = out_pdf.read_bytes()
        except Exception as exc:
            app.logger.exception("coach review failed")
            return Response(_coach_upload_form(
                f"Coach Randy couldn't finish ({exc})."),
                mimetype="text/html", status=500)

    base = _safe_slug(client_name) if client_name else "Client"
    download_name = f"{base}_Functional_Review_{date.today().isoformat()}.pdf"
    return send_file(io.BytesIO(data), mimetype="application/pdf",
                     as_attachment=True, download_name=download_name)


def _run_report(on_success) -> Response:
    """Shared report runner: validate uploads, run the pipeline, and on a clean
    self-check deliver the PDF (calling `on_success` once, just before delivery,
    to consume the entitlement). The guardrail is identical in every access mode.
    """
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

    # Report delivered: now (and only now) consume the entitlement.
    if on_success:
        on_success()

    base = _safe_slug(client_name) if client_name else "Client"
    download_name = f"{base}_Biomarker_Timeline_{date.today().isoformat()}.pdf"
    return send_file(io.BytesIO(data), mimetype="application/pdf",
                     as_attachment=True, download_name=download_name)


@app.post("/generate")
def generate() -> Response:
    # Admin accounts generate freely, unmetered, in any mode.
    if _is_admin():
        return _run_report(None)

    # ---- account mode: entitlement is a subscription or a report credit ----
    if gate.LOGIN_REQUIRED:
        email = _account_email()
        if not email:
            return redirect("/login", code=303)
        ent = _entitlement(email)
        if not ent:
            return redirect("/app", code=303)
        if ent == "credit":
            return _run_report(lambda: store.consume_credit(email, note="report delivered"))
        return _run_report(None)  # active subscription — unlimited, nothing to consume

    # ---- guest mode: entitlement is the access cookie + one-time session ----
    if not _has_access():
        # No cookie, but a signed-in account may hold a webhook-recorded credit
        # or an active subscription (same recovery path as /app above).
        email = _account_email()
        ent = _entitlement(email) if email else None
        if ent == "credit":
            return _run_report(lambda: store.consume_credit(email, note="report delivered"))
        if ent:
            return _run_report(None)
        return redirect("/app", code=303)
    payload = gate.read_token(request.cookies.get(gate.COOKIE_NAME))
    paid_session_id = None
    if payload and payload.get("k") == "stripe" and payload.get("plan") != "sub":
        paid_session_id = payload.get("ref")
        if paid_session_id and store.is_consumed(paid_session_id):
            return redirect("/app", code=303)
    if paid_session_id:
        return _run_report(lambda sid=paid_session_id:
                           store.mark_consumed(sid, note="report delivered"))
    return _run_report(None)


@app.errorhandler(Exception)
def _unhandled(e) -> Response:
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e  # let 404/413/etc. behave normally
    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    return Response(_error_page(
        "Something went wrong on our end. Please try again, or email "
        "contact@vitalisforge.com."), mimetype="text/html", status=500)


@app.errorhandler(413)
def too_large(_e) -> Response:
    return Response(_upload_form("Those files are larger than the 40 MB limit. "
                                 "Try uploading fewer at a time."),
                    mimetype="text/html", status=413)


if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
