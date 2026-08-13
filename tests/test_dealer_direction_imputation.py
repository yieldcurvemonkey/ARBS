"""The capped-notional imputation, pinned.

Four things can go wrong here and none of them announce themselves:

* the **fitter** can be quietly wrong -- a censored MLE that does not recover a
  known parameter still returns a number, and every downstream table is then
  precise and false. So every function on the calibration path is validated
  against simulated data whose answer is known before it is allowed near the
  tape (sections 1-2): both lognormal MLEs, both Pareto estimators, both
  truncated cdfs, the KS statistic, and ``fit_frequency_table`` itself;
* the **bound** can be the answer -- where the likelihood has no interior
  maximum, whichever box wall the optimiser reaches first decides the estimate.
  That is fine if it is the documented wall and the fit says so, and it is a
  silent fabrication otherwise, so the shipped table is checked for cells
  standing on the *undocumented* one and for a degeneracy flag that matches
  (section 3);
* the **frozen calibration** can be mis-transcribed -- the multipliers were
  measured in ``scratch/imp_fix01_sweep.py``; here they are recomputed from the
  stored ``(mu, sigma, cap)`` so a typo cannot survive, and the headline is
  required to satisfy its own model-free cross-check (section 3);
* the **application** can double-count -- scaling notional before pricing runs
  the multiplier through the pricing path a second time, so the only sanctioned
  application is to the signed KRD. The module must not expose any other, and
  that is tested by looking for the *value* ``notional × multiplier`` in the
  output columns rather than for a function name (section 5).

Everything here is offline and seeded: no DB, no network, so it runs in the
fast gate.
"""
from __future__ import annotations

import dataclasses
import datetime

import numpy as np
import pandas as pd
import pytest

from SDRUtils.dealer_direction import imputation as imp
from SDRUtils.dealer_direction import types as ddt


# --------------------------------------------------------------------------
# 1. The fitter recovers known parameters. This is the self-test.
# --------------------------------------------------------------------------

def _lognormal_sample(rng, mu, sigma, u, cap, n):
    """A left-truncated lognormal sample split the way the tape splits it."""
    z = np.exp(rng.normal(mu, sigma, n))
    z = z[z >= u]
    return z[z < cap], int((z >= cap).sum())


def test_lognormal_censored_mle_recovers_known_parameters():
    """The estimator the module ships, against an answer known in advance.

    Simulate a lognormal, censor it at the cap exactly as Part 43 does, hand
    the fitter the sub-cap observations plus the *count* above the cap, and
    require the generating parameters back.

    The mu tolerance is 0.30, not 0.15, and the reason is not slack in the
    fitter. At (mu=16, sigma=1.8) the window ``[u, C)`` starts 0.96 sigma ABOVE
    mu, so only the top ~16% of the distribution is ever observed and mu is
    weakly identified: the fit returns 15.74, and its log-likelihood on that
    sample is HIGHER than the true parameters' (-366731.9 vs -366734.7). An MLE
    that beats the truth on the truth's own sample is working; the residual is
    identification, not bias. That is asserted below rather than assumed, and
    the estimand -- which is what the module actually consumes -- is checked to
    5% in :func:`test_lognormal_mean_above_matches_the_simulated_conditional_mean`.
    """
    rng = np.random.default_rng(20260811)
    u, cap = 5e7, 5e8
    for mu_true, sigma_true in ((17.0, 1.2), (16.0, 1.8), (18.0, 0.9)):
        sub, n_cap = _lognormal_sample(rng, mu_true, sigma_true, u, cap, 120_000)
        w = np.ones_like(sub)
        mu, sigma = imp.lognormal_censored_mle(sub, w, u, cap, n_cap)
        assert mu == pytest.approx(mu_true, abs=0.30)
        assert sigma == pytest.approx(sigma_true, abs=0.12)

        stats = imp._suffstats(np.log(sub), w)
        args = (stats, np.log(u), np.log(cap), float(n_cap))
        assert (imp._ln_negll([mu, np.log(sigma)], *args)
                <= imp._ln_negll([mu_true, np.log(sigma_true)], *args))


def test_censored_fit_reproduces_the_capped_count_and_truncation_only_does_not():
    """Why the censored MLE is the one that ships.

    The truncation-only MLE never sees how many prints landed at the cap, so
    nothing stops its implied tail mass from disagreeing with the observed one
    -- measured on the tape at -72% to +2400%. The censored fit uses that count
    as data, so its prediction cannot wander far from it.
    """
    rng = np.random.default_rng(7)
    u, cap = 5e7, 5e8
    sub, n_cap = _lognormal_sample(rng, 17.4, 1.5, u, cap, 200_000)
    w = np.ones_like(sub)

    mu_c, s_c = imp.lognormal_censored_mle(sub, w, u, cap, n_cap)
    mu_t, s_t = imp.lognormal_truncated_mle(sub, w, u, cap)

    pred_c = imp.predicted_capped_count(w.sum(), imp.lognormal_tail_ratio(mu_c, s_c, u, cap))
    pred_t = imp.predicted_capped_count(w.sum(), imp.lognormal_tail_ratio(mu_t, s_t, u, cap))

    assert abs(pred_c / n_cap - 1.0) < 0.05
    # not a claim that the truncation-only fit is useless, a claim that it is
    # unconstrained where it matters: it is the worse of the two on this test.
    assert abs(pred_c / n_cap - 1.0) < abs(pred_t / n_cap - 1.0)


def test_lognormal_mean_above_matches_the_simulated_conditional_mean():
    """E[N | N > C] is the estimand; check it against the sample it came from."""
    rng = np.random.default_rng(11)
    u, cap = 5e7, 5e8
    z = np.exp(rng.normal(17.4, 1.5, 400_000))
    z = z[z >= u]
    sub, above = z[z < cap], z[z >= cap]
    mu, sigma = imp.lognormal_censored_mle(sub, np.ones_like(sub), u, cap, len(above))
    fitted = imp.lognormal_mean_above(mu, sigma, cap)
    assert fitted == pytest.approx(above.mean(), rel=0.05)


