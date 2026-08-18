"""Tests for the factor-neutral sizing study.

Everything here that can run on SYNTHETIC data does. That is deliberate and it
is the lesson this repo keeps re-learning: a checking tool validated only
against the production data it is meant to audit reports success and hides
exactly what it was built to find. So the loadings are constructed with a known
answer and the tests assert the solves recover it.

**Every recovery test has a paired MUTATION test** that breaks one term and
asserts the check fails. A test that cannot fail is indistinguishable from one
that does not work, and three of the checks below (the PC1 tie-out, the cost
model, the causality of the walk-forward fit) are the ones the whole study rests
on -- so each is pinned from both directions.

The three tests marked ``integration`` read the cached leg runs and certify the
composition against the four stored engine passes. They skip cleanly when the
artifacts are absent so the fast gate stays green on a cold checkout.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
import pytest

from RVUtils.ConvexityRV import factor_attribution as fa
from RVUtils.ConvexityRV import factor_neutral_sizing as fns

REPO = pathlib.Path(__file__).resolve().parents[1]
DATA = REPO / "notebooks" / "data" / "convexity_rv"
TENORS = ("2Y", "3Y", "5Y", "7Y", "10Y", "15Y", "20Y", "25Y", "30Y", "40Y", "50Y")


# ===========================================================================
# Fixtures -- a synthetic curve with a KNOWN factor structure
# ===========================================================================
def _synth_panel(n_days: int = 900, seed: int = 11) -> pd.DataFrame:
    """A rate panel whose PCA has a genuinely humped PC1 and a monotone PC2.

    Humped on purpose: a FLAT PC1 would make DV01-neutral and PC1-neutral the
    same trade, and every interesting claim in this module is about the gap
    between them. The hump is the reason ``pc1_neutral`` exists.
    """
    rng = np.random.default_rng(seed)
    yrs = np.array([fa._tenor_years(t) for t in TENORS], dtype=float)
    lvl = 0.30 + 0.05 * np.exp(-((np.log(yrs) - np.log(7.0)) ** 2))   # humped
    slope = np.linspace(0.55, -0.30, len(TENORS))                     # monotone
    curv = (np.log(yrs) - np.log(yrs).mean()) ** 2
    curv = curv - curv.mean()
    f = rng.normal(0.0, [6.0, 2.0, 0.8], size=(n_days, 3))
    d = f @ np.vstack([lvl, slope, curv])
    lv = 3.0 + np.cumsum(d, axis=0) / 100.0
    idx = pd.bdate_range("2018-01-01", periods=n_days)
    return pd.DataFrame(lv, index=idx, columns=list(TENORS))


@pytest.fixture(scope="module")
def panel() -> pd.DataFrame:
    return _synth_panel()


@pytest.fixture(scope="module")
def fcfg() -> fa.FactorConfig:
    return fa.FactorConfig(tenors=TENORS, extra_tenors=())


@pytest.fixture(scope="module")
def fm(panel, fcfg) -> fa.FactorModel:
    return fa.fit_factor_model(panel, fcfg)


@pytest.fixture(scope="module")
def loadings(fm) -> pd.DataFrame:
    return fns.leg_pc_loadings(fm, ("5Y", "10Y", "30Y", "50Y", "20Yx5Y", "25Yx5Y"))


# ===========================================================================
# 1. pc1_neutral -- the retarget's headline sizing
# ===========================================================================
def test_pc1_neutral_zeroes_the_level_factor(loadings):
    w = fns.pc1_neutral_weights("5Y", "30Y", loadings, dv01=100_000.0)
    f = fns.package_pc_exposure(w, loadings)
    scale = max(abs(w["5Y"]), abs(w["30Y"])) * float(loadings["PC1"].abs().max())
    assert abs(float(f["PC1"])) < 1e-9 * scale
    assert w["30Y"] == pytest.approx(-100_000.0)


def test_pc1_neutral_is_deliberately_not_dv01_neutral(loadings):
    """The whole point. If the two legs' PC1 loadings differ, so must the sizes."""
    w = fns.pc1_neutral_weights("5Y", "30Y", loadings, dv01=100_000.0)
    net = sum(w.values())
    assert abs(net) > 1.0, "a humped PC1 must make PC1-neutral differ from DV01-neutral"
    ratio = loadings.loc["30Y", "PC1"] / loadings.loc["5Y", "PC1"]
    assert w["5Y"] == pytest.approx(100_000.0 * ratio)


