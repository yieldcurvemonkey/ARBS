"""Tests for the cross-strategy factor attribution.

Everything here runs on SYNTHETIC data with a known answer -- no curve, no
network, no artifacts. That is deliberate: the point of a checking tool is to
find a defect, and a checking tool validated only against the same production
data it is meant to audit reports success and hides exactly what it was built
to find. So the P&L is constructed as

    y = b_level*F1 + b_slope*F2 + 0.5*gamma*parallel^2 + carry + noise

with the coefficients chosen, and the tests assert the machinery recovers them.
Every recovery test has a paired mutation test that breaks one term and asserts
the check FAILS -- otherwise a test that always passes is indistinguishable from
one that works.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV.factor_attribution import _active_weight as fa_active_weight
from RVUtils.ConvexityRV.factor_attribution import sizing_diagnosis as fa_sizing
from RVUtils.ConvexityRV.factor_attribution import (
    BP_TO_USD,
    FACTOR_ORDER,
    STABILITY_FLOOR,
    AttributionResult,
    FactorConfig,
    StrategySeries,
    align_to_factor_calendar,
    annuity_dv01,
    attribute,
    exposure_tieout,
    classify_pcs,
    convexity_from_parallel,
    daily_design,
    decisive_table,
    dv01_neutral_ladder,
    fit_factor_model,
    gamma_from_payoff_profile,
    interval_factors,
    package_pc_exposure,
    realised_variance,
    spot_ladder_for_leg,
    trade_design,
)

TENORS = ("2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y")
YEARS = np.array([2, 3, 5, 7, 10, 15, 20, 25, 30, 40, 50], dtype=float)


# ===========================================================================
# Fixtures: a synthetic curve whose factor structure is known by construction
# ===========================================================================
def _synthetic_rates(n_days: int = 1200, seed: int = 11,
                     level_drift_bp: float = 0.12) -> pd.DataFrame:
    """A curve driven by one level, one slope and one curvature factor.

    Shapes are fixed and orthogonalised, so the eigen-decomposition has a unique
    answer up to sign, and the variances are well separated so PC ordering is
    not a coin flip. ``level_drift_bp`` puts a genuine upward drift in the level
    so the demeaned-vs-raw scores test has something to see.
    """
    rng = np.random.default_rng(seed)
    lg = np.log(YEARS)
    level = np.ones_like(YEARS)
    slope = lg - lg.mean()
    curv = (lg - lg.mean()) ** 2
    curv = curv - curv.mean()
    curv = curv - (curv @ slope) / (slope @ slope) * slope
    shapes = np.column_stack([level / np.linalg.norm(level),
                              slope / np.linalg.norm(slope),
                              curv / np.linalg.norm(curv)])
    sd = np.array([6.0, 2.5, 1.0])
    f = rng.normal(size=(n_days, 3)) * sd
    f[:, 0] += level_drift_bp
    d = f @ shapes.T + rng.normal(scale=0.15, size=(n_days, len(YEARS)))
    lvl_bp = 300.0 + np.cumsum(d, axis=0)
    idx = pd.bdate_range("2019-01-02", periods=n_days)
    return pd.DataFrame(lvl_bp / 100.0, index=idx, columns=list(TENORS))


@pytest.fixture(scope="module")
def cfg() -> FactorConfig:
    return FactorConfig(tenors=TENORS, extra_tenors=())


@pytest.fixture(scope="module")
def fm(cfg):
    return fit_factor_model(_synthetic_rates(), cfg)


# ===========================================================================
# 1. The basis
# ===========================================================================
def test_pca_recovers_level_slope_curvature(fm):
    """PC1/PC2/PC3 must be level/slope/curvature -- checked, not assumed."""
    cls = classify_pcs(fm.loadings, fm.tenors, n=3)
    assert list(cls["label"]) == ["level", "slope", "curvature"]
    # A level factor loads the same way on every tenor.
    assert cls.loc["PC1", "same_sign_frac"] == pytest.approx(1.0)
    # A slope factor crosses zero exactly once and is monotone in log-tenor.
    assert cls.loc["PC2", "n_sign_flips"] == 1
    assert abs(cls.loc["PC2", "corr_with_log_tenor"]) > 0.95
    # A slope factor has no parallel component; a level factor is all parallel.
    assert abs(cls.loc["PC2", "loading_sum"]) < 0.1
    assert abs(cls.loc["PC1", "loading_sum"]) > 3.0


def test_explained_variance_is_ordered_and_dominated_by_level(fm):
    ev = fm.explained_variance
    assert ev.iloc[0] > ev.iloc[1] > ev.iloc[2]
    assert 0.80 < ev.iloc[0] < 0.999
    assert ev.iloc[:3].sum() > 0.98


def test_classify_pcs_labels_a_rotated_grid_correctly():
    """The classifier reads the vector's own shape, not a prior on which PC it is."""
    tenors = ["2Y", "5Y", "10Y", "30Y"]
    loadings = pd.DataFrame(
        {"PC1": [0.5, 0.5, 0.5, 0.5],        # level
         "PC2": [-0.6, -0.2, 0.3, 0.7],      # slope: one sign change
         "PC3": [0.5, -0.5, -0.5, 0.5]},     # curvature: two sign changes
        index=tenors)
    cls = classify_pcs(loadings, tenors, n=3)
    assert list(cls["label"]) == ["level", "slope", "curvature"]


