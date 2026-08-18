"""Fast-path coverage for swaption normal-vol selectors."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import importlib

from Query.IRSwaptions.IRSwaptionValue import IRSwaptionValue
from Query.IRSwaptions.pricer import IRSwaptionPricable


def _leg(option_type: str, strike: float) -> IRSwaptionPricable:
    return IRSwaptionPricable(
        option_type=option_type,
        exercise_date=dt.date(2026, 1, 2),
        underlying_effective_date=dt.date(2026, 1, 2),
        underlying_maturity_date=dt.date(2036, 1, 2),
        strike=strike,
        notional=1.0,
    )


def test_nvol_uses_only_implied_normal_vol_not_full_risk_metrics(monkeypatch):
    mod = importlib.import_module("Query.IRSwaptions.IRSwaptionValue")
    context = SimpleNamespace(metadata={})
    package = [_leg("receiver", 0.04), _leg("payer", 0.04)]
    calls = []

    monkeypatch.setattr(mod, "leg_metrics", lambda *_args: (_ for _ in ()).throw(AssertionError("full metrics")))
    monkeypatch.setattr(
        mod,
        "leg_implied_normal_vol_bps",
        lambda _ctx, leg: calls.append(leg.option_type) or (100.0 if leg.option_type == "receiver" else 120.0),
    )

    vmap = mod.IRSwaptionValueFunctionMap(
        context=context, package=package, risk_weights=[1.0, 1.0]
    )
    assert vmap.apply(IRSwaptionValue.NVOL) == 110.0
    assert calls == ["receiver", "payer"]


def test_full_metric_map_memoizes_same_economic_leg_within_context(monkeypatch):
    mod = importlib.import_module("Query.IRSwaptions.IRSwaptionValue")
    context = SimpleNamespace(metadata={})
    leg = _leg("payer", 0.04)
    calls = []

    def _metrics(_ctx, priceable):
        calls.append(priceable)
        return {"SPOT_NPV": 3.0}

    monkeypatch.setattr(mod, "leg_metrics", _metrics)
    vmap = mod.IRSwaptionValueFunctionMap(context=context, package=[leg], risk_weights=[1.0])
    assert vmap.apply(IRSwaptionValue.SPOT_NPV) == 3.0
    assert vmap.apply(IRSwaptionValue.SPOT_NPV) == 3.0
    assert len(calls) == 1