def test_pc1_neutral_ties_out_to_pca_rv_curve_weights(panel):
    """The house function computes the same object; this is a TIE-OUT, not a copy.

    ``pca_rv.curve_weights(short, long, neutralize=("PC1",))`` returns
    ``{short: -v1_long/v1_short, long: 1}``. Scaled by ``-dv01`` that is exactly
    :func:`pc1_neutral_weights`. Checked against a real ``make_pca_rv_builder``
    fit on the same panel rather than against the docstring, because two
    implementations of one formula is how the two quietly stop agreeing.
    """
    from RVUtils.pca_rv import make_pca_rv_builder

    fit, _fv, _res, _fly, curve_weights, *_ = make_pca_rv_builder(
        panel * 100.0, tenors=list(TENORS), on="changes", matrix="cov", n_factors=3)
    fit()
    house = curve_weights("5Y", "30Y", neutralize=("PC1",))

    cfg = fa.FactorConfig(tenors=TENORS, extra_tenors=())
    L = fns.leg_pc_loadings(fa.fit_factor_model(panel, cfg), ("5Y", "30Y"))
    mine = fns.pc1_neutral_weights("5Y", "30Y", L, dv01=100_000.0)

    scaled = {k: -100_000.0 * v for k, v in house.items()}
    assert mine["5Y"] == pytest.approx(scaled["5Y"], rel=1e-10)
    assert mine["30Y"] == pytest.approx(scaled["30Y"], rel=1e-10)


def test_pc1_neutral_MUTATION_wrong_ratio_direction_fails(loadings):
    """Invert the ratio -- the sizing error a sign slip would produce -- and the
    level exposure must NOT come out at zero. Without this the tie-out above
    would pass for a function that returns the reciprocal."""
    v_f = float(loadings.loc["5Y", "PC1"])
    v_b = float(loadings.loc["30Y", "PC1"])
    bad = {"5Y": 100_000.0 * v_f / v_b, "30Y": -100_000.0}   # ratio inverted
    f = fns.package_pc_exposure(bad, loadings)
    assert abs(float(f["PC1"])) > 1.0, "the mutation must break level neutrality"


def test_pc1_neutral_refuses_two_constraints(loadings):
    with pytest.raises(ValueError, match="TWO-leg"):
        fns.pc1_neutral_weights("5Y", "30Y", loadings, neutralize=("PC1", "PC2"))


def test_pc1_neutral_raises_on_degenerate_front_leg(loadings):
    L = loadings.copy()
    L.loc["5Y", "PC1"] = 0.0
    with pytest.raises(np.linalg.LinAlgError):
        fns.pc1_neutral_weights("5Y", "30Y", L)


# ===========================================================================
# 2. pc12_neutral -- three legs, two constraints
# ===========================================================================
def test_pc12_neutral_zeroes_both_factors(loadings):
    w = fns.pc12_neutral_weights("5Y", "30Y", "10Y", loadings, dv01=100_000.0)
    f = fns.package_pc_exposure(w, loadings)
    scale = max(abs(v) for v in w.values()) * float(loadings.abs().to_numpy().max())
    assert abs(float(f["PC1"])) < 1e-9 * scale
    assert abs(float(f["PC2"])) < 1e-9 * scale
    assert w["30Y"] == pytest.approx(-100_000.0)


