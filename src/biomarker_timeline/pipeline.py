"""The repeatable four-stage pipeline: INTAKE → EXTRACT → SELF-CHECK → OUTPUT.

This is the workflow that produces the thing people buy. The self-check is a
hard gate: if it fails, no PDF is written — a `review_needed.txt` is produced
instead, and a human must verify the listed items before re-running.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from datetime import date

from . import ai_extract
from .extract import (build_series, coverage_report, dedupe_readings, extract_all,
                      find_draw_date)
from .intake import SourceDocument, intake
from .report import ReportContext, build_html, render_pdf, visible_text
from .selfcheck import run_self_check

_NAME_LABELS = ["patient name", "patient", "name", "client name", "client"]


def detect_client_name(docs: list[SourceDocument]) -> str | None:
    """Best-effort transcription of the patient name from the source PDFs.

    Purely a transcription convenience for the cover page; never inferred.
    """
    for doc in docs:
        for ln in doc.lines:
            low = ln.lower()
            for label in _NAME_LABELS:
                m = re.search(
                    rf"\b{re.escape(label)}\b\s*[:#]\s*([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){{0,3}})",
                    ln, flags=re.I)
                if m and label in low:
                    name = m.group(1).strip()
                    # avoid grabbing a following field label
                    name = re.split(r"\b(dob|date|id|sex|gender|age|account|mrn)\b", name, flags=re.I)[0].strip()
                    if 2 <= len(name) <= 40:
                        return name
    return None


@dataclass
class PipelineResult:
    passed: bool
    output_path: Path | None
    review_path: Path | None
    n_markers: int
    n_readings: int
    n_draws: int


def run_pipeline(
    input_dir: Path,
    output_path: Path,
    client_name: str | None = None,
    verbose: bool = True,
) -> PipelineResult:
    input_dir = Path(input_dir)
    output_path = Path(output_path)
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        if verbose:
            print(msg)

    # ---- STAGE 1: INTAKE ----
    log("\n[1/4] INTAKE — reading lab PDFs…")
    docs = intake(input_dir)
    if not docs:
        raise SystemExit(
            f"No PDF files found in {input_dir}. "
            f"Drop the client's lab PDFs there and run again."
        )
    for d in docs:
        log(f"      · {d.name} ({len(d.pages)} page(s))")

    # ---- STAGE 2: EXTRACT ----
    log("\n[2/4] EXTRACT — pulling biomarkers and building time series…")
    series, readings, warnings = extract_all(docs)

    # Optional AI fallback (Claude): reads layouts the regex misses, transcription
    # only. The self-check below still re-verifies every value against the source.
    if ai_extract.enabled():
        log(f"      · AI fallback enabled (model: {ai_extract.MODEL})")
        ai_readings = []
        for doc in docs:
            dd, _ = find_draw_date(doc)
            ai_readings.extend(ai_extract.extract_document(doc, dd or date.min))
            # Scanned/image pages (no text) read via Claude vision — per-page date,
            # falling back to the document's own date for pages without one.
            ai_readings.extend(ai_extract.extract_document_vision(doc, dd or date.min))
        if ai_readings:
            readings, notes = dedupe_readings(readings + ai_readings)
            series = build_series(readings)
            warnings.extend(notes)
            log(f"      · with AI -> {len(readings)} readings across {len(series)} markers")

    # If some readings still have no date but the whole upload has exactly ONE
    # distinct draw date, attribute the undated ones to it (single-draw upload
    # across multiple files). Flagged, never invented from nothing.
    known_dates = {r.draw_date for r in readings if r.draw_date != date.min}
    if len(known_dates) == 1:
        only = next(iter(known_dates))
        for r in readings:
            if r.draw_date == date.min:
                r.draw_date = only
                r.review_flags.append("draw date taken from the other file(s) in this upload")
        series = build_series(readings)

    log(f"      · {len(readings)} readings across {len(series)} markers, "
        f"{len({r.draw_date for r in readings})} draw date(s)")
    for w in warnings:
        log(f"      ! {w}")

    # Coverage audit (operator-facing): what was captured vs missed per file.
    coverage = coverage_report(docs, readings)
    (output_dir / "coverage.txt").write_text(coverage, encoding="utf-8")
    if verbose:
        log("\n" + coverage)

    name = client_name or detect_client_name(docs) or "Client"
    ctx = ReportContext(
        client_name=name,
        series=series,
        readings=readings,
        source_files=[d.name for d in docs],
    )

    # Build the report HTML now (in memory) so the self-check can scan the
    # exact text that WOULD be rendered, before any PDF exists.
    html_str = build_html(ctx)
    rendered_text = visible_text(html_str)

    # ---- STAGE 3: SELF-CHECK (mandatory gate) ----
    log("\n[3/4] SELF-CHECK — validating before anything is shipped…")
    check = run_self_check(readings, series, rendered_text, extra_warnings=warnings)
    check.print_summary()

    n_draws = len({r.draw_date for r in readings})
    if not check.passed:
        review_path = output_dir / "review_needed.txt"
        check.write_review_file(review_path)
        log(f"      Halted. Wrote {review_path}")
        log("      No report was generated. Resolve the items above and re-run.")
        return PipelineResult(False, None, review_path, len(series), len(readings), n_draws)

    # A stale review file from a prior failed run would be misleading — clear it.
    stale = output_dir / "review_needed.txt"
    if stale.exists():
        stale.unlink()

    # ---- STAGE 4: OUTPUT ----
    log("[4/4] OUTPUT — rendering branded PDF…")
    render_pdf(html_str, output_path)
    log(f"      Done. Report written to {output_path}")
    return PipelineResult(True, output_path, None, len(series), len(readings), n_draws)
