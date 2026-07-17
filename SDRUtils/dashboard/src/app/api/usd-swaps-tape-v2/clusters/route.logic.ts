// Migrated off the frozen legs_v1 to legs_v2 (v1 writes were revoked at the
// Phase-4 cutover, so this route was returning stale/empty data for post-cutover
// days). Bucketing unified to the coalesced original-execution anchor to match
// the other aggregation routes (a no-op while original == execution; correct
// once the alpha-join makes them diverge). 2026-07-17 anchor unification.
export const CLUSTERS_SQL = `
  SELECT
    cluster_id,
    MIN(COALESCE(original_execution_timestamp, execution_timestamp)) AS start_ts,
    MAX(COALESCE(original_execution_timestamp, execution_timestamp)) AS end_ts,
    COUNT(*)::int AS trade_count,
    SUM(risk)::float AS total_risk,
    SUM(ABS(notional))::float AS gross_notional,
    (ARRAY_AGG(DISTINCT tape_label ORDER BY tape_label))[1:5] AS tape_labels,
    (ARRAY_AGG(DISTINCT lifecycle_type ORDER BY lifecycle_type))[1:5] AS lifecycle_types
  FROM arbs_usd_swap_tape_legs_v2
  WHERE as_of_date = $1::date
    AND cluster_id IS NOT NULL
  GROUP BY cluster_id
  ORDER BY MIN(COALESCE(original_execution_timestamp, execution_timestamp))
`