def test_pareto_censored_mle_recovers_alpha_where_naive_hill_is_biased():
    """The tail index is reported, so it too has to be right.

    The naive Hill estimator ignores the right truncation at the cap and reads
    the tail as thinner than it is; the censored MLE carries the truncation
    term. If Hill were unbiased here the test would not be exercising the
    correction, so that is asserted as well.
    """
    rng = np.random.default_rng(3)
    u, cap = 5e7, 5e8
    for alpha_true in (0.8, 1.2, 1.8):
        z = u * (rng.random(150_000) ** (-1.0 / alpha_true))
        sub, n_cap = z[z < cap], int((z >= cap).sum())
        w = np.ones_like(sub)
        alpha = imp.pareto_censored_mle(sub, w, u, cap, n_cap)
        hill = len(sub) / np.sum(np.log(sub / u))
        assert alpha == pytest.approx(alpha_true, rel=0.05)
        assert abs(hill - alpha_true) > 0.05 * alpha_true


def test_pareto_truncated_mle_is_the_estimator_that_removes_the_hill_bias():
    """``pareto_truncated_mle``'s docstring advertises +53%/+23%/+6%. Check IT.

    The censored test above recomputes Hill inline and never calls this
    function, so replacing its whole body with naive Hill goes unnoticed --
    which is the same as having no test at all for the correction the docstring
    is selling. Here the function under test is the function called, the
    advertised bias is reproduced from the same samples, and the corrected
    estimate is required to be within 1% of the truth in every case.

    Only the sub-cap sample is passed: this is the truncation-only estimator, so
    the cap-shaped hole is all it has to work with, and the correction term
    ``1 - (u/C)^alpha`` is the only thing that can recover alpha from it.
    """
    rng = np.random.default_rng(3)
    u, cap = 5e7, 5e8
    measured = []
    for alpha_true in (0.8, 1.2, 1.8):
        z = u * (rng.random(400_000) ** (-1.0 / alpha_true))
        sub = z[z < cap]
        w = np.ones_like(sub)
        alpha = imp.pareto_truncated_mle(sub, w, u, cap)
        hill = len(sub) / np.sum(np.log(sub / u))
        measured.append(hill / alpha_true - 1.0)
        assert alpha == pytest.approx(alpha_true, rel=0.01), alpha_true
    # the advertised bias, in the same order: +53% / +23% / +6%
    assert measured == pytest.approx([0.53, 0.23, 0.06], abs=0.03), measured


def test_grouped_frequency_path_equals_the_raw_path():
    """The tape is fed to the fitter as (value, count), not as rows.

    Part 43 notionals are rounded onto a round-number lattice, so the tape
    collapses to a few thousand distinct values and the fit is run weighted.
    Weighted and unweighted must be the same estimator or the whole calibration
    is off by an unknown amount.
    """
    rng = np.random.default_rng(5)
    u, cap = 5e7, 5e8
    z = u * (rng.random(200_000) ** (-1.0 / 1.7))
    sub, n_cap = z[z < cap], int((z >= cap).sum())
    lattice = np.round(sub / 1e6) * 1e6
    lattice = lattice[(lattice >= u) & (lattice < cap)]
    values, counts = np.unique(lattice, return_counts=True)

    a_raw = imp.pareto_censored_mle(lattice, np.ones_like(lattice), u, cap, n_cap)
    a_grp = imp.pareto_censored_mle(values, counts.astype(float), u, cap, n_cap)
    m_raw = imp.lognormal_censored_mle(lattice, np.ones_like(lattice), u, cap, n_cap)
    m_grp = imp.lognormal_censored_mle(values, counts.astype(float), u, cap, n_cap)

    assert a_raw == pytest.approx(a_grp, abs=1e-9)
    e_raw = imp.lognormal_mean_above(*m_raw, cap)
    e_grp = imp.lognormal_mean_above(*m_grp, cap)
    assert e_raw == pytest.approx(e_grp, rel=1e-3)


def test_fit_cell_refuses_a_sample_too_small_to_fit():
    """A cell with no tail is not fitted with a wide prior; it returns nothing."""
    rng = np.random.default_rng(1)
    u, cap = 5e7, 5e8
    z = np.exp(rng.normal(17.0, 1.0, 300))
    sub = z[(z >= u) & (z < cap)][:20]
    assert imp.fit_cell(sub, np.ones_like(sub), u, cap, 3.0) is None


def test_fit_cell_needs_distinct_points_and_not_only_weight():
    """``MIN_TAIL_WEIGHT`` alone is not the guard, and the tape is why.

    Notional lands on a round-number lattice, so a cell can carry thousands of
    prints on three distinct values. Two free parameters fitted to three points
    is a wide prior wearing a large sample size, which is what
    ``MIN_TAIL_POINTS`` is for -- and the weight guard cannot see it.
    """
    u, cap = 5e7, 5e8
    x = np.array([1e8, 2e8, 3e8])
    w = np.array([400.0, 400.0, 400.0])          # 1200 >> MIN_TAIL_WEIGHT
    assert w.sum() > imp.MIN_TAIL_WEIGHT and len(x) < imp.MIN_TAIL_POINTS
    assert imp.fit_cell(x, w, u, cap, 50.0) is None


def test_fit_cell_refuses_a_cell_with_nothing_above_the_cap():
    """``n_cap = 0`` is the censored estimator quietly becoming the rejected one.

    Measured hazard: a cell whose capped prints all land a dollar off C (band
    edge fuzz, or a wrong cap value for the cell) counts zero of them, and the
    "censored" fit then reproduces the truncation-only fit and returns a
    confident multiplier -- with a ``capped_count_error`` of ``predicted / 0``
    to check it with. It has to stop, not warn.
    """
    rng = np.random.default_rng(4)
    u, cap = 5e7, 5e8
    z = np.exp(rng.normal(17.4, 1.5, 50_000))
    sub = z[(z >= u) & (z < cap)]
    with pytest.raises(ValueError, match="censored count"):
        imp.fit_cell(sub, np.ones_like(sub), u, cap, 0.0)
    # ... and the diagnostic that would have divided by it is nan, not a raise
    fit = imp.fit_cell(sub, np.ones_like(sub), u, cap, 100.0)
    assert np.isnan(dataclasses.replace(fit, n_cap=0.0).capped_count_error)


