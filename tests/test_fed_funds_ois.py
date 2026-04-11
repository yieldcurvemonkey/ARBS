import pandas as pd
import pytest

from SDRUtils.products.usd.fed_funds_ois import classify_fed_funds_ois_trade
from SDRUtils.products.usd.linear_base import TenorSegment, RateIndex, LinearProductType


def _make_ff_row(**overrides):
    base = {
        "Dissemination Identifier": "2304676889000000201",
        "Action type": "NEWT",
        "Event type": "TRAD",
        "Execution Timestamp": "2026-03-09 15:30:00+00:00",
        "Effective Date": "2026-03-11",
        "Expiration Date": "2027-03-11",
        "Notional amount-Leg 1": "500,000,000",
        "Notional currency-Leg 1": "USD",
        "Fixed rate-Leg 1": "0.0432",
        "UPI Underlier Name": "USD-Federal Funds-OIS Compound",
        "UPI FISN": "NA/Swap OIS USD",
        "Cleared": "Y",
        "Package indicator": False,
    }
    base.update(overrides)
    return pd.Series(base)


class TestClassifyFedFundsOis:
    def test_1y_ff_ois(self):
        row = _make_ff_row()
        result = classify_fed_funds_ois_trade(row, trade_id=200)
        assert result.rate_index == RateIndex.FED_FUNDS
        assert result.linear_product_type == LinearProductType.OIS
        assert result.tenor_segment == TenorSegment.SHORT
        assert result.tenor_years == pytest.approx(1.0, abs=0.1)

    def test_10y_ff_medium_term(self):
        row = _make_ff_row(
            **{"Effective Date": "2026-03-19", "Expiration Date": "2036-03-19"}
        )
        result = classify_fed_funds_ois_trade(row, trade_id=201)
        assert result.tenor_segment == TenorSegment.MEDIUM
        assert result.tenor_years == pytest.approx(10.0, abs=0.1)

    def test_ff_h15_compound_variant(self):
        row = _make_ff_row(**{"UPI Underlier Name": "USD-Federal Funds-H.15-OIS-COMPOUND"})
        result = classify_fed_funds_ois_trade(row, trade_id=202)
        assert result.rate_index == RateIndex.FED_FUNDS_COMPOUND

    def test_ff_h15_plain(self):
        row = _make_ff_row(**{"UPI Underlier Name": "USD-Federal Funds-H.15"})
        result = classify_fed_funds_ois_trade(row, trade_id=203)
        assert result.rate_index == RateIndex.FED_FUNDS
