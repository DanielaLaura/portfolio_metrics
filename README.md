# Portfolio Metrics Extraction

A crawl-phase proof of concept that extracts key financial and operating metrics from heterogeneous portfolio company PDF reports and lands them in a queryable, tested warehouse table.

24 sample PDFs in, 9 canonical metrics out, one reviewable table per company and quarter.

## How to run

    make install        # Python deps (Python 3.11+)
    make review         # reviewer path: rebuilds everything from the committed
                        # extraction output, no API key needed. Loads the CSVs
                        # into DuckDB, runs dbt build with tests, and prints
                        # the final review table.

    # Full pipeline (re-runs LLM extraction, needs an Anthropic API key):
    cp .env.example .env      # then add your key
    make pipeline

## Architecture

    PDFs (data/pdfs/)
      │
      ├─ Layer 1  extract/parse_tables.py     deterministic label/value/quarter
      │           harvest: collects every pair that provably exists on the page
      ├─ Layer 2  extract/llm_extract.py      Claude structured extraction: maps
      │           each company's labels onto 9 canonical metrics, verbatim values
      └─ Verify   extract/run_extraction.py   every LLM value is checked against
                  Layer 1: pair / value_only / none verification tiers
      │
      ▼
    data/extracted/*.csv        committed artifacts: diffable, reviewable
      │
      ▼  extract/load_raw.py    staged into DuckDB as raw.* tables
      │
      ▼  dbt (dbt/)
    sources   src_extractions                    typing, units, entity resolution
    staging   stg_metric_observations            observation grain + provenance
    core      fct_metrics_performance_snapshot   periodic snapshot fact
              dim_company · dim_metric           (company × period × metric)
    marts     mart_metric_pivot                  human review table

## Data flow

1. `parse_tables.py` reads the text of every PDF and harvests each label, value and quarter it can find, around 332 pairs in total, without interpreting any of them.
2. `llm_extract.py` sends each PDF to Claude and gets back structured JSON with the canonical metrics, verbatim values, the reporting currency, and any notes about rebrands or metric definition changes.
3. `run_extraction.py` grades every value the LLM returned against the harvest from step 1 and records a verification tier of pair, value_only or none, then writes everything to `data/extracted/*.csv`.
4. `load_raw.py` stages those CSVs into DuckDB as `raw.*` tables.
5. dbt takes it from there: sources handle typing and entity resolution, staging tags each observation with its provenance, core dedups to the snapshot fact and builds the dimensions, and the mart produces the review pivot.

## Worked example: `CarbonTrack_Q2_2025.pdf`, table to warehouse

This is the Key Metrics table as it appears in the PDF, with two quarter columns:

| Metric | Q2 2025 | Q1 2025 |
|---|---|---|
| Contracted ARR | $16.9M | $15.2M |
| Recognized Revenue | $4.1M | $3.8M |
| Gross Margin | 73% | 72% |
| Net Revenue Retention (LTM) | 121% | 118% |
| Logo Churn (LTM) | 3.8% | 4.1% |
| Total Headcount | 78 | 72 |
| Monthly Net Burn | ($0.55M) | ($0.61M) |
| Cash Balance | $13.8M | $14.8M |

**Step 1: text extraction flattens the table.** pypdf returns one line per cell, top to bottom, and the table structure disappears entirely:

```
Metric
Q2 2025
Q1 2025
Contracted ARR
$16.9M
$15.2M
Recognized Revenue
$4.1M
$3.8M
...
```

**Step 2: the parser classifies every line and rebuilds the rows.** Each line gets a kind. `Q2 2025` is a period, `$16.9M` matches the value regex, and everything else counts as text. `itertools.groupby` bundles consecutive lines of the same kind, and three rules replay the table from those bundles:

```
"Metric"                     text, header word  → new table, reset columns
"Q2 2025","Q1 2025"          period run         → periods = [Q2 2025, Q1 2025]
"Contracted ARR"             text               → label candidate
"$16.9M","$15.2M"            value run (2 vals) → zip with periods:
                                 (Contracted ARR, $16.9M, Q2 2025)
                                 (Contracted ARR, $15.2M, Q1 2025)
"Recognized Revenue"         text               → next label … and so on
```

There is one guard: when a row has more values than there are period columns, which happens in tables like the pipeline's `Stage | Deals | ACV`, it cannot be a quarter table, so only the first value is kept and it gets tagged with the report's own quarter. For this file the parser produces 16 pairs, 8 metrics across 2 quarters, all still verbatim strings.

**Step 3: the LLM classifies the same text.** Each PDF goes through one API call where the output schema is locked to the 9 canonical metrics, so the model has to decide which of the labels it sees correspond to which metric and return the values exactly as they appear in the document, one entry per quarter column:

```json
{"company_name": "CarbonTrack Analytics Corp.", "period": "Q2 2025", "currency": "USD",
 "metrics": [
   {"canonical_metric": "arr", "period": "Q2 2025",
    "reported_label": "Contracted ARR", "value_raw": "$16.9M"},
   {"canonical_metric": "arr", "period": "Q1 2025",
    "reported_label": "Contracted ARR", "value_raw": "$15.2M"},
   {"canonical_metric": "net_dollar_retention", "period": "Q2 2025",
    "reported_label": "Net Revenue Retention (LTM)", "value_raw": "121%"}, ...]}
```

This is where the mapping happens: "Contracted ARR" and "Net Revenue Retention (LTM)" both get recognized for what they mean and come back as `arr` and `net_dollar_retention`.

**Step 4: reconciliation grades every LLM value against the parser's pairs.** The check is exact set membership on the normalized triple of label, value and quarter:

```
LLM row:      ("contracted arr", "$16.9M", "Q2 2025")
parser pairs: {("contracted arr", "$16.9M", "Q2 2025"), ...}   → found → verification = pair
```

The graded rows land in `data/extracted/raw_extractions.csv`, still as strings:

```csv
CarbonTrack_Q2_2025.pdf,CarbonTrack Analytics Corp.,Q2 2025,USD,arr,Contracted ARR,$16.9M,pair,
CarbonTrack_Q2_2025.pdf,CarbonTrack Analytics Corp.,Q1 2025,USD,arr,Contracted ARR,$15.2M,pair,
```

**Step 5: load.** `load_raw.py` copies the CSVs into DuckDB as the `raw.raw_extractions` and `raw.document_notes` tables, and this is where Python hands over to SQL.

**Step 6: `src_extractions` types the strings.** Mechanically, this is what happens to `"($0.55M)"`:

```
starts with '('            → is_negative = true
regex digits               → magnitude = 0.55
ends with 'M'              → unit = currency_m, ×1.0 (millions)
value_num = -1 × 0.55 × 1.0 = -0.55
'Q2 2025'                  → period_sort = 2025.25
```

The same model resolves entities by joining `entity_map`. The reported name in this file, `CarbonTrack Analytics Corp.`, has no map entry and passes through unchanged. The portfolio snapshot refers to the same company as just `CarbonTrack`, and for those rows the map translates the short name to `CarbonTrack Analytics Corp.` so that both documents group as one company.

**Step 7: `stg_metric_observations` tags provenance.** The filename tells us this report belongs to Q2 2025, which becomes `doc_period`, and each row's own quarter is compared against it:

```
period Q2 2025 = doc_period → provenance = own_report
period Q1 2025 ≠ doc_period → provenance = prior_column   (history from the comparison column)
(snapshot file rows)        → provenance = snapshot
```

At this point the combination of CarbonTrack, Q2 2025 and `arr` has two observation rows, one from the company's own report and one from the snapshot, both saying `$16.9M`.

**Step 8: the fact dedups to snapshot grain.** Window functions partition by company, period and metric, the precedence own_report over prior_column over snapshot picks the winner, and the losing observation turns into evidence on the surviving row:

```
canonical_company=CarbonTrack Analytics Corp. | period=Q2 2025 | canonical_metric=arr
value_num=16.9 | provenance=own_report | verification=pair
n_sources=2 | cross_source_agrees=true | possible_restatement=false
```

The Q1 row survives as well, with `provenance=prior_column` as its single source. CarbonTrack has no Q1 PDF in the corpus, so that entire quarter exists only because step 2 recovered the comparison column.

**Step 9: the pivot produces the review table.** One row per company and quarter:

```
CarbonTrack Analytics Corp. | Q1 2025 | rev 3.8 | arr 15.2 | gm 72 | ndr 118 | churn 4.1 | cash 14.8 | hc 72
CarbonTrack Analytics Corp. | Q2 2025 | rev 4.1 | arr 16.9 | gm 73 | ndr 121 | churn 3.8 | cash 13.8 | hc 78
```

The output schema of the fact table (`fct_metrics_performance_snapshot`, grain: company × period × metric):

| Column | Type | Meaning |
|---|---|---|
| canonical_company | varchar | entity after human-approved resolution |
| period / period_sort | varchar / double | 'Q2 2025' / 2025.25 (sortable) |
| canonical_metric | varchar | one of the 9 |
| value_num / unit / currency | double / varchar / varchar | typed value; currency_m · pct · count; USD/GBP |
| value_raw / reported_label | varchar | verbatim audit trail |
| provenance | varchar | own_report · prior_column · snapshot |
| verification | varchar | pair · value_only · none |
| n_sources / cross_source_agrees / possible_restatement | int / bool / bool | multi-document evidence |
| source_file / notes | varchar | lineage and extraction caveats |
| metric_key | varchar | primary key (unique-tested) |

## Querying the database directly

```bash
brew install duckdb          # once, if you don't have the CLI

duckdb -readonly dbt/target/portfolio.duckdb
```

```sql
show all tables;
select * from mart_metric_pivot order by canonical_company, period;
select * from fct_metrics_performance_snapshot
 where canonical_company like 'NovaCloud%' and canonical_metric = 'arr'
 order by period_sort;
select * from dim_company;
select * from stg_metric_observations         -- every observation, all sources
 where canonical_company like 'CarbonTrack%' and period = 'Q2 2025';
.quit
```

No DuckDB CLI? The same peek works through dbt:

```bash
cd dbt && dbt show --profiles-dir . --select mart_metric_pivot --limit 40
```

## The 9 canonical metrics

Recognized revenue, ARR, gross margin, EBITDA, net dollar retention, logo churn, cash balance, monthly net burn and headcount. Together they cover growth, unit economics, retention and runway across different strategies. Metrics are stored long, so a metric a company does not report is simply an absent row rather than a guess, and `dim_metric` documents the type and expected unit of each one.

## Key design decisions

1. **The LLM classifies but never invents.** Every value it returns comes back verbatim from the document and is then cross-checked against a deterministic parse of the same page, so a number the parser cannot find gets flagged for review instead of being trusted. The first time a value becomes an actual number is in dbt, where the conversion is written in SQL that is versioned and tested.
2. **The messy-document handling lives upstream so the warehouse stays boring.** Label variants like "Contracted ARR", "End-of-Period ARR" and "Annual Recurring Revenue", currency detection for the one company that reports in GBP, and rebrand detection are all the LLM layer's job. By the time rows land in dbt every company shares one schema, which is also the reason staging is a single model.
3. **Provenance is a first-class column.** The same metric can appear in its own quarter's report, in the next quarter's comparison column, and in the portfolio snapshot. The fact table resolves this with a precedence of own report, then prior-quarter column, then snapshot, and the extra observations become cross-source agreement checks. When a later report disagrees with the original, the row gets flagged as a possible restatement, because for a monitoring team that is a signal worth seeing rather than an error to hide.
4. **The fact builds incrementally, by grain key rather than by period.** Loading is append-only with a batch stamp, and a new document can revise an old quarter, since a Q3 report carries a Q2 comparison column and a late snapshot adds a cross-check. Any key touched by a new batch is rebuilt from all of its observations with delete+insert, so the evidence columns stay correct. A re-extraction that changes already-loaded rows needs `make rebuild`, which does a full refresh from the CSVs.
5. **Humans own the judgment calls.** Entity resolution, such as the FleetLink to Apex Freight rebrand, and the metric dictionary are hand-maintained seeds rather than LLM output. The extraction results themselves are declared as a dbt source, since dbt observes that data but does not own it.

## Edge cases in the sample data (and how they're handled)

- **A mid-year rebrand.** FleetLink became Apex Freight Solutions in April 2025 and the Q2 report declares it in a successor-entity footnote. The mapping lives in the human-approved `entity_map` seed and the company's history is unified under the successor entity.
- **Metrics renamed across quarters.** NovaCloud's revenue line moves from "Total Billings" to "Recognized Revenue" to "Net Revenue" over four quarters, and "NRR" becomes "Net Dollar Retention" along the way. Values are extracted verbatim with definition notes, and the footnoted equivalences are preserved in `document_notes.csv`.
- **A GBP reporter.** PeopleFlow reports "Net Pound Retention", which is how the currency gets detected. It is carried per row and never converted.
- **Two-column quarter tables with restated history.** TalentVault, CarbonTrack, ClearPay and ConstructIQ show current and prior quarter side by side. Both columns are extracted and provenance-tagged, and any disagreement involving a prior-quarter column flags `possible_restatement`.
- **Metrics that migrate into prose.** Some quarters a headcount or margin appears only in commentary, with a footnote saying it was not tabled that period. These still get extracted, come out with verification tier `none`, and are routed to human review. All 6 flagged rows in the current run are of this kind.
- **Label drift between the snapshot and the standalone reports.** The snapshot says "FTE" where the report says "Total Headcount", "Cash" instead of "Cash Balance", and shortens company names. Canonical mapping absorbs the labels and the cross-source agreement checks confirm the values.
- **Quarterly versus monthly burn.** ConstructIQ reports its net burn quarterly where every other company reports monthly. The value is extracted verbatim with a periodicity note and never converted.
- **Sector heterogeneity.** A logistics marketplace, a specialty lender and several SaaS companies report very different metric sets. The long format handles this naturally, since an absent metric is an absent row and never a guess.

## Assumptions

- Filenames follow `Company_Q#_YYYY.pdf` and the file's quarter is the report's primary period.
- Table quarter columns are current-quarter-first, which holds for all sample files.
- Prior-period numbers mentioned in prose, like "up from 4.4M", are rounded narrative and are not extracted. Only table columns count.
- Monetary values are millions of the company's reporting currency, with no FX conversion at this stage. The currency is carried on every row.
- At most one metric definition caveat per row, recorded in the `notes` column. NovaCloud's revenue line, which changed definition twice across quarters, is the motivating example.

## What I'd do next

- **FX normalization**, with a rates table and a USD-normalized column in core.
- **Point-in-time modeling**, keeping restated values as versions (as reported versus latest) instead of picking one by precedence.
- **Layout-aware parsing** with pdfplumber coordinates, for scanned or complex PDFs where the line-pairing heuristic breaks.
- **An extraction eval set**: hand-label a gold subset and score every extraction change against it in CI.
- **A thin BI layer** on `mart_metric_pivot`, which is already dashboard-shaped.
