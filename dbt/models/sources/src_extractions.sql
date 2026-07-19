-- Grain: one row per (source_file, company_name, period, canonical_metric).
-- Types the verbatim extraction values — sign, magnitude, unit; monetary
-- normalized to millions — and resolves reported company names to canonical
-- entities (rebrands, name variants) via the human-reviewed entity map.

with source as (

    select * from {{ source('raw', 'raw_extractions') }}

),

entity_map as (

    select * from {{ ref('entity_map') }}

),

parsed as (

    select
        source_file,
        company_name,
        period,
        currency,
        canonical_metric,
        reported_label,
        value_raw,
        verification,
        notes,

        (value_raw like '(%' or value_raw like '-%') as is_negative,

        cast(
            replace(regexp_extract(value_raw, '([0-9][0-9,]*(\.[0-9]+)?)', 1), ',', '')
            as double
        ) as magnitude,

        case
            when strpos(value_raw, '%') > 0                 then 'pct'
            when regexp_matches(value_raw, 'bps\)?$')       then 'bps'
            when regexp_matches(value_raw, 'x\)?$')         then 'ratio_x'
            when regexp_matches(value_raw, '[MBkK]\)?$')    then 'currency_m'
            else 'count'
        end as unit,

        case
            when regexp_matches(value_raw, 'B\)?$')     then 1000.0
            when regexp_matches(value_raw, 'M\)?$')     then 1.0
            when regexp_matches(value_raw, '[kK]\)?$')  then 0.001
            else 1.0
        end as to_millions

    from source

)

select
    parsed.source_file,
    coalesce(entity_map.canonical_company, parsed.company_name) as canonical_company,
    parsed.company_name as reported_company,
    parsed.period,
    parsed.currency,
    parsed.canonical_metric,
    parsed.reported_label,
    parsed.value_raw,
    parsed.verification,
    parsed.notes,
    parsed.unit,
    case when parsed.is_negative then -1 else 1 end
        * parsed.magnitude
        * case when parsed.unit = 'currency_m' then parsed.to_millions else 1.0 end
        as value_num,
    cast(regexp_extract(parsed.period, 'Q([1-4])', 1) as int) as period_quarter,
    cast(regexp_extract(parsed.period, '(\d{4})', 1) as int) as period_year,
    cast(regexp_extract(parsed.period, '(\d{4})', 1) as int)
        + (cast(regexp_extract(parsed.period, 'Q([1-4])', 1) as int) - 1) / 4.0
        as period_sort
from parsed
left join entity_map
    on parsed.company_name = entity_map.reported_name
