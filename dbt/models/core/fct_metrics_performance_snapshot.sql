-- Periodic snapshot fact. Grain: one row per (canonical_company, period,
-- canonical_metric). Multiple observations of the same metric are deduped
-- by source precedence:
--   1. the quarter's own report
--   2. a prior-quarter column in a later report
--   3. the portfolio snapshot
-- Extra observations survive as cross-source checks; a disagreement
-- involving a prior-quarter column is flagged as a possible restatement.

with observations as (

    select * from {{ ref('stg_metric_observations') }}

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
        ) as has_prior_column_source
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
    canonical_company || '|' || period || '|' || canonical_metric as metric_key
from ranked
where source_rank = 1
