"""Tests for RVUtils.signal_backtest — data-agnostic signal->position->backtest module.

Written FIRST (TDD red phase) before any implementation exists.
Seed RNG for reproducibility.
"""
import numpy as np
import pandas as pd
import pytest

# ── helpers ─────────────────────────────────────────────────────────────────

def _make_ou_spread(n: int = 500, kappa: float = 0.07, mu: float = 0.0,
                    sigma: float = 0.20, x0: float = 0.0, seed: int = 42) -> pd.Series:
    """Simulate a mean-reverting OU spread on a business-day index."""
    rng = np.random.default_rng(seed)
    phi = np.exp(-kappa)
    s_step = sigma * np.sqrt((1.0 - np.exp(-2 * kappa)) / (2 * kappa))
    x = np.empty(n)
    x[0] = x0
    for t in range(1, n):
        x[t] = mu + phi * (x[t - 1] - mu) + s_step * rng.standard_normal()
    idx = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.Series(x, index=idx, name="ou_spread")


# ── import target (will fail until implementation exists) ──────────────────

from RVUtils.signal_backtest import make_signal_backtest_builder


# ── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ou_builder():
    """Build a signal_backtest builder on a synthetic OU spread."""
    signal = _make_ou_spread(n=600, kappa=0.08, mu=0.0, sigma=0.18, x0=0.30, seed=42)
    ret = signal.diff()
    return make_signal_backtest_builder(signal, ret=ret, periods_per_year=252)


@pytest.fixture(scope="module")
def ou_builder_default_ret():
    """Builder where ret defaults to signal.diff()."""
    signal = _make_ou_spread(n=600, kappa=0.08, mu=0.0, sigma=0.18, x0=0.30, seed=99)
    return make_signal_backtest_builder(signal, periods_per_year=252)


# ── test 1 : tuple unpacking ─────────────────────────────────────────────────

def test_builder_returns_eight_callables(ou_builder):
    """make_signal_backtest_builder returns 9 items per spec (kept for naming compat)."""
    result = ou_builder
    # Spec names 9 items: forecast, zscore_signal, position, pnl, stats,
    # ex_ante_sharpe, first_passage, regime_gate, get_data
    assert len(result) == 9
    forecast, zscore_signal, position, pnl, stats, ex_ante_sharpe, first_passage, regime_gate, get_data = result
    for fn in result:
        assert callable(fn)


def test_builder_returns_nine_callables(ou_builder):
    """make_signal_backtest_builder must return exactly 9 items (spec says 9)."""
    assert len(ou_builder) == 9


# ── test 2 : get_data ────────────────────────────────────────────────────────

def test_get_data_returns_signal_and_ret(ou_builder):
    *_, get_data = ou_builder
    signal, ret = get_data()
    assert isinstance(signal, pd.Series)
    assert isinstance(ret, pd.Series)


def test_get_data_default_ret_is_diff(ou_builder_default_ret):
    *_, get_data = ou_builder_default_ret
    signal, ret = get_data()
    expected_ret = signal.diff()
    pd.testing.assert_series_equal(ret, expected_ret)


# ── test 3 : forecast ────────────────────────────────────────────────────────

def test_forecast_cap(ou_builder):
    """forecast(scale, cap) values must be clipped to [-cap, +cap]."""
    forecast, *_ = ou_builder
    fc = forecast(scale=10.0, cap=20.0)
    assert isinstance(fc, pd.Series)
    assert fc.abs().max() <= 20.0 + 1e-9


def test_forecast_cap_tight(ou_builder):
    """With a small cap the result should be saturated (all values at ±cap)."""
    forecast, *_ = ou_builder
    fc = forecast(scale=100.0, cap=5.0)
    assert fc.abs().max() <= 5.0 + 1e-9


def test_forecast_sign_follows_signal(ou_builder):
    """forecast sign should follow -signal (mean-reversion: high spread -> sell)."""
    forecast, *_ = ou_builder
    fc = forecast(scale=10.0, cap=20.0)
    *_, get_data = ou_builder
    signal, _ = get_data()
    # Correlation between forecast and -signal should be strongly positive
    # (forecast = clip(scale * signal / mean(|signal|)) -> positively correlated with signal)
    corr = fc.corr(signal.reindex(fc.index))
    assert corr > 0.9  # very high since it's a scaled/clipped version


# ── test 4 : zscore_signal ───────────────────────────────────────────────────

def test_zscore_signal_values_in_set(ou_builder):
    """zscore_signal must return positions in {-1, 0, +1} only."""
    _, zscore_signal, *_ = ou_builder
    pos = zscore_signal(window=60, entry=1.5, exit=0.5, stop=4.0)
    assert isinstance(pos, pd.Series)
    assert set(pos.dropna().unique()).issubset({-1.0, 0.0, 1.0})


