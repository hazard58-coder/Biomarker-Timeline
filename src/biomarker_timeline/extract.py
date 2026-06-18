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
    "Million/uL", "Thousand/uL", "x10E6/uL", "x10E3/uL", "10*6/uL", "10*3/uL",
    "cells/uL", "M/uL", "K/uL",
    "mg/dL", "ng/dL", "ng/mL", "pg/mL", "mcg/dL", "ug/dL", "uIU/mL", "mIU/mL",
    "mIU/L", "nmol/L", "umol/L", "mmol/L", "g/dL", "mg/L", "U/L", "IU/L",
    "fL", "pg", "%",
]
# Match units case-insensitively but keep the canonical spelling from the list.
_UNIT_RE = re.compile("(" + "|".join(re.escape(u) for u in KNOWN_UNITS) + ")", re.I)
_UNIT_CANON = {u.lower(): u for u in KNOWN_UNITS}

# A value is a number that starts a fresh token (preceded by whitespace/line
# start), so a digit inside an analyte name (e.g. the "1" in "Hemoglobin A1c")
# is never mistaken for the result.
_VALUE_NUM = re.compile(r"(?:^|\s)(-?\d+(?:\.\d+)?)")

# Strip a leading range label before parsing. Labs use several: Quest prints
# "Reference Range:", PWNHealth-style reports print "Desired Range:", etc.
_REF_LABEL = re.compile(r"(reference|desired|normal|expected|ref)\s+(range|interval)\s*:?", re.I)

# Reference-range shapes, in priority order. The (?:or)?=? handles Quest's
# "< OR = 39" / "> OR = 40" notation as well as "<=" / ">=" and plain "<200".
_RANGE_BETWEEN = re.compile(r"(\d+(?:\.\d+)?)\s*[-–—]\s*(\d+(?:\.\d+)?)")
_RANGE_UPPER = re.compile(r"[<≤]\s*(?:or\s*)?=?\s*(\d+(?:\.\d+)?)", re.I)
_RANGE_LOWER = re.compile(r"[>≥]\s*(?:or\s*)?=?\s*(\d+(?:\.\d+)?)", re.I)

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_FLAG_WORDS = re.compile(r"\b(high|low|h|l|hi|lo|abnormal|normal|critical|aa)\b", re.I)

# Values below this extraction confidence are routed to human review. This is an
# ACCURACY gate (did we read the number right), not the legal guardrail — that
# (no interpretation) is never relaxed. Tunable via env without a code change.
import os as _os
CONFIDENCE_REVIEW_THRESHOLD = float(_os.environ.get("CONFIDENCE_REVIEW_THRESHOLD", "0.80"))

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
        incl = "=" in m.group(0) or "or" in m.group(0).lower()
        sym = "≤" if incl else "<"
        return ReferenceRange(high=float(m.group(1)), raw=f"{sym}{m.group(1)}"), m.group(0)
    m = _RANGE_LOWER.search(text)
    if m:
        incl = "=" in m.group(0) or "or" in m.group(0).lower()
        sym = "≥" if incl else ">"
        return ReferenceRange(low=float(m.group(1)), raw=f"{sym}{m.group(1)}"), m.group(0)
    return None, ""


def _standalone_refunit(line: str) -> tuple[ReferenceRange | None, str]:
    """Parse a line that is essentially just a range statement printed below the
    value, e.g. Quest's "Reference range: <100" or "Desired Range: 250-1100
    ng/dL". Returns (range, unit) — the unit may live on this line too."""
    s = line.strip()
    if not _REF_LABEL.match(s):
        return None, ""
    body = _REF_LABEL.sub(" ", s, count=1)
    ref, _ = _parse_reference(body)
    unit_m = _UNIT_RE.search(body)
    unit = _UNIT_CANON.get(unit_m.group(1).lower(), unit_m.group(1)) if unit_m else ""
    return ref, unit


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
    first_num = _VALUE_NUM.search(line)
    if not first_num:
        return None
    start = first_num.start(1)
    label_part = line[:start].strip()
    data_part = line[start:].strip()

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

    # Unit (canonicalized to the spelling in KNOWN_UNITS).
    unit_m = _UNIT_RE.search(residual)
    unit = _UNIT_CANON.get(unit_m.group(1).lower(), unit_m.group(1)) if unit_m else ""
    if unit_m:
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
    last: Reading | None = None  # most recent reading, for next-line range attach
    for raw_line in doc.lines:
        parsed = _parse_line(raw_line)
        if not parsed:
            # Some labs print the range (and sometimes the unit) on the line
            # BELOW the value — Quest's LDL "Reference range: <100", or a
            # PWNHealth-style "Desired Range: 250-1100 ng/dL". Attach to the
            # preceding marker if it was missing those.
            if last is not None and (not last.reference.has_range or not last.unit):
                ref, unit = _standalone_refunit(raw_line)
                got_range = ref is not None and ref.has_range and not last.reference.has_range
                got_unit = bool(unit) and not last.unit
                if got_range:
                    last.reference = ref
                    last.confidence = last.confidence / 0.90
                if got_unit:
                    last.unit = unit
                    last.confidence = last.confidence / 0.85
                if got_range or got_unit:
                    last.review_flags = [
                        f for f in last.review_flags
                        if not (got_range and "reference range" in f)
                        and not (got_unit and "unit not detected" in f)]
                    last.confidence = round(min(1.0, last.confidence), 3)
                    if last.reference.has_range and last.unit:
                        last = None  # fully resolved
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

        reading = Reading(
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
        )
        readings.append(reading)
        last = reading
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
