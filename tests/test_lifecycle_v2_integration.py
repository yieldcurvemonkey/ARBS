"""Tests for lifecycle_v2 integration with existing lifecycle pipeline."""

import pandas as pd
import pytest
from datetime import date

from SDRUtils.core.lifecycle import (
    replay_lifecycle_full,
    build_lifecycle_summary_from_resolved,
)


def _make_messages(rows):
    return pd.DataFrame(rows)


class TestBuildLifecycleSummaryFromResolved:
    def test_newt_only_produces_summary(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-001")
        summary = build_lifecycle_summary_from_resolved(resolved)
        assert not summary.was_corrected
        assert not summary.arrived_in_later_file
        assert not summary.is_terminated

    def test_cross_day_corr_detected(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
            {
                "Dissemination Identifier": "200",
                "Original Dissemination Identifier": "100",
                "Action type": "CORR",
                "Event type": None,
                "Amendment indicator": None,
                "Event timestamp": "2026-03-10 04:00:55",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.0455",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-002")

        # With file_dates showing cross-day arrival
        file_dates = {
            "100": date(2026, 3, 9),
            "200": date(2026, 3, 10),
        }
        summary = build_lifecycle_summary_from_resolved(resolved, file_dates=file_dates)
        assert summary.was_corrected
        assert summary.arrived_in_later_file
        assert summary.economics_changed
        assert "Fixed rate-Leg 1" in summary.fields_changed

    def test_amendment_modi_detected(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 20:13:27",
                "Execution Timestamp": "2026-03-09 20:13:23",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
            {
                "Dissemination Identifier": "201",
                "Original Dissemination Identifier": "100",
                "Action type": "MODI",
                "Event type": "TRAD",
                "Amendment indicator": True,
                "Event timestamp": "2026-03-10 11:36:35",
                "Execution Timestamp": "2026-03-09 20:13:23",
                "Notional amount-Leg 1": "12,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-003")
        file_dates = {
            "100": date(2026, 3, 9),
            "201": date(2026, 3, 10),
        }
        summary = build_lifecycle_summary_from_resolved(resolved, file_dates=file_dates)
        assert summary.was_economically_modified
        assert summary.arrived_in_later_file
        assert "Notional amount-Leg 1" in summary.fields_changed

    def test_term_detected(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
            {
                "Dissemination Identifier": "300",
                "Original Dissemination Identifier": "100",
                "Action type": "TERM",
                "Event type": "ETRM",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 15:15:56",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-004")
        summary = build_lifecycle_summary_from_resolved(resolved)
        assert summary.is_terminated

    def test_no_file_dates_defaults_to_event_date(self):
        msgs = _make_messages([
            {
                "Dissemination Identifier": "100",
                "Original Dissemination Identifier": None,
                "Action type": "NEWT",
                "Event type": "TRAD",
                "Amendment indicator": None,
                "Event timestamp": "2026-03-09 14:00:05",
                "Execution Timestamp": "2026-03-09 14:00:00",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": "0.045",
            },
        ])
        resolved = replay_lifecycle_full(msgs, synthetic_uti="UTI-005")
        # Should not crash when no file_dates provided
        summary = build_lifecycle_summary_from_resolved(resolved)
        assert summary.original_execution_timestamp is not None


# --- Lifecycle Pipeline Integration Tests (against real SDR data) ---

from pathlib import Path
from SDRUtils.core.lifecycle import resolve_lifecycle_for_day

# Try worktree path first, fall back to main repo
_CSV_PATH = Path(__file__).resolve().parent.parent / "notebooks" / "sdr" / "sdr_example.csv"
if not _CSV_PATH.exists():
    _CSV_PATH = Path("C:/Users/chris/clee/ARBS/notebooks/sdr/sdr_example.csv")


@pytest.fixture
def sdr_week():
    if not _CSV_PATH.exists():
        pytest.skip("sdr_example.csv not found")
    return pd.read_csv(
        _CSV_PATH,
        low_memory=False,
        dtype={
            "Dissemination Identifier": str,
            "Original Dissemination Identifier": str,
        },
    )


class TestLifecyclePipelineIntegration:
    def test_resolve_produces_output(self, sdr_week):
        """resolve_lifecycle_for_day produces lc_* columns for one day's data."""
        sdr_week["event_date"] = pd.to_datetime(sdr_week["Event timestamp"]).dt.date
        day = sdr_week["event_date"].value_counts().index[0]
        day_df = sdr_week[sdr_week["event_date"] == day].copy()
        day_df["file_date"] = day

        result = resolve_lifecycle_for_day(day_df)
        assert len(result) > 0
        assert "lc_status" in result.columns
        assert "lc_n_events" in result.columns
        assert "lc_is_corrected" in result.columns
        assert "lc_correction_crossed_day" in result.columns

    def test_most_trades_are_active(self, sdr_week):
        """Most NEWT trades on a given day should be ACTIVE."""
        sdr_week["event_date"] = pd.to_datetime(sdr_week["Event timestamp"]).dt.date
        day = sdr_week["event_date"].value_counts().index[0]
        day_df = sdr_week[sdr_week["event_date"] == day].copy()
        day_df["file_date"] = day

        result = resolve_lifecycle_for_day(day_df)
        active_pct = (result["lc_status"] == "ACTIVE").mean()
        assert active_pct > 0.5, f"Expected >50% ACTIVE, got {active_pct:.1%}"

    def test_corrected_trades_exist(self, sdr_week):
        """Full week should contain some corrected trades."""
        sdr_week["event_date"] = pd.to_datetime(sdr_week["Event timestamp"]).dt.date
        sdr_week["file_date"] = sdr_week["event_date"]

        all_results = []
        for day in sdr_week["event_date"].dropna().unique():
            day_df = sdr_week[sdr_week["event_date"] == day].copy()
            result = resolve_lifecycle_for_day(day_df)
            if not result.empty:
                all_results.append(result)

        combined = pd.concat(all_results)
        n_corrected = combined["lc_is_corrected"].sum()
        assert n_corrected > 0, "Expected some corrected trades in full week"

    def test_lc_columns_survive_column_normalization(self, sdr_week):
        """Verify lc_* column names pass through the snake_case normalizer."""
        import re
        sdr_week["event_date"] = pd.to_datetime(sdr_week["Event timestamp"]).dt.date
        day = sdr_week["event_date"].value_counts().index[0]
        day_df = sdr_week[sdr_week["event_date"] == day].copy()
        day_df["file_date"] = day

        result = resolve_lifecycle_for_day(day_df)
        for col in result.columns:
            normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", col.lower()).lower().replace(" ", "_")
            assert normalized == col, f"Column {col!r} would be renamed to {normalized!r}"
