"""Tests for unified special tenor classification."""

import pandas as pd
import pytest
from dataclasses import fields as dc_fields

from SDRUtils.core.classification import (
    SwapTradeClassification,
    SpecialTenorType,
    SpecialTenorConfidence,
)


class TestSwapTradeClassificationFields:
    """Verify new special_tenor fields exist on the dataclass."""

    def _make_classification(self, **overrides):
        defaults = dict(
            event_action="NEWT-TRAD",
            trade_id=1,
            execution_timestamp=pd.Timestamp("2026-01-07 21:00:00"),
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2036-01-09"),
            product_type="OIS_SWAP",
            trade_label="spot 10Y",
            notional=100_000_000.0,
            notional_currency="USD",
            is_notional_capped=False,
            tenor_years=10.0,
            tenor_label="10Y",
            is_forward=False,
            forward_start_years=0.0,
            forward_label="spot",
            fixed_rate=0.04,
        )
        defaults.update(overrides)
        return SwapTradeClassification(**defaults)

    def test_default_special_tenor_type_is_standard(self):
        c = self._make_classification()
        assert c.special_tenor_type == "STANDARD"

    def test_default_special_tenor_confidence_is_high(self):
        c = self._make_classification()
        assert c.special_tenor_confidence == "high"

    def test_default_special_tenor_tags_is_empty(self):
        c = self._make_classification()
        assert c.special_tenor_tags == []

    def test_can_set_imm_type(self):
        c = self._make_classification(
            special_tenor_type="IMM",
            special_tenor_tags=["IMM"],
        )
        assert c.special_tenor_type == "IMM"

    def test_can_set_multiple_tags(self):
        c = self._make_classification(
            special_tenor_type="INVOICE_SWAP",
            special_tenor_tags=["MATCHED_MATURITY", "INVOICE_SWAP"],
        )
        assert "MATCHED_MATURITY" in c.special_tenor_tags
        assert "INVOICE_SWAP" in c.special_tenor_tags

    def test_matched_ust_cusip_default_none(self):
        c = self._make_classification()
        assert c.matched_ust_cusip is None

    def test_invoice_swap_ticker_default_none(self):
        c = self._make_classification()
        assert c.invoice_swap_ticker is None

    def test_is_mac_default_false(self):
        c = self._make_classification()
        assert c.is_mac is False


from SDRUtils.core.tenors import classify_intrinsic_special_tenor


class TestIntrinsicSpecialTenor:
    """Tests for Phase 1 intrinsic special tenor classification."""

    def test_standard_tenor_returns_standard(self):
        """A normal 10Y swap should be STANDARD."""
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2036-01-09"),
            tenor_label="10Y",
            forward_label="spot",
            is_forward=False,
        )
        assert typ == "STANDARD"
        assert conf == "high"
        assert tags == []

    def test_imm_maturity_detected(self):
        """Swap maturing on IMM date (3rd Wed of Dec 2026) should tag IMM."""
        # 3rd Wednesday of December 2026 = Dec 16 (pure IMM, no FOMC overlap)
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2026-12-16"),
            tenor_label="IMM_Z2026",
            forward_label="spot",
            is_forward=False,
        )
        assert typ == "IMM"
        assert "IMM" in tags

    def test_imm_forward_detected(self):
        """Forward-starting on IMM date should tag IMM."""
        # 3rd Wednesday of June 2027 = Jun 16 (pure IMM, no FOMC overlap)
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2027-06-16"),
            expiration_date=pd.Timestamp("2029-06-16"),
            tenor_label="2Y",
            forward_label="IMM_M2027",
            is_forward=True,
        )
        assert typ == "IMM"
        assert "IMM" in tags

    def test_fomc_maturity_detected(self):
        """Swap maturing on FOMC date should tag FOMC."""
        # FOMC meeting Jan 29, 2025
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2025-01-02"),
            expiration_date=pd.Timestamp("2025-01-29"),
            tenor_label="FOMC_20250129",
            forward_label="spot",
            is_forward=False,
        )
        assert typ == "FOMC"
        assert "FOMC" in tags

    def test_tier1_fomc_to_fomc_wins(self):
        """Both eff and mat on FOMC meetings -> tier 1 fires, returns FOMC.

        3-tier priority (tier 1 = FOMC-to-FOMC on meeting dates) supersedes
        the old 'FOMC > IMM when both tags present' rule: when both sides
        land on FOMC meetings, the label is unambiguously FOMC."""
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2025-01-29"),
            expiration_date=pd.Timestamp("2025-06-18"),
            tenor_label="IMM_M2025",
            forward_label="FOMC_20250129",
            is_forward=True,
        )
        assert typ == "FOMC"
        assert tags == ["FOMC"]

    def test_labels_checked_not_just_dates(self):
        """Even if date doesn't match QL IMM, label prefix is enough."""
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2026-01-09"),
            expiration_date=pd.Timestamp("2026-12-16"),
            tenor_label="IMM_Z2026",
            forward_label="spot",
            is_forward=False,
        )
        assert "IMM" in tags


