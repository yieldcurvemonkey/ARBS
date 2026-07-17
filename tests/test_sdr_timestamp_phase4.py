"""Execution-vs-Event timestamp integration — Phase 4 (schema + ingest).

String-level DDL assertions (no DB) + migration markers + the leg-row builder
carrying the new timestamp/delta columns. Package-level rollups and the
end-to-end write are covered by the DB integration path (marked db, deferred).
"""

import pandas as pd


class TestSchemaV2DDL:
    def _sql(self):
        from SDRUtils._swappulse_scripts._tape_schema_v2 import TAPE_SCHEMA_SQL_V2
        return TAPE_SCHEMA_SQL_V2

    def test_leg_columns_added(self):
        sql = self._sql()
        for col in (
            "event_timestamp", "report_lag_seconds", "alpha_lag_seconds",
            "original_execution_source", "event_timestamp_granularity",
            "report_lag_invariant_violation",
        ):
            assert f"ADD COLUMN IF NOT EXISTS {col} " in sql, col

    def test_package_columns_added(self):
        sql = self._sql()
        for col in (
            "event_start", "event_end", "max_report_lag_seconds",
            "median_report_lag_seconds", "late_report",
        ):
            assert f"ADD COLUMN IF NOT EXISTS {col} " in sql, col

    def test_display_view_exposes_package_rollups(self):
        sql = self._sql()
        for col in (
            "p.event_start", "p.event_end", "p.max_report_lag_seconds",
            "p.median_report_lag_seconds", "p.late_report",
        ):
            assert col in sql, col

    def test_event_index_created(self):
        assert "idx_tape_v2_legs_event" in self._sql()


class TestMigrationMarkers:
    def test_markers_present(self):
        from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import _LATEST_MIGRATION_COLS
        assert ("arbs_usd_swap_tape_legs_v2", "event_timestamp") in _LATEST_MIGRATION_COLS
        assert ("arbs_usd_swap_tape_packages_v2", "event_start") in _LATEST_MIGRATION_COLS


class TestBuildLegRows:
    def test_carries_timestamps_and_defaults_granularity(self):
        from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import build_leg_rows
        tape = pd.DataFrame({
            "trade_id": ["A1"],
            "package_id": ["P1"],
            "leg_order": [0],
            "execution_timestamp": pd.to_datetime(["2026-03-09T14:00:00Z"], utc=True),
            "event_timestamp": pd.to_datetime(["2026-03-10T10:00:00Z"], utc=True),
            "report_lag_seconds": [72000.0],
            "alpha_lag_seconds": [0.0],
            "original_execution_source": ["newt"],
            "report_lag_invariant_violation": [False],
        })
        rows = build_leg_rows(tape, as_of_date="2026-03-09")
        assert len(rows) == 1
        r = rows[0]
        assert r["event_timestamp"] is not None
        assert r["report_lag_seconds"] == 72000.0
        assert r["alpha_lag_seconds"] == 0.0
        assert r["original_execution_source"] == "newt"
        # CFTC feed is second-precision -> defaulted when event ts present.
        assert r["event_timestamp_granularity"] == "second"
        assert r["report_lag_invariant_violation"] is False
