-- Grain: one row per (source_file, canonical_company, period, canonical_metric).
-- Resolves reported company names to canonical entities (rebrands, name variants)
-- and classifies each source document as standalone report vs portfolio snapshot.

with staged as (

    select * from {{ ref('stg_extractions') }}

),

entity_map as (

    select * from {{ ref('entity_map') }}

)

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
    staged.layer1_verified,
    staged.notes,
    staged.period_year,
    staged.period_quarter,
    staged.period_sort,
    case
        when staged.source_file ilike 'portfolio_snapshot%' then 'snapshot'
        else 'standalone'
    end as source_type
from staged
left join entity_map
    on staged.company_name = entity_map.reported_name
