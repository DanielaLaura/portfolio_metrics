"""Layer 2: LLM structured extraction with canonical metric mapping.

Each PDF goes through one Claude call. The model maps every company's
idiosyncratic labels, such as "Contracted ARR", "End-of-Period ARR" or
"Annual Recurring Revenue", onto a small canonical schema, detects the
reporting currency, and surfaces footnotes about rebrands and metric
definition changes. Values are returned VERBATIM, because all typing and
unit conversion happens downstream in dbt, so this layer never does
arithmetic.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv

MODEL = "claude-sonnet-4-6"

CANONICAL_METRICS = [
    "recognized_revenue",
    "arr",
    "gross_margin",
    "ebitda",
    "net_dollar_retention",
    "logo_churn",
    "cash_balance",
    "monthly_net_burn",
    "headcount",
]


def _str(desc: str) -> dict:
    return {"type": "string", "description": desc}


def _opt_str(desc: str) -> dict:
    return {"type": ["string", "null"], "description": desc}


def _arr(items: dict) -> dict:
    return {"type": "array", "items": items}


METRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "canonical_metric": {"type": "string", "enum": CANONICAL_METRICS},
        "period": _str("Quarter THIS VALUE belongs to, e.g. 'Q2 2025' — one entry per quarter column"),
        "reported_label": _str("Label VERBATIM from the document"),
        "value_raw": _str("Value VERBATIM, e.g. '$8.4M', '78%', '($0.75M)', '142'. Never convert or compute"),
        "notes": _opt_str("Caveats: definition changed vs prior quarters, prose/footnote source, non-monthly burn, etc."),
    },
    "required": ["canonical_metric", "period", "reported_label", "value_raw"],
}

COMPANY_SCHEMA = {
    "type": "object",
    "properties": {
        "company_name": _str("Company name as stated in the document (not the filename)"),
        "period": _str("The report's primary period, e.g. 'Q2 2025'"),
        "currency": _str("ISO currency code for monetary values (USD, GBP...); 'unknown' if not determinable"),
        "metrics": _arr(METRIC_SCHEMA),
    },
    "required": ["company_name", "period", "currency", "metrics"],
}

EXTRACTION_TOOL = {
    "name": "record_extraction",
    "description": "Record the metrics extracted from a portfolio company report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "companies": _arr(COMPANY_SCHEMA),
            "entity_notes": _opt_str("Any rebrand, rename, or corporate identity change mentioned"),
            "definition_notes": _opt_str("Any footnote on metric renames or definition changes vs prior reporting"),
        },
        "required": ["companies", "entity_notes", "definition_notes"],
    },
}

SYSTEM_PROMPT = f"""You extract metrics from portfolio company reporting PDFs for an investment monitoring team.

Extract ONLY these canonical metrics: {", ".join(CANONICAL_METRICS)}.

Mapping guidance:
- recognized_revenue: quarterly recognized/net revenue for the period ("Recognized Revenue", "Quarterly Revenue", "Total Recognized Revenue", "Net Revenue", "Total Billings"). If several revenue lines exist, pick the TOTAL for the period and note what you chose. If the label implies a different definition than recognized revenue (e.g. billings), extract it and flag in notes.
- arr: end-of-period ARR ("ARR", "Contracted ARR", "Annual Recurring Revenue", "Subscription ARR", "End-of-Period ARR").
- net_dollar_retention: NDR/NRR and local-currency equivalents (e.g. "Net Pound Retention"). Note the variant label.
- logo_churn: logo/customer churn rate.
- monthly_net_burn: net cash burn. If reported on a non-monthly basis (e.g. quarterly), STILL extract it verbatim and state the periodicity in notes. Never convert.
- cash_balance: cash / cash & equivalents / cash & restricted cash (note variants).
- gross_margin, ebitda, headcount: as labelled.

Rules:
- Values VERBATIM. Never compute, convert units, or annualize.
- Metric periods follow the table columns exactly: a single-column table yields ONE entry per metric, for that column's quarter (or the report's own quarter if no column header). A two-column quarter table yields one entry per column. Never emit more entries than the table has quarter columns. Prior-period figures mentioned in prose ("up from 4.4M in Q4 2024") do NOT count — table columns only; prose numbers are rounded narrative.
- A metric found only in prose or a footnote still counts — extract it and note where it came from.
- Skip metrics that are absent. Do not guess.
- Determine currency from context (e.g. "Net Pound Retention" implies GBP; "(USD)" implies USD). Use 'unknown' if unclear.
- Multi-company documents: one entry per company in `companies`.
- Report every rebrand/rename and metric definition change you see in entity_notes / definition_notes."""


def get_client() -> anthropic.Anthropic:
    load_dotenv()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key.")
    return anthropic.Anthropic(api_key=key)


def extract_document(client: anthropic.Anthropic, text: str, source_file: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_extraction"},
        messages=[
            {"role": "user", "content": f"Document filename: {source_file}\n\n---\n\n{text}"}
        ],
    )
    for block in response.content:
        if block.type == "tool_use":
            return block.input
    raise ValueError(f"No tool_use block in response for {source_file}")


if __name__ == "__main__":
    import sys

    from parse_tables import extract_text

    client = get_client()
    pdf = Path(sys.argv[1])
    result = extract_document(client, extract_text(pdf), pdf.name)
    print(json.dumps(result, indent=2))
