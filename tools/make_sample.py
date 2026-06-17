"""Generate the complete SAMPLE deliverable.

Creates realistic SYNTHETIC lab PDFs for a fictional client (Marcus Hale, four
draws over ~9 months on a TRT-relevant panel), writes them to
samples/source_labs/, then runs the full pipeline to produce a finished example
report at samples/Marcus_Hale_Biomarker_Timeline_SAMPLE.pdf.

EVERYTHING HERE IS FICTIONAL. The values are invented to demonstrate the
product's charts and out-of-range flagging. They are not real results and carry
no medical meaning.

To vary realism, two draws are rendered in a LabCorp-style layout and two in a
Quest-style layout, with different column orders and analyte spellings — this
exercises the synonym normalization and cross-lab time-series merging.

Run:  python tools/make_sample.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from weasyprint import HTML

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from biomarker_timeline.pipeline import run_pipeline  # noqa: E402

SAMPLES = ROOT / "samples"
SOURCE = SAMPLES / "source_labs"

CLIENT = "Marcus Hale"
DOB = "1985-04-12"

# Four draw dates spanning ~9 months.
DRAWS = [
    date(2025, 8, 25),
    date(2025, 11, 17),
    date(2026, 2, 9),
    date(2026, 5, 18),
]

# Each analyte: (canonical label, unit, reference text, [v1, v2, v3, v4]).
# Values are invented to produce a realistic spread of in-range and
# outside-range results across the timeline.
PANEL = [
    ("Testosterone, Total", "ng/dL", "264-916",   [312, 720, 880, 1040]),
    ("Testosterone, Free",  "pg/mL", "8.7-25.1",  [5.9, 14.2, 19.8, 27.5]),
    ("Sex Hormone Binding Globulin", "nmol/L", "16.5-55.9", [28, 22, 19, 17]),
    ("Estradiol",           "pg/mL", "8.0-35.0",  [22, 38, 47, 58]),
    ("LH",                  "mIU/mL", "1.7-8.6",  [4.2, 0.4, 0.3, 0.2]),
    ("FSH",                 "mIU/mL", "1.5-12.4", [3.1, 0.7, 0.5, 0.4]),
    ("Prolactin",           "ng/mL", "4.0-15.2",  [9.1, 10.2, 11.5, 12.0]),
    ("TSH",                 "uIU/mL", "0.450-4.500", [1.8, 2.1, 1.9, 2.3]),
    ("PSA, Total",          "ng/mL", "0.0-4.0",   [0.8, 0.9, 1.1, 1.4]),
    ("Hematocrit",          "%",     "38.3-48.6", [44.1, 47.8, 49.9, 51.2]),
    ("Hemoglobin",          "g/dL",  "13.2-17.1", [15.0, 16.2, 16.9, 17.4]),
    ("RBC",                 "x10E6/uL", "4.14-5.80", [5.10, 5.45, 5.72, 5.95]),
    ("Cholesterol, Total",  "mg/dL", "100-199",   [185, 192, 201, 196]),
    ("HDL Cholesterol",     "mg/dL", ">39",       [52, 48, 44, 41]),
    ("LDL Cholesterol",     "mg/dL", "0-99",      [96, 101, 110, 104]),
    ("Triglycerides",       "mg/dL", "0-149",     [120, 142, 158, 135]),
]

# Quest-style spellings differ from LabCorp's; used for the Quest layouts.
QUEST_NAMES = {
    "Testosterone, Total": "TESTOSTERONE, TOTAL",
    "Testosterone, Free": "TESTOSTERONE, FREE",
    "Sex Hormone Binding Globulin": "SEX HORMONE BINDING GLOBULIN",
    "Estradiol": "ESTRADIOL",
    "LH": "LUTEINIZING HORMONE (LH)",
    "FSH": "FOLLICLE STIMULATING HORMONE (FSH)",
    "Prolactin": "PROLACTIN",
    "TSH": "THYROID STIMULATING HORMONE",
    "PSA, Total": "PROSTATE SPECIFIC AG, TOTAL",
    "Hematocrit": "HEMATOCRIT",
    "Hemoglobin": "HEMOGLOBIN",
    "RBC": "RED BLOOD CELL COUNT",
    "Cholesterol, Total": "CHOLESTEROL, TOTAL",
    "HDL Cholesterol": "HDL CHOLESTEROL",
    "LDL Cholesterol": "LDL-CHOLESTEROL",
    "Triglycerides": "TRIGLYCERIDES",
}


def _fmt(v: float) -> str:
    return str(int(v)) if float(v) == int(v) else str(v)


def _flag(value: float, ref: str) -> str:
    """Compute the printed High/Low flag the lab would show (synthetic)."""
    import re
    mb = re.match(r"([\d.]+)-([\d.]+)$", ref)
    if mb:
        lo, hi = float(mb.group(1)), float(mb.group(2))
        if value < lo:
            return "Low"
        if value > hi:
            return "High"
    if ref.startswith(">"):
        if value < float(ref[1:]):
            return "Low"
    if ref.startswith("<"):
        if value > float(ref[1:]):
            return "High"
    return ""


_BASE_LAB_CSS = """
@page { size: Letter; margin: 0.6in; }
* { box-sizing: border-box; }
body { font-family: 'Helvetica', 'Arial', sans-serif; color: #111; font-size: 9pt; }
.hd { display:flex; justify-content:space-between; border-bottom: 2px solid #333; padding-bottom:6px; }
.lab { font-size: 16pt; font-weight: bold; letter-spacing: 0.5px; }
.lab .sub { font-size: 7.5pt; font-weight: normal; color:#555; letter-spacing:0; }
.meta { font-size: 8pt; color:#222; }
.pt { margin: 10px 0; padding: 8px 10px; background:#f3f3f3; border:1px solid #ccc; font-size: 8.5pt; }
.pt b { display:inline-block; min-width: 110px; }
h3 { font-size: 9.5pt; margin: 14px 0 4px; border-bottom:1px solid #999; padding-bottom:2px; }
table { width:100%; border-collapse: collapse; font-size: 8.6pt; }
th { text-align:left; border-bottom:1px solid #333; padding:3px 6px; font-size:7.8pt; text-transform:uppercase; }
td { padding:2.5px 6px; border-bottom:0.5px solid #ddd; }
td.r, th.r { text-align:right; }
.fl { color:#a00; font-weight:bold; }
.foot { margin-top:16px; font-size:7pt; color:#666; border-top:1px solid #ccc; padding-top:6px; }
"""


def render_labcorp(draw: date, values_idx: int) -> str:
    rows = []
    for name, unit, ref, vals in PANEL:
        v = vals[values_idx]
        fl = _flag(v, ref)
        flcell = f"<td class='fl'>{fl}</td>" if fl else "<td></td>"
        rows.append(
            f"<tr><td>{name}</td><td class='r'>{_fmt(v)}</td>{flcell}"
            f"<td>{unit}</td><td>{ref}</td></tr>"
        )
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>{_BASE_LAB_CSS}</style></head><body>
  <div class="hd">
    <div class="lab">LabCorp<div class="sub">Laboratory Corporation of America</div></div>
    <div class="meta">
      Specimen ID: 075-{draw.strftime('%y%m')}-{4400+values_idx}<br/>
      Account: VITALIS FORGE WELLNESS<br/>
      Page 1 of 1
    </div>
  </div>
  <div class="pt">
    <b>Patient Name:</b> {CLIENT} &nbsp;&nbsp; <b>DOB:</b> {DOB} &nbsp;&nbsp; <b>Sex:</b> M<br/>
    <b>Date Collected:</b> {draw.strftime('%m/%d/%Y')} &nbsp;&nbsp;
    <b>Date Reported:</b> {draw.strftime('%m/%d/%Y')} &nbsp;&nbsp;
    <b>Ordering Physician:</b> Self-Pay
  </div>
  <h3>Comprehensive Hormone &amp; Metabolic Panel</h3>
  <table>
    <thead><tr><th>Analyte</th><th class="r">Value</th><th>Flag</th>
      <th>Units</th><th>Reference Interval</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="foot">This is a SYNTHETIC specimen generated for software
    demonstration. Not a real laboratory result.</div>
</body></html>"""


def render_quest(draw: date, values_idx: int) -> str:
    # Quest layout: Analyte | Flag | Result | Reference Range | Units
    rows = []
    for name, unit, ref, vals in PANEL:
        v = vals[values_idx]
        fl = _flag(v, ref)
        flcell = f"<td class='fl'>{fl}</td>" if fl else "<td></td>"
        qname = QUEST_NAMES[name]
        rows.append(
            f"<tr><td>{qname}</td>{flcell}<td class='r'>{_fmt(v)}</td>"
            f"<td>{ref}</td><td>{unit}</td></tr>"
        )
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'>
<style>{_BASE_LAB_CSS}</style></head><body>
  <div class="hd">
    <div class="lab">Quest Diagnostics<div class="sub">Test results provided by Quest Diagnostics</div></div>
    <div class="meta">
      Accession: QD{draw.strftime('%Y%m%d')}{values_idx}<br/>
      Client: Vitalis Forge Wellness<br/>
      Page 1 of 1
    </div>
  </div>
  <div class="pt">
    <b>Patient Name:</b> {CLIENT} &nbsp;&nbsp; <b>DOB:</b> {DOB} &nbsp;&nbsp; <b>Gender:</b> Male<br/>
    <b>Collected:</b> {draw.strftime('%m/%d/%Y')} &nbsp;&nbsp;
    <b>Reported:</b> {draw.strftime('%m/%d/%Y')}
  </div>
  <h3>Hormone, CBC and Lipid Results</h3>
  <table>
    <thead><tr><th>Analyte</th><th>Flag</th><th class="r">Result</th>
      <th>Reference Range</th><th>Units</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="foot">SYNTHETIC specimen generated for software demonstration.
    Not a real laboratory result.</div>
</body></html>"""


def main() -> int:
    SOURCE.mkdir(parents=True, exist_ok=True)
    # alternate LabCorp / Quest to exercise synonym + cross-lab merging
    renderers = [render_labcorp, render_quest, render_labcorp, render_quest]
    vendors = ["LabCorp", "Quest", "LabCorp", "Quest"]
    print("Generating synthetic source lab PDFs…")
    for i, (draw, render, vendor) in enumerate(zip(DRAWS, renderers, vendors), start=1):
        html = render(draw, i - 1)
        out = SOURCE / f"draw{i}_{vendor}_{draw.isoformat()}.pdf"
        HTML(string=html).write_pdf(str(out))
        print(f"  · {out.relative_to(ROOT)}")

    report_path = SAMPLES / "Marcus_Hale_Biomarker_Timeline_SAMPLE.pdf"
    print("\nRunning the full pipeline on the synthetic labs…")
    result = run_pipeline(
        input_dir=SOURCE,
        output_path=report_path,
        client_name=CLIENT,
    )
    if not result.passed:
        print("\nSample generation halted at self-check (see review_needed.txt).")
        return 2
    print(f"\nSAMPLE complete: {report_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
