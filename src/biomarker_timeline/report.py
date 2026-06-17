"""Stage 4 — OUTPUT.

Render the branded Vitalis Forge PDF: a cover page with the full disclaimer,
one trend chart per biomarker (value over time with the reference band shaded),
a master data table, and a closing "bring this to your physician" page.

Every disclaimer is deliberately written WITHOUT any banned interpretive word
(see selfcheck.BANNED_WORDS) — including in negation — so the self-check's
banned-word scan can stay strict and global.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from weasyprint import HTML

from . import theme
from .charts import chart_png_b64
from .markers import panel_for
from .models import MarkerSeries, Reading

BRAND_NAME = "Vitalis Forge"
PRODUCT_NAME = "Biomarker Timeline"

FOOTER_TEXT = (
    f"{PRODUCT_NAME} by {BRAND_NAME}  ·  Data-organization report, not medical "
    f"advice  ·  Review all results with a licensed physician"
)

# Full first-page disclaimer. Contains NO banned word, even in negation.
COVER_DISCLAIMER = (
    "This report is a data-organization document. It transcribes and charts the "
    "values from the lab PDFs you provided, next to each lab's own printed "
    "reference range. It does not interpret those values, diagnose any condition, "
    "or prescribe any treatment, dose, supplement, or action. Every number and "
    "every range shown here is copied directly from your source lab reports. "
    "Review all results with a licensed physician, who is the appropriate person "
    "to discuss what they mean for you."
)

HOW_TO_READ = (
    "Each chart below shows one biomarker's values across your draw dates. The "
    "shaded band is the reference range printed on that lab's own report. A point "
    "drawn in ember falls outside that printed range; a point in gold falls inside "
    "it. The number beside each point is the transcribed value for that draw."
)

CLOSING_TEXT = (
    "This timeline was built for one purpose: to put your own numbers in front of "
    "a licensed physician in a single, readable document. Bring this report to your "
    "next appointment. The reference ranges shown are the labs' own; the values are "
    "yours, transcribed from the PDFs you provided. Any question about what a value "
    "means for you is a question for your physician."
)


@dataclass
class ReportContext:
    client_name: str
    series: list[MarkerSeries]
    readings: list[Reading]
    generated_on: date = field(default_factory=date.today)
    source_files: list[str] = field(default_factory=list)

    @property
    def draw_dates(self) -> list[date]:
        ds = sorted({r.draw_date for r in self.readings if r.draw_date != date.min})
        return ds

    @property
    def date_span(self) -> str:
        ds = self.draw_dates
        if not ds:
            return "—"
        if len(ds) == 1:
            return ds[0].strftime("%b %-d, %Y")
        return f"{ds[0].strftime('%b %-d, %Y')} – {ds[-1].strftime('%b %-d, %Y')}"

    @property
    def n_flags(self) -> int:
        return sum(1 for r in self.readings if r.out_of_range)


def _esc(s: str) -> str:
    return _html.escape(str(s))


def _page_css() -> str:
    return f"""
@page {{
  size: Letter;
  margin: 0.7in 0.65in 0.85in 0.65in;
  background: {theme.OBSIDIAN};
  @bottom-center {{
    content: "{FOOTER_TEXT}";
    font-family: 'Inter', sans-serif;
    font-size: 6.8pt;
    color: {theme.MUTED};
    margin-top: 6pt;
  }}
  @bottom-right {{
    content: counter(page) " / " counter(pages);
    font-family: 'Inter', sans-serif;
    font-size: 6.8pt;
    color: {theme.MUTED};
  }}
}}
/* Brand rule #2: the named cover page must NULL the footer explicitly. */
@page cover {{
  margin: 0.7in 0.65in 0.7in 0.65in;
  @bottom-center {{ content: none; }}
  @bottom-right {{ content: none; }}
}}
.cover-page {{ page: cover; }}
.page-break {{ break-before: page; }}
.avoid-break {{ break-inside: avoid; }}
"""


def _cover_html(ctx: ReportContext) -> str:
    files = "".join(f"<li>{_esc(f)}</li>" for f in ctx.source_files) or "<li>—</li>"
    return f"""
