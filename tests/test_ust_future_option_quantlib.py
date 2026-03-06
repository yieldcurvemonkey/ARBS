import datetime
import math

import pytz
import pytest

import MDP.USTFutures.USTFutureOptionMDP as ustfo_module
from MDP.USTFutures.USTFutureOptionMDP import (
    USTFutureOptionSABRParams,
    USTFutureOptionSABRSmile,
    USTFutureOptionMDP,
    _bachelier_greeks_fd,
    _bachelier_price,
    _calibrate_sabr_normal_from_delta_points,
    _implied_normal_vol,
    _normal_delta_to_strike,
    _sabr_normal_vol,
)


def test_bachelier_price_implied_vol_consistency():
    right = "C"
    strike = 112.5
    forward = 112.3
    tte = 0.5
    discount = 0.99
    vol = 1.25

    price = _bachelier_price(right, strike, forward, vol, tte, discount)
    iv = _implied_normal_vol(right, strike, forward, tte, price, discount)
    assert iv == iv
    assert iv == pytest.approx(vol, rel=1e-3)


def test_bachelier_greeks_fd_are_finite():
    delta, gamma, vega, theta = _bachelier_greeks_fd(
        right="C",
        strike=112.5,
        forward=112.3,
        vol_normal=1.25,
        tte=0.5,
        discount=0.99,
    )
    assert math.isfinite(delta)
    assert math.isfinite(gamma)
    assert math.isfinite(vega)
    assert math.isfinite(theta)
    assert gamma > 0.0
    assert vega > 0.0


def test_bachelier_greeks_with_ql_calculator():
    fd = _bachelier_greeks_fd(
        right="C",
        strike=112.5,
        forward=112.3,
        vol_normal=1.25,
        tte=0.5,
        discount=0.99,
        use_ql_calculator=False,
    )
    ql_calc = _bachelier_greeks_fd(
        right="C",
        strike=112.5,
        forward=112.3,
        vol_normal=1.25,
        tte=0.5,
        discount=0.99,
        use_ql_calculator=True,
    )

    for v in ql_calc:
        assert math.isfinite(v)

    assert ql_calc[0] == pytest.approx(fd[0], rel=2e-2)
    assert ql_calc[1] == pytest.approx(fd[1], rel=2e-2)
    assert ql_calc[2] == pytest.approx(fd[2], rel=2e-2)


def test_discount_factor_fail_open(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")

    class _FailCurveBuilder:
        def build_curve(self, *args, **kwargs):
            raise RuntimeError("curve boom")

    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _FailCurveBuilder())
    memo = {}

    df, err = mdp._discount_factor(
        valuation_ts=pytz.timezone("America/New_York").localize(datetime.datetime(2026, 3, 4, 17, 0)),
        expiry_date=datetime.date(2026, 6, 26),
        curve_name="USD-SOFR-1D-Q12xM12STIRT",
        curve_kwargs={},
        memo=memo,
    )
    assert df == 1.0
    assert err is not None


def test_compute_fv01_maps_barchart_root_and_falls_back(monkeypatch):
    mdp = USTFutureOptionMDP(source="BARCHART_USTFO-QL")
    seen = {}

    class _FailBasketUSTFuturesMDP:
        def __init__(self, source="BARCHART_USTF-RL"):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            _ = exc_type, exc, tb
            return False

        def get_delivery_basket(self, *, as_of, symbol, **kwargs):
            _ = as_of, kwargs
            seen["symbol"] = symbol
            raise RuntimeError("boom")

    monkeypatch.setattr(ustfo_module, "USTFuturesMDP", _FailBasketUSTFuturesMDP)

    fv01 = mdp._compute_fv01(
        underlying_contract="ZFJ26",
        forward=109.5,
        as_of=datetime.date(2026, 3, 3),
    )

    assert seen["symbol"] == "FVJ26"
    assert math.isfinite(fv01)
    assert fv01 == pytest.approx(0.040)


def test_sabr_normal_vol_is_finite_atm_and_otm():
    atm = _sabr_normal_vol(
        strike=112.9,
        forward=112.9,
        time_to_expiry=30.0 / 365.0,
        alpha=0.07,
        beta=0.5,
        rho=0.25,
        nu=2.2,
    )
    otm = _sabr_normal_vol(
        strike=114.0,
        forward=112.9,
        time_to_expiry=30.0 / 365.0,
        alpha=0.07,
        beta=0.5,
        rho=0.25,
        nu=2.2,
    )
    assert math.isfinite(atm)
    assert math.isfinite(otm)
    assert atm > 0.0
    assert otm > 0.0