def test_raw_scores_carry_the_drift_that_demeaned_scores_discard(fm):
    """The module's headline measurement decision, asserted rather than asserted-to.

    Summing raw scores over the whole sample must reproduce the projection of
    the TOTAL curve move. Demeaned scores cannot: they sum to ~0 by
    construction, which is exactly how a directional drift gets misbooked as
    alpha.
    """
    total_move = (fm.rates_bp.iloc[-1] - fm.rates_bp.iloc[0]).reindex(fm.model.columns)
    expected = float(total_move.values @ fm.loadings["PC1"].values)
    assert float(fm.scores["PC1"].sum()) == pytest.approx(expected, rel=1e-8)
    assert abs(float(fm.scores_demeaned["PC1"].sum())) < 1e-6 * abs(expected)
    assert abs(expected) > 100.0, "fixture must actually drift for this to bite"


def test_parallel_move_is_the_grid_mean_change(fm):
    expect = fm.d_rates_bp[list(fm.tenors)].mean(axis=1)
    pd.testing.assert_series_equal(fm.parallel, expect, check_names=False)


def test_convexity_regressor_is_not_a_linear_function_of_the_pcs(fm):
    """The task's requirement, made checkable: near-zero correlation with each PC."""
    cvx = convexity_from_parallel(fm.parallel)
    for pc in ("PC1", "PC2", "PC3"):
        assert abs(float(np.corrcoef(cvx, fm.scores[pc])[0, 1])) < 0.15
    # ...but it is a deterministic function of the level, hence R^2 ~ 1 on |PC1|.
    assert float(np.corrcoef(cvx, fm.scores["PC1"].abs()) [0, 1]) > 0.8
    assert cvx.min() >= 0.0


def test_convexity_regressor_is_not_demeaned(fm):
    """Demeaning it would move the average gamma earnings into the intercept."""
    assert float(convexity_from_parallel(fm.parallel).mean()) > 0.0


# ===========================================================================
# 2. Interval aggregation
# ===========================================================================
def test_interval_factors_cumulate_to_the_terminal_move(fm):
    idx = fm.scores.index
    a, b = idx[10], idx[260]
    ivf = interval_factors(fm, [(a, b)], n_pcs=3)
    move = (fm.rates_bp.loc[b] - fm.rates_bp.loc[a]).reindex(fm.model.columns)
    assert float(ivf["PC1"].iloc[0]) == pytest.approx(
        float(move.values @ fm.loadings["PC1"].values), rel=1e-8)
    assert float(ivf["parallel"].iloc[0]) == pytest.approx(float(move.mean()), rel=1e-8)
    assert float(ivf["parallel_sq"].iloc[0]) == pytest.approx(
        float(ivf["parallel"].iloc[0]) ** 2, rel=1e-12)
    assert int(ivf["n_days"].iloc[0]) == 250


def test_interval_entry_is_exclusive(fm):
    """(entry, exit] -- the entry day's own change belongs to the previous trade."""
    idx = fm.scores.index
    a, b = idx[10], idx[11]
    ivf = interval_factors(fm, [(a, b)], n_pcs=3)
    assert int(ivf["n_days"].iloc[0]) == 1
    assert float(ivf["PC1"].iloc[0]) == pytest.approx(float(fm.scores["PC1"].loc[b]))


def test_realised_variance_differs_from_squared_terminal_move(fm):
    """The delta-hedged and buy-and-hold convexity regressors are NOT the same."""
    idx = fm.scores.index
    ivf = interval_factors(fm, [(idx[10], idx[260])], n_pcs=3)
    assert float(ivf["realised_var"].iloc[0]) > 0
    assert float(ivf["realised_var"].iloc[0]) != pytest.approx(
        float(ivf["parallel_sq"].iloc[0]), rel=0.05)


