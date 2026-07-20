-- Warn when the same metric for the same company and period disagrees
-- between two source documents. A disagreement is not necessarily an
-- extraction bug, since it can be a real reporting inconsistency, and that
-- is exactly why it warrants human review rather than a hard failure.

{{ config(severity='warn') }}

select
    canonical_company,
    period,
    canonical_metric,
    value_raw,
    n_sources
from {{ ref('fct_metrics_performance_snapshot') }}
where has_cross_source_check
  and not cross_source_agrees
