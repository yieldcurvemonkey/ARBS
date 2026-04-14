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


class TestEventTypeLabelIntegration:
    """Labels, clean_tape, summary reflect event type flags."""

    def _make_tape_df(self, event_action="NEWT-NOVA", event_type="NOVA"):
        return pd.DataFrame({
            "trade_id": ["A1"],
            "upi_underlier_name": ["USD-SOFR-COMPOUND"],
            "product_type": ["OIS_SWAP"],
            "upi_reset_freq": [""],
            "upi_notional_schedule": [""],
            "forward_label": ["spot"],
            "forward_start_years": [0.0],
            "tenor_label": ["10Y"],
            "tenor_display": ["10Y"],
            "trade_type": ["OUTRIGHT"],
            "lifecycle_type": ["NEW_TRADE"],
            "is_unwind": [False],
            "is_mac": [False],
            "is_ufro": [False],
            "is_block": [False],
            "cleared": ["I"],
            "is_novation_born": [event_type == "NOVA" and "NEWT" in event_action],
            "is_novation_terminated": [event_type == "NOVA" and "TERM" in event_action],
            "is_exercise_born": [event_type == "EXER"],
            "is_clearing_termination": [event_type == "CLRG"],
            "xd_status": ["ACTIVE"],
            "xd_has_partial_unwind": [False],
        })

    def test_nova_in_label(self):
        tape = TradeTape(self._make_tape_df("NEWT-NOVA", "NOVA"))
        df = tape._build_enriched_label(self._make_tape_df("NEWT-NOVA", "NOVA"))
        assert "NOVA-IN" in df.iloc[0]["tape_label"]

    def test_nova_out_label(self):
        tape = TradeTape(self._make_tape_df("TERM-NOVA", "NOVA"))
        df = tape._build_enriched_label(self._make_tape_df("TERM-NOVA", "NOVA"))
        assert "NOVA-OUT" in df.iloc[0]["tape_label"]

    def test_exer_label(self):
        tape = TradeTape(self._make_tape_df("NEWT-EXER", "EXER"))
        df = tape._build_enriched_label(self._make_tape_df("NEWT-EXER", "EXER"))
        assert "EXER" in df.iloc[0]["tape_label"]

    def test_clrg_label(self):
        tape = TradeTape(self._make_tape_df("TERM-CLRG", "CLRG"))
        df = tape._build_enriched_label(self._make_tape_df("TERM-CLRG", "CLRG"))
        assert "CLRG" in df.iloc[0]["tape_label"]


class TestCleanTapeEventType:
    """clean_tape excludes novation-terminated and clearing-terminated."""

    def _make_classified_df(self):
        return pd.DataFrame({
            "trade_id": ["A1", "B1", "C1"],
            "execution_timestamp": pd.to_datetime([
                "2026-03-09 14:00:00+00:00",
                "2026-03-09 15:00:00+00:00",
                "2026-03-09 16:00:00+00:00",
            ]),
            "event_action": ["TERM-NOVA", "TERM-CLRG", "NEWT-TRAD"],
            "event_type": ["NOVA", "CLRG", "TRAD"],
            "tenor_label": ["10Y", "5Y", "10Y"],
            "tenor_years": [10.0, 5.0, 10.0],
            "forward_label": ["spot", "spot", "spot"],
            "forward_start_years": [0.0, 0.0, 0.0],
            "notional": [25_000_000, 50_000_000, 25_000_000],
            "fixed_rate": [0.04, 0.045, 0.04],
            "estimated_pv01": [9000, 4500, 9000],
            "product_type": ["OIS_SWAP", "OIS_SWAP", "OIS_SWAP"],
            "upi_underlier_name": ["USD-SOFR-COMPOUND"] * 3,
            "unique_product_identifier": [""] * 3,
            "platform_identifier": ["XXXX"] * 3,
            "cleared": ["I"] * 3,
            "prime_brokerage_transaction_indicator": [False] * 3,
            "block_trade_election_indicator": [False] * 3,
            "large_notional_off-facility_swap_election_indicator": [False] * 3,
            "other_payment_type": [""] * 3,
            "other_payment_amount": [0] * 3,
            "package_indicator": [""] * 3,
            "package_transaction_spread": [0] * 3,
            "package_type": ["OUTRIGHT"] * 3,
            "special_tenor_type": [""] * 3,
            "effective_date": pd.to_datetime(["2026-03-11"] * 3),
            "expiration_date": pd.to_datetime(["2036-03-11", "2031-03-11", "2036-03-11"]),
            "non-standardized_term_indicator": [False] * 3,
        })

    def test_nova_and_clrg_excluded(self):
        tape = TradeTape(self._make_classified_df())
        tape.compute()
        clean = tape.clean_tape()
        ids = clean["trade_id"].values
        assert "A1" not in ids  # TERM+NOVA excluded
        assert "B1" not in ids  # TERM+CLRG excluded
        assert "C1" in ids     # NEWT+TRAD kept


class TestSummaryEventType:
    """summary() includes event type counts."""

    def test_summary_has_event_type_keys(self):
        df = pd.DataFrame({
            "trade_id": ["A1"],
            "execution_timestamp": pd.to_datetime(["2026-03-09 14:00:00+00:00"]),
            "event_action": ["NEWT-TRAD"],
            "event_type": ["TRAD"],
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
        tape = TradeTape(df)
        tape.compute()
        s = tape.summary()
        assert "n_novations" in s
        assert "n_compressions_spec" in s
        assert "n_exercise_born" in s
        assert "n_clearing_terminations" in s
        assert "n_non_standard_term" in s


EXAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "notebooks", "sdr", "sdr_example.csv")


@pytest.mark.skipif(not os.path.exists(EXAMPLE_CSV), reason="sdr_example.csv not available")
class TestEventTypeRealData:
    """Integration tests with real SDR data."""

    @pytest.fixture
    def raw_df(self):
        df = pd.read_csv(EXAMPLE_CSV, low_memory=False, dtype={
            "Dissemination Identifier": str,
            "Original Dissemination Identifier": str,
        })
        df["Original Dissemination Identifier"] = df["Original Dissemination Identifier"].fillna("")
        return df

    def test_nova_count(self, raw_df):
        nova = raw_df[raw_df["Event type"] == "NOVA"]
        assert len(nova) > 1500

    def test_comp_count(self, raw_df):
        comp = raw_df[raw_df["Event type"] == "COMP"]
        assert len(comp) > 2000

    def test_exer_count(self, raw_df):
        exer = raw_df[raw_df["Event type"] == "EXER"]
        assert len(exer) > 500

    def test_clrg_count(self, raw_df):
        clrg = raw_df[raw_df["Event type"] == "CLRG"]
        assert len(clrg) > 400

    def test_nova_action_type_breakdown(self, raw_df):
        nova = raw_df[raw_df["Event type"] == "NOVA"]
        actions = nova["Action type"].value_counts()
        assert "NEWT" in actions.index
        assert "TERM" in actions.index
