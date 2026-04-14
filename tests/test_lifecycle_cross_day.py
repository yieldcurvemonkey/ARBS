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
