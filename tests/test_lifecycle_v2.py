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


import pandas as pd
from SDRUtils.core.lifecycle import group_by_uti


class TestGroupByUti:
    def test_single_newt(self):
        """A lone NEWT forms its own group."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100"],
            "Original Dissemination Identifier": [None],
            "Action type": ["NEWT"],
        })
        groups = group_by_uti(df)
        assert len(groups) == 1
        assert "100" in groups
        assert len(groups["100"]) == 1

    def test_newt_plus_modi(self):
        """NEWT + MODI pointing to same original form one group."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200"],
            "Original Dissemination Identifier": [None, "100"],
            "Action type": ["NEWT", "MODI"],
        })
        groups = group_by_uti(df)
        assert len(groups) == 1
        root = list(groups.keys())[0]
        assert len(groups[root]) == 2

    def test_newt_plus_corr_plus_term(self):
        """Full chain: NEWT -> CORR -> TERM grouped together."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200", "300"],
            "Original Dissemination Identifier": [None, "100", "100"],
            "Action type": ["NEWT", "CORR", "TERM"],
        })
        groups = group_by_uti(df)
        assert len(groups) == 1
        root = list(groups.keys())[0]
        assert len(groups[root]) == 3

    def test_two_independent_trades(self):
        """Two unrelated NEWTs form two separate groups."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200", "300"],
            "Original Dissemination Identifier": [None, None, "200"],
            "Action type": ["NEWT", "NEWT", "MODI"],
        })
        groups = group_by_uti(df)
        assert len(groups) == 2

    def test_transitive_chain(self):
        """A -> B -> C should all end up in same group via transitivity."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["A", "B", "C"],
            "Original Dissemination Identifier": [None, "A", "B"],
            "Action type": ["NEWT", "MODI", "MODI"],
        })
        groups = group_by_uti(df)
        assert len(groups) == 1

    def test_nan_original_treated_as_self(self):
        """NaN in Original Dissemination Identifier means self-referencing (NEWT)."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200"],
            "Original Dissemination Identifier": [float("nan"), "100"],
            "Action type": ["NEWT", "CORR"],
        })
        groups = group_by_uti(df)
        assert len(groups) == 1

    def test_orphan_modi_forms_singleton(self):
        """MODI pointing to unknown original forms its own singleton group."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "999"],
            "Original Dissemination Identifier": [None, "UNKNOWN_ID"],
            "Action type": ["NEWT", "MODI"],
        })
        groups = group_by_uti(df)
        assert len(groups) == 2  # "100" group + "999"/"UNKNOWN_ID" group


from SDRUtils.core.lifecycle import resolve_lifecycle_for_day


class TestResolveLifecycleForDay:
    def test_single_newt_day(self):
        """Day with one NEWT produces one lifecycle row."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100"],
            "Original Dissemination Identifier": [None],
            "Action type": ["NEWT"],
            "Event type": ["TRAD"],
            "Event timestamp": [pd.Timestamp("2026-03-09 14:00:05")],
            "Execution Timestamp": [pd.Timestamp("2026-03-09 14:00:00")],
            "Amendment indicator": [None],
            "file_date": [date(2026, 3, 9)],
            "Notional amount-Leg 1": [10_000_000],
            "Fixed rate-Leg 1": [0.045],
        })
        result = resolve_lifecycle_for_day(df)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["lc_n_events"] == 1
        assert row["lc_status"] == "ACTIVE"
        assert row["lc_is_corrected"] == False

    def test_newt_plus_modi_same_day(self):
        """NEWT + MODI on same day produces enriched lifecycle row."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200"],
            "Original Dissemination Identifier": [None, "100"],
            "Action type": ["NEWT", "MODI"],
            "Event type": ["TRAD", "TRAD"],
            "Event timestamp": [
                pd.Timestamp("2026-03-09 14:00:05"),
                pd.Timestamp("2026-03-09 14:05:00"),
            ],
            "Execution Timestamp": [
                pd.Timestamp("2026-03-09 14:00:00"),
                pd.Timestamp("2026-03-09 14:00:00"),
            ],
            "Amendment indicator": [None, True],
            "file_date": [date(2026, 3, 9), date(2026, 3, 9)],
            "Notional amount-Leg 1": [10_000_000, 5_000_000],
            "Fixed rate-Leg 1": [0.045, 0.045],
        })
        result = resolve_lifecycle_for_day(df)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["lc_n_events"] == 2
        assert row["lc_was_amended"] == True

    def test_lifecycle_only_chain_excluded(self):
        """MODI/CORR without NEWT on this day produces no output rows."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["200", "300"],
            "Original Dissemination Identifier": ["100", "100"],
            "Action type": ["MODI", "CORR"],
            "Event type": ["TRAD", None],
            "Event timestamp": [
                pd.Timestamp("2026-03-10 10:00:00"),
                pd.Timestamp("2026-03-10 10:05:00"),
            ],
            "Execution Timestamp": [
                pd.Timestamp("2026-03-09 14:00:00"),
                pd.Timestamp("2026-03-09 14:00:00"),
            ],
            "Amendment indicator": [False, None],
            "file_date": [date(2026, 3, 10), date(2026, 3, 10)],
            "Notional amount-Leg 1": [10_000_000, 10_000_000],
            "Fixed rate-Leg 1": [0.045, 0.046],
        })
        result = resolve_lifecycle_for_day(df)
        assert len(result) == 0

    def test_two_trades_same_day(self):
        """Two independent NEWTs produce two lifecycle rows."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200"],
            "Original Dissemination Identifier": [None, None],
            "Action type": ["NEWT", "NEWT"],
            "Event type": ["TRAD", "TRAD"],
            "Event timestamp": [
                pd.Timestamp("2026-03-09 14:00:00"),
                pd.Timestamp("2026-03-09 14:05:00"),
            ],
            "Execution Timestamp": [
                pd.Timestamp("2026-03-09 14:00:00"),
                pd.Timestamp("2026-03-09 14:05:00"),
            ],
            "Amendment indicator": [None, None],
            "file_date": [date(2026, 3, 9), date(2026, 3, 9)],
            "Notional amount-Leg 1": [10_000_000, 20_000_000],
            "Fixed rate-Leg 1": [0.045, 0.050],
        })
        result = resolve_lifecycle_for_day(df)
        assert len(result) == 2

    def test_newt_term_same_day(self):
        """NEWT + TERM on same day shows TERMINATED status."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "300"],
            "Original Dissemination Identifier": [None, "100"],
            "Action type": ["NEWT", "TERM"],
            "Event type": ["TRAD", "ETRM"],
            "Event timestamp": [
                pd.Timestamp("2026-03-09 14:00:05"),
                pd.Timestamp("2026-03-09 15:15:56"),
            ],
            "Execution Timestamp": [
                pd.Timestamp("2026-03-09 14:00:00"),
                pd.Timestamp("2026-03-09 14:00:00"),
            ],
            "Amendment indicator": [None, None],
            "file_date": [date(2026, 3, 9), date(2026, 3, 9)],
            "Notional amount-Leg 1": [10_000_000, 10_000_000],
            "Fixed rate-Leg 1": [0.045, 0.045],
        })
        result = resolve_lifecycle_for_day(df)
        assert len(result) == 1
        assert result.iloc[0]["lc_status"] == "TERMINATED"

    def test_result_indexed_by_newt_dissem_id(self):
        """Result index is the NEWT dissemination ID for merge compatibility."""
        df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200"],
            "Original Dissemination Identifier": [None, "100"],
            "Action type": ["NEWT", "MODI"],
            "Event type": ["TRAD", "TRAD"],
            "Event timestamp": [
                pd.Timestamp("2026-03-09 14:00:05"),
                pd.Timestamp("2026-03-09 14:05:00"),
            ],
            "Execution Timestamp": [
                pd.Timestamp("2026-03-09 14:00:00"),
                pd.Timestamp("2026-03-09 14:00:00"),
            ],
            "Amendment indicator": [None, True],
            "file_date": [date(2026, 3, 9), date(2026, 3, 9)],
            "Notional amount-Leg 1": [10_000_000, 5_000_000],
            "Fixed rate-Leg 1": [0.045, 0.045],
        })
        result = resolve_lifecycle_for_day(df)
        assert result.index.name == "Dissemination Identifier"
        assert "100" in result.index


