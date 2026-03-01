import datetime
import math

import pytz
import pytest

from MDP.STIRFutures.STIRFutureOptionMDP import (
    STIRFutureOptionMDP,
    _bachelier_greeks_fd,
    _bachelier_price,
    _implied_normal_vol,
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
