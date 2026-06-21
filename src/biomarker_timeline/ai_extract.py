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
# When on, the AI fallback only fills markers already in the curated dictionary
# (no "Other" markers like sodium/BUN) — keeps the report to the known panel.
KNOWN_ONLY = os.environ.get("AI_KNOWN_ONLY", "").strip().lower() in ("1", "true", "yes", "on")
# Vision: read scanned/image pages (no text layer). Default on when AI is enabled.
VISION = os.environ.get("AI_VISION", "1").strip().lower() not in ("0", "false", "no", "off")
VISION_MAX_PAGES = int(os.environ.get("AI_VISION_MAX_PAGES", "40"))
VISION_CONCURRENCY = max(1, int(os.environ.get("AI_VISION_CONCURRENCY", "5")))
VISION_DPI = int(os.environ.get("AI_VISION_DPI", "150"))
AI_TIMEOUT = float(os.environ.get("AI_TIMEOUT", "60"))  # per-call seconds
_MAX_CHARS = 60000
_PAGE_TEXT_MIN = 40  # a page with fewer characters than this is treated as scanned

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


def diagnostics() -> dict:
    """Live status of the AI fallback, for an admin to see WHY it isn't firing
    (wrong model, bad key, egress blocked, package missing, ...)."""
    d = {
        "api_key_set": bool(API_KEY),
        "ai_extract_off": _OFF,
        "enabled": enabled(),
        "model": MODEL,
        "known_only": KNOWN_ONLY,
        "vision": VISION,
        "anthropic_installed": False,
        "pymupdf_installed": False,
        "test_call": "not run",
    }
    try:
        import fitz  # noqa: F401
        d["pymupdf_installed"] = True
    except Exception:
        d["pymupdf_installed"] = False
    try:
        import anthropic
        d["anthropic_installed"] = True
        d["anthropic_version"] = getattr(anthropic, "__version__", "?")
    except Exception as exc:
        d["test_call"] = f"anthropic import FAILED: {exc}"
        return d
    if not API_KEY:
        d["test_call"] = "no API key set"
        return d
    try:
        client = anthropic.Anthropic(api_key=API_KEY, timeout=AI_TIMEOUT)
        msg = client.messages.create(
            model=MODEL, max_tokens=16,
            messages=[{"role": "user", "content": "Reply with exactly: ok"}])
        txt = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        d["test_call"] = f"OK — model replied: {txt.strip()[:30]!r}"
    except Exception as exc:
        d["test_call"] = f"ERROR — {type(exc).__name__}: {exc}"
    return d


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
    elif KNOWN_ONLY:
        return None  # curated-panel-only mode: skip markers not in the dictionary
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


_VISION_SYSTEM = (
    "You transcribe laboratory result values from an IMAGE of a lab report page. "
    "You ONLY copy what is literally printed. You never interpret a value, never "
    "say whether it is high, low, normal, abnormal, optimal, good, or bad, never "
    "diagnose, and never recommend anything.\n\n"
    "Return ONLY a JSON object (no prose, no code fence) with two keys:\n"
    "  collected_date  the specimen COLLECTION date printed on the page, as "
    "\"YYYY-MM-DD\" (use the collected/drawn date, not the reported/printed date); "
    "null if none is printed.\n"
    "  results  an array of the biomarker results on the page; each item has: "
    "name (as printed), value (number, or null if not a plain number), value_text "
    "(literal result if not a plain number e.g. \"<0.1\", \"Negative\"; else null), "
    "unit (as printed or null), ref_low (lower number of the printed reference "
    "range or null), ref_high (upper number or null).\n\n"
    "Include only real analyte results that have a value. Skip headers, patient "
    "info, and notes. Never invent a value that is not printed."
)


def _parse_json_object(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _render_page_png(path, page_index: int, dpi: int = 150) -> bytes:
    import fitz  # PyMuPDF
    with fitz.open(str(path)) as d:
        pix = d[page_index].get_pixmap(dpi=dpi)
        return pix.tobytes("png")


def extract_document_vision(doc: SourceDocument) -> list[Reading]:
    """Read scanned/image pages (no text layer) with Claude vision — markers AND
    the per-page collection date, so a multi-date cumulative scan yields multiple
    draws. Returns [] if disabled or on failure."""
    if not enabled() or not VISION:
        return []
    img_pages = [i for i, t in enumerate(doc.pages)
                 if len((t or "").strip()) < _PAGE_TEXT_MIN]
    if not img_pages:
        return []
    try:
        import base64
        import anthropic
        from concurrent.futures import ThreadPoolExecutor
        from .extract import _parse_date_token
    except Exception as exc:
        _log.warning("vision unavailable: %s", exc)
        return []

    pages = img_pages[:VISION_MAX_PAGES]

    def _read_page(i: int) -> list[Reading]:
        try:
            png = _render_page_png(doc.path, i, dpi=VISION_DPI)
            b64 = base64.standard_b64encode(png).decode("ascii")
            client = anthropic.Anthropic(api_key=API_KEY, timeout=AI_TIMEOUT)
            msg = client.messages.create(
                model=MODEL, max_tokens=4096, system=_VISION_SYSTEM,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64",
                                                 "media_type": "image/png", "data": b64}},
                    {"type": "text", "text": "Transcribe this lab page as the specified JSON."},
                ]}])
            raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        except Exception as exc:
            _log.warning("vision extract failed for %s page %d: %s", doc.name, i + 1, exc)
            return []
        obj = _parse_json_object(raw)
        dd = _parse_date_token(str(obj.get("collected_date") or "")) or date.min
        res: list[Reading] = []
        for item in obj.get("results", []):
            if isinstance(item, dict):
                r = _to_reading(item, dd, doc.name)
                if r:
                    r.review_flags.append("ai-vision")
                    res.append(r)
        return res

    # Vision pages are I/O-bound Claude calls — run them concurrently so a
    # many-page scan finishes in seconds, not minutes (avoids worker timeouts).
    out: list[Reading] = []
    try:
        with ThreadPoolExecutor(max_workers=min(VISION_CONCURRENCY, len(pages))) as ex:
            for res in ex.map(_read_page, pages):
                out.extend(res)
    except Exception as exc:
        _log.warning("vision pool failed for %s: %s", doc.name, exc)
    return out


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
        client = anthropic.Anthropic(api_key=API_KEY, timeout=AI_TIMEOUT)
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