def test_calibrate_sabr_normal_from_delta_points_recovers_reasonable_params():
    forward = 112.90625
    time_to_expiry = 30.0 / 365.0
    true_alpha = 0.069
    true_rho = 0.34
    true_nu = 2.45
    market_points = []

    for right in ("C", "P"):
        for delta_abs in (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50):
            vol = _sabr_normal_vol(
                strike=forward,
                forward=forward,
                time_to_expiry=time_to_expiry,
                alpha=true_alpha,
                beta=0.5,
                rho=true_rho,
                nu=true_nu,
            )
            for _ in range(32):
                strike = _normal_delta_to_strike(
                    delta_abs=delta_abs,
                    vol_normal=vol,
                    forward=forward,
                    time_to_expiry=time_to_expiry,
                    right=right,
                )
                nxt = _sabr_normal_vol(
                    strike=strike,
                    forward=forward,
                    time_to_expiry=time_to_expiry,
                    alpha=true_alpha,
                    beta=0.5,
                    rho=true_rho,
                    nu=true_nu,
                )
                if abs(nxt - vol) < 1e-12:
                    break
                vol = nxt
            market_points.append((delta_abs, vol, right))

    params = _calibrate_sabr_normal_from_delta_points(
        forward=forward,
        time_to_expiry=time_to_expiry,
        market_points=market_points,
        beta=0.5,
    )

    assert params.beta == pytest.approx(0.5)
    assert params.alpha == pytest.approx(true_alpha, rel=2e-1)
    assert params.rho == pytest.approx(true_rho, rel=2e-1)
    assert params.nu == pytest.approx(true_nu, rel=2.5e-1)


def test_calibrate_sabr_handles_duplicate_atm_strikes():
    forward = 112.90625
    time_to_expiry = 30.0 / 365.0
    market_points = [
        (0.50, 0.77, "C"),
        (0.50, 0.77, "P"),
        (0.25, 0.84, "C"),
        (0.25, 0.72, "P"),
        (0.10, 1.04, "C"),
        (0.10, 0.75, "P"),
    ]
    params = _calibrate_sabr_normal_from_delta_points(
        forward=forward,
        time_to_expiry=time_to_expiry,
        market_points=market_points,
        beta=0.5,
    )
    assert math.isfinite(params.alpha)
    assert math.isfinite(params.rho)
    assert math.isfinite(params.nu)


def test_sabr_smile_supports_price_and_futures_ytm_strike_spaces():
    params = USTFutureOptionSABRParams(
        alpha=0.069,
        beta=0.5,
        rho=0.34,
        nu=2.45,
        forward_price=112.90625,
        forward_futures_ytm=0.0435,
        time_to_expiry=30.0 / 365.0,
        expiry_date=datetime.date(2026, 4, 3),
        as_of=datetime.date(2026, 3, 4),
    )
    smile = USTFutureOptionSABRSmile(
        source="USTFO_DUAL-QL",
        globex_symbol="TY_30",
        underlying_contract="ZNH26",
        quote_timestamp=pytz.timezone("America/New_York").localize(datetime.datetime(2026, 3, 4, 17, 0)),
        fv01=0.08,
        params=params,
        points=tuple(),
        price_grid=tuple([112.0, 112.5, 113.0, 113.5, 114.0]),
        futures_ytm_grid=tuple([0.0445, 0.0440, 0.0435, 0.0430, 0.0425]),
    )

    strike_price = 113.0
    strike_ytm = smile.price_to_futures_ytm(strike_price)
    vol_price = smile.normal_vol(strike_price, strike_space="price", vol_units="price")
    vol_ytm = smile.normal_vol(strike_ytm, strike_space="futures_ytm", vol_units="price")
    vol_bps = smile.normal_vol(strike_price, strike_space="price", vol_units="bps")

    assert strike_ytm == pytest.approx(0.0435)
    assert smile.futures_ytm_to_price(strike_ytm) == pytest.approx(strike_price)
    assert vol_ytm == pytest.approx(vol_price, rel=1e-10)
    assert vol_bps == pytest.approx(vol_price / smile.fv01, rel=1e-12)