class TestBuildClassificationLifecycleIntegration:
    """Test that resolve_lifecycle_for_day output merges correctly with classification output."""

    def test_lifecycle_columns_merge_on_dissem_id(self):
        """Simulate the merge that happens in build_classification_dataframe."""
        # Simulated classifications_df (what classify_messages returns after to_dataframe)
        classifications_df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200"],
            "event_action": ["NEWT-TRAD", "NEWT-TRAD"],
            "tenor_label": ["5Y", "10Y"],
        })

        # Simulated raw day_df with lifecycle events
        day_df = pd.DataFrame({
            "Dissemination Identifier": ["100", "200", "300"],
            "Original Dissemination Identifier": [None, None, "100"],
            "Action type": ["NEWT", "NEWT", "MODI"],
            "Event type": ["TRAD", "TRAD", "TRAD"],
            "Event timestamp": [
                pd.Timestamp("2026-03-09 14:00:05"),
                pd.Timestamp("2026-03-09 14:05:00"),
                pd.Timestamp("2026-03-09 14:10:00"),
            ],
            "Execution Timestamp": [
                pd.Timestamp("2026-03-09 14:00:00"),
                pd.Timestamp("2026-03-09 14:05:00"),
                pd.Timestamp("2026-03-09 14:00:00"),
            ],
            "Amendment indicator": [None, None, True],
            "file_date": [date(2026, 3, 9), date(2026, 3, 9), date(2026, 3, 9)],
            "Notional amount-Leg 1": [10_000_000, 20_000_000, 5_000_000],
            "Fixed rate-Leg 1": [0.045, 0.050, 0.045],
        })

        lifecycle_df = resolve_lifecycle_for_day(day_df)

        # Merge as it would happen in build_classification_dataframe
        classifications_df["Dissemination Identifier"] = classifications_df["Dissemination Identifier"].astype("string")
        lifecycle_df.index = lifecycle_df.index.astype("string")

        merged = classifications_df.merge(
            lifecycle_df,
            left_on="Dissemination Identifier",
            right_index=True,
            how="left",
        )

        assert len(merged) == 2  # Same row count as classifications
        assert "lc_status" in merged.columns
        assert "lc_n_events" in merged.columns

        # Trade 100 had a MODI, so n_events=2
        row_100 = merged[merged["Dissemination Identifier"] == "100"].iloc[0]
        assert row_100["lc_n_events"] == 2
        assert row_100["lc_was_amended"] == True

        # Trade 200 had only NEWT, so n_events=1
        row_200 = merged[merged["Dissemination Identifier"] == "200"].iloc[0]
        assert row_200["lc_n_events"] == 1
        assert row_200["lc_was_amended"] == False
