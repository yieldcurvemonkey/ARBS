"""Tests for the gates module."""

from __future__ import annotations

import datetime

import pytest


def _make_candidate(*, archetype, legs):
    from RVUtils.STIRAsymmetricScreener._types import CandidateDef

    return CandidateDef.from_components(
        archetype=archetype,
        underlying="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        legs=tuple(legs),
    )


def _payoff(max_payoff=100.0, max_loss=-10.0):
    from RVUtils.STIRAsymmetricScreener._payoff import PayoffSummary

    return PayoffSummary(
        max_payoff_ticks=max_payoff,
        max_loss_ticks=max_loss,
        payoff_zone_price=(95.0, 96.0),
        max_loss_zone_price=(96.5, 97.5),
    )


def _greeks(vega=0.5):
    from RVUtils.STIRAsymmetricScreener._greeks import CandidateGreeks

    return CandidateGreeks(
        delta_dv01=0.0,
        gamma_per_bp_squared=0.0,
        vega_per_volpoint=vega,
        theta_per_day=-0.001,
        vega_aged_1m=vega * 0.7,
        theta_aged_1m=-0.001,
        theta_aged_3m=-0.001,
    )


def _carry():
    from RVUtils.STIRAsymmetricScreener._carry import CarryRecord

    return CarryRecord(
        carry_1w=-0.1, carry_1m=-0.5, carry_3m=-1.0,
        carry_to_expiry=-2.0, carry_to_premium_ratio=-0.05,
    )


def _signals():
    return ()


def test_gate_wing_passes_when_asymmetry_above_threshold_and_vega_positive():
    from RVUtils.STIRAsymmetricScreener._gates import gate_wing
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        OptionLeg,
        ScreenerConfig,
    )

    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="P", strike=96.50, quantity=1,
    )
    cand = _make_candidate(archetype=ArchetypeType.WING, legs=[leg])
    res = gate_wing(
        candidate=cand,
        signals=_signals(),
        payoff=_payoff(max_payoff=120.0, max_loss=-10.0),
        greeks=_greeks(vega=0.5),
        carry=_carry(),
        rnd=None,
        config=ScreenerConfig(),
    )
    assert res.passed
    assert res.failed_gates == ()


def test_gate_wing_fails_when_asymmetry_below_threshold():
    from RVUtils.STIRAsymmetricScreener._gates import gate_wing
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        OptionLeg,
        ScreenerConfig,
    )

    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="P", strike=96.50, quantity=1,
    )
    cand = _make_candidate(archetype=ArchetypeType.WING, legs=[leg])
    res = gate_wing(
        candidate=cand,
        signals=_signals(),
        payoff=_payoff(max_payoff=20.0, max_loss=-10.0),  # ratio = 2.0
        greeks=_greeks(vega=0.5),
        carry=_carry(),
        rnd=None,
        config=ScreenerConfig(),
    )
    assert not res.passed
    assert any("asymmetry_ratio" in g for g in res.failed_gates)


def test_gate_wide_vertical_fails_when_width_below_25bp():
    from RVUtils.STIRAsymmetricScreener._gates import gate_wide_vertical
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        OptionLeg,
        ScreenerConfig,
    )

    legs = [
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="C", strike=96.30, quantity=1,
        ),
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="C", strike=96.4375, quantity=-1,  # 13.75bp width
        ),
    ]
    cand = _make_candidate(archetype=ArchetypeType.WIDE_VERTICAL, legs=legs)
    res = gate_wide_vertical(
        candidate=cand,
        signals=_signals(),
        payoff=_payoff(max_payoff=10.0, max_loss=-2.0),
        greeks=_greeks(),
        carry=_carry(),
        rnd=None,
        config=ScreenerConfig(),
    )
    assert not res.passed
    assert any("width" in g for g in res.failed_gates)


def test_gate_risk_reversal_passes_when_zero_cost():
    from RVUtils.STIRAsymmetricScreener._gates import gate_risk_reversal
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        OptionLeg,
        ScreenerConfig,
    )

    legs = [
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="C", strike=96.50, quantity=1, premium_ticks=5.0,
        ),
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="P", strike=96.10, quantity=-1, premium_ticks=5.0,
        ),
    ]
    cand = _make_candidate(archetype=ArchetypeType.RISK_REVERSAL, legs=legs)
    res = gate_risk_reversal(
        candidate=cand,
        signals=_signals(),
        payoff=_payoff(max_payoff=999.0, max_loss=-999.0),  # unbounded
        greeks=_greeks(),
        carry=_carry(),
        rnd=None,
        config=ScreenerConfig(),
    )
    # Zero cost = 0 net premium ⇒ passes the |debit/credit|≤5 gate
    assert res.passed


def test_gate_ladder_fails_when_strikes_not_uniform():
    from RVUtils.STIRAsymmetricScreener._gates import gate_ladder
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        OptionLeg,
        ScreenerConfig,
    )

    legs = [
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="P", strike=96.0625, quantity=1,
        ),
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="P", strike=96.125, quantity=-1,
        ),
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="P", strike=96.50, quantity=-1,  # not uniform
        ),
    ]
    cand = _make_candidate(archetype=ArchetypeType.LADDER, legs=legs)
    res = gate_ladder(
        candidate=cand,
        signals=_signals(),
        payoff=_payoff(max_payoff=20.0, max_loss=-3.0),
        greeks=_greeks(),
        carry=_carry(),
        rnd=None,
        config=ScreenerConfig(),
    )
    assert not res.passed
    assert any("non_uniform_spacing" in g for g in res.failed_gates)


def test_gate_dispatch_table_covers_all_archetypes():
    from RVUtils.STIRAsymmetricScreener._gates import GATE_BY_ARCHETYPE
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    assert set(GATE_BY_ARCHETYPE.keys()) == set(ArchetypeType)
