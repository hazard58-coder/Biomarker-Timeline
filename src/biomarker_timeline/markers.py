"""Canonical biomarker dictionary and synonym normalization.

Real LabCorp / Quest reports print the same analyte under many spellings
("Testosterone, Total", "Total Testosterone", "TESTOSTERONE,TOTAL", "Test Total").
This module maps every known spelling to a single canonical key so a marker's
values line up into one time series across draws and across labs.

Nothing here interprets values. It only recognizes and labels analytes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MarkerDef:
    key: str                       # canonical key
    display_name: str              # canonical human label used in the report
    panel: str                     # grouping for the report ("Androgens", "CBC", ...)
    synonyms: tuple[str, ...] = field(default_factory=tuple)
    typical_units: tuple[str, ...] = field(default_factory=tuple)


# Ordered roughly the way a clinician reads a TRT panel. The report respects
# this order so related markers sit near each other.
MARKERS: list[MarkerDef] = [
    MarkerDef("testosterone_total", "Testosterone, Total", "Androgens",
              ("testosterone total", "total testosterone", "testosterone,total",
               "testosterone serum", "testosterone, serum", "test total", "testosterone"),
              ("ng/dL",)),
    MarkerDef("testosterone_free", "Testosterone, Free", "Androgens",
              ("testosterone free", "free testosterone", "testosterone,free",
               "free testosterone direct", "testosterone free direct",
               "free test", "testosterone, free (direct)"),
              ("pg/mL", "ng/dL")),
    MarkerDef("shbg", "Sex Hormone Binding Globulin (SHBG)", "Androgens",
              ("shbg", "sex hormone binding globulin", "sex hormone-binding globulin",
               "sex hormone binding globulin (shbg)"),
              ("nmol/L",)),
    MarkerDef("estradiol", "Estradiol", "Hormones",
              ("estradiol", "estradiol sensitive", "estradiol, sensitive",
               "estradiol (sensitive)", "e2", "estradiol, ultrasensitive",
               "estradiol ultrasensitive"),
              ("pg/mL",)),
    MarkerDef("lh", "Luteinizing Hormone (LH)", "Hormones",
              ("lh", "luteinizing hormone", "luteinizing hormone (lh)", "lutenizing hormone"),
              ("mIU/mL",)),
    MarkerDef("fsh", "Follicle Stimulating Hormone (FSH)", "Hormones",
              ("fsh", "follicle stimulating hormone", "follicle-stimulating hormone",
               "follicle stimulating hormone (fsh)"),
              ("mIU/mL",)),
    MarkerDef("prolactin", "Prolactin", "Hormones",
              ("prolactin",), ("ng/mL",)),
    MarkerDef("tsh", "Thyroid Stimulating Hormone (TSH)", "Hormones",
              ("tsh", "thyroid stimulating hormone", "thyroid-stimulating hormone"),
              ("uIU/mL", "mIU/L")),
    MarkerDef("psa", "Prostate Specific Antigen (PSA)", "Prostate",
              ("psa", "prostate specific antigen", "prostate-specific antigen",
               "psa, total", "psa total", "prostate specific ag, total"),
              ("ng/mL",)),
    MarkerDef("hematocrit", "Hematocrit", "Complete Blood Count",
              ("hematocrit", "hct", "haematocrit"), ("%",)),
    MarkerDef("hemoglobin", "Hemoglobin", "Complete Blood Count",
              ("hemoglobin", "hgb", "haemoglobin"), ("g/dL",)),
    MarkerDef("rbc", "Red Blood Cell Count", "Complete Blood Count",
              ("rbc", "red blood cell count", "red blood cells", "erythrocytes"),
              ("x10E6/uL", "M/uL")),
    MarkerDef("cholesterol_total", "Cholesterol, Total", "Lipid Panel",
              ("cholesterol total", "total cholesterol", "cholesterol,total",
               "cholesterol, total", "cholesterol serum"),
              ("mg/dL",)),
    MarkerDef("hdl", "HDL Cholesterol", "Lipid Panel",
              ("hdl", "hdl cholesterol", "hdl-c", "hdl chol", "cholesterol hdl"),
              ("mg/dL",)),
    MarkerDef("ldl", "LDL Cholesterol", "Lipid Panel",
              ("ldl", "ldl cholesterol", "ldl-c", "ldl chol calc", "ldl chol",
               "ldl cholesterol calc", "ldl-cholesterol"),
              ("mg/dL",)),
    MarkerDef("triglycerides", "Triglycerides", "Lipid Panel",
              ("triglycerides", "triglycerides", "trig", "triglyceride"),
              ("mg/dL",)),
]

_PANEL_ORDER = ["Androgens", "Hormones", "Prostate", "Complete Blood Count", "Lipid Panel"]

# Build lookup tables.
_BY_KEY: dict[str, MarkerDef] = {m.key: m for m in MARKERS}
_SYNONYM_INDEX: dict[str, str] = {}
for _m in MARKERS:
    _SYNONYM_INDEX[_normalize := _m.display_name.lower()] = _m.key
    for _s in _m.synonyms:
        _SYNONYM_INDEX[_s.lower()] = _m.key


def _clean(name: str) -> str:
    """Lowercase and squeeze a printed label for matching."""
    s = name.lower().strip()
    # drop trailing method/flag tokens labs append, and punctuation noise
    s = re.sub(r"\b(serum|plasma|lc/ms-ms|lcmsms|direct|calc|calculated|by .*)\b", " ", s)
    s = s.replace(",", " ").replace(".", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def canonical_for(label: str) -> tuple[str | None, float]:
    """Resolve a printed analyte label to a canonical key with a match confidence.

    Returns (canonical_key | None, confidence_contribution in 0..1).
    Exact synonym hits score 1.0; cleaned/substring hits score lower so the
    SELF-CHECK stage can route fuzzy matches to human review.
    """
    raw = label.lower().strip().rstrip(":")
    if raw in _SYNONYM_INDEX:
        return _SYNONYM_INDEX[raw], 1.0

    cleaned = _clean(label)
    if cleaned in _SYNONYM_INDEX:
        return _SYNONYM_INDEX[cleaned], 0.95

    # token-aware containment match against each synonym's cleaned form.
    # We pad with spaces so matches respect whole-token boundaries (avoids
    # "lh" matching inside an unrelated word).
    padded = f" {cleaned} "
    best_key, best_score = None, 0.0
    for syn, key in _SYNONYM_INDEX.items():
        cs = _clean(syn)
        if not cs or len(cs) < 3:
            continue
        if cs == cleaned:
            return key, 0.95
        if f" {cs} " in padded or padded.strip() in f" {cs} ":
            # prefer longer (more specific, more complete) matches
            score = 0.7 * (min(len(cs), len(cleaned)) / max(len(cs), len(cleaned)))
            if score > best_score:
                best_key, best_score = key, max(0.55, score)
    return best_key, best_score


def display_name(key: str) -> str:
    return _BY_KEY[key].display_name if key in _BY_KEY else key


def panel_for(key: str) -> str:
    return _BY_KEY[key].panel if key in _BY_KEY else "Other"


def panel_sort_key(key: str) -> tuple[int, int]:
    """Sort canonical keys by panel order, then by their order within MARKERS."""
    m = _BY_KEY.get(key)
    if not m:
        return (len(_PANEL_ORDER), 999)
    panel_idx = _PANEL_ORDER.index(m.panel) if m.panel in _PANEL_ORDER else len(_PANEL_ORDER)
    within = next((i for i, x in enumerate(MARKERS) if x.key == key), 999)
    return (panel_idx, within)


def known_units(key: str) -> tuple[str, ...]:
    m = _BY_KEY.get(key)
    return m.typical_units if m else ()
