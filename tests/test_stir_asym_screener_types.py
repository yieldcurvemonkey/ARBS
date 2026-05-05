"""Tests for STIRAsymmetricScreener._types."""

from __future__ import annotations

import datetime

import pytest


def test_archetype_type_has_eight_members():
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    assert {m.value for m in ArchetypeType} == {
        "wing",
        "wide_vertical",
        "risk_reversal",
        "ratio",
        "ladder",
        "conditional_curve",
        "tree",
        "condor",
    }


def test_option_leg_instantiation_and_dict_round_trip():
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    leg = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="P",
        strike=96.50,
        quantity=1,
        premium_ticks=3.0,
        open_interest=1500.0,
        volume=120.0,
        bid=2.75,
        ask=3.25,
    )
    d = leg.to_dict()
    assert d["contract"] == "SFRU6"
    assert d["right"] == "P"
    assert d["strike"] == 96.50
    assert d["quantity"] == 1
    assert d["premium_ticks"] == 3.0
    assert d["expiry"] == "2026-09-11"


def test_option_leg_is_long_short_semantics():
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    long_leg = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="C",
        strike=97.00,
        quantity=2,
    )
    short_leg = OptionLeg(
        contract="SFRU6",
        expiry=datetime.date(2026, 9, 11),
        right="C",
        strike=97.00,
        quantity=-1,
    )
    assert long_leg.is_long is True
    assert short_leg.is_long is False
    assert long_leg.abs_quantity == 2
    assert short_leg.abs_quantity == 1


def test_option_leg_is_frozen():
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    leg = OptionLeg(
        contract="ERV5",
        expiry=datetime.date(2025, 10, 31),
        right="P",
        strike=98.0625,
        quantity=1,
    )
    with pytest.raises(Exception):
        leg.strike = 99.0  # type: ignore[misc]