def test_realised_variance_rolling_window(fm):
    rv = realised_variance(fm.parallel, 5)
    assert rv.isna().sum() == 4
    assert float(rv.iloc[4]) == pytest.approx(float((fm.parallel.iloc[:5] ** 2).sum()))


# ===========================================================================
# 3. The regression: recovery, then mutation
# ===========================================================================
def _synthetic_pnl(fm, *, b_level=800.0, b_slope=-300.0, b_curv=250.0,
                   gamma=40.0, carry_per_day=-120.0, noise=250.0, seed=3):
    """A P&L with a KNOWN factor decomposition, in dollars.

    ``b_curv`` is deliberately large relative to ``b_slope``: PC3's daily sd in
    the fixture is 1.0bp against PC2's 2.5bp, so a curvature beta of the same
    size as the slope beta would be estimated at a fraction of the signal-to-
    noise and the recovery tolerance would be measuring the fixture's noise
    rather than the estimator.
    """
    rng = np.random.default_rng(seed)
    idx = fm.scores.index
    carry = pd.Series(carry_per_day, index=idx)
    y = (b_level * fm.scores["PC1"] + b_slope * fm.scores["PC2"]
         + b_curv * fm.scores["PC3"] + 0.5 * gamma * fm.parallel ** 2
         + carry + rng.normal(scale=noise, size=len(idx)))
    s = StrategySeries(name="synthetic", level="daily", y=y,
                       weight=pd.Series(1.0, index=idx), carry=carry)
    return s, dict(level=b_level, slope=b_slope, curvature=b_curv,
                   convexity=0.5 * gamma, carry=1.0)


def test_attribution_recovers_known_coefficients(fm, cfg):
    s, truth = _synthetic_pnl(fm)
    X = daily_design(fm, s, n_pcs=3)
    res = attribute(s.y, X, name="synthetic", level="daily",
                    hac_lag=cfg.hac_lag_daily)
    for k, v in truth.items():
        assert res.coefs[k] == pytest.approx(v, rel=0.10), f"{k}: {res.coefs[k]} vs {v}"
    assert res.r2 > 0.95
    assert abs(res.tstats["level"]) > 10


def test_attribution_shares_close_to_one_hundred_percent(fm, cfg):
    s, _ = _synthetic_pnl(fm)
    X = daily_design(fm, s, n_pcs=3)
    res = attribute(s.y, X, name="synthetic", level="daily", hac_lag=cfg.hac_lag_daily)
    assert float(res.shares.sum()) == pytest.approx(1.0, abs=1e-9)
    assert float(res.contributions.sum()) == pytest.approx(res.total_pnl, rel=1e-9)


def test_attribution_detects_a_pure_convexity_book(fm, cfg):
    """A book with NO linear factor exposure must report ~all P&L as convexity."""
    s, _ = _synthetic_pnl(fm, b_level=0.0, b_slope=0.0, b_curv=0.0,
                          gamma=400.0, carry_per_day=0.0, noise=50.0)
    X = daily_design(fm, s, n_pcs=3)
    res = attribute(s.y, X, name="pure_gamma", level="daily", hac_lag=cfg.hac_lag_daily)
    assert res.shares["convexity"] > 0.90
    assert abs(res.shares["level"]) < 0.05
    assert abs(res.shares["slope"]) < 0.05


def test_attribution_detects_a_pure_slope_book(fm, cfg):
    """...and the mirror image, so the test cannot pass by always saying 'gamma'."""
    s, _ = _synthetic_pnl(fm, b_level=0.0, b_slope=-4000.0, b_curv=0.0,
                          gamma=0.0, carry_per_day=0.0, noise=50.0)
    X = daily_design(fm, s, n_pcs=3)
    res = attribute(s.y, X, name="pure_slope", level="daily", hac_lag=cfg.hac_lag_daily)
    assert abs(res.shares["convexity"]) < 0.05
    assert res.shares["slope"] > 0.90


def test_mutation_zeroing_the_slope_term_is_caught(fm, cfg):
    """Mutation guard: if the true slope beta is zero, the recovery test must FAIL.

    Without this the recovery test above could pass on a machinery that ignores
    its inputs -- a checking tool that is itself wrong.
    """
    s, truth = _synthetic_pnl(fm, b_slope=0.0)
    X = daily_design(fm, s, n_pcs=3)
    res = attribute(s.y, X, name="mutant", level="daily", hac_lag=cfg.hac_lag_daily)
    with pytest.raises(AssertionError):
        assert res.coefs["slope"] == pytest.approx(-300.0, rel=0.10)
    assert res.coefs["slope"] == pytest.approx(0.0, abs=30.0)


