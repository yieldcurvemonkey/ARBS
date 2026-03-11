import importlib
import datetime as dt
import math

import pytest

from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue, IRSwaptionValueFunctionMap
from Query.IRSwaptions.pricer import IRSwaptionPricable


value_module = importlib.import_module("Query.IRSwaptions.IRSwaptionValue")


class _DummyContext:
    pass


def test_value_enum_metrics_with_deterministic_leg_metrics(monkeypatch):
    metrics = {
        "A": {
            "NVOL": 100.0,
            "SPOT_NPV": 10.0,
            "FWD_NPV": 11.0,
            "SPOT_PREM": 0.000010,
            "FWD_PREM": 0.11,
            "DV01": 1.2,
            "DELTA": 0.5,
            "GAMMA": 0.3,
            "GAMMA_01": 0.02,
            "VEGA_01": 0.8,
            "THETA_1D": -0.04,
            "CHARM": -0.01,
            "VETA": -0.02,
            "DAILY_BREAKEVEN_NVOL": 0.05,
            "ANNUAL_BREAKEVEN_NVOL": 12.6,
        },
        "B": {
            "NVOL": 80.0,
            "SPOT_NPV": 4.0,
            "FWD_NPV": 4.4,
            "SPOT_PREM": 0.000004,
            "FWD_PREM": 0.044,
            "DV01": 0.5,
            "DELTA": 0.2,
            "GAMMA": 0.1,
            "GAMMA_01": 0.01,
            "VEGA_01": 0.3,
            "THETA_1D": -0.01,
            "CHARM": -0.003,
            "VETA": -0.004,
            "DAILY_BREAKEVEN_NVOL": 0.02,
            "ANNUAL_BREAKEVEN_NVOL": 5.04,
        },
    }

    monkeypatch.setattr(value_module, "leg_metrics", lambda _ctx, leg: metrics[leg.label])

    package = [
        IRSwaptionPricable(
            option_type="payer",
            exercise_date=None,
            underlying_effective_date=None,
            underlying_maturity_date=None,
            strike=0.04,
            notional=1.0,
            label="A",
        ),
        IRSwaptionPricable(
            option_type="payer",
            exercise_date=None,
            underlying_effective_date=None,
            underlying_maturity_date=None,
            strike=0.04,
            notional=1.0,
            label="B",
        ),
    ]
    rws = [1.0, -1.0]
    fmap = IRSwaptionValueFunctionMap(context=_DummyContext(), package=package, risk_weights=rws)

    assert fmap.apply(IRSwaptionValue.NVOL) == pytest.approx(90.0)
    assert fmap.apply(IRSwaptionValue.SPREAD_NVOL) == pytest.approx(20.0)
    assert fmap.apply(IRSwaptionValue.SPOT_NPV) == pytest.approx(6.0)
    assert fmap.apply(IRSwaptionValue.FWD_NPV) == pytest.approx(6.6)
    assert fmap.apply(IRSwaptionValue.SPOT_PREM) == pytest.approx(0.06)
    assert fmap.apply(IRSwaptionValue.FWD_PREM) == pytest.approx(6.6)
    assert fmap.apply(IRSwaptionValue.DV01) == pytest.approx(0.7)
    assert fmap.apply(IRSwaptionValue.DELTA) == pytest.approx(0.3)
    assert fmap.apply(IRSwaptionValue.GAMMA) == pytest.approx(0.2)
    assert fmap.apply(IRSwaptionValue.GAMMA_01) == pytest.approx(0.01)
    assert fmap.apply(IRSwaptionValue.VEGA_01) == pytest.approx(0.5)
    assert fmap.apply(IRSwaptionValue.THETA_1D) == pytest.approx(-0.03)
    assert fmap.apply(IRSwaptionValue.CHARM) == pytest.approx(-0.007)
    assert fmap.apply(IRSwaptionValue.VETA) == pytest.approx(-0.016)
    assert fmap.apply(IRSwaptionValue.DAILY_BREAKEVEN_NVOL) == pytest.approx(0.03)
    assert fmap.apply(IRSwaptionValue.ANNUAL_BREAKEVEN_NVOL) == pytest.approx(7.56)


def test_midcurve_fair_nvol_from_synthetic_vanillas(monkeypatch):
    ex = dt.date(2027, 3, 4)
    eff = dt.date(2029, 3, 4)
    mat = dt.date(2034, 3, 4)
    mid = IRSwaptionPricable(
        option_type="payer",
        exercise_date=ex,
        underlying_effective_date=eff,
        underlying_maturity_date=mat,
        strike=0.02,
        notional=1.0,
        label="MID",
    )

    monkeypatch.setattr(value_module, "leg_forward_rate", lambda _ctx, _leg: 0.02)

    def _model_vol(_ctx, leg, strike=None):
        _ = strike
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == eff:
            return 0.005  # short vanilla (1Yx2Y style)
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == mat:
            return 0.007  # long vanilla (1Yx7Y style)
        if leg.exercise_date == eff and leg.underlying_effective_date == eff and leg.underlying_maturity_date == mat:
            return 0.010  # long-expiry vanilla (3Yx5Y style)
        raise AssertionError("Unexpected synthetic leg in test")

    monkeypatch.setattr(value_module, "leg_model_vol", _model_vol)

    class _Swap:
        def __init__(self, bps):
            self._bps = bps

        def fixedLegBPS(self):
            return self._bps

    def _build_swap(_ctx, leg, curve_handle=None):
        _ = curve_handle
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == eff:
            return _Swap(2.0)
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == mat:
            return _Swap(7.0)
        return _Swap(1.0)

    monkeypatch.setattr(value_module, "build_underlying_swap", _build_swap)

    fmap = IRSwaptionValueFunctionMap(context=_DummyContext(), package=[mid], risk_weights=[1.0])
    fair_mid = fmap.apply(IRSwaptionValue.MIDCURVE_FAIR_NVOL, rho=1.0)

    expected_sigma = math.sqrt((0.4 * 0.4 * 0.005 * 0.005) + (1.4 * 1.4 * 0.007 * 0.007) - (2.0 * 0.4 * 1.4 * 0.005 * 0.007))
    assert fair_mid == pytest.approx(expected_sigma * 10_000.0)


