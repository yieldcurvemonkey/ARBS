import pytest
from datetime import datetime, date
from SDRUtils.core.lifecycle_v2 import LifecycleEvent, LifecycleSummary


class TestLifecycleEvent:
    def test_newt_event(self):
        evt = LifecycleEvent(
            action_type="NEWT",
            event_type="TRAD",
            amendment_indicator=None,
            event_timestamp=datetime(2026, 3, 9, 14, 33, 25),
            execution_timestamp=datetime(2026, 3, 9, 14, 33, 22),
            dissemination_id="2302018906000000101",
            original_dissemination_id=None,
            file_date=date(2026, 3, 9),
            changed_economics={},
        )
        assert evt.action_type == "NEWT"
        assert evt.original_dissemination_id is None
        assert evt.file_date == date(2026, 3, 9)

    def test_corr_has_no_event_type(self):
        evt = LifecycleEvent(
            action_type="CORR",
            event_type=None,
            amendment_indicator=None,
            event_timestamp=datetime(2026, 3, 10, 4, 0, 55),
            execution_timestamp=datetime(2026, 2, 10, 14, 40, 45),
            dissemination_id="2293644082000000301",
            original_dissemination_id="2027434344000000301",
            file_date=date(2026, 3, 10),
            changed_economics={"Notional amount-Leg 1": "500,000,000"},
        )
        assert evt.event_type is None
        assert evt.original_dissemination_id is not None

    def test_modi_amendment_true(self):
        evt = LifecycleEvent(
            action_type="MODI",
            event_type="TRAD",
            amendment_indicator=True,
            event_timestamp=datetime(2026, 3, 10, 11, 36, 35),
            execution_timestamp=datetime(2026, 3, 9, 20, 13, 23),
            dissemination_id="2317000000000000001",
            original_dissemination_id="2304676889000000101",
            file_date=date(2026, 3, 10),
            changed_economics={"Notional amount-Leg 1": "12,000,000"},
        )
        assert evt.amendment_indicator is True


from SDRUtils.core.lifecycle_v2 import build_summary


class TestBuildSummary:
    def _newt(self, file_date=date(2026, 3, 9), exec_ts=datetime(2026, 3, 9, 14, 0, 0)):
        return LifecycleEvent(
            action_type="NEWT", event_type="TRAD", amendment_indicator=None,
            event_timestamp=datetime(2026, 3, 9, 14, 0, 5), execution_timestamp=exec_ts,
            dissemination_id="100", original_dissemination_id=None,
            file_date=file_date, changed_economics={},
        )

    def test_newt_only(self):
        summary = build_summary([self._newt()])
        assert not summary.was_corrected
        assert not summary.was_economically_modified
        assert not summary.arrived_in_later_file
        assert not summary.is_terminated
        assert summary.original_execution_timestamp == datetime(2026, 3, 9, 14, 0, 0)
        assert summary.correction_lag_seconds == 0

    def test_cross_day_corr_flags_arrived_late(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="CORR", event_type=None, amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 10, 4, 0, 55),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="200", original_dissemination_id="100",
                file_date=date(2026, 3, 10),
                changed_economics={"Fixed rate-Leg 1": 0.045},
            ),
        ]
        summary = build_summary(chain)
        assert summary.was_corrected
        assert summary.arrived_in_later_file
        assert summary.economics_changed
        assert "Fixed rate-Leg 1" in summary.fields_changed
        assert summary.correction_lag_seconds > 0

    def test_modi_amendment_false_is_null_fill(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="MODI", event_type="TRAD", amendment_indicator=False,
                event_timestamp=datetime(2026, 3, 9, 14, 0, 10),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="201", original_dissemination_id="100",
                file_date=date(2026, 3, 9), changed_economics={},
            ),
        ]
        summary = build_summary(chain)
        assert summary.was_null_filled
        assert not summary.was_economically_modified
        assert not summary.arrived_in_later_file

    def test_modi_amendment_true_is_economic(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="MODI", event_type="TRAD", amendment_indicator=True,
                event_timestamp=datetime(2026, 3, 9, 15, 1, 32),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="202", original_dissemination_id="100",
                file_date=date(2026, 3, 9),
                changed_economics={"Notional amount-Leg 1": "12,000,000"},
            ),
        ]
        summary = build_summary(chain)
        assert summary.was_economically_modified
        assert "Notional amount-Leg 1" in summary.fields_changed
        assert summary.economics_changed

    def test_term_marks_terminated(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="TERM", event_type="ETRM", amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9, 15, 15, 56),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="300", original_dissemination_id="100",
                file_date=date(2026, 3, 9), changed_economics={},
            ),
        ]
        summary = build_summary(chain)
        assert summary.is_terminated

    def test_term_then_revi_not_terminated(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="TERM", event_type="ETRM", amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9, 15, 0, 0),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="300", original_dissemination_id="100",
                file_date=date(2026, 3, 9), changed_economics={},
            ),
            LifecycleEvent(
                action_type="REVI", event_type=None, amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9, 21, 4, 14),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="400", original_dissemination_id="100",
                file_date=date(2026, 3, 9), changed_economics={},
            ),
        ]
        summary = build_summary(chain)
        assert not summary.is_terminated
        assert summary.was_revived

    def test_eror_flags(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="EROR", event_type=None, amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9, 16, 0, 0),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="500", original_dissemination_id="100",
                file_date=date(2026, 3, 9), changed_economics={},
            ),
        ]
        summary = build_summary(chain)
        assert summary.was_errored

    def test_partial_unwind_cross_day(self):
        """Real pattern: 25M SOFR 10Y -> 12M -> 7M -> 5 -> TERM across 2 days."""
        chain = [
            LifecycleEvent(
                action_type="NEWT", event_type="TRAD", amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9, 20, 13, 27),
                execution_timestamp=datetime(2026, 3, 9, 20, 13, 23),
                dissemination_id="2304676889000000101", original_dissemination_id=None,
                file_date=date(2026, 3, 9),
                changed_economics={"Notional amount-Leg 1": "25,000,000"},
            ),
            LifecycleEvent(
                action_type="MODI", event_type="TRAD", amendment_indicator=True,
                event_timestamp=datetime(2026, 3, 10, 11, 36, 35),
                execution_timestamp=datetime(2026, 3, 9, 20, 13, 23),
                dissemination_id="X1", original_dissemination_id="2304676889000000101",
                file_date=date(2026, 3, 10),
                changed_economics={"Notional amount-Leg 1": "12,000,000"},
            ),
            LifecycleEvent(
                action_type="MODI", event_type="TRAD", amendment_indicator=True,
                event_timestamp=datetime(2026, 3, 10, 11, 36, 46),
                execution_timestamp=datetime(2026, 3, 9, 20, 13, 23),
                dissemination_id="X2", original_dissemination_id="2304676889000000101",
                file_date=date(2026, 3, 10),
                changed_economics={"Notional amount-Leg 1": "7,000,000"},
            ),
            LifecycleEvent(
                action_type="TERM", event_type="ETRM", amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 10, 11, 36, 51),
                execution_timestamp=datetime(2026, 3, 9, 20, 13, 23),
                dissemination_id="X3", original_dissemination_id="2304676889000000101",
                file_date=date(2026, 3, 10), changed_economics={},
            ),
        ]
        summary = build_summary(chain)
        assert summary.arrived_in_later_file
        assert summary.was_economically_modified
        assert summary.is_terminated
        assert summary.economics_changed
        assert summary.correction_lag_seconds > 50000  # > 14 hours


