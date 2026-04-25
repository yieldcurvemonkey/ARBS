"""Phase 6 monitoring panel: quality-flag time series.

Views over the v2 tape legs table that expose daily rates of each
compliance / data-quality signal introduced by phases 2-5. Alerts fire
when any rate drifts materially from baseline — early warning that the
upstream SDR feed has changed shape.

Run after ``TAPE_SCHEMA_SQL_V2`` — these views depend on v2 leg columns.
"""
from __future__ import annotations


MONITORING_SQL_V2 = """
-- Daily quality-flag rates over the v2 leg table. Alert thresholds
-- live in the Grafana dashboard; this view is the data source.
CREATE OR REPLACE VIEW arbs_usd_swap_tape_quality_daily_v2 AS
SELECT
    l.as_of_date,
    COUNT(*) AS total_rows,
    SUM(CASE WHEN l.state_machine_violation THEN 1 ELSE 0 END) AS state_machine_violations,
    SUM(CASE WHEN l.cap_band_violation THEN 1 ELSE 0 END) AS cap_band_violations,
    SUM(CASE WHEN l.frequency_anomaly THEN 1 ELSE 0 END) AS frequency_anomalies,
    SUM(CASE WHEN l.schedule_truncated THEN 1 ELSE 0 END) AS schedules_truncated,
    SUM(CASE WHEN COALESCE(array_length(l.missing_required_fields, 1), 0) > 0 THEN 1 ELSE 0 END) AS rows_missing_required,
    SUM(CASE WHEN l.d2_missing THEN 1 ELSE 0 END) AS d2_missing_rows,
    -- Matrix distribution so a sudden ADMIN spike (e.g. new compression
    -- convention) is visible day over day.
    SUM(CASE WHEN l.economic_class = 'ECONOMIC_FLOW' THEN 1 ELSE 0 END) AS n_economic_flow,
    SUM(CASE WHEN l.economic_class = 'ECONOMIC_UNWIND' THEN 1 ELSE 0 END) AS n_economic_unwind,
    SUM(CASE WHEN l.economic_class = 'ECONOMIC_AMENDMENT' THEN 1 ELSE 0 END) AS n_economic_amendment,
    SUM(CASE WHEN l.economic_class = 'ADMINISTRATIVE' THEN 1 ELSE 0 END) AS n_administrative,
    SUM(CASE WHEN l.economic_class = 'VALUATION' THEN 1 ELSE 0 END) AS n_valuation,
    SUM(CASE WHEN l.economic_class = 'UNKNOWN' THEN 1 ELSE 0 END) AS n_unknown_class
FROM arbs_usd_swap_tape_legs_v2 l
GROUP BY l.as_of_date
ORDER BY l.as_of_date DESC;
"""


__all__ = ["MONITORING_SQL_V2"]
