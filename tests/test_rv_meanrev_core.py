"""Synthetic, no-network tests for the consolidated mean-reversion core.

Every fixture is either closed-form or a planted process with a known answer.
Nothing here touches the network, a database, or a data provider.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from RVUtils.mean_reversion import (
    adf_pvalue,
    bertram_thresholds,
    calibrate_ou,
    expected_passage_time,
    half_life,
    hurst_exponent,
    kalman_hedge_ratio,
    kalman_local_level,
    optimal_ou_thresholds,
    ou_band_levels,
    ou_mle,
    rolling_ar1,
    rolling_half_life,
    rolling_zscore,
    variance_ratio,
    variance_ratio_stat,
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

def ou_path(n=4000, phi=0.9, mu=3.0, sd=1.0, seed=0):
    rng = np.random.default_rng(seed)
    x = np.empty(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = mu + phi * (x[i - 1] - mu) + sd * rng.standard_normal()
    return pd.Series(x, index=pd.RangeIndex(n))


def rw_path(n=4000, sd=1.0, seed=1):
    rng = np.random.default_rng(seed)
    return pd.Series(np.cumsum(sd * rng.standard_normal(n)))


# --------------------------------------------------------------------------
# half-life / rolling AR(1)
# --------------------------------------------------------------------------

def test_half_life_recovers_planted_phi():
    phi = 0.9
    hl = half_life(ou_path(phi=phi, n=6000))
    assert hl == pytest.approx(math.log(2) / -math.log(phi), rel=0.1)


def test_half_life_of_a_random_walk_is_nan_or_enormous():
    """OLS AR(1) on a random walk has a downward small-sample bias in phi, so
    the fit is often 'mean-reverting' with a half-life of hundreds of periods.
    That is a gate on magnitude, not a NaN check -- which is exactly the trap a
    sub-1-day / multi-hundred-day half-life screen has to encode."""
    hl = half_life(rw_path(n=4000))
    assert (not np.isfinite(hl)) or hl > 200


def test_rolling_ar1_matches_calibrate_ou_on_the_same_window():
    s = ou_path(n=400, phi=0.85, mu=1.5)
    w = 120
    roll = rolling_ar1(s, w)
    assert not np.isfinite(roll["phi"].iloc[w - 1]), "only w-1 usable pairs there"
    for i in (w, 200, 399):
        # rolling_ar1 regresses y_t on y_{t-1} over the w PAIRS ending at i
        ref = calibrate_ou(s.iloc[i - w:i + 1])
        assert roll["phi"].iloc[i] == pytest.approx(ref["phi"], rel=1e-8)
        assert roll["mu"].iloc[i] == pytest.approx(ref["mu"], rel=1e-6)
        assert roll["half_life"].iloc[i] == pytest.approx(ref["half_life"], rel=1e-6)
        assert roll["sigma"].iloc[i] == pytest.approx(ref["sigma"], rel=1e-6)


def test_rolling_half_life_is_a_column_of_rolling_ar1():
    s = ou_path(n=300, phi=0.8)
    pd.testing.assert_series_equal(
        rolling_half_life(s, 100), rolling_ar1(s, 100)["half_life"].rename("half_life"))


def test_rolling_ar1_is_causal():
    """Changing a future value must not move a past fit."""
    s = ou_path(n=300, phi=0.8)
    a = rolling_ar1(s, 100)["phi"]
    s2 = s.copy()
    s2.iloc[250] += 50.0
    b = rolling_ar1(s2, 100)["phi"]
    pd.testing.assert_series_equal(a.iloc[:150], b.iloc[:150])


# --------------------------------------------------------------------------
# z-score
# --------------------------------------------------------------------------

def test_rolling_zscore_hand_computed():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = rolling_zscore(s, 3, ddof=0)
    # window [1,2,3]: mean 2, popstd sqrt(2/3)
    assert z.iloc[2] == pytest.approx((3 - 2) / math.sqrt(2 / 3))
    assert np.isnan(z.iloc[1])


def test_rolling_zscore_exclude_current_uses_the_prior_window():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = rolling_zscore(s, 3, ddof=0, exclude_current=True)
    # at t=3 the stats come from [1,2,3]; the print judged is 4
    assert z.iloc[3] == pytest.approx((4 - 2) / math.sqrt(2 / 3))


# --------------------------------------------------------------------------
# Hurst — the 2x scaling bug this replaces
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method,min_lag", [("std", 2), ("rs", 10)])
def test_hurst_random_walk_is_half(method, min_lag):
    # R/S is badly biased on very short segments, so it needs a higher min_lag.
    h = hurst_exponent(rw_path(n=6000), max_lag=100, method=method, min_lag=min_lag)
    assert h == pytest.approx(0.5, abs=0.10), f"{method} gave {h}"


def test_hurst_mean_reverting_below_half():
    assert hurst_exponent(ou_path(n=6000, phi=0.8), max_lag=100) < 0.4


def test_hurst_persistent_process_above_half():
    """I(2): std(y_{t+l} - y_t) grows like l**1.5, so H must read well above 0.5."""
    rng = np.random.default_rng(3)
    y = pd.Series(np.cumsum(np.cumsum(rng.standard_normal(4000))))
    assert hurst_exponent(y, max_lag=100) > 0.8


def test_hurst_std_estimator_ignores_a_deterministic_drift():
    """Documented trap: the drift cancels in x_{t+l} - x_t, so a straight line
    plus small noise reads H ~ 0, not H ~ 1. A regime filter that reads a
    strongly drifting fly as 'mean-reverting' is seeing this, not signal."""
    trend = pd.Series(np.arange(3000, dtype=float)
                      + np.random.default_rng(3).standard_normal(3000) * 0.1)
    assert abs(hurst_exponent(trend, max_lag=100)) < 0.1


def test_hurst_is_not_double_the_old_implementation_scale():
    """The prior closure returned 2*slope; a random walk must not read ~1.0."""
    assert hurst_exponent(rw_path(n=6000), max_lag=100) < 0.7


# --------------------------------------------------------------------------
# variance ratio
# --------------------------------------------------------------------------

def test_variance_ratio_random_walk_near_one():
    assert variance_ratio(rw_path(n=8000), k=5) == pytest.approx(1.0, abs=0.12)


def test_variance_ratio_mean_reverting_below_one():
    assert variance_ratio(ou_path(n=8000, phi=0.7), k=5) < 0.75


def test_variance_ratio_trending_above_one():
    rng = np.random.default_rng(7)
    x = np.cumsum(rng.standard_normal(8000) + 0.0)
    # positively autocorrelated increments
    d = np.convolve(rng.standard_normal(8000), np.ones(3) / 3, mode="same")
    assert variance_ratio(pd.Series(np.cumsum(d)), k=5) > 1.3
    assert np.isfinite(variance_ratio(pd.Series(x), k=5))


def test_variance_ratio_stat_does_not_reject_a_random_walk():
    out = variance_ratio_stat(rw_path(n=8000), k=5)
    assert abs(out["z"]) < 2.0
    assert out["pvalue"] > 0.05


def test_variance_ratio_stat_rejects_strong_mean_reversion():
    out = variance_ratio_stat(ou_path(n=8000, phi=0.6), k=5)
    assert out["z"] < -3.0 and out["pvalue"] < 0.01


def test_variance_ratio_too_short_is_nan():
    assert not np.isfinite(variance_ratio(pd.Series([1.0, 2.0, 3.0]), k=5))


# --------------------------------------------------------------------------
# OU MLE
# --------------------------------------------------------------------------

def test_ou_mle_recovers_planted_parameters():
    s = ou_path(n=8000, phi=0.9, mu=2.0, sd=1.0)
    out = ou_mle(s)
    assert out["mu"] == pytest.approx(2.0, abs=0.25)
    assert out["phi"] == pytest.approx(0.9, abs=0.02)
    assert out["half_life"] == pytest.approx(math.log(2) / -math.log(0.9), rel=0.15)


def test_ou_mle_close_to_ols_calibration():
    s = ou_path(n=4000, phi=0.85, mu=1.0)
    a, b = ou_mle(s), calibrate_ou(s)
    assert a["phi"] == pytest.approx(b["phi"], rel=0.02)
    assert a["half_life"] == pytest.approx(b["half_life"], rel=0.05)


def test_ou_mle_short_series_is_nan():
    assert not np.isfinite(ou_mle(pd.Series([1.0, 2.0]))["kappa"])


# --------------------------------------------------------------------------
# optimal bands
# --------------------------------------------------------------------------

def test_zero_cost_band_is_degenerate_not_a_constant():
    """The old fallback returned a*=1.0 at zero cost, above a*=0.017 at cost 0.01."""
    a0, b0 = optimal_ou_thresholds(1.0, 1.0, 0.0)
    assert a0 == 0.0 and b0 == 0.0


def test_thresholds_widen_monotonically_with_cost():
    prev = -1.0
    for c in (0.0, 0.01, 0.1, 0.5, 1.0, 2.0):
        a, _ = optimal_ou_thresholds(1.0, 1.0, c)
        assert a > prev, f"non-monotone at cost {c}"
        prev = a


def test_threshold_satisfies_the_first_order_condition():
    """Independently coded FOC on the cycle time T(a) = E[tau(-a -> +a)]."""
    import scipy.special as sp

    def T(x):
        return sum((math.sqrt(2) * x) ** k * sp.gamma(k / 2) / math.factorial(k)
                   for k in range(1, 60, 2))

    def Tp(x):
        return math.sqrt(2) * sum((math.sqrt(2) * x) ** (k - 1) * sp.gamma(k / 2)
                                  / math.factorial(k - 1) for k in range(1, 60, 2))

    for c, case, c_eff in ((0.4, "long_only", 0.4), (0.4, "symmetric", 0.2)):
        a, _ = optimal_ou_thresholds(1.0, 1.0, c, case=case)
        assert abs(T(a) - (a - c_eff) * Tp(a)) < 1e-6, f"{case} a={a}"


def test_threshold_is_the_argmax_of_profit_per_unit_time():
    """A brute-force scan must not find a better band than the FOC root."""
    c = 0.8
    a_star, _ = optimal_ou_thresholds(1.0, 1.0, c)

    def obj(a):
        return (2 * a - c) / expected_passage_time(-a, a, kappa=1.0)

    best = max(np.linspace(0.05, 4.0, 800), key=obj)
    assert obj(a_star) >= obj(best) - 1e-9


def test_expected_passage_time_matches_monte_carlo():
    """Gamma belongs in the NUMERATOR. The denominator variant gives 1.366 for
    this passage; Monte Carlo on dz = -z dt + sqrt(2) dW measures 3.042."""
    assert expected_passage_time(-1.0, 1.0, kappa=1.0) == pytest.approx(2.995, abs=0.05)
    assert expected_passage_time(-2.0, 2.0, kappa=1.0) == pytest.approx(11.854, abs=0.15)
    assert expected_passage_time(0.0, 1.0, kappa=1.0) == pytest.approx(2.093, abs=0.05)


def test_ou_band_levels_uses_kappa_and_sigma():
    """optimal_ou_thresholds ignores them by construction; the wrapper must not."""
    p_slow = {"mu": 5.0, "kappa": 0.05, "sigma": 1.0}
    p_fast = {"mu": 5.0, "kappa": 0.50, "sigma": 1.0}
    a = ou_band_levels(p_slow, cost=1.5)
    b = ou_band_levels(p_fast, cost=1.5)
    assert a["sigma_eq"] > b["sigma_eq"]
    assert a["entry_level"] != b["entry_level"]
    assert a["entry_level"] == pytest.approx(5.0 + a["entry_z"] * a["sigma_eq"])
    assert a["exit_level"] == pytest.approx(5.0 + a["exit_z"] * a["sigma_eq"])


def test_ou_band_levels_wider_when_costs_are_higher():
    p = {"mu": 0.0, "kappa": 0.1, "sigma": 1.0}
    lo = ou_band_levels(p, cost=0.5)
    hi = ou_band_levels(p, cost=3.0)
    assert hi["entry_level"] > lo["entry_level"]


def test_ou_band_levels_nan_on_bad_params():
    out = ou_band_levels({"mu": np.nan, "kappa": np.nan, "sigma": np.nan}, cost=1.0)
    assert not np.isfinite(out["entry_level"])


def test_expected_passage_time_scales_inversely_with_kappa():
    t1 = expected_passage_time(-1.0, 1.0, kappa=1.0)
    t2 = expected_passage_time(-1.0, 1.0, kappa=2.0)
    assert t1 == pytest.approx(2.0 * t2, rel=1e-9)


def test_expected_passage_time_increases_with_width():
    assert (expected_passage_time(-2.0, 2.0, kappa=1.0)
            > expected_passage_time(-1.0, 1.0, kappa=1.0))


def test_expected_passage_time_requires_m_above_a():
    assert not np.isfinite(expected_passage_time(1.0, -1.0))


def test_bertram_agrees_with_the_foc_solution():
    p = {"mu": 0.0, "kappa": 0.2, "sigma": 1.0}
    foc = ou_band_levels(p, cost=2.0)
    grid = bertram_thresholds(p, cost=2.0, grid=2000)
    assert grid["entry_z"] == pytest.approx(foc["entry_z"], abs=0.05)


def test_bertram_reports_a_positive_expected_return_when_the_band_pays():
    p = {"mu": 0.0, "kappa": 0.2, "sigma": 3.0}
    out = bertram_thresholds(p, cost=1.0)
    assert out["ret_per_period"] > 0 and out["expected_hold"] > 0


# --------------------------------------------------------------------------
# Kalman
# --------------------------------------------------------------------------

def test_kalman_local_level_tracks_a_constant():
    s = pd.Series(np.full(200, 7.0))
    out = kalman_local_level(s, q=1e-4, r=1.0)
    assert out["filtered"].iloc[-1] == pytest.approx(7.0, abs=1e-6)
    assert abs(out["z"].iloc[-1]) < 1e-6


def test_kalman_local_level_prior_is_causal():
    """prior[t] must not move when y[t] changes -- it is formed before the print."""
    s = ou_path(n=200, phi=0.9)
    a = kalman_local_level(s)
    s2 = s.copy()
    s2.iloc[150] += 100.0
    b = kalman_local_level(s2)
    assert a["prior"].iloc[150] == pytest.approx(b["prior"].iloc[150])
    assert a["prior"].iloc[151] != pytest.approx(b["prior"].iloc[151])


def test_kalman_local_level_z_flags_a_jump():
    s = pd.Series(np.zeros(300))
    s.iloc[200] = 10.0
    out = kalman_local_level(s, q=1e-6, r=1.0)
    assert out["z"].iloc[200] > 5.0


def test_kalman_hedge_ratio_recovers_a_constant_beta():
    rng = np.random.default_rng(11)
    n = 3000
    x1 = pd.Series(np.cumsum(rng.standard_normal(n)))
    x2 = pd.Series(np.cumsum(rng.standard_normal(n)))
    y = 0.7 * x1 + 0.3 * x2 + rng.standard_normal(n) * 0.01
    out = kalman_hedge_ratio(y, pd.DataFrame({"x1": x1, "x2": x2}),
                             delta=1e-6, r=1e-4)
    assert out["beta_x1"].iloc[-1] == pytest.approx(0.7, abs=0.05)
    assert out["beta_x2"].iloc[-1] == pytest.approx(0.3, abs=0.05)


def test_kalman_hedge_ratio_pred_is_causal():
    rng = np.random.default_rng(12)
    n = 400
    x = pd.DataFrame({"x1": np.cumsum(rng.standard_normal(n))})
    y = pd.Series(0.5 * x["x1"].to_numpy() + rng.standard_normal(n) * 0.1)
    a = kalman_hedge_ratio(y, x)
    y2 = y.copy()
    y2.iloc[300] += 50.0
    b = kalman_hedge_ratio(y2, x)
    assert a["pred"].iloc[300] == pytest.approx(b["pred"].iloc[300])


# --------------------------------------------------------------------------
# ADF
# --------------------------------------------------------------------------

def test_adf_pvalue_low_for_ou_high_for_random_walk():
    assert adf_pvalue(ou_path(n=1000, phi=0.85)) < 0.01
    assert adf_pvalue(rw_path(n=1000)) > 0.10


def test_adf_pvalue_nan_when_too_short():
    assert not np.isfinite(adf_pvalue(pd.Series([1.0, 2.0])))