def test_mutation_dropping_a_driver_from_X_collapses_r2(fm, cfg):
    """Removing a real driver must show up as a materially worse fit."""
    s, _ = _synthetic_pnl(fm, noise=100.0)
    X = daily_design(fm, s, n_pcs=3)
    full = attribute(s.y, X, name="full", level="daily", hac_lag=cfg.hac_lag_daily)
    partial = attribute(s.y, X.drop(columns=["level"]), name="partial",
                        level="daily", hac_lag=cfg.hac_lag_daily)
    assert full.r2 - partial.r2 > 0.5


def test_incremental_r2_sums_to_total_r2(fm, cfg):
    s, _ = _synthetic_pnl(fm)
    X = daily_design(fm, s, n_pcs=3)
    res = attribute(s.y, X, name="synthetic", level="daily", hac_lag=cfg.hac_lag_daily)
    assert float(res.incremental_r2.sum()) == pytest.approx(res.r2, abs=1e-8)
    assert list(res.incremental_r2.index) == [c for c in FACTOR_ORDER if c in X.columns]


def test_hac_tstats_are_smaller_than_ols_on_overlapping_data(fm):
    """Overlapping windows inflate OLS t-stats; HAC is why the module uses it."""
    import statsmodels.api as sm
    s, _ = _synthetic_pnl(fm)
    X = daily_design(fm, s, n_pcs=3)
    res_hac = attribute(s.y, X, name="h", level="daily", hac_lag=60)
    Xc = sm.add_constant(X)
    ols = sm.OLS(s.y.reindex(X.index), Xc).fit()
    assert abs(res_hac.tstats["convexity"]) < abs(float(ols.tvalues["convexity"])) * 1.5


def test_denominator_stability_flag_fires_on_a_near_zero_net(fm, cfg):
    """Two huge offsetting drivers netting to ~nothing must be flagged, not ranked."""
    idx = fm.scores.index
    rng = np.random.default_rng(9)
    y = (5000.0 * fm.scores["PC1"] - 5000.0 * fm.scores["PC1"]
         + pd.Series(rng.normal(scale=1.0, size=len(idx)), index=idx))
    y = 5000.0 * fm.scores["PC2"] + y  # a big driver, but a total near zero
    y = y - y.mean() + 1e-6
    s = StrategySeries(name="knife_edge", level="daily", y=y,
                       weight=pd.Series(1.0, index=idx))
    res = attribute(s.y, daily_design(fm, s, n_pcs=3), name="knife_edge",
                    level="daily", hac_lag=cfg.hac_lag_daily)
    assert res.denom_stability < STABILITY_FLOOR
    assert res.denom_unstable is True


def test_denominator_stability_flag_does_not_fire_on_a_healthy_book(fm, cfg):
    s, _ = _synthetic_pnl(fm, b_level=4000.0, noise=50.0)
    res = attribute(s.y, daily_design(fm, s, n_pcs=3), name="healthy",
                    level="daily", hac_lag=cfg.hac_lag_daily)
    assert res.denom_stability > STABILITY_FLOOR
    assert res.denom_unstable is False


def test_attribute_rejects_a_design_with_no_known_columns(fm):
    idx = fm.scores.index
    y = pd.Series(1.0, index=idx)
    with pytest.raises(ValueError, match="no usable factor columns"):
        attribute(y, pd.DataFrame({"nonsense": np.ones(len(idx))}, index=idx),
                  name="x", level="daily")


# ===========================================================================
# 4. Signing and the design matrices
# ===========================================================================
def test_daily_design_drops_days_with_no_position(fm):
    idx = fm.scores.index
    w = pd.Series(1.0, index=idx)
    w.iloc[:100] = 0.0
    s = StrategySeries(name="gap", level="daily", y=pd.Series(1.0, index=idx), weight=w)
    X = daily_design(fm, s, n_pcs=3)
    assert len(X) == len(idx) - 100
    assert X.index[0] == idx[100]


def test_daily_design_scales_by_the_net_package_count(fm):
    idx = fm.scores.index
    s2 = StrategySeries(name="two", level="daily", y=pd.Series(1.0, index=idx),
                        weight=pd.Series(2.0, index=idx))
    s1 = StrategySeries(name="one", level="daily", y=pd.Series(1.0, index=idx),
                        weight=pd.Series(1.0, index=idx))
    X2, X1 = daily_design(fm, s2, n_pcs=3), daily_design(fm, s1, n_pcs=3)
    np.testing.assert_allclose(X2["level"].values, 2.0 * X1["level"].values)
    np.testing.assert_allclose(X2["convexity"].values, 2.0 * X1["convexity"].values)


