-- Periodic snapshot fact with one row per (canonical_company, period,
-- canonical_metric). When the same metric is observed in several documents,
-- the surviving row is chosen by source precedence:
--   1. the quarter's own report
--   2. a prior-quarter column in a later report
--   3. the portfolio snapshot
-- The extra observations are kept as cross-source checks, and a
-- disagreement that involves a prior-quarter column gets flagged as a
-- possible restatement.
--
-- The build is incremental by grain key, not by period, because a new
-- document can revise an old quarter: a Q3 report carries a Q2 comparison
-- column and a late snapshot adds a cross-check, both of which change the
-- evidence columns on an existing row. Any key touched by a new batch is
-- rebuilt from ALL of its observations via delete+insert, so the window
-- functions always see the complete picture for that key.

{{ config(
    materialized='incremental',
    unique_key='metric_key',
    incremental_strategy='delete+insert'
) }}

with observations as (

    select * from {{ ref('stg_metric_observations') }}

    {% if is_incremental() %}
    where canonical_company || '|' || period || '|' || canonical_metric in (
        select canonical_company || '|' || period || '|' || canonical_metric
        from {{ ref('stg_metric_observations') }}
        where loaded_at > (
            select coalesce(max(max_loaded_at), timestamp '1900-01-01') from {{ this }}
        )
    )
    {% endif %}

),

ranked as (

    select
        *,
        row_number() over (
            partition by canonical_company, period, canonical_metric
            order by case provenance
                when 'own_report'   then 1
                when 'prior_column' then 2
                else 3
            end
        ) as source_rank,
        count(*) over (
            partition by canonical_company, period, canonical_metric
        ) as n_sources,
        count(distinct value_num) over (
            partition by canonical_company, period, canonical_metric
        ) as n_distinct_values,
        max(case when provenance = 'prior_column' then 1 else 0 end) over (
            partition by canonical_company, period, canonical_metric
        ) as has_prior_column_source,
        max(loaded_at) over (
            partition by canonical_company, period, canonical_metric
        ) as max_loaded_at
    from observations

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
    provenance,
    verification,
    n_sources,
    (n_sources > 1) as has_cross_source_check,
    (n_distinct_values = 1) as cross_source_agrees,
    (n_sources > 1 and n_distinct_values > 1 and has_prior_column_source = 1)
        as possible_restatement,
    notes,
    max_loaded_at,
    canonical_company || '|' || period || '|' || canonical_metric as metric_key
from ranked
where source_rank = 1