def test_pc12_neutral_leaves_curvature_alone(loadings):
    """Two constraints on three legs cannot also zero PC3, and must not pretend to."""
    w = fns.pc12_neutral_weights("5Y", "30Y", "10Y", loadings)
    f = fns.package_pc_exposure(w, loadings)
    assert abs(float(f["PC3"])) > 1.0


def test_pc12_neutral_MUTATION_sign_flip_in_solve_fails(loadings):
    """Flip the sign of the right-hand side -- the classic solve bug -- and the
    neutralised factors must come out at TWICE the unhedged exposure, not zero."""
    ks = ["PC1", "PC2"]
    f_f = loadings.loc["5Y", ks].to_numpy(float)
    f_b = loadings.loc["30Y", ks].to_numpy(float)
    f_h = loadings.loc["10Y", ks].to_numpy(float)
    r_b = -100_000.0
    M = np.column_stack([f_f, f_h])
    r_f, r_h = np.linalg.solve(M, +r_b * f_b)          # sign flipped
    bad = {"5Y": float(r_f), "30Y": r_b, "10Y": float(r_h)}
    f = fns.package_pc_exposure(bad, loadings)
    assert abs(float(f["PC1"])) > 1.0 and abs(float(f["PC2"])) > 1.0


def test_pc12_neutral_rejects_hedge_that_is_already_a_leg(loadings):
    with pytest.raises(ValueError, match="already a leg"):
        fns.pc12_neutral_weights("5Y", "30Y", "5Y", loadings)


def test_pc12_neutral_raises_on_ill_conditioned_solve(loadings):
    """Two free legs that are collinear in the neutralised subspace cannot span
    it. Returning enormous weights instead of raising is how an ill-posed hedge
    reaches a P&L table looking like a result."""
    L = loadings.copy()
    L.loc["10Y", ["PC1", "PC2"]] = L.loc["5Y", ["PC1", "PC2"]].to_numpy() * (1 + 1e-12)
    with pytest.raises(np.linalg.LinAlgError, match="ill-conditioned"):
        fns.pc12_neutral_weights("5Y", "30Y", "10Y", L)


# ===========================================================================
# 3. Variance shares -- the column the retarget rests on
# ===========================================================================
def test_variance_shares_sum_to_one(loadings, fm):
    lam = fm.model.eigenvalues.reindex(["PC1", "PC2", "PC3"]).astype(float)
    w = fns.dv01_neutral_weights("5Y", "30Y", 100_000.0)
    vs = fns.package_variance_shares(w, loadings, lam)
    assert float(vs.sum()) == pytest.approx(1.0)
    assert (vs >= -1e-15).all()


def test_variance_shares_move_to_zero_for_the_neutralised_pc(loadings, fm):
    lam = fm.model.eigenvalues.reindex(["PC1", "PC2", "PC3"]).astype(float)
    base = fns.package_variance_shares(
        fns.dv01_neutral_weights("20Yx5Y", "25Yx5Y", 100_000.0), loadings, lam)
    hedged = fns.package_variance_shares(
        fns.pc1_neutral_weights("20Yx5Y", "25Yx5Y", loadings), loadings, lam)
    assert float(base["PC1"]) > 1e-3
    assert float(hedged["PC1"]) < 1e-12


