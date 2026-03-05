import datetime
import math

import pytz
import pytest

import MDP.USTFutures.USTFutureOptionMDP as ustfo_module
from MDP.USTFutures.USTFutureOptionMDP import (
    USTFutureOptionMDP,
    _bachelier_greeks_fd,
    _bachelier_price,
    _implied_normal_vol,
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