def test_the_censored_mle_will_not_return_an_optimum_that_never_converged():
    """"Still returns numbers" is the failure the refit instructions name.

    Measured over the 103 censored fits of the six-threshold sweep, restricting
    the restart grid to converged runs costs at most 4.7e-10 of negative
    log-likelihood, so the shipped calibration is unchanged by it. The
    truncation-only comparator is the opposite -- its best run is the
    non-converged one in 16 of 103 fits, by up to 6.3e3 -- so it keeps the best
    fit and reports the flag instead. Both halves are asserted, because a guard
    applied to the wrong estimator would silently make the comparator worse.
    """
    rng = np.random.default_rng(6)
    u, cap = 5e7, 5e8
    z = np.exp(rng.normal(17.4, 1.5, 20_000))
    z = z[z >= u]
    sub, n_cap = z[z < cap], float((z >= cap).sum())

    real = imp.optimize.minimize

    def never_converges(*args, **kwargs):
        r = real(*args, **kwargs)
        r.success = False
        r.message = "Maximum number of iterations has been exceeded."
        return r

    imp.optimize.minimize = never_converges
    try:
        with pytest.raises(RuntimeError, match="converged"):
            imp.lognormal_censored_mle(sub, np.ones_like(sub), u, cap, n_cap)
        mu, sigma = imp.lognormal_truncated_mle(sub, np.ones_like(sub), u, cap)
        assert np.isfinite(mu) and np.isfinite(sigma)
    finally:
        imp.optimize.minimize = real


def test_a_lognormal_pinned_on_the_sigma_wall_is_reported_as_degenerate():
    """The flag that decides whether a multiplier can be read as an estimate.

    Feed the fitter what the tape actually hands it in five cells -- a Pareto
    tail, censored at the cap -- and the lognormal has no interior maximum: it
    climbs to ``sigma = LN_SIGMA_MAX`` and stops there because the box says so.
    The multiplier that comes back is a function of the bound, so
    ``ln_degenerate`` must say so; a lognormal sample through the same code path
    must not.
    """
    rng = np.random.default_rng(20260811)
    u, cap = 5e7, 2e8

    z = u * (rng.random(200_000) ** (-1.0 / 1.2))
    sub, n_cap = z[z < cap], float((z >= cap).sum())
    par = imp.fit_cell(sub, np.ones_like(sub), u, cap, n_cap)
    assert par.ln_degenerate is True
    assert par.ln_sigma_censored == pytest.approx(6.0, abs=1e-6)
    assert par.ln_sigma_censored == pytest.approx(imp.LN_SIGMA_MAX, abs=1e-6)

    z = np.exp(rng.normal(17.4, 1.5, 200_000))
    z = z[z >= u]
    sub, n_cap = z[z < cap], float((z >= cap).sum())
    ln = imp.fit_cell(sub, np.ones_like(sub), u, cap, n_cap)
    assert ln.ln_degenerate is False
    assert ln.ln_sigma_censored == pytest.approx(1.5, abs=0.1)


def test_the_degeneracy_detector_watches_every_wall_of_the_box():
    """It watched sigma only, and the wall that bit on the tape was mu's.

    Six of the eighteen shipped cells sat on ``mu = ln(u) - LN_MU_SLACK`` to
    within 4e-7 and every one of them reported ``ln_degenerate = False``,
    because the mu wall stopped the optimiser before sigma could reach its own
    threshold. A detector that cannot fire on the bound that actually binds is
    not a detector.
    """
    u, cap = 5e7, 5e8
    interior = imp._ln_on_box_wall(17.0, 1.5, u, cap)
    assert interior is False
    assert imp._ln_on_box_wall(np.log(u) - imp.LN_MU_SLACK + 1e-9, 1.5, u, cap)
    assert imp._ln_on_box_wall(17.0, 0.99 * imp.LN_SIGMA_MAX, u, cap)
    assert imp._ln_on_box_wall(np.log(cap) + 10.0 - 1e-9, 1.5, u, cap)
    assert imp._ln_on_box_wall(17.0, np.exp(-3.0) * 1.001, u, cap)


def test_lognormal_cdf_truncated_is_renormalised_onto_the_window():
    """Without the renormalisation this is a lognormal cdf, and KS is nonsense.

    Checked against the empirical cdf of a sample drawn and then truncated the
    same way, which does not reuse the formula: at ``u`` it must be 0 and just
    below ``C`` it must be 1, and in between it must track the sample.
    """
    rng = np.random.default_rng(21)
    mu, sigma, u, cap = 17.4, 1.5, 5e7, 5e8
    z = np.exp(rng.normal(mu, sigma, 400_000))
    win = np.sort(z[(z >= u) & (z < cap)])

    assert imp.lognormal_cdf_truncated(u, mu, sigma, u, cap) == pytest.approx(0.0, abs=1e-12)
    assert imp.lognormal_cdf_truncated(cap * (1 - 1e-12), mu, sigma, u, cap) == \
        pytest.approx(1.0, abs=1e-6)
    for q in (7e7, 1e8, 2e8, 4e8):
        empirical = float(np.searchsorted(win, q, side="right")) / len(win)
        assert imp.lognormal_cdf_truncated(q, mu, sigma, u, cap) == \
            pytest.approx(empirical, abs=0.005), q


def test_pareto_cdf_truncated_is_renormalised_onto_the_window():
    """Same for the comparator: the truncation denominator is load-bearing."""
    rng = np.random.default_rng(22)
    alpha, u, cap = 1.4, 5e7, 5e8
    z = u * (rng.random(400_000) ** (-1.0 / alpha))
    win = np.sort(z[z < cap])

    assert imp.pareto_cdf_truncated(u, alpha, u, cap) == pytest.approx(0.0, abs=1e-12)
    assert imp.pareto_cdf_truncated(cap, alpha, u, cap) == pytest.approx(1.0, abs=1e-12)
    for q in (7e7, 1e8, 2e8, 4e8):
        empirical = float(np.searchsorted(win, q, side="right")) / len(win)
        assert imp.pareto_cdf_truncated(q, alpha, u, cap) == \
            pytest.approx(empirical, abs=0.005), q


def test_weighted_ks_measures_both_sides_of_every_step():
    """A one-sided KS is half a statistic, and on a lattice it is the wrong half.

    Notional is rounded onto round numbers, so the empirical cdf is a staircase
    with tall steps and the fitted cdf can pass through the middle of one. The
    distance that matters is then to the *lower* edge, which is exactly the arm
    an implementation drops when it computes ``max|upper - F|`` alone. Three
    equally weighted points and a cdf laid exactly on the upper edges: the true
    two-sided statistic is 1/3 and the one-armed one is 0.
    """
    x = np.array([1.0, 2.0, 3.0])
    w = np.ones(3)
    assert imp.weighted_ks(x, w, lambda q: np.array([1, 2, 3.0]) / 3.0) == \
        pytest.approx(1.0 / 3.0)
    assert imp.weighted_ks(x, w, lambda q: np.array([0, 1, 2.0]) / 3.0) == \
        pytest.approx(1.0 / 3.0)
    # and the weights are counts: grouped must equal repeated
    xr = np.array([1.0, 1.0, 2.0, 3.0])
    assert imp.weighted_ks(xr, np.ones(4), lambda q: np.searchsorted(
        [1.0, 1.0, 2.0, 3.0], q, side="right") / 4.0) == pytest.approx(
        imp.weighted_ks(x, np.array([2.0, 1.0, 1.0]), lambda q: np.searchsorted(
            [1.0, 1.0, 2.0, 3.0], q, side="right") / 4.0))
    with pytest.raises(ValueError):
        imp.weighted_ks(x, np.zeros(3), lambda q: np.zeros_like(q))


