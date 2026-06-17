"""Command-line entry point.

Usage:
    python -m biomarker_timeline                 # input/ -> output/biomarker_timeline.pdf
    python -m biomarker_timeline input/ -o output/report.pdf --name "Jane Doe"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="biomarker_timeline",
        description="Biomarker Timeline by Vitalis Forge — organize and visualize a "
                    "client's own lab values over time. This tool transcribes and "
                    "charts data only; it does not interpret, diagnose, or advise.",
    )
    parser.add_argument("input_dir", nargs="?", default="input",
                        help="folder containing the client's lab PDFs (default: input/)")
    parser.add_argument("-o", "--output", default="output/biomarker_timeline.pdf",
                        help="output PDF path (default: output/biomarker_timeline.pdf)")
    parser.add_argument("--name", default=None,
                        help="client name for the cover page (otherwise auto-detected)")
    parser.add_argument("-q", "--quiet", action="store_true", help="reduce console output")
    args = parser.parse_args(argv)

    result = run_pipeline(
        input_dir=Path(args.input_dir),
        output_path=Path(args.output),
        client_name=args.name,
        verbose=not args.quiet,
    )
    return 0 if result.passed else 2


if __name__ == "__main__":
    sys.exit(main())
