"""Coach Randy — a SEPARATE functional/educational review.

This is a DIFFERENT product from the Biomarker Timeline data report. The data
report only ORGANIZES and transcribes a client's own numbers and is held to a
strict no-interpretation guardrail (see selfcheck.BANNED_WORDS). Coach Randy is
the opposite by design: it interprets. It adds a functional ("optimal") range
next to each lab's own standard range and writes plain-language educational
notes, as a wellness coach would.

Because it interprets, it is NEVER merged into the data report, NEVER run
through the banned-word self-check, and is wrapped in heavy "educational, not
medical advice" disclaimers. It is gated to the admin until a licensed
clinician / counsel has reviewed the output you intend to sell.

Generation is powered by Claude ("Coach Randy"). It works on the SAME extracted
numbers as the data report (via pipeline.gather), so the two always agree on the
underlying values — they differ only in that this one is allowed to comment.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import theme
from .models import MarkerSeries, Reading

_log = logging.getLogger("biomarker.coach")

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("COACH_MODEL", os.environ.get("AI_EXTRACT_MODEL", "claude-sonnet-4-6")).strip()
TIMEOUT = float(os.environ.get("COACH_TIMEOUT", "120"))
PERSONA = os.environ.get("COACH_NAME", "Coach Randy").strip() or "Coach Randy"

BRAND_NAME = "Vitalis Forge"
PRODUCT_NAME = "Functional Review"


def enabled() -> bool:
    return bool(API_KEY)


# --- The persona / system prompt --------------------------------------------
# Coach Randy is a wellness coach, NOT a clinician. The prompt forces an
# educational framing and forbids prescriptions, doses, and diagnoses while
# still allowing the functional-range commentary that is the whole point here.
_SYSTEM = f"""You are {PERSONA}, an experienced wellness and lab-literacy coach who
helps people understand their own bloodwork in plain language. You are writing an
EDUCATIONAL review of a client's lab values for general wellness understanding.

You are NOT a physician and this is NOT medical care. You must:
- Frame everything as general education, not diagnosis or treatment.
- NEVER prescribe or suggest a specific drug, hormone, dose, or prescription change.
- NEVER tell the reader to start, stop, or adjust any medication or protocol.
- Repeatedly defer specific decisions to the reader's own licensed physician.
- Speak about commonly-cited "functional" or "optimal" ranges as general wellness
  reference points that many coaches use, NOT as official medical thresholds, and
  note they are opinions that vary between practitioners.
- You MAY name general lifestyle categories (sleep, nutrition, training, stress,
  hydration) in broad educational terms, but NOT specific supplement brands,
  doses, or prescriptions.

You will receive the client's markers as JSON: each has the marker name, unit,
the lab's own printed standard range, and the time series of dated values.

Return ONLY a JSON object (no prose, no code fence) with these keys:
  summary   2-4 short paragraphs of plain-language, educational overview of the
            overall picture and any themes across the markers. Encouraging, calm,
            non-alarming. End by deferring specifics to their physician.
  markers   an array, one item per marker you were given, each with:
     name            the marker name exactly as given
     optimal_range   a short string for a commonly-cited functional/optimal range
                     for this marker & unit (e.g. "70-90"), or "" if you are not
                     confident one is widely cited. Use the SAME unit as given.
     position        one of "within", "below", "above", or "unknown" — where the
                     client's most recent value sits relative to that functional
                     range (purely a comparison; "unknown" if no range/value).
     note            1-3 sentences of general education about what this marker
                     reflects and what a value in this area can relate to in broad
                     wellness terms. No prescriptions, no doses, no diagnosis.
