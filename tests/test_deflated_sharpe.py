"""Tests for BT.signals.deflated_sharpe.

Validates the closed-form properties of Bailey & Lopez de Prado (2014):
  - Sharpe variance reduces to the Lo (2002) form under normality.
  - Expected max-Sharpe-under-null grows with sqrt(log N).
  - DSR probability is 0.5 when observed Sharpe equals the benchmark.
  - DSR shrinks observed Sharpe when N trials grows.
  - Vectorised grid gate produces the same probabilities as the
    per-trial function when supplied the same benchmark.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from BT.signals.deflated_sharpe import (
    EULER_MASCHERONI,
    apply_dsr_gate,
    deflated_sharpe,
    expected_max_sharpe_null,
    sharpe_estimator_variance,
    sharpe_stats,
)


# ─────────────────────────────────────────────────────────────────────
# sharpe_stats
# ─────────────────────────────────────────────────────────────────────

def test_sharpe_stats_normal_returns():
    rng = np.random.default_rng(seed=1234)
    r = rng.normal(loc=0.001, scale=0.01, size=10_000)
    stats = sharpe_stats(r)
    assert stats["T"] == 10_000
    expected_sr = r.mean() / r.std(ddof=1)
    assert stats["sr"] == pytest.approx(expected_sr, rel=1e-9)
    # Normal returns: skew ~ 0, kurt ~ 3
    assert abs(stats["skew"]) < 0.1
    assert stats["kurt"] == pytest.approx(3.0, abs=0.1)


def test_sharpe_stats_short_series():
    assert sharpe_stats([1.0]) == {"sr": 0.0, "T": 1, "skew": 0.0, "kurt": 3.0}
    assert sharpe_stats([]) == {"sr": 0.0, "T": 0, "skew": 0.0, "kurt": 3.0}


def test_sharpe_stats_zero_variance():
    r = [0.001] * 100
    stats = sharpe_stats(r)
    assert stats["sr"] == 0.0
    assert stats["T"] == 100


def test_sharpe_stats_drops_nans():
    r = [0.01, np.nan, -0.005, 0.02, np.nan, 0.01]
    stats = sharpe_stats(r)
    assert stats["T"] == 4


# ─────────────────────────────────────────────────────────────────────
# sharpe_estimator_variance
# ─────────────────────────────────────────────────────────────────────

def test_sharpe_variance_under_normality():
    """Lo (2002): for normal returns, sigma^2(SR) = (1 + 0.5 * SR^2) / (T - 1)."""
    sr = 0.05
    T = 252
    expected = (1.0 + 0.5 * sr * sr) / (T - 1)
    got = sharpe_estimator_variance(sr=sr, skew=0.0, kurt=3.0, T=T)
    assert got == pytest.approx(expected, rel=1e-12)


def test_sharpe_variance_increases_with_skew_kurt():
    base = sharpe_estimator_variance(sr=0.05, skew=0.0, kurt=3.0, T=252)
    # Negative skew + fat tails inflate the variance.
    fat = sharpe_estimator_variance(sr=0.05, skew=-1.5, kurt=8.0, T=252)
    assert fat > base


# ─────────────────────────────────────────────────────────────────────
# expected_max_sharpe_null
# ─────────────────────────────────────────────────────────────────────

def test_expected_max_sharpe_null_monotonic_in_N():
    var = 0.01
    vals = [expected_max_sharpe_null(n, var) for n in (2, 10, 100, 1_000)]
    assert vals == sorted(vals)
    assert vals[0] > 0


def test_expected_max_sharpe_null_scales_with_sqrt_var():
    a = expected_max_sharpe_null(100, sr_variance=0.01)
    b = expected_max_sharpe_null(100, sr_variance=0.04)
    # sqrt(0.04/0.01) = 2
    assert b == pytest.approx(2.0 * a, rel=1e-12)


def test_expected_max_sharpe_null_degenerate_inputs():
    assert expected_max_sharpe_null(1, sr_variance=0.01) == 0.0
    assert expected_max_sharpe_null(100, sr_variance=0.0) == 0.0
    assert expected_max_sharpe_null(100, sr_variance=-1.0) == 0.0


def test_expected_max_sharpe_null_uses_euler_constant():
    from scipy.stats import norm
    n, var = 100, 0.01
    gamma = EULER_MASCHERONI
    expected = np.sqrt(var) * (
        (1 - gamma) * norm.ppf(1 - 1 / n) + gamma * norm.ppf(1 - 1 / (n * np.e))
    )
    assert expected_max_sharpe_null(n, var) == pytest.approx(expected, rel=1e-12)


# ─────────────────────────────────────────────────────────────────────
# deflated_sharpe — single trial
# ─────────────────────────────────────────────────────────────────────

def test_dsr_prob_half_when_sr_equals_benchmark():
    rng = np.random.default_rng(seed=42)
    r = rng.normal(loc=0.001, scale=0.01, size=500)
    sr = r.mean() / r.std(ddof=1)
    out = deflated_sharpe(r, n_trials=1, sr_benchmark=sr)
    assert out["dsr_prob"] == pytest.approx(0.5, abs=1e-9)


def test_dsr_prob_above_half_when_sr_exceeds_benchmark():
    rng = np.random.default_rng(seed=42)
    r = rng.normal(loc=0.002, scale=0.01, size=1_000)
    out = deflated_sharpe(r, n_trials=1, sr_benchmark=0.0)
    assert out["dsr_prob"] > 0.95


def test_dsr_more_trials_lowers_dsr_prob():
    """As N grows, sr0 grows, so dsr_prob falls."""
    rng = np.random.default_rng(seed=7)
    r = rng.normal(loc=0.0015, scale=0.01, size=500)
    # Use a fixed variance so trial count is the only changing input.
    sr_var = 0.0005
    out_low = deflated_sharpe(r, n_trials=2, sr_variance=sr_var)
    out_high = deflated_sharpe(r, n_trials=10_000, sr_variance=sr_var)
    assert out_high["sr0"] > out_low["sr0"]
    assert out_high["dsr_prob"] < out_low["dsr_prob"]


def test_sharpe_variance_negative_skew_inflates_sigma():
    """Negative skewness inflates the Sharpe estimator variance.

    Direct closed-form check on the Mertens / Lo formula.
    """
    sr = 0.05
    T = 252
    var_sym = sharpe_estimator_variance(sr, skew=0.0, kurt=3.0, T=T)
    var_left = sharpe_estimator_variance(sr, skew=-2.0, kurt=3.0, T=T)
    var_right = sharpe_estimator_variance(sr, skew=+2.0, kurt=3.0, T=T)
    # For positive SR, negative skew increases the variance (penalises),
    # positive skew decreases it (rewards).
    assert var_left > var_sym > var_right


def test_dsr_handles_short_series_gracefully():
    out = deflated_sharpe([0.01, 0.02], n_trials=1, sr_benchmark=0.0)
    assert out["dsr_prob"] == 0.5
    assert out["T"] == 2


# ─────────────────────────────────────────────────────────────────────
# apply_dsr_gate — grid aggregation
# ─────────────────────────────────────────────────────────────────────

def test_apply_dsr_gate_basic_grid():
    rng = np.random.default_rng(seed=0)
    trials = []
    # 5 trials with varying mean returns
    means = [0.0, 0.0005, 0.001, 0.0015, 0.002]
    for m in means:
        trials.append({"daily_pnl": rng.normal(loc=m, scale=0.01, size=500).tolist()})
    df = pd.DataFrame(trials)
    out = apply_dsr_gate(df, threshold=0.95)

    assert "dsr_prob" in out.columns
    assert "dsr_pass" in out.columns
    assert len(out) == 5

    # The strongest-mean trial should have the highest Sharpe and dsr_prob.
    assert out["sr_per_period"].idxmax() == 4
    assert out["dsr_prob"].idxmax() == 4
    # The zero-drift trial must rank lowest on Sharpe.
    assert out["sr_per_period"].idxmin() == 0
    # All trials share the same benchmark sr0.
    assert out["dsr_sr0"].nunique() == 1


def test_apply_dsr_gate_threshold_filters():
    """A grid of pure-noise trials should mostly fail the 0.95 gate."""
    rng = np.random.default_rng(seed=1)
    n = 50
    rows = [
        {"daily_pnl": rng.normal(loc=0.0, scale=0.01, size=300).tolist()}
        for _ in range(n)
    ]
    df = pd.DataFrame(rows)
    out = apply_dsr_gate(df, threshold=0.95)
    # Under the null with the DSR benchmark accounting for N trials, the
    # vast majority must fail. (We allow at most ~5%.)
    pass_rate = out["dsr_pass"].mean()
    assert pass_rate <= 0.10


def test_apply_dsr_gate_signal_passes():
    """A clearly-skilled trial must clear the gate even in a noisy grid."""
    rng = np.random.default_rng(seed=2)
    rows = []
    for _ in range(40):
        rows.append({"daily_pnl": rng.normal(loc=0.0, scale=0.01, size=600).tolist()})
    # One genuinely strong trial — annualised SR ~ 3.2
    strong = rng.normal(loc=0.002, scale=0.01, size=600)
    rows.append({"daily_pnl": strong.tolist()})
    df = pd.DataFrame(rows)
    out = apply_dsr_gate(df, threshold=0.95)
    # The strong trial must pass.
    assert bool(out.iloc[-1]["dsr_pass"])


def test_apply_dsr_gate_requires_returns_col():
    df = pd.DataFrame([{"sharpe": 1.5}])
    with pytest.raises(KeyError):
        apply_dsr_gate(df, returns_col="daily_pnl")


def test_apply_dsr_gate_handles_empty_returns():
    df = pd.DataFrame([
        {"daily_pnl": []},
        {"daily_pnl": [0.01, 0.02, -0.005, 0.015, -0.01, 0.02]},
    ])
    out = apply_dsr_gate(df)
    assert not out.iloc[0]["dsr_pass"]
    assert pd.isna(out.iloc[0]["dsr_prob"])
    assert out.iloc[1]["T_obs"] == 6


def test_apply_dsr_gate_matches_per_trial_with_shared_benchmark():
    """Grid gate must agree with the per-trial function when given the same sr0."""
    rng = np.random.default_rng(seed=11)
    rows = [
        {"daily_pnl": rng.normal(loc=0.0008, scale=0.01, size=400).tolist()}
        for _ in range(6)
    ]
    df = pd.DataFrame(rows)
    out = apply_dsr_gate(df)
    sr0 = float(out["dsr_sr0"].iloc[0])

    for i, ret in enumerate(df["daily_pnl"]):
        single = deflated_sharpe(ret, n_trials=len(df), sr_benchmark=sr0)
        assert out.iloc[i]["dsr_prob"] == pytest.approx(single["dsr_prob"], rel=1e-9)
        assert out.iloc[i]["dsr_z"] == pytest.approx(single["dsr_z"], rel=1e-9)
        assert out.iloc[i]["sr_per_period"] == pytest.approx(single["sr"], rel=1e-9)
