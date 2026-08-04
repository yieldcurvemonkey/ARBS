"""Synthetic, no-network tests for the intraday microstructure diagnostics.

The assertions here are derived from the models themselves -- Roll's bid-ask
bounce and the variance-ratio identity it forces -- and checked against series
CONSTRUCTED to have a known answer, rather than against whatever the
implementation happens to return on real data. Two of the three exist because
the corresponding mistake was actually made while building the intraday lab:

* the bounce correction was first applied through ``E|X| = sqrt(2/pi)*sd``, which
  produced a "corrected" opportunity LARGER than the raw one;
* the front-leg filter was applied to ``cm_slot``, which is the BELLY, silently
  selecting a different slice per spacing and an empty one at 12m.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MeanRev.diagnostics import (
    bounce_implied_variance_ratio,
    debounced_abs_move,
    roll_effective_spread,
    variance_ratio,
)
from RVUtils.MeanRev.panel import add_strip_slots, enumerate_structures


def _bounce_series(n=20000, spread=1.0, sigma=0.0, seed=0):
    """An efficient price observed through a pure Roll bounce.

    ``observed_t = efficient_t + q_t * spread/2`` with ``q_t = +-1`` iid. With
    ``sigma=0`` the efficient price is constant, so EVERY observed move is
    bounce and Roll must recover ``spread`` exactly in the limit.
    """
    rng = np.random.default_rng(seed)
    eff = np.cumsum(rng.normal(0.0, sigma, n)) if sigma > 0 else np.zeros(n)
    q = rng.choice([-1.0, 1.0], size=n)
    return pd.DataFrame({"k": eff + q * spread / 2.0})


# ---------------------------------------------------------------------------
# Roll's effective spread
# ---------------------------------------------------------------------------

def test_roll_recovers_a_known_spread_from_pure_bounce():
    """The defining case: no efficient-price movement, so the spread is all there is."""
    for spread in (0.5, 1.0, 2.0):
        s = roll_effective_spread(_bounce_series(spread=spread, sigma=0.0))
        assert s == pytest.approx(spread, rel=0.05), f"spread {spread} -> {s}"


def test_roll_recovers_the_spread_through_a_random_walk():
    """A drifting efficient price adds variance but no autocovariance.

    Roll's estimator keys on ``Cov(r_t, r_{t-1})``, and a random walk contributes
    zero to that, so the recovered spread must be unchanged by adding one.
    """
    s = roll_effective_spread(_bounce_series(spread=1.0, sigma=0.4, seed=7))
    assert s == pytest.approx(1.0, rel=0.10)


def test_roll_returns_zero_when_there_is_no_bounce():
    """A pure random walk has no negative autocovariance and so implies no spread.

    Returning 0.0 rather than NaN matters: a caller subtracting this from its own
    opportunity must never have the subtraction silently inflate the result.
    """
    rng = np.random.default_rng(3)
    w = pd.DataFrame({"k": np.cumsum(rng.normal(0, 1, 20000))})
    assert roll_effective_spread(w) == 0.0


def test_roll_needs_enough_data_before_it_will_answer():
    small = pd.DataFrame({"k": [1.0, 2.0, 1.5, 1.8]})
    assert roll_effective_spread(small) == 0.0


# ---------------------------------------------------------------------------
# the bounce correction
# ---------------------------------------------------------------------------

def test_debounced_move_is_never_larger_than_the_raw_move():
    """The property the first implementation violated.

    Removing a component of an observed move cannot make the move bigger. The
    Gaussian conversion ``E|X| = 0.798*sd`` breaks this on fat-tailed,
    zero-inflated data because ``E|X|/sd`` there is 0.59-0.69, not 0.798 -- so
    the "corrected" figure came out ABOVE the raw one.
    """
    rng = np.random.default_rng(11)
    # deliberately fat-tailed and zero-inflated, like a package on a tick grid
    m = pd.Series(rng.standard_t(3, 5000) * np.where(rng.random(5000) < 0.3, 0.0, 1.0))
    raw = float(m.abs().mean())
    for roll in (0.0, 0.25, 0.5, 1.0, 2.0):
        assert debounced_abs_move(m, roll) <= raw + 1e-12


def test_debounced_move_equals_raw_when_there_is_no_bounce():
    m = pd.Series(np.random.default_rng(5).normal(0, 2, 4000))
    assert debounced_abs_move(m, 0.0) == pytest.approx(float(m.abs().mean()))


def test_debounced_move_shrinks_monotonically_in_the_spread():
    m = pd.Series(np.random.default_rng(9).normal(0, 2, 4000))
    vals = [debounced_abs_move(m, r) for r in (0.0, 0.5, 1.0, 1.5, 2.0)]
    assert all(a >= b for a, b in zip(vals, vals[1:])), vals


def test_debounced_move_floors_at_zero_rather_than_going_imaginary():
    """A spread wider than the observed dispersion means no reachable opportunity."""
    m = pd.Series(np.random.default_rng(1).normal(0, 0.1, 2000))
    assert debounced_abs_move(m, 50.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# the variance-ratio identity
# ---------------------------------------------------------------------------

def test_pure_bounce_forces_vr2_to_equal_one_plus_rho1():
    """Roll's model is an MA(1), which pins VR(2) exactly.

    This is the check that separates artifact from signal in the real lab: if the
    measured VR(2) is reproduced by 1 + rho(1), the two-bar "mean reversion" is
    microstructure and nothing else.
    """
    w = _bounce_series(n=40000, spread=1.0, sigma=0.3, seed=13)
    d = w.diff().dropna()
    rho = float(d["k"].autocorr(lag=1))
    vr = variance_ratio(w, horizons=(2,))
    assert vr[2] == pytest.approx(1.0 + rho, abs=0.02)


def test_pure_bounce_variance_ratio_falls_monotonically_and_does_NOT_recover():
    """The correction to an intuition that is wrong and sounds right.

    It is natural to assume a fixed noise term becomes negligible at long
    horizons so ``VR(q)`` climbs back toward 1. It does not. The noise enters
    ``Var(r_q)`` ONCE regardless of ``q`` while the denominator scales with
    ``q``, so

        VR(q) = (q*sw2 + 2*su2) / (q*(sw2 + 2*su2))

    falls monotonically to ``sw2/(sw2 + 2*su2)`` -- a constant strictly below 1.
    A steadily falling variance ratio is therefore EXACTLY what pure bid-ask
    bounce looks like, and on its own is not evidence of anything else.
    """
    spread, sigma = 1.0, 0.3
    w = _bounce_series(n=200000, spread=spread, sigma=sigma, seed=17)
    vr = variance_ratio(w, horizons=(2, 6, 30, 120))
    assert vr[2] > vr[6] > vr[30] > vr[120], dict(vr)

    su2 = (spread / 2.0) ** 2
    limit = sigma ** 2 / (sigma ** 2 + 2 * su2)
    assert vr[120] == pytest.approx(limit, abs=0.05)
    assert limit < 0.5      # nowhere near 1


def test_bounce_implied_vr_matches_a_simulated_pure_bounce():
    """The benchmark must reproduce the thing it is a benchmark for."""
    spread, sigma = 1.0, 0.3
    w = _bounce_series(n=200000, spread=spread, sigma=sigma, seed=29)
    var1 = float(w.diff().stack(future_stack=True).dropna().var())
    model = bounce_implied_variance_ratio(spread, var1, horizons=(2, 6, 30, 120))
    obs = variance_ratio(w, horizons=(2, 6, 30, 120))
    for q in (2, 6, 30, 120):
        assert model[q] == pytest.approx(obs[q], abs=0.05), q


def test_genuine_reversion_falls_below_the_bounce_benchmark():
    """What actually separates signal from microstructure.

    An OU process observed through the same bounce must produce a VR profile
    BELOW the pure-bounce benchmark -- that gap is the real reversion, and it is
    the only defensible way to claim any.
    """
    rng = np.random.default_rng(31)
    n, kappa, spread = 200000, 0.05, 1.0
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = (1 - kappa) * x[t - 1] + rng.normal(0, 0.3)
    q = rng.choice([-1.0, 1.0], size=n)
    w = pd.DataFrame({"k": x + q * spread / 2.0})
    var1 = float(w.diff().stack(future_stack=True).dropna().var())
    obs = variance_ratio(w, horizons=(6, 30, 120))
    model = bounce_implied_variance_ratio(spread, var1, horizons=(6, 30, 120))
    gaps = {h: model[h] - obs[h] for h in (6, 30, 120)}
    # reverting below the benchmark at every horizon...
    assert all(g > 0 for g in gaps.values()), gaps
    # ...and the gap WIDENS with the horizon, because an OU with a ~14-step
    # half-life still looks like a random walk at q=6 and has fully reverted by
    # q=120. That growth is the signature; the level at any single q is not.
    assert gaps[6] < gaps[30] < gaps[120], gaps
    assert gaps[120] > 0.10, gaps


def test_random_walk_has_variance_ratio_one():
    rng = np.random.default_rng(23)
    w = pd.DataFrame({"k": np.cumsum(rng.normal(0, 1, 40000))})
    vr = variance_ratio(w, horizons=(2, 6, 30))
    for q in (2, 6, 30):
        assert vr[q] == pytest.approx(1.0, abs=0.15)


# ---------------------------------------------------------------------------
# cm_slot is the BELLY -- the fact that broke the front-leg filter
# ---------------------------------------------------------------------------

def _toy_strip(n_contracts=18, n_dates=40):
    """A synthetic quarterly strip: one date index, contracts every 3 months."""
    rows = []
    base = pd.Timestamp("2024-01-10")
    for d in range(n_dates):
        asof = base + pd.Timedelta(days=d)
        for i in range(n_contracts):
            start = pd.Timestamp("2024-03-20") + pd.DateOffset(months=3 * i)
            rows.append({"as_of": asof, "code": f"C{i:02d}",
                         "imm_start": start,
                         "rate_pct": 4.0 + 0.01 * i + 0.001 * d})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("spacing", [1, 2, 3, 4])
def test_cm_slot_is_the_belly_not_the_front_leg(spacing):
    """For spacing s the belly starts at 1+s, so `cm_slot <= 4` is not "front"."""
    slots = add_strip_slots(_toy_strip())
    st = enumerate_structures(slots, spacing=spacing, max_slot=16)
    assert st["cm_slot"].min() == 1 + spacing


def test_filtering_on_cm_slot_is_empty_at_12m_spacing():
    """The concrete failure: a whole spacing silently vanishing from a study.

    With spacing 4 the belly is never below 5, so `cm_slot <= 4` selects nothing
    and a 12m column disappears from every table -- without an error.
    """
    slots = add_strip_slots(_toy_strip())
    st = enumerate_structures(slots, spacing=4, max_slot=16)
    assert len(st[st["cm_slot"] <= 4]) == 0
    # the correct filter keeps the front legs it is supposed to
    front = st[st["cm_slot"] - 4 <= 4]
    assert len(front) > 0
    assert front["cm_slot"].max() <= 8


def test_front_leg_filter_is_comparable_across_spacings():
    """Every spacing must contribute the same front-leg positions, or the
    spacings are not being compared on equal terms."""
    slots = add_strip_slots(_toy_strip())
    for spacing in (1, 2, 3, 4):
        st = enumerate_structures(slots, spacing=spacing, max_slot=16)
        front = st[st["cm_slot"] - spacing <= 4]
        assert set(front["cm_slot"] - spacing) == {1, 2, 3, 4}, spacing
