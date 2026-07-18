-- Grain: one row per (canonical_company, period, canonical_metric).
-- The tidy long table for analysis. Where a metric appears in both a standalone
-- report and the portfolio snapshot, the standalone value wins and the snapshot
-- becomes a cross-source check (cross_source_agrees).

with resolved as (

    select * from {{ ref('int_metrics_resolved') }}

),

ranked as (

    select
        *,
        row_number() over (
            partition by canonical_company, period, canonical_metric
            order by case source_type when 'standalone' then 1 else 2 end
        ) as source_rank,
        count(*) over (
            partition by canonical_company, period, canonical_metric
        ) as n_sources,
        count(distinct value_num) over (
            partition by canonical_company, period, canonical_metric
        ) as n_distinct_values
    from resolved

)

select
    canonical_company,
    period,
    period_year,
    period_quarter,
    period_sort,
    canonical_metric,
    currency,
    value_num,
    unit,
    value_raw,
    reported_label,
    source_file,
    source_type,
    layer1_verified,
    n_sources,
    (n_sources > 1) as has_cross_source_check,
    (n_distinct_values = 1) as cross_source_agrees,
    notes,
    canonical_company || '|' || period || '|' || canonical_metric as metric_key
from ranked
where source_rank = 1
