"""Execution-vs-Event timestamp integration — Phase 2 tests.

Covers lifecycle_v2 surfacing the original-execution anchor (Task 2.1), the
best-effort alpha-join resolver (Task 2.2), and the trade_tape enrichment
that materializes both timestamps + report_lag/alpha_lag + the real anchor
with the invariant flag (Task 2.3).
"""

from datetime import date

import pandas as pd

from SDRUtils.core.lifecycle_v2 import (
    LifecycleEvent,
    build_summary,
    flatten_lifecycle_summary,
)
from SDRUtils.analytics.alpha_join import (
    SOURCE_FALLBACK,
    SOURCE_LINEAGE,
    SOURCE_NEWT,
    resolve_original_execution,
)
from SDRUtils.analytics.trade_tape import TradeTape


def _ts(s):
    return pd.Timestamp(s)


class TestLifecycleOriginalExecSurfaced:
    def test_flatten_emits_original_execution_and_latest(self):
        newt = LifecycleEvent(
            action_type="NEWT", event_type="TRAD", amendment_indicator=None,
            event_timestamp=_ts("2026-03-09T14:00:00Z"),
            execution_timestamp=_ts("2026-03-09T14:00:00Z"),
            dissemination_id="A1", original_dissemination_id=None,
            file_date=date(2026, 3, 9),
        )
        modi = LifecycleEvent(
            action_type="MODI", event_type="TRAD", amendment_indicator=True,
            event_timestamp=_ts("2026-03-10T10:00:00Z"),
            execution_timestamp=_ts("2026-03-09T14:00:00Z"),
            dissemination_id="A2", original_dissemination_id="A1",
            file_date=date(2026, 3, 10),
        )
        summary = build_summary([newt, modi])

        class _Resolved:
            status = "ACTIVE"
            inception_state = None
            current_state = None

        flat = flatten_lifecycle_summary(summary, _Resolved())
        assert flat["lc_original_execution_timestamp"] == _ts("2026-03-09T14:00:00Z")
        assert flat["lc_latest_update_timestamp"] == _ts("2026-03-10T10:00:00Z")


class TestAlphaJoin:
    def test_lineage_and_orphan(self):
        df = pd.DataFrame({
            "trade_id": ["A1", "A2", "B1"],
            "original_dissemination_id": [None, "A1", None],
            "event_action": ["NEWT-TRAD", "NEWT-CLRG", "NEWT-CLRG"],
            "execution_timestamp": pd.to_datetime(
                ["2026-03-09T14:00:00Z", "2026-03-11T09:00:00Z", "2026-03-11T09:05:00Z"],
                utc=True,
            ),
            "event_timestamp": pd.to_datetime(
                ["2026-03-09T14:00:00Z", "2026-03-11T09:00:00Z", "2026-03-11T09:05:00Z"],
                utc=True,
            ),
        })
        out = resolve_original_execution(df).set_index("trade_id")

        # A2 links to A1 via Original Dissemination Identifier -> alpha anchor.
        assert out.loc["A2", "original_execution_timestamp"] == _ts("2026-03-09T14:00:00Z")
        assert out.loc["A2", "original_execution_source"] == SOURCE_LINEAGE
        assert out.loc["A2", "alpha_lag_seconds"] > 0

        # B1 is an unlinked orphan -> own execution, newt, zero lag.
        assert out.loc["B1", "original_execution_source"] == SOURCE_NEWT
        assert out.loc["B1", "alpha_lag_seconds"] == 0

    def test_preserves_upstream_fallback(self):
        df = pd.DataFrame({
            "trade_id": ["S1"],
            "original_dissemination_id": [None],
            "event_action": ["NEWT-TRAD"],
            "execution_timestamp": pd.to_datetime(["2026-03-09T15:00:00Z"], utc=True),
            "event_timestamp": pd.to_datetime(["2026-03-09T15:00:00Z"], utc=True),
            "original_execution_source": [SOURCE_FALLBACK],
        })
        out = resolve_original_execution(df)
        assert out.loc[0, "original_execution_source"] == SOURCE_FALLBACK


class TestEnrichExecTimestamps:
    def _df(self):
        return pd.DataFrame({
            "trade_id": ["A1", "A2", "C1", "V1"],
            "event_action": ["NEWT-TRAD", "MODI-TRAD", "NEWT-CLRG", "NEWT-TRAD"],
            "execution_timestamp": pd.to_datetime([
                "2026-03-09T14:00:00Z",  # fresh
                "2026-03-09T14:00:00Z",  # modi reuses original execution
                "2026-03-11T09:00:00Z",  # clearing-accept time (new UTI)
                "2026-03-09T15:00:00Z",  # base for an invariant violation
            ], utc=True),
            "event_timestamp": pd.to_datetime([
                "2026-03-09T14:00:00Z",  # == exec -> lag 0
                "2026-03-10T10:00:00Z",  # +20h report lag
                "2026-03-11T09:00:00Z",  # == exec
                "2026-03-09T14:00:00Z",  # BEFORE exec -> violation
            ], utc=True),
            "lc_original_execution_timestamp": pd.to_datetime([
                "2026-03-09T14:00:00Z",
                "2026-03-09T14:00:00Z",
                "2026-03-09T14:00:00Z",  # earlier than clearing exec -> lineage
                "2026-03-09T15:00:00Z",
            ], utc=True),
        })

    def test_deltas_anchor_and_invariant(self):
        df = self._df()
        out = TradeTape(df)._enrich_exec_timestamps(df.copy()).set_index("trade_id")

        # report_lag_seconds = event - execution, clamped >= 0.
        assert out.loc["A1", "report_lag_seconds"] == 0
        assert out.loc["A2", "report_lag_seconds"] == 20 * 3600
        assert out.loc["C1", "report_lag_seconds"] == 0
        assert out.loc["V1", "report_lag_seconds"] == 0  # clamped from -1h

        # invariant flag: only V1 (event < execution beyond tolerance).
        assert bool(out.loc["V1", "report_lag_invariant_violation"]) is True
        assert bool(out.loc["A2", "report_lag_invariant_violation"]) is False

        # original-execution anchor: C1's lc anchor is strictly earlier than its
        # (clearing) execution -> upgraded to lineage; the rest are their own.
        assert out.loc["C1", "original_execution_timestamp"] == _ts("2026-03-09T14:00:00Z")
        assert out.loc["C1", "original_execution_source"] == SOURCE_LINEAGE
        assert out.loc["C1", "alpha_lag_seconds"] > 0
        assert out.loc["A1", "original_execution_source"] == SOURCE_NEWT
        assert out.loc["A1", "alpha_lag_seconds"] == 0

        # clearing-accept timestamp only on NEWT-CLRG rows.
        assert out.loc["C1", "clearing_accepted_timestamp"] == _ts("2026-03-11T09:00:00Z")
        assert pd.isna(out.loc["A1", "clearing_accepted_timestamp"])
