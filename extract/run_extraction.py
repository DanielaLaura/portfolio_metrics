"""Orchestrator: run both extraction layers on every PDF and reconcile.

For each canonical metric the LLM returns, we check its verbatim value against
the deterministic label/value pairs from Layer 1. A match means the number
provably exists in the document — the LLM chose it, but did not invent it.
Mismatches are flagged, never dropped: the review CSV is the contract with
the human reviewer.

Outputs (dbt seeds):
  dbt/seeds/raw_extractions.csv  — one row per (source_file, company, period, metric)
  dbt/seeds/document_notes.csv   — entity/definition notes per document
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

from llm_extract import extract_document, get_client
from parse_tables import extract_text, parse_pdf

REPO_ROOT = Path(__file__).resolve().parent.parent
PDF_DIR = REPO_ROOT / "data" / "pdfs"
SEED_DIR = REPO_ROOT / "dbt" / "seeds"

EXTRACTION_COLUMNS = [
    "source_file",
    "company_name",
    "period",
    "currency",
    "canonical_metric",
    "reported_label",
    "value_raw",
    "layer1_verified",
    "notes",
]

NOTES_COLUMNS = ["source_file", "note_type", "note"]


def normalize_value(v: str) -> str:
    """Loose comparison key: '43 bps' == '43bps', '$8.4M' stays distinct from '8.4M'."""
    return v.replace(" ", "").strip()


def reconcile(llm_result: dict, layer1_pairs: list, source_file: str) -> list[dict]:
    layer1_values = {normalize_value(p.value_raw) for p in layer1_pairs}
    rows = []
    for company in llm_result["companies"]:
        for metric in company["metrics"]:
            rows.append(
                {
                    "source_file": source_file,
                    "company_name": company["company_name"],
                    "period": company["period"],
                    "currency": company["currency"],
                    "canonical_metric": metric["canonical_metric"],
                    "reported_label": metric["reported_label"],
                    "value_raw": metric["value_raw"],
                    "layer1_verified": normalize_value(metric["value_raw"]) in layer1_values,
                    "notes": metric.get("notes") or "",
                }
            )
    return rows


def main() -> None:
    client = get_client()
    SEED_DIR.mkdir(parents=True, exist_ok=True)

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
        verified = sum(r["layer1_verified"] for r in rows)
        print(f"{len(rows)} metrics, {verified} verified against Layer 1")
        time.sleep(0.5)  # gentle on rate limits

    with open(SEED_DIR / "raw_extractions.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXTRACTION_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    with open(SEED_DIR / "document_notes.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NOTES_COLUMNS)
        writer.writeheader()
        writer.writerows(all_notes)

    unverified = [r for r in all_rows if not r["layer1_verified"]]
    print(f"\nWrote {len(all_rows)} metric rows -> {SEED_DIR / 'raw_extractions.csv'}")
    print(f"Wrote {len(all_notes)} document notes -> {SEED_DIR / 'document_notes.csv'}")
    if unverified:
        print(f"\n{len(unverified)} rows NOT verified against Layer 1 (review these):")
        for r in unverified:
            print(f"  {r['source_file']}: {r['canonical_metric']} = {r['value_raw']!r} ({r['notes']})")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
