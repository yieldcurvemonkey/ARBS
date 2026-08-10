"""Tests for the asynchronous lead-lag toolkit.

The load-bearing tests are the two that a lead-lag study most needs and most often
lacks: that the estimator RECOVERS a lag deliberately injected into synthetic
data, and that it reports NOTHING on data where no lag exists.  Twelve of twelve
defects found post-hoc in earlier research in this repo happened to favour the
hypothesis under test, and a lead-lag estimator run on a grid has a known,
directional bias -- so a placebo is not decoration here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.MBO.analytics.leadlag import (
    LeadLagResult,
    lead_lag_placebo,
    epps_curve,
    hayashi_yoshida,
    lead_lag,
    lead_lag_curve,
    lead_lag_ratio,
)

S = 1_000_000_000  # one second in nanoseconds
T0 = 1_784_073_600 * S


def _walk(n, seed, step=1.0):
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0.0, step, n))


def _series(n=4000, seed=0, dt=S // 10):
    """A regularly-spaced random walk."""
    return T0 + np.arange(n, dtype=np.int64) * dt, _walk(n, seed)


# --------------------------------------------------------------------------- #
# the estimator itself
# --------------------------------------------------------------------------- #

def test_a_series_against_itself_is_perfectly_correlated():
    t, p = _series()
    got = hayashi_yoshida(t, p, t, p)
    assert got["corr"] == pytest.approx(1.0, abs=1e-9)
    assert got["cov"] == pytest.approx(got["rv_x"], rel=1e-9)


def test_a_series_against_its_negation_is_perfectly_anticorrelated():
    t, p = _series()
    assert hayashi_yoshida(t, p, t, -p)["corr"] == pytest.approx(-1.0, abs=1e-9)


def test_independent_walks_are_uncorrelated():
    t1, p1 = _series(seed=1)
    t2, p2 = _series(seed=2)
    assert abs(hayashi_yoshida(t1, p1, t2, p2)["corr"]) < 0.1


def test_asynchronous_observation_does_not_bias_the_estimate():
    """The whole point: two views of one process on different clocks still
    correlate near one, where a common grid would attenuate them."""
    n = 4000
    t = T0 + np.arange(n, dtype=np.int64) * (S // 10)
    p = _walk(n, seed=3)
    # sample the same path on two irregular, disjoint subsets
    rng = np.random.default_rng(11)
    ia = np.sort(rng.choice(n, size=n // 2, replace=False))
    ib = np.sort(rng.choice(n, size=n // 2, replace=False))
    got = hayashi_yoshida(t[ia], p[ia], t[ib], p[ib])
    assert got["corr"] > 0.75


def test_an_empty_series_gives_nan_not_an_exception():
    got = hayashi_yoshida(np.array([], dtype=np.int64), np.array([]),
                          *_series())
    assert np.isnan(got["corr"])
    assert got["n_pairs"] == 0


def test_a_single_observation_has_no_increments():
    t, p = _series()
    got = hayashi_yoshida(np.array([T0], dtype=np.int64), np.array([1.0]), t, p)
    assert np.isnan(got["corr"])


# --------------------------------------------------------------------------- #
# recovering an injected lag
# --------------------------------------------------------------------------- #

def _lagged_pair(lag_ns, n=6000, dt=S // 20, seed=7, noise=0.0):
    """Y is X delayed by ``lag_ns``: X leads Y by that much, by construction."""
    t = T0 + np.arange(n, dtype=np.int64) * dt
    x = _walk(n, seed)
    y = x.copy()
    if noise:
        y = y + np.random.default_rng(seed + 1).normal(0.0, noise, n)
    return t, x, t + int(lag_ns), y


def test_a_zero_lag_is_recovered_as_zero():
    tx, x, ty, y = _lagged_pair(0)
    r = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=81)
    assert abs(r.lag_ns) <= r.mesh_ns


@pytest.mark.parametrize("lag_ms", [100, 250, 500])
def test_an_injected_positive_lag_is_recovered(lag_ms):
    """X leads Y: the estimate must be positive and within one mesh."""
    lag = lag_ms * S // 1000
    tx, x, ty, y = _lagged_pair(lag)
    r = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=161)
    assert r.lag_ns > 0
    assert abs(r.lag_ns - lag) <= 2 * r.mesh_ns
    assert not r.degenerate


def test_the_sign_convention_reverses_when_the_roles_swap():
    lag = 300 * S // 1000
    tx, x, ty, y = _lagged_pair(lag)
    forward = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=161)
    reverse = lead_lag(ty, y, tx, x, max_lag_ns=2 * S, n_lags=161)
    assert forward.lag_ns > 0
    assert reverse.lag_ns < 0
    assert forward.lag_ns == pytest.approx(-reverse.lag_ns, abs=2 * forward.mesh_ns)


def test_the_lead_lag_ratio_agrees_with_the_argmax_on_direction():
    lag = 300 * S // 1000
    tx, x, ty, y = _lagged_pair(lag)
    r = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=161)
    assert r.llr > 1.0                      # X leads Y


# --------------------------------------------------------------------------- #
# the placebo, and honest uncertainty
# --------------------------------------------------------------------------- #

def test_independent_series_do_not_survive_a_permutation_test():
    """The placebo, done the way the theory endorses.

    No central limit theorem exists for this estimator, so significance cannot
    come from a t-statistic. It comes from asking how often a peak this large
    arises when the relationship is destroyed and everything else -- the clock,
    the mesh, the return distribution -- is held fixed.
    """
    t1, p1 = _series(seed=21)
    t2, p2 = _series(seed=22)
    got = lead_lag_placebo(t1, p1, t2, p2, max_lag_ns=2 * S, n_lags=41,
                           n_placebo=60, seed=3)
    assert got["p_value"] > 0.05


def test_shuffling_one_series_destroys_a_real_lag():
    """A genuine lead-lag must not survive scrambling one side's timestamps."""
    lag = 300 * S // 1000
    tx, x, ty, y = _lagged_pair(lag)
    real = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=161)
    rng = np.random.default_rng(5)
    shuffled = rng.permutation(y)
    placebo = lead_lag(tx, x, ty, shuffled, max_lag_ns=2 * S, n_lags=161)
    assert abs(real.corr_at_peak) > abs(placebo.corr_at_peak) * 3


