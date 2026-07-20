"""Layer 1: deterministic label/value/period extraction from PDF metric tables.

When a PDF is text-extracted its metric tables flatten into period headers,
label lines and value lines, and three rules are enough to recover the
structure:

1. A run of "Q# YYYY" lines defines the table's quarter columns.
2. A run of value lines is one row, and the values pair with the quarter
   columns in order.
3. Any other text line is a candidate label, and a header word such as
   "Metric", "KPI" or "Stage" starts a new table.

Nothing gets interpreted here, there is no canonical mapping and no unit
parsing. The output serves as the ground truth that the LLM results are
reconciled against.
"""

from __future__ import annotations

import re
from collections import namedtuple
from itertools import groupby
from pathlib import Path

import pypdf

# Table values: $8.4M, 6.8M, 78%, 123%, 1,420, 2.4x, +148bps, ($0.75M), $84k, 142
VALUE_RE = re.compile(r"\(?[+\-]?\$?[\d,]+(?:\.\d+)?\s*(?:M|B|k|K|bps|x|%)?\)?")

# A period column header, alone on its line: "Q2 2025"
PERIOD_RE = re.compile(r"Q[1-4] 20\d\d")

# Table header words: they start a new table and are never metric labels.
HEADER_RE = re.compile(
    r"Metric|Item|KPI|Stage|Sector|Platform Metric|Opportunities|"
    r"Total Pipeline|Weighted|Outstanding Balance|Share of Book"
)

FILENAME_RE = re.compile(r"^(?P<company>.+)_(?P<period>Q[1-4]_\d{4})\.pdf$")

RawPair = namedtuple(
    "RawPair", "source_file file_company file_period period label_raw value_raw"
)


def extract_text(pdf_path: Path) -> str:
    reader = pypdf.PdfReader(pdf_path)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def parse_filename(name: str) -> tuple[str | None, str | None]:
    m = FILENAME_RE.match(name)
    if not m:
        return None, None
    company = m.group("company").replace("_", " ")
    period = m.group("period").replace("_", " ")  # Q2_2025 -> Q2 2025
    return (None, period) if company == "Portfolio Snapshot" else (company, period)


def _kind(line: str) -> str:
    if PERIOD_RE.fullmatch(line):
        return "period"
    if VALUE_RE.fullmatch(line):
        return "value"
    return "text"


def parse_pairs(text: str, source_file: str) -> list[RawPair]:
    file_company, file_period = parse_filename(source_file)
    default = file_period or "unknown"
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    pairs: list[RawPair] = []
    periods, label = [default], None
    for kind, group_iter in groupby(lines, key=_kind):
        group = list(group_iter)
        if kind == "period":
            periods = group
        elif kind == "value" and label:
            # More values than quarter columns means this is not a quarter
            # table (e.g. a pipeline Stage | Deals | ACV table): keep only
            # the first value, tagged with the report's own period.
            row = zip(periods, group) if len(group) <= len(periods) \
                else [(default, group[0])]
            pairs += [
                RawPair(source_file, file_company, file_period, per, label, val)
                for per, val in row
            ]
            label = None
        elif kind == "text":
            last = group[-1]
            if HEADER_RE.fullmatch(last):
                periods, label = [default], None
            else:
                label = last if len(last) < 60 else None
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
            print(f"  [{p.period}] {p.label_raw!r:45} -> {p.value_raw!r}")
