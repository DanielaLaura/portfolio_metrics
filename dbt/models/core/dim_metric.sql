select
    canonical_metric,
    metric_type,
    expected_unit
from {{ ref('metric_dictionary') }}