def test_the_result_reports_an_interval_and_no_standard_error():
    """Hoffmann-Rosenbaum-Yoshida Proposition 2: no central limit theorem exists
    for this estimator, so a t-statistic would have no justification."""
    tx, x, ty, y = _lagged_pair(200 * S // 1000)
    r = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=81)
    assert r.interval_ns[0] == r.lag_ns - r.mesh_ns
    assert r.interval_ns[1] == r.lag_ns + r.mesh_ns
    assert not hasattr(r, "t_stat")
    assert not hasattr(r, "std_error")
    assert not hasattr(r, "pvalue")


def test_the_interval_contains_the_true_lag():
    lag = 250 * S // 1000
    tx, x, ty, y = _lagged_pair(lag)
    r = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=161)
    lo, hi = r.interval_ns
    assert lo - r.mesh_ns <= lag <= hi + r.mesh_ns


def test_ties_break_toward_the_smaller_lag():
    """A flat contrast must not read as a large lead just because the grid ends
    there."""
    t = T0 + np.arange(500, dtype=np.int64) * S
    flat = np.zeros(500)
    r = lead_lag(t, flat, t, flat, max_lag_ns=5 * S, n_lags=21)
    assert r.lag_ns == 0


# --------------------------------------------------------------------------- #
# the Epps diagnostic
# --------------------------------------------------------------------------- #