def test_pareto_tail_ratio_is_the_survival_ratio_and_not_its_inverse():
    """``S(C)/S(u) = (u/C)^alpha`` is a probability; inverted it is 1/p."""
    assert imp.pareto_tail_ratio(2.0, 1e8, 1e9) == pytest.approx(0.01)
    assert imp.pareto_tail_ratio(0.5, 1e8, 1e9) == pytest.approx(10.0 ** -0.5)
    for alpha in (0.5, 1.0, 2.0, 4.0):
        assert 0.0 < imp.pareto_tail_ratio(alpha, 1e8, 1e9) < 1.0


def test_fit_frequency_table_refits_a_known_tape_cell_by_cell():
    """The function that produces a calibration, against a known answer.

    Nothing exercised this before, so a refit could key every cell to ``V1``,
    fit at the wrong threshold, or return an estimator nobody asked for, and the
    check the module's own docstring tells a refitter to run would stay green.
    Three simulated cells across two vintages, lattice-rounded the way the tape
    is: the keys, the threshold and the recovered multipliers are all asserted.
    """
    rng = np.random.default_rng(20260811)
    spec = {("V1", 0.0): (4e8, 18.0, 1.1), ("V1", 2.0): (2e8, 17.4, 1.2),
            ("V2", 0.0): (8e8, 18.6, 1.1)}
    rows = []
    for (vintage, lo), (cap, mu, sigma) in spec.items():
        z = np.exp(rng.normal(mu, sigma, 60_000))
        lattice = np.round(z[z < cap] / 1e6) * 1e6
        vals, cnts = np.unique(lattice[lattice > 0], return_counts=True)
        rows += [{"vintage": vintage, "lo": lo, "cap": cap, "notional": float(v),
                  "is_capped": False, "n": int(c)} for v, c in zip(vals, cnts)]
        rows.append({"vintage": vintage, "lo": lo, "cap": cap, "notional": cap,
                     "is_capped": True, "n": int((z >= cap).sum())})

    fits = imp.fit_frequency_table(pd.DataFrame(rows))

    assert set(fits) == set(spec), "a cell is keyed by (vintage, lo), both of them"
    for key, (cap, mu, sigma) in spec.items():
        fit = fits[key]
        assert fit.u == pytest.approx(cap / 4.0), "u = C/THRESHOLD_DIVISOR"
        truth = imp.lognormal_mean_above(mu, sigma, cap) / cap
        assert fit.multiplier == pytest.approx(truth, rel=0.06), key
        assert abs(fit.capped_count_error) < 0.05, key
        assert fit.ln_degenerate is False


def test_fit_frequency_table_names_the_cells_it_could_not_fit():
    """A partial refit must not look like a complete one.

    16 of 18 cells returned in a dict of 16 is indistinguishable from 16 of 16,
    and "no fit" read as "no imputation" is precisely the misreading the
    ``>30y`` band's own docstring warns about. So the skip is a warning that
    names the cell, and a table where nothing fits at all is an error.
    """
    good = {"vintage": "V1", "lo": 0.0, "cap": 4e8}
    rng = np.random.default_rng(9)
    z = np.exp(rng.normal(18.0, 1.1, 40_000))
    lattice = np.round(z[z < 4e8] / 1e6) * 1e6
    vals, cnts = np.unique(lattice[lattice > 0], return_counts=True)
    rows = [dict(good, notional=float(v), is_capped=False, n=int(c))
            for v, c in zip(vals, cnts)]
    rows.append(dict(good, notional=4e8, is_capped=True, n=int((z >= 4e8).sum())))
    thin = [{"vintage": "V1", "lo": 9.0, "cap": 1e8, "notional": 3e7,
             "is_capped": False, "n": 4},
            {"vintage": "V1", "lo": 9.0, "cap": 1e8, "notional": 1e8,
             "is_capped": True, "n": 7}]

    with pytest.warns(RuntimeWarning, match=r"lo=9\.0"):
        fits = imp.fit_frequency_table(pd.DataFrame(rows + thin))
    assert set(fits) == {("V1", 0.0)}

    with pytest.warns(RuntimeWarning), pytest.raises(ValueError, match="no cell"):
        imp.fit_frequency_table(pd.DataFrame(thin))


def test_fit_frequency_table_stops_when_a_cell_has_capped_prints_off_its_cap():
    """Capped prints that never sit on C mean the cell's cap value is wrong.

    Not the same case as an uncensored cell: here the tape says 900 prints were
    capped and the schedule says the cap is somewhere they are not. Counting
    zero of them and fitting anyway returns a multiplier for a cap that did not
    apply.
    """
    cell = {"vintage": "V1", "lo": 0.0, "cap": 4e8}
    rows = [dict(cell, notional=1.5e8, is_capped=False, n=900),
            dict(cell, notional=2.5e8, is_capped=False, n=400),
            dict(cell, notional=4e8 - 1.0, is_capped=True, n=900)]
    with pytest.raises(ValueError, match="censored count"):
        imp.fit_frequency_table(pd.DataFrame(rows))


# --------------------------------------------------------------------------
# 2. The infinite-mean trap, kept visible.
# --------------------------------------------------------------------------

def test_pareto_mean_is_infinite_below_alpha_one_and_says_so():
    """alpha <= 1 has no mean. It is reported as inf, never as a number."""
    assert imp.pareto_mean_above(0.75, 1e8) == float("inf")
    assert imp.pareto_mean_above(1.0, 1e8) == float("inf")
    assert np.isfinite(imp.pareto_mean_above(1.4, 1e8))
    assert imp.pareto_mean_above(2.0, 1e8) == pytest.approx(2e8)


