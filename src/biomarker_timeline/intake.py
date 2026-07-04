"""Stage 1 — INTAKE.

Read every PDF in the input folder. Handle multiple labs from multiple dates.
Each PDF becomes a `SourceDocument` carrying its full extracted text and the
per-page text, which later stages parse and re-verify against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber


@dataclass
class SourceDocument:
    path: Path
    pages: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def text(self) -> str:
        return "\n".join(self.pages)

    @property
    def lines(self) -> list[str]:
        out: list[str] = []
        for page in self.pages:
            out.extend(page.splitlines())
        return out


def read_pdf(path: Path) -> SourceDocument:
    pages: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            # layout=True keeps columns roughly aligned, which helps line-based parsing
            txt = page.extract_text(layout=True, x_density=6, y_density=10) or ""
            pages.append(txt)
    return SourceDocument(path=path, pages=pages)


def intake(input_dir: Path) -> list[SourceDocument]:
    """Discover and read all PDFs in `input_dir` (sorted for deterministic runs)."""
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"Input folder does not exist: {input_dir}")
    pdf_paths = sorted(input_dir.glob("*.pdf")) + sorted(input_dir.glob("*.PDF"))
    docs = [read_pdf(p) for p in pdf_paths]
    return docs