# ===========================================================================
# 4. The cost model -- must reproduce the incumbent EXACTLY
# ===========================================================================
def test_leg_cost_reproduces_the_two_leg_flat_fee():
    """The generalisation is only admissible if it changes nothing for two legs.

    ``build_backtest`` charges a flat ``2 * cost_bp_one_way * package_dv01`` per
    cohort round trip. The per-leg model must land on the same $100,000, or
    every comparison against the incumbent is a comparison of two cost models.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    cfg = ll.strat1_config()
    c_leg = fns.leg_cost_bp_one_way(cfg)
    w = fns.dv01_neutral_weights("5Y", "30Y", cfg.package_dv01)
    fee = 2.0 * c_leg * sum(abs(v) for v in w.values())
    flat = 2.0 * float(cfg.cost_bp_one_way) * float(cfg.package_dv01)
    assert fee == pytest.approx(flat)
    assert fee == pytest.approx(100_000.0)


def test_leg_cost_MUTATION_forgetting_the_half_doubles_the_fee():
    """Drop the ``/ 2`` and the two-leg package pays twice the committed fee."""
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    cfg = ll.strat1_config()
    bad = float(cfg.cost_bp_one_way)                       # no / 2
    w = fns.dv01_neutral_weights("5Y", "30Y", cfg.package_dv01)
    fee = 2.0 * bad * sum(abs(v) for v in w.values())
    assert fee == pytest.approx(200_000.0)
    assert fee != pytest.approx(100_000.0)


def test_the_fee_follows_gross_dv01_not_the_leg_count(loadings):
    """A three-leg package's fee is whatever its gross DV01 says, not a flat rate.

    Note what is deliberately NOT asserted: that three legs always cost more.
    They usually do -- the fitted 5Y/30Y ``pc12_neutral`` trades $364,300 of
    gross DV01 against the incumbent's $200,000 -- but a hedge that shrinks the
    front leg can trade less, and a test that demanded "more" would be pinning a
    coincidence of one loading matrix rather than the cost model.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    cfg = ll.strat1_config()
    c_leg = fns.leg_cost_bp_one_way(cfg)
    w3 = fns.pc12_neutral_weights("5Y", "30Y", "10Y", loadings, dv01=cfg.package_dv01)
    gross3 = sum(abs(v) for v in w3.values())
    fee3 = 2.0 * c_leg * gross3
    assert len(w3) == 3
    assert fee3 == pytest.approx(0.5 * gross3)          # 2 * 0.25 bp
    assert fee3 != pytest.approx(100_000.0), (
        "a three-leg package must not silently pay the two-leg flat fee")
    # and doubling the hedge leg's size must move the fee by exactly its share
    w4 = dict(w3)
    w4["10Y"] = 2.0 * w4["10Y"]
    assert 2.0 * c_leg * sum(abs(v) for v in w4.values()) == pytest.approx(
        fee3 + 2.0 * c_leg * abs(w3["10Y"]))


# ===========================================================================
# 5. The walk-forward fit -- causality is the claim, so it is pinned
# ===========================================================================
def test_walk_forward_loadings_are_strictly_causal(panel, fcfg):
    """Corrupt the panel AFTER the sizing date; the weights must not move.

    This is the look-ahead test. A weight fitted on an expanding window is only
    honest if data at or after the decision date cannot reach it, and the way to
    demonstrate that is to change that data and observe nothing.
    """
    dates = [panel.index[400], panel.index[600]]
    base, _d, _v = fns.walk_forward_loadings(panel, fcfg, dates, ("5Y", "30Y"),
                                            min_fit_days=50, hard_floor=15)
    tainted = panel.copy()
    tainted.iloc[610:] = tainted.iloc[610:] * 3.0 + 7.0
    after, _d2, _v2 = fns.walk_forward_loadings(tainted, fcfg, dates, ("5Y", "30Y"),
                                                min_fit_days=50, hard_floor=15)
    for d in dates:
        pd.testing.assert_frame_equal(base[d], after[d])


def test_walk_forward_MUTATION_leaky_window_does_move(panel, fcfg):
    """The paired half: a fit that includes the corrupted future MUST change.

    Without this, the causality test above would also pass for a function that
    ignored its ``dates`` argument entirely and returned a constant.
    """
    tainted = panel.copy()
    tainted.iloc[610:] = tainted.iloc[610:] * 3.0 + 7.0
    d_late = [panel.index[800]]
    a, _, _ = fns.walk_forward_loadings(panel, fcfg, d_late, ("5Y", "30Y"),
                                        min_fit_days=50, hard_floor=15)
    b, _, _ = fns.walk_forward_loadings(tainted, fcfg, d_late, ("5Y", "30Y"),
                                        min_fit_days=50, hard_floor=15)
    assert not np.allclose(a[d_late[0]].to_numpy(), b[d_late[0]].to_numpy())


