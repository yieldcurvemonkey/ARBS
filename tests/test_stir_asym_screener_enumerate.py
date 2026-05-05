"""Tests for the remaining 7 enumerators (wide vertical, RR, ratio, ladder,
conditional curve, tree, condor)."""

from __future__ import annotations

import datetime

import numpy as np
import pytest


def _make_universe_entry(*, contract: str = "SFRU26", forward_price: float = 96.30):
    from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry

    fine_step = 0.0625
    strikes = tuple(round(forward_price + (i - 10) * fine_step, 4) for i in range(21))
    return UniverseEntry(
        underlying=contract,
        contract=contract,
        option_root="SFR",
        expiry=datetime.date(2026, 9, 11),
        forward_price=forward_price,
        atm_strike=forward_price,
        strikes=strikes,
        fine_step=fine_step,
        coarse_step=0.25,
        dte_calendar=120,
    )


def _make_rnd(*, std_rate: float = 0.40):
    from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord

    grid = np.linspace(2.0, 5.0, 200)
    density = np.exp(-((grid - 3.7) ** 2) / (2 * std_rate ** 2))
    density /= np.trapezoid(density, grid)
    cdf = np.cumsum(density) * (grid[1] - grid[0])
    cdf = cdf / cdf[-1]
    return RNDRecord(
        contract="SFRU26",
        expiry=datetime.date(2026, 9, 11),
        dte=120,
        strike_grid_rate=grid,
        n_strikes_observed=20,
        density_pdf=density,
        density_cdf=cdf,
        fed_target_bins={},
        mode_count=1,
        mode_locations=(3.7,),
        mode_heights=(float(density.max()),),
        mean_rate=3.7,
        std_rate=std_rate,
        skew=0.0,
        kurt=3.0,
        stability_flag="stable",
        extrapolation_dominated=False,
        sabr_density_on_same_grid=None,
        sabr_rnd_kl_divergence=0.0,
    )


# --- Wide vertical -----------------------------------------------------------


def test_wide_vertical_each_candidate_is_two_legs_same_right():
    from RVUtils.STIRAsymmetricScreener._enumerate.wide_vertical import (
        enumerate_wide_verticals,
    )
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    entry = _make_universe_entry()
    cands = enumerate_wide_verticals(entry)
    assert cands
    for c in cands:
        assert c.archetype == ArchetypeType.WIDE_VERTICAL
        assert len(c.legs) == 2
        rights = {l.right for l in c.legs}
        assert len(rights) == 1  # both legs same side
        # One leg long, one short
        signs = {l.quantity > 0 for l in c.legs}
        assert signs == {True, False}
        # Width ≥ 25bp
        strikes = [l.strike for l in c.legs]
        assert abs(strikes[0] - strikes[1]) >= 0.25


# --- Risk reversal -----------------------------------------------------------


def test_risk_reversal_emits_call_over_and_put_over():
    from RVUtils.STIRAsymmetricScreener._enumerate.risk_reversal import (
        enumerate_risk_reversals,
    )
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    entry = _make_universe_entry()
    cands = enumerate_risk_reversals(entry)
    assert len(cands) == 2  # call-over + put-over
    for c in cands:
        assert c.archetype == ArchetypeType.RISK_REVERSAL
        assert len(c.legs) == 2
        rights = {l.right for l in c.legs}
        assert rights == {"C", "P"}
        signs = {l.quantity > 0 for l in c.legs}
        assert signs == {True, False}


# --- Ratio -------------------------------------------------------------------


def test_ratio_each_candidate_has_two_legs_with_unequal_weights():
    from RVUtils.STIRAsymmetricScreener._enumerate.ratio import enumerate_ratios
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    entry = _make_universe_entry()
    rnd = _make_rnd(std_rate=0.20)
    cands = enumerate_ratios(entry, rnd=rnd)
    assert cands
    for c in cands:
        assert c.archetype == ArchetypeType.RATIO
        assert len(c.legs) == 2
        # Same right
        assert len({l.right for l in c.legs}) == 1
        # Unequal absolute quantities
        qty_abs = sorted({abs(l.quantity) for l in c.legs})
        assert len(qty_abs) == 2  # 1×2, 2×1, 2×3 → distinct absolute counts


# --- Ladder ------------------------------------------------------------------


