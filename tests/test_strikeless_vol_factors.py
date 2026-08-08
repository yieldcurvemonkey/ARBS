import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from RVUtils.StrikelessVol.factors import (
    changes_regression,
    durbin_watson,
    frequency_ladder,
    levels_regression,
)


@pytest.fixture
def planted():
    """A world where d(spread) = -0.78 * d(vol) + noise, by construction."""
    rng = np.random.default_rng(7)
    n = 1500
    idx = pd.bdate_range("2020-01-01", periods=n)
    dvol = rng.normal(0.0, 0.05, n)
    vol = pd.Series(80.0 + np.cumsum(dvol), index=idx)
    # noise_sd=0.05 (not the 0.5 a first draft used): at noise_sd=0.5 the
    # planted beta's OLS sampling std error (~0.26) swamps the rel=0.15
    # tolerance band (0.117) -- a 500-seed Monte Carlo shows that fixture
    # passes only ~35% of the time even though the estimator is unbiased
    # (mean recovered beta -0.781). At 0.05 the same sweep passes 100/500
    # and seed=7 lands at R^2~=0.40, close to the real sample's R^2~=0.34.
    dspread = -0.78 * dvol + rng.normal(0.0, 0.05, n)
    spread = pd.Series(-50.0 + np.cumsum(dspread), index=idx)
    return spread, vol


def test_changes_regression_recovers_the_planted_beta(planted):
    spread, vol = planted
    res = changes_regression(spread, {"vol": vol})
    assert res.kind == "changes"
    assert res.anchor_only is False
    assert res.betas["vol"] == pytest.approx(-0.78, rel=0.15)
    assert abs(res.tstats["vol"]) > 2.0


def test_changes_regression_residuals_are_not_autocorrelated(planted):
    spread, vol = planted
    res = changes_regression(spread, {"vol": vol})
    assert 1.7 < res.durbin_watson < 2.3


def test_levels_regression_is_flagged_anchor_only(planted):
    spread, vol = planted
    res = levels_regression(spread, {"vol": vol})
    assert res.anchor_only is True
    assert res.kind == "levels"
    # trending data -> DW near zero, which is exactly why it is anchor-only
    assert res.durbin_watson < 0.6


def test_durbin_watson_of_white_noise_is_two():
    rng = np.random.default_rng(3)
    assert durbin_watson(pd.Series(rng.normal(0, 1, 5000))) == pytest.approx(2.0, abs=0.1)


def test_durbin_watson_of_a_random_walk_is_near_zero():
    rng = np.random.default_rng(3)
    assert durbin_watson(pd.Series(np.cumsum(rng.normal(0, 1, 5000)))) < 0.3


def test_frequency_ladder_reports_every_horizon(planted):
    spread, vol = planted
    lad = frequency_ladder(spread, {"vol": vol}, horizons=(1, 5, 21))
    assert list(lad["horizon_days"]) == [1, 5, 21]
    assert {"beta_vol", "t_vol", "r_squared", "n"} <= set(lad.columns)
    # Each row must actually be regressed at its own horizon, not merely
    # labelled with it: .diff(h) drops exactly h leading rows, so n must
    # fall as h grows. A ladder that silently regressed every row at
    # horizon_days=1 (while still writing the correct horizon_days label)
    # would report identical n across all three rows -- this would not
    # catch that bug without this assertion.
    assert list(lad["n"]) == [len(spread) - h for h in (1, 5, 21)]


def test_regression_result_exposes_the_intercept():
    """RegressionResult.betas deliberately excludes the constant term (see
    _fit's cols = [c for c in data.columns if c != '_y_'], built BEFORE
    sm.add_constant is called) -- but the brief's published levels equation
    (y = 5.66 - 1.18*vol + 0.443*ASW) is entirely about the intercept plus
    two slopes, and comparing only the slopes silently drops the regime-level
    ('re-basing') claim the intercept carries. This plants a known intercept
    and confirms it comes back unchanged, not merely present as some field."""
    rng = np.random.default_rng(13)
    n = 300
    idx = pd.bdate_range("2022-01-01", periods=n)
    x = pd.Series(rng.normal(0, 1, n), index=idx)
    y = pd.Series(5.66 + 2.0 * x + rng.normal(0, 0.01, n), index=idx)
    res = levels_regression(y, {"x": x})
    assert res.intercept == pytest.approx(5.66, abs=0.05)
    # cross-check against an independently-fit OLS on the same data --
    # not just "some number close to 5.66 by construction," but literally
    # the same constant term statsmodels itself would report.
    naive = sm.OLS(y, sm.add_constant(x)).fit()
    assert res.intercept == pytest.approx(float(naive.params["const"]), rel=1e-9)


def test_two_factor_regression_returns_both_betas(planted):
    spread, vol = planted
    rng = np.random.default_rng(11)
    umep = pd.Series(
        2.0 + np.cumsum(rng.normal(0.0, 0.01, len(spread))), index=spread.index
    )
    res = changes_regression(spread, {"vol": vol, "umep": umep})
    assert set(res.betas) == {"vol", "umep"}
    assert set(res.tstats) == {"vol", "umep"}


def test_hac_correction_matters_for_overlapping_horizon_windows():
    """None of the other tests would fail if HAC were silently dropped in
    favour of classical OLS t-stats -- the planted fixture's residuals are
    close to white noise (DW ~= 2), so naive and HAC standard errors nearly
    coincide there and `abs(tstat) > 2.0` passes either way. This is exactly
    the trap the brief calls out: "a test that plants a known beta and
    recovers it must fail if the regression dropped its HAC correction, or
    it is only testing polyfit."

    At horizon_days=21, day-over-day diffs of daily series overlap by 20 of
    21 days, which mechanically autocorrelates the regression residuals
    (DW << 2) even though the underlying increments are iid -- the textbook
    case Newey-West exists for. Classical OLS overstates significance by
    more than 2x here; a HAC-dropping regression would sail through the
    `< 0.6 * naive_t` bound below where the real implementation does not.
    """
    rng = np.random.default_rng(5)
    n = 1200
    idx = pd.bdate_range("2020-01-01", periods=n)
    dx = rng.normal(0, 1, n)
    x = pd.Series(np.cumsum(dx), index=idx)
    dy = 0.5 * dx + rng.normal(0, 1, n)
    y = pd.Series(np.cumsum(dy), index=idx)

    res = changes_regression(y, {"x": x}, horizon_days=21)
    assert res.durbin_watson < 0.5  # confirms the overlap actually autocorrelates

    dxx = x.diff(21).dropna()
    dyy = y.diff(21).dropna()
    naive = sm.OLS(dyy, sm.add_constant(dxx)).fit()
    naive_t = float(naive.tvalues.iloc[1])

    # HAC only touches standard errors -- point estimates must still agree.
    assert res.betas["x"] == pytest.approx(float(naive.params.iloc[1]), rel=1e-9)
    # A real HAC correction knocks the overstated classical significance
    # down materially; a dropped correction would not.
    assert abs(res.tstats["x"]) < 0.6 * abs(naive_t)
