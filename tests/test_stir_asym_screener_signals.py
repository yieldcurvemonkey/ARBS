"""Tests for the signals module."""

from __future__ import annotations

import datetime
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest


def _stub_smile(*, forward_price: float = 96.30, time_to_expiry: float = 0.25):
    from MDP.STIRFutures.STIRFutureOptionMDP import (
        STIRFutureOptionSABRParams,
        STIRFutureOptionSABRSmile,
    )

    params = STIRFutureOptionSABRParams(
        alpha=0.005, beta=0.0, rho=-0.05, nu=0.6,
        forward_price=forward_price,
        forward_rate=100.0 - forward_price,
        time_to_expiry=time_to_expiry,
        expiry_date=datetime.date(2026, 9, 11),
        as_of=datetime.date(2026, 4, 28),
    )
    return STIRFutureOptionSABRSmile(
        source="STUB", symbol="SFRU26",
        underlying_contract="SFRU26",
        quote_timestamp=datetime.datetime(2026, 4, 28, 16, 0),
        params=params, points=tuple(),
    )


def _stub_path(spot=0.04, rates=(0.04, 0.04, 0.04)):
    from RVUtils.STIRAsymmetricScreener._path import FOMCPath

    meets = (
        datetime.date(2026, 6, 17),
        datetime.date(2026, 9, 16),
        datetime.date(2026, 12, 9),
    )
    cum = tuple((r - spot) * 10000.0 for r in rates)
    marg = (cum[0],) + tuple(cum[i] - cum[i - 1] for i in range(1, len(cum)))
    return FOMCPath(
        as_of=datetime.date(2026, 4, 28),
        meetings=meets,
        meeting_labels=("Jun26", "Sep26", "Dec26"),
        spot_target=spot,
        implied_meeting_rates=rates,
        cumulative_change_bp=cum,
        marginal_change_bp=marg,
    )


def test_signal_path_bias_triggered_when_fair_diverges_from_implied():
    from RVUtils.STIRAsymmetricScreener._signals import signal_path_bias
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    path = _stub_path(rates=(0.04, 0.04, 0.04))  # 0bp cumulative change
    fair = (-50.0, -75.0, -100.0)  # fair has cuts
    sig = signal_path_bias(fomc_path=path, fair_path_bp=fair, config=ScreenerConfig())
    assert sig.triggered
    assert sig.value >= 50.0


def test_signal_carry_quality_triggers_only_when_both_horizons_positive():
    from RVUtils.STIRAsymmetricScreener._carry import CarryRecord
    from RVUtils.STIRAsymmetricScreener._signals import signal_carry_quality
    from RVUtils.STIRAsymmetricScreener._types import ScreenerConfig

    cfg = ScreenerConfig()
    pos = CarryRecord(carry_1w=0.1, carry_1m=0.5, carry_3m=1.5, carry_to_expiry=2.0, carry_to_premium_ratio=0.1)
    neg = CarryRecord(carry_1w=-0.1, carry_1m=-0.5, carry_3m=-1.5, carry_to_expiry=-2.0, carry_to_premium_ratio=-0.1)
    mixed = CarryRecord(carry_1w=0.1, carry_1m=0.5, carry_3m=1.5, carry_to_expiry=-2.0, carry_to_premium_ratio=0.1)
    assert signal_carry_quality(carry=pos, config=cfg).triggered
    assert not signal_carry_quality(carry=neg, config=cfg).triggered
    assert not signal_carry_quality(carry=mixed, config=cfg).triggered


def test_signal_asymmetry_ratio_triggers_above_archetype_threshold():
    from RVUtils.STIRAsymmetricScreener._payoff import PayoffSummary
    from RVUtils.STIRAsymmetricScreener._signals import signal_asymmetry_ratio
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        CandidateDef,
        OptionLeg,
        ScreenerConfig,
    )

    leg = OptionLeg(
        contract="SFRU26", expiry=datetime.date(2026, 9, 11),
        right="P", strike=96.50, quantity=1,
    )
    cdef = CandidateDef.from_components(
        archetype=ArchetypeType.WING,
        underlying="SFRU26", expiry=datetime.date(2026, 9, 11),
        legs=(leg,),
    )
    payoff = PayoffSummary(
        max_payoff_ticks=120.0, max_loss_ticks=-10.0,
        payoff_zone_price=(95.0, 96.0), max_loss_zone_price=(96.5, 97.0),
    )
    sig = signal_asymmetry_ratio(
        candidate=cdef, payoff_summary=payoff, config=ScreenerConfig()
    )
    assert sig.triggered
    assert sig.value == pytest.approx(12.0)


