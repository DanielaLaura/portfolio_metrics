with src as (

    select * from {{ ref('src_extractions') }}

),

tagged as (

    select
        *,
        case
            when source_file ilike 'portfolio_snapshot%' then 'snapshot'
            else 'standalone'
        end as source_type,
        replace(regexp_extract(source_file, '(Q[1-4]_20\d\d)', 1), '_', ' ') as doc_period
    from src

)

select
    *,
    case
        when source_type = 'snapshot' then 'snapshot'
        when period = doc_period      then 'own_report'
        else                               'prior_column'
    end as provenance
from tagged
