"""CvxSuite.ou — re-export identity, planted-OU recovery, and the FPT sampler
against answers known before the code ran.

Anchors and their provenance:

* Bertram (2010) series: ``expected_passage_time(-1, +1, kappa=1)`` =
  2.9953146623 for the standardized OU; the canonical docstring records the MC
  verification 3.042 (dt=5e-4) and that the Gamma-in-DENOMINATOR variant
  previously shipped gave 1.366 (RVUtils/mean_reversion.py:333-345). The wrong
  variant's number is used as a negative control.
* Single-step law: with kappa=1, dt=0.5, sigma=sqrt(2), x0=-1, target=+1 the
  one-step hit probability is 1 - Phi((1 - (-exp(-0.5)))/0.795060) = 0.0216585
  (plain normal CDF — computable by hand); an Euler step std (sigma*sqrt(dt) =
  1.0) would give 0.0540787. This is the one test that separates the exact
  discretisation from Euler at material dt.
* Planted OU (kappa=0.05, mu=10, sigma=1.2, n=20000, seed 20260826): ou_mle
  recovers kappa=0.05482, mu=10.116, sigma=1.2005 (measured on this machine,
  2026-08-26) — the path generator here shares fpt_sample's exact
  discretisation deliberately; independence from fpt_sample comes from the two
  anchors above, and the generator only feeds fit-recovery tests against the
  PLANTED parameters.

All tests are pure logic — no store, no panel, no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import RVUtils.mean_reversion as mr
from RVUtils.CvxSuite import ou

SEED = 20260826

# Planted OU used by the recovery tests.
KAPPA_TRUE = 0.05
MU_TRUE = 10.0
SIGMA_TRUE = 1.2
HL_TRUE = np.log(2.0) / KAPPA_TRUE  # 13.8629 days

BERTRAM_TAU = 2.9953146623311286     # expected_passage_time(-1, +1, kappa=1)
WRONG_GAMMA_DENOM_TAU = 1.366        # the previously-shipped wrong variant (docstring)
ONE_STEP_P_EXACT = 0.0216584949      # 1 - Phi((1 + exp(-0.5)) / 0.7950601)
ONE_STEP_P_EULER = 0.0540786820      # same but with step std sigma*sqrt(dt) = 1.0


def _sim_ou(kappa: float, mu: float, sigma: float, x0: float, n: int,
            dt: float, rng: np.random.Generator) -> pd.Series:
    """Exact-discretisation OU path (grid marginals exactly OU)."""
    phi = np.exp(-kappa * dt)
    s = sigma * np.sqrt((1.0 - np.exp(-2.0 * kappa * dt)) / (2.0 * kappa))
    eps = rng.standard_normal(n - 1)
    x = np.empty(n)
    x[0] = x0
    for i in range(1, n):
        x[i] = mu + phi * (x[i - 1] - mu) + s * eps[i - 1]
    return pd.Series(x)


# ============================================================================
# Re-exports
# ============================================================================

def test_reexports_are_the_canonical_objects():
    """Every re-export IS the mean_reversion object, not a copy.

    MUTATION: shadow any name with a local re-implementation (or import from
    the wrong module) — the identity assert on that name fails.
    """
    for name in ("calibrate_ou", "ou_mle", "half_life", "rolling_ar1",
                 "rolling_half_life", "ou_conditional", "ou_ex_ante_sharpe",
                 "expected_passage_time"):
        assert getattr(ou, name) is getattr(mr, name), name
        assert name in ou.__all__


def test_global_rng_fpt_kernel_is_not_reexported():
    """The global-RNG kernel stays out of this namespace by design.

    MUTATION: add ``first_passage_time`` to the re-export block — this fails,
    keeping the seeded-Generator policy visible at the import site.
    """
    assert not hasattr(ou, "first_passage_time")
    assert "first_passage_time" not in ou.__all__


# ============================================================================
# Planted-OU recovery
# ============================================================================

def test_ou_mle_recovers_planted_kappa():
    """ou_mle on a 20k-bar planted OU recovers the planted parameters.

    Measured on this seed: kappa 0.05482 (true 0.05), mu 10.116, sigma 1.2005,
    half-life 12.64 (true 13.86). Tolerances are ~4x the asymptotic standard
    error of kappa-hat at this sample size.

    MUTATION: break ou_mle's kappa line (drop the log, or the /dt) — the
    25%-band assert on kappa fails. MUTATION: swap sigma for sigma_eq — the 5%
    sigma band fails (sigma_eq here is 3.79, not 1.2).
    """
    s = _sim_ou(KAPPA_TRUE, MU_TRUE, SIGMA_TRUE, MU_TRUE, 20_000, 1.0,
                np.random.default_rng(SEED))
    fit = ou.ou_mle(s)
    assert abs(fit["kappa"] - KAPPA_TRUE) / KAPPA_TRUE < 0.25
    assert abs(fit["mu"] - MU_TRUE) < 0.5
    assert abs(fit["sigma"] - SIGMA_TRUE) / SIGMA_TRUE < 0.05
    assert abs(fit["half_life"] - HL_TRUE) / HL_TRUE < 0.25
    # negative control: the same band must REJECT a 2x-wrong kappa — if it
    # cannot, the tolerance is vacuous and catches nothing.
    assert not abs(fit["kappa"] - 2.0 * KAPPA_TRUE) / (2.0 * KAPPA_TRUE) < 0.25
    assert not abs(fit["half_life"] - 2.0 * HL_TRUE) / (2.0 * HL_TRUE) < 0.25


def test_calibrate_ou_and_ou_mle_are_drop_in_comparable():
    """OLS and MLE fits agree on a clean planted path (same return keys, close
    values) — the recon's 'fit method is a sweepable axis' property.

    MUTATION: change either fit's parameterisation (e.g. return phi where
    kappa belongs) — the 1% cross-agreement asserts fail.
    """
    s = _sim_ou(KAPPA_TRUE, MU_TRUE, SIGMA_TRUE, MU_TRUE, 20_000, 1.0,
                np.random.default_rng(SEED))
    a, b = ou.calibrate_ou(s), ou.ou_mle(s)
    assert set(a) == set(b)
    for key in ("mu", "kappa", "sigma", "phi", "half_life"):
        assert np.isclose(a[key], b[key], rtol=1e-2), key


# ============================================================================
# fpt_sample vs the Bertram analytic series
# ============================================================================

def test_expected_passage_time_analytic_anchor():
    """The re-exported series reproduces the recorded number to 1e-9 and is
    nowhere near the Gamma-in-denominator variant's 1.366.

    MUTATION: move the Gamma to the denominator (the historical bug recorded
    in the docstring) — the 1e-9 pin fails and the value lands near 1.366.
    """
    tau = ou.expected_passage_time(-1.0, 1.0, kappa=1.0)
    assert abs(tau - BERTRAM_TAU) < 1e-9
    assert abs(tau - WRONG_GAMMA_DENOM_TAU) > 1.0


def test_fpt_sample_mean_matches_bertram_within_mc_error():
    """MC mean passage time on the standardized OU vs the analytic series.

    tau(-1 -> +1), kappa=1, sigma=sqrt(2) (sigma_eq=1), dt=1e-3: measured
    3.0146 on seed 20260826 vs 2.9953 analytic — the same overshoot band as
    the canonical verification (3.042 at dt=5e-4). Band +-0.25 covers MC error
    (2000 paths) plus discrete-monitoring overshoot.

    MUTATION: flip the phi sign, break the hit comparison direction, or
    censored->steps inside fpt_sample — the mean leaves the band. MUTATION:
    Gamma-in-denominator on the analytic side — the negative control
    (|mean - 1.366| > 1) fails.
    """
    params = {"kappa": 1.0, "mu": 0.0, "sigma": np.sqrt(2.0)}
    hits = ou.fpt_sample(-1.0, 1.0, params, sims=2000, steps=30_000, dt=1e-3,
                         rng=np.random.default_rng(SEED))
    assert hits.shape == (2000,)
    assert np.isfinite(hits).all()          # no censoring at this cap (30 time units)
    mean_time = hits.mean() * 1e-3          # step indices -> time units
    assert abs(mean_time - BERTRAM_TAU) < 0.25
    assert abs(mean_time - WRONG_GAMMA_DENOM_TAU) > 1.0


def test_fpt_sample_single_step_law_is_exact_not_euler():
    """One step at material dt: hit probability equals the exact transition
    law, not the Euler approximation.

    kappa=1, dt=0.5: exact step std 0.79506, Euler sigma*sqrt(dt) = 1.0;
    P(hit in one step) exact 0.021658 vs Euler 0.054079. Measured 0.02173 at
    200k sims. This is the only test that catches an exact-vs-Euler step-std
    mutation — at dt=1e-3 the two are numerically indistinguishable.

    MUTATION: replace s_step with sigma*np.sqrt(dt) — p lands near 0.054 and
    both asserts fail.
    """
    params = {"kappa": 1.0, "mu": 0.0, "sigma": np.sqrt(2.0)}
    hits = ou.fpt_sample(-1.0, 1.0, params, sims=200_000, steps=1, dt=0.5,
                         rng=np.random.default_rng(SEED))
    p_hit = float(np.isfinite(hits).mean())
    assert abs(p_hit - ONE_STEP_P_EXACT) < 0.0015          # ~4.5 binomial SE
    assert abs(p_hit - ONE_STEP_P_EULER) > 0.02


# ============================================================================
# fpt_sample mechanics
# ============================================================================

def test_fpt_sample_deterministic_under_seed():
    """Same Generator seed -> identical hit arrays; different seed -> different.

    MUTATION: read the global RNG (np.random.standard_normal) instead of the
    passed Generator — two calls advance the global stream, so the equal-seed
    identity fails.
    """
    params = {"kappa": 0.05, "mu": 0.0, "sigma": 1.0}
    a = ou.fpt_sample(2.0, 0.0, params, sims=500, steps=252,
                      rng=np.random.default_rng(SEED))
    b = ou.fpt_sample(2.0, 0.0, params, sims=500, steps=252,
                      rng=np.random.default_rng(SEED))
    c = ou.fpt_sample(2.0, 0.0, params, sims=500, steps=252,
                      rng=np.random.default_rng(SEED + 1))
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_fpt_sample_censored_paths_are_inf_and_hits_are_step_indices():
    """Censored = np.inf exactly (not steps); an unmissable barrier hits at
    step index 1.

    MUTATION: keep the canonical censored->steps fold — the isinf assert
    fails. MUTATION: 0-based step indexing — the all-ones assert fails.
    """
    # instant hit: strong reversion from -10 toward mu=0, barrier just above start
    inst = ou.fpt_sample(-10.0, -9.99, {"kappa": 5.0, "mu": 0.0, "sigma": 1.0},
                         sims=500, steps=10, rng=np.random.default_rng(5))
    assert np.array_equal(np.unique(inst), np.array([1.0]))
    # far barrier, near-zero kappa: most paths censor, and censoring is inf
    far = ou.fpt_sample(-10.0, 50.0, {"kappa": 1e-6, "mu": 0.0, "sigma": 1.0},
                        sims=2000, steps=504, rng=np.random.default_rng(3))
    assert np.isinf(far).any()
    assert not (far[np.isinf(far) == False] > 504).any()  # noqa: E712 — finite hits <= cap
    assert np.isinf(far).mean() > 0.95                    # measured 0.9935 on this seed


def test_fpt_sample_invalid_inputs():
    """No-fit params (NaN/negative kappa), non-finite x0/target -> all-NaN
    array; wrong rng type -> TypeError; bad sims/steps/dt -> ValueError.

    MUTATION: return zeros (or empty) on the no-fit path — the all-NaN asserts
    fail; a silent zero here would read as 'hits immediately' downstream.
    """
    good = {"kappa": 0.1, "mu": 0.0, "sigma": 1.0}
    rng = np.random.default_rng(SEED)
    nan_fit = ou.calibrate_ou(pd.Series([1.0, 2.0]))       # too short -> NaN params
    assert np.isnan(nan_fit["kappa"])
    for bad_params in (nan_fit, {"kappa": -0.5, "mu": 0.0, "sigma": 1.0},
                       {"kappa": 0.1, "mu": np.nan, "sigma": 1.0}):
        out = ou.fpt_sample(1.0, 0.0, bad_params, sims=7, rng=rng)
        assert out.shape == (7,) and np.isnan(out).all()
    assert np.isnan(ou.fpt_sample(np.nan, 0.0, good, sims=3, rng=rng)).all()
    assert np.isnan(ou.fpt_sample(1.0, np.inf, good, sims=3, rng=rng)).all()
    with pytest.raises(TypeError, match="Generator"):
        ou.fpt_sample(1.0, 0.0, good, rng=42)
    with pytest.raises(ValueError, match="sims"):
        ou.fpt_sample(1.0, 0.0, good, sims=0, rng=rng)
    with pytest.raises(ValueError, match="steps"):
        ou.fpt_sample(1.0, 0.0, good, steps=0, rng=rng)
    with pytest.raises(ValueError, match="dt"):
        ou.fpt_sample(1.0, 0.0, good, dt=0.0, rng=rng)


# ============================================================================
# fpt_stats
# ============================================================================

def test_fpt_stats_planted_arithmetic():
    """hits=[1,2,3,inf], steps=10: every field is a hand-computed number.

    e_fpt = (1+2+3+10)/4 = 4.0 (censored->steps); p_hit = 0.75;
    frac_censored = 0.25; order-statistic quantiles (method='lower') are
    1.0/2.0/3.0.

    MUTATION: compute e_fpt over finite hits only — 2.0 != 4.0 fails.
    MUTATION: swap p_hit/frac_censored — both 0.75/0.25 pins fail.
    MUTATION: linear-interpolated quantiles — q75 on a mostly-censored array
    (covered in the negative-control test below) becomes NaN, and here q25
    would drift to 1.75.
    """
    st = ou.fpt_stats(np.array([1.0, 2.0, 3.0, np.inf]), steps=10)
    assert st["e_fpt"] == 4.0
    assert st["e_fpt"] != 2.0            # the finite-only wrong path, explicitly
    assert st["p_hit"] == 0.75
    assert st["frac_censored"] == 0.25
    assert (st["q25"], st["q50"], st["q75"]) == (1.0, 2.0, 3.0)


def test_fpt_stats_quantiles_allow_inf():
    """Quantiles are over ALL paths: a mostly-censored array has inf medians —
    and never NaN (linear interpolation between two infs is NaN; the
    order-statistic choice is what keeps this well-defined).

    MUTATION: switch np.quantile to method='linear' — q50/q75 become NaN and
    the isinf asserts fail.
    """
    st = ou.fpt_stats(np.array([1.0, np.inf, np.inf, np.inf]), steps=504)
    assert st["q25"] == 1.0
    assert np.isinf(st["q50"]) and np.isinf(st["q75"])
    assert not np.isnan(st["q50"])
    assert st["p_hit"] == 0.25 and st["frac_censored"] == 0.75
    assert st["e_fpt"] == (1.0 + 3 * 504) / 4.0


def test_fpt_stats_no_censoring_needs_no_steps():
    """With zero censored paths, ``steps`` is not required and must not leak
    into the result: e_fpt is the plain mean (5.0), quantiles the order
    statistics, and passing steps anyway changes nothing.

    MUTATION: require steps unconditionally (raise when steps=None even with
    zero censored paths) — the bare call here fails. MUTATION: fold steps into
    e_fpt even when nothing is censored — the steps=999 negative control
    stops matching the bare-call result.
    """
    st = ou.fpt_stats(np.array([2.0, 4.0, 6.0, 8.0]))
    assert st["e_fpt"] == 5.0
    assert st["p_hit"] == 1.0 and st["frac_censored"] == 0.0
    assert (st["q25"], st["q50"], st["q75"]) == (2.0, 4.0, 6.0)
    # negative control: steps present but unused gives the identical dict
    assert ou.fpt_stats(np.array([2.0, 4.0, 6.0, 8.0]), steps=999) == st


def test_fpt_stats_censored_without_steps_raises():
    """Censoring present + steps=None must raise, not guess a cap.

    MUTATION: default the cap to max(finite hits) — this silently
    underestimates e_fpt and the pytest.raises fails.
    """
    with pytest.raises(ValueError, match="steps"):
        ou.fpt_stats(np.array([1.0, np.inf]))
    with pytest.raises(ValueError, match="empty"):
        ou.fpt_stats(np.array([]))


def test_nan_hits_propagate_as_nan_never_zero():
    """The no-fit chain: fpt_sample NaN array -> fpt_stats all-NaN dict ->
    p_fpt_exceeds NaN. The NaN check runs BEFORE the censoring logic, so a
    no-fit array is never misread as 0%-censored / p_hit=0.

    MUTATION: reorder fpt_stats to compute isinf/p_hit before the NaN check —
    p_hit becomes 0.0 (isfinite(NaN) is False) and the isnan asserts fail.
    MUTATION: drop the NaN guard in p_fpt_exceeds — NaN > 10 is False, the
    result becomes 0.0, and the isnan assert fails.
    """
    hits = ou.fpt_sample(1.0, 0.0, {"kappa": np.nan, "mu": 0.0, "sigma": 1.0},
                         sims=50, rng=np.random.default_rng(SEED))
    assert np.isnan(hits).all()
    st = ou.fpt_stats(hits, steps=504)     # must NOT raise, must NOT say p_hit=0
    assert all(np.isnan(v) for v in st.values())
    assert np.isnan(ou.p_fpt_exceeds(hits, 10.0))
    assert np.isnan(ou.p_fpt_exceeds(np.array([1.0, 2.0]), np.nan))


# ============================================================================
# carry_over_horizon / p_fpt_exceeds arithmetic
# ============================================================================

def test_carry_over_horizon_is_a_plain_product():
    """0.5 bp/day over 63 days is 31.5 bp; sign passes through; NaN in -> NaN.

    MUTATION: divide by the horizon, or annualise by 252 or sqrt(252) — the
    exact 31.5 pin fails (0.5*63/252 = 0.125; 0.5*63/sqrt(252) = 1.984).
    """
    assert ou.carry_over_horizon(0.5, 63.0) == 31.5
    assert ou.carry_over_horizon(-0.2, 10.0) == -2.0
    assert ou.carry_over_horizon(0.0, 63.0) == 0.0
    assert np.isnan(ou.carry_over_horizon(np.nan, 63.0))
    # negative controls: the two nearby wrong conventions
    assert ou.carry_over_horizon(0.5, 63.0) != 0.5 * 63.0 / 252.0
    assert ou.carry_over_horizon(0.5, 63.0) != 0.5 * 63.0 / np.sqrt(252.0)


def test_p_fpt_exceeds_counts_censored_and_is_strict():
    """hits=[5,20,inf,inf]: P(>10)=0.75 (20 and both censored), P(>25)=0.5
    (censored only), P(>4)=1.0; a hit exactly AT the horizon does not exceed.

    MUTATION: drop non-finite hits before comparing — P(>10) becomes 0.5 and
    the 0.75 pin fails. MUTATION: use >= — the boundary case [10] at days=10
    returns 1.0 instead of 0.0.
    """
    hits = np.array([5.0, 20.0, np.inf, np.inf])
    assert ou.p_fpt_exceeds(hits, 10.0) == 0.75
    assert ou.p_fpt_exceeds(hits, 25.0) == 0.5
    assert ou.p_fpt_exceeds(hits, 4.0) == 1.0
    assert ou.p_fpt_exceeds(np.array([10.0]), 10.0) == 0.0   # strict >
    with pytest.raises(ValueError, match="empty"):
        ou.p_fpt_exceeds(np.array([]), 10.0)


# ============================================================================
# kappa=0 negative control — a random walk must not look tradeable
# ============================================================================

def test_random_walk_negative_control():
    """A non-reverting series must come out non-reverting end to end.

    Three prongs, because a FINITE random-walk sample usually fits phi
    slightly below 1 (Dickey-Fuller small-sample bias) and then half_life is
    huge-but-finite rather than NaN:

    1. a deterministic phi=1.0 series (a pure trend) -> half_life NaN by the
       (0,1) phi gate — the guaranteed sentinel;
    2. a seeded 756-bar driftless random walk -> half_life NaN or > 100 days
       (measured 301.9 on seed 7, phi=0.9977) — non-reverting at the trading
       scale of the 504-step FPT cap;
    3. near-zero-kappa params with a far target -> heavy censoring: measured
       frac_censored 0.9935 on seed 3; q50 = inf; e_fpt pinned near the cap.

    MUTATION: half_life returning a finite default (the old 1.0 sentinel one
    of the eleven pre-consolidation copies used) — prong 1 or 2 fails.
    MUTATION: censored->steps inside fpt_sample — prong 3's isinf q50 fails.
    """
    # 1. exact unit root
    hl_trend = ou.half_life(pd.Series(np.arange(600, dtype=float)))
    assert np.isnan(hl_trend) or hl_trend > 1e6
    # 2. seeded random walk
    rw = pd.Series(np.random.default_rng(7).standard_normal(756).cumsum())
    hl_rw = ou.half_life(rw)
    assert np.isnan(hl_rw) or hl_rw > 100.0
    fit = ou.ou_mle(rw)
    assert np.isnan(fit["phi"]) or fit["phi"] > 0.98
    # 3. heavy censoring under a ~zero-kappa fit
    hits = ou.fpt_sample(-10.0, 50.0, {"kappa": 1e-6, "mu": 0.0, "sigma": 1.0},
                         sims=2000, steps=504, rng=np.random.default_rng(3))
    st = ou.fpt_stats(hits, steps=504)
    assert st["frac_censored"] > 0.95
    assert st["p_hit"] < 0.05
    assert np.isinf(st["q50"]) and np.isinf(st["q75"])
    assert st["e_fpt"] > 0.9 * 504
    # and the breakeven question answers "almost certainly slower than 63d"
    assert ou.p_fpt_exceeds(hits, 63.0) > 0.95