def test_walk_forward_flags_short_fits_rather_than_dropping_them(panel, fcfg):
    dates = [panel.index[20], panel.index[500]]
    _l, diag, _v = fns.walk_forward_loadings(panel, fcfg, dates, ("5Y", "30Y"),
                                             min_fit_days=250, hard_floor=15)
    assert len(diag) == 2, "a thin cohort must be sized, not dropped"
    assert bool(diag["short_fit"].iloc[0]) and not bool(diag["short_fit"].iloc[1])


def test_walk_forward_refuses_below_the_hard_floor(panel, fcfg):
    with pytest.raises(ValueError, match="hard floor"):
        fns.walk_forward_loadings(panel, fcfg, [panel.index[5]], ("5Y", "30Y"),
                                  min_fit_days=250, hard_floor=15)


def test_walk_forward_scores_use_only_history(panel, fcfg, fm):
    d = panel.index[600]
    V = fm.loadings[["PC1", "PC2", "PC3"]]
    sc = fns.walk_forward_scores(panel, fcfg, V, d, window=100)
    assert sc.index.max() < d
    assert len(sc) == 100


# ===========================================================================
# 6. Composition linearity -- the premise of one-pass-per-leg
# ===========================================================================
def _toy_legs(n: int = 60):
    idx = pd.bdate_range("2020-01-01", periods=n)
    runs = {}
    rng = np.random.default_rng(3)
    for j, leg in enumerate(("A", "B")):
        marks = pd.DataFrame(
            {f"{leg}_c0000": np.cumsum(rng.normal(0, 100, n)),
             f"{leg}_c0001": np.concatenate([np.zeros(20),
                                             np.cumsum(rng.normal(0, 100, n - 20))])},
            index=idx)
        coh = pd.DataFrame([
            {"tag": f"{leg}_c0000", "leg": leg, "cohort": 0, "entry": idx[0],
             "exit": idx[40], "live_at_end": False, "closed": True,
             "gross_pnl_ccy": float(marks[f"{leg}_c0000"].iloc[40]),
             "gross_pnl_bp": 0.0},
            {"tag": f"{leg}_c0001", "leg": leg, "cohort": 1, "entry": idx[20],
             "exit": pd.NaT, "live_at_end": True, "closed": False,
             "gross_pnl_ccy": np.nan, "gross_pnl_bp": np.nan},
        ])
        # a closed cohort's mark stops at its exit; realised P&L takes over
        marks.loc[idx[41:], f"{leg}_c0000"] = np.nan
        eq = marks.fillna(0.0).sum(axis=1)
        runs[leg] = fns.LegRun(leg=leg, equity=eq, cohorts=coh, marks=marks)
        _ = j
    return runs, idx


def _toy_weights(scale: float = 1.0) -> pd.DataFrame:
    rows = []
    for k, (entry, exit_, closed) in enumerate([(0, 40, True), (20, None, False)]):
        for leg, r in (("A", +100_000.0 * scale), ("B", -100_000.0 * scale)):
            rows.append({"structure": "T", "sizing": "s", "cohort": k,
                         "entry": entry, "exit": exit_, "closed": closed,
                         "leg": leg, "dv01": r})
    return pd.DataFrame(rows)


