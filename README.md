# Portfolio Metrics Extraction — Crawl-Phase POC

Extracts key financial and operating metrics from heterogeneous portfolio
company PDF reports into a queryable, tested warehouse table.

24 sample PDFs → 9 canonical metrics → one reviewable table per company-quarter.

## How to run

    make install        # Python deps (Python 3.11+)
    make review         # reviewer path: rebuild everything from committed
                        # extraction output — no API key needed. Loads CSVs
                        # into DuckDB, runs dbt build + tests, prints the
                        # final review table.

    # Full pipeline (re-runs LLM extraction, needs an Anthropic API key):
    cp .env.example .env      # then add your key
    make pipeline

## Architecture

    PDFs (data/pdfs/)
      │
      ├─ Layer 1  extract/parse_tables.py     deterministic label/value/quarter
      │           harvest — collects every pair that provably exists on the page
      ├─ Layer 2  extract/llm_extract.py      Claude structured extraction — maps
      │           each company's labels onto 9 canonical metrics, verbatim values
      └─ Verify   extract/run_extraction.py   every LLM value is checked against
                  Layer 1: pair / value_only / none verification tiers
      │
      ▼
    data/extracted/*.csv        committed artifacts — diffable, reviewable
      │
      ▼  extract/load_raw.py    staged into DuckDB as raw.* tables
      │
      ▼  dbt (dbt/)
    sources   src_extractions                    typing, units, entity resolution
    staging   stg_metric_observations            observation grain + provenance
    core      fct_metrics_performance_snapshot   periodic snapshot fact
              dim_company · dim_metric           (company × period × metric)
    marts     mart_metric_pivot                  human review table

## The 9 canonical metrics

revenue (recognized), ARR, gross margin, EBITDA, net dollar retention,
logo churn, cash balance, monthly net burn, headcount — chosen to cover
growth, unit economics, retention, and runway across strategies. Stored
long (absent metric = absent row, never a guess); `dim_metric` documents
each metric's type and expected unit.

## Key design decisions

1. **The LLM classifies; it never invents.** Extraction values are returned
   verbatim and cross-checked against a deterministic parse of the same
   page. A number the parser can't find is flagged, not trusted. First
   numeric conversion happens in dbt — versioned, tested SQL.
2. **Messy-document handling is upstream; the warehouse is boring.** Label
   variants ("Contracted ARR" / "End-of-Period ARR" / "Annual Recurring
   Revenue"), currency detection (one company reports in GBP), and rebrand
   detection are the LLM layer's job. By the time rows land in dbt, all
   companies share one schema — which is why staging is a single model.
3. **Provenance is first-class.** The same metric can appear in its own
   quarter's report, in the next quarter's comparison column, and in the
   portfolio snapshot. Precedence: own report > prior-quarter column >
   snapshot. Extra observations become cross-source agreement checks; a
   later report disagreeing with the original is flagged as a possible
   restatement — a signal a monitoring team wants, not an error.
4. **Humans own the judgment calls.** Entity resolution (FleetLink →
   Apex Freight rebrand) and the metric dictionary are hand-maintained
   seeds, not LLM output. Extraction output is a dbt *source* — dbt
   observes it, it doesn't own it.

## Assumptions

- Filenames follow `Company_Q#_YYYY.pdf`; the file's quarter is the
  report's primary period.
- Table quarter columns are current-quarter-first (holds for all samples).
- Prior-period numbers in prose ("up from 4.4M") are rounded narrative and
  are not extracted; only table columns count.
- Monetary values are millions of the company's reporting currency; no FX
  conversion at this stage (currency is carried per row).
- One metric definition caveat per row max (`notes` column) — e.g.
  NovaCloud's revenue line changed definition twice across quarters.

## What I'd do next

- **FX normalization** — a rates table + USD-normalized column in core.
- **Point-in-time modeling** — keep restated values as versions
  (as-reported vs latest) instead of precedence-picking one.
- **Layout-aware parsing** (pdfplumber coordinates) for scanned/complex
  PDFs where the line-pairing heuristic breaks.
- **Extraction eval set** — hand-label a gold subset; score extraction
  changes against it in CI.
- **Incremental runs** — only process new PDFs; snapshot dbt models.
- **A thin BI layer** on `mart_metric_pivot` (it's already dashboard-shaped).