<section class="cover-page">
  <div class="brandbar">
    <span class="wordmark">VITALIS&nbsp;FORGE</span>
    <span class="brandtag">WELLNESS · DATA</span>
  </div>
  <hr class="rule"/>
  <div class="cover-title">
    <div class="kicker">PERSONAL BIOMARKER REPORT</div>
    <h1>Biomarker<br/>Timeline</h1>
    <div class="cover-sub">Prepared for <span class="gold">{_esc(ctx.client_name)}</span></div>
  </div>

  <table style="table-layout:fixed; width:100%; margin-top:14pt;"><tr>
    <td width="33%"><div class="stat"><div class="stat-n">{len(ctx.series)}</div>
        <div class="stat-l">Biomarkers tracked</div></div></td>
    <td width="33%"><div class="stat"><div class="stat-n">{len(ctx.draw_dates)}</div>
        <div class="stat-l">Lab draws</div></div></td>
    <td width="34%"><div class="stat"><div class="stat-n">{ctx.n_flags}</div>
        <div class="stat-l">Values outside lab range</div></div></td>
  </tr></table>

  <div class="panel" style="margin-top:14pt;">
    <table style="table-layout:fixed; width:100%;"><tr>
      <td width="50%">
        <div class="meta-l">DATE RANGE</div>
        <div class="meta-v">{_esc(ctx.date_span)}</div>
      </td>
      <td width="50%">
        <div class="meta-l">REPORT GENERATED</div>
        <div class="meta-v">{ctx.generated_on.strftime('%B %-d, %Y')}</div>
      </td>
    </tr></table>
    <div class="meta-l" style="margin-top:10pt;">SOURCE LAB FILES</div>
    <ul class="filelist">{files}</ul>
  </div>

  <div class="disclaimer-box">
    <div class="disclaimer-h">IMPORTANT — PLEASE READ FIRST</div>
    <p>{_esc(COVER_DISCLAIMER)}</p>
  </div>
</section>
"""


def _chart_block(ctx: ReportContext) -> str:
    blocks = ["<section class='page-break'>",
              "<h2>Biomarker Trends</h2>",
              f"<p class='muted small'>{_esc(HOW_TO_READ)}</p>",
              "<hr class='rule-thin'/>"]
    current_panel = None
    for s in ctx.series:
        panel = panel_for(s.canonical)
        if panel != current_panel:
            blocks.append(f"<div class='panel-label'>{_esc(panel)}</div>")
            current_panel = panel
        img = chart_png_b64(s)
        readings = s.ordered()
        # factual per-draw caption row
        cells = []
        for r in readings:
            flag = ""
            if r.out_of_range:
                pos = r.range_position() or "outside"
                flag = f" <span class='flagged'>({pos} range)</span>"
            cells.append(
                f"<span class='cap-date'>{r.draw_date.strftime('%b %Y')}:</span> "
                f"<span class='cap-val'>{_esc(r.value_str())} {_esc(r.unit)}</span>{flag}"
            )
        caption = " &nbsp;·&nbsp; ".join(cells)
        flagnote = ""
        if s.n_out_of_range:
            flagnote = (f"<span class='tag tag-flag'>{s.n_out_of_range} OUTSIDE LAB RANGE</span>")
        else:
            flagnote = "<span class='tag tag-inrange'>ALL INSIDE LAB RANGE</span>"
        blocks.append(f"""
        <div class="chart-card avoid-break">
          <div class="chart-head">
            <span class="chart-name">{_esc(s.display_name)}</span>
            {flagnote}
          </div>
          <img class="chart-img" src="data:image/png;base64,{img}"/>
          <div class="chart-cap">{caption}</div>
        </div>
        """)
    blocks.append("</section>")
    return "".join(blocks)


def _master_table(ctx: ReportContext) -> str:
    dates = ctx.draw_dates
    date_headers = "".join(
        f"<th class='num'>{d.strftime('%b %-d<br/>%Y')}</th>" for d in dates)
    rows = []
    current_panel = None
    n_cols = 3 + len(dates)
    for s in ctx.series:
        panel = panel_for(s.canonical)
        if panel != current_panel:
            rows.append(f"<tr class='panelhead'><td colspan='{n_cols}'>{_esc(panel)}</td></tr>")
            current_panel = panel
        by_date = {r.draw_date: r for r in s.readings}
        ref = next((r.reference for r in s.ordered() if r.reference.has_range), None)
        ref_disp = f"{ref.display()}" if ref else "—"
        value_cells = []
        for d in dates:
            r = by_date.get(d)
            if r is None:
                value_cells.append("<td class='num muted'>—</td>")
            elif r.out_of_range:
                value_cells.append(
                    f"<td class='num flagged'>{_esc(r.value_str())}<sup>‡</sup></td>")
            else:
                value_cells.append(f"<td class='num'>{_esc(r.value_str())}</td>")
        rows.append(
            f"<tr><td>{_esc(s.display_name)}</td>"
            f"<td class='muted'>{_esc(s.unit)}</td>"
            + "".join(value_cells)
            + f"<td class='muted'>{_esc(ref_disp)}</td></tr>"
        )
    return f"""