def test_ladder_each_candidate_has_three_consecutive_strikes():
    from RVUtils.STIRAsymmetricScreener._enumerate.ladder import enumerate_ladders
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    entry = _make_universe_entry()
    cands = enumerate_ladders(entry)
    assert cands
    for c in cands:
        assert c.archetype == ArchetypeType.LADDER
        assert len(c.legs) == 3
        strikes = sorted(l.strike for l in c.legs)
        # Consecutive: equal step
        d1 = strikes[1] - strikes[0]
        d2 = strikes[2] - strikes[1]
        assert abs(d1 - d2) < 1e-6
        # 1× long + 1× short + 1× short pattern
        signs = sorted(l.quantity for l in c.legs)
        assert signs == [-1, -1, 1]


# --- Conditional curve -------------------------------------------------------


def test_conditional_curve_pairs_front_and_back_expiries():
    from RVUtils.STIRAsymmetricScreener._enumerate.conditional_curve import (
        enumerate_conditional_curve,
    )
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    front = _make_universe_entry(contract="SFRM26", forward_price=96.20)
    back = _make_universe_entry(contract="SFRU26", forward_price=96.30)
    # back expiry has to be > front expiry
    back_dt = back.__class__(
        underlying=back.underlying,
        contract=back.contract,
        option_root=back.option_root,
        expiry=datetime.date(2026, 9, 11),
        forward_price=back.forward_price,
        atm_strike=back.atm_strike,
        strikes=back.strikes,
        fine_step=back.fine_step,
        coarse_step=back.coarse_step,
        dte_calendar=back.dte_calendar,
    )
    front_dt = front.__class__(
        underlying=front.underlying,
        contract=front.contract,
        option_root=front.option_root,
        expiry=datetime.date(2026, 6, 12),
        forward_price=front.forward_price,
        atm_strike=front.atm_strike,
        strikes=front.strikes,
        fine_step=front.fine_step,
        coarse_step=front.coarse_step,
        dte_calendar=45,
    )
    cands = enumerate_conditional_curve(front_dt, all_entries=(front_dt, back_dt))
    assert cands
    for c in cands:
        assert c.archetype == ArchetypeType.CONDITIONAL_CURVE
        assert len(c.legs) == 2
        expiries = {l.expiry for l in c.legs}
        assert len(expiries) == 2  # different expiries


def test_conditional_curve_returns_empty_when_no_back_leg():
    from RVUtils.STIRAsymmetricScreener._enumerate.conditional_curve import (
        enumerate_conditional_curve,
    )

    front = _make_universe_entry()
    cands = enumerate_conditional_curve(front, all_entries=(front,))
    assert cands == []


# --- Tree --------------------------------------------------------------------


def test_tree_each_candidate_has_three_legs_with_broken_widths():
    from RVUtils.STIRAsymmetricScreener._enumerate.tree import enumerate_trees
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    entry = _make_universe_entry()
    cands = enumerate_trees(entry)
    assert cands
    for c in cands:
        assert c.archetype == ArchetypeType.TREE
        assert len(c.legs) == 3
        # Center is short 2x, wings are long 1x each
        weights = sorted(l.quantity for l in c.legs)
        assert weights == [-2, 1, 1]
        strikes = sorted(l.strike for l in c.legs)
        # Widths must differ (broken)
        assert abs((strikes[1] - strikes[0]) - (strikes[2] - strikes[1])) > 1e-6


# --- Condor ------------------------------------------------------------------


def test_condor_each_candidate_has_four_legs():
    from RVUtils.STIRAsymmetricScreener._enumerate.condor import enumerate_condors
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    entry = _make_universe_entry()
    rnd = _make_rnd(std_rate=0.20)
    cands = enumerate_condors(entry, rnd=rnd)
    assert cands
    for c in cands:
        assert c.archetype == ArchetypeType.CONDOR
        assert len(c.legs) == 4
        # Weights pattern: +1, -1, -1, +1
        weights = [l.quantity for l in sorted(c.legs, key=lambda l: l.strike)]
        assert weights == [1, -1, -1, 1]


# --- Dispatch table ----------------------------------------------------------


def test_enumerator_dispatch_table_covers_all_archetypes():
    from RVUtils.STIRAsymmetricScreener._enumerate import ENUMERATOR_BY_ARCHETYPE
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    assert set(ENUMERATOR_BY_ARCHETYPE.keys()) == set(ArchetypeType)
