import datetime
from unittest.mock import patch

import numpy as np
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import (
    STIRFutureOptionSABRParams,
    STIRFutureOptionSABRSmile,
    STIRFutureOptionSmilePoint,
)
from RVUtils.ImpliedDistribution import RNDInput
from RVUtils.ImpliedDistribution.implied_distribution import SFRImpliedDistribution
from RVUtils.ImpliedDistribution._breeden_litzenberger import extract_rnd_breeden_litzenberger
from RVUtils.ImpliedDistribution._data_prep import smile_to_rnd_input


def _smile(points):
    return STIRFutureOptionSABRSmile(
        source="BARCHART_STIRFO-QL",
        symbol="SFRZ26",
        underlying_contract="SFRZ26",
        quote_timestamp=datetime.datetime(2026, 4, 23, 17, 0),
        params=STIRFutureOptionSABRParams(
            alpha=0.1,
            beta=0.5,
            rho=0.0,
            nu=1.0,
            forward_price=96.5,
            forward_rate=3.5,
            time_to_expiry=0.5,
            expiry_date=datetime.date(2026, 12, 16),
            as_of=datetime.date(2026, 4, 23),
        ),
        points=tuple(points),
    )


def _point(label, right, strike, price, oi, vol=0.01):
    return STIRFutureOptionSmilePoint(
        label=label,
        right=right,
        delta_abs=25.0,
        atm_offset_bps=0.0,
        strike_price=strike,
        strike_rate=100.0 - strike,
        iv_normal_price=vol,
        iv_normal_bps=vol * 100.0,
        market_price=price,
        discount_factor=1.0,
        open_interest=oi,
    )


def test_smile_to_rnd_input_uses_observed_otm_prices_and_oi_filter():
    smile = _smile(
        [
            _point("SFRZ26|9600P", "P", 96.0, 0.05, 150.0),
            _point("SFRZ26|9650C-low-oi", "C", 96.5, 0.15, 50.0),
            _point("SFRZ26|9700C", "C", 97.0, 0.07, 175.0),
            _point("SFRZ26|9700P-itm", "P", 97.0, 0.55, 175.0),
        ]
    )

    rnd = smile_to_rnd_input(
        smile,
        use_sabr_vols=False,
        raw_market_open_interest_min=100.0,
        raw_market_otm_only=True,
    )

    assert rnd.strike_source == "market_jpm"
    assert rnd.strikes_price.tolist() == [96.0, 97.0]
    # OTM put converted to an equivalent call premium: P + F - K.
    assert rnd.call_premiums.tolist() == pytest.approx([0.55, 0.07])


def test_sfr_implied_distribution_defaults_to_raw_jpm_bl_native_bins():
    seen = {}
    rnd_input = RNDInput(
        symbol="SFRZ26",
        as_of=datetime.date(2026, 4, 23),
        forward_price=96.5,
        forward_rate=3.5,
        time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 16),
        discount_factor=1.0,
        strikes_price=np.array([96.0, 96.5, 97.0]),
        call_premiums=np.array([0.6, 0.3, 0.1]),
        strike_source="market_jpm",
    )

    def fake_smile_to_rnd_input(smile, **kwargs):
        seen["prep"] = kwargs
        return rnd_input

    def fake_extract_rnd(rnd, **kwargs):
        seen["bl"] = kwargs
        return "bl-result"

    with patch("RVUtils.ImpliedDistribution.implied_distribution.smile_to_rnd_input", fake_smile_to_rnd_input):
        with patch("RVUtils.ImpliedDistribution.implied_distribution.extract_rnd_breeden_litzenberger", fake_extract_rnd):
            snap = SFRImpliedDistribution().extract(_smile([]), run_gm=False)

    assert snap.bl_result == "bl-result"
    assert seen["prep"]["use_sabr_vols"] is False
    assert seen["prep"]["sabr_extrapolation"] is False
    assert seen["prep"]["raw_market_open_interest_min"] == 100.0
    assert seen["prep"]["raw_market_otm_only"] is True
    assert seen["bl"]["smoothing_param"] == pytest.approx(1e-4)
    assert seen["bl"]["scale_smoothing_by_n"] is False
    assert seen["bl"]["n_ghost_points"] == 10
    assert seen["bl"]["ghost_extension_bps"] == pytest.approx(5.0)
    assert seen["bl"]["bin_width_bps"] == pytest.approx(25.0)


def test_bl_smoothing_param_is_literal_by_default():
    seen = {}

    class FakeSpline:
        def __init__(self, x, y, *, k, s):
            seen["s"] = s

        def __call__(self, x, nu=0):
            arr = np.asarray(x, dtype=float)
            if nu == 2:
                return np.ones_like(arr)
            return np.zeros_like(arr)

    rnd_input = RNDInput(
        symbol="SFRZ26",
        as_of=datetime.date(2026, 4, 23),
        forward_price=96.5,
        forward_rate=3.5,
        time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 16),
        discount_factor=1.0,
        strikes_price=np.array([96.0, 96.5, 97.0]),
        call_premiums=np.array([0.6, 0.3, 0.1]),
        strike_source="test",
    )

    with patch("RVUtils.ImpliedDistribution._breeden_litzenberger.UnivariateSpline", FakeSpline):
        extract_rnd_breeden_litzenberger(rnd_input, smoothing_param=1e-4, n_ghost_points=1)

    assert seen["s"] == pytest.approx(1e-4)


def test_bl_can_opt_into_legacy_n_scaled_smoothing():
    seen = {}

    class FakeSpline:
        def __init__(self, x, y, *, k, s):
            seen["s"] = s
            seen["n"] = len(x)

        def __call__(self, x, nu=0):
            arr = np.asarray(x, dtype=float)
            if nu == 2:
                return np.ones_like(arr)
            return np.zeros_like(arr)

    rnd_input = RNDInput(
        symbol="SFRZ26",
        as_of=datetime.date(2026, 4, 23),
        forward_price=96.5,
        forward_rate=3.5,
        time_to_expiry=0.5,
        expiry_date=datetime.date(2026, 12, 16),
        discount_factor=1.0,
        strikes_price=np.array([96.0, 96.5, 97.0]),
        call_premiums=np.array([0.6, 0.3, 0.1]),
        strike_source="test",
    )

    with patch("RVUtils.ImpliedDistribution._breeden_litzenberger.UnivariateSpline", FakeSpline):
        extract_rnd_breeden_litzenberger(
            rnd_input,
            smoothing_param=1e-4,
            scale_smoothing_by_n=True,
            n_ghost_points=1,
        )

    assert seen["s"] == pytest.approx(1e-4 * seen["n"])
