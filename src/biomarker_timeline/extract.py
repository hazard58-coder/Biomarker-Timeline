"""Stage 2 — EXTRACT.

For each source document: find the draw date, then pull every recognizable
biomarker line into a `Reading` of {name, value, unit, reference_range,
draw_date} with a per-value confidence score. Synonyms are normalized to a
single canonical marker (see markers.py), and readings are assembled into one
time series per marker across all dates.

This module transcribes. It never decides what a value means.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .intake import SourceDocument
from .markers import canonical_for, display_name, panel_sort_key
from .models import MarkerSeries, Reading, ReferenceRange

# Units we recognize on lab reports. Longer/more specific spellings first so
# "ng/dL" is preferred over a bare "dL".
KNOWN_UNITS = [
    "x10E6/uL", "x10E3/uL", "10*6/uL", "10*3/uL", "M/uL", "K/uL",
    "mg/dL", "ng/dL", "ng/mL", "pg/mL", "uIU/mL", "mIU/mL", "mIU/L",
    "nmol/L", "umol/L", "mmol/L", "g/dL", "U/L", "IU/L", "%",
]
_UNIT_RE = re.compile("(" + "|".join(re.escape(u) for u in KNOWN_UNITS) + ")")

# Reference-range shapes, in priority order.
_RANGE_BETWEEN = re.compile(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)")
_RANGE_UPPER = re.compile(r"[<≤]\s*(\d+(?:\.\d+)?)")
_RANGE_LOWER = re.compile(r"[>≥]\s*(\d+(?:\.\d+)?)")

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_FLAG_WORDS = re.compile(r"\b(high|low|h|l|hi|lo|abnormal|normal|critical|aa)\b", re.I)

CONFIDENCE_REVIEW_THRESHOLD = 0.80

# Date labels in rough priority order (collection date is what we want).
_DATE_LABELS = [
    "date collected", "collected", "specimen collected", "collection date",
    "draw date", "date drawn", "date of service", "date of collection",
    "service date", "reported", "date reported", "report date",
]

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def _parse_date_token(token: str) -> date | None:
    token = token.strip()
    # MM/DD/YYYY or MM-DD-YYYY (also 2-digit year)
    m = re.match(r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})", token)
    if m:
        mo, da, yr = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if yr < 100:
            yr += 2000
        try:
            return date(yr, mo, da)
        except ValueError:
            return None
    # Month DD, YYYY
    m = re.match(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", token)
    if m:
        mo = _MONTHS.get(m.group(1)[:3].lower())
        if mo:
            try:
                return date(int(m.group(3)), mo, int(m.group(2)))
            except ValueError:
                return None
    # YYYY-MM-DD
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", token)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def find_draw_date(doc: SourceDocument) -> tuple[date | None, str]:
    """Return (draw_date, source_line). Prefers an explicit collection date."""
    text_lines = doc.lines
    lowered = [ln.lower() for ln in text_lines]
    for label in _DATE_LABELS:
        for i, ln in enumerate(lowered):
            idx = ln.find(label)
            if idx == -1:
                continue
            tail = text_lines[i][idx + len(label):]
            # strip a leading colon / whitespace then read the first date token
            tail = tail.lstrip(" :\t")
            for tok in re.findall(
                r"[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}",
                tail,
            ):
                d = _parse_date_token(tok)
                if d:
                    return d, text_lines[i].strip()
    # fallback: first date-looking token anywhere
    for i, ln in enumerate(text_lines):
        for tok in re.findall(
            r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2}", ln):
            d = _parse_date_token(tok)
            if d:
                return d, ln.strip()
    return None, ""


def _parse_reference(text: str) -> tuple[ReferenceRange | None, str]:
    """Extract a reference range and return (range, matched_text)."""
    m = _RANGE_BETWEEN.search(text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return ReferenceRange(low=lo, high=hi, raw=f"{m.group(1)}-{m.group(2)}"), m.group(0)
    m = _RANGE_UPPER.search(text)
    if m:
        return ReferenceRange(high=float(m.group(1)), raw=f"<{m.group(1)}"), m.group(0)
    m = _RANGE_LOWER.search(text)
    if m:
        return ReferenceRange(low=float(m.group(1)), raw=f">{m.group(1)}"), m.group(0)
    return None, ""


def _parse_line(line: str) -> tuple[str, float, str, ReferenceRange, list[str], float] | None:
    """Try to parse one line into a reading.

    Returns (display_label, value, unit, reference, review_flags, confidence)
    or None if the line is not a recognizable biomarker row.
    """
    if not line.strip():
        return None

    # Locate where the numeric data begins: the first number that is NOT part
    # of the analyte name. Analyte names occasionally contain digits (e.g.
    # "Vitamin D, 25-Hydroxy") so we look for the first standalone number that
    # is followed by unit/range-like content.
    first_num = _NUMBER.search(line)
    if not first_num:
        return None
    label_part = line[: first_num.start()].strip()
    data_part = line[first_num.start():].strip()

    # Some labs (e.g. Quest) print the High/Low flag column BETWEEN the analyte
    # name and the value, so it lands at the tail of the label. Strip trailing
    # flag tokens so they don't corrupt the name match.
    prev = None
    while prev != label_part:
        prev = label_part
        label_part = re.sub(
            r"[\s|]+(high|low|hi|lo|h|l|abnormal|normal|critical|aa)\s*$",
            "", label_part, flags=re.I).strip()

    if len(label_part) < 2:
        return None

    canonical, name_score = canonical_for(label_part)
    if not canonical or name_score < 0.5:
        return None

    review: list[str] = []

    # Reference range first (so we can remove it before isolating the value).
    reference, range_text = _parse_reference(data_part)
    residual = data_part.replace(range_text, " ", 1) if range_text else data_part

    # Unit.
    unit_m = _UNIT_RE.search(residual)
    unit = unit_m.group(1) if unit_m else ""
    if unit:
        residual = residual[: unit_m.start()] + " " + residual[unit_m.end():]

    # Strip flag words (High/Low/H/L) so they aren't mistaken for values.
    residual = _FLAG_WORDS.sub(" ", residual)

    # The value is the first remaining standalone number.
    nums = _NUMBER.findall(residual)
    if not nums:
        return None
    value = float(nums[0])

    # ---- confidence ----
    conf = name_score
    if not unit:
        conf *= 0.85
        review.append("unit not detected")
    if reference is None:
        conf *= 0.90
        review.append("reference range not printed/parsed")
    if len(nums) > 1:
        # leftover numbers after removing range+unit -> value isolation ambiguous
        conf *= 0.80
        review.append(f"ambiguous value isolation (candidates: {', '.join(nums)})")
    conf = max(0.0, min(1.0, conf))

    return (display_name(canonical), value, unit, reference or ReferenceRange(),
            review, round(conf, 3))


def extract_document(doc: SourceDocument) -> tuple[list[Reading], list[str]]:
    """Extract all readings from one document. Returns (readings, doc_warnings)."""
    warnings: list[str] = []
    draw_date, date_line = find_draw_date(doc)
    if draw_date is None:
        warnings.append(f"{doc.name}: no draw date could be parsed")

    readings: list[Reading] = []
    seen: set[str] = set()
    for raw_line in doc.lines:
        parsed = _parse_line(raw_line)
        if not parsed:
            continue
        label, value, unit, reference, review, conf = parsed
        canonical, _ = canonical_for(label)
        if canonical is None:
            continue
        # De-duplicate: a marker can appear once per draw. Keep the highest
        # confidence instance if the same canonical marker repeats in one doc.
        key = canonical
        if key in seen:
            continue
        seen.add(key)

        if draw_date is None:
            review = review + ["draw date missing for this document"]

        readings.append(Reading(
            canonical=canonical,
            display_name=label,
            value=value,
            unit=unit,
            reference=reference,
            draw_date=draw_date or date.min,
            confidence=conf,
            source_file=doc.name,
            source_text=raw_line.strip(),
            review_flags=review,
        ))
    return readings, warnings


def build_series(all_readings: list[Reading]) -> list[MarkerSeries]:
    """Group readings into one MarkerSeries per canonical marker, panel-ordered."""
    by_key: dict[str, MarkerSeries] = {}
    for r in all_readings:
        s = by_key.get(r.canonical)
        if s is None:
            s = MarkerSeries(canonical=r.canonical, display_name=r.display_name)
            by_key[r.canonical] = s
        s.readings.append(r)
    series = list(by_key.values())
    series.sort(key=lambda s: panel_sort_key(s.canonical))
    return series


def extract_all(docs: list[SourceDocument]) -> tuple[list[MarkerSeries], list[Reading], list[str]]:
    """Run extraction across all documents. Returns (series, readings, warnings)."""
    all_readings: list[Reading] = []
    warnings: list[str] = []
    for doc in docs:
        readings, w = extract_document(doc)
        all_readings.extend(readings)
        warnings.extend(w)
    series = build_series(all_readings)
    return series, all_readings, warnings
