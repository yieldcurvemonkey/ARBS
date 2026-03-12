import datetime as dt
import importlib

import pytest

from Query.IRSwaptions.IRSwaptionStructure import IRSwaptionStructure, IRSwaptionStructureFunctionMap

structure_module = importlib.import_module("Query.IRSwaptions.IRSwaptionStructure")


class _FakeCurve:
    @staticmethod
    def calendar_advance(d, tenor):
        token = str(tenor).upper()
        if token.endswith("Y"):
            return d + dt.timedelta(days=365 * int(token[:-1]))
        if token.endswith("M"):
            return d + dt.timedelta(days=30 * int(token[:-1]))
        if token.endswith("D"):
            return d + dt.timedelta(days=int(token[:-1]))
        raise ValueError(token)


class _FakeContext:
    def __init__(self):
        self.as_of_date = dt.date(2026, 3, 5)
        self.curve = _FakeCurve()


@pytest.fixture
def structure_map(monkeypatch):
    smap = IRSwaptionStructureFunctionMap(context=_FakeContext())
    monkeypatch.setattr(smap, "_strike_inputs", lambda **kwargs: (0.04, 0.008, 1.0))
    return smap


@pytest.mark.parametrize(
    "structure,expected_legs,extra_kwargs",
    [
        (IRSwaptionStructure.RECEIVER, 1, {}),
        (IRSwaptionStructure.PAYER, 1, {}),
        (IRSwaptionStructure.STRADDLE, 2, {}),
        (IRSwaptionStructure.STRANGLE, 2, {}),
        (IRSwaptionStructure.RECEIVER_SPREAD, 2, {}),
        (IRSwaptionStructure.PAYER_SPREAD, 2, {}),
        (IRSwaptionStructure.RECEIVER_FLY, 3, {}),
        (IRSwaptionStructure.PAYER_FLY, 3, {}),
        (IRSwaptionStructure.RECEIVER_1x2, 2, {"costless": False}),
        (IRSwaptionStructure.PAYER_1x2, 2, {"costless": False}),
        (IRSwaptionStructure.RECEIVER_LADDER, 3, {"costless": False}),
        (IRSwaptionStructure.PAYER_LADDER, 3, {"costless": False}),
        (IRSwaptionStructure.RISK_REVERSAL, 2, {}),
    ],
)
def test_structure_leg_counts_and_weights(structure_map, structure, expected_legs, extra_kwargs):
    package, rws = structure_map.apply(
        structure,
        expiry="1Y",
        tail="5Y",
        strike=0.04,
        side="buy",
        **extra_kwargs,
    )
    assert len(package) == expected_legs
    assert len(rws) == expected_legs


def test_side_sell_flips_structure_sign(structure_map):
    _, rws_buy = structure_map.apply(IRSwaptionStructure.PAYER_SPREAD, expiry="1Y", tail="5Y", strike=0.04, side="buy")
    _, rws_sell = structure_map.apply(IRSwaptionStructure.PAYER_SPREAD, expiry="1Y", tail="5Y", strike=0.04, side="sell")
    assert rws_sell == [-x for x in rws_buy]


def test_costless_1x2_solver_converges(monkeypatch, structure_map):
    # Linear toy premium function with a root close to the default guess.
    monkeypatch.setattr(
        structure_map,
        "_leg_npv",
        lambda option_type, strike, dates, notional: 0.5 + 100.0 * (0.04 - float(strike)),
    )
    package, _ = structure_map.apply(
        IRSwaptionStructure.PAYER_1x2,
        expiry="1Y",
        tail="5Y",
        strike=0.04,
        costless=True,
    )
    assert len(package) == 2
    assert package[1].strike > package[0].strike


def test_costless_solver_failure_path_has_explicit_error(structure_map):
    with pytest.raises(ValueError, match="structure=PAYER_1x2"):
        structure_map._solve_costless(
            func=lambda _k: 1.0,
            bracket=(0.03, 0.05),
            guess=0.04,
            structure_name="PAYER_1x2",
            tenor_hint="1Yx5Y",
        )


def test_payer_fly_risk_weights_regression(structure_map):
    _, rws = structure_map.apply(
        IRSwaptionStructure.PAYER_FLY,
        expiry="1Y",
        tail="5Y",
        strike=0.04,
        side="buy",
    )
    assert rws == [-1.0, 2.0, -1.0]


def test_vega_01_target_scales_package_notional(monkeypatch, structure_map):
    monkeypatch.setattr(structure_module, "leg_vega_01", lambda _ctx, leg: abs(float(leg.notional)) * 0.00032)

    package, rws = structure_map.apply(
        IRSwaptionStructure.PAYER,
        expiry="1Y",
        tail="10Y",
        strike=0.04,
        vega_01=50_000.0,
    )

    assert rws == [1.0]
    assert len(package) == 1
    assert abs(package[0].notional * 0.00032) == pytest.approx(50_000.0)


def test_delta_strike_suffix_overrides_resolution_option_type(structure_map):
    dates = (dt.date(2027, 3, 5), dt.date(2027, 3, 5), dt.date(2028, 3, 4))

    payer_delta_strike = structure_map._resolve_strike(
        "25DP",
        option_type="receiver",
        exercise_date=dates[0],
        underlying_effective_date=dates[1],
        underlying_maturity_date=dates[2],
        notional=100_000_000.0,
    )
    receiver_delta_strike = structure_map._resolve_strike(
        "25DR",
        option_type="payer",
        exercise_date=dates[0],
        underlying_effective_date=dates[1],
        underlying_maturity_date=dates[2],
        notional=100_000_000.0,
    )

    assert payer_delta_strike > 0.04
    assert receiver_delta_strike < 0.04
