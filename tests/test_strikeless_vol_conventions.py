import math

import pytest

from RVUtils.StrikelessVol.conventions import (
    FLATTENER,
    STEEPENER,
    TRADING_DAYS,
    VolQuote,
    annual_normals_to_bp_day,
    bp_day_to_annual_normals,
    slope_bp,
)


def test_trading_days_is_252():
    assert TRADING_DAYS == 252.0


def test_gs_daily_vol_matches_published_annual_normals():
    # GS IR_SWAPTION_VOLS_V1_STANDARD publishes impliedNormalVolatility as a
    # DAILY bp vol. USD 2y10y on 2026-08-03 was 5.329, quoted on the desk as
    # 84.6 normals.
    assert bp_day_to_annual_normals(5.329) == pytest.approx(84.6, abs=0.05)
    assert annual_normals_to_bp_day(84.6) == pytest.approx(84.6 / math.sqrt(252.0))


def test_conversions_round_trip():
    assert annual_normals_to_bp_day(bp_day_to_annual_normals(4.2)) == pytest.approx(4.2)


def test_vol_quote_requires_full_label():
    with pytest.raises(TypeError):
        VolQuote(5.0)  # measure / underlying / window are mandatory


def test_vol_quote_annual_normals():
    q = VolQuote(
        value_bp_day=5.329,
        measure="implied",
        underlying="USD 2y10y ATM swaption",
        window="atm",
    )
    assert q.annual_normals == pytest.approx(84.6, abs=0.05)


def test_vol_quote_is_frozen():
    q = VolQuote(value_bp_day=1.0, measure="realized", underlying="x", window="63d")
    with pytest.raises(Exception):
        q.value_bp_day = 2.0


def test_slope_is_long_minus_short_and_inverted_is_negative():
    # 10y10y = 4.00%, 20y10y = 3.42% -> inverted -> -58bp
    assert slope_bp(short_rate=0.0400, long_rate=0.0342) == pytest.approx(-58.0)
    assert slope_bp(short_rate=0.0342, long_rate=0.0400) == pytest.approx(58.0)


def test_direction_constants():
    assert FLATTENER == 1
    assert STEEPENER == -1
