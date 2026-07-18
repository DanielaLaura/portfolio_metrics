-- Warn when the same metric for the same company/period disagrees between
-- the standalone report and the portfolio snapshot. Disagreement is not
-- necessarily an extraction bug — it can be a real reporting inconsistency —
-- which is exactly why it warrants human review rather than a hard failure.

{{ config(severity='warn') }}

select
    canonical_company,
    period,
    canonical_metric,
    value_raw,
    n_sources
from {{ ref('mart_portfolio_metrics') }}
where has_cross_source_check
  and not cross_source_agrees
