"""Re-vendor the Vitalis Forge report fonts.

Downloads the official Google Fonts variable TTFs for Oswald and Inter, instances
the specific static weights the report uses, and writes them to
src/biomarker_timeline/assets/fonts/. These instanced TTFs are committed so the
tool needs no network at runtime; you only need to run this if you want to
refresh or change the weights.

Run:  python tools/build_fonts.py
"""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "biomarker_timeline" / "assets" / "fonts"

JOBS = [
    ("https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
     [("Oswald-SemiBold.ttf", {"wght": 600}),
      ("Oswald-Bold.ttf", {"wght": 700})]),
    ("https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
     [("Inter-Regular.ttf", {"wght": 400, "opsz": 18}),
      ("Inter-SemiBold.ttf", {"wght": 600, "opsz": 18})]),
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for url, outs in JOBS:
        print(f"downloading {url}")
        raw = urllib.request.urlopen(url, timeout=120).read()
        for name, axes in outs:
            f = TTFont(io.BytesIO(raw))
            instantiateVariableFont(f, axes, inplace=True)
            out = OUT_DIR / name
            f.save(str(out))
            print(f"  wrote {out.relative_to(OUT_DIR.parent.parent.parent.parent)} "
                  f"({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
