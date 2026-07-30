"""Synthetic tests for the SR3 contract / cost algebra.

Every number here is hand-computable from two facts: one SR3 contract is
$25 per bp of its own rate, and crossing costs half a tick (0.25bp / $6.25) per
contract per side.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeanRev.contracts import (
    FLY_WEIGHTS_CONTRACTS,
    SR3_DV01_USD,
    PackageWeights,
    best_integer_weights,
    integer_weight_frontier,
    package_contracts,
    package_cost_bp,
    package_cost_usd,
    package_dv01_usd,
    spread_from_weights,
)


# --------------------------------------------------------------------------
# the core algebra
# --------------------------------------------------------------------------

def test_plain_fly_is_four_contracts():
    assert package_contracts(FLY_WEIGHTS_CONTRACTS) == 4.0


def test_plain_fly_round_trip_is_two_bp_not_one_and_a_half():
    """The belly is TWO contracts and you cross on both. A per-leg charge
    (3 legs x 2 x 0.25) gives 1.5bp and understates it by 25%."""
    assert package_cost_bp(FLY_WEIGHTS_CONTRACTS) == pytest.approx(2.0)
    assert package_cost_usd(FLY_WEIGHTS_CONTRACTS) == pytest.approx(50.0)


def test_dv01_per_bp_of_spread_is_invariant_to_weights():
    """The whole point of the futures case: $25/bp of the spread, always."""
    for w in [(-1, 2, -1), (-3, 7, -4), (-10, 23, -13), (1, 0, 0)]:
        assert package_dv01_usd(w) == pytest.approx(SR3_DV01_USD)


def test_cost_in_bp_is_contract_count_times_half_a_bp():
    for w in [(-1, 2, -1), (-3, 7, -4), (-4, 9, -5)]:
        assert package_cost_bp(w) == pytest.approx(package_contracts(w) * 0.5)


def test_level_neutral_cost_in_bp_equals_the_belly():
    """Wings summing to the belly => contracts = 2*belly => cost = belly bp."""
    for nf, b, nk in [(1, 2, 1), (3, 7, 4), (4, 9, 5), (5, 12, 7)]:
        w = (-nf, b, -nk)
        assert sum(abs(x) for x in w) == 2 * b
        assert package_cost_bp(w) == pytest.approx(float(b))


def test_scaling_a_package_does_not_change_cost_in_spread_sigmas():
    """cost(bp of S) and sigma(S) both scale with the belly, so the ratio is
    invariant -- you cannot make a fly cheaper by trading it bigger."""
    rng = np.random.default_rng(0)
    n = 500
    idx = pd.bdate_range("2022-01-03", periods=n)
    legs = pd.DataFrame({
        "f": 4.0 + np.cumsum(rng.standard_normal(n)) * 0.01,
        "b": 4.1 + np.cumsum(rng.standard_normal(n)) * 0.01,
        "k": 4.2 + np.cumsum(rng.standard_normal(n)) * 0.01,
    }, index=idx)
    ratios = []
    for m in (1, 2, 5):
        w = tuple(m * x for x in FLY_WEIGHTS_CONTRACTS)
        s = spread_from_weights(legs, w)
        ratios.append(package_cost_bp(w) / s.std())
    assert ratios[0] == pytest.approx(ratios[1], rel=1e-9)
    assert ratios[0] == pytest.approx(ratios[2], rel=1e-9)


def test_spread_from_weights_matches_the_fly_convention():
    legs = pd.DataFrame({"f": [5.00], "b": [5.10], "k": [5.22]})
    s = spread_from_weights(legs, FLY_WEIGHTS_CONTRACTS)
    # 2*5.10 - 5.00 - 5.22 = -0.02 pct = -2 bp
    assert float(s.iloc[0]) == pytest.approx(-2.0, abs=1e-9)


def test_spread_from_weights_rejects_a_weight_mismatch():
    legs = pd.DataFrame({"f": [1.0], "b": [2.0], "k": [3.0]})
    with pytest.raises(ValueError):
        spread_from_weights(legs, (-1, 2))


# --------------------------------------------------------------------------
# PackageWeights
# --------------------------------------------------------------------------

def test_package_properties():
    p = PackageWeights(w=(-3.0, 7.0, -4.0), label="3/-7/4")
    assert p.contracts == 14.0
    assert p.net_exposure == pytest.approx(0.0)
    assert p.belly == 7.0
    assert p.wing_split[0] == pytest.approx(3 / 7)
    assert p.wing_split[1] == pytest.approx(4 / 7)
    assert p.cost_bp() == pytest.approx(7.0)
    assert p.cost_usd() == pytest.approx(175.0)


def test_net_exposure_flags_a_directional_leak():
    """Wings that do not sum to the belly leave outright rate exposure."""
    assert PackageWeights(w=(-1.0, 2.0, -1.0)).net_exposure == pytest.approx(0.0)
    assert PackageWeights(w=(-1.0, 2.0, -0.9)).net_exposure == pytest.approx(0.1)


# --------------------------------------------------------------------------
# the integer frontier -- fidelity costs contracts
# --------------------------------------------------------------------------

def test_equal_wings_are_matched_exactly_by_the_smallest_belly():
    fr = integer_weight_frontier(0.5, 0.5, max_belly=12)
    first = fr.iloc[0]
    assert first["belly"] == 2
    assert (first["n_front"], first["n_back"]) == (1, 1)
    assert first["wing_error"] == pytest.approx(0.0)
    assert first["contracts"] == 4.0


def test_the_measured_tilt_needs_a_belly_of_seven():
    """EG and Box-Tiao both land near 0.43/0.58; 3/-7/4 is the cheapest integer
    package that gets within a percentage point of it."""
    p = best_integer_weights(0.432, 0.578, tol=0.01)
    assert p is not None
    assert p.w == (-3.0, 7.0, -4.0)
    assert p.contracts == 14.0
    assert p.cost_bp() == pytest.approx(7.0)


def test_tighter_tolerance_costs_more_contracts():
    loose = best_integer_weights(0.432, 0.578, tol=0.05, max_belly=400)
    tight = best_integer_weights(0.432, 0.578, tol=1e-4, max_belly=400)
    assert loose is not None and tight is not None
    assert tight.contracts > loose.contracts


def test_the_desks_whole_menu_is_three_packages():
    """The measured tilt (0.4277 front share) admits exactly three practical
    integer packages, and then nothing better until a belly of 166 contracts:

        belly 2 = 1/-2/1   4 contracts  2.0bp  wing error 0.0723
        belly 5 = 2/-5/3  10 contracts  5.0bp  wing error 0.0277
        belly 7 = 3/-7/4  14 contracts  7.0bp  wing error 0.00085

    3/7 = 0.42857 is within 8.5e-4 of the target, and the next belly that
    improves on it at all is 89 (38/89) -- more than 12x the contracts for a
    0.0001 gain in fidelity. So fidelity is not a dial, it is a three-way choice.
    """
    fr = integer_weight_frontier(0.432, 0.578, max_belly=200)
    f = fr[fr["is_frontier"]]
    bellies = f["belly"].tolist()
    assert bellies[:3] == [2, 5, 7]
    nxt = [b for b in bellies if b > 7][0]
    assert nxt >= 80, f"expected a large jump after belly 7, got {nxt}"
    exp = {2: (4.0, 2.0), 5: (10.0, 5.0), 7: (14.0, 7.0)}
    for b, (c, cost) in exp.items():
        r = f[f["belly"] == b].iloc[0]
        assert r["contracts"] == pytest.approx(c)
        assert r["cost_bp_of_spread"] == pytest.approx(cost)
    assert float(f.loc[f["belly"] == 7, "wing_error"].iloc[0]) < 1e-3


def test_frontier_wing_error_is_non_increasing_along_the_frontier():
    fr = integer_weight_frontier(0.432, 0.578, max_belly=40)
    f = fr[fr["is_frontier"]]
    assert (f["wing_error"].diff().dropna() < 0).all()


def test_frontier_keeps_every_package_level_neutral():
    fr = integer_weight_frontier(0.41, 0.59, max_belly=20)
    assert np.allclose(fr["net_exposure"].to_numpy(), 0.0)
    assert np.allclose((fr["n_front"] + fr["n_back"]).to_numpy(),
                       fr["belly"].to_numpy())


def test_frontier_cost_grows_with_fidelity():
    fr = integer_weight_frontier(0.432, 0.578, max_belly=40)
    f = fr[fr["is_frontier"]]
    assert (f["cost_bp_of_spread"].diff().dropna() > 0).all()


def test_degenerate_betas_return_empty():
    assert integer_weight_frontier(0.0, 0.0).empty
    assert best_integer_weights(np.nan, np.nan) is None


def test_no_package_within_tolerance_returns_none():
    # an extreme split cannot be hit within 1e-6 by a small belly
    assert best_integer_weights(0.4321357, 0.5678643, tol=1e-7, max_belly=8) is None