<section class="page-break">
  <h2>Master Data Table</h2>
  <p class='muted small'>Every value below is transcribed from your source lab PDFs.
     The reference range column is each lab's own printed range.</p>
  <hr class='rule-thin'/>
  <table class="data">
    <thead><tr>
      <th>Biomarker</th><th>Unit</th>{date_headers}<th>Lab reference range</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <p class='tiny muted' style='margin-top:8pt;'>
     <span class='flagged'>‡</span> = value falls outside the lab's own printed
     reference range for that draw. This mark is a factual comparison against the
     printed range only.</p>
</section>
"""


def _closing_html(ctx: ReportContext) -> str:
    return f"""
<section class="page-break closing">
  <div class="brandbar">
    <span class="wordmark small-mark">VITALIS&nbsp;FORGE</span>
  </div>
  <hr class="rule"/>
  <h1 style="font-size:24pt;">Bring this to<br/>your physician.</h1>
  <div class="panel" style="margin-top:16pt;">
    <p style="font-size:11pt; line-height:1.65;">{_esc(CLOSING_TEXT)}</p>
  </div>
  <div class="disclaimer-box" style="margin-top:20pt;">
    <div class="disclaimer-h">DISCLAIMER</div>
    <p>{_esc(COVER_DISCLAIMER)}</p>
  </div>
  <div class="signoff">
    <div class="meta-l">PREPARED BY</div>
    <div class="meta-v">{BRAND_NAME} — {PRODUCT_NAME}</div>
    <div class="muted tiny" style="margin-top:4pt;">
       Generated {ctx.generated_on.strftime('%B %-d, %Y')}</div>
  </div>
</section>
"""


def _report_css() -> str:
    return f"""
{theme.base_css()}
{_page_css()}

.brandbar {{ display: flex; justify-content: space-between; align-items: baseline; }}
.wordmark {{
  font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 16pt;
  letter-spacing: 0.18em; color: {theme.COPPER};
}}
.wordmark.small-mark {{ font-size: 13pt; }}
.brandtag {{
  font-family: 'Oswald', sans-serif; font-weight: 600; font-size: 8pt;
  letter-spacing: 0.22em; color: {theme.MUTED};
}}

.cover-title {{ margin-top: 26pt; }}
.kicker {{
  font-family: 'Oswald', sans-serif; font-weight: 600; font-size: 9.5pt;
  letter-spacing: 0.24em; color: {theme.GOLD}; margin-bottom: 6pt;
}}
.cover-title h1 {{ font-size: 46pt; line-height: 0.98; }}
.cover-sub {{ font-size: 12pt; color: {theme.OFFWHITE}; margin-top: 10pt; }}

