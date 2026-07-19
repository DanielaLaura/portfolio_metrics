-- Warn when an extracted metric's parsed unit differs from the metric
-- dictionary's expected unit — usually an extraction error (e.g. a
-- percentage captured where millions were expected).

{{ config(severity='warn') }}

select
    f.canonical_company,
    f.period,
    f.canonical_metric,
    f.value_raw,
    f.unit,
    d.expected_unit
from {{ ref('fct_metrics_performance_snapshot') }} f
join {{ ref('dim_metric') }} d using (canonical_metric)
where f.unit != d.expected_unit