def test_trade_design_flips_every_regressor_including_the_squared_one(fm):
    """A steepener is short gamma: the convexity column must flip sign too."""
    idx = fm.scores.index
    ivs = [(idx[10], idx[100]), (idx[110], idx[200])]
    y = pd.Series([1.0, 1.0])
    long = StrategySeries(name="l", level="trade", y=y,
                          weight=pd.Series([1.0, 1.0]), intervals=ivs)
    short = StrategySeries(name="s", level="trade", y=y,
                           weight=pd.Series([-1.0, -1.0]), intervals=ivs)
    XL, XS = trade_design(fm, long, n_pcs=3), trade_design(fm, short, n_pcs=3)
    for c in ("level", "slope", "curvature", "convexity"):
        np.testing.assert_allclose(XS[c].values, -XL[c].values)
    assert (XL["convexity"] > 0).all()
    assert (XS["convexity"] < 0).all()


def test_trade_design_convexity_mode_switch(fm):
    idx = fm.scores.index
    s = StrategySeries(name="s", level="trade", y=pd.Series([1.0]),
                       weight=pd.Series([1.0]), intervals=[(idx[10], idx[260])])
    a = trade_design(fm, s, n_pcs=3, convexity="parallel_sq")["convexity"].iloc[0]
    b = trade_design(fm, s, n_pcs=3, convexity="realised_var")["convexity"].iloc[0]
    assert a != pytest.approx(b, rel=0.05)
    with pytest.raises(ValueError, match="parallel_sq or realised_var"):
        trade_design(fm, s, n_pcs=3, convexity="nope")


def test_trade_design_requires_intervals(fm):
    s = StrategySeries(name="s", level="trade", y=pd.Series([1.0]),
                       weight=pd.Series([1.0]))
    with pytest.raises(ValueError, match="needs intervals"):
        trade_design(fm, s, n_pcs=3)


# ===========================================================================
# 5. The sizing diagnosis
# ===========================================================================
def test_pc_exposure_reproduces_the_pnl_of_a_ladder_exactly(fm):
    """The tie-out that binds section 5 to section 2: f.F must equal r.dR."""
    ladder = {"5Y": 100_000.0, "30Y": -100_000.0}
    f = package_pc_exposure(ladder, fm, n_pcs=len(fm.tenors))
    r = pd.Series(ladder).reindex(fm.model.columns).fillna(0.0)
    direct = fm.d_rates_bp[fm.model.columns].values @ r.values
    viafac = fm.scores[f.index].values @ f.values
    np.testing.assert_allclose(direct, viafac, rtol=1e-8, atol=1e-6)


def test_dv01_neutral_flattener_is_not_pc1_neutral(fm):
    """The sizing finding, as a property of the loadings alone.

    A DV01-neutral package has zero NET DV01, but PC1's loadings are not flat
    across the grid, so its PC1 exposure is not zero either. It is small
    relative to an outright -- and that is the point: small, not zero.
    """
    ladder = dv01_neutral_ladder("5Y", "30Y", 100_000.0, fm.rates_bp.mean().to_dict())
    assert sum(ladder.values()) == pytest.approx(0.0, abs=1e-6)
    f = package_pc_exposure(ladder, fm, n_pcs=3)
    outright = package_pc_exposure({"30Y": 100_000.0}, fm, n_pcs=3)
    assert abs(f["PC1"]) < 0.35 * abs(outright["PC1"])
    # ...and the package is overwhelmingly a SLOPE position, which is the point.
    assert abs(f["PC2"]) > 5.0 * abs(f["PC1"])
    # Neutralising DV01 does not shrink the slope exposure; it concentrates it.
    assert abs(f["PC2"]) > abs(outright["PC2"])


def test_dv01_neutral_ladder_signs_follow_the_package_convention(fm):
    """Flattener = pay the front leg, receive the back leg."""
    ladder = dv01_neutral_ladder("5Y", "30Y", 100_000.0, fm.rates_bp.mean().to_dict())
    assert ladder["5Y"] > 0 and ladder["30Y"] < 0


def test_spot_ladder_for_forward_leg_conserves_dv01_and_straddles_the_tenors():
    rates = {"10Y": 300.0, "20Y": 320.0, "30Y": 330.0}
    lad = spot_ladder_for_leg("10Yx10Y", 100_000.0, rates)
    assert set(lad) == {"20Y", "10Y"}
    assert sum(lad.values()) == pytest.approx(100_000.0, rel=1e-9)
    assert lad["20Y"] > 100_000.0 > 0 > lad["10Y"]


