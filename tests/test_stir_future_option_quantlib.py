import datetime
import math

import pytz
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import (
    STIRFutureOptionSABRParams,
    STIRFutureOptionSABRSmile,
    STIRFutureOptionMDP,
    _bachelier_greeks_fd,
    _bachelier_price,
    _calibrate_sabr_normal_from_delta_points,
    _implied_normal_vol,
    _normal_delta_to_strike,
    _sabr_normal_vol,
)


def test_bachelier_price_implied_vol_consistency():
    right = "C"
    strike = 97.0
    forward = 96.8
    tte = 1.25
    discount = 0.99
    vol = 0.85

    price = _bachelier_price(right, strike, forward, vol, tte, discount)
    iv = _implied_normal_vol(right, strike, forward, tte, price, discount)
    assert iv == iv
    assert iv == pytest.approx(vol, rel=1e-3)


def test_bachelier_greeks_fd_are_finite():
    delta, gamma, vega, theta = _bachelier_greeks_fd(
        right="C",
        strike=97.0,
        forward=96.8,
        vol_normal=0.85,
        tte=1.25,
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
        strike=97.0,
        forward=96.8,
        vol_normal=0.85,
        tte=1.25,
        discount=0.99,
        use_ql_calculator=False,
    )
    ql_calc = _bachelier_greeks_fd(
        right="C",
        strike=97.0,
        forward=96.8,
        vol_normal=0.85,
        tte=1.25,
        discount=0.99,
        use_ql_calculator=True,
    )

    for v in ql_calc:
        assert math.isfinite(v)

    assert ql_calc[0] == pytest.approx(fd[0], rel=2e-2)
    assert ql_calc[1] == pytest.approx(fd[1], rel=2e-2)
    assert ql_calc[2] == pytest.approx(fd[2], rel=2e-2)


def test_discount_factor_fail_open(monkeypatch):
    mdp = STIRFutureOptionMDP(source="BARCHART_STIRFO-QL")

    class _FailCurveBuilder:
        def build_curve(self, *args, **kwargs):
            raise RuntimeError("curve boom")

    monkeypatch.setattr(mdp, "_get_curve_builder", lambda: _FailCurveBuilder())
    memo = {}

    df, err = mdp._discount_factor(
        valuation_ts=pytz.timezone("America/New_York").localize(datetime.datetime(2026, 1, 2, 17, 0)),
        expiry_date=datetime.date(2026, 12, 16),
        curve_name="USD-OIS-Q12xM12STIRT-SERFFX-MIX23",
        curve_kwargs={},
        memo=memo,
    )
    assert df == 1.0
    assert err is not None


def test_sabr_normal_vol_is_finite_atm_and_otm():
    atm = _sabr_normal_vol(
        strike=96.25,
        forward=96.25,
        time_to_expiry=90.0 / 365.0,
        alpha=0.06,
        beta=0.5,
        rho=-0.15,
        nu=1.8,
    )
    otm = _sabr_normal_vol(
        strike=96.75,
        forward=96.25,
        time_to_expiry=90.0 / 365.0,
        alpha=0.06,
        beta=0.5,
        rho=-0.15,
        nu=1.8,
    )
    assert math.isfinite(atm)
    assert math.isfinite(otm)
    assert atm > 0.0
    assert otm > 0.0


def test_calibrate_sabr_normal_from_delta_points_recovers_reasonable_params():
    forward = 96.25
    time_to_expiry = 90.0 / 365.0
    true_alpha = 0.06
    true_rho = -0.20
    true_nu = 1.90
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
    assert params.nu == pytest.approx(true_nu, rel=3e-1)


def test_calibrate_sabr_handles_duplicate_atm_strikes():
    forward = 96.25
    time_to_expiry = 90.0 / 365.0
    market_points = [
        (0.50, 0.14, "C"),
        (0.50, 0.14, "P"),
        (0.25, 0.18, "C"),
        (0.25, 0.12, "P"),
        (0.10, 0.24, "C"),
        (0.10, 0.11, "P"),
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


def test_sabr_smile_supports_price_rate_and_delta_views():
    params = STIRFutureOptionSABRParams(
        alpha=0.06,
        beta=0.5,
        rho=-0.20,
        nu=1.90,
        forward_price=96.25,
        forward_rate=3.75,
        time_to_expiry=90.0 / 365.0,
        expiry_date=datetime.date(2026, 6, 17),
        as_of=datetime.date(2026, 3, 19),
    )
    smile = STIRFutureOptionSABRSmile(
        source="STIRFO_DUAL-QL",
        symbol="SR3_90",
        underlying_contract="SFRM26",
        quote_timestamp=pytz.timezone("America/New_York").localize(datetime.datetime(2026, 3, 19, 17, 0)),
        params=params,
        points=tuple(),
    )

    strike_price = 96.50
    strike_rate = smile.price_to_rate(strike_price)
    vol_price = smile.normal_vol(strike_price, strike_space="price", vol_units="price")
    vol_rate = smile.normal_vol(strike_rate, strike_space="rate", vol_units="price")
    vol_bps = smile.normal_vol(strike_price, strike_space="price", vol_units="bps")

    assert strike_rate == pytest.approx(3.50)
    assert smile.rate_to_price(strike_rate) == pytest.approx(strike_price)
    assert vol_rate == pytest.approx(vol_price, rel=1e-10)
    assert vol_bps == pytest.approx(vol_price * 100.0, rel=1e-12)

    call_strike_price = smile.delta_to_strike(25, "C", strike_space="price")
    call_strike_rate = smile.delta_to_strike(25, "C", strike_space="rate")
    assert call_strike_rate == pytest.approx(100.0 - call_strike_price, rel=1e-12)

    delta_strikes, delta_vols = smile.normal_vol_for_deltas([25, 50], right=["C", "P"], strike_space_out="rate", vol_units="bps")
    assert len(delta_strikes) == 2
    assert len(delta_vols) == 2
    assert delta_vols[0] == pytest.approx(
        smile.normal_vol(delta_strikes[0], strike_space="rate", vol_units="bps"),
        rel=1e-12,
    )