def test_the_band_flag_agrees_with_the_estimator_at_alpha_exactly_one():
    """``alpha == 1`` is the boundary and it is on the no-mean side.

    No shipped band sits exactly on 1.0, so a flag written ``>= 1.0`` would
    disagree with :func:`pareto_mean_above` only at the one point that decides
    whether the estimand exists -- and nothing on the tape would notice.
    """
    band = dataclasses.replace(imp.CAP_BANDS[0], tail_index=1.0)
    assert band.tail_mean_exists is False
    assert imp.pareto_mean_above(band.tail_index, band.cap) == float("inf")
    assert dataclasses.replace(band, tail_index=1.0 + 1e-12).tail_mean_exists is True


def test_every_band_reports_a_tail_index_and_whether_its_mean_exists():
    """Requirement: report the fitted tail index and state if the mean exists.

    The trap fired at u = C/10 (alpha < 1 in 10 of 18 cells) and has not fully
    cleared at the shipped u = C/4: two short-tenor V1 cells still sit below 1.
    That is a statement about ``[u, C)`` being the *body* of the distribution,
    not about a monstrous tail -- and it does not touch the lognormal headline,
    which is why both numbers travel together on every band.
    """
    below_one = [b for b in imp.CAP_BANDS if b.tail_index <= 1.0]
    assert [b.vintage + " " + b.label for b in below_one] == ["V1 <=46d", "V1 46d-3m"]
    for band in imp.CAP_BANDS:
        assert band.tail_index > 0.0
        # the property is a restatement of its own body, so check the thing it
        # is a proxy for instead: whether the Pareto estimand exists at all
        finite = bool(np.isfinite(imp.pareto_mean_above(band.tail_index, band.cap)))
        assert band.tail_mean_exists is finite, band.label
        if finite:
            assert imp.pareto_mean_above(band.tail_index, band.cap) > band.cap


# --------------------------------------------------------------------------
# 3. The frozen calibration is what was measured.
# --------------------------------------------------------------------------

def test_frozen_multiplier_is_recomputable_from_the_stored_parameters():
    """A mis-transcribed multiplier is invisible; a recomputed one is not.

    ``multiplier = E[N | N > C] / C`` is a deterministic function of the stored
    ``(mu, sigma, cap)``, so storing all four lets the table check itself.
    """
    for band in imp.CAP_BANDS:
        recomputed = imp.lognormal_mean_above(band.ln_mu, band.ln_sigma, band.cap) / band.cap
        assert recomputed == pytest.approx(band.multiplier, rel=1e-3), band.label


def test_the_calibration_covers_the_measured_schedule():
    """Nine bands, two vintages, distinct caps within a vintage."""
    assert len(imp.CAP_BANDS) == 18
    for vintage in (imp.VINTAGE_V1, imp.VINTAGE_V2):
        bands = imp.bands_for_vintage(vintage)
        assert len(bands) == 9
        caps = [b.cap for b in bands]
        assert len(set(caps)) == 9, "notional-matching needs caps unique per vintage"
        assert caps == sorted(caps, reverse=True), "cap falls monotonically in tenor"
        los = [b.lo for b in bands]
        assert los == sorted(los) and los[0] == 0.0


def test_every_multiplier_is_above_one_and_not_absurd():
    """An imputed size below the cap would contradict the censoring itself.

    The upper guard is the measured range (1.64-4.22); anything outside it means
    the fit collapsed onto a power-law mimic and extrapolated *further* than the
    five cells that already have, which is what ``ln_degenerate`` reports.
    """
    for band in imp.CAP_BANDS:
        assert 1.0 < band.multiplier < 5.0, band.label
        assert band.expected_notional == pytest.approx(band.multiplier * band.cap)


def test_no_shipped_fit_is_standing_on_the_mu_wall():
    """The shipped estimate must be a fit, not a numerical guard.

    Six of the eighteen cells used to sit on ``mu = ln(u) - LN_MU_SLACK`` to
    within 4.4e-7, so their multipliers were a function of that constant: V1
    5y-10y read 3.954 at slack 30 and 4.218 once the wall was moved out of the
    way (where it stays put at 60, 150 and 300). Any cell within 1.0 of the wall
    again means the box is deciding the answer, and the fix is to widen the box,
    not to widen this test.
    """
    for band in imp.CAP_BANDS:
        u = band.cap / imp.THRESHOLD_DIVISOR
        assert band.ln_mu - (np.log(u) - imp.LN_MU_SLACK) > 1.0, band.label
        assert np.log(band.cap) + 10.0 - band.ln_mu > 1.0, band.label


def test_the_shipped_table_says_which_cells_are_bound_determined():
    """``ln_degenerate`` travels with the calibration or it protects nobody.

    ``CellFit`` carried the flag and ``CapBand`` did not, so the shipped table
    could not surface it even when it fired. It fires in five cells -- the ones
    whose censored fit is pinned at ``sigma = LN_SIGMA_MAX``, i.e. a lognormal
    imitating a power law -- and those five carry 55.3% of the imputed excess
    DV01, which is the reason it has to be visible rather than inferable.
    """
    pinned = [b for b in imp.CAP_BANDS if b.ln_sigma > 0.98 * imp.LN_SIGMA_MAX]
    assert [b.vintage + " " + b.label for b in pinned] == [
        "V1 3m-6m", "V1 5y-10y", "V2 <=46d", "V2 3m-6m", "V2 5y-10y"]
    for band in imp.CAP_BANDS:
        assert band.ln_degenerate == (band in pinned), band.label
        assert band.ln_sigma <= imp.LN_SIGMA_MAX + 1e-9, band.label
    for band in pinned:
        assert band.ln_sigma == pytest.approx(6.0, abs=1e-6)


def test_the_fit_reproduces_the_capped_count_in_every_cell():
    """The censored fit's own test, carried as a stored diagnostic.

    +-19% in every cell at u = C/4. If a future refit widens this, the number
    moves here first and the failure is loud.
    """
    for band in imp.CAP_BANDS:
        assert abs(band.capped_count_error) <= 0.19, band.label


def test_headline_shares_sit_inside_the_quoted_sensitivity_band():
    lo, hi = imp.SENSITIVITY_DV01_SHARE
    assert lo < imp.IMPUTED_DV01_SHARE <= hi
    lo_n, hi_n = imp.SENSITIVITY_NOTIONAL_SHARE
    assert lo_n < imp.IMPUTED_NOTIONAL_SHARE <= hi_n
    # per bucket too -- these two dicts had no assertion at all, and a bucket
    # headline outside its own threshold range is a transcription error
    assert set(imp.IMPUTED_SHARE_BY_BUCKET) == set(imp.SENSITIVITY_DV01_SHARE_BY_BUCKET)
    for bucket, (_, dv01) in imp.IMPUTED_SHARE_BY_BUCKET.items():
        blo, bhi = imp.SENSITIVITY_DV01_SHARE_BY_BUCKET[bucket]
        assert blo <= dv01 <= bhi, bucket
        assert blo < bhi, bucket