def test_forward_nvol_midcurve_single_leg_and_two_leg_modes(monkeypatch):
    ex = dt.date(2027, 3, 4)
    eff = dt.date(2029, 3, 4)
    mat = dt.date(2034, 3, 4)

    mid = IRSwaptionPricable(
        option_type="payer",
        exercise_date=ex,
        underlying_effective_date=eff,
        underlying_maturity_date=mat,
        strike=0.02,
        notional=1.0,
        label="MID",
    )
    short = IRSwaptionPricable(
        option_type="payer",
        exercise_date=ex,
        underlying_effective_date=ex,
        underlying_maturity_date=eff,
        strike=0.02,
        notional=1.0,
        label="SHORT",
    )
    long = IRSwaptionPricable(
        option_type="payer",
        exercise_date=eff,
        underlying_effective_date=eff,
        underlying_maturity_date=mat,
        strike=0.02,
        notional=1.0,
        label="LONG",
    )

    metrics = {
        "MID": {"NVOL": 80.0},
        "SHORT": {"NVOL": 80.0},
        "LONG": {"NVOL": 100.0},
    }
    monkeypatch.setattr(value_module, "leg_metrics", lambda _ctx, leg: metrics[leg.label])
    monkeypatch.setattr(value_module, "leg_forward_rate", lambda _ctx, _leg: 0.02)

    def _model_vol(_ctx, leg, strike=None):
        _ = strike
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == eff:
            return 0.005
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == mat:
            return 0.007
        if leg.exercise_date == eff and leg.underlying_effective_date == eff and leg.underlying_maturity_date == mat:
            return 0.010
        return 0.01

    monkeypatch.setattr(value_module, "leg_model_vol", _model_vol)

    def _tte(_ctx, leg):
        if leg.exercise_date == ex and leg.underlying_effective_date == eff:
            return 1.0  # midcurve leg
        if leg.exercise_date == eff and leg.underlying_effective_date == eff:
            return 3.0  # long-expiry vanilla
        if leg.label == "SHORT":
            return 1.0
        if leg.label == "LONG":
            return 3.0
        if leg.exercise_date == ex and leg.underlying_effective_date == ex:
            return 1.0
        return 1.0

    monkeypatch.setattr(value_module, "leg_tte_years", _tte)

    class _Swap:
        def __init__(self, bps):
            self._bps = bps

        def fixedLegBPS(self):
            return self._bps

    def _build_swap(_ctx, leg, curve_handle=None):
        _ = curve_handle
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == eff:
            return _Swap(2.0)
        if leg.exercise_date == ex and leg.underlying_effective_date == ex and leg.underlying_maturity_date == mat:
            return _Swap(7.0)
        return _Swap(1.0)

    monkeypatch.setattr(value_module, "build_underlying_swap", _build_swap)

    fmap_mid = IRSwaptionValueFunctionMap(context=_DummyContext(), package=[mid], risk_weights=[1.0])
    fwd_from_mid = fmap_mid.apply(IRSwaptionValue.FWD_NVOL)
    expected_from_mid = math.sqrt((3.0 * 0.010 * 0.010 - 1.0 * 0.008 * 0.008) / (3.0 - 1.0)) * 10_000.0
    assert fwd_from_mid == pytest.approx(expected_from_mid)

    fwd_from_mid_fair = fmap_mid.apply(IRSwaptionValue.FWD_NVOL, use_fair_midcurve=True, rho=1.0)
    fair_mid_sigma = math.sqrt((0.4 * 0.4 * 0.005 * 0.005) + (1.4 * 1.4 * 0.007 * 0.007) - (2.0 * 0.4 * 1.4 * 0.005 * 0.007))
    expected_from_mid_fair = math.sqrt((3.0 * 0.010 * 0.010 - 1.0 * fair_mid_sigma * fair_mid_sigma) / 2.0) * 10_000.0
    assert fwd_from_mid_fair == pytest.approx(expected_from_mid_fair)

    fmap_two = IRSwaptionValueFunctionMap(context=_DummyContext(), package=[short, long], risk_weights=[1.0, 1.0])
    fwd_two_leg = fmap_two.apply(IRSwaptionValue.FWD_NVOL)
    expected_two_leg = math.sqrt((3.0 * 0.010 * 0.010 - 1.0 * 0.008 * 0.008) / 2.0) * 10_000.0
    assert fwd_two_leg == pytest.approx(expected_two_leg)
