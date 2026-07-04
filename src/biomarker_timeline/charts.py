"""Trend charts: one per biomarker, value over time with the lab's reference
band shaded. Rendered with matplotlib to a base64 PNG and inlined into the
report HTML (reliable in WeasyPrint).

A chart only plots numbers and the lab's own printed range. It draws no
conclusions, adds no annotations of meaning, and labels nothing as good or bad.
"""

from __future__ import annotations

import base64
import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from . import theme  # noqa: E402
from .models import MarkerSeries  # noqa: E402

# Register the vendored Vitalis Forge fonts with matplotlib so chart text
# matches the report typography.
for _family, _weight in [("Oswald", 600), ("Oswald", 700), ("Inter", 400), ("Inter", 600)]:
    try:
        fm.fontManager.addfont(str(theme.font_path(_family, _weight)))
    except Exception:
        pass

_OSWALD = fm.FontProperties(family="Oswald", weight=600)
_INTER = fm.FontProperties(family="Inter", weight=400)
_INTER_SB = fm.FontProperties(family="Inter", weight=600)


def chart_png_b64(series: MarkerSeries, width_in: float = 6.6, height_in: float = 2.35) -> str:
    """Render one marker's trend chart and return base64-encoded PNG bytes."""
    readings = series.numeric_ordered()
    dates = [r.draw_date for r in readings]
    values = [r.value for r in readings]

    fig, ax = plt.subplots(figsize=(width_in, height_in), dpi=200)
    fig.patch.set_facecolor(theme.OBSIDIAN)
    ax.set_facecolor(theme.CHARCOAL)

    # --- reference band (the lab's own printed range) ---
    ref = next((r.reference for r in readings if r.reference.has_range), None)
    band_label = None
    if ref is not None and ref.has_range:
        lo = ref.low if ref.low is not None else min(values)
        hi = ref.high if ref.high is not None else max(values)
        ax.axhspan(lo, hi, color=theme.COPPER, alpha=0.14, zorder=0)
        if ref.low is not None:
            ax.axhline(ref.low, color=theme.COPPER, lw=0.8, alpha=0.55, zorder=1)
        if ref.high is not None:
            ax.axhline(ref.high, color=theme.COPPER, lw=0.8, alpha=0.55, zorder=1)
        band_label = f"Lab reference range: {ref.display()} {series.unit}".strip()

    # --- the trend line ---
    ax.plot(dates, values, color=theme.GOLD, lw=1.8, zorder=3,
            solid_capstyle="round")

    # --- per-point markers; points outside the printed range get the ember dot ---
    for r in readings:
        outside = r.flagged
        ax.scatter([r.draw_date], [r.value], s=46, zorder=4,
                   color=theme.EMBER if outside else theme.GOLD,
                   edgecolors=theme.OBSIDIAN, linewidths=1.0)
        ax.annotate(r.value_str(), (r.draw_date, r.value),
                    textcoords="offset points", xytext=(0, 8),
                    ha="center", fontproperties=_INTER_SB, fontsize=8,
                    color=theme.EMBER if outside else theme.OFFWHITE)

    # --- axes styling ---
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for spine in ("left", "bottom"):
        ax.spines[spine].set_color(theme.HAIRLINE)

    ax.tick_params(colors=theme.MUTED, labelsize=7.5, length=3)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    for lbl in ax.get_yticklabels():
        lbl.set_fontproperties(_INTER)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.set_xticks(dates)
    for lbl in ax.get_xticklabels():
        lbl.set_fontproperties(_INTER)
        lbl.set_rotation(0)

    ax.grid(axis="y", color=theme.HAIRLINE, lw=0.4, alpha=0.5)
    ax.set_axisbelow(True)

    # headroom so value labels and band don't collide with the frame
    ymin, ymax = ax.get_ylim()
    pad = (ymax - ymin) * 0.18 or 1.0
    ax.set_ylim(ymin - pad * 0.4, ymax + pad)

    if band_label:
        ax.set_title(band_label, fontproperties=_INTER, fontsize=7.6,
                     color=theme.MUTED, loc="left", pad=6)

    fig.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=theme.OBSIDIAN, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")
