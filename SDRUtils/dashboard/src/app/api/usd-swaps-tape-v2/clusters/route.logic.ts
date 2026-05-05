export const CLUSTERS_SQL = `
  SELECT
    cluster_id,
    MIN(execution_timestamp) AS start_ts,
    MAX(execution_timestamp) AS end_ts,
    COUNT(*)::int AS trade_count,
    SUM(risk)::float AS total_risk,
    SUM(ABS(notional))::float AS gross_notional,
    (ARRAY_AGG(DISTINCT tape_label ORDER BY tape_label))[1:5] AS tape_labels,
    (ARRAY_AGG(DISTINCT lifecycle_type ORDER BY lifecycle_type))[1:5] AS lifecycle_types
  FROM arbs_usd_swap_tape_legs_v1
  WHERE as_of_date = $1::date
    AND cluster_id IS NOT NULL
  GROUP BY cluster_id
  ORDER BY MIN(execution_timestamp)
`