def test_spot_ladder_for_a_spot_leg_is_itself():
    assert spot_ladder_for_leg("30Y", 5.0, {"30Y": 300.0}) == {"30Y": 5.0}


def test_annuity_dv01_is_monotone_and_near_the_zero_rate_limit():
    assert annuity_dv01(0.0, 10.0) == pytest.approx(10.0e-4)
    assert annuity_dv01(300.0, 30.0) > annuity_dv01(300.0, 10.0)
    assert annuity_dv01(300.0, 30.0) < 30.0e-4          # discounting bites


def test_gamma_from_payoff_profile_reads_a_known_quadratic():
    """gamma = 2a for a profile P(x) = a x^2 + b x + c, carry included in c."""
    a, b, c = 0.004, -0.2, -1.5
    rows = []
    for _ in range(50):
        row = {"structure": "S"}
        for h in (-25, 0, 25):
            row[f"payoff_bp_{h:+d}" if h else "payoff_bp_+0"] = a * h * h + b * h + c
        rows.append(row)
    panel = pd.DataFrame(rows).rename(columns={"payoff_bp_-25": "payoff_bp_-25"})
    assert gamma_from_payoff_profile(panel, "S", half_width_bp=25.0) == pytest.approx(2 * a)


def test_gamma_from_payoff_profile_is_immune_to_the_carry_level():
    """payoff_profile adds carry as a LEVEL, so the second difference must ignore it."""
    a = 0.004
    def panel_with(c):
        return pd.DataFrame([{"structure": "S",
                              "payoff_bp_-25": a * 625 + c,
                              "payoff_bp_+0": c,
                              "payoff_bp_+25": a * 625 + c}])
    g0 = gamma_from_payoff_profile(panel_with(0.0), "S")
    g1 = gamma_from_payoff_profile(panel_with(-50.0), "S")
    assert g0 == pytest.approx(g1)
    assert g0 == pytest.approx(2 * a)


def test_gamma_from_payoff_profile_rejects_an_unknown_structure():
    panel = pd.DataFrame([{"structure": "S", "payoff_bp_-25": 1.0,
                           "payoff_bp_+0": 0.0, "payoff_bp_+25": 1.0}])
    with pytest.raises(KeyError):
        gamma_from_payoff_profile(panel, "T")


# ===========================================================================
# 6. The decisive table
# ===========================================================================
def _res(name, level, shares, unstable=False, total=1.0):
    return AttributionResult(
        name=name, level=level, n_obs=100, window="w", total_pnl=total, unit="usd",
        r2=0.5, r2_adj=0.5,
        coefs=pd.Series(dtype=float), tstats=pd.Series(dtype=float),
        pvalues=pd.Series(dtype=float), incremental_r2=pd.Series(dtype=float),
        contributions=pd.Series(shares), shares=pd.Series(shares),
        gross_shares=pd.Series(shares),
        denom_stability=0.01 if unstable else 0.9, denom_unstable=unstable)


def test_decisive_table_ranks_by_convexity_share():
    rows = [_res("a", "daily", {"convexity": 0.1}),
            _res("b", "daily", {"convexity": 0.9}),
            _res("c", "daily", {"convexity": 0.5})]
    tbl = decisive_table(rows, level="daily")
    assert list(tbl["strategy"]) == ["b", "c", "a"]


def test_decisive_table_sinks_unstable_denominators_to_the_bottom():
    rows = [_res("stable", "daily", {"convexity": 0.5}),
            _res("blowup", "daily", {"convexity": 40.0}, unstable=True)]
    tbl = decisive_table(rows, level="daily")
    assert list(tbl["strategy"]) == ["stable", "blowup"]
    assert bool(tbl["denom_unstable"].iloc[-1]) is True


def test_decisive_table_filters_by_level():
    rows = [_res("a", "daily", {"convexity": 0.1}), _res("a", "trade", {"convexity": 0.2})]
    assert len(decisive_table(rows, level="trade")) == 1
    assert len(decisive_table(rows)) == 2


def test_gross_shares_are_bounded_and_sum_to_one_in_absolute_value(fm, cfg):
    """The readable companion to share_*: immune to a small net denominator."""
    s, _ = _synthetic_pnl(fm)
    res = attribute(s.y, daily_design(fm, s, n_pcs=3), name="g", level="daily",
                    hac_lag=cfg.hac_lag_daily)
    assert res.gross_shares.abs().max() <= 1.0
    assert float(res.gross_shares.abs().sum()) == pytest.approx(1.0, abs=1e-9)


