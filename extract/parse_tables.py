"""Layer 1: deterministic extraction of label/value pairs from PDF metric tables.

The reporting PDFs render metric tables as alternating label/value lines once
text-extracted. This layer captures every (label, value) pair it can find with
zero interpretation — no canonical mapping, no unit parsing. Its output is the
ground truth that Layer 2 (LLM) results are reconciled against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pypdf

# Matches table values: $8.4M, 6.8M, 78%, 123%, 1,420, 2.4x, +148bps, ($0.75M), $84k, 142
VALUE_RE = re.compile(
    r"^\(?[+\-]?\$?[\d,]+(?:\.\d+)?\s*(?:M|B|k|K|bps|x|%)?\)?$"
)

# Lines that are table headers or period labels, not metric labels
NON_LABEL_RE = re.compile(
    r"^(Metric|Item|Stage|Sector|Q[1-4] \d{4}|Opportunities|Total Pipeline|"
    r"Weighted|Outstanding Balance|Share of Book)$"
)

FILENAME_RE = re.compile(r"^(?P<company>.+)_(?P<period>Q[1-4]_\d{4})\.pdf$")


@dataclass
class RawPair:
    source_file: str
    file_company: str | None  # from filename; None for multi-company docs
    file_period: str | None
    label_raw: str
    value_raw: str


def extract_text(pdf_path: Path) -> str:
    reader = pypdf.PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_filename(name: str) -> tuple[str | None, str | None]:
    m = FILENAME_RE.match(name)
    if not m:
        return None, None
    company = m.group("company").replace("_", " ")
    period = m.group("period").replace("_", " ")  # Q2_2025 -> Q2 2025
    if company == "Portfolio Snapshot":
        return None, period
    return company, period


def parse_pairs(text: str, source_file: str) -> list[RawPair]:
    file_company, file_period = parse_filename(source_file)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    pairs: list[RawPair] = []
    prev: str | None = None
    for line in lines:
        is_value = bool(VALUE_RE.match(line))
        if (
            is_value
            and prev is not None
            and not VALUE_RE.match(prev)
            and not NON_LABEL_RE.match(prev)
            and len(prev) < 60  # narrative sentences are not labels
        ):
            pairs.append(RawPair(source_file, file_company, file_period, prev, line))
        prev = line
    return pairs


def parse_pdf(pdf_path: Path) -> list[RawPair]:
    return parse_pairs(extract_text(pdf_path), pdf_path.name)


if __name__ == "__main__":
    import sys

    pdf_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/pdfs")
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        pairs = parse_pdf(pdf)
        print(f"\n=== {pdf.name} ({len(pairs)} pairs) ===")
        for p in pairs:
            print(f"  {p.label_raw!r:50} -> {p.value_raw!r}")
