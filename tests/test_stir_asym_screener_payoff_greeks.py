"""Tests for the payoff and Greeks modules (Phase 8)."""

from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np
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


# --- Payoff tests ------------------------------------------------------------


def test_long_call_payoff_zero_below_strike_positive_above():
    from RVUtils.STIRAsymmetricScreener._payoff import payoff_at_grid
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    leg = OptionLeg(
        contract="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        right="C",
        strike=96.50,
        quantity=1,
    )
    grid = np.array([95.0, 96.0, 96.50, 97.0, 98.0])
    payoff = payoff_at_grid([leg], grid)
    # Payoff in ticks; intrinsic = max(F-K, 0) * 100
    np.testing.assert_allclose(payoff, [0.0, 0.0, 0.0, 50.0, 150.0])


def test_call_spread_max_at_short_strike():
    from RVUtils.STIRAsymmetricScreener._payoff import (
        max_payoff_loss,
        payoff_at_grid,
    )
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    long_leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.50, quantity=1,
    )
    short_leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=97.50, quantity=-1,
    )
    summary = max_payoff_loss([long_leg, short_leg], net_premium_ticks=10.0)
    # max payoff = (1.0 width × 100) - 10 = 90 ticks
    assert summary.max_payoff_ticks == pytest.approx(90.0)
    # max loss = -10 (lose entry premium)
    assert summary.max_loss_ticks == pytest.approx(-10.0)


def test_breakevens_for_call_spread_with_premium():
    from RVUtils.STIRAsymmetricScreener._payoff import breakevens
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    long_leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.50, quantity=1,
    )
    short_leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=97.50, quantity=-1,
    )
    bes = breakevens([long_leg, short_leg], net_premium_ticks=10.0)
    # Single breakeven at long_strike + premium-as-price = 96.50 + 0.10 = 96.60
    assert any(abs(b - 96.60) < 0.01 for b in bes)


def test_payoff_ratio_1x2_negative_beyond_short_strike():
    from RVUtils.STIRAsymmetricScreener._payoff import payoff_at_grid
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    # 1×2 put: long 1× 96.50P + short 2× 96.00P
    legs = [
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="P", strike=96.50, quantity=1,
        ),
        OptionLeg(
            contract="SFRU26", expiry=datetime.date(2026, 9, 11),
            right="P", strike=96.00, quantity=-2,
        ),
    ]
    grid = np.array([94.0, 95.0, 96.00, 96.25, 96.50, 97.0])
    payoff = payoff_at_grid(legs, grid, net_premium_ticks=0.0)
    # At F=96.0: long pays 0.5, shorts give 0; payoff = +50 ticks (max)
    assert payoff[2] > 0
    # At F=94.0 (deep ITM puts): long pays 2.5, shorts pay 4.0 each * 2 = 8.0;
    # net = 2.5 - 4.0 = -1.5 → -150 ticks (negative)
    assert payoff[0] < 0


# --- Greeks tests ------------------------------------------------------------


def test_long_call_has_positive_delta_dv01_negative_for_rates():
    from RVUtils.STIRAsymmetricScreener._greeks import compute_greeks
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile()
    # Long ATM call → positive price delta → negative DV01 (long-rate-down)
    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.30, quantity=1,
    )
    greeks = compute_greeks(legs=[leg], smile=smile, as_of_tte=0.25)
    assert greeks.delta_dv01 < 0  # benefits when rates fall


def test_long_call_has_positive_vega_negative_theta():
    from RVUtils.STIRAsymmetricScreener._greeks import compute_greeks
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile()
    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.30, quantity=1,
    )
    greeks = compute_greeks(legs=[leg], smile=smile, as_of_tte=0.25)
    assert greeks.vega_per_volpoint > 0
    assert greeks.theta_per_day < 0


def test_call_spread_has_smaller_vega_than_outright_call():
    from RVUtils.STIRAsymmetricScreener._greeks import compute_greeks
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile()
    long_leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.30, quantity=1,
    )
    short_leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=97.00, quantity=-1,
    )
    g_outright = compute_greeks(legs=[long_leg], smile=smile, as_of_tte=0.25)
    g_spread = compute_greeks(legs=[long_leg, short_leg], smile=smile, as_of_tte=0.25)
    # Spread vega ≤ outright vega (short leg subtracts non-negative vega)
    assert abs(g_spread.vega_per_volpoint) <= abs(g_outright.vega_per_volpoint) + 1e-9


def test_aged_theta_smaller_than_entry_theta():
    """Theta should be larger in magnitude as expiry approaches."""
    from RVUtils.STIRAsymmetricScreener._greeks import compute_greeks
    from RVUtils.STIRAsymmetricScreener._types import OptionLeg

    smile = _stub_smile()
    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="C", strike=96.30, quantity=1,
    )
    greeks = compute_greeks(legs=[leg], smile=smile, as_of_tte=0.30)
    # Aged Greeks shift the as-of forward in time. 3m aged ⇒ much closer to
    # expiry ⇒ |theta_aged_3m| > |theta_aged_1m| (theta accelerates near expiry).
    assert abs(greeks.theta_aged_3m) >= abs(greeks.theta_aged_1m) - 1e-9
