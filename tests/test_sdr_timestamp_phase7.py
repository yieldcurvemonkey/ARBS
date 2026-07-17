"""Execution-vs-Event timestamp integration — Phase 7 (monitoring)."""


def test_monitoring_view_has_lag_and_coverage_metrics():
    from SDRUtils._swappulse_scripts._tape_monitoring_v2 import MONITORING_SQL_V2 as sql
    from SDRUtils.config import LATE_REPORT_THRESHOLD_SECONDS

    for col in (
        "median_report_lag_seconds",
        "p95_report_lag_seconds",
        "max_report_lag_seconds",
        "late_report_rows",
        "report_lag_invariant_violations",
        "rows_missing_event_ts",
        "n_alpha_lineage",
        "n_alpha_fallback",
        "n_alpha_newt",
    ):
        assert col in sql, col
    # Threshold is interpolated from config (single source of truth).
    assert f"> {LATE_REPORT_THRESHOLD_SECONDS}" in sql
