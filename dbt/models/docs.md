{% docs raw_extractions %}
Extraction pipeline output, one row per (source_file, company_name, period,
canonical_metric). Values are verbatim strings exactly as they appear in the
PDFs, each graded with a verification tier during reconciliation. Written by
`extract/run_extraction.py` and staged into the warehouse by
`extract/load_raw.py`, which loads append-only and stamps every batch with
`loaded_at`. dbt observes this table but does not own it.
{% enddocs %}

{% docs document_notes %}
Entity and metric-definition notes surfaced by the LLM layer for each
document: rebrand declarations, metric renames, footnoted equivalences.
These notes are the evidence trail behind entity-map decisions.
{% enddocs %}

{% docs src_extractions %}
First typed layer. Grain: one row per (source_file, company_name, period,
canonical_metric).

Turns the verbatim value strings into numbers: sign from parentheses,
magnitude from the digits, unit from the suffix, with monetary values
normalized to millions. Also resolves reported company names to canonical
entities through the human-reviewed `entity_map` seed, where an unmapped
name simply passes through unchanged.
{% enddocs %}

{% docs stg_metric_observations %}
Observation grain: one row per (source_file, canonical_company, period,
canonical_metric). A metric can be observed more than once, in its own
quarter's report, in a later report's prior-quarter comparison column, and
in the portfolio snapshot, and every observation survives here.

Each row is tagged with its provenance. The report's own quarter comes from
the filename, and a row whose period matches it is `own_report`, a row from
an older quarter is `prior_column`, and rows from the portfolio snapshot are
`snapshot`.

Staging is a single model on purpose. Extraction normalizes company variance
upstream, so all companies share one schema, and the model splits per
company the day one of them needs custom SQL.
{% enddocs %}

{% docs fct_metrics_performance_snapshot %}
Periodic snapshot fact and the central table of the project. Grain: one row
per (canonical_company, period, canonical_metric), enforced by a unique test
on `metric_key`.

Collects every observation of a metric from staging, picks the surviving row
by source precedence (the quarter's own report, then a prior-quarter column
in a later report, then the portfolio snapshot), and turns the losing
observations into evidence columns: `n_sources`, `cross_source_agrees`, and
`possible_restatement` when a prior-quarter column disagrees with the
original report.

Builds incrementally by grain key with delete+insert, because a new document
can revise an old quarter. Any key touched by a new load batch is rebuilt
from all of its observations, so the evidence columns always reflect the
complete picture. A re-extraction that changes already-loaded rows requires
`make rebuild` for a full refresh.
{% enddocs %}

{% docs dim_company %}
One row per canonical portfolio company: the canonical name as the key, the
other names the company has reported under in `former_names`, the best known
reporting currency, and the document count. Built after entity resolution,
so FleetLink history appears under Apex Freight Solutions.
{% enddocs %}

{% docs dim_metric %}
One row per canonical metric, from the hand-maintained `metric_dictionary`
seed: the metric's type (financial or operating) and its expected unit,
which powers the unit-consistency warn test against the fact.
{% enddocs %}

{% docs mart_metric_pivot %}
The human review table. Grain: one row per (canonical_company, period), with
one column per canonical metric and quality counters for unverified rows,
rows needing review, possible restatements and cross-source conflicts. This
is the table a reviewer scans and the natural input for a dashboard.
{% enddocs %}

{% docs assert_cross_source_agreement %}
Warns when the same metric for the same company and period disagrees between
two source documents. A disagreement is not necessarily an extraction bug,
since it can be a real reporting inconsistency, and that is exactly why it
warrants human review rather than a hard failure.
{% enddocs %}

{% docs assert_units_match_dictionary %}
Warns when an extracted metric's parsed unit differs from the metric
dictionary's expected unit, which usually means an extraction error, such as
a percentage captured where millions were expected.
{% enddocs %}

{% docs entity_map %}
Human-reviewed mapping from reported company names to canonical entities,
such as the FleetLink to Apex Freight rebrand. Exceptions only: a name that
is absent from the map is already canonical and passes through unchanged.
Merges are never made on name similarity; a document has to declare the
relationship and a human has to approve the line.
{% enddocs %}

{% docs metric_dictionary %}
The canonical metric set, with the type and expected unit of each of the 9
tracked metrics. Hand-maintained, and the reference the unit-consistency
test checks the fact against.
{% enddocs %}
