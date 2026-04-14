import math
import pytest
from datetime import datetime, date

from SDRUtils.core.lifecycle import ResolvedTrade
from SDRUtils.core.lifecycle_v2 import (
    LifecycleEvent,
    LifecycleSummary,
    flatten_cross_day_summary,
)


class TestFlattenCrossDaySummary:
    """Tests for flatten_cross_day_summary."""

    def _make_resolved(
        self,
        *,
        status: str = "ACTIVE",
        inception_notional: float = 25_000_000,
        current_notional: float = 25_000_000,
    ) -> ResolvedTrade:
        resolved = ResolvedTrade(synthetic_uti="test-uti")
        resolved.status = status
        resolved.inception_state = {"Notional amount-Leg 1": inception_notional}
        resolved.current_state = {"Notional amount-Leg 1": current_notional}
        return resolved

    def _make_summary(
        self,
        *,
        n_events: int = 1,
        was_corrected: bool = False,
        was_amended: bool = False,
        is_terminated: bool = False,
        fields_changed: set | None = None,
        correction_lag: int = 0,
        file_dates: list[date] | None = None,
    ) -> LifecycleSummary:
        chain = []
        fds = file_dates or [date(2026, 3, 9)]
        for i in range(n_events):
            fd = fds[i] if i < len(fds) else fds[-1]
            chain.append(LifecycleEvent(
                action_type="NEWT" if i == 0 else "MODI",
                event_type="TRAD" if i == 0 else None,
                amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9 + i, 14, 0, 0),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id=f"id_{i}",
                original_dissemination_id=f"id_{i-1}" if i > 0 else None,
                file_date=fd,
            ))
        s = LifecycleSummary(chain=chain)
        s.was_corrected = was_corrected
        s.was_economically_modified = was_amended
        s.is_terminated = is_terminated
        s.fields_changed = fields_changed or set()
        s.correction_lag_seconds = correction_lag
        return s

    def test_active_no_change(self):
        summary = self._make_summary(n_events=1, file_dates=[date(2026, 3, 9)])
        resolved = self._make_resolved()
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_n_events"] == 1
        assert flat["xd_status"] == "ACTIVE"
        assert flat["xd_inception_notional"] == 25_000_000
        assert flat["xd_current_notional"] == 25_000_000
        assert flat["xd_notional_pct_remaining"] == 1.0
        assert flat["xd_is_terminated"] is False
        assert flat["xd_has_partial_unwind"] is False
        assert flat["xd_n_days_spanned"] == 1

    def test_terminated(self):
        summary = self._make_summary(
            n_events=5, is_terminated=True,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 10), date(2026, 3, 10), date(2026, 3, 10)],
        )
        resolved = self._make_resolved(status="TERMINATED", current_notional=0)
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_status"] == "TERMINATED"
        assert flat["xd_is_terminated"] is True
        assert flat["xd_notional_pct_remaining"] == 0.0
        assert flat["xd_n_days_spanned"] == 2

    def test_partial_unwind_active(self):
        summary = self._make_summary(
            n_events=3, was_amended=True,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 10)],
            fields_changed={"Notional amount-Leg 1"},
        )
        resolved = self._make_resolved(
            status="ACTIVE", inception_notional=25_000_000, current_notional=12_000_000,
        )
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_status"] == "PARTIAL_UNWIND"
        assert flat["xd_has_partial_unwind"] is True
        assert flat["xd_notional_pct_remaining"] == pytest.approx(0.48)
        assert flat["xd_was_amended"] is True
        assert "Notional amount-Leg 1" in flat["xd_fields_changed"]

    def test_partial_unwind_then_terminated(self):
        summary = self._make_summary(
            n_events=4, is_terminated=True, was_amended=True,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10), date(2026, 3, 10), date(2026, 3, 10)],
        )
        resolved = self._make_resolved(
            status="TERMINATED", inception_notional=25_000_000, current_notional=5_000_000,
        )
        flat = flatten_cross_day_summary(summary, resolved)

        # Terminated overrides partial unwind status
        assert flat["xd_status"] == "TERMINATED"
        assert flat["xd_has_partial_unwind"] is True
        assert flat["xd_is_terminated"] is True

    def test_errored(self):
        summary = self._make_summary(n_events=2)
        resolved = self._make_resolved(status="ERRORED")
        resolved.inception_state = None
        resolved.current_state = None
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_status"] == "ERRORED"
        assert math.isnan(flat["xd_inception_notional"])
        assert math.isnan(flat["xd_current_notional"])
        assert math.isnan(flat["xd_notional_pct_remaining"])

    def test_zero_inception_notional(self):
        summary = self._make_summary(n_events=1)
        resolved = self._make_resolved(inception_notional=0, current_notional=0)
        flat = flatten_cross_day_summary(summary, resolved)

        assert math.isnan(flat["xd_notional_pct_remaining"])

    def test_corrected_with_lag(self):
        summary = self._make_summary(
            n_events=2, was_corrected=True, correction_lag=82800,
            file_dates=[date(2026, 3, 9), date(2026, 3, 10)],
        )
        resolved = self._make_resolved()
        flat = flatten_cross_day_summary(summary, resolved)

        assert flat["xd_was_corrected"] is True
        assert flat["xd_correction_lag_seconds"] == 82800


import pandas as pd
from SDRUtils.core.lifecycle import resolve_lifecycle_cross_day


