-- Grain: one row per (source_file, company_name, period, canonical_metric).
-- Types the verbatim value strings from extraction: sign, magnitude, unit.
-- All monetary values normalized to millions; percentages kept as numeric percent.

with source as (

    select * from {{ ref('raw_extractions') }}

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
        layer1_verified,
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
    source_file,
    company_name,
    period,
    currency,
    canonical_metric,
    reported_label,
    value_raw,
    layer1_verified,
    notes,
    unit,
    case when is_negative then -1 else 1 end
        * magnitude
        * case when unit = 'currency_m' then to_millions else 1.0 end
        as value_num,
    -- 'Q2 2025' -> sortable 2025.25
    cast(regexp_extract(period, 'Q([1-4])', 1) as int) as period_quarter,
    cast(regexp_extract(period, '(\d{4})', 1) as int) as period_year,
    cast(regexp_extract(period, '(\d{4})', 1) as int)
        + (cast(regexp_extract(period, 'Q([1-4])', 1) as int) - 1) / 4.0
        as period_sort
from parsed