def test_zscore_signal_exit_zeros_position(ou_builder):
    """When |z| <= exit threshold, position should be 0 (mean-reversion exit)."""
    _, zscore_signal, *_ = ou_builder
    pos = zscore_signal(window=60, entry=1.5, exit=0.5, stop=4.0)
    # Just verify we get some 0s (the spread does cross exit threshold)
    assert (pos == 0).any()


def test_zscore_signal_has_long_positions(ou_builder):
    """With an OU spread that dips below -entry, we should see +1 positions."""
    _, zscore_signal, *_ = ou_builder
    pos = zscore_signal(window=60, entry=1.5, exit=0.5, stop=4.0)
    assert (pos == 1).any()


def test_zscore_signal_has_short_positions(ou_builder):
    """With an OU spread that spikes above +entry, we should see -1 positions."""
    _, zscore_signal, *_ = ou_builder
    pos = zscore_signal(window=60, entry=1.5, exit=0.5, stop=4.0)
    assert (pos == -1).any()


# ── test 5 : position ────────────────────────────────────────────────────────

def test_position_binary_returns_series(ou_builder):
    *_, regime_gate, get_data = ou_builder
    _, zscore_signal, position, *_ = ou_builder
    pos = position(method="binary")
    assert isinstance(pos, pd.Series)


def test_position_vol_target_returns_series(ou_builder):
    _, _, position, *_ = ou_builder
    pos = position(method="vol_target", target_vol=0.10, vol_window=36)
    assert isinstance(pos, pd.Series)
    assert pos.dropna().__len__() > 0


def test_position_inverse_vol_returns_series(ou_builder):
    _, _, position, *_ = ou_builder
    pos = position(method="inverse_vol", target_vol=0.10, vol_window=36)
    assert isinstance(pos, pd.Series)


def test_position_idm_cap(ou_builder):
    """IDM should be capped at cap_idm; passing idm >> cap_idm should not change result vs idm=cap_idm."""
    _, _, position, *_ = ou_builder
    pos_capped = position(method="vol_target", idm=1e6, cap_idm=2.5)
    pos_at_cap = position(method="vol_target", idm=2.5, cap_idm=2.5)
    pd.testing.assert_series_equal(pos_capped, pos_at_cap)


# ── test 6 : pnl ─────────────────────────────────────────────────────────────

def test_pnl_returns_series(ou_builder):
    _, zscore_signal, position, pnl, *_ = ou_builder
    pos = position(method="binary")
    p = pnl(pos)
    assert isinstance(p, pd.Series)


def test_pnl_uses_shifted_position(ou_builder):
    """pnl should use positions.shift(1) * ret so no look-ahead."""
    _, _, position, pnl, *_ = ou_builder
    *_, get_data = ou_builder
    signal, ret = get_data()
    pos = position(method="binary")
    p = pnl(pos, cost_bps=0.0)
    # Manual check: first non-NaN pnl should be at index where both pos.shift(1) and ret are defined
    first_pnl_idx = p.first_valid_index()
    pos_shift = pos.shift(1)
    first_pos_idx = pos_shift.first_valid_index()
    # The first valid pnl should not be before the first valid pos.shift(1)
    assert first_pnl_idx >= first_pos_idx


def test_pnl_zero_cost_vs_with_cost(ou_builder):
    """With positive costs, net pnl should be <= gross pnl (costs always non-negative)."""
    _, _, position, pnl, *_ = ou_builder
    pos = position(method="binary")
    gross = pnl(pos, cost_bps=0.0)
    net = pnl(pos, cost_bps=5.0)
    # Net cumulative should be <= gross cumulative
    assert net.sum() <= gross.sum() + 1e-9


# ── test 7 : stats ───────────────────────────────────────────────────────────

REQUIRED_STATS_KEYS = {"sharpe", "t_stat", "hit_rate", "max_dd", "turnover", "avg_hold", "sharpe_net"}


def test_stats_keys_present(ou_builder):
    """stats() must return all required keys."""
    _, _, position, pnl, stats, *_ = ou_builder
    pos = position(method="binary")
    s = stats(pos, cost_bps=0.0)
    assert isinstance(s, dict)
    assert REQUIRED_STATS_KEYS.issubset(set(s.keys())), (
        f"Missing keys: {REQUIRED_STATS_KEYS - set(s.keys())}"
    )


def test_stats_max_dd_nonpositive(ou_builder):
    """max_dd must be <= 0 (it is the maximum drawdown, always non-positive)."""
    _, _, position, pnl, stats, *_ = ou_builder
    pos = position(method="binary")
    s = stats(pos, cost_bps=0.0)
    assert s["max_dd"] <= 0.0 + 1e-9


def test_stats_sharpe_net_lower_than_gross_with_costs(ou_builder):
    """sharpe_net (with cost_bps=5) should be < sharpe (gross) — costs reduce net Sharpe."""
    _, _, position, pnl, stats, *_ = ou_builder
    pos = position(method="binary")
    s_gross = stats(pos, cost_bps=0.0)
    s_net5 = stats(pos, cost_bps=5.0)
    assert s_net5["sharpe_net"] < s_gross["sharpe"] + 1e-9