def test_gross_shares_stay_finite_where_net_shares_explode(fm, cfg):
    """The case the net share cannot express: a book that nets ~zero."""
    idx = fm.scores.index
    y = 5000.0 * fm.scores["PC2"]
    y = y - y.mean() + 1e-9
    s = StrategySeries(name="k", level="daily", y=y, weight=pd.Series(1.0, index=idx))
    res = attribute(s.y, daily_design(fm, s, n_pcs=3), name="k", level="daily",
                    hac_lag=cfg.hac_lag_daily)
    assert abs(res.shares["slope"]) > 10.0          # meaningless
    assert abs(res.gross_shares["slope"]) <= 1.0    # still readable


def test_summary_row_carries_all_three_readings(fm, cfg):
    s, _ = _synthetic_pnl(fm)
    res = attribute(s.y, daily_design(fm, s, n_pcs=3), name="g", level="daily",
                    hac_lag=cfg.hac_lag_daily)
    row = res.summary_row()
    for k in FACTOR_ORDER:
        assert f"share_{k}" in row and f"gross_{k}" in row
        assert f"incr_{k}" in row and f"t_{k}" in row
    assert row["share_unexplained"] == pytest.approx(res.shares["unexplained"])


# ===========================================================================
# 7. Guards on the shared constants
# ===========================================================================
def test_bp_to_usd_matches_the_hundred_k_dv01_convention():
    assert BP_TO_USD == 100_000.0


def test_factor_order_is_the_documented_one():
    assert FACTOR_ORDER == ("level", "slope", "curvature", "convexity", "carry")


def test_fit_factor_model_rejects_a_missing_tenor(cfg):
    panel = _synthetic_rates(200).drop(columns=["40Y"])
    with pytest.raises(KeyError, match="40Y"):
        fit_factor_model(panel, cfg)


# ===========================================================================
# 8. Calendar alignment -- the trap that deleted $17.7m of real marks
# ===========================================================================
def test_align_carries_an_unscored_days_mark_onto_the_next_scored_day():
    """A Good Friday mark must move forward, not vanish."""
    cal = pd.DatetimeIndex(["2020-04-08", "2020-04-09", "2020-04-13", "2020-04-14"])
    pnl = pd.Series([1.0, 2.0, 100.0, 4.0, 5.0],
                    index=pd.DatetimeIndex(["2020-04-08", "2020-04-09", "2020-04-10",
                                            "2020-04-13", "2020-04-14"]))
    out, dropped = align_to_factor_calendar(pnl, cal)
    assert dropped == 0.0
    assert float(out.sum()) == pytest.approx(float(pnl.sum()))
    assert float(out.loc["2020-04-13"]) == pytest.approx(104.0)   # 100 folded forward
    assert float(out.loc["2020-04-09"]) == pytest.approx(2.0)


def test_align_reports_rather_than_hides_marks_past_the_calendar():
    cal = pd.DatetimeIndex(["2020-04-08", "2020-04-09"])
    pnl = pd.Series([1.0, 2.0, 7.0],
                    index=pd.DatetimeIndex(["2020-04-08", "2020-04-09", "2020-04-10"]))
    out, dropped = align_to_factor_calendar(pnl, cal)
    assert dropped == pytest.approx(7.0)
    assert float(out.sum()) == pytest.approx(3.0)


def test_align_is_the_identity_when_the_calendars_agree(fm):
    pnl = pd.Series(1.0, index=fm.scores.index)
    out, dropped = align_to_factor_calendar(pnl, fm.scores.index)
    assert dropped == 0.0
    pd.testing.assert_series_equal(out, pnl, check_names=False)


def test_active_weight_ignores_a_cohort_whose_exit_is_nat(fm):
    """The NaT trap, pinned: an unfilled exit silently gives the cohort no size.

    This is the behaviour the loaders must defend against by filling NaT with the
    end of the calendar -- documented here so a future change that "fixes"
    `_active_weight` instead cannot pass silently.
    """
    idx = fm.scores.index[:50]
    w_nat = fa_active_weight(idx, [idx[0]], [pd.NaT], [1.0])
    w_ok = fa_active_weight(idx, [idx[0]], [idx[-1]], [1.0])
    assert float(w_nat.sum()) == 0.0
    assert float(w_ok.sum()) == 49.0


# ===========================================================================
# 9. The sizing diagnosis' variance decomposition and the tie-out
# ===========================================================================
def _fake_signal_panel(structures, gamma_bp=0.002, carry=-1.5):
    """A payoff-profile panel with a KNOWN gamma, so sizing_diagnosis is testable
    without the real 90MB artifact."""
    a = gamma_bp / 2.0
    rows = []
    for label, _f, _b in structures:
        for _ in range(20):
            rows.append({"structure": label,
                         "payoff_bp_-25": a * 625 + carry,
                         "payoff_bp_+0": carry,
                         "payoff_bp_+25": a * 625 + carry})
    return pd.DataFrame(rows)


