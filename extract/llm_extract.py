"""Layer 2: LLM structured extraction with canonical metric mapping.

One Claude call per PDF. The model maps each company's idiosyncratic labels
("Contracted ARR", "End-of-Period ARR", "Annual Recurring Revenue") onto a
small canonical schema, detects currency, and surfaces footnotes about
rebrands and metric definition changes. Values are returned VERBATIM — all
typing and unit conversion happens downstream in dbt, so this layer never
does arithmetic.
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

EXTRACTION_TOOL = {
    "name": "record_extraction",
    "description": "Record the metrics extracted from a portfolio company report.",
    "input_schema": {
        "type": "object",
        "properties": {
            "companies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "company_name": {
                            "type": "string",
                            "description": "Company name as stated in the document (not the filename).",
                        },
                        "period": {
                            "type": "string",
                            "description": "Reporting period, e.g. 'Q2 2025'.",
                        },
                        "currency": {
                            "type": "string",
                            "description": "ISO currency code for monetary values (USD, GBP, EUR...). 'unknown' if not determinable.",
                        },
                        "metrics": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "canonical_metric": {
                                        "type": "string",
                                        "enum": CANONICAL_METRICS,
                                    },
                                    "reported_label": {
                                        "type": "string",
                                        "description": "The label VERBATIM as it appears in the document.",
                                    },
                                    "value_raw": {
                                        "type": "string",
                                        "description": "The value VERBATIM, e.g. '$8.4M', '78%', '($0.75M)', '142'. Never convert or compute.",
                                    },
                                    "notes": {
                                        "type": ["string", "null"],
                                        "description": "Caveats: definition changed vs prior quarters, value found in prose/footnote rather than a table, burn reported quarterly instead of monthly, etc.",
                                    },
                                },
                                "required": ["canonical_metric", "reported_label", "value_raw"],
                            },
                        },
                    },
                    "required": ["company_name", "period", "currency", "metrics"],
                },
            },
            "entity_notes": {
                "type": ["string", "null"],
                "description": "Any rebrand, rename, or corporate identity change mentioned (e.g. 'Company X was formerly Company Y, effective <date>').",
            },
            "definition_notes": {
                "type": ["string", "null"],
                "description": "Any footnote stating a metric was renamed or its definition changed vs prior reporting.",
            },
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
- A metric found only in prose or a footnote still counts — extract it and note where it came from.
- Skip metrics that are absent. Do not guess.
- Determine currency from context (e.g. "Net Pound Retention" implies GBP; "(USD)" implies USD). Use 'unknown' if unclear.
- Multi-company documents: one entry per company in `companies`.
- Report every rebrand/rename and metric definition change you see in entity_notes / definition_notes."""


def get_client() -> anthropic.Anthropic:
    load_dotenv()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY not set — copy .env.example to .env and add your key.")
    return anthropic.Anthropic(api_key=key)


def extract_document(client: anthropic.Anthropic, text: str, source_file: str) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_extraction"},
        messages=[
            {
                "role": "user",
                "content": f"Document filename: {source_file}\n\n---\n\n{text}",
            }
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