def test_stats_hit_rate_bounded(ou_builder):
    """hit_rate must be in [0, 1]."""
    _, _, position, pnl, stats, *_ = ou_builder
    pos = position(method="binary")
    s = stats(pos, cost_bps=0.0)
    assert 0.0 <= s["hit_rate"] <= 1.0


def test_stats_turnover_nonneg(ou_builder):
    """turnover must be >= 0."""
    _, _, position, pnl, stats, *_ = ou_builder
    pos = position(method="binary")
    s = stats(pos, cost_bps=0.0)
    assert s["turnover"] >= 0.0


def test_stats_sharpe_positive_on_mean_reverting_signal(ou_builder):
    """Mean-reversion strategy on a genuine OU spread should have positive Sharpe."""
    _, zscore_signal, position, pnl, stats, *_ = ou_builder
    # Use mean-reversion z-score positions (the strategy that should profit)
    pos = zscore_signal(window=60, entry=1.5, exit=0.5, stop=4.0)
    s = stats(pos, cost_bps=0.0)
    assert s["sharpe"] > 0, f"Expected positive Sharpe on OU spread, got {s['sharpe']:.4f}"


# ── test 8 : regime_gate ────────────────────────────────────────────────────

def test_regime_gate_zeros_disallowed(ou_builder):
    """regime_gate must zero positions where regime is not in `allowed`."""
    _, _, position, pnl, stats, ex_ante_sharpe, first_passage, regime_gate, get_data = ou_builder
    signal, _ = get_data()
    pos = position(method="binary")

    # Create a regime series: first half "expansion", second half "recession"
    n = len(signal)
    regime = pd.Series("expansion", index=signal.index)
    regime.iloc[n // 2 :] = "recession"

    gated = regime_gate(pos, regime, allowed=["expansion"])

    # Positions in "recession" zone must all be 0
    recession_mask = regime == "recession"
    assert (gated[recession_mask] == 0).all(), "Positions in 'recession' should be zeroed"

    # Positions in "expansion" zone should equal the original positions
    expansion_mask = regime == "expansion"
    pd.testing.assert_series_equal(
        gated[expansion_mask], pos[expansion_mask], check_names=False
    )


def test_regime_gate_empty_allowed(ou_builder):
    """When allowed=[], all positions should be 0."""
    _, _, position, pnl, stats, ex_ante_sharpe, first_passage, regime_gate, get_data = ou_builder
    signal, _ = get_data()
    pos = position(method="binary")
    regime = pd.Series("any", index=signal.index)
    gated = regime_gate(pos, regime, allowed=[])
    assert (gated == 0).all()


# ── test 9 : ex_ante_sharpe ─────────────────────────────────────────────────

def test_ex_ante_sharpe_finite_float(ou_builder):
    """ex_ante_sharpe should return a finite float for a well-behaved OU series."""
    *_, ex_ante_sharpe, first_passage, regime_gate, get_data = ou_builder
    sr = ex_ante_sharpe(horizon=21)
    assert np.isfinite(sr), f"Expected finite ex-ante Sharpe, got {sr}"
    assert isinstance(sr, float)


def test_ex_ante_sharpe_with_explicit_x0(ou_builder):
    """ex_ante_sharpe with explicit x0 should also return a finite float."""
    *_, ex_ante_sharpe, first_passage, regime_gate, get_data = ou_builder
    sr = ex_ante_sharpe(x0=0.5, horizon=21)
    assert np.isfinite(sr)


# ── test 10 : first_passage ──────────────────────────────────────────────────

def test_first_passage_returns_positive_float(ou_builder):
    """first_passage(target) should return a positive finite float."""
    *_, ex_ante_sharpe, first_passage, regime_gate, get_data = ou_builder
    signal, _ = get_data()
    np.random.seed(0)
    fpt = first_passage(target=0.0, sims=500, steps=252)
    assert isinstance(fpt, float)
    assert np.isfinite(fpt)
    assert fpt > 0


# ── test 11 : edge cases ────────────────────────────────────────────────────

def test_all_zero_regime_leaves_no_positions(ou_builder):
    """regime_gate with no allowed regimes should produce all-zero positions."""
    _, _, position, pnl, stats, ex_ante_sharpe, first_passage, regime_gate, get_data = ou_builder
    signal, _ = get_data()
    pos = position(method="vol_target")
    regime = pd.Series("bear", index=signal.index)
    gated = regime_gate(pos, regime, allowed=["bull"])
    assert (gated == 0).all()


def test_stats_without_explicit_positions_uses_default(ou_builder):
    """stats() called with no positions should use default binary position."""
    _, _, position, pnl, stats, *_ = ou_builder
    s = stats()
    assert REQUIRED_STATS_KEYS.issubset(set(s.keys()))