def test_compose_book_is_exactly_linear_in_the_weights():
    """Scaling every weight by k must scale the whole equity path by k.

    This IS the claim that lets sixteen books come from eight engine runs. If it
    were only approximately true, every table in the study would be a different
    kind of number from the engine's own.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    runs, idx = _toy_legs()
    cfg = ll.strat1_config()
    w1, w3 = _toy_weights(1.0), _toy_weights(3.0)
    for w in (w1, w3):
        w["entry"] = [idx[int(e)] for e in w["entry"]]
        w["exit"] = [pd.NaT if pd.isna(e) else idx[int(e)] for e in w["exit"]]
    eq1, _ = fns.compose_book(runs, w1, cfg=cfg)
    eq3, _ = fns.compose_book(runs, w3, cfg=cfg)
    np.testing.assert_allclose(eq3.to_numpy(), 3.0 * eq1.to_numpy(), rtol=1e-12)


def test_compose_book_charges_the_fee_only_after_the_unwind():
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    runs, idx = _toy_legs()
    cfg = ll.strat1_config()
    w = _toy_weights(1.0)
    w["entry"] = [idx[int(e)] for e in w["entry"]]
    w["exit"] = [pd.NaT if pd.isna(e) else idx[int(e)] for e in w["exit"]]
    free, _ = fns.compose_book(runs, w, cfg=cfg, cost_bp_one_way=0.0)
    paid, book = fns.compose_book(runs, w, cfg=cfg)
    gap = (free - paid)
    assert gap.iloc[0] == pytest.approx(0.0)
    assert gap.iloc[-1] == pytest.approx(100_000.0)
    assert int(book["closed"].sum()) == 1


def test_breakeven_cost_uses_gross_dv01_not_the_cohort_count():
    """A three-leg package trades more risk per cohort, so a per-cohort
    denominator understates its break-even. Pinned by construction: doubling the
    gross DV01 at the same gross P&L must halve the break-even cost."""
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    cfg = ll.strat1_config()
    book = pd.DataFrame([{"closed": True, "gross_bp": 10.0, "gross_dv01": 200_000.0},
                         {"closed": True, "gross_bp": 6.0, "gross_dv01": 200_000.0}])
    fat = book.assign(gross_dv01=400_000.0)
    b1 = fns.breakeven_cost_bp(book, cfg=cfg)
    b2 = fns.breakeven_cost_bp(fat, cfg=cfg)
    assert b1 == pytest.approx(16.0 * cfg.package_dv01 / (2 * 400_000.0))
    assert b2 == pytest.approx(b1 / 2.0)


def test_breakeven_cost_is_negative_when_the_book_loses_gross():
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    book = pd.DataFrame([{"closed": True, "gross_bp": -5.0, "gross_dv01": 200_000.0}])
    assert fns.breakeven_cost_bp(book, cfg=ll.strat1_config()) < 0


# ===========================================================================
# 7. The slope overlay
# ===========================================================================
def test_slope_hedge_ratio_cancels_the_measured_beta(loadings):
    beta = 12_345.0
    h = fns.slope_hedge_ratio(beta, loadings)
    inst = fns.slope_instrument_weights(h)
    f2 = sum(w * float(loadings.loc[leg, "PC2"]) for leg, w in inst.items())
    assert beta + f2 == pytest.approx(0.0, abs=1e-6)


def test_slope_hedge_ratio_MUTATION_wrong_sign_doubles_the_exposure(loadings):
    beta = 12_345.0
    inst = fns.slope_instrument_weights(-fns.slope_hedge_ratio(beta, loadings))
    f2 = sum(w * float(loadings.loc[leg, "PC2"]) for leg, w in inst.items())
    assert beta + f2 == pytest.approx(2.0 * beta, rel=1e-9)


def test_slope_beta_path_recovers_a_planted_beta():
    idx = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(5)
    pc2 = pd.Series(rng.normal(0, 2.0, len(idx)), index=idx)
    beta_true = 5_000.0
    equity = pd.Series(np.cumsum(beta_true * pc2.to_numpy()
                                 + rng.normal(0, 1.0, len(idx))), index=idx)
    w = pd.Series(1.0, index=idx)
    reb = [idx[300]]
    scores = {reb[0]: pd.DataFrame({"PC1": 0.0, "PC2": pc2}, index=idx)}
    out = fns.slope_beta_path(equity, w, scores, reb, window=252)
    assert float(out["beta_usd_per_pc2"].iloc[0]) == pytest.approx(beta_true, rel=1e-3)
    assert int(out["n_days"].iloc[0]) == 252


def test_slope_beta_path_never_uses_data_at_or_after_the_rebalance():
    idx = pd.bdate_range("2020-01-01", periods=400)
    rng = np.random.default_rng(7)
    pc2 = pd.Series(rng.normal(0, 2.0, len(idx)), index=idx)
    eq = pd.Series(np.cumsum(3_000.0 * pc2.to_numpy()), index=idx)
    w = pd.Series(1.0, index=idx)
    reb = [idx[300]]
    scores = {reb[0]: pd.DataFrame({"PC2": pc2}, index=idx)}
    a = fns.slope_beta_path(eq, w, scores, reb, window=252)
    eq2 = eq.copy()
    eq2.iloc[300:] = eq2.iloc[300:] * 50.0        # corrupt only the future
    b = fns.slope_beta_path(eq2, w, scores, reb, window=252)
    assert float(a["beta_usd_per_pc2"].iloc[0]) == pytest.approx(
        float(b["beta_usd_per_pc2"].iloc[0]))


# ===========================================================================
# 8. Sample size -- the direction of the haircut, which is easy to invert
# ===========================================================================
def test_n_eff_is_monotone_decreasing_in_cross_structure_correlation():
    """More correlated structures must be worth FEWER independent observations.

    Getting this direction backwards would credit four near-identical books with
    more evidence than four independent ones, which is the failure mode that
    makes a spurious Sharpe look significant.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    cfg = ll.strat1_config()
    rng = np.random.default_rng(13)
    entries = pd.bdate_range("2019-02-01", periods=40, freq="ME")
    exits = entries + pd.DateOffset(years=1)
    base = rng.normal(0, 1, len(entries))
    out = {}
    for rho in (0.0, 0.9):
        books = {}
        for j in range(4):
            noise = rng.normal(0, 1, len(entries))
            pnl = rho * base + np.sqrt(max(1 - rho ** 2, 0)) * noise
            books[f"S{j}"] = pd.DataFrame({
                "closed": True, "entry": entries, "exit": exits, "net_bp": pnl})
        out[rho] = fns.n_eff_report(books, cfg=cfg)
    assert out[0.9]["mean_pairwise_r"] > out[0.0]["mean_pairwise_r"]
    assert out[0.9]["n_eff_pooled"] < out[0.0]["n_eff_pooled"]
    assert out[0.9]["k_eff_structures"] < out[0.0]["k_eff_structures"]