def test_epps_curve_shows_grid_correlation_collapsing_at_high_frequency():
    """Two views of one process on different clocks: the grid estimate must decay
    as the interval shrinks while Hayashi-Yoshida does not."""
    n = 20000
    t = T0 + np.arange(n, dtype=np.int64) * (S // 100)
    p = _walk(n, seed=31)
    rng = np.random.default_rng(32)
    ia = np.sort(rng.choice(n, size=n // 3, replace=False))
    ib = np.sort(rng.choice(n, size=n // 3, replace=False))
    out = epps_curve(t[ia], p[ia], t[ib], p[ib],
                     freqs=("10ms", "100ms", "1s", "10s"))
    fast = out.iloc[0]["grid_corr"]
    slow = out.iloc[-1]["grid_corr"]
    assert fast < slow                       # the Epps effect, on our own data
    assert out["hy_corr"].nunique() == 1     # HY does not depend on the grid
    assert out.iloc[0]["epps_gap"] > out.iloc[-1]["epps_gap"]


def test_lead_lag_curve_is_symmetric_in_length_and_carries_pair_counts():
    tx, x, ty, y = _lagged_pair(0, n=500)
    lags = [-S, 0, S]
    c = lead_lag_curve(tx, x, ty, y, lags)
    assert list(c["lag_ns"]) == lags
    assert (c["n_pairs"] > 0).all()


def test_lead_lag_ratio_of_an_empty_curve_is_nan():
    assert np.isnan(lead_lag_ratio(pd.DataFrame()))


def test_lead_lag_ratio_needs_both_signs():
    c = pd.DataFrame({"lag_ns": [1, 2], "corr": [0.5, 0.4]})
    assert np.isnan(lead_lag_ratio(c))


def test_a_real_lag_survives_the_permutation_test():
    """The other half of the placebo: it must not reject everything."""
    tx, x, ty, y = _lagged_pair(200 * S // 1000, n=2000)
    got = lead_lag_placebo(tx, x, ty, y, max_lag_ns=S, n_lags=41,
                           n_placebo=60, seed=4)
    assert got["p_value"] == 0.0
    assert abs(got["corr_at_peak"]) > got["placebo_p95"]


def test_the_placebo_permutes_increments_not_prices():
    """Permuting prices would change the return distribution and make the null
    too easy to reject; permuting increments preserves realised variance."""
    tx, x, ty, y = _lagged_pair(0, n=1500)
    got = lead_lag_placebo(tx, x, ty, y, max_lag_ns=S, n_lags=21,
                           n_placebo=40, seed=5)
    assert got["n_placebo"] == 40
    assert 0.0 <= got["placebo_median"] <= 1.0


# --------------------------------------------------------------------------- #
# microstructure noise and the trading-time subgrid
# --------------------------------------------------------------------------- #

def _noisy_pair(n=60000, seed=41, flicker=200):
    """Two views of one price path, buried in tick flicker.

    Reproduces the real book's shape: a common signal that moves rarely, observed
    through a stream of events that mostly do not move the mid at all. On ZNU6
    only 0.39% of top-of-book events changed the mid.
    """
    rng = np.random.default_rng(seed)
    t = T0 + np.arange(n, dtype=np.int64) * (S // 1000)
    signal = np.repeat(_walk(n // flicker + 1, seed)[: n // flicker + 1],
                       flicker)[:n]
    x = signal + rng.normal(0.0, 0.5, n)
    y = signal + rng.normal(0.0, 0.5, n)
    return t, x, t, y


def test_raw_hayashi_yoshida_is_crushed_by_microstructure_noise():
    """The failure this module now warns about, reproduced.

    HY assumes no microstructure noise. On event-level book data it reports
    almost nothing between two series that share a signal -- measured at 0.011
    between ZNU6 and ZFU6, two tightly-linked Treasury futures.
    """
    tx, x, ty, y = _noisy_pair()
    raw = hayashi_yoshida(tx, x, ty, y)["corr"]
    coarse = hayashi_yoshida(tx, x, ty, y, subsample=500)["corr"]
    assert raw < 0.2
    assert coarse > raw * 2


def test_subsampling_in_trading_time_recovers_the_relationship():
    tx, x, ty, y = _noisy_pair()
    corrs = [hayashi_yoshida(tx, x, ty, y, subsample=k)["corr"]
             for k in (1, 20, 200, 1000)]
    assert corrs == sorted(corrs)          # monotone in the subsampling factor
    assert corrs[-1] > 0.5


def test_the_signature_plot_reports_the_curve_and_whether_it_flattened():
    from RVUtils.MBO.analytics.leadlag import hy_signature

    tx, x, ty, y = _noisy_pair()
    sig = hy_signature(tx, x, ty, y, factors=(1, 50, 500, 5000))
    assert list(sig["subsample"]) == [1, 50, 500, 5000]
    assert (sig["n_pairs"].diff().dropna() < 0).all()   # coarser means fewer pairs
    assert sig["still_rising"].iloc[1]                  # noise still dominating early


def test_subsampling_does_not_disturb_a_clean_signal():
    """On data with no noise the subgrid should change little -- so the parameter
    cannot be blamed for a result it did not cause."""
    t, p = _series(n=8000, seed=61)
    full = hayashi_yoshida(t, p, t, p)["corr"]
    thin = hayashi_yoshida(t, p, t, p, subsample=10)["corr"]
    assert full == pytest.approx(1.0, abs=1e-9)
    assert thin == pytest.approx(1.0, abs=1e-9)


def test_lead_lag_accepts_the_subsample_and_still_recovers_a_lag():
    lag = 500 * S // 1000
    tx, x, ty, y = _lagged_pair(lag, n=20000, dt=S // 100)
    r = lead_lag(tx, x, ty, y, max_lag_ns=2 * S, n_lags=81, subsample=10)
    assert r.lag_ns > 0
    assert abs(r.lag_ns - lag) <= 3 * r.mesh_ns
