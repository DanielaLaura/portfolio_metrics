-- Grain: one row per (source_file, canonical_company, period, canonical_metric).
-- Resolves reported company names to canonical entities (rebrands, name
-- variants) and tags each row's provenance: the report's own quarter, a
-- prior-quarter column in a later report, or the portfolio snapshot.

with staged as (

    select * from {{ ref('stg_extractions') }}

),

entity_map as (

    select * from {{ ref('entity_map') }}

),

resolved as (

    select
        staged.source_file,
        coalesce(entity_map.canonical_company, staged.company_name) as canonical_company,
        staged.company_name as reported_company,
        staged.period,
        staged.currency,
        staged.canonical_metric,
        staged.reported_label,
        staged.value_raw,
        staged.value_num,
        staged.unit,
        staged.verification,
        staged.notes,
        staged.period_year,
        staged.period_quarter,
        staged.period_sort,
        case
            when staged.source_file ilike 'portfolio_snapshot%' then 'snapshot'
            else 'standalone'
        end as source_type,
        -- the report's own quarter, from the filename: 'NovaCloud_Q2_2025.pdf' -> 'Q2 2025'
        replace(regexp_extract(staged.source_file, '(Q[1-4]_20\d\d)', 1), '_', ' ') as doc_period
    from staged
    left join entity_map
        on staged.company_name = entity_map.reported_name

)

select
    *,
    case
        when source_type = 'snapshot' then 'snapshot'
        when period = doc_period      then 'own_report'
        else                               'prior_column'
    end as provenance
from resolved
