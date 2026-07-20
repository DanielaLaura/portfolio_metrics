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