from SDRUtils.core.lifecycle_v2 import flatten_lifecycle_summary
from SDRUtils.core.lifecycle import ResolvedTrade


class TestFlattenLifecycleSummary:
    def _newt(self, file_date=date(2026, 3, 9)):
        return LifecycleEvent(
            action_type="NEWT", event_type="TRAD", amendment_indicator=None,
            event_timestamp=datetime(2026, 3, 9, 14, 0, 5),
            execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
            dissemination_id="100", original_dissemination_id=None,
            file_date=file_date, changed_economics={},
        )

    def test_newt_only_flat(self):
        summary = build_summary([self._newt()])
        resolved = ResolvedTrade(synthetic_uti="100", status="ACTIVE")
        flat = flatten_lifecycle_summary(summary, resolved)

        assert flat["lc_n_events"] == 1
        assert flat["lc_status"] == "ACTIVE"
        assert flat["lc_is_corrected"] is False
        assert flat["lc_was_amended"] is False
        assert flat["lc_was_null_filled"] is False
        assert flat["lc_was_revived"] is False
        assert flat["lc_has_economics_change"] is False
        assert flat["lc_correction_crossed_day"] is False
        assert flat["lc_correction_lag_seconds"] == 0
        assert flat["lc_fields_changed"] == ""

    def test_corrected_trade_flat(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="CORR", event_type=None, amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 10, 4, 0, 55),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="200", original_dissemination_id="100",
                file_date=date(2026, 3, 10),
                changed_economics={"Fixed rate-Leg 1": 0.045},
            ),
        ]
        summary = build_summary(chain)
        resolved = ResolvedTrade(synthetic_uti="100", status="ACTIVE")
        flat = flatten_lifecycle_summary(summary, resolved)

        assert flat["lc_n_events"] == 2
        assert flat["lc_is_corrected"] is True
        assert flat["lc_has_economics_change"] is True
        assert flat["lc_correction_crossed_day"] is True
        assert flat["lc_correction_lag_seconds"] > 0
        assert "Fixed rate-Leg 1" in flat["lc_fields_changed"]

    def test_terminated_trade_flat(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="TERM", event_type="ETRM", amendment_indicator=None,
                event_timestamp=datetime(2026, 3, 9, 15, 15, 56),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="300", original_dissemination_id="100",
                file_date=date(2026, 3, 9), changed_economics={},
            ),
        ]
        summary = build_summary(chain)
        resolved = ResolvedTrade(synthetic_uti="100", status="TERMINATED")
        flat = flatten_lifecycle_summary(summary, resolved)

        assert flat["lc_status"] == "TERMINATED"
        assert flat["lc_n_events"] == 2

    def test_multiple_fields_changed(self):
        chain = [
            self._newt(),
            LifecycleEvent(
                action_type="MODI", event_type="TRAD", amendment_indicator=True,
                event_timestamp=datetime(2026, 3, 9, 15, 0, 0),
                execution_timestamp=datetime(2026, 3, 9, 14, 0, 0),
                dissemination_id="201", original_dissemination_id="100",
                file_date=date(2026, 3, 9),
                changed_economics={
                    "Notional amount-Leg 1": "12,000,000",
                    "Fixed rate-Leg 1": 0.045,
                },
            ),
        ]
        summary = build_summary(chain)
        resolved = ResolvedTrade(synthetic_uti="100", status="ACTIVE")
        flat = flatten_lifecycle_summary(summary, resolved)

        assert flat["lc_was_amended"] is True
        fields = flat["lc_fields_changed"].split(",")
        assert len(fields) == 2
        assert "Notional amount-Leg 1" in fields
        assert "Fixed rate-Leg 1" in fields
