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

    def test_fomc_takes_priority_over_imm_when_both_match(self):
        """If both FOMC and IMM labels present, FOMC wins (higher priority)."""
        typ, conf, tags = classify_intrinsic_special_tenor(
            effective_date=pd.Timestamp("2025-01-29"),
            expiration_date=pd.Timestamp("2025-06-18"),
            tenor_label="IMM_M2025",
            forward_label="FOMC_20250129",
            is_forward=True,
        )
        assert typ == "FOMC"
        assert "IMM" in tags
        assert "FOMC" in tags

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
