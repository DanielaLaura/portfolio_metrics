with src as (

    select * from {{ ref('src_extractions') }}

)

select
    canonical_company,
    array_to_string(
        list(distinct reported_company)
            filter (where reported_company != canonical_company),
        '; '
    ) as former_names,
    max(case when currency != 'unknown' then currency end) as reporting_currency,
    count(distinct source_file) as n_source_documents,
    min(period_sort) as first_period_sort,
    max(period_sort) as last_period_sort
from src
group by canonical_company