def test_signal_rnd_prob_edge_compares_conditional_to_rnd():
    import datetime as dt

    from RVUtils.STIRAsymmetricScreener._payoff import PayoffSummary
    from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord
    from RVUtils.STIRAsymmetricScreener._signals import signal_rnd_prob_edge
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        CandidateDef,
        OptionLeg,
        ScreenerConfig,
    )

    grid = np.linspace(2.0, 5.0, 200)
    density = np.exp(-((grid - 3.7) ** 2) / (2 * 0.3 ** 2))
    density /= np.trapezoid(density, grid)
    cdf = np.cumsum(density) * (grid[1] - grid[0])
    cdf = cdf / cdf[-1]
    rnd = RNDRecord(
        contract="SFRU26", expiry=dt.date(2026, 9, 11), dte=120,
        strike_grid_rate=grid, n_strikes_observed=20,
        density_pdf=density, density_cdf=cdf,
        fed_target_bins={}, mode_count=1, mode_locations=(3.7,),
        mode_heights=(float(density.max()),),
        mean_rate=3.7, std_rate=0.3, skew=0.0, kurt=3.0,
        stability_flag="stable", extrapolation_dominated=False,
        sabr_density_on_same_grid=None, sabr_rnd_kl_divergence=0.0,
    )

    leg = OptionLeg(
        contract="SFRU26", expiry=dt.date(2026, 9, 11),
        right="P", strike=96.50, quantity=1,
    )
    cdef = CandidateDef.from_components(
        archetype=ArchetypeType.WING,
        underlying="SFRU26", expiry=dt.date(2026, 9, 11),
        legs=(leg,),
    )
    # Wing payoff zone is rates ≥ 3.5 (price ≤ 96.5)
    payoff = PayoffSummary(
        max_payoff_ticks=20.0, max_loss_ticks=-3.0,
        payoff_zone_price=(94.0, 96.50),
        max_loss_zone_price=(96.50, 98.0),
    )
    sig = signal_rnd_prob_edge(
        candidate=cdef, rnd=rnd, payoff_summary=payoff,
        conditional_prob_full_payoff=0.40,  # user thinks 40%
        config=ScreenerConfig(),
    )
    # RND mean=3.7, payoff zone is rates ≥ 3.5; ~75% of mass above 3.5.
    # Edge = 0.40 - 0.75 ≈ -0.35
    assert sig.triggered  # |edge| ≥ 0.10


def test_compute_all_signals_returns_one_per_kind():
    from RVUtils.STIRAsymmetricScreener._carry import CarryRecord
    from RVUtils.STIRAsymmetricScreener._market_data import STIRMarketData
    from RVUtils.STIRAsymmetricScreener._payoff import PayoffSummary
    from RVUtils.STIRAsymmetricScreener._signals import (
        SignalKind,
        compute_all_signals,
    )
    from RVUtils.STIRAsymmetricScreener._types import (
        ArchetypeType,
        CandidateDef,
        OptionLeg,
        ScreenerConfig,
    )

    md = STIRMarketData(
        as_of=datetime.date(2026, 4, 28),
        universe=tuple(),
        smiles={},
        curve_handle=None,
        curve_asof=None,
        fomc_schedule=pd.DataFrame(),
        leg_market={},
    )
    cdef = CandidateDef.from_components(
        archetype=ArchetypeType.WING,
        underlying="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        legs=(
            OptionLeg(
                contract="SFRU26", expiry=datetime.date(2026, 9, 11),
                right="P", strike=96.50, quantity=1,
            ),
        ),
    )
    payoff = PayoffSummary(
        max_payoff_ticks=10.0, max_loss_ticks=-3.0,
        payoff_zone_price=(95.0, 96.50),
        max_loss_zone_price=(96.50, 97.50),
    )
    carry = CarryRecord(
        carry_1w=-0.1, carry_1m=-0.5, carry_3m=-1.0,
        carry_to_expiry=-2.0, carry_to_premium_ratio=-0.05,
    )

    signals = compute_all_signals(
        candidate=cdef,
        md=md,
        rnd=None,
        fomc_path=_stub_path(),
        payoff_summary=payoff,
        carry=carry,
    )
    kinds = {s.kind for s in signals}
    expected = set(SignalKind)
    assert kinds == expected