def test_the_headline_satisfies_its_own_model_free_cross_check():
    """The docstring's arithmetic, executed instead of asserted.

    ``share = (k-1)·c / (1 + (k-1)·c)`` ties three separately measured numbers
    together: the DV01 the capped prints carry at the cap value (c = 14.17%,
    one query, no likelihood), the DV01-weighted effective multiplier the fit
    implies (k = 2.37), and the imputed share (16.22%). Editing any one of them
    without the other two -- which is what happens when a headline is updated by
    hand after a refit -- breaks the identity.

    The frequency-table population gives 15.97% against the leg-by-leg 16.22%;
    the two differ by 1.96% of legs and 0.25pp of headline, which is the
    coverage difference and not a coding accident, so they are required to agree
    to half a point and no closer.
    """
    c, k = imp.CAPPED_AT_CAP_DV01_SHARE, imp.EFFECTIVE_MULTIPLIER
    implied = (k - 1.0) * c / (1.0 + (k - 1.0) * c)
    assert implied == pytest.approx(imp.IMPUTED_DV01_SHARE_LEG_BY_LEG, abs=5e-4)
    assert imp.IMPUTED_DV01_SHARE == pytest.approx(
        imp.IMPUTED_DV01_SHARE_LEG_BY_LEG, abs=0.005)
    # the flat-multiplier reference points quoted in the docstring
    assert (1.0 * c) / (1.0 + 1.0 * c) == pytest.approx(0.124, abs=5e-4)
    assert (1.1 * c) / (1.0 + 1.1 * c) == pytest.approx(0.135, abs=5e-4)


def test_the_two_families_fail_about_equally_so_the_band_is_within_family():
    """The quoted band is threshold sensitivity, and that is not the big risk.

    Absolute KS is 0.07-0.29 for the lognormal *and* the Pareto -- notional is
    rounded onto a round-number lattice and no continuous law fits a lattice --
    and at the shipped u = C/4 the Pareto is the closer of the two in 9 of 18
    cells, by at most 0.036. So the family choice is not an empirical win, and
    the sensitivity band does not contain the uncertainty it creates. Both
    statistics are stored per band so this stays checkable rather than asserted
    in prose.

    The numbers moved when the mu wall came off (7/9/2 from 6/10/2, worst gap
    0.035 from 0.020): both KS statistics are taken against the truncation-only
    fits, and two of those were on the wall too. The direction of the finding
    did not move -- the lognormal is still not the better fit, it just fails
    slightly differently.
    """
    ks_ln = [b.ks_lognormal for b in imp.CAP_BANDS]
    ks_par = [b.ks_pareto for b in imp.CAP_BANDS]
    for series in (ks_ln, ks_par):
        assert 0.069 <= min(series) and max(series) <= 0.287

    lognormal_wins = sum(a < b for a, b in zip(ks_ln, ks_par))
    pareto_wins = sum(b < a for a, b in zip(ks_ln, ks_par))
    assert (lognormal_wins, pareto_wins) == (7, 9), \
        "at u=C/4 the lognormal is NOT the better KS fit"
    assert max(abs(a - b) for a, b in zip(ks_ln, ks_par)) < 0.036


def test_direction_neutrality_is_recorded_as_unresolved_not_as_neutral():
    """Requirement 5: capped x direction, and what the answer actually was.

    Two odds ratios are stored because two methods disagree: the curve-based
    classifiers say capped prints are 1.34x more likely to be labelled RECEIVED
    (CI excludes 1), the curve-free tick rule says 0.88 (CI includes 1). Their
    intervals do not overlap, so this is not one estimate with noise around it,
    and the module must not be read as having shown neutrality. The assertion
    below is the disagreement itself: if a future measurement makes the two
    agree, this fails and the docstring gets rewritten deliberately.
    """
    curve_or, curve_lo, curve_hi = imp.CAPPED_RECEIVED_ODDS_RATIO_CURVE_BASED
    tick_or, tick_lo, tick_hi = imp.CAPPED_RECEIVED_ODDS_RATIO_CURVE_FREE

    assert curve_lo > 1.0, "the curve-based 2x2 does show a skew"
    assert tick_lo < 1.0 < tick_hi, "the curve-free 2x2 does not"
    assert tick_hi < curve_lo, "the two intervals must be disjoint for the claim to hold"
    assert 0.0 < imp.UNCLASSIFIABLE_SHARE_OF_IMPUTED_DV01 < 0.10
    assert imp.IMPUTED_SHARE_OF_UNCLASSIFIABLE_DV01 > 0.25, (
        "the overlap is the point: most unclassifiable DV01 is capped DV01")


# --------------------------------------------------------------------------
# 4. The schedule lookup.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("day", "vintage"),
    [
        (datetime.date(2024, 3, 1), imp.VINTAGE_V1),
        (datetime.date(2024, 10, 4), imp.VINTAGE_V1),   # last V1 print
        (datetime.date(2024, 10, 5), imp.VINTAGE_V1),   # the weekend between
        (datetime.date(2024, 10, 6), imp.VINTAGE_V1),
        (datetime.date(2024, 10, 7), imp.VINTAGE_V2),   # first V2 print
        (datetime.date(2026, 8, 7), imp.VINTAGE_V2),
    ],
)
def test_vintage_boundary_is_the_measured_changeover(day, vintage):
    """Measured: last V1 print 2024-10-04, first V2 print 2024-10-07, no overlap."""
    assert imp.vintage_for(day) == vintage


def test_cap_lookup_is_total_over_tenor():
    """Every tenor gets a cap.

    The empirically merged bands have holes (V1 10.5-10.75, nothing capped
    beyond 41y) because bins with n < 25 were dropped. A lookup with a hole in
    it returns None on a live print, so the bands are contiguous by
    construction: each runs from its own ``lo`` to the next band's, the last one
    to infinity.
    """
    for day in (datetime.date(2024, 5, 1), datetime.date(2025, 5, 1)):
        for tenor in (0.003, 0.12, 0.5, 1.0, 2.0, 2.25, 10.6, 30.0, 41.5, 60.0):
            cap = imp.cap_for(tenor, day)
            assert cap is not None and cap > 0


