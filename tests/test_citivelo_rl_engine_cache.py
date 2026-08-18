"""Small regression tests for the Citi rateslib swaption-engine hot cache."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from MDP.IRSwaptions.CITIVELO.rl_engine import RLSwaptionEngine
from Query.IRSwaptions.pricer import IRSwaptionPricable


class _Curve:
    def __init__(self, *, forward: float, pv01: float):
        self.forward = forward
        self.pv01_value = pv01
        self.builds = 0

    def build_irswap(self, **_kwargs):
        self.builds += 1
        return object()

    def fair_rate(self, _swap):
        return self.forward

    def pv01(self, _swap):
        return self.pv01_value


class _Cube:
    is_rateslib = True

    def normal_vol(self, _expiry, _tenor, *, offset_bp):
        return 100.0 + float(offset_bp) * 0.01


def _leg(strike: float) -> IRSwaptionPricable:
    return IRSwaptionPricable(
        option_type="payer",
        exercise_date=dt.date(2027, 8, 14),
        underlying_effective_date=dt.date(2027, 8, 14),
        underlying_maturity_date=dt.date(2042, 8, 14),
        strike=strike,
        notional=1.0,
    )


def test_rl_engine_reuses_curve_inputs_for_strikes_of_same_underlying():
    curve = _Curve(forward=0.04, pv01=0.0005)
    context = SimpleNamespace(curve=curve, as_of_date=dt.date(2026, 8, 14))
    engine = RLSwaptionEngine(cube=_Cube())

    assert engine.forward(context, _leg(0.04)) == 0.04
    assert engine.annuity(context, _leg(0.0425)) == 5.0
    assert engine.normal_vol(context, _leg(0.0375)) == pytest.approx(0.009975)
    assert curve.builds == 1


def test_rl_engine_keeps_curve_snapshots_separate():
    engine = RLSwaptionEngine(cube=_Cube())
    first = _Curve(forward=0.04, pv01=0.0005)
    second = _Curve(forward=0.05, pv01=0.0006)
    as_of = dt.date(2026, 8, 14)

    assert engine.forward(SimpleNamespace(curve=first, as_of_date=as_of), _leg(0.04)) == 0.04
    assert engine.forward(SimpleNamespace(curve=second, as_of_date=as_of), _leg(0.04)) == 0.05
    assert first.builds == 1
    assert second.builds == 1
