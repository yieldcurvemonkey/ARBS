"""Tests for RVUtils.StatisticalFinance.

The point of most of these is not that the code runs. It is that each tool gives
the RIGHT answer on an input whose answer is known in advance -- a permutation
test that always returns 0.04 would pass a smoke test and hide every finding it
was built to make.

So: the invariants are checked exactly, the null behaviour is checked for
uniformity, and the multiple-testing procedures are checked for the property
they exist to provide (familywise error control) by simulating the null.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.StatisticalFinance import (
    empirical_rademacher_complexity,
    permutation_index,
    permute_bars,
    permute_multi_bars,
    permute_multi_prices,
    permute_price,
    permute_series_within_groups,
    permutation_test,
    picker_pvalue,
    ras_bound,
    romano_wolf,
    selection_bias_pvalue,
    sharpe_of_book,
    shared_sign_flip_null,
    standardize_returns,
    timer_pvalue,
    topk_upper_bound,
)


def _prices(n=500, seed=0):
    rng = np.random.default_rng(seed)
    return 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))


def _bars(n=200, seed=0):
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = close * np.exp(rng.normal(0, 0.002, n))
    high = np.maximum(open_, close) * np.exp(np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * np.exp(-np.abs(rng.normal(0, 0.003, n)))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.integers(100, 1000, n).astype(float)},
                        index=pd.date_range("2024-01-01", periods=n, freq="min"))


# ===========================================================================
# Permutation sampling -- exact invariants
# ===========================================================================
def test_permute_price_preserves_endpoints_and_return_multiset():
    p = _prices()
    rng = np.random.default_rng(1)
    q = permute_price(p, rng=rng)

    assert q[0] == pytest.approx(p[0], rel=0, abs=1e-12)
    # The last price is the first times exp(sum of returns), and a permutation
    # does not change a sum -- so it is preserved too, not merely in distribution.
    assert q[-1] == pytest.approx(p[-1], rel=1e-9)
    assert np.sort(np.diff(np.log(q))) == pytest.approx(np.sort(np.diff(np.log(p))), rel=1e-12)
    # and it actually moved something
    assert not np.allclose(q, p)


def test_permute_price_does_not_mutate_its_input():
    p = _prices(50)
    before = p.copy()
    permute_price(p, rng=np.random.default_rng(2))
    assert np.array_equal(p, before)


def test_permute_price_is_reproducible_from_the_generator():
    p = _prices(200)
    a = permute_price(p, rng=np.random.default_rng(7))
    b = permute_price(p, rng=np.random.default_rng(7))
    assert np.array_equal(a, b)


def test_shared_index_preserves_cross_sectional_correlation_exactly():
    rng = np.random.default_rng(3)
    base = rng.normal(0, 0.01, 400)
    p1 = 100 * np.exp(np.cumsum(base + rng.normal(0, 0.003, 400)))
    p2 = 50 * np.exp(np.cumsum(base + rng.normal(0, 0.003, 400)))
    r_before = np.corrcoef(np.diff(np.log(p1)), np.diff(np.log(p2)))[0, 1]

    q1, q2 = permute_multi_prices([p1, p2], np.random.default_rng(4))
    r_after = np.corrcoef(np.diff(np.log(q1)), np.diff(np.log(q2)))[0, 1]

    # Identical reordering of both return series leaves their correlation alone.
    assert r_after == pytest.approx(r_before, abs=1e-12)
    assert r_before > 0.5


def test_independent_permutation_destroys_correlation_but_shared_does_not():
    rng = np.random.default_rng(5)
    base = rng.normal(0, 0.01, 400)
    p1 = 100 * np.exp(np.cumsum(base))
    p2 = 100 * np.exp(np.cumsum(base))          # perfectly correlated
    q1 = permute_price(p1, rng=np.random.default_rng(11))
    q2 = permute_price(p2, rng=np.random.default_rng(12))
    r = np.corrcoef(np.diff(np.log(q1)), np.diff(np.log(q2)))[0, 1]
    assert abs(r) < 0.3          # gone, as it should be without a shared index


def test_permute_bars_keeps_bars_well_formed_and_pins_the_ends():
    b = _bars()
    q = permute_bars(b, rng=np.random.default_rng(6))

    assert list(q.columns) == list(b.columns)
    assert len(q) == len(b)
    assert q.index.equals(b.index)
    # every emitted bar is a real bar: high is the top, low is the bottom
    assert (q["high"] >= q[["open", "close"]].max(axis=1) - 1e-9).all()
    assert (q["low"] <= q[["open", "close"]].min(axis=1) + 1e-9).all()
    assert (q["high"] >= q["low"]).all()
    # the window starts where it started
    for col in ("open", "high", "low", "close"):
        assert q[col].iloc[0] == pytest.approx(b[col].iloc[0], rel=1e-12)
    # the intra-bar geometry is a permutation of the original geometry
    def geom(f):
        lg = np.log(f)
        return np.sort(np.round((lg["high"] - lg["open"]).to_numpy(), 12))
    assert geom(q) == pytest.approx(geom(b), abs=1e-9)


def test_permute_multi_bars_handles_a_dynamic_universe():
    a = _bars(120, seed=1)
    b = _bars(120, seed=2).iloc[40:]              # lists late
    out = permute_multi_bars([a, b], np.random.default_rng(9))
    assert len(out) == 2
    assert out[0].index.equals(a.index)
    assert out[1].index.equals(b.index)
    for f in out:
        assert (f["high"] >= f["low"]).all()


def test_permute_within_groups_keeps_each_group_endpoint():
    idx = pd.date_range("2024-01-01 09:00", periods=120, freq="min")
    s = pd.Series(_prices(120, seed=8), index=idx)
    day = pd.Series(idx.floor("h"), index=idx)     # four "days" of 30
    q = permute_series_within_groups(s, day, np.random.default_rng(10))

    for _k, g in s.groupby(day).groups.items():
        assert q.loc[g].iloc[0] == pytest.approx(s.loc[g].iloc[0], rel=1e-12)
        assert q.loc[g].iloc[-1] == pytest.approx(s.loc[g].iloc[-1], rel=1e-9)
    assert not np.allclose(q.to_numpy(), s.to_numpy())


# ===========================================================================
# Monte Carlo permutation tests -- null behaviour
# ===========================================================================
def test_pvalue_resolution_is_bounded_below_by_one_over_m_plus_one():
    """A test with M draws cannot report more confidence than M draws bought."""
    rng = np.random.default_rng(0)
    r = timer_pvalue(pnl=np.full(50, 1.0), side=np.ones(50), draws=99, rng=rng)
    assert r.p_value >= 1.0 / (99 + 1) - 1e-12
    assert r.resolution == pytest.approx(0.01)


def test_timer_pvalue_is_uniform_under_the_null():
    """No timing skill -> p-values spread over [0,1] with mean about a half."""
    ps = []
    for seed in range(40):
        rng = np.random.default_rng(seed)
        move = rng.normal(0, 1, 200)
        side = rng.choice([-1.0, 1.0], 200)           # sides chosen blind
        ps.append(timer_pvalue(side * move, side, draws=199, rng=rng).p_value)
    ps = np.array(ps)
    assert 0.35 < ps.mean() < 0.65
    assert (ps < 0.05).mean() < 0.20                   # not systematically tiny


def test_timer_pvalue_detects_real_timing_skill():
    """Sides chosen WITH knowledge of the move must be flagged."""
    rng = np.random.default_rng(1)
    move = rng.normal(0, 1, 300)
    side = np.sign(move)                               # perfect foresight
    r = timer_pvalue(side * move, side, draws=499, rng=rng)
    assert r.p_value <= 0.01
    assert r.observed > r.null_mean


def test_picker_pvalue_detects_selection_skill():
    rng = np.random.default_rng(2)
    T, N = 250, 6
    rets = pd.DataFrame(rng.normal(0, 0.01, (T, N)), columns=list("abcdef"))
    # put all the weight on whichever asset actually wins that day
    w = np.zeros((T, N))
    w[np.arange(T), rets.to_numpy().argmax(axis=1)] = 1.0
    weights = pd.DataFrame(w, columns=rets.columns)
    r = picker_pvalue(rets, weights, draws=199, rng=rng)
    assert r.p_value <= 0.02


def test_permutation_test_counts_failed_draws_instead_of_hiding_them():
    calls = {"n": 0}

    def stat(x):
        return float(np.mean(x))

    def permuter(rng, x):
        calls["n"] += 1
        if calls["n"] % 3 == 0:
            raise ValueError("boom")
        return {"x": rng.permutation(x)}

    r = permutation_test(stat, permuter, draws=30, rng=np.random.default_rng(0),
                         x=np.arange(10.0))
    assert r.n_failed == 10
    assert r.n_draws == 20
    assert r.p_value == pytest.approx((1 + 20) / 21)   # a permuted mean always ties


def test_sharpe_of_book_is_not_annualised():
    x = np.array([1.0, -1.0, 1.0, -1.0, 2.0])
    assert sharpe_of_book(x) == pytest.approx(x.mean() / x.std(ddof=1))
    assert sharpe_of_book([1.0]) == 0.0


# ===========================================================================
# Strategy families
# ===========================================================================
def test_selection_bias_pvalue_uses_the_family_maximum():
    obs = np.array([2.0, 1.0, 0.5])
    # a null in which some draw's BEST always beats the observed best
    null = np.tile(np.array([3.0, 0.0, 0.0]), (99, 1))
    assert selection_bias_pvalue(obs, null) == pytest.approx(1.0)

    null2 = np.tile(np.array([0.1, 0.0, 0.0]), (99, 1))
    assert selection_bias_pvalue(obs, null2) == pytest.approx(1 / 100)


def test_selection_bias_is_stricter_than_a_single_strategy_test():
    """The whole reason the tool exists: searching costs you significance."""
    rng = np.random.default_rng(3)
    M, n = 500, 200
    null = rng.normal(0, 1, (M, n))
    obs = np.full(n, 2.2)
    single = (1 + int((null[:, 0] >= 2.2).sum())) / (M + 1)
    family = selection_bias_pvalue(obs, null)
    assert family > single
    assert single < 0.05 < family


def test_topk_upper_bound_is_monotone_and_matches_at_rank_one():
    rng = np.random.default_rng(4)
    null = rng.normal(0, 1, (400, 20))
    obs = rng.normal(0, 1, 20)
    tb = topk_upper_bound(obs, null)
    assert tb.loc[1, "p_upper_bound"] == pytest.approx(selection_bias_pvalue(obs, null))
    assert (np.diff(tb["p_upper_bound"].to_numpy()) >= -1e-12).all()


def test_romano_wolf_adjusted_pvalues_are_monotone():
    rng = np.random.default_rng(5)
    null = rng.normal(0, 1, (600, 25))
    obs = rng.normal(0.3, 1, 25)
    res = romano_wolf(obs, null)
    p = res.table["p_adjusted"].to_numpy()
    assert (np.diff(p) >= -1e-12).all()
    assert (p >= res.table["p_raw"].to_numpy() - 1e-12).all()


def test_romano_wolf_is_at_least_as_powerful_as_the_upper_bound():
    rng = np.random.default_rng(6)
    null = rng.normal(0, 1, (800, 30))
    obs = np.concatenate([rng.normal(3.0, 0.1, 3), rng.normal(0, 1, 27)])
    rw = romano_wolf(obs, null).table
    ub = topk_upper_bound(obs, null)
    # stepdown shrinks the competing set, so it can only be smaller or equal
    assert (rw["p_adjusted"].to_numpy() <= ub["p_upper_bound"].to_numpy() + 1e-12).all()


def test_romano_wolf_controls_familywise_error_under_the_null():
    """The property it exists for: with NOTHING real, it rejects ~alpha of the time.

    This is the known-answer test for the whole module. A procedure that fails
    it is not conservative-but-useful, it is broken in the direction that
    manufactures discoveries.
    """
    alpha, experiments, rejections = 0.10, 300, 0
    rng = np.random.default_rng(7)
    T, n, M = 60, 12, 199
    for _ in range(experiments):
        data = rng.normal(0, 1, (T, n))                # no strategy has an edge
        obs = data.mean(axis=0) / data.std(axis=0, ddof=1)
        null = np.empty((M, n))
        for i in range(M):
            flipped = data * rng.choice([-1.0, 1.0], size=(T, 1))
            null[i] = flipped.mean(axis=0) / flipped.std(axis=0, ddof=1)
        if romano_wolf(obs, null, alpha=alpha).n_rejected > 0:
            rejections += 1
    fwer = rejections / experiments
    assert fwer <= alpha + 0.06, f"familywise error {fwer:.3f} exceeds alpha={alpha}"


# ===========================================================================
# Rademacher anti-serum
# ===========================================================================
def test_standardize_makes_the_column_mean_the_sharpe():
    rng = np.random.default_rng(8)
    x = rng.normal(0.05, 1.0, (500, 3))
    z = standardize_returns(x)
    assert z.mean(axis=0) == pytest.approx(x.mean(axis=0) / x.std(axis=0, ddof=1), rel=1e-9)


def test_rademacher_complexity_grows_with_the_number_of_independent_strategies():
    """More independent things tried -> more of any noise pattern is fittable."""
    rng = np.random.default_rng(9)
    T = 300
    small = standardize_returns(rng.normal(0, 1, (T, 2)))
    large = standardize_returns(rng.normal(0, 1, (T, 200)))
    r_small = empirical_rademacher_complexity(small, draws=300, rng=np.random.default_rng(1))
    r_large = empirical_rademacher_complexity(large, draws=300, rng=np.random.default_rng(1))
    assert r_large > r_small > 0


def test_rademacher_complexity_charges_a_correlated_family_less():
    """The reason to prefer RAS to a count-based haircut: 200 copies of one
    strategy are not 200 strategies."""
    rng = np.random.default_rng(10)
    T = 300
    base = rng.normal(0, 1, (T, 1))
    clones = standardize_returns(np.repeat(base, 200, axis=1)
                                 + rng.normal(0, 0.01, (T, 200)))
    independent = standardize_returns(rng.normal(0, 1, (T, 200)))
    r_clone = empirical_rademacher_complexity(clones, draws=400, rng=np.random.default_rng(2))
    r_indep = empirical_rademacher_complexity(independent, draws=400, rng=np.random.default_rng(2))
    assert r_clone < r_indep


def test_ras_terms_match_the_closed_form():
    import math
    rng = np.random.default_rng(11)
    T, N, delta = 400, 7, 0.05
    x = rng.normal(0, 1, (T, N))
    res = ras_bound(x, delta=delta, draws=200, rng=np.random.default_rng(3))
    assert res.sampling_error == pytest.approx(3 * math.sqrt(2 * math.log(2 / delta) / T))
    assert res.multiple_testing == pytest.approx(math.sqrt(2 * math.log(2 * N / delta) / T))
    assert res.complexity_penalty == pytest.approx(2 * res.rademacher)
    assert res.bound == pytest.approx(res.sharpe - res.haircut)


def test_ras_rejects_pure_noise_and_can_accept_a_strong_signal():
    rng = np.random.default_rng(12)
    T = 4000
    noise = rng.normal(0, 1, (T, 50))
    assert (ras_bound(noise, draws=200, rng=np.random.default_rng(4)).bound <= 0).all()

    strong = rng.normal(0.30, 1.0, (T, 3))     # Sharpe ~0.30 per period
    res = ras_bound(strong, draws=200, rng=np.random.default_rng(5))
    assert (res.bound > 0).any(), res.terms().to_dict()


def test_ras_haircut_grows_with_the_size_of_the_family():
    rng = np.random.default_rng(13)
    T = 800
    few = ras_bound(rng.normal(0, 1, (T, 3)), draws=200, rng=np.random.default_rng(6))
    many = ras_bound(rng.normal(0, 1, (T, 400)), draws=200, rng=np.random.default_rng(6))
    assert many.haircut > few.haircut
    assert many.multiple_testing > few.multiple_testing


def test_shared_sign_flip_null_moves_the_statistic_where_a_permutation_cannot():
    """A row permutation leaves every column Sharpe untouched -- only flips work."""
    rng = np.random.default_rng(14)
    x = rng.normal(0.1, 1.0, (200, 5))
    obs = x.mean(axis=0) / x.std(axis=0, ddof=1)

    permuted = rng.permutation(x, axis=0)
    assert (permuted.mean(axis=0) / permuted.std(axis=0, ddof=1)) == pytest.approx(obs)

    null = shared_sign_flip_null(x, draws=300, rng=np.random.default_rng(15))
    assert null.shape == (300, 5)
    assert np.nanstd(null[:, 0]) > 0.01


def test_shared_sign_flip_null_preserves_cross_strategy_correlation():
    """Two near-identical configs must stay near-identical in the null, or the
    family maximum is inflated and every family p-value gets too forgiving."""
    rng = np.random.default_rng(16)
    base = rng.normal(0.05, 1.0, (300, 1))
    x = np.hstack([base, base + rng.normal(0, 0.01, (300, 1))])
    null = shared_sign_flip_null(x, draws=400, rng=np.random.default_rng(17))
    assert np.corrcoef(null[:, 0], null[:, 1])[0, 1] > 0.99


def test_shared_sign_flip_null_handles_missing_trades():
    rng = np.random.default_rng(18)
    x = rng.normal(0, 1, (100, 3))
    x[:40, 1] = np.nan                      # config 1 only traded later
    null = shared_sign_flip_null(x, draws=100, rng=np.random.default_rng(19))
    assert np.isfinite(null).all()