@pytest.mark.parametrize("bad", [None, float("nan"), -1.0, "7y"])
def test_a_tenor_that_is_not_a_tenor_is_a_value_error(bad):
    """The guard says ValueError; ``np.isfinite(None)`` says TypeError.

    A caller with a missing tenor gets whichever exception the first operation
    happens to raise, and only one of them is the one the message documents.
    """
    with pytest.raises(ValueError):
        imp.band_for_tenor(bad, datetime.date(2025, 5, 1))


def test_cap_falls_with_tenor_and_rose_at_the_2024_recalibration():
    """Both directions of the measured schedule, on one assertion each."""
    day1, day2 = datetime.date(2024, 5, 1), datetime.date(2025, 5, 1)
    assert imp.cap_for(0.05, day1) == 6.4e9
    assert imp.cap_for(0.05, day2) == 17e9
    assert imp.cap_for(7.0, day1) == 170e6
    assert imp.cap_for(7.0, day2) == 470e6
    caps = [imp.cap_for(t, day2) for t in (0.05, 0.2, 0.4, 0.8, 1.5, 3.0, 7.0, 20.0, 35.0)]
    assert caps == sorted(caps, reverse=True)


def test_the_tenor_mismatch_flag_fires_on_the_measured_edge_case():
    """1.92% of capped legs have keys that disagree, and they are surfaced.

    A V1 print at $170mm (the 5y-10y cap) with a tenor of 25y is a real row on
    the tape, not a hypothetical -- 173 legs carry that cap at tenors from 5.06
    to 25.02 years. It is still imputed, off the cap that was actually applied,
    but a consumer restricting to the fit's own population needs to see it.
    """
    legs = pd.DataFrame({
        "notional": [170e6, 170e6],
        "as_of_date": [datetime.date(2024, 5, 1)] * 2,
        "tenor_years": [7.0, 25.0],
        "is_capped": [True, True],
    })
    out = imp.impute_frame(legs)
    assert list(out["notional_imputed"]) == [True, True]
    assert list(out["notional_impute_factor"]) == [pytest.approx(4.2176, abs=1e-3)] * 2
    assert bool(out.loc[0, "notional_cell_tenor_mismatch"]) is False
    assert bool(out.loc[1, "notional_cell_tenor_mismatch"]) is True
    # and it is absent, not guessed, when there is no tenor column
    assert "notional_cell_tenor_mismatch" not in imp.impute_frame(
        legs.drop(columns="tenor_years")).columns


def test_a_capped_print_is_identified_by_its_notional_not_its_tenor():
    """Measured: 68,945 of 68,946 capped prints sit exactly on a schedule value.

    The tenor edges are fuzzy where the regulator's tenor and the tape's
    date-derived ``tenor_years`` disagree -- six V1 prints at 11.008y carry the
    5y-10y cap of $170mm, and two at 31.5y carry the 10y-30y cap. The printed
    notional IS the cap, so it is the identifier; tenor is the fallback.
    """
    day = datetime.date(2024, 5, 1)
    band = imp.band_for_capped_notional(170e6, day)
    assert band is not None and band.cap == 170e6
    assert imp.band_for_tenor(11.008, day).cap == 120e6      # tenor disagrees
    assert imp.tenor_band_agrees(170e6, 11.008, day) is False
    assert imp.tenor_band_agrees(170e6, 7.0, day) is True


def test_an_unrecognised_cap_value_is_flagged_not_scaled():
    """The one measured exception: a $78,613,002 print flagged capped on
    2025-09-17 at 0.25y, where the V2 cap is $7.5bn. Nothing about that print
    says how it was censored, so it is not imputed -- it is named.
    """
    r = imp.impute(78_613_002.0, datetime.date(2025, 9, 17), is_capped=True,
                   tenor_years=0.246575)
    assert r.notional_imputed is False
    assert r.notional_impute_factor is None
    assert r.reason == imp.REASON_CAP_UNRECOGNISED


# --------------------------------------------------------------------------
# 5. Application: flag, never silently substitute.
# --------------------------------------------------------------------------

def test_an_uncapped_leg_is_untouched():
    r = imp.impute(250e6, datetime.date(2025, 5, 1), is_capped=False, tenor_years=7.0)
    assert r.notional_imputed is False
    assert r.notional_impute_factor is None
    assert r.expected_notional is None
    assert r.reason == imp.REASON_NOT_CAPPED


def test_a_capped_leg_carries_its_multiplier_and_the_tail_index():
    r = imp.impute(470e6, datetime.date(2025, 5, 1), is_capped=True, tenor_years=7.0)
    assert r.notional_imputed is True
    assert r.notional_impute_factor > 1.0
    assert r.expected_notional == pytest.approx(r.notional_impute_factor * 470e6)
    assert r.tail_index > 0
    # "in (True, False)" is true of every bool; the claim is that the flag is
    # the band's, and that it answers the question it names
    assert r.tail_mean_exists is (r.tail_index > 1.0)
    assert r.tail_index == imp.band_for_capped_notional(
        470e6, datetime.date(2025, 5, 1)).tail_index
    assert r.reason == imp.REASON_IMPUTED


def test_the_imputation_fields_are_the_provenance_fields():
    """The audit trail is the point: a consumer must be able to drop these rows.

    ``types.Provenance`` already declares ``notional_imputed`` and
    ``notional_impute_factor``; if the imputation ever stopped filling exactly
    those, the flag would go missing and the substitution would be silent.
    """
    r = imp.impute(470e6, datetime.date(2025, 5, 1), is_capped=True, tenor_years=7.0)
    fields = r.provenance_fields()
    assert set(fields) == {"notional_imputed", "notional_impute_factor"}
    prov = ddt.Provenance(
        unit_key="u", curve_name="c", curve_timestamp=pd.Timestamp("2025-05-01"),
        snapshot_lag_seconds=60.0, snapshot_policy="STRICT",
        pricing_clock_field="execution_timestamp", rule="RATE_VS_MID",
        risk_sanity_reason=None, tau_bucket=None, code_vintage="test", **fields)
    assert prov.notional_imputed is True
    assert prov.notional_impute_factor == r.notional_impute_factor


