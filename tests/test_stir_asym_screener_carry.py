"""Tests for the carry module."""

from __future__ import annotations

import datetime

import pytest


def _stub_smile(*, forward_price: float = 96.30, time_to_expiry: float = 0.25):
    from MDP.STIRFutures.STIRFutureOptionMDP import (
        STIRFutureOptionSABRParams,
        STIRFutureOptionSABRSmile,
    )

    params = STIRFutureOptionSABRParams(
        alpha=0.005,
        beta=0.0,
        rho=-0.05,
        nu=0.6,
        forward_price=forward_price,
        forward_rate=100.0 - forward_price,
        time_to_expiry=time_to_expiry,
        expiry_date=datetime.date(2026, 9, 11),
        as_of=datetime.date(2026, 4, 28),
    )
    return STIRFutureOptionSABRSmile(
        source="STUB",
        symbol="SFRU26",
        underlying_contract="SFRU26",
        quote_timestamp=datetime.datetime(2026, 4, 28, 16, 0),
        params=params,
        points=tuple(),
    )


def test_long_call_carry_negative_aged_forward():
    """A long call has negative theta → premium decays with time."""
    from RVUtils.STIRAsymmetricScreener._carry import compute_carry
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile(time_to_expiry=0.25)
    leg = OptionLeg(
        contract="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        right="C",
        strike=96.30,
        quantity=1,
    )
    carry = compute_carry(
        legs=[leg], smile=smile, base_tte=0.25, net_premium_ticks=20.0
    )
    assert carry.carry_1w < 0
    assert carry.carry_1m < 0
    assert carry.carry_3m < 0


def test_short_outright_has_positive_carry():
    """A short call has positive theta → premium grows in our favor."""
    from RVUtils.STIRAsymmetricScreener._carry import compute_carry
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile(time_to_expiry=0.25)
    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.30, quantity=-1,
    )
    carry = compute_carry(
        legs=[leg], smile=smile, base_tte=0.25, net_premium_ticks=-20.0
    )
    # Short call: P&L moves in our favor as time decays → carry > 0
    assert carry.carry_3m > 0


def test_carry_to_expiry_intrinsic():
    """At expiry, carry_to_expiry should equal intrinsic - net_premium."""
    from RVUtils.STIRAsymmetricScreener._carry import compute_carry
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile(time_to_expiry=0.25)
    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.50, quantity=1,
    )
    carry = compute_carry(
        legs=[leg], smile=smile, base_tte=0.25, net_premium_ticks=20.0
    )
    # Strike OTM (96.30 < 96.50) → intrinsic at expiry = 0; carry to expiry = -p_now
    # carry_to_expiry = p_exp - p_now → negative (since p_now > 0, p_exp = 0)
    assert carry.carry_to_expiry < 0


def test_carry_record_has_ratio_when_premium_nonzero():
    from RVUtils.STIRAsymmetricScreener._carry import compute_carry
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile(time_to_expiry=0.25)
    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.30, quantity=1,
    )
    carry = compute_carry(
        legs=[leg], smile=smile, base_tte=0.25, net_premium_ticks=20.0
    )
    # ratio = carry_3m / |premium|
    assert abs(carry.carry_to_premium_ratio - carry.carry_3m / 20.0) < 1e-9