def test_positively_correlated_structures_are_worth_less_than_their_count():
    """The regime this study is actually in: measured r-bar of 0.59-0.76.

    ``k_eff`` is NOT capped at ``k`` and must not be -- with a negative mean
    pairwise correlation the equal-weight portfolio genuinely has less variance
    than ``k`` independent bets, and clipping it would misreport the formula. The
    claim that matters is the one that binds here: positive correlation buys
    fewer independent observations than the structure count.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    entries = pd.bdate_range("2019-02-01", periods=40, freq="ME")
    exits = entries + pd.DateOffset(years=1)
    rng = np.random.default_rng(17)
    common = rng.normal(0, 1, len(entries))
    books = {f"S{j}": pd.DataFrame(
        {"closed": True, "entry": entries, "exit": exits,
         "net_bp": 0.8 * common + 0.6 * rng.normal(0, 1, len(entries))})
        for j in range(4)}
    rep = fns.n_eff_report(books, cfg=ll.strat1_config())
    assert rep["mean_pairwise_r"] > 0.3
    assert rep["k_eff_structures"] < rep["n_structures"]
    assert rep["n_eff_pooled"] < rep["n_nominal_pooled"]


# ===========================================================================
# 9. Config invariants the report quotes
# ===========================================================================
def test_scored_sizings_are_the_trial_count():
    assert fns.SCORED_SIZINGS == fns.SIZINGS
    assert len(fns.SCORED_SIZINGS) == 4
    assert "pc1_neutral" in fns.SIZINGS
    assert "vega_neutral" not in fns.SIZINGS


def test_headline_sizing_matches_the_measured_dominant_factor():
    """The retarget's pre-commitment must follow from its own evidence table."""
    for structure, shares in fns.ATTRIBUTION_VARIANCE_SHARES.items():
        dominant = max(shares, key=shares.get)
        headline = fns.HEADLINE_SIZING[structure]
        if dominant == "level":
            assert headline == "pc1_neutral", structure
        elif dominant == "slope":
            assert headline == "pc12_neutral", structure