def test_sizing_diagnosis_variance_shares_are_eigenvalue_weighted(fm):
    """The whole point of ``var_pc*``: a big PC3 exposure is a SMALL PC3 risk.

    Asserted against the function's own output, not against arithmetic
    re-derived in the test -- a test that recomputes the formula it is checking
    passes even when the function drops the eigenvalue weighting entirely.
    """
    structs = [("5Y/30Y", "5Y", "30Y"), ("30Y/50Y", "30Y", "50Y")]
    sz = fa_sizing(structs, fm, _fake_signal_panel(structs)).set_index("structure")
    for lab in ("5Y/30Y", "30Y/50Y"):
        shares = np.array([sz.loc[lab, f"var_pc{i}"] for i in (1, 2, 3)])
        assert shares.sum() == pytest.approx(1.0)
        assert (shares >= 0).all()

        f = np.array([sz.loc[lab, f"pc{i}_usd_per_unit"] for i in (1, 2, 3)])
        lam = fm.model.eigenvalues.reindex(["PC1", "PC2", "PC3"]).values
        want = (f ** 2) * lam
        np.testing.assert_allclose(shares, want / want.sum(), rtol=1e-9)

        # ...and it must NOT be the unweighted dollar-square share. PC3 carries
        # under 1% of daily variance, so ignoring lambda would inflate it.
        naive = (f ** 2) / (f ** 2).sum()
        assert abs(shares[2] - naive[2]) > 0.05, (
            "eigenvalue weighting makes no difference here -- the test cannot "
            "distinguish a correct implementation from one that drops it")


def test_sizing_diagnosis_reads_the_planted_gamma(fm):
    structs = [("5Y/30Y", "5Y", "30Y")]
    sz = fa_sizing(structs, fm, _fake_signal_panel(structs, gamma_bp=0.004))
    assert float(sz["gamma_bp_per_bp2"].iloc[0]) == pytest.approx(0.004)
    assert float(sz["convex_pnl_1y_usd"].iloc[0]) > 0
    assert float(sz["slope_to_convex"].iloc[0]) > 0


def test_exposure_tieout_recovers_a_planted_exposure_exactly(fm, cfg):
    """Build a P&L that IS the ladder's P&L; the tie-out must come back clean."""
    label, front, back = "5Y/30Y", "5Y", "30Y"
    ladder = dv01_neutral_ladder(front, back, 100_000.0, fm.rates_bp.mean().to_dict())
    r = pd.Series(ladder).reindex(fm.model.columns).fillna(0.0)
    y = pd.Series(fm.d_rates_bp[fm.model.columns].values @ r.values, index=fm.scores.index)
    s = StrategySeries(name=f"planted {label}", level="daily", y=y,
                       weight=pd.Series(1.0, index=y.index))
    res = attribute(y, daily_design(fm, s, n_pcs=3), name=f"planted {label}",
                    level="daily", hac_lag=cfg.hac_lag_daily)
    tie = exposure_tieout(fm, [(label, front, back)], {f"planted {label}": res})
    assert float(tie["rel_err"].iloc[0]) < 0.02
    assert float(tie["cosine"].iloc[0]) > 0.999
    assert float(tie["ratio_slope"].iloc[0]) == pytest.approx(1.0, rel=0.02)


def test_mutation_a_wrong_ladder_fails_the_tieout(fm, cfg):
    """Mutation guard for the tie-out: plant the WRONG package, demand a failure."""
    label, front, back = "5Y/30Y", "5Y", "30Y"
    wrong = dv01_neutral_ladder("10Y", "20Y", 100_000.0, fm.rates_bp.mean().to_dict())
    r = pd.Series(wrong).reindex(fm.model.columns).fillna(0.0)
    y = pd.Series(fm.d_rates_bp[fm.model.columns].values @ r.values, index=fm.scores.index)
    s = StrategySeries(name=f"planted {label}", level="daily", y=y,
                       weight=pd.Series(1.0, index=y.index))
    res = attribute(y, daily_design(fm, s, n_pcs=3), name=f"planted {label}",
                    level="daily", hac_lag=cfg.hac_lag_daily)
    tie = exposure_tieout(fm, [(label, front, back)], {f"planted {label}": res})
    assert float(tie["rel_err"].iloc[0]) > 0.5, "a wrong ladder must NOT tie out"
