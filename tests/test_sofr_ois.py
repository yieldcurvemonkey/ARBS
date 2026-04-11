import pandas as pd
import pytest

from SDRUtils.products.usd.sofr_ois import classify_sofr_ois_trade
from SDRUtils.products.usd.linear_base import TenorSegment, RateIndex, LinearProductType


def _make_sofr_row(**overrides):
    base = {
        "Dissemination Identifier": "2304676889000000101",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Execution Timestamp": "2026-03-09 20:13:23+00:00",
        "Effective Date": "2026-03-19",
        "Expiration Date": "2036-03-19",
        "Notional amount-Leg 1": "25,000,000",
        "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": None,
        "UPI Underlier Name": "USD-SOFR",
        "UPI FISN": "NA/Swap OIS USD",
        "Cleared": "Y",
        "Package indicator": False,
    }
    base.update(overrides)
    return pd.Series(base)


class TestClassifySofrOis:
    def test_10y_spot_sofr(self):
        row = _make_sofr_row()
        result = classify_sofr_ois_trade(row, trade_id=100)
        assert result.rate_index == RateIndex.SOFR
        assert result.linear_product_type == LinearProductType.OIS
        assert result.tenor_segment == TenorSegment.MEDIUM
        assert result.tenor_years == pytest.approx(10.0, abs=0.1)

    def test_2y_short_term(self):
        row = _make_sofr_row(
            **{"Effective Date": "2026-03-19", "Expiration Date": "2028-03-19"}
        )
        result = classify_sofr_ois_trade(row, trade_id=101)
        assert result.tenor_segment == TenorSegment.SHORT
        assert result.tenor_years == pytest.approx(2.0, abs=0.1)

    def test_sofr_compound_variant(self):
        row = _make_sofr_row(**{"UPI Underlier Name": "USD-SOFR-COMPOUND"})
        result = classify_sofr_ois_trade(row, trade_id=102)
        assert result.rate_index == RateIndex.SOFR_COMPOUND