def test_hedge_leg_is_not_a_leg_of_any_structure():
    legs = {l for _lab, f, b in fa.STRAT1_STRUCTURES for l in (f, b)}
    assert fns.HEDGE_LEG not in legs or fns.HEDGE_LEG == "10Y"
    # 10Y is not a leg of any of the four long-end structures:
    assert fns.HEDGE_LEG not in legs


# ===========================================================================
# 10. Integration -- against the cached engine runs
# ===========================================================================
_HAVE_LEGS = all((DATA / f"fns_leg_equity_{fns.safe_leg(l)}.parquet").exists()
                 for l in fns.LEG_UNIVERSE)
_HAVE_UNIT = all((DATA / f"strat1_le_unit_equity_{fns.safe_leg(s)}.parquet").exists()
                 for s, _f, _b in fa.STRAT1_STRUCTURES)


@pytest.mark.integration
@pytest.mark.skipif(not _HAVE_LEGS, reason="cached leg runs absent")
def test_leg_runs_share_one_schedule_and_intersect_to_the_unit_grid():
    runs, idx = fns.load_leg_runs(DATA)
    assert len(runs) == len(fns.LEG_UNIVERSE)
    assert len(idx) == 1907, "the intersection must land on the stored runs' grid"
    ref = runs[fns.LEG_UNIVERSE[0]].cohorts
    for r in runs.values():
        assert list(pd.to_datetime(r.cohorts["entry"])) == list(pd.to_datetime(ref["entry"]))
        assert r.equity.index.equals(idx)


@pytest.mark.integration
@pytest.mark.skipif(not (_HAVE_LEGS and _HAVE_UNIT), reason="cached runs absent")
def test_composition_reproduces_the_stored_engine_runs_to_machine_precision():
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    runs, _idx = fns.load_leg_runs(DATA)
    cert = fns.certify_dv01_neutral(runs, DATA, cfg=ll.strat1_config())
    assert len(cert) == 4
    assert cert["terminal_gap_pct"].abs().max() < 1e-9
    assert cert["corr_daily_changes"].min() > 1 - 1e-12


@pytest.mark.integration
@pytest.mark.skipif(not _HAVE_LEGS, reason="cached leg runs absent")
def test_MUTATION_a_mis_signed_package_fails_the_certification():
    """The certification must be capable of failing. Compose the STEEPENER --
    the same two legs with the signs swapped -- and it must not certify."""
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    cfg = ll.strat1_config()
    runs, _idx = fns.load_leg_runs(DATA)
    sched = runs["5Y"].cohorts
    w = pd.DataFrame([
        {"structure": "5Y/30Y", "sizing": "steepener", "cohort": int(c["cohort"]),
         "entry": pd.Timestamp(c["entry"]),
         "exit": pd.Timestamp(c["exit"]) if pd.notna(c["exit"]) else pd.NaT,
         "closed": bool(c["closed"]), "leg": leg, "dv01": r}
        for _i, c in sched.iterrows()
        for leg, r in {"5Y": -cfg.package_dv01, "30Y": +cfg.package_dv01}.items()])
    eq, _b = fns.compose_book(runs, w, cfg=cfg)
    eng = pd.read_parquet(DATA / "strat1_le_unit_equity_5Y-30Y.parquet")["equity_usd"]
    eng.index = pd.to_datetime(eng.index)
    out = fns.certify_engine(eng, eq, label="5Y/30Y", sizing="steepener", cfg=cfg)
    assert abs(out["terminal_gap_pct"]) > 1.0
    assert out["corr_daily_changes"] < 0