from SDRUtils.products.usd.usd_swaps import classify_usd_swap_trade


class TestClassifyUsdSwapTradeSpecialTenor:
    """Verify Phase 1 is wired into classify_usd_swap_trade."""

    def _make_row(self, **overrides):
        defaults = {
            "Action type": "NEWT",
            "Event type": "TRAD",
            "Execution Timestamp": "2026-01-07 21:00:00+00:00",
            "Effective Date": "2026-01-09",
            "Expiration Date": "2036-01-09",
            "UPI FISN": "NA/T Swap Fxd Flt OIS USD",
            "UPI Underlier Name": "USD-SOFR-OIS Compound",
            "Notional amount-Leg 1": "100,000,000",
            "Notional currency-Leg 1": "USD",
            "Fixed rate-Leg 1": 0.04,
        }
        defaults.update(overrides)
        return pd.Series(defaults)

    def test_standard_swap_has_standard_type(self):
        row = self._make_row()
        c = classify_usd_swap_trade(row, trade_id=1, curve=None)
        assert c.special_tenor_type == "STANDARD"
        assert c.special_tenor_tags == []

    def test_imm_maturity_swap_has_imm_type(self):
        # 3rd Wednesday of December 2026 = Dec 16 (pure IMM, no FOMC overlap)
        row = self._make_row(**{"Expiration Date": "2026-12-16"})
        c = classify_usd_swap_trade(row, trade_id=2, curve=None)
        assert c.special_tenor_type == "IMM"
        assert "IMM" in c.special_tenor_tags


from SDRUtils.products.usd.usd_swaps import _is_round_notional, _resolve_special_tenor_priority
import numpy as np


class TestIsRoundNotional:
    """Tests for round-notional detection."""

    def test_exact_multiple_of_5m_is_round(self):
        assert _is_round_notional(100_000_000) is True
        assert _is_round_notional(250_000_000) is True
        assert _is_round_notional(5_000_000) is True

    def test_non_multiple_is_not_round(self):
        assert _is_round_notional(147_300_000) is False
        assert _is_round_notional(103_500_000) is False

    def test_nan_is_not_round(self):
        assert _is_round_notional(float("nan")) is False

    def test_zero_is_not_round(self):
        assert _is_round_notional(0) is False

    def test_negative_is_not_round(self):
        assert _is_round_notional(-100_000_000) is False


class TestResolveSpecialTenorPriority:
    """Tests for the final rollup that resolves unified special_tenor fields."""

    def _make_df(self, rows):
        return pd.DataFrame(rows)

    def test_standard_swap_stays_standard(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": False,
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "spot",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "STANDARD"

    def test_mms_upgrades_standard_to_matched_maturity(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 147_300_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MATCHED_MATURITY"
        assert "MATCHED_MATURITY" in result["special_tenor_tags"].iloc[0]

    def test_invoice_swap_wins_over_matched_maturity(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": "TYA",
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 147_300_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "INVOICE_SWAP"
        assert "MATCHED_MATURITY" in result["special_tenor_tags"].iloc[0]
        assert "INVOICE_SWAP" in result["special_tenor_tags"].iloc[0]

    def test_spot_round_notional_mms_gets_low_confidence(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "spot",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MATCHED_MATURITY"
        assert result["special_tenor_confidence"].iloc[0] == "low"

    def test_spot_nonround_notional_mms_gets_medium_confidence(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "spot",
            "notional": 147_300_000,
            "tenor_years": 10.0,
            "effective_date": "2026-01-09",
            "expiration_date": "2036-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MATCHED_MATURITY"
        assert result["special_tenor_confidence"].iloc[0] == "medium"

    def test_forward_mms_gets_high_confidence_regardless_of_notional(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2027-01-09",
            "expiration_date": "2037-01-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_confidence"].iloc[0] == "high"

    def test_mac_tags_added(self):
        df = self._make_df([{
            "special_tenor_type": "IMM",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "['IMM']",
            "matched_ust_maturity": False,
            "invoice_swap_ticker": None,
            "is_mac": True,
            "forward_label": "spot",
            "notional": 100_000_000,
            "tenor_years": 10.0,
            "effective_date": "2026-03-18",
            "expiration_date": "2036-03-18",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_type"].iloc[0] == "MAC"
        assert "IMM" in result["special_tenor_tags"].iloc[0]
        assert "MAC" in result["special_tenor_tags"].iloc[0]

    def test_short_tenor_mms_gets_low_confidence(self):
        df = self._make_df([{
            "special_tenor_type": "STANDARD",
            "special_tenor_confidence": "high",
            "special_tenor_tags": "[]",
            "matched_ust_maturity": True,
            "matched_ust_maturity_trade_confidence": "high",
            "invoice_swap_ticker": None,
            "is_mac": False,
            "forward_label": "1Y",
            "notional": 147_300_000,
            "tenor_years": 0.5,
            "effective_date": "2026-01-09",
            "expiration_date": "2026-07-09",
        }])
        result = _resolve_special_tenor_priority(df)
        assert result["special_tenor_confidence"].iloc[0] == "low"
