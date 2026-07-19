-- Grain: one row per OBSERVATION (source_file, canonical_company, period,
-- canonical_metric). A metric can be observed more than once — in its own
-- quarter's report, in a later report's prior-quarter column, and in the
-- portfolio snapshot. Each observation is tagged with its provenance; the
-- core fact dedups to snapshot grain.
--
-- Staging is a single model on purpose: extraction normalizes company
-- variance upstream, so all companies share one schema. It splits per
-- company the day one needs custom SQL.

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
        -- the report's own quarter, from the filename: 'NovaCloud_Q2_2025.pdf' -> 'Q2 2025'
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
