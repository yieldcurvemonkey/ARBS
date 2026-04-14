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


class TestEnrichEventTypeFlags:
    """_enrich_event_type extracts boolean flags from event_type column."""

    def _make_df(self, event_action="NEWT-TRAD", event_type="TRAD", **overrides):
        data = {
            "trade_id": ["A1"],
            "event_action": [event_action],
            "event_type": [event_type],
            "tenor_label": ["10Y"],
            "tenor_years": [10.0],
            "notional": [25_000_000],
            "upi_underlier_name": ["USD-SOFR-COMPOUND"],
            "non-standardized_term_indicator": [False],
        }
        data.update(overrides)
        return pd.DataFrame(data)

    def test_comp_flag(self):
        df = self._make_df("NEWT-COMP", "COMP")
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_compression_spec"]) is True

    def test_exer_flag(self):
        df = self._make_df("NEWT-EXER", "EXER")
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_exercise_born"]) is True

    def test_nova_born_flag(self):
        df = self._make_df("NEWT-NOVA", "NOVA")
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_novation"]) is True
        assert bool(result.iloc[0]["is_novation_born"]) is True
        assert bool(result.iloc[0]["is_novation_terminated"]) is False

    def test_nova_terminated_flag(self):
        df = self._make_df("TERM-NOVA", "NOVA")
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_novation"]) is True
        assert bool(result.iloc[0]["is_novation_terminated"]) is True
        assert bool(result.iloc[0]["is_novation_born"]) is False

    def test_clrg_flag(self):
        df = self._make_df("TERM-CLRG", "CLRG")
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_clearing_termination"]) is True

    def test_non_standard_term_flag(self):
        df = self._make_df(**{"non-standardized_term_indicator": [True]})
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_non_standard_term"]) is True

    def test_trad_no_flags(self):
        df = self._make_df("NEWT-TRAD", "TRAD")
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_compression_spec"]) is False
        assert bool(result.iloc[0]["is_exercise_born"]) is False
        assert bool(result.iloc[0]["is_novation"]) is False
        assert bool(result.iloc[0]["is_clearing_termination"]) is False

    def test_fallback_when_no_event_type_column(self):
        """When event_type missing, extract from event_action."""
        df = self._make_df("TERM-NOVA", "NOVA")
        df = df.drop(columns=["event_type"])
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert bool(result.iloc[0]["is_novation_terminated"]) is True


class TestCompressionSpecOverride:
    """is_compression_spec feeds into is_compression."""

    def _make_df(self, event_action="NEWT-COMP", event_type="COMP"):
        return pd.DataFrame({
            "trade_id": ["A1"],
            "execution_timestamp": pd.to_datetime(["2026-03-09 14:00:00+00:00"]),
            "event_action": [event_action],
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

    def test_newt_comp_is_compression(self):
        """NEWT+COMP should be flagged is_compression=True via spec signal."""
        df = self._make_df("NEWT-COMP", "COMP")
        tape = TradeTape(df)
        result = tape.compute()
        row = result.iloc[0]
        assert bool(row["is_compression_spec"]) is True
        assert bool(row["is_compression"]) is True


class TestNovationMatching:
    """Conservative novation chain matching."""

    def _make_nova_pair(self):
        """TERM+NOVA and NEWT+NOVA with matching criteria."""
        return pd.DataFrame({
            "trade_id": ["OLD1", "NEW1"],
            "event_action": ["TERM-NOVA", "NEWT-NOVA"],
            "event_type": ["NOVA", "NOVA"],
            "execution_timestamp": pd.to_datetime([
                "2026-03-09 14:00:00+00:00",
                "2026-03-09 14:00:30+00:00",
            ]),
            "tenor_years": [10.0, 10.0],
            "notional": [25_000_000, 25_000_000],
            "upi_underlier_name": ["USD-SOFR-COMPOUND", "USD-SOFR-COMPOUND"],
            "non-standardized_term_indicator": [False, False],
        })

    def test_matched_pair_gets_shared_id(self):
        df = self._make_nova_pair()
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert result.iloc[0]["novation_match_id"] == result.iloc[1]["novation_match_id"]
        assert pd.notna(result.iloc[0]["novation_match_id"])

    def test_matched_pair_confidence_high(self):
        df = self._make_nova_pair()
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert result.iloc[0]["novation_confidence"] == "HIGH"

    def test_unmatched_nova_has_nan_match_id(self):
        df = pd.DataFrame({
            "trade_id": ["OLD1"],
            "event_action": ["TERM-NOVA"],
            "event_type": ["NOVA"],
            "execution_timestamp": pd.to_datetime(["2026-03-09 14:00:00+00:00"]),
            "tenor_years": [10.0],
            "notional": [25_000_000],
            "upi_underlier_name": ["USD-SOFR-COMPOUND"],
            "non-standardized_term_indicator": [False],
        })
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert pd.isna(result.iloc[0]["novation_match_id"])

    def test_different_notional_no_match(self):
        df = self._make_nova_pair()
        df.loc[1, "notional"] = 50_000_000  # different notional
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert pd.isna(result.iloc[0]["novation_match_id"])

    def test_timestamp_beyond_60s_no_match(self):
        df = self._make_nova_pair()
        df.loc[1, "execution_timestamp"] = pd.Timestamp("2026-03-09 14:05:00+00:00")
        tape = TradeTape(df)
        result = tape._enrich_event_type(df.copy())
        assert pd.isna(result.iloc[0]["novation_match_id"])
