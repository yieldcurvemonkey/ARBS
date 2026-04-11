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