Keep every note educational and general. When unsure, say less."""


@dataclass
class CoachMarker:
    name: str
    unit: str
    latest_value: str
    standard_range: str
    optimal_range: str
    position: str
    note: str


@dataclass
class CoachReview:
    client_name: str
    summary: str
    markers: list[CoachMarker] = field(default_factory=list)
    generated_on: date = field(default_factory=date.today)
    model: str = MODEL
    persona: str = PERSONA


def _marker_payload(series: list[MarkerSeries]) -> list[dict]:
    """Compact JSON the model reasons over — the same numbers as the data report."""
    out = []
    for s in series:
        pts = []
        for r in s.ordered():
            pts.append({
                "date": r.draw_date.isoformat() if r.draw_date != date.min else None,
                "value": r.value if r.value is not None else r.value_text,
            })
        ref = next((r.reference for r in s.ordered() if r.reference.has_range), None)
        out.append({
            "name": s.display_name,
            "unit": s.unit,
            "standard_range": ref.display() if ref else "",
            "series": pts,
        })
    return out


def _latest_str(s: MarkerSeries) -> str:
    r = s.ordered()[-1]
    v = r.value_str()
    return f"{v} {s.unit}".strip()


def _standard_str(s: MarkerSeries) -> str:
    ref = next((r.reference for r in s.ordered() if r.reference.has_range), None)
    return ref.display() if ref else "—"


def generate_review(series: list[MarkerSeries], client_name: str) -> CoachReview:
    """Ask Claude (as the coach persona) for the functional review. Raises on a
    hard failure so the caller can surface it (this is an explicit admin action,
    not a silent fallback like the data-report AI pass)."""
    if not enabled():
        raise RuntimeError("ANTHROPIC_API_KEY is not set — Coach Randy needs it.")
    if not series:
        raise RuntimeError("No markers were extracted, so there is nothing to review.")

    import anthropic

    payload = _marker_payload(series)
    client = anthropic.Anthropic(api_key=API_KEY, timeout=TIMEOUT)
    msg = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=_SYSTEM,
        messages=[{"role": "user", "content": (
            f"Client: {client_name}\n\n"
            f"Markers (JSON):\n{json.dumps(payload, indent=2)}\n\n"
            f"Write the educational functional review as the specified JSON object."
        )}],
    )
    raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    obj = _parse_json_object(raw)

    notes_by_name = {}
    for item in obj.get("markers", []) or []:
        if isinstance(item, dict) and item.get("name"):
            notes_by_name[str(item["name"]).strip().lower()] = item

    markers: list[CoachMarker] = []
    for s in series:
        item = notes_by_name.get(s.display_name.strip().lower(), {})
        markers.append(CoachMarker(
            name=s.display_name,
            unit=s.unit,
            latest_value=_latest_str(s),
            standard_range=_standard_str(s),
            optimal_range=str(item.get("optimal_range") or "").strip(),
            position=str(item.get("position") or "unknown").strip().lower(),
            note=str(item.get("note") or "").strip(),
        ))

    summary = str(obj.get("summary") or "").strip()
    if not summary:
        summary = ("A written overview was not returned for this review. The "
                   "marker-by-marker notes below are general education only.")
    return CoachReview(client_name=client_name, summary=summary, markers=markers)


def _parse_json_object(raw: str) -> dict:
    import re
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Rendering — its own branded PDF, visually distinct from the data report and
# wrapped in heavy "educational, not medical advice" disclaimers.
# ---------------------------------------------------------------------------
import html as _html  # noqa: E402

from weasyprint import HTML  # noqa: E402

_HEAVY_DISCLAIMER = (
    "This Functional Review is EDUCATIONAL CONTENT ONLY and is NOT medical advice, "
    "diagnosis, or treatment. It was generated by an AI wellness-coaching assistant "
    f"({PERSONA}), who is not a physician. The \"functional\" or \"optimal\" ranges "
    "shown here are general wellness reference points that vary between practitioners "
    "and are NOT official medical thresholds — your lab's own standard range is shown "
    "alongside for comparison. Nothing here prescribes or adjusts any medication, "
    "hormone, dose, supplement, or protocol. Always consult your own licensed "
    "physician before making any health decision. By reading this you acknowledge it "
    "is general education and not a substitute for professional medical care."
)

_FOOTER = (f"{PERSONA} Functional Review by {BRAND_NAME}  ·  Educational content, "
           f"not medical advice  ·  Consult your licensed physician")

_POS_LABEL = {
    "within": ("within functional range", "pos-within"),
    "below": ("below functional range", "pos-out"),
    "above": ("above functional range", "pos-out"),
    "unknown": ("—", "pos-unknown"),
}


def _esc(s) -> str:
    return _html.escape(str(s))


def _coach_css() -> str:
    # A green-leaning accent on the otherwise-Vitalis palette signals this is the
    # coaching product, visibly distinct from the copper data report.
    return f"""
{theme.base_css()}
@page {{
  size: Letter;
  margin: 0.7in 0.65in 0.9in 0.65in;
  background: {theme.OBSIDIAN};
  @bottom-center {{
    content: "{_FOOTER}";
    font-family: 'Inter', sans-serif; font-size: 6.6pt; color: {theme.MUTED};
  }}
  @bottom-right {{
    content: counter(page) " / " counter(pages);
    font-family: 'Inter', sans-serif; font-size: 6.6pt; color: {theme.MUTED};
  }}
}}
@page cover {{ @bottom-center {{ content: none; }} @bottom-right {{ content: none; }} }}
.cover-page {{ page: cover; }}
.page-break {{ break-before: page; }}
.avoid-break {{ break-inside: avoid; }}

.brandbar {{ display: flex; justify-content: space-between; align-items: baseline; }}
.wordmark {{ font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 16pt;
  letter-spacing: 0.18em; color: {theme.COPPER}; }}
.brandtag {{ font-family: 'Oswald', sans-serif; font-weight: 600; font-size: 8pt;
  letter-spacing: 0.22em; color: {theme.MUTED}; }}

.kicker {{ font-family: 'Oswald', sans-serif; font-weight: 600; font-size: 9.5pt;
  letter-spacing: 0.24em; color: {theme.GOLD}; margin: 26pt 0 6pt 0; }}
.cover-title h1 {{ font-size: 42pt; line-height: 1.0; }}
.cover-sub {{ font-size: 12pt; color: {theme.OFFWHITE}; margin-top: 10pt; }}
.coachmark {{ color: {theme.GOLD}; }}

