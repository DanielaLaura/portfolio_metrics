"""Orchestrator: run both extraction layers on every PDF and reconcile.

For each canonical metric the LLM returns, we check its verbatim value against
the deterministic label/value pairs from Layer 1. A match means the number
provably exists in the document — the LLM chose it, but did not invent it.
Mismatches are flagged, never dropped: the review CSV is the contract with
the human reviewer.

Outputs:
  data/extracted/raw_extractions.csv — one row per (source_file, company, period, metric)
  data/extracted/document_notes.csv  — entity/definition notes per document
Both are then staged into DuckDB as raw.* tables via load_raw.py.
"""

from __future__ import annotations

import csv
import re
import sys
import time
from pathlib import Path

from llm_extract import extract_document, get_client
from load_raw import load as load_raw
from parse_tables import extract_text, parse_pdf

REPO_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = REPO_ROOT / "data" / "pdfs"
OUT_DIR = REPO_ROOT / "data" / "extracted"

EXTRACTION_COLUMNS = [
    "source_file",
    "company_name",
    "period",
    "currency",
    "canonical_metric",
    "reported_label",
    "value_raw",
    "verification",
    "notes",
]

NOTES_COLUMNS = ["source_file", "note_type", "note"]


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def normalize_value(v: str) -> str:
    """Loose comparison key: '43 bps' == '43bps', '$8.4M' stays distinct from '8.4M'."""
    return v.replace(" ", "").strip()


def normalize_label(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def reconcile(llm_result: dict, layer1_pairs: list, source_file: str) -> list[dict]:
    """Grade each LLM metric against the deterministic net.

    pair       — label, value, and quarter all match: fully verified
    value_only — the number exists in that quarter under a different label
                 (e.g. footnote/prose the parser cannot pair): review
    none       — the number is not in the parser's net at all: flag hard
    """
    triples = {
        (normalize_label(p.label_raw), normalize_value(p.value_raw), p.period)
        for p in layer1_pairs
    }
    value_periods = {(normalize_value(p.value_raw), p.period) for p in layer1_pairs}
    rows = []
    for company in llm_result["companies"]:
        for metric in company["metrics"]:
            key3 = (
                normalize_label(metric["reported_label"]),
                normalize_value(metric["value_raw"]),
                metric["period"],
            )
            verification = (
                "pair" if key3 in triples
                else "value_only" if key3[1:] in value_periods
                else "none"
            )
            rows.append(
                {
                    "source_file": source_file,
                    "company_name": company["company_name"],
                    "period": metric["period"],
                    "currency": company["currency"],
                    "canonical_metric": metric["canonical_metric"],
                    "reported_label": metric["reported_label"],
                    "value_raw": metric["value_raw"],
                    "verification": verification,
                    "notes": metric.get("notes") or "",
                }
            )
    return rows


def main() -> None:
    client = get_client()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    all_notes: list[dict] = []
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    for i, pdf in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf.name} ...", end=" ", flush=True)
        text = extract_text(pdf)
        pairs = parse_pdf(pdf)
        result = extract_document(client, text, pdf.name)
        rows = reconcile(result, pairs, pdf.name)
        all_rows.extend(rows)
        for note_type in ("entity_notes", "definition_notes"):
            if result.get(note_type):
                all_notes.append(
                    {"source_file": pdf.name, "note_type": note_type, "note": result[note_type]}
                )
        tiers = {t: sum(1 for r in rows if r["verification"] == t) for t in ("pair", "value_only", "none")}
        print(f"{len(rows)} metrics — pair: {tiers['pair']}, value_only: {tiers['value_only']}, none: {tiers['none']}")
        time.sleep(0.5)  # gentle on rate limits

    write_csv(OUT_DIR / "raw_extractions.csv", all_rows, EXTRACTION_COLUMNS)
    write_csv(OUT_DIR / "document_notes.csv", all_notes, NOTES_COLUMNS)
    print(f"\nWrote {len(all_rows)} metric rows and {len(all_notes)} document notes -> {OUT_DIR}")
    load_raw()

    flagged = [r for r in all_rows if r["verification"] != "pair"]
    if flagged:
        print(f"\n{len(flagged)} rows need review (verification != 'pair'):")
        for r in flagged:
            print(
                f"  [{r['verification']}] {r['source_file']}: [{r['period']}] {r['canonical_metric']}"
                f" = {r['value_raw']!r} label={r['reported_label']!r} ({r['notes']})"
            )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
