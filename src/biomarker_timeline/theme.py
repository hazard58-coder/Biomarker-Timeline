"""Vitalis Forge brand theme: palette, embedded fonts, shared CSS tokens.

Per the brand kit, fonts are EMBEDDED as base64 data URIs (path-based
@font-face fails in WeasyPrint's isolated render context). The static TTF
weights are vendored under assets/fonts/ so no network is needed at runtime.
"""

from __future__ import annotations

import base64
import functools
from pathlib import Path

# ---------------------------------------------------------------------------
# Palette (from the Vitalis Forge brand kit)
# ---------------------------------------------------------------------------
OBSIDIAN = "#0E0F12"   # page background
CHARCOAL = "#1B1E24"   # panel / section blocks
COPPER = "#B87333"     # PRIMARY accent: rules, headers, key figures
GOLD = "#C9A227"       # SECONDARY accent: callouts, secondary emphasis
EMBER = "#C8602F"      # warm highlight, sparing — one focal accent per page
OFFWHITE = "#ECEAE4"   # body text
MUTED = "#9AA0A6"      # labels / captions

# Derived tones used for chart fills and subtle separators.
CHARCOAL_SOFT = "#23272E"
HAIRLINE = "#2C313A"
COPPER_SOFT = "#3A2A1B"   # translucent-looking copper band for chart fills

_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
_FONT_FILES = {
    ("Oswald", 600): "Oswald-SemiBold.ttf",
    ("Oswald", 700): "Oswald-Bold.ttf",
    ("Inter", 400): "Inter-Regular.ttf",
    ("Inter", 600): "Inter-SemiBold.ttf",
}


def font_path(family: str, weight: int) -> Path:
    return _FONT_DIR / _FONT_FILES[(family, weight)]


@functools.lru_cache(maxsize=None)
def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def font_face_css() -> str:
    """Build @font-face blocks with base64-embedded TTFs."""
    blocks = []
    for (family, weight), fname in _FONT_FILES.items():
        data = _b64(_FONT_DIR / fname)
        blocks.append(
            "@font-face{"
            f"font-family:'{family}';font-style:normal;font-weight:{weight};"
            f"src:url(data:font/ttf;base64,{data}) format('truetype');"
            "}"
        )
    return "\n".join(blocks)


def base_css() -> str:
    """Shared CSS tokens: fonts, colors, table and typography defaults.

    Layout note (brand kit rule #1): NO CSS grid anywhere — multi-column
    layouts use fixed tables. This stylesheet only defines tokens; the report
    template supplies the table markup.
    """
    return f"""
{font_face_css()}

:root {{
  --obsidian: {OBSIDIAN};
  --charcoal: {CHARCOAL};
  --copper: {COPPER};
  --gold: {GOLD};
  --ember: {EMBER};
  --offwhite: {OFFWHITE};
  --muted: {MUTED};
  --hairline: {HAIRLINE};
}}

* {{ box-sizing: border-box; }}

html, body {{
  background: {OBSIDIAN};
  color: {OFFWHITE};
  font-family: 'Inter', sans-serif;
  font-weight: 400;
  font-size: 10.5pt;
  line-height: 1.5;
  margin: 0;
  padding: 0;
}}

h1, h2, h3, h4 {{
  font-family: 'Oswald', sans-serif;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: {OFFWHITE};
  margin: 0 0 6pt 0;
}}

h1 {{ font-size: 30pt; line-height: 1.08; }}
h2 {{ font-size: 17pt; color: {COPPER}; text-transform: uppercase; letter-spacing: 0.06em; }}
h3 {{ font-size: 12.5pt; font-weight: 600; }}

a {{ color: {GOLD}; text-decoration: none; }}

.muted {{ color: {MUTED}; }}
.copper {{ color: {COPPER}; }}
.gold {{ color: {GOLD}; }}
.ember {{ color: {EMBER}; }}
.small {{ font-size: 8.5pt; }}
.tiny {{ font-size: 7.5pt; }}

.rule {{ border: 0; border-top: 1.5pt solid {COPPER}; margin: 10pt 0; }}
.rule-thin {{ border: 0; border-top: 0.75pt solid {HAIRLINE}; margin: 8pt 0; }}

.panel {{
  background: {CHARCOAL};
  border: 0.75pt solid {HAIRLINE};
  border-left: 3pt solid {COPPER};
  border-radius: 3pt;
  padding: 12pt 14pt;
}}

.tag {{
  display: inline-block;
  font-family: 'Oswald', sans-serif;
  font-weight: 600;
  font-size: 7.5pt;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2pt 7pt;
  border-radius: 2pt;
}}
.tag-inrange {{ color: {OFFWHITE}; background: {CHARCOAL_SOFT}; border: 0.75pt solid {HAIRLINE}; }}
.tag-flag {{ color: {OBSIDIAN}; background: {GOLD}; }}

/* Data tables ---------------------------------------------------------- */
table.data {{
  width: 100%;
  border-collapse: collapse;
  font-size: 8.8pt;
}}
table.data th {{
  font-family: 'Oswald', sans-serif;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 7.8pt;
  color: {COPPER};
  text-align: left;
  padding: 5pt 6pt;
  border-bottom: 1pt solid {COPPER};
}}
table.data td {{
  padding: 4.5pt 6pt;
  border-bottom: 0.5pt solid {HAIRLINE};
  vertical-align: top;
}}
table.data tr.panelhead td {{
  font-family: 'Oswald', sans-serif;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: 8pt;
  color: {GOLD};
  background: {CHARCOAL};
  padding-top: 7pt;
}}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.flagged {{ color: {GOLD}; font-weight: 600; }}
"""
