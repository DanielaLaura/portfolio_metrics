-- Grain: one row per (canonical_company, period).
-- Wide human-review table: one column per canonical metric.
-- Monetary values in millions of the company's reporting currency.

with metrics as (

    select * from {{ ref('mart_portfolio_metrics') }}

)

select
    canonical_company,
    period,
    max(currency)                                                            as currency,
    max(case when canonical_metric = 'recognized_revenue'  then value_num end) as recognized_revenue_m,
    max(case when canonical_metric = 'arr'                 then value_num end) as arr_m,
    max(case when canonical_metric = 'gross_margin'        then value_num end) as gross_margin_pct,
    max(case when canonical_metric = 'ebitda'              then value_num end) as ebitda_m,
    max(case when canonical_metric = 'net_dollar_retention' then value_num end) as ndr_pct,
    max(case when canonical_metric = 'logo_churn'          then value_num end) as logo_churn_pct,
    max(case when canonical_metric = 'cash_balance'        then value_num end) as cash_m,
    max(case when canonical_metric = 'monthly_net_burn'    then value_num end) as monthly_net_burn_m,
    max(case when canonical_metric = 'headcount'           then value_num end) as headcount,
    count(*)                                                     as metrics_extracted,
    sum(case when verification = 'none'       then 1 else 0 end) as unverified_count,
    sum(case when verification = 'value_only' then 1 else 0 end) as review_count,
    sum(case when possible_restatement        then 1 else 0 end) as possible_restatements,
    sum(case when has_cross_source_check and not cross_source_agrees then 1 else 0 end)
                                                                 as cross_source_conflicts
from metrics
group by canonical_company, period
order by canonical_company, max(period_sort)
