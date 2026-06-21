"""AI extraction fallback (Claude) — transcription only.

When the regex parser misses a lab's layout, Claude reads the report text and
returns structured marker rows. It is constrained to TRANSCRIPTION: it copies
only what is literally printed and never interprets, judges, diagnoses, or
recommends. The pipeline's mandatory self-check still re-verifies every value
against the source text and scans the rendered report for banned words, so an
invented or interpretive value cannot reach a report.

Enabled when ANTHROPIC_API_KEY is set (and AI_EXTRACT is not turned off). When
disabled, the pipeline is exactly the regex-only behavior.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

from .intake import SourceDocument
from .markers import canonical_for, display_name as marker_display_name
from .models import Reading, ReferenceRange

_log = logging.getLogger("biomarker.ai")

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODEL = os.environ.get("AI_EXTRACT_MODEL", "claude-sonnet-4-6").strip()
_OFF = os.environ.get("AI_EXTRACT", "1").strip().lower() in ("0", "false", "no", "off")
_MAX_CHARS = 60000

_SYSTEM = (
    "You transcribe laboratory result values from the text of a lab report. You "
    "ONLY copy what is literally printed. You never interpret a value, never say "
    "whether it is high, low, normal, abnormal, optimal, good, or bad, never "
    "diagnose, and never recommend anything.\n\n"
    "Return ONLY a JSON array (no prose, no code fence). Each element is one "
    "biomarker result that has a value printed in the text, with keys:\n"
    "  name       analyte name exactly as printed\n"
    "  value      the numeric result as a number, or null if it is not a plain number\n"
    "  value_text the literal result when it is not a plain number (e.g. \"<0.1\", "
    "\">300\", \"Negative\", \"Detected\"), otherwise null\n"
    "  unit       the unit as printed, or null\n"
    "  ref_low    the lower number of the lab's printed reference range, or null\n"
    "  ref_high   the upper number of the lab's printed reference range, or null\n"
    "  source     the exact line or short snippet the result came from\n\n"
    "Include only real analyte results that have a value. Skip section headers, "
    "patient info, comments, and educational notes. Never invent a number that is "
    "not printed. If only a bounded value like \"<0.1\" is printed, set value to "
    "null and value_text to \"<0.1\"."
)


def enabled() -> bool:
    return bool(API_KEY) and not _OFF


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "marker"


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _to_reading(obj: dict, draw_date: date, source_file: str) -> Reading | None:
    name = str(obj.get("name") or "").strip()
    if not name:
        return None

    value = _num(obj.get("value"))
    value_text = str(obj.get("value_text") or "").strip()
    if value is None and not value_text:
        # A non-numeric value sometimes arrives in `value`; keep it verbatim.
        raw = str(obj.get("value") or "").strip()
        if not raw:
            return None
        value_text = raw

    unit = str(obj.get("unit") or "").strip()
    lo, hi = _num(obj.get("ref_low")), _num(obj.get("ref_high"))
    ref = ReferenceRange(low=lo, high=hi) if (lo is not None or hi is not None) else ReferenceRange()

    # Only trust a confident name match; otherwise keep the marker under its own
    # name (a weak fuzzy match like "Magnesium, RBC" -> "RBC" must not happen).
    canonical, score = canonical_for(name)
    if canonical and score >= 0.6:
        disp = marker_display_name(canonical)
    else:
        canonical = "ai_" + _slug(name)
        disp = name if not name.isupper() else name.title()

    source = str(obj.get("source") or "").strip()
    if not source:
        source = f"{name} {value_text or (value if value is not None else '')} {unit}".strip()

    conf = 0.9 if unit else 0.82
    return Reading(
        canonical=canonical,
        display_name=disp,
        value=value,
        value_text=value_text if value is None else "",
        unit=unit,
        reference=ref,
        draw_date=draw_date,
        confidence=round(conf, 3),
        source_file=source_file,
        source_text=source,
        review_flags=["ai-extracted"],
    )


def _parse_json_array(raw: str) -> list:
    raw = raw.strip()
    m = re.search(r"\[.*\]", raw, re.S)  # tolerate stray prose / code fences
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def extract_document(doc: SourceDocument, draw_date: date) -> list[Reading]:
    """Run the Claude transcription pass on one document. Returns [] on any
    failure (so the pipeline silently falls back to regex-only)."""
    if not enabled():
        return []
    text = (doc.text or "")[:_MAX_CHARS]
    if not text.strip():
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=API_KEY)
        msg = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user",
                       "content": f"Lab report text:\n\n{text}\n\n"
                                  f"Return the JSON array of printed results."}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    except Exception as exc:
        _log.warning("AI extraction call failed for %s: %s", doc.name, exc)
        return []

    out: list[Reading] = []
    for obj in _parse_json_array(raw):
        if isinstance(obj, dict):
            r = _to_reading(obj, draw_date, doc.name)
            if r:
                out.append(r)
    return out
