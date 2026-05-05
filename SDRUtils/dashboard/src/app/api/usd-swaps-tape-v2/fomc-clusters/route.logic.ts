export const FOMC_CLUSTERS_SQL = `
  SELECT
    l.fomc_meeting_label,
    COUNT(*)::int AS trade_count,
    SUM(l.risk)::float AS net_risk,
    SUM(ABS(l.notional))::float AS gross_notional,
    BOOL_OR(l.is_multi_meeting_cluster) AS has_multi_meeting_flow
  FROM arbs_usd_swap_tape_legs_v1 l
  WHERE l.as_of_date = $1::date
    AND l.is_fomc_dated = TRUE
    AND l.fomc_meeting_label IS NOT NULL
  GROUP BY l.fomc_meeting_label
  ORDER BY l.fomc_meeting_label
`
