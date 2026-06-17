"""Stage 3 — SELF-CHECK (mandatory).

Validate extracted output against a fixed quality checklist and print a
PASS/FAIL line for each item. If any check FAILs, the pipeline halts and writes
`review_needed.txt` listing exactly what a human must verify. An unreviewed
report is never shipped.

The six checks (from the build brief):
  1. Every extracted value re-verified against the source text; no invented
     markers or numbers.
  2. Any value with low extraction confidence is flagged for human review,
     not silently included.
  3. Every draw date parsed and ordered correctly.
  4. Units consistent within each marker across dates (flag mismatches).
  5. Each marker's reference range captured where printed.
  6. No interpretive language anywhere in the output (banned-words scan).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .extract import CONFIDENCE_REVIEW_THRESHOLD
from .models import MarkerSeries, Reading

# Banned interpretive words. These are judgment/advice words; the report only
# transcribes and organizes, so none of these may appear in visible output.
# (Disclaimers are phrased to avoid every one of these on purpose.)
BANNED_WORDS = [
    "should", "suggests", "suggest", "optimal", "consider", "recommend",
    "recommended", "indicates", "indicate", "advise",
    "high", "low", "elevated", "deficient", "deficiency", "abnormal",
    "improve", "improved", "worsen", "better", "worse", "healthy", "unhealthy",
    "normal", "good", "bad", "concerning", "ideal",
]
_BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in BANNED_WORDS) + r")\b", re.I)

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_RANGE_HINT = re.compile(r"\d+(?:\.\d+)?\s*[-–—]\s*\d+(?:\.\d+)?|[<>≤≥]\s*\d")


@dataclass
class CheckResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)

    def line(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}"


@dataclass
class SelfCheckReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def print_summary(self) -> None:
        print("\n=== SELF-CHECK ===")
        for c in self.checks:
            print("  " + c.line())
            for d in c.details:
                print(f"        - {d}")
        verdict = "PASS — report cleared for rendering" if self.passed \
            else "FAIL — report halted; see review_needed.txt"
        print(f"=== {verdict} ===\n")

    def write_review_file(self, path: Path) -> None:
        lines = [
            "REVIEW NEEDED — Biomarker Timeline self-check did not pass.",
            "An unreviewed report is never shipped. A human must verify the items",
            "below against the source lab PDFs before this report can be generated.",
            "",
            f"Generated: {date.today().isoformat()}",
            "=" * 64,
            "",
        ]
        for c in self.checks:
            if c.passed:
                lines.append(f"[PASS] {c.name}")
            else:
                lines.append(f"[FAIL] {c.name}")
                for d in c.details:
                    lines.append(f"    - {d}")
            lines.append("")
        Path(path).write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_values_verified(readings: list[Reading]) -> CheckResult:
    details: list[str] = []
    for r in readings:
        if not r.source_text:
            details.append(f"{r.display_name} ({r.source_file}): no source text retained")
            continue
        src_nums = {float(n) for n in _NUMBER.findall(r.source_text)}
        if not any(abs(r.value - n) < 1e-6 for n in src_nums):
            details.append(
                f"{r.display_name} = {r.value_str()} not found in source line "
                f"[{r.source_file}]: \"{r.source_text}\""
            )
    return CheckResult(
        "1. Every extracted value re-verified against source text (no invented numbers)",
        passed=not details, details=details)


def _check_low_confidence(readings: list[Reading]) -> CheckResult:
    details: list[str] = []
    for r in readings:
        if r.confidence < CONFIDENCE_REVIEW_THRESHOLD:
            reasons = "; ".join(r.review_flags) or "low match confidence"
            details.append(
                f"{r.display_name} ({r.source_file}, {r.draw_date}): "
                f"confidence {r.confidence:.2f} < {CONFIDENCE_REVIEW_THRESHOLD:.2f} "
                f"[{reasons}] — verify against source"
            )
    return CheckResult(
        "2. Low-confidence values routed to human review (none silently included)",
        passed=not details, details=details)


def _check_dates(readings: list[Reading], series: list[MarkerSeries]) -> CheckResult:
    details: list[str] = []
    for r in readings:
        if r.draw_date == date.min:
            details.append(f"{r.display_name} ({r.source_file}): draw date not parsed")
    for s in series:
        dates = [r.draw_date for r in s.ordered() if r.draw_date != date.min]
        dups = {d for d in dates if dates.count(d) > 1}
        for d in dups:
            details.append(f"{s.display_name}: duplicate draw date {d} (cannot order cleanly)")
    return CheckResult(
        "3. Every draw date parsed and ordered correctly",
        passed=not details, details=details)


def _check_units(series: list[MarkerSeries]) -> CheckResult:
    details: list[str] = []
    for s in series:
        if s.has_unit_mismatch:
            details.append(
                f"{s.display_name}: inconsistent units across dates "
                f"({', '.join(u or '(blank)' for u in s.units)})"
            )
    return CheckResult(
        "4. Units consistent within each marker across dates",
        passed=not details, details=details)


def _check_ranges(readings: list[Reading]) -> CheckResult:
    details: list[str] = []
    for r in readings:
        printed = bool(_RANGE_HINT.search(r.source_text))
        if printed and not r.reference.has_range:
            details.append(
                f"{r.display_name} ({r.source_file}): source line appears to print a "
                f"range but none was captured: \"{r.source_text}\""
            )
    return CheckResult(
        "5. Reference range captured wherever the lab printed one",
        passed=not details, details=details)


def _check_no_interpretation(rendered_text: str) -> CheckResult:
    details: list[str] = []
    for m in _BANNED_RE.finditer(rendered_text):
        start = max(0, m.start() - 35)
        end = min(len(rendered_text), m.end() + 35)
        snippet = " ".join(rendered_text[start:end].split())
        details.append(f"banned word '{m.group(0)}' in output: \"…{snippet}…\"")
    # de-duplicate identical snippets
    details = list(dict.fromkeys(details))
    return CheckResult(
        "6. No interpretive language anywhere in the output (banned-words scan)",
        passed=not details, details=details)


def run_self_check(
    readings: list[Reading],
    series: list[MarkerSeries],
    rendered_text: str,
    extra_warnings: list[str] | None = None,
) -> SelfCheckReport:
    """Run all six checks. `rendered_text` is the visible text of the report
    that WILL be rendered, scanned here before any PDF is produced."""
    report = SelfCheckReport(checks=[
        _check_values_verified(readings),
        _check_low_confidence(readings),
        _check_dates(readings, series),
        _check_units(series),
        _check_ranges(readings),
        _check_no_interpretation(rendered_text),
    ])
    # Surface intake/extract warnings as informational notes on check 3 (dates),
    # where most warnings originate. They do not by themselves flip a verdict —
    # the dedicated checks above own pass/fail.
    if extra_warnings:
        for w in extra_warnings:
            report.checks[2].details.append(f"note: {w}")
    return report
