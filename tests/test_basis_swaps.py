import pandas as pd
import pytest

from SDRUtils.products.usd.basis_swaps import classify_basis_swap_trade
from SDRUtils.products.usd.linear_base import (
    BasisType,
    LinearProductType,
    TenorSegment,
)


def _make_basis_row(**overrides):
    base = {
        "Dissemination Identifier": "2304676889000000301",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Execution Timestamp": "2026-03-09 16:00:00+00:00",
        "Effective Date": "2026-03-11",
        "Expiration Date": "2031-03-11",
        "Notional amount-Leg 1": "100,000,000",
        "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": None,
        "Spread-Leg 1": "0.0003",
        "Spread-Leg 2": None,
        "UPI Underlier Name": "USD-Federal Funds-OIS Compound vs USD-SOFR-OIS Compound",
        "UPI FISN": "NA/Swap Flt Flt USD",
        "Cleared": "Y",
        "Package indicator": False,
    }
    base.update(overrides)
    return pd.Series(base)


class TestClassifyBasisSwap:
    def test_sofr_ff_basis(self):
        row = _make_basis_row()
        result = classify_basis_swap_trade(row, trade_id=300)
        assert result.basis_type == BasisType.SOFR_FF
        assert result.linear_product_type == LinearProductType.BASIS
        assert result.tenor_segment == TenorSegment.MEDIUM
        assert result.tenor_years == pytest.approx(5.0, abs=0.1)
        assert result.spread_bps == pytest.approx(3.0, abs=0.1)

    def test_sofr_tenor_basis(self):
        row = _make_basis_row(
            **{"UPI Underlier Name": "USD-SOFR vs USD-SOFR"}
        )
        result = classify_basis_swap_trade(row, trade_id=301)
        assert result.basis_type == BasisType.SOFR_TENOR

    def test_ff_tenor_basis(self):
        row = _make_basis_row(
            **{"UPI Underlier Name": "USD-Federal Funds-H.15 vs USD-Federal Funds-H.15"}
        )
        result = classify_basis_swap_trade(row, trade_id=302)
        assert result.basis_type == BasisType.FF_TENOR

    def test_cms_basis(self):
        row = _make_basis_row(
            **{"UPI Underlier Name": "USD-ISDA-Swap Rate vs USD-ISDA-Swap Rate"}
        )
        result = classify_basis_swap_trade(row, trade_id=303)
        assert result.basis_type == BasisType.CMS

    def test_sifma_basis(self):
        row = _make_basis_row(
            **{"UPI Underlier Name": "USD-SIFMA Municipal Swap Index vs USD-SIFMA Municipal Swap Index"}
        )
        result = classify_basis_swap_trade(row, trade_id=304)
        assert result.basis_type == BasisType.SIFMA

    def test_obfr_sofr_basis(self):
        row = _make_basis_row(
            **{"UPI Underlier Name": "USD-Overnight Bank Funding Rate vs USD-SOFR-COMPOUND"}
        )
        result = classify_basis_swap_trade(row, trade_id=305)
        assert result.basis_type == BasisType.OBFR_SOFR

    def test_xccy_basis(self):
        row = _make_basis_row(
            **{
                "UPI Underlier Name": "JPY-TONA-OIS Compound vs USD-SOFR-OIS Compound",
                "UPI FISN": "NA/Swap Flt Flt JPY USD",
            }
        )
        result = classify_basis_swap_trade(row, trade_id=306)
        assert result.basis_type == BasisType.XCCY

    def test_short_term_basis(self):
        row = _make_basis_row(
            **{"Effective Date": "2026-03-11", "Expiration Date": "2027-03-11"}
        )
        result = classify_basis_swap_trade(row, trade_id=307)
        assert result.tenor_segment == TenorSegment.SHORT

    def test_spread_from_leg2(self):
        row = _make_basis_row(**{"Spread-Leg 1": None, "Spread-Leg 2": "0.0005"})
        result = classify_basis_swap_trade(row, trade_id=308)
        assert result.spread_bps == pytest.approx(5.0, abs=0.1)

    def test_leg_indices_populated(self):
        row = _make_basis_row()
        result = classify_basis_swap_trade(row, trade_id=309)
        assert "Federal Funds" in result.leg1_rate_index
        assert "SOFR" in result.leg2_rate_index
