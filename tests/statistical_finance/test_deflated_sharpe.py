"""Deflated Sharpe — checked against cases whose answer is known before the code runs.

The test that matters is the last one: a search over many pure-noise strategies must NOT be
certified. If `deflated_sharpe_of_best` blesses the best of 300 random walks, it is worse than
useless, because that is exactly the situation it exists to catch.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from RVUtils.StatisticalFinance.deflated_sharpe import (EULER_MASCHERONI, deflated_sharpe_from_sharpes,
                                                        deflated_sharpe_of_best,
                                                        deflated_sharpe_ratio, effective_trials,
                                                        expected_max_sharpe,
                                                        min_track_record_length,
                                                        probabilistic_sharpe_ratio, sharpe_moments)


# ============================ THE PUBLISHED WORKED EXAMPLE ============================
# Bailey & Lopez de Prado (2014), pp.9-10. A strategist reports an annualised SR of 2.5 over 5
# years of daily data (T=1250, 250/yr) with skew -3 and kurtosis 10, after N=100 trials whose
# annualised Sharpes had variance 1/2. The paper prints SR0 = 0.1132 and DSR = 0.9004, then says
# N=46 would have given 0.9505, and that with NORMAL moments it would have taken N=88 to reach the
# same 0.9505. Reproducing all four pins the entire chain -- Eq.1, Eq.2, the units conversion and
# the non-excess kurtosis convention -- against a source outside this repository.
#
# Note the unit handling: the Sharpe divides by sqrt(250) but the VARIANCE divides by 250.
_PAPER = dict(sharpe=2.5 / np.sqrt(250), var=0.5 / 250, n_obs=1250, skew=-3.0, kurtosis=10.0)


def test_paper_worked_example_sr0():
    assert expected_max_sharpe(100, _PAPER["var"]) == pytest.approx(0.1132, abs=5e-5)


def test_paper_worked_example_dsr():
    sr0 = expected_max_sharpe(100, _PAPER["var"])
    got = probabilistic_sharpe_ratio(_PAPER["sharpe"], n_obs=_PAPER["n_obs"], skew=_PAPER["skew"],
                                     kurtosis=_PAPER["kurtosis"], benchmark=sr0)
    assert got == pytest.approx(0.9004, abs=5e-5)


def test_paper_worked_example_n46_reaches_the_95_threshold():
    sr0 = expected_max_sharpe(46, _PAPER["var"])
    got = probabilistic_sharpe_ratio(_PAPER["sharpe"], n_obs=_PAPER["n_obs"], skew=_PAPER["skew"],
                                     kurtosis=_PAPER["kurtosis"], benchmark=sr0)
    assert got == pytest.approx(0.9505, abs=5e-5)


def test_paper_worked_example_normal_moments_tolerate_n88():
    """Same 0.9505 with gamma3=0, gamma4=3 -- this is what pins the NON-excess convention.

    Passing excess kurtosis (0.0) here instead of 3.0 moves the answer off 0.9505, so a
    convention slip cannot survive this test.
    """
    sr0 = expected_max_sharpe(88, _PAPER["var"])
    got = probabilistic_sharpe_ratio(_PAPER["sharpe"], n_obs=_PAPER["n_obs"], skew=0.0,
                                     kurtosis=3.0, benchmark=sr0)
    assert got == pytest.approx(0.9505, abs=5e-5)


# ------------------------------------------------------------------ moments
def test_moments_of_a_normal_sample_are_the_normal_values():
    r = stats.norm.rvs(loc=0.01, scale=0.1, size=20_000, random_state=1)
    m = sharpe_moments(r)
    assert m["skew"] == pytest.approx(0.0, abs=0.05)
    assert m["kurtosis"] == pytest.approx(3.0, abs=0.1)   # NON-excess
    assert m["sharpe"] == pytest.approx(0.1, abs=0.02)


def test_zero_variance_returns_nan_not_infinity():
    assert np.isnan(sharpe_moments([1.0] * 100)["sharpe"])


# ---------------------------------------------------------------------- PSR
def test_psr_reduces_to_the_normal_cdf_when_moments_are_normal():
    """With skew 0 and kurtosis 3 the variance term is 1 + SR^2/2 — check the closed form."""
    sr, n = 0.10, 500
    got = probabilistic_sharpe_ratio(sr, n_obs=n, skew=0.0, kurtosis=3.0, benchmark=0.0)
    want = stats.norm.cdf(sr * np.sqrt(n - 1) / np.sqrt(1.0 + 0.5 * sr ** 2))
    assert got == pytest.approx(want, rel=1e-12)


def test_psr_is_half_when_the_observed_sharpe_equals_the_benchmark():
    assert probabilistic_sharpe_ratio(0.2, n_obs=300, benchmark=0.2) == pytest.approx(0.5)


def test_negative_skew_and_fat_tails_lower_the_psr():
    """The economic point of the correction: the same Sharpe is worth less with tail risk."""
    clean = probabilistic_sharpe_ratio(0.1, n_obs=500, skew=0.0, kurtosis=3.0)
    nasty = probabilistic_sharpe_ratio(0.1, n_obs=500, skew=-1.5, kurtosis=9.0)
    assert nasty < clean


def test_psr_refuses_a_sample_too_short_for_the_correction():
    assert np.isnan(probabilistic_sharpe_ratio(0.5, n_obs=10))


# --------------------------------------------------------------- SR0 / trials
def test_expected_max_sharpe_matches_the_closed_form():
    n, var = 100, 0.04
    a = stats.norm.ppf(1 - 1 / n)
    b = stats.norm.ppf(1 - 1 / (n * np.e))
    want = np.sqrt(var) * ((1 - EULER_MASCHERONI) * a + EULER_MASCHERONI * b)
    assert expected_max_sharpe(n, var) == pytest.approx(want, rel=1e-12)


def test_a_single_trial_has_no_selection_bias_to_deflate():
    assert expected_max_sharpe(1, 0.04) == 0.0


def test_more_trials_raise_the_bar():
    bars = [expected_max_sharpe(n, 0.04) for n in (2, 10, 100, 1000)]
    assert bars == sorted(bars)


def test_effective_trials_collapses_for_identical_series_and_holds_for_independent_ones():
    rng = np.random.default_rng(0)
    base = rng.normal(size=400)
    identical = [base + 1e-12 * rng.normal(size=400) for _ in range(20)]
    assert effective_trials(identical) < 2.0

    independent = [rng.normal(size=400) for _ in range(20)]
    assert effective_trials(independent) > 15.0


# ---------------------------------------------------------------------- DSR
def test_dsr_is_below_psr_because_the_bar_is_higher():
    rng = np.random.default_rng(3)
    r = rng.normal(0.02, 0.1, 400)
    out = deflated_sharpe_ratio(r, n_trials=200, var_sharpe=0.01)
    assert out["dsr"] < out["psr_vs_zero"]


def test_the_best_of_many_pure_noise_strategies_is_not_certified():
    """THE test. 300 zero-edge random walks; the winner must not pass.

    If this ever returns a high DSR the module is actively harmful — it would bless the exact
    artefact it exists to expose.
    """
    rng = np.random.default_rng(20260812)
    trials = [rng.normal(0.0, 1.0, 332) for _ in range(300)]
    out = deflated_sharpe_of_best(trials)

    assert out["best_sharpe"] > 0, "the best of 300 noise trials should look good in-sample"
    assert out["dsr"] < 0.95, f"noise was certified: DSR={out['dsr']}"
    assert out["sr0"] > 0, "with 300 trials the null bar must be positive"


def test_a_genuinely_strong_strategy_still_survives_the_deflation():
    """Guard on the guard: the test above would also pass if DSR were always 0."""
    rng = np.random.default_rng(11)
    strong = rng.normal(0.25, 1.0, 1000)          # per-period Sharpe ~0.25, very large
    out = deflated_sharpe_ratio(strong, n_trials=50, var_sharpe=0.002)
    assert out["dsr"] > 0.95, f"a real edge was rejected: {out}"


def test_effective_n_makes_the_verdict_stricter_not_weaker_when_trials_are_correlated():
    rng = np.random.default_rng(5)
    common = rng.normal(0.02, 1.0, 332)
    trials = [common + 0.05 * rng.normal(size=332) for _ in range(100)]
    with_eff = deflated_sharpe_of_best(trials, use_effective_n=True)
    without = deflated_sharpe_of_best(trials, use_effective_n=False)
    assert with_eff["n_trials_effective"] < without["n_trials_raw"]
    # fewer independent trials => lower bar => DSR is not lower; the point is that it is HONEST
    assert with_eff["sr0"] <= without["sr0"] + 1e-12


# ==================== REGRESSION GUARDS ON THE SMALL-N / FLOAT-N FIXES ====================
def test_sr0_is_never_negative_so_the_deflation_cannot_run_backwards():
    """Eq.5 is derived for N >> 1 and dips NEGATIVE between N=1 and N~1.28.

    Unfloored, expected_max_sharpe(1.1, 0.04) returns -0.0635: a negative bar, which would make
    the DEFLATED ratio larger than the undeflated one. Whatever else is true, the correction must
    never reward you for having searched.
    """
    for n in (1.0, 1.05, 1.1, 1.2, 1.3, 1.5, 2.0, 10.0):
        assert expected_max_sharpe(n, 0.04) >= 0.0, f"negative bar at N={n}"


def test_effective_n_is_not_rounded_to_an_integer():
    """A fractional effective-N rounded down to 1 sets SR0 to exactly 0 and deletes the deflation."""
    a = expected_max_sharpe(1.4, 0.04)
    b = expected_max_sharpe(2.6, 0.04)
    assert a > 0.0 and b > a, "float trial counts must produce a real, increasing bar"


def test_var_sharpe_of_zero_gives_no_bar_rather_than_nan():
    assert expected_max_sharpe(500, 0.0) == 0.0


# ------------------------------------------------------- effective-N methods disagree, knowingly
def test_effective_n_methods_bracket_each_other_on_a_correlated_grid():
    """All four must collapse below M, and Bailey's Eq.9 must be the most conservative.

    Eq.9 is a straight-line interpolation with no derivation and it over-counts: measured against
    simulation at M=300, rho=0.8 the true effective count is ~5.9 and Eq.9 says 60.8. Over-counting
    is the SAFE direction (a higher bar), which is why it stays the default -- but the ordering
    must hold, or the docstring is lying.
    """
    rng = np.random.default_rng(4)
    common = rng.normal(size=400)
    trials = [np.sqrt(0.8) * common + np.sqrt(0.2) * rng.normal(size=400) for _ in range(120)]

    bailey = effective_trials(trials, method="bailey")
    evt = effective_trials(trials, method="evt_mc", rng=np.random.default_rng(1))
    equi = effective_trials(trials, method="equicorrelation")
    indep = effective_trials(trials, method="independent")

    assert indep == 120.0
    assert 1.0 <= evt < bailey < indep, (evt, bailey, indep)
    assert 1.0 <= equi < bailey


def test_evt_mc_recovers_the_known_answer_for_independent_trials():
    """Guard on the guard: with genuinely independent trials the accurate method must return ~M."""
    rng = np.random.default_rng(9)
    trials = [rng.normal(size=600) for _ in range(40)]
    got = effective_trials(trials, method="evt_mc", rng=np.random.default_rng(2))
    assert got > 25.0, f"independent trials collapsed to {got}"


# ----------------------------------------------------------------- the list-of-Sharpes entry point
def test_from_sharpes_matches_a_hand_computed_deflation():
    sharpes = [0.05, 0.02, -0.01, 0.03, 0.09, 0.00, 0.04, -0.03]
    out = deflated_sharpe_from_sharpes(sharpes, n_obs=332, skew=0.0, kurtosis=3.0)
    want_var = float(np.var(np.asarray(sharpes), ddof=1))
    assert out["var_sharpe"] == pytest.approx(want_var)
    assert out["n_trials"] == 8.0
    assert out["best_sharpe"] == pytest.approx(0.09)
    assert out["sr0"] == pytest.approx(expected_max_sharpe(8, want_var))
    assert out["dsr"] < out["psr_vs_zero"]


def test_from_sharpes_annualisation_scales_sharpe_and_variance_differently():
    """SR/sqrt(P) but V/P. Getting this wrong is the classic silent error in DSR code."""
    ann = [1.8, 0.4, 1.1, -0.3, 2.4]
    P = 252
    out = deflated_sharpe_from_sharpes(ann, n_obs=1000, periods_per_year=P)
    per_period = np.asarray(ann) / np.sqrt(P)
    assert out["best_sharpe"] == pytest.approx(2.4 / np.sqrt(P))
    assert out["var_sharpe"] == pytest.approx(float(np.var(np.asarray(ann), ddof=1)) / P)
    assert out["var_sharpe"] == pytest.approx(float(np.var(per_period, ddof=1)))


# ------------------------------------------------------------------------------ MinTRL
def test_min_track_record_length_is_infinite_for_a_losing_strategy():
    assert np.isinf(min_track_record_length(-0.01))


def test_min_track_record_length_shrinks_as_the_edge_grows():
    lengths = [min_track_record_length(s) for s in (0.02, 0.05, 0.10, 0.20)]
    assert lengths == sorted(lengths, reverse=True)


# ================================ NULL CALIBRATION ================================
def test_the_null_is_calibrated_not_merely_quiet():
    """Over many repetitions of a pure-noise search, DSR must behave like a probability.

    The single-seed test above ("noise is not certified") would also pass a function that always
    returned 0. This one pins the distribution: the mean DSR of a noise winner sits near 0.5, and
    the false-certification rate at the 95% threshold is ~0 -- the bar is E[max], the mean of a
    right-skewed maximum, so the typical winner falls just below it and the test is conservative.

    Note this is why "best-of-many random strategies gives DSR ~ 0" is the wrong expectation: a
    correctly calibrated DSR gives ~0.5 there. DSR ~ 0 is what a MID-RANKED pick returns, and that
    case is checked below.
    """
    rng = np.random.default_rng(2026)
    T, M, reps = 500, 120, 60
    dsrs = []
    for _ in range(reps):
        R = rng.standard_normal((T, M))
        dsrs.append(deflated_sharpe_of_best([R[:, j] for j in range(M)],
                                            use_effective_n=False)["dsr"])
    dsrs = np.asarray(dsrs, dtype=float)
    assert 0.30 < dsrs.mean() < 0.70, f"null is not centred: mean DSR {dsrs.mean():.3f}"
    assert (dsrs > 0.95).mean() < 0.10, f"noise certified {100 * (dsrs > 0.95).mean():.1f}% of the time"


def test_a_mid_ranked_pick_from_a_noise_family_is_crushed():
    """The genuine DSR ~ 0 case: an average member of a searched family has no claim at all."""
    rng = np.random.default_rng(77)
    T, M = 500, 120
    R = rng.standard_normal((T, M))
    sharpes = R.mean(0) / R.std(0, ddof=1)
    median_col = int(np.argsort(sharpes)[M // 2])
    out = deflated_sharpe_ratio(R[:, median_col], n_trials=M,
                                var_sharpe=float(np.var(sharpes, ddof=1)))
    assert out["dsr"] < 0.05, f"a mid-ranked noise pick scored DSR={out['dsr']}"
