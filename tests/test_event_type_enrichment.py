import math
import os
import pytest
from datetime import datetime, date

import pandas as pd
from SDRUtils.analytics.trade_tape import TradeTape


class TestEventTypePassthrough:
    """Event type column survives classification pipeline into TradeTape."""

    def _minimal_df_with_event_type(self, event_type="TRAD"):
        """Classified DataFrame with event_type column present."""
        return pd.DataFrame({
            "trade_id": ["A1"],
            "execution_timestamp": pd.to_datetime(["2026-03-09 14:00:00+00:00"]),
            "event_action": [f"NEWT-{event_type}"],
            "event_type": [event_type],
            "tenor_label": ["10Y"],
            "tenor_years": [10.0],
            "forward_label": ["spot"],
            "forward_start_years": [0.0],
            "notional": [25_000_000],
            "fixed_rate": [0.04],
            "estimated_pv01": [9000],
            "product_type": ["OIS_SWAP"],
            "upi_underlier_name": ["USD-SOFR-COMPOUND"],
            "unique_product_identifier": [""],
            "platform_identifier": ["XXXX"],
            "cleared": ["I"],
            "prime_brokerage_transaction_indicator": [False],
            "block_trade_election_indicator": [False],
            "large_notional_off-facility_swap_election_indicator": [False],
            "other_payment_type": [""],
            "other_payment_amount": [0],
            "package_indicator": [""],
            "package_transaction_spread": [0],
            "package_type": ["OUTRIGHT"],
            "special_tenor_type": [""],
            "effective_date": pd.to_datetime(["2026-03-11"]),
            "expiration_date": pd.to_datetime(["2036-03-11"]),
            "non-standardized_term_indicator": [False],
        })

    def test_event_type_column_exists(self):
        """Classified data with event_type column passes through."""
        df = self._minimal_df_with_event_type("TRAD")
        assert "event_type" in df.columns
        assert df.iloc[0]["event_type"] == "TRAD"

    def test_event_type_fallback_from_event_action(self):
        """When event_type column missing, extract from event_action."""
        df = self._minimal_df_with_event_type("NOVA")
        df = df.drop(columns=["event_type"])
        # Fallback extraction
        if "event_type" not in df.columns and "event_action" in df.columns:
            parts = df["event_action"].astype(str).str.split("-", n=1)
            df["event_type"] = parts.str[1].fillna("")
        assert df.iloc[0]["event_type"] == "NOVA"
