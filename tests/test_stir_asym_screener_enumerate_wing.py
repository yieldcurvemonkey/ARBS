"""Tests for the wing enumerator (spec §1.1)."""

from __future__ import annotations

import datetime
from typing import Tuple

import numpy as np
import pytest


def _stub_universe_entry(
    *,
    contract: str = "SFRU26",
    forward_price: float = 96.30,
    fine_step: float = 0.0625,
):
    from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry

    # 11 strikes around forward
    strikes = tuple(forward_price + (i - 5) * fine_step for i in range(11))
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


def _stub_rnd_record(*, std_rate: float = 0.40, mean_rate: float = 3.70):
    from RVUtils.STIRAsymmetricScreener._rnd import RNDRecord

    grid = np.linspace(mean_rate - 4 * std_rate, mean_rate + 4 * std_rate, 200)
    density = np.exp(-((grid - mean_rate) ** 2) / (2 * std_rate ** 2))
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
        mode_locations=(mean_rate,),
        mode_heights=(float(density.max()),),
        mean_rate=mean_rate,
        std_rate=std_rate,
        skew=0.0,
        kurt=3.0,
        stability_flag="stable",
        extrapolation_dominated=False,
        sabr_density_on_same_grid=None,
        sabr_rnd_kl_divergence=0.0,
    )


def test_wing_enumerator_emits_otm_only():
    from RVUtils.STIRAsymmetricScreener._enumerate.wing import enumerate_wings
    from RVUtils.STIRAsymmetricScreener._types import ArchetypeType

    entry = _stub_universe_entry()
    rnd = _stub_rnd_record()
    cands = enumerate_wings(entry, rnd=rnd)
    assert cands
    for c in cands:
        assert c.archetype == ArchetypeType.WING
        assert len(c.legs) == 1
        leg = c.legs[0]
        # OTM: call strike > fwd; put strike < fwd
        if leg.right == "C":
            assert leg.strike > entry.forward_price
        else:
            assert leg.strike < entry.forward_price


def test_wing_enumerator_rejects_implied_prob_above_threshold():
    from RVUtils.STIRAsymmetricScreener._enumerate.wing import enumerate_wings

    entry = _stub_universe_entry()
    # Tight density → ATM-adjacent strikes have high implied prob
    rnd = _stub_rnd_record(std_rate=0.05)  # very tight
    cands = enumerate_wings(entry, rnd=rnd)
    # Should reject high-prob strikes; the only candidates should be far OTM
    for c in cands:
        # all kept candidates have ip ≤ 0.30; with tight density only deep tails survive
        leg = c.legs[0]
        z = abs((100.0 - leg.strike) - rnd.mean_rate) / rnd.std_rate
        assert z > 0.5  # all should be at least somewhat far


def test_wing_enumerator_rejects_far_outliers_4sigma():
    from RVUtils.STIRAsymmetricScreener._enumerate.wing import enumerate_wings
    from RVUtils.STIRAsymmetricScreener._universe import UniverseEntry

    # Universe with very wide strike grid; 4σ gate must trim
    entry = UniverseEntry(
        underlying="SFRU26",
        contract="SFRU26",
        option_root="SFR",
        expiry=datetime.date(2026, 9, 11),
        forward_price=96.30,
        atm_strike=96.30,
        strikes=tuple(96.30 + i * 0.5 for i in range(-20, 21)),  # ±10 wide
        fine_step=0.0625,
        coarse_step=0.25,
        dte_calendar=120,
    )
    rnd = _stub_rnd_record(std_rate=0.30)  # 4σ ≈ 1.20 in price space
    cands = enumerate_wings(entry, rnd=rnd)
    for c in cands:
        leg = c.legs[0]
        z = abs(leg.strike - entry.forward_price) / rnd.std_rate
        assert z <= 4.0


def test_wing_enumerator_no_rnd_falls_back_to_all_otm_strikes():
    from RVUtils.STIRAsymmetricScreener._enumerate.wing import enumerate_wings

    entry = _stub_universe_entry()
    cands = enumerate_wings(entry, rnd=None)
    # Without RND, no implied-prob filtering — all OTM strikes pass
    n_otm = sum(1 for s in entry.strikes if s != entry.forward_price)
    assert len(cands) == n_otm