.warnbox {{
  margin-top: 20pt; background: {theme.CHARCOAL}; border: 0.75pt solid {theme.HAIRLINE};
  border-top: 3pt solid {theme.EMBER}; border-radius: 3pt; padding: 13pt 15pt;
}}
.warn-h {{ font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 9.5pt;
  letter-spacing: 0.14em; color: {theme.EMBER}; margin-bottom: 6pt; }}
.warnbox p {{ font-size: 8.8pt; line-height: 1.6; color: {theme.OFFWHITE}; margin: 0; }}

.summary p {{ font-size: 10.5pt; line-height: 1.65; margin: 0 0 8pt 0; }}

td.pos-within {{ color: {theme.GOLD}; font-weight: 600; }}
td.pos-out {{ color: {theme.EMBER}; font-weight: 600; }}
td.pos-unknown {{ color: {theme.MUTED}; }}
.note {{ font-size: 8.4pt; color: {theme.OFFWHITE}; line-height: 1.45; }}
.optcol {{ color: {theme.GOLD}; font-weight: 600; }}
"""


def _cover_html(rv: CoachReview) -> str:
    return f"""
<section class="cover-page">
  <div class="brandbar">
    <span class="wordmark">VITALIS&nbsp;FORGE</span>
    <span class="brandtag">COACHING · EDUCATION</span>
  </div>
  <hr class="rule"/>
  <div class="cover-title">
    <div class="kicker">EDUCATIONAL FUNCTIONAL REVIEW</div>
    <h1>{_esc(rv.persona)}'s<br/>Functional Review</h1>
    <div class="cover-sub">Prepared for <span class="coachmark">{_esc(rv.client_name)}</span>
      · {rv.generated_on.strftime('%B %-d, %Y')}</div>
  </div>
  <div class="warnbox">
    <div class="warn-h">READ THIS FIRST — EDUCATIONAL, NOT MEDICAL ADVICE</div>
    <p>{_esc(_HEAVY_DISCLAIMER)}</p>
  </div>
</section>
"""


def _summary_html(rv: CoachReview) -> str:
    paras = "".join(f"<p>{_esc(p.strip())}</p>"
                    for p in rv.summary.split("\n") if p.strip())
    return f"""
<section class="page-break">
  <h2>Overview</h2>
  <hr class='rule-thin'/>
  <div class="summary">{paras}</div>
</section>
"""


def _table_html(rv: CoachReview) -> str:
    rows = []
    for m in rv.markers:
        label, cls = _POS_LABEL.get(m.position, _POS_LABEL["unknown"])
        opt = m.optimal_range or "—"
        rows.append(
            f"<tr class='avoid-break'>"
            f"<td>{_esc(m.name)}</td>"
            f"<td class='num'>{_esc(m.latest_value)}</td>"
            f"<td class='muted'>{_esc(m.standard_range)}</td>"
            f"<td class='optcol'>{_esc(opt)}</td>"
            f"<td class='{cls}'>{_esc(label)}</td>"
            f"</tr>"
            f"<tr class='avoid-break'><td colspan='5' class='note'>{_esc(m.note)}</td></tr>"
        )
    return f"""
<section class="page-break">
  <h2>Marker-by-Marker</h2>
  <p class='muted small'>The <span class='optcol'>functional range</span> column is a
     general wellness reference point ({_esc(rv.persona)}'s, AI-generated) shown next to
     your lab's own standard range. Functional ranges are opinions that vary between
     practitioners — they are not official medical thresholds.</p>
  <hr class='rule-thin'/>
  <table class="data">
    <thead><tr>
      <th>Marker</th><th class='num'>Most recent</th><th>Lab standard range</th>
      <th>Functional range</th><th>Position</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
"""


def _closing_html(rv: CoachReview) -> str:
    return f"""
<section class="page-break">
  <div class="brandbar"><span class="wordmark" style="font-size:13pt;">VITALIS&nbsp;FORGE</span></div>
  <hr class="rule"/>
  <h1 style="font-size:22pt;">Take this to<br/>your physician.</h1>
  <div class="warnbox" style="margin-top:18pt;">
    <div class="warn-h">DISCLAIMER</div>
    <p>{_esc(_HEAVY_DISCLAIMER)}</p>
  </div>
  <p class='muted tiny' style='margin-top:16pt;'>
     Generated by {_esc(rv.persona)} ({_esc(rv.model)}) on
     {rv.generated_on.strftime('%B %-d, %Y')} for {BRAND_NAME}.</p>
</section>
"""


def build_html(rv: CoachReview) -> str:
    body = _cover_html(rv) + _summary_html(rv) + _table_html(rv) + _closing_html(rv)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{_esc(rv.persona)} Functional Review — {_esc(rv.client_name)}</title>
<style>{_coach_css()}</style>
</head><body>{body}</body></html>"""


def render_pdf(rv: CoachReview, out_path: Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=build_html(rv)).write_pdf(str(out_path))