class TestResolveCrossDayLifecycle:
    """Tests for resolve_lifecycle_cross_day."""

    def _make_raw_df(self, rows: list[dict]) -> pd.DataFrame:
        """Build a raw SDR DataFrame from row dicts."""
        df = pd.DataFrame(rows)
        # Ensure required columns exist
        for col in ["Dissemination Identifier", "Original Dissemination Identifier",
                     "Action type", "Event timestamp", "file_date"]:
            if col not in df.columns:
                df[col] = ""
        return df

    def _newt_row(self, dissem_id: str, ts: str, file_date: date, notional: float = 25_000_000) -> dict:
        return {
            "Dissemination Identifier": dissem_id,
            "Original Dissemination Identifier": "",
            "Action type": "NEWT",
            "Event type": "TRAD",
            "Event timestamp": ts,
            "Execution Timestamp": ts,
            "Amendment indicator": False,
            "file_date": file_date,
            "Notional amount-Leg 1": notional,
        }

    def _modi_row(self, dissem_id: str, orig_id: str, ts: str, file_date: date,
                   notional: float = 25_000_000, amendment: bool = False) -> dict:
        return {
            "Dissemination Identifier": dissem_id,
            "Original Dissemination Identifier": orig_id,
            "Action type": "MODI",
            "Event type": None,
            "Event timestamp": ts,
            "Execution Timestamp": ts,
            "Amendment indicator": amendment,
            "file_date": file_date,
            "Notional amount-Leg 1": notional,
        }

    def _term_row(self, dissem_id: str, orig_id: str, ts: str, file_date: date) -> dict:
        return {
            "Dissemination Identifier": dissem_id,
            "Original Dissemination Identifier": orig_id,
            "Action type": "TERM",
            "Event type": "ETRM",
            "Event timestamp": ts,
            "Execution Timestamp": ts,
            "Amendment indicator": False,
            "file_date": file_date,
            "Notional amount-Leg 1": 0,
        }

    def test_newt_plus_cross_day_term(self):
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._term_row("A2", "A1", "2026-03-10 12:00:00", date(2026, 3, 10)),
        ])
        result = resolve_lifecycle_cross_day(raw_df, {"A1"})

        assert len(result) == 1
        row = result.iloc[0]
        assert row["xd_status"] == "TERMINATED"
        assert bool(row["xd_is_terminated"]) is True
        assert row["xd_n_events"] == 2
        assert row["xd_n_days_spanned"] == 2

    def test_partial_unwind_chain(self):
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9), notional=25_000_000),
            self._modi_row("A2", "A1", "2026-03-10 10:00:00", date(2026, 3, 10),
                           notional=12_000_000, amendment=True),
            self._modi_row("A3", "A2", "2026-03-10 11:00:00", date(2026, 3, 10),
                           notional=7_000_000, amendment=True),
            self._modi_row("A4", "A3", "2026-03-10 12:00:00", date(2026, 3, 10),
                           notional=5_000_000, amendment=True),
            self._term_row("A5", "A4", "2026-03-10 13:00:00", date(2026, 3, 10)),
        ])
        result = resolve_lifecycle_cross_day(raw_df, {"A1"})

        row = result.iloc[0]
        assert row["xd_status"] == "TERMINATED"
        assert bool(row["xd_has_partial_unwind"]) is True
        assert row["xd_inception_notional"] == 25_000_000
        assert row["xd_n_events"] == 5

    def test_skip_intraday_only(self):
        """Groups with all events on same file_date should be skipped when flag is True."""
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._modi_row("A2", "A1", "2026-03-09 15:00:00", date(2026, 3, 9)),
        ])
        result = resolve_lifecycle_cross_day(raw_df, {"A1"}, skip_intraday_only=True)
        assert result.empty

        result2 = resolve_lifecycle_cross_day(raw_df, {"A1"}, skip_intraday_only=False)
        assert len(result2) == 1

    def test_classified_ids_filter(self):
        """Only groups with NEWTs in classified_dissem_ids produce output."""
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._term_row("A2", "A1", "2026-03-10 12:00:00", date(2026, 3, 10)),
            self._newt_row("B1", "2026-03-09 15:00:00", date(2026, 3, 9)),
            self._term_row("B2", "B1", "2026-03-10 13:00:00", date(2026, 3, 10)),
        ])
        # Only A1 is classified
        result = resolve_lifecycle_cross_day(raw_df, {"A1"})
        assert len(result) == 1
        assert result.index[0] == "A1"

    def test_empty_raw_df(self):
        result = resolve_lifecycle_cross_day(pd.DataFrame(), {"A1"})
        assert result.empty

    def test_newt_empty_string_original_dissem(self):
        """NEWT with empty-string Original Dissemination Identifier groups correctly."""
        raw_df = self._make_raw_df([
            self._newt_row("A1", "2026-03-09 14:00:00", date(2026, 3, 9)),
            self._modi_row("A2", "A1", "2026-03-10 10:00:00", date(2026, 3, 10)),
        ])
        # Verify NEWT's Original Dissemination Identifier is empty string
        assert raw_df.iloc[0]["Original Dissemination Identifier"] == ""
        result = resolve_lifecycle_cross_day(raw_df, {"A1"}, skip_intraday_only=False)
        assert len(result) == 1
        assert result.iloc[0]["xd_n_events"] == 2