.stat {{ border-left: 2.5pt solid {theme.COPPER}; padding-left: 9pt; }}
.stat-n {{ font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 26pt;
          color: {theme.OFFWHITE}; line-height: 1; }}
.stat-l {{ font-size: 8pt; color: {theme.MUTED}; text-transform: uppercase;
          letter-spacing: 0.08em; margin-top: 3pt; }}

.meta-l {{ font-family: 'Oswald', sans-serif; font-weight: 600; font-size: 7.5pt;
          letter-spacing: 0.12em; color: {theme.MUTED}; }}
.meta-v {{ font-size: 11pt; color: {theme.OFFWHITE}; margin-top: 2pt; }}
.filelist {{ margin: 4pt 0 0 0; padding-left: 14pt; }}
.filelist li {{ font-size: 9pt; color: {theme.OFFWHITE}; margin: 1pt 0; }}

.disclaimer-box {{
  margin-top: 18pt; background: {theme.CHARCOAL}; border: 0.75pt solid {theme.HAIRLINE};
  border-top: 2.5pt solid {theme.GOLD}; border-radius: 3pt; padding: 12pt 14pt;
}}
.disclaimer-h {{
  font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 9pt;
  letter-spacing: 0.14em; color: {theme.GOLD}; margin-bottom: 5pt;
}}
.disclaimer-box p {{ font-size: 8.6pt; line-height: 1.55; color: {theme.OFFWHITE}; margin: 0; }}

.panel-label {{
  font-family: 'Oswald', sans-serif; font-weight: 700; font-size: 10pt;
  letter-spacing: 0.12em; text-transform: uppercase; color: {theme.GOLD};
  margin: 14pt 0 7pt 0; padding-bottom: 3pt; border-bottom: 0.75pt solid {theme.HAIRLINE};
}}
.chart-card {{
  background: {theme.CHARCOAL}; border: 0.75pt solid {theme.HAIRLINE};
  border-radius: 3pt; padding: 9pt 11pt 7pt 11pt; margin-bottom: 9pt;
}}
.chart-head {{ display: flex; justify-content: space-between; align-items: center;
              margin-bottom: 3pt; }}
.chart-name {{ font-family: 'Oswald', sans-serif; font-weight: 600; font-size: 11.5pt;
              color: {theme.OFFWHITE}; }}
.chart-img {{ width: 100%; height: auto; display: block; }}
.chart-cap {{ font-size: 7.8pt; color: {theme.MUTED}; margin-top: 4pt;
             border-top: 0.5pt solid {theme.HAIRLINE}; padding-top: 4pt; }}
.cap-val {{ color: {theme.OFFWHITE}; font-weight: 600; }}
.cap-date {{ color: {theme.MUTED}; }}

.closing h1 {{ color: {theme.OFFWHITE}; }}
.signoff {{ margin-top: 26pt; border-top: 1.5pt solid {theme.COPPER}; padding-top: 8pt; }}
"""


def build_html(ctx: ReportContext) -> str:
    body = (
        _cover_html(ctx)
        + _chart_block(ctx)
        + _master_table(ctx)
        + _closing_html(ctx)
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<title>{PRODUCT_NAME} — {_esc(ctx.client_name)}</title>
<style>{_report_css()}</style>
</head><body>{body}</body></html>"""


# --- visible-text extraction for the self-check banned-word scan -------------
_STYLE_RE = re.compile(r"<style.*?</style>", re.S | re.I)
_SCRIPT_RE = re.compile(r"<script.*?</script>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def visible_text(html_str: str) -> str:
    """Return the human-visible text of the report HTML (no CSS, no tags, no
    base64 image data) for the banned-word scan."""
    s = _STYLE_RE.sub(" ", html_str)
    s = _SCRIPT_RE.sub(" ", s)
    # drop <img ... base64 ...> entirely so chart bytes aren't scanned
    s = re.sub(r"<img[^>]*>", " ", s)
    s = _TAG_RE.sub(" ", s)
    s = _html.unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def render_pdf(html_str: str, out_path: Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_str).write_pdf(str(out_path))
