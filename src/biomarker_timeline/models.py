"""Core data structures for the Biomarker Timeline pipeline.

These are deliberately plain dataclasses with no behavior beyond simple,
factual helpers. Nothing here interprets a value — a `Reading` only knows
whether it falls inside or outside the lab's OWN printed reference range,
which is transcription, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class ReferenceRange:
    """A lab's own printed reference range for a marker.

    Exactly as printed on the source PDF. We never invent a range; if the lab
    did not print one, `low`/`high` stay None and the report says so.
    """

    low: Optional[float] = None
    high: Optional[float] = None
    raw: str = ""  # the literal text as it appeared on the page, e.g. ">39" or "264-916"

    @property
    def has_range(self) -> bool:
        return self.low is not None or self.high is not None

    def contains(self, value: float) -> Optional[bool]:
        """Return True/False if the value is within the printed range, else None.

        None means "no range was printed, so no factual statement can be made."
        This is a purely arithmetic comparison against the lab's own numbers.
        """
        if not self.has_range:
            return None
        if self.low is not None and value < self.low:
            return False
        if self.high is not None and value > self.high:
            return False
        return True

    def display(self) -> str:
        if self.raw:
            return self.raw
        if self.low is not None and self.high is not None:
            return f"{_fmt(self.low)}–{_fmt(self.high)}"
        if self.high is not None:
            return f"≤{_fmt(self.high)}"
        if self.low is not None:
            return f"≥{_fmt(self.low)}"
        return "—"


@dataclass
class Reading:
    """A single biomarker value from a single lab draw.

    `source_text` is the exact line the value was transcribed from, retained so
    the SELF-CHECK stage can re-verify every number against its source.
    """

    canonical: str          # canonical marker key, e.g. "testosterone_total"
    display_name: str       # human label, e.g. "Testosterone, Total"
    value: float
    unit: str
    reference: ReferenceRange
    draw_date: date
    confidence: float       # 0.0 - 1.0
    source_file: str = ""
    source_text: str = ""   # the literal source line, for re-verification
    review_flags: list[str] = field(default_factory=list)

    @property
    def in_range(self) -> Optional[bool]:
        return self.reference.contains(self.value)

    @property
    def out_of_range(self) -> bool:
        """True only when the lab printed a range AND the value falls outside it."""
        return self.in_range is False

    def range_position(self) -> Optional[str]:
        """Factual position relative to the printed range: 'below' / 'above'.

        This is transcription of an arithmetic comparison, not a judgment about
        what the position means for the person.
        """
        if not self.reference.has_range:
            return None
        if self.reference.low is not None and self.value < self.reference.low:
            return "below"
        if self.reference.high is not None and self.value > self.reference.high:
            return "above"
        return None

    def value_str(self) -> str:
        return _fmt(self.value)


@dataclass
class MarkerSeries:
    """The full time series for one canonical marker across all draws."""

    canonical: str
    display_name: str
    readings: list[Reading] = field(default_factory=list)

    def ordered(self) -> list[Reading]:
        return sorted(self.readings, key=lambda r: r.draw_date)

    @property
    def units(self) -> list[str]:
        seen: list[str] = []
        for r in self.readings:
            if r.unit not in seen:
                seen.append(r.unit)
        return seen

    @property
    def unit(self) -> str:
        u = self.units
        return u[0] if u else ""

    @property
    def has_unit_mismatch(self) -> bool:
        return len([u for u in self.units if u]) > 1

    @property
    def latest(self) -> Reading:
        return self.ordered()[-1]

    @property
    def n_out_of_range(self) -> int:
        return sum(1 for r in self.readings if r.out_of_range)


def _fmt(x: float) -> str:
    """Format a number without trailing-zero noise (652.0 -> '652', 25.10 -> '25.1')."""
    if x == int(x):
        return str(int(x))
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s
