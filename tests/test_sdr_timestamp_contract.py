"""Execution-vs-Event timestamp integration — Phase 1 contract tests.

Spec: docs/superpowers/specs/2026-07-17-sdr-execution-vs-event-timestamp-integration-design.md
Covers config slots + tuning constants (Task 1.1), the TradeClassification
model slots + DataFrame flow (Task 1.2), and the USD swap classifier reading
the raw Event timestamp (Task 1.3).
"""

import pandas as pd

from SDRUtils import config
from SDRUtils.config import SDRColumnConfig
from SDRUtils.core.classification import (
    SwapTradeClassification,
    classifications_to_dataframe,
)


class TestConfigSlots:
    def test_raw_and_internal_names(self):
        c = SDRColumnConfig()
        assert c.raw_event_timestamp == "Event timestamp"
        assert c.event_timestamp == "event_timestamp"
        assert c.original_execution_timestamp == "original_execution_timestamp"
        assert c.report_lag_seconds == "report_lag_seconds"
        assert c.alpha_lag_seconds == "alpha_lag_seconds"
        assert c.original_execution_source == "original_execution_source"
        assert c.event_timestamp_granularity == "event_timestamp_granularity"

    def test_tuning_constants(self):
        assert config.LATE_REPORT_THRESHOLD_SECONDS == 900
        assert config.ALPHA_JOIN_COVERAGE_GATE == 0.95


class TestModelSlots:
    def _min_swap(self, **overrides):
        kw = dict(
            event_action="NEWT-TRAD",
            trade_id=1,
            execution_timestamp=pd.Timestamp("2026-03-09T14:00:00Z"),
            effective_date=pd.Timestamp("2026-03-11"),
            expiration_date=pd.Timestamp("2036-03-11"),
            product_type="OIS_SWAP",
            trade_label="spot 10Y",
            notional=25_000_000.0,
            notional_currency="USD",
            is_notional_capped=False,
            tenor_years=10.0,
            tenor_label="10Y",
            is_forward=False,
            forward_start_years=0.0,
            forward_label="spot",
            fixed_rate=0.04,
        )
        kw.update(overrides)
        return SwapTradeClassification(**kw)

    def test_event_timestamp_and_source_flow_to_dataframe(self):
        c = self._min_swap(
            event_timestamp=pd.Timestamp("2026-03-09T14:05:00Z"),
            original_execution_source="newt",
        )
        df = classifications_to_dataframe([c])
        assert "event_timestamp" in df.columns
        assert "original_execution_source" in df.columns
        assert df.loc[0, "event_timestamp"] == pd.Timestamp("2026-03-09T14:05:00Z")
        assert df.loc[0, "original_execution_source"] == "newt"

    def test_optional_delta_slots_exist(self):
        c = self._min_swap()
        # New kw-only slots default to None and do not break construction.
        assert c.report_lag_seconds is None
        assert c.alpha_lag_seconds is None
        assert c.original_execution_timestamp is None


class TestUsdSwapClassifierEventTs:
    def _row(self):
        return pd.Series(
            {
                "Execution Timestamp": "2026-03-09T14:00:00Z",
                "Event timestamp": "2026-03-09T14:05:00Z",
                "Effective Date": "2026-03-11",
                "Expiration Date": "2036-03-11",
                "Action type": "NEWT",
                "Event type": "TRAD",
                "UPI FISN": "Swap Fxd Flt OIS",
                "UPI Underlier Name": "USD-SOFR-OIS Compound",
                "Notional amount-Leg 1": "25,000,000",
                "Fixed rate-Leg 1": 0.04,
                "Notional currency-Leg 1": "USD",
            }
        )

    def test_classifier_reads_event_timestamp(self):
        from SDRUtils.products.usd.usd_swaps import classify_usd_swap_trade

        c = classify_usd_swap_trade(self._row(), trade_id=1, curve=None)
        assert c.execution_timestamp == pd.Timestamp("2026-03-09T14:00:00Z")
        assert c.event_timestamp == pd.Timestamp("2026-03-09T14:05:00Z")
        # De-conflated: the two are distinct instants.
        assert c.event_timestamp != c.execution_timestamp
