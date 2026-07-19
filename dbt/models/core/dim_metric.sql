-- Grain: one row per canonical metric (the tracked set of 9).
-- Sourced from the hand-maintained metric dictionary seed.

select
    canonical_metric,
    metric_type,
    expected_unit
from {{ ref('metric_dictionary') }}