def test_impute_frame_adds_columns_and_never_edits_notional():
    """Requirement 3 mechanically: the imputed value lives in its own column.

    Row 2 is the vintage guard doing its job. $120mm IS a cap -- the V1 10y-30y
    one -- but on 2025-05-01 the schedule in force is V2, where the 10y-30y cap
    is $250mm. A lookup that ignored the date would happily impute it at 1.99x.
    """
    legs = pd.DataFrame({
        "notional": [470e6, 250e6, 120e6, 78_613_002.0],
        "as_of_date": [datetime.date(2025, 5, 1)] * 3 + [datetime.date(2025, 9, 17)],
        "tenor_years": [7.0, 20.0, 20.0, 0.246575],
        "is_capped": [True, False, True, True],
    })
    before = legs["notional"].copy()
    out = imp.impute_frame(legs)

    pd.testing.assert_series_equal(out["notional"], before)
    assert list(out["notional_imputed"]) == [True, False, False, False]
    assert list(out["notional_impute_reason"]) == [
        imp.REASON_IMPUTED, imp.REASON_NOT_CAPPED,
        imp.REASON_CAP_UNRECOGNISED, imp.REASON_CAP_UNRECOGNISED]
    assert np.isnan(out.loc[1, "notional_impute_factor"])
    assert np.isnan(out.loc[2, "notional_impute_factor"])
    assert out.loc[0, "notional_expected_reporting_only"] > out.loc[0, "notional"]
    # the tenor cross-check rides along when a tenor column is there: row 0 is
    # a 7y print at the V2 5y-10y cap, so its two keys agree
    assert out.loc[0, "notional_cell_tenor_mismatch"] is np.False_ or (
        out.loc[0, "notional_cell_tenor_mismatch"] is False)
    assert pd.isna(out.loc[1, "notional_cell_tenor_mismatch"]), "only imputed rows"
    # and the same frame through the scalar path, row for row -- including the
    # factor, where the two paths deliberately differ in spelling: a float
    # column cannot hold None, so the frame says NaN where the scalar says None
    for i, row in legs.iterrows():
        scalar = imp.impute(row["notional"], row["as_of_date"], row["is_capped"])
        assert scalar.notional_imputed == out.loc[i, "notional_imputed"]
        assert scalar.reason == out.loc[i, "notional_impute_reason"]
        if scalar.notional_impute_factor is None:
            assert pd.isna(out.loc[i, "notional_impute_factor"])
            assert pd.isna(out.loc[i, "notional_expected_reporting_only"])
        else:
            assert scalar.notional_impute_factor == pytest.approx(
                out.loc[i, "notional_impute_factor"])
            assert scalar.expected_notional == pytest.approx(
                out.loc[i, "notional_expected_reporting_only"])
        # ... and both spellings are refused by the only sanctioned application
        with pytest.raises(ValueError):
            imp.apply_to_signed_krd({"5Y": 1.0}, None)
        with pytest.raises(ValueError):
            imp.apply_to_signed_krd({"5Y": 1.0}, float("nan"))


def test_the_multiplier_is_applied_to_the_signed_krd_not_to_notional():
    """Requirement 4, and the reason the module has no notional-scaling helper.

    ``risk`` and any repriced KRD are computed FROM the capped notional, so they
    carry the same right-censoring. Scaling notional first and then pricing runs
    the multiplier through the pricing path a second time.
    """
    krd = {"2Y": -1200.0, "5Y": 0.0, "10Y": 3400.0}
    scaled = imp.apply_to_signed_krd(krd, 2.5)
    assert scaled == {"2Y": -3000.0, "5Y": 0.0, "10Y": 8500.0}
    assert krd == {"2Y": -1200.0, "5Y": 0.0, "10Y": 3400.0}, "must not mutate"

    arr = np.array([-1200.0, 0.0, 3400.0])
    np.testing.assert_allclose(imp.apply_to_signed_krd(arr, 2.5), arr * 2.5)

    # sign is direction, set before this point, and the multiplier cannot move it
    for factor in (1.0, 1.7, 4.0):
        out = imp.apply_to_signed_krd(krd, factor)
        assert [np.sign(v) for v in out.values()] == [np.sign(v) for v in krd.values()]


@pytest.mark.parametrize("bad", [None, 0.0, 0.9, -2.0, float("nan")])
def test_apply_to_signed_krd_rejects_a_factor_that_is_not_an_imputation(bad):
    """A factor below 1 would shrink a censored position. There is no such case."""
    with pytest.raises(ValueError):
        imp.apply_to_signed_krd({"5Y": 100.0}, bad)


def test_no_column_is_notional_times_multiplier_without_saying_so():
    """The double-count vector, found by its VALUE rather than by its name.

    The old version of this test grepped ``dir(imp)`` for ``scale_notional`` and
    ``apply_to_notional``. It could not fail -- and it did not fail on the
    column that was there: ``impute_frame`` shipped ``notional_expected``,
    literally ``notional × multiplier``, one ``df[...]`` away from the pricing
    path the module docstring says it must never reach. Pricing off it and then
    calling :func:`apply_to_signed_krd` squares the correction.

    So the assertion is on the numbers: any added column that equals
    ``notional × factor`` on the imputed rows must carry ``reporting_only`` in
    its name. Re-adding the hazard under any innocuous spelling fails here,
    which a name grep cannot do.
    """
    legs = pd.DataFrame({
        "notional": [470e6, 250e6, 120e6],
        "as_of_date": [datetime.date(2025, 5, 1)] * 3,
        "tenor_years": [7.0, 20.0, 20.0],
        "is_capped": [True, False, True],
    })
    out = imp.impute_frame(legs)
    imputed = out["notional_imputed"].to_numpy(dtype=bool)
    product = (out["notional"].to_numpy(float)
               * out["notional_impute_factor"].to_numpy(float))[imputed]
    assert np.isfinite(product).all() and (product > 0).all(), "nothing to detect"

    hazards = []
    for col in set(out.columns) - set(legs.columns) - {"notional_impute_factor"}:
        values = pd.to_numeric(out[col], errors="coerce").to_numpy(float)[imputed]
        if np.allclose(values, product, rtol=1e-12, equal_nan=False):
            hazards.append(col)
    assert hazards, "the expected-notional column vanished; check the rename"
    for col in hazards:
        assert "reporting_only" in col, (
            f"{col!r} is notional x multiplier under a name a consumer would "
            "feed to a pricer")

    # and there is still no function that does it either
    for name in dir(imp):
        if not name.startswith("_"):
            assert "scale_notional" not in name
            assert not name.startswith("apply_to_notional")
