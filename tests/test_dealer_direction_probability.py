"""The probability model, tested against data whose answer is set here.

A fitted ``tau`` that is wrong is invisible: it produces a complete, plausible,
monotone ``p`` that is simply the wrong width. Nothing downstream can tell. So
every claim this module makes is pinned against something that is not the
module's own output:

* **recovery** -- simulate from the model at known ``(b0, h, s)`` and confirm
  the estimator gets them back, across a grid, at sample sizes the tape
  actually provides;
* **the algebra** -- ``tau = s^2/(2h)``, the moment closed form, and the
  dead-zone width are each checked against an independent derivation;
* **the frozen predecessor** -- ``stir_flow.confidence.sigma_mid`` does this
  exact variance decomposition by hand, so the fit must reproduce it;
* **the diagnostics** -- a check that never fires is not a check, so the
  leptokurtosis flag is tested in *both* directions;
* **calibration** -- measured with labels on simulated data, where labels
  exist. There are no labels on the tape and this file does not pretend
  otherwise; see :func:`test_calibration_degrades_measurably_under_asymmetric_flow`
  for what the fixed-0.5 weight costs when the assumption is false.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from SDRUtils.dealer_direction import conventions as conv
from SDRUtils.dealer_direction import probability as prob
from SDRUtils.stir_flow import confidence as frozen_conf


def _rng(seed):
    return np.random.default_rng(seed)


# --------------------------------------------------------------------------
# 1. The algebra. tau is s^2/(2h), and getting it backwards inverts the
#    comparative static in h.
# --------------------------------------------------------------------------

def test_tau_is_variance_over_twice_the_half_spread_not_the_half_spread():
    """The single most consequential line in the module.

    DESIGN.md 1.1: reading ``tau`` as the half-spread inverts the comparative
    static -- it would make a wide-spread bucket *less* decidable when it is
    more. Pinned numerically so a refactor cannot quietly swap them.
    """
    fit = prob.MixtureFit(bucket="T", n=1000, n_trimmed=1000,
                          b0=0.0, h=0.25, s=0.20, loglik=0.0)
    assert fit.tau == pytest.approx(0.20 ** 2 / (2 * 0.25))
    assert fit.tau == pytest.approx(0.08)
    assert fit.tau != pytest.approx(0.25)          # NOT the half-spread


def test_a_wider_spread_bucket_is_more_decidable():
    """tau shrinks as h grows, holding mid quality fixed."""
    narrow = prob.MixtureFit("N", 1000, 1000, 0.0, 0.10, 0.20, 0.0)
    wide = prob.MixtureFit("W", 1000, 1000, 0.0, 0.40, 0.20, 0.0)
    assert wide.tau < narrow.tau
    # and the same deviation is a more confident call in the wider bucket
    assert prob.p_customer_paid(0.10, wide) > prob.p_customer_paid(0.10, narrow)


def test_mid_quality_enters_quadratically():
    """Halving ``s`` quarters ``tau``. This is why the curve work was the blocker."""
    coarse = prob.MixtureFit("C", 1000, 1000, 0.0, 0.25, 0.40, 0.0)
    fine = prob.MixtureFit("F", 1000, 1000, 0.0, 0.25, 0.20, 0.0)
    assert fine.tau == pytest.approx(coarse.tau / 4.0)


def test_p_is_the_bayes_posterior_of_the_two_component_mixture():
    """Derived, not asserted: sigma((x-b0)/tau) must equal the density ratio.

    If these disagree the logistic form is not the posterior of the mixture
    that was fitted, and every ``p`` is a different quantity from the one the
    likelihood maximised.
    """
    b0, h, s = 0.03, 0.22, 0.17
    fit = prob.MixtureFit("B", 1000, 1000, b0, h, s, 0.0)
    for x in (-0.9, -0.2, 0.0, 0.03, 0.31, 1.4):
        num = math.exp(-0.5 * ((x - b0 - h) / s) ** 2)
        den = num + math.exp(-0.5 * ((x - b0 + h) / s) ** 2)
        assert prob.p_customer_paid(x, fit) == pytest.approx(num / den, rel=1e-12)


def test_p_at_the_bias_is_exactly_a_coin_flip():
    """``b0`` is a curve bias, not information. At ``x == b0`` there is no call."""
    fit = prob.MixtureFit("B", 1000, 1000, -0.48, 0.25, 0.20, 0.0)
    assert prob.p_customer_paid(-0.48, fit) == pytest.approx(0.5)
    assert conv.signed_weight(prob.p_customer_paid(-0.48, fit)) == pytest.approx(0.0)


# --------------------------------------------------------------------------
# 2. Recovery from simulation. The estimator is tested against data whose
#    answer is set here, before it is trusted on data whose answer is not.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(("b0", "h", "s", "expect_flags"), [
    (0.00, 0.25, 0.15, (prob.FIT_OK,)),      # well separated, unbiased
    (-0.48, 0.25, 0.20, (prob.FIT_OK,)),     # the measured Barchart bias, F-20
    # ``h/s = 0.5`` is the regime MIN_BUCKET_N's docstring says is not
    # identifiable, and the fit says so too -- even at n = 20,000. Its
    # ``se_log_tau`` measures 0.1547 against a MAX_SE_LOG_TAU of 0.1520, i.e. a
    # p90 ``tau`` error of ``1.6449 * 0.1547 = 0.254``, just outside
    # TAU_RECOVERY_TOLERANCE. The point estimates below are still good; the
    # flag records that this sample cannot promise they are. Under the old
    # gate's wrong quantile (0.25/1.2816 = 0.1951) this cell came back OK,
    # which is the over-confidence that correction removes.
    (0.02, 0.15, 0.30, (prob.FIT_IMPRECISE,)),
    (0.10, 0.60, 0.10, (prob.FIT_OK,)),      # very wide spread, tiny mid error
])
def test_recovers_known_parameters(b0, h, s, expect_flags):
    x, _ = prob.simulate(b0=b0, h=h, s=s, n=20_000, rng=_rng(11))
    fit = prob.fit_mixture(x, bucket="SIM")

    assert fit.b0 == pytest.approx(b0, abs=0.02)
    assert fit.h == pytest.approx(h, rel=0.10)
    assert fit.s == pytest.approx(s, rel=0.10)
    assert fit.tau == pytest.approx(s * s / (2 * h), rel=0.20)
    assert fit.flags == expect_flags, fit.flags


def test_the_moment_check_is_a_coin_flip_at_realistic_overlap():
    """Why the diagnostic is gated on a z-score and not on the sign.

    The population excess kurtosis of this mixture at ``h/s = 0.5`` is only
    -0.080, against a sampling standard error of ``sqrt(24/n)`` -- 0.245 at
    n=400. So the *sign* of the sample excess kurtosis is very nearly a coin
    flip for every overlapping bucket the tape has, and a sign-gated diagnostic
    would route roughly half of them into the robust fallback at random. That
    is measured here rather than argued.
    """
    h, s = 0.09, 0.18
    pop = ((h ** 4 + 6 * h ** 2 * s ** 2 + 3 * s ** 4) / (h ** 2 + s ** 2) ** 2) - 3
    assert pop == pytest.approx(-0.080, abs=0.002)

    rng = _rng(97)
    imaginary = sum(not prob.moment_estimates(
        prob.simulate(b0=0.0, h=h, s=s, n=400, rng=rng)[0]).real for _ in range(200))
    assert 0.25 < imaginary / 200 < 0.75          # a coin flip, as claimed

    fired = sum(prob.FIT_LEPTOKURTIC in prob.fit_mixture(
        prob.simulate(b0=0.0, h=h, s=s, n=400, rng=rng)[0], bucket="Z").flags
        for _ in range(200))
    assert fired <= 4                             # the z-gate does not


def test_recovery_is_unbiased_across_repeated_draws():
    """One lucky seed is not recovery. Twenty-five draws, median relative error."""
    truth = dict(b0=0.01, h=0.28, s=0.18)
    taus = []
    for seed in range(25):
        x, _ = prob.simulate(n=3000, rng=_rng(200 + seed), **truth)
        taus.append(prob.fit_mixture(x, bucket="SIM").tau)
    tau_true = truth["s"] ** 2 / (2 * truth["h"])
    assert np.median(taus) == pytest.approx(tau_true, rel=0.06)


def test_the_trim_does_not_bias_a_clean_fit():
    """A quantile trim would. A robust-scale trim removes ~nothing when clean.

    The hazard is specific: trimming a fixed fraction off a clean mixture makes
    the sample MORE platykurtic, which makes the moment check pass more readily
    and biases ``s`` and ``h`` down -- so ``tau`` comes out too small and every
    ``p`` is overconfident. Measured here rather than assumed.
    """
    x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=40_000, rng=_rng(7))
    kept = prob.trim_mask(x).mean()
    assert kept > 0.995, f"robust trim removed {1 - kept:.2%} of clean data"

    trimmed = prob.fit_mixture(x, bucket="T")
    untrimmed = prob.fit_mixture(x, bucket="U", trim_k=float("inf"))
    assert trimmed.tau == pytest.approx(untrimmed.tau, rel=0.05)


def test_the_trim_actually_removes_the_pathological_tail():
    """The other direction: a check that never fires is not a check."""
    x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=5000, rng=_rng(9))
    contaminated = np.concatenate([x, np.array([-40.0, 90.0, 1e4, -1e4])])
    assert prob.trim_mask(contaminated)[-4:].sum() == 0
    clean_fit = prob.fit_mixture(x, bucket="C")
    dirty_fit = prob.fit_mixture(contaminated, bucket="D")
    assert dirty_fit.tau == pytest.approx(clean_fit.tau, rel=0.05)


# --------------------------------------------------------------------------
# 3. Check one -- the moment closed form, and the diagnostic that must fire.
# --------------------------------------------------------------------------

def test_moment_closed_form_inverts_the_population_moments_exactly():
    """Analytic, no sampling: m2 = h^2+s^2 and m4 = h^4+6h^2s^2+3s^4."""
    h, s = 0.31, 0.19
    m2 = h ** 2 + s ** 2
    m4 = h ** 4 + 6 * h ** 2 * s ** 2 + 3 * s ** 4
    mc = prob.moment_estimates_from_moments(m2, m4)
    assert mc.real
    assert mc.s_moment == pytest.approx(s, rel=1e-9)
    assert mc.h_moment == pytest.approx(h, rel=1e-9)


def test_the_moment_check_agrees_with_the_mle_on_clean_data():
    """Two estimators, one answer. They are independent enough to disagree."""
    x, _ = prob.simulate(b0=0.05, h=0.30, s=0.20, n=50_000, rng=_rng(3))
    fit = prob.fit_mixture(x, bucket="M")
    assert fit.moment is not None and fit.moment.real
    assert fit.moment.h_moment == pytest.approx(fit.h, rel=0.10)
    assert fit.moment.s_moment == pytest.approx(fit.s, rel=0.10)


def test_a_separated_mixture_is_platykurtic():
    """The condition for a real moment solution, stated as the physics."""
    x, _ = prob.simulate(b0=0.0, h=0.30, s=0.15, n=50_000, rng=_rng(5))
    mc = prob.moment_estimates(x[prob.trim_mask(x)])
    assert mc.excess_kurtosis < 0
    assert mc.real


def test_the_leptokurtosis_diagnostic_fires_on_a_three_component_bucket():
    """A bucket the two-component model does not describe must SAY so.

    Not degrade quietly. Modelled here as a mixture contaminated by a wide
    third population, which is what the Barchart curve produces for real: the
    legacy ``SOFR 1Y`` bucket is leptokurtic at every trim level from 0% to
    10%, its sd collapsing 8.84 -> 0.35 bp between them, because part of the
    bucket is priced against a broken region of the curve and part is not.
    """
    rng = _rng(13)
    core, _ = prob.simulate(b0=0.0, h=0.25, s=0.10, n=9000, rng=rng)
    wide = rng.normal(0.0, 3.0, 1000)
    x = np.concatenate([core, wide])

    fit = prob.fit_mixture(x, bucket="LEPTO")
    assert prob.FIT_LEPTOKURTIC in fit.flags
    assert fit.moment is not None and not fit.moment.real
    assert fit.moment.excess_kurtosis > 0


def test_the_leptokurtosis_diagnostic_does_not_fire_on_clean_data():
    """The other half. A flag that is always on carries no information."""
    for seed in range(12):
        x, _ = prob.simulate(b0=0.0, h=0.26, s=0.17, n=4000, rng=_rng(400 + seed))
        assert prob.FIT_LEPTOKURTIC not in prob.fit_mixture(x, bucket="OK").flags


def test_a_flagged_bucket_falls_back_to_a_robust_scale():
    """Flagged, not dropped -- and the fallback must be stated, not implicit.

    The fallback is the frozen predecessor's own decomposition: a robust total
    dispersion, an ``h`` from outside this sample, and ``s`` by subtraction.
    Using the same arithmetic as the module it is cross-checked against is what
    stops the fallback and the check drifting apart.
    """
    rng = _rng(17)
    # b0 is the measured Barchart bias, not zero, and that is load-bearing: on
    # a centred sample ``b0 = median(kept)`` and ``b0 = 0`` are the same number,
    # so a fallback that dropped the bias entirely would pass unnoticed. It is
    # the bias term that positions the whole logistic, and this is the code
    # path 100% of real buckets take (every bucket in scratch/prob05_real.py is
    # ROBUST_SCALE_FALLBACK), so it is pinned here rather than assumed.
    x = np.concatenate([prob.simulate(b0=-0.48, h=0.2, s=0.08, n=6000, rng=rng)[0],
                        -0.48 + rng.standard_t(2.0, 1500) * 2.0])
    stats = frozen_conf.TickStats(median_tick_bps=0.40, disp_jns=None,
                                  futures_tick_bps=0.25)
    fit = prob.fit_mixture(x, bucket="FB", tick_stats=stats)

    assert prob.FIT_LEPTOKURTIC in fit.flags
    assert prob.FIT_ROBUST_FALLBACK in fit.flags
    assert fit.s > 0 and fit.h > 0 and math.isfinite(fit.tau)
    # h came from the tick, not from the contaminated sample
    assert fit.h == pytest.approx(0.20)
    kept = x[prob.trim_mask(x)]
    # Spelled out rather than called through ``prob.trimmed_dispersion``: using
    # the module's own helper on both sides makes any change to it cancel, and
    # the frozen predecessor's documented bug is exactly such a change (an RMS
    # about ZERO instead of about the mean). This is the one test placed to see
    # that, so it does the arithmetic itself.
    rms_about_mean = math.sqrt(float(np.mean((kept - kept.mean()) ** 2)))
    assert fit.s == pytest.approx(math.sqrt(rms_about_mean ** 2 - 0.20 ** 2),
                                  rel=1e-9)
    assert fit.b0 == pytest.approx(float(np.median(kept)), rel=1e-12)
    # ...and that median really is the bias and not zero. It sits 0.022 off the
    # true -0.48 because the t(2) contamination is not symmetric about it,
    # which is the trim-stability question the module docstring discusses --
    # what matters here is that a fallback which dropped b0 entirely would be
    # 0.48 out, i.e. p inverted for every deviation in (-0.48, 0).
    assert fit.b0 == pytest.approx(-0.48, abs=0.05)


def test_a_fallback_with_no_outside_estimate_does_not_claim_one():
    """The self-h fallback must not be labelled as an independent estimate.

    A leptokurtic bucket with no tick and no parent still gets the robust
    decomposition, but ``h`` there is the sample's OWN MLE. Flagging it
    ``H_FROM_INDEPENDENT_ESTIMATE`` would be a lie in provenance, and the
    consequence is worse than cosmetic: the anchored sample-size floor is
    granted on the strength of that flag, and it was measured only for an
    external and approximately correct ``h``. The bucket would then refuse to
    pool because of the one number in it that cannot be trusted.
    """
    rng = _rng(181)
    x = np.concatenate([prob.simulate(b0=0.0, h=0.2, s=0.08, n=3000, rng=rng)[0],
                        rng.standard_t(2.0, 800) * 2.0])
    fit = prob.fit_mixture(x, bucket="SELF")          # no tick_stats, no parent

    assert prob.FIT_LEPTOKURTIC in fit.flags
    assert prob.FIT_ROBUST_FALLBACK in fit.flags
    assert prob.FIT_ANCHORED_H not in fit.flags
    assert fit.min_n_required == prob.MIN_BUCKET_N

    # ...and with a tick it does claim one, and does get the lower floor
    anchored = prob.fit_mixture(x, bucket="ANCH", tick_stats=frozen_conf.TickStats(
        median_tick_bps=0.40, disp_jns=None, futures_tick_bps=0.25))
    assert prob.FIT_ANCHORED_H in anchored.flags
    assert anchored.min_n_required == prob.MIN_BUCKET_N_ANCHORED


def test_the_decomposition_uses_a_second_moment_not_a_robust_scale():
    """A MAD is not an estimate of ``sqrt(h^2+s^2)``, and using one is severe.

    ``1.4826 * MAD`` is normal-consistent and a separated mixture is not
    normal: at ``h/s = 2.5`` the mixture's MAD is almost exactly ``h``, so the
    converted scale overstates ``sqrt(m2)`` by ~38%, and subtracting ``h^2``
    turns that into a factor-of-7 error in ``s^2``. It measured as a p90
    ``tau`` error of 7.8 with a PERFECT anchor -- an invisible defect, because
    every fit still came back finite, monotone and plausible.
    """
    rng = _rng(151)
    h, s = 0.45, 0.18
    x, _ = prob.simulate(b0=0.0, h=h, s=s, n=200_000, rng=rng)
    truth = math.sqrt(h ** 2 + s ** 2)

    assert prob.trimmed_dispersion(x) == pytest.approx(truth, rel=0.01)
    assert prob.robust_scale(x) > 1.25 * truth          # and badly so


# --------------------------------------------------------------------------
# 4. Check two -- h against an independent spread estimate.
#    `stir_flow.confidence.sigma_mid` already does this decomposition by hand.
# --------------------------------------------------------------------------

def test_reproduces_the_frozen_sigma_mid_decomposition_exactly():
    """``sqrt(disp_jns^2 - half^2)`` IS ``s`` when disp_jns is the fit's own.

    Feed the frozen function the dispersion and tick our fit implies and it
    must hand back our ``s``. This is an algebraic identity, so it is checked
    at float tolerance -- if it ever fails, the two modules are decomposing
    different quantities.
    """
    for h, s in [(0.25, 0.18), (0.50, 0.10), (0.12, 0.31)]:
        fit = prob.MixtureFit("X", 1000, 1000, 0.0, h, s, 0.0)
        stats = prob.tick_stats_implied_by(fit, futures_tick_bps=0.25)
        assert frozen_conf.sigma_mid(stats) == pytest.approx(s, rel=1e-12)
        assert stats.median_tick_bps == pytest.approx(2 * h)


def test_the_frozen_decomposition_absorbs_a_curve_bias_into_the_mid_error():
    """Why the new fit estimates ``b0`` and the old one could not.

    ``compute_dispersion`` takes ``disp_jns`` as the RMS of ``s2m`` about
    ZERO, so a biased curve inflates it by ``b0^2`` and ``sigma_mid`` books the
    whole of that as mid-measurement error. With the measured Barchart bias of
    -0.48 bp that is not a rounding difference: it roughly doubles ``s``, which
    QUADRUPLES ``tau``. The new fit puts ``b0`` in the model instead.
    """
    h, s, b0 = 0.25, 0.20, -0.48
    honest = prob.MixtureFit("H", 1000, 1000, b0, h, s, 0.0)
    naive = prob.tick_stats_implied_by(honest, futures_tick_bps=0.25,
                                       include_bias_in_dispersion=True)
    s_naive = frozen_conf.sigma_mid(naive)
    assert s_naive > 1.9 * s
    assert (s_naive ** 2 / (2 * h)) > 3.8 * honest.tau


def test_crosscheck_flags_a_fit_that_disagrees_with_the_tick():
    x, _ = prob.simulate(b0=0.0, h=0.25, s=0.15, n=20_000, rng=_rng(23))
    fit = prob.fit_mixture(x, bucket="CC")

    agree = prob.crosscheck_against_tick(
        fit, frozen_conf.TickStats(median_tick_bps=0.50, disp_jns=None,
                                   futures_tick_bps=0.25))
    assert agree.agrees, agree

    disagree = prob.crosscheck_against_tick(
        fit, frozen_conf.TickStats(median_tick_bps=4.0, disp_jns=None,
                                   futures_tick_bps=0.25))
    assert not disagree.agrees
    assert disagree.h_independent == pytest.approx(2.0)


def test_the_crosscheck_checks_s_as_well_as_h():
    """The other half of the second opinion, which no other test reaches.

    Every other fixture in this file builds ``TickStats(disp_jns=None)``, so
    ``sigma_mid`` returns its own fallback, ``s_independent`` is None and the
    ``s`` arm of ``agrees`` is never evaluated. Here ``disp_jns`` is set, and
    the disagreeing case is constructed so that ``h`` agrees EXACTLY -- the
    verdict can then only have come from ``s``.
    """
    h, s = 0.25, 0.15
    fit = prob.MixtureFit("S", 5000, 5000, 0.0, h, s, 0.0)

    consistent = prob.tick_stats_implied_by(fit, futures_tick_bps=0.25)
    xc = prob.crosscheck_against_tick(fit, consistent)
    assert xc.s_independent == pytest.approx(s, rel=1e-9)
    assert xc.ratio_h == pytest.approx(1.0) and xc.ratio_s == pytest.approx(1.0)
    assert xc.agrees

    # same tick, so ratio_h stays exactly 1; a dispersion implying 3x the mid
    # error must still be a disagreement
    wide = frozen_conf.TickStats(median_tick_bps=2 * h,
                                 disp_jns=math.sqrt(h ** 2 + (3 * s) ** 2),
                                 futures_tick_bps=0.25)
    xc_bad = prob.crosscheck_against_tick(fit, wide)
    assert xc_bad.ratio_h == pytest.approx(1.0)
    assert xc_bad.ratio_s == pytest.approx(1 / 3, rel=1e-6)
    assert not xc_bad.agrees


def test_fit_mixture_raises_the_crosscheck_flag_when_a_good_mle_contradicts_the_tick():
    """The flag has to be emitted by the FIT, not only by the checker.

    ``test_crosscheck_flags_a_fit_that_disagrees_with_the_tick`` calls
    :func:`prob.crosscheck_against_tick` directly, so the branch in
    :func:`prob.fit_mixture` that turns a disagreement into a flag was
    unexercised: replacing its condition with ``if False`` changed nothing.
    Here the MLE is reliable (well separated, n = 4,000) so the comparison is a
    statement, and the tick is 4.4x the fitted half-spread.
    """
    x, _ = prob.simulate(b0=0.0, h=0.45, s=0.18, n=4000, rng=_rng(311))
    stats = frozen_conf.TickStats(median_tick_bps=4.0, disp_jns=None,
                                  futures_tick_bps=0.25)
    fit = prob.fit_mixture(x, bucket="XC", tick_stats=stats)

    assert fit.mle_reliable and fit.crosscheck.comparable
    assert prob.FIT_ANCHORED_H not in fit.flags       # the MLE was kept, as it should be
    assert prob.FIT_CROSSCHECK_DISAGREES in fit.flags


def test_the_crosscheck_is_not_a_tautology_on_an_anchored_fit():
    """An anchored fit's ``h`` came FROM the tick. Comparing them checks nothing.

    This is not hypothetical. The first version compared ``fit.h`` and reported
    ``ratio_h`` of exactly 1.000 on 21 of 22 real buckets -- indistinguishable
    from a perfect result, and in fact a measurement of the anchor against
    itself. The comparison has to be the sample's own MLE, which the fit keeps
    even when a fallback replaced it.
    """
    rng = _rng(179)
    # a bucket the mixture cannot separate on its own -> the anchored route
    x, _ = prob.simulate(b0=0.0, h=0.05, s=0.20, n=3000, rng=rng)
    stats = frozen_conf.TickStats(median_tick_bps=0.90, disp_jns=None,
                                  futures_tick_bps=0.25)
    fit = prob.fit_mixture(x, bucket="TAUT", tick_stats=stats)

    assert prob.FIT_ANCHORED_H in fit.flags
    assert fit.h == pytest.approx(0.45)              # h IS the anchor
    assert fit.h_mle is not None and fit.h_mle != pytest.approx(0.45)
    assert fit.crosscheck.ratio_h != pytest.approx(1.0, abs=1e-6)
    assert fit.crosscheck.h_fit == pytest.approx(fit.h_mle)
    # ...and it declines to make a claim, because the MLE it would compare is
    # itself the thing that failed
    assert not fit.crosscheck.comparable
    assert prob.FIT_CROSSCHECK_DISAGREES not in fit.flags


# --------------------------------------------------------------------------
# 5. Buckets and pooling.
# --------------------------------------------------------------------------

def test_a_thin_bucket_pools_into_its_parent_rather_than_fitting_three_params():
    """A bucket with 30 prints cannot support a 3-parameter mixture fit."""
    rng = _rng(31)
    rows = []
    for tb in ("1Y-2Y", "2Y-3Y"):
        x, _ = prob.simulate(b0=0.0, h=0.25, s=0.15, n=6000, rng=rng)
        rows.append(prob.frame(x, venue=conv_venue(), rate_index="SOFR",
                               structure="OUTRIGHT", tenor_band=tb))
    thin, _ = prob.simulate(b0=0.0, h=0.25, s=0.15, n=30, rng=rng)
    rows.append(prob.frame(thin, venue=conv_venue(), rate_index="SOFR",
                           structure="OUTRIGHT", tenor_band="30Y+"))
    import pandas as pd
    cal = prob.Calibration.fit(pd.concat(rows, ignore_index=True))

    thin_key = prob.BucketKey(conv_venue(), "SOFR", "OUTRIGHT", "STANDARD", "30Y+")
    fit = cal.for_key(thin_key)
    assert prob.FIT_POOLED in fit.flags
    assert fit.pooled_from is not None
    assert fit.n >= prob.MIN_BUCKET_N


def test_pooling_walks_the_ladder_and_always_terminates_at_a_global_fit():
    import pandas as pd
    x, _ = prob.simulate(b0=0.0, h=0.3, s=0.2, n=5000, rng=_rng(37))
    df = prob.frame(x, venue="D2C", rate_index="SOFR",
                    structure="OUTRIGHT", tenor_band="2Y-3Y")
    cal = prob.Calibration.fit(df)
    exotic = prob.BucketKey("D2D", "FED_FUNDS", "FLY", "FOMC", "20Y-30Y")
    fit = cal.for_key(exotic)
    assert fit is not None
    # The donor is named, not just the fact of pooling: ``FIT_POOLED`` is set on
    # every non-exact match, so asserting the flag alone would pass identically
    # if the ladder had walked to some wrong bucket. Nothing in this frame
    # matches any level of the exotic key, so the answer has to be the global.
    assert prob.FIT_POOLED in fit.flags
    assert fit.pooled_from == prob.GLOBAL_BUCKET
    assert fit.bucket == exotic.label()          # asked-for bucket, donor named


def _parent_child_frame(n_child, *, h_parent=0.20, h_child=0.07, s=0.20,
                        seed=5):
    """A thin child bucket whose PARENT has a three-times wider half-spread.

    :data:`prob.DEFAULT_POOLING_ORDER` drops ``venue_class`` first, so the
    leaf's immediate parent is the venue-dropped bucket -- here dominated by
    the 6,000-row D2C population, whose ``h`` is 0.20 while the child's is
    0.07. This is the shape the tape has: one venue trades a name in size and
    another trades it thinly, and their spreads are not the same number.
    """
    import pandas as pd
    rng = _rng(seed)
    x, _ = prob.simulate(b0=0.0, h=h_parent, s=s, n=6000, rng=rng)
    parts = [prob.frame(x, venue="D2C", rate_index="SOFR",
                        structure="OUTRIGHT", tenor_band="30Y+")]
    x, _ = prob.simulate(b0=0.0, h=h_child, s=s, n=n_child, rng=rng)
    parts.append(prob.frame(x, venue="D2D", rate_index="SOFR",
                            structure="OUTRIGHT", tenor_band="30Y+"))
    return pd.concat(parts, ignore_index=True)


_VENUE_DROPPED = ("rate_index=SOFR|structure=OUTRIGHT|"
                  "special_tenor_type=STANDARD|tenor_band=30Y+")


def test_a_parents_h_is_not_an_outside_estimate_and_cannot_buy_the_lower_floor():
    """A parent's sample CONTAINS the child's rows. It is not a second opinion.

    Measured (``scratch/pf02_calfit.py``), child ``h = 0.07``, ``s = 0.20``, so
    ``tau_true = 0.286`` bp, parent ``h = 0.20``:

        anchored on the parent   tau = 0.0058   -- 49x too NARROW, and admitted
        no anchor                tau = 2.07     -- 7x too wide, and pooled away

    The narrow one is the dangerous one: at ``tau = 0.0058`` a deviation of
    0.02 bp -- noise on any curve -- is called at ``p = 0.97``. And it was
    admitted to the ladder because ``H_FROM_INDEPENDENT_ESTIMATE`` halved the
    sample floor, on the strength of an ``h`` that is not independent of
    anything. The anchored floor was measured with an EXACT anchor
    (``scratch/prob06_anchored.py``); this one is 2.9x too high.

    Borrowing from the parent is what the pooling ladder is for, and it borrows
    the parent's whole coherent ``(b0, h, s)`` rather than splicing the
    parent's ``h`` onto the child's second moment.
    """
    cal = prob.Calibration.fit(_parent_child_frame(450))
    key = prob.BucketKey("D2D", "SOFR", "OUTRIGHT", "STANDARD", "30Y+")
    leaf = cal.fits[key.label()]
    tau_true = 0.20 ** 2 / (2 * 0.07)

    assert prob.FIT_ANCHORED_H not in leaf.flags
    assert leaf.min_n_required == prob.MIN_BUCKET_N
    # unidentifiable and unanchored -> the no-information limit, which is WIDE
    assert leaf.tau > tau_true

    served = cal.for_key(key)
    assert prob.FIT_POOLED in served.flags
    assert served.pooled_from == _VENUE_DROPPED
    assert abs(prob.p_customer_paid(0.02, served) - 0.5) < 0.10


def test_a_large_unidentifiable_bucket_keeps_a_wide_tau_not_its_parents_spread():
    """The half a sample floor cannot fix, and the reason the route had to go.

    Above the floor the bucket is served on its own, so the floor never gets a
    say: with the parent's ``h`` spliced in, this bucket reported
    ``tau = 0.041`` against a true 0.286 (7x narrow) at n = 2,000 and 0.016
    (18x) at n = 6,000 -- admitted at every size. Flagging the provenance
    honestly would not have changed one of those numbers.
    """
    cal = prob.Calibration.fit(_parent_child_frame(2000))
    key = prob.BucketKey("D2D", "SOFR", "OUTRIGHT", "STANDARD", "30Y+")
    served = cal.for_key(key)
    tau_true = 0.20 ** 2 / (2 * 0.07)

    assert served.pooled_from is None            # big enough to answer for itself
    assert prob.FIT_ANCHORED_H not in served.flags
    assert prob.FIT_UNSEPARATED in served.flags
    assert served.tau > tau_true
    assert abs(prob.p_customer_paid(0.02, served) - 0.5) < 0.10


def test_pooling_reads_the_trimmed_count_because_the_trim_removes_real_mass():
    """``n`` and ``n_trimmed`` differ by the legacy tape's 1e4 bp pathologies.

    A bucket with 900 prints of which 200 are unusable has 700 usable ones, and
    700 is below the floor. Reading the raw ``n`` admits it; reading
    ``n_trimmed`` pools it. That is the difference between a fit on 700
    observations being published and the parent's fit on 6,900 being published.
    """
    import pandas as pd
    rng = _rng(97)
    x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=6000, rng=rng)
    parts = [prob.frame(x, venue="D2C", rate_index="SOFR",
                        structure="OUTRIGHT", tenor_band="30Y+")]
    core, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=700, rng=rng)
    junk = rng.normal(0.0, 1.0, 200) * 1e4
    parts.append(prob.frame(np.concatenate([core, junk]), venue="D2D",
                            rate_index="SOFR", structure="OUTRIGHT",
                            tenor_band="30Y+"))
    cal = prob.Calibration.fit(pd.concat(parts, ignore_index=True))

    key = prob.BucketKey("D2D", "SOFR", "OUTRIGHT", "STANDARD", "30Y+")
    leaf = cal.fits[key.label()]
    assert leaf.n >= prob.MIN_BUCKET_N > leaf.n_trimmed      # the whole point
    served = cal.for_key(key)
    assert prob.FIT_POOLED in served.flags
    assert served.pooled_from == _VENUE_DROPPED


def test_min_bucket_n_is_the_measured_floor_not_a_round_number():
    """Set by :func:`prob.recovery_grid`, which is re-run at reduced scale below."""
    assert prob.MIN_BUCKET_N == prob.MEASURED_MIN_BUCKET_N
    assert prob.MIN_BUCKET_N_ANCHORED == prob.MEASURED_MIN_BUCKET_N_ANCHORED
    assert prob.MIN_BUCKET_N > prob.MIN_BUCKET_N_ANCHORED > 100


def test_the_tau_se_gate_is_the_p90_of_an_ABSOLUTE_error():
    """``MAX_SE_LOG_TAU`` converts a tolerance into a standard error, once.

    :data:`prob.TAU_RECOVERY_TOLERANCE` is a p90 of ``|tau_hat/tau - 1|`` --
    :func:`prob.tau_recovery_error` takes ``abs`` before the quantile. The p90
    of ``|N(0, s)|`` is ``1.6449 s`` (it is the 95th percentile of the signed
    error), not ``1.2816 s``. Using the signed quantile leaves the gate 28.3%
    too loose, so fits whose own likelihood cannot hold ``tau`` inside the
    stated tolerance keep it anyway -- in exactly the marginal band the rule
    exists to police.
    """
    from scipy import stats as sps

    z = np.abs(_rng(0).standard_normal(2_000_000))
    p90_abs = float(np.quantile(z, 0.90))
    assert p90_abs == pytest.approx(1.6449, abs=0.005)          # measured
    assert p90_abs == pytest.approx(float(sps.norm.ppf(0.95)), abs=0.005)
    assert float(sps.norm.ppf(0.90)) == pytest.approx(1.2816, abs=0.001)

    assert prob.MAX_SE_LOG_TAU == pytest.approx(
        prob.TAU_RECOVERY_TOLERANCE / p90_abs, rel=2e-3)
    assert prob.MAX_SE_LOG_TAU < prob.TAU_RECOVERY_TOLERANCE / 1.2816
    # stated the other way round: a fit sitting exactly on the gate is exactly
    # at the tolerance, which is what "expressed as an SE" has to mean
    assert p90_abs * prob.MAX_SE_LOG_TAU == pytest.approx(
        prob.TAU_RECOVERY_TOLERANCE, rel=2e-3)


def _refusal_and_error(n, h, s, reps=200, seed=909):
    """Refusal rate, and the p90 error over the draws that did not refuse.

    Reported separately because the combined p90 is BIMODAL near the floor --
    a refusal is pinned at ~20x -- so whether the p90 lands in the good mass or
    the refusal mass is a coin flip across seeds. It swung 0.319 to 20.3
    between two seeds at n=400. Splitting them makes both halves stable, and it
    makes the two failure modes distinguishable, which the combined number
    does not.
    """
    rng = _rng(seed)
    truth = s * s / (2 * h)
    refused, errs = 0, []
    for _ in range(reps):
        x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
        f = prob.fit_mixture(x, bucket="F", min_n=0)
        refused += prob.FIT_UNSEPARATED in f.flags
        errs.append(abs(f.tau / truth - 1.0))
    e = np.asarray(errs)
    kept = e[e < 5.0]
    return refused / reps, float(np.quantile(kept, 0.90)) if kept.size else float("inf")


def test_the_measured_floor_reproduces_at_reduced_scale():
    """Re-derive the constant rather than trusting the comment above it.

    Exercised at the case that BINDS -- ``h/s = 1``, which is what a
    Citi-quality bucket looks like (F-15) and which is the column that set 800.
    At an easier separation almost any floor would pass, so testing there would
    pin nothing.

    Both clauses matter. The first says the floor is high enough; the second,
    that a quarter of it is not, is what stops the floor drifting down.
    """
    refusal, p90 = _refusal_and_error(prob.MIN_BUCKET_N, 0.18, 0.18)
    assert refusal <= 0.03, refusal
    assert p90 <= prob.TAU_RECOVERY_TOLERANCE, p90

    refusal_low, p90_low = _refusal_and_error(prob.MIN_BUCKET_N // 4, 0.18, 0.18)
    assert refusal_low > 0.15, refusal_low
    assert p90_low > prob.TAU_RECOVERY_TOLERANCE, p90_low


def test_below_h_over_s_of_one_the_mixture_is_simply_not_identifiable():
    """The wall, stated as a test so it cannot be forgotten by a later reader.

    This is not slow convergence. At ``h/s = 0.75`` the fit still refuses on
    18% of draws at n=1600, and no sample size the tape provides fixes it: the
    population excess kurtosis at ``h/s = 0.5`` is -0.080 against a sampling
    SE of ``sqrt(24/n)``, so separation needs n > 34,000. Refusing is the
    correct behaviour -- the alternative is a confident ``tau`` from noise.
    """
    assert 24.0 / (0.080 / 3.0) ** 2 > 30_000          # the n a sign test needs
    refusal, _ = _refusal_and_error(1600, 0.75 * 0.18, 0.18, reps=120)
    assert refusal > 0.10, refusal


def test_the_anchored_floor_reproduces_too_and_is_genuinely_lower():
    """The anchor is what makes an ``h/s <= 1`` bucket estimable at all.

    Same measurement, same tolerance, ``h`` supplied from outside. If the
    anchored path were not materially better here there would be no reason to
    carry a second floor -- so the test asserts the *gap*, not just the level.
    """
    h, s, n = 0.18, 0.18, prob.MIN_BUCKET_N_ANCHORED
    rng = _rng(211)
    errs, anchored = [], 0
    for _ in range(150):
        x, _ = prob.simulate(b0=0.0, h=h, s=s, n=n, rng=rng)
        stats = frozen_conf.TickStats(median_tick_bps=2 * h, disp_jns=None,
                                      futures_tick_bps=0.25)
        fit = prob.fit_mixture(x, bucket="A", tick_stats=stats)
        anchored += prob.FIT_ANCHORED_H in fit.flags
        errs.append(abs(fit.tau / (s * s / (2 * h)) - 1.0))

    assert float(np.quantile(errs, 0.90)) <= prob.TAU_RECOVERY_TOLERANCE
    # The anchor is the majority route at h/s = 1 and vanishes as the sample
    # starts to identify itself -- that is the routing behaving as designed
    # rather than the anchor being used unconditionally. Measured under the
    # corrected MAX_SE_LOG_TAU (scratch/pf06_routing.py): 0.887 here, 0.117 at
    # h/s = 1.25, 0.000 at 1.5 and above. The old band (0.3-0.9) was measured
    # under the gate's wrong quantile, where the anchor was reached for on 0.433
    # of these draws; the pair of clauses below says more than that band did,
    # because the second one is what "not unconditional" actually means.
    assert anchored / 150 > 0.5
    rng = _rng(217)
    still = sum(prob.FIT_ANCHORED_H in prob.fit_mixture(
        prob.simulate(b0=0.0, h=1.5 * s, s=s, n=n, rng=rng)[0], bucket="B",
        tick_stats=frozen_conf.TickStats(median_tick_bps=3 * s, disp_jns=None,
                                         futures_tick_bps=0.25)).flags
        for _ in range(60))
    assert still / 60 <= 0.05, still

    # ...and the same bucket without an anchor refuses on an eighth of draws
    refusal, _ = _refusal_and_error(n, h, s)
    assert refusal > 0.05, refusal


def test_a_well_separated_bucket_ignores_the_anchor_and_keeps_its_own_mle():
    """The other half of the routing rule, and the reason it is not "always
    anchor when one exists".

    At ``h/s = 2.5`` the unanchored MLE is excellent (p90 0.12 at n=400) and an
    anchor that is 25% low would cost a factor of 4.4 -- measured, in
    ``scratch/prob07_route.py``. So a bucket whose own likelihood pins ``tau``
    down must keep it, whatever tick estimate happens to be available.
    """
    rng = _rng(213)
    h, s = 0.45, 0.18
    stats = frozen_conf.TickStats(median_tick_bps=2 * h, disp_jns=None,
                                  futures_tick_bps=0.25)
    used = sum(prob.FIT_ANCHORED_H in prob.fit_mixture(
        prob.simulate(b0=0.0, h=h, s=s, n=400, rng=rng)[0],
        bucket="W", tick_stats=stats).flags for _ in range(60))
    assert used == 0


def test_tenor_bands_partition_the_line_with_no_gap_and_no_overlap():
    edges = prob.TENOR_BAND_EDGES
    assert edges[0] == 0.0 and edges[-1] == float("inf")
    assert list(edges) == sorted(edges)
    assert len(prob.TENOR_BAND_LABELS) == len(edges) - 1
    for years, expect in [(0.02, prob.TENOR_BAND_LABELS[0]),
                          (2.0, "1Y-2Y"), (2.0001, "2Y-3Y"),
                          (45.0, prob.TENOR_BAND_LABELS[-1])]:
        assert prob.tenor_band(years) == expect


def test_a_tenor_that_is_not_a_tenor_is_refused_rather_than_put_in_the_first_band():
    """Bands are ``(lo, hi]`` and the first one is ``(0, 1M]``, so zero is not in it.

    A zero or negative tenor is a broken or mis-signed term, and calibrating it
    against the 0-1M half-spread -- the tightest bucket on the grid, so the
    most confident ``tau`` -- turns a data defect into a confident call. It has
    to land in a bucket that has no fit, which is what UNKNOWN is for.
    """
    for bad in (0.0, -0.0, -3.0, -1e-9):
        assert prob.tenor_band(bad) == "UNKNOWN", bad
    assert prob.tenor_band(float("nan")) == "UNKNOWN"
    assert prob.tenor_band(None) == "UNKNOWN"
    assert prob.tenor_band(1e-9) == prob.TENOR_BAND_LABELS[0]   # still a tenor


# --------------------------------------------------------------------------
# 6. The dead zone -- in probability space, cross-checked in bp.
# --------------------------------------------------------------------------

def test_dead_zone_width_is_the_logit_of_delta_times_tau():
    fit = prob.MixtureFit("D", 1000, 1000, 0.0, 0.25, 0.20, 0.0)
    for delta in (0.01, 0.05, 0.15):
        w = prob.dead_zone_half_width_bps(fit.tau, delta)
        assert w == pytest.approx(fit.tau * math.log((0.5 + delta) / (0.5 - delta)))
        # and it is exactly the boundary: at w, |p - 0.5| == delta
        assert abs(prob.p_customer_paid(w, fit) - 0.5) == pytest.approx(delta)


def test_the_dead_zone_is_reporting_only_because_2p_minus_1_already_handles_it():
    """DESIGN 1.3: the aggregation does not depend on the dead zone."""
    fit = prob.MixtureFit("D", 1000, 1000, 0.0, 0.25, 0.20, 0.0)
    call = prob.direction_probability(0.0, fit)
    assert call.in_dead_zone
    assert call.signed_weight == pytest.approx(0.0)
    assert call.p == pytest.approx(0.5)


def test_the_briefs_dead_zone_in_bp_implies_a_very_wide_delta_on_a_good_curve():
    """The cross-check the brief asked for, and it does not come out at 0.05 bp.

    With Citi-quality mids (F-15: IQR 0.266 bp, 40.5% inside +-0.1 bp) a
    plausible bucket is ``h ~ 0.15``, ``s ~ 0.13``, so ``tau ~ 0.056`` bp. A
    ``delta = 0.05`` dead zone is then 0.0113 bp on each side -- four to nine
    times NARROWER than the brief's 0.05-0.1 bp. Reaching the brief's range
    needs ``delta`` of 0.21 to 0.36, i.e. abstaining on everything between
    p=0.29 and p=0.71, or between 0.145 and 0.855. Recorded as a finding, not
    silently reconciled: the brief's number is right for a curve whose mid
    error is of that order, which the Barchart curve's is (median |s2m| 0.71
    bp) and the Citi curve's is not.
    """
    citi = prob.MixtureFit("CITI", 5000, 5000, 0.02, 0.15, 0.13, 0.0)
    assert citi.tau == pytest.approx(0.0563, abs=0.002)
    assert prob.dead_zone_half_width_bps(citi.tau, 0.05) == pytest.approx(0.0113,
                                                                          abs=0.0005)
    assert prob.delta_for_dead_zone_bps(citi.tau, 0.05) == pytest.approx(0.208,
                                                                         abs=0.01)
    assert prob.delta_for_dead_zone_bps(citi.tau, 0.10) == pytest.approx(0.355,
                                                                         abs=0.01)

    # ...and on the legacy Barchart curve the brief's number IS about right:
    # median |s2m| 0.71 bp, so s is of order 0.5 bp and tau of order 0.5 bp.
    barchart = prob.MixtureFit("BARCHART", 5000, 5000, -0.48, 0.25, 0.50, 0.0)
    assert 0.04 < prob.dead_zone_half_width_bps(barchart.tau, 0.05) < 0.12


def test_delta_and_bp_width_are_inverses():
    for tau in (0.02, 0.056, 0.4):
        for delta in (0.02, 0.1, 0.35):
            w = prob.dead_zone_half_width_bps(tau, delta)
            assert prob.delta_for_dead_zone_bps(tau, w) == pytest.approx(delta)


# --------------------------------------------------------------------------
# 7. Time variation -- and a stability test with a known answer both ways.
# --------------------------------------------------------------------------

def test_se_log_tau_matches_the_empirical_spread():
    """Validate the measurement tool before using it.

    ``tau_stability`` weights by ``se_log_tau``, which is a finite-difference
    Hessian -- exactly the kind of quantity that can be quietly wrong and make
    a heterogeneity test reject or accept for the wrong reason. So the analytic
    SE is checked against the actual spread of repeated fits at known
    parameters, which is the only thing that could catch it.
    """
    rng = _rng(1009)
    logtaus, ses = [], []
    for _ in range(200):
        x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=800, rng=rng)
        f = prob.fit_mixture(x, bucket="SE")
        if f.se_log_tau:
            logtaus.append(math.log(f.tau))
            ses.append(f.se_log_tau)
    empirical = float(np.std(logtaus, ddof=1))
    analytic = float(np.median(ses))
    assert analytic == pytest.approx(empirical, rel=0.25), (analytic, empirical)


def _period_fits(seeds, s_by_period, n=800):
    rng = _rng(seeds)
    fits = []
    for s in s_by_period:
        x, _ = prob.simulate(b0=0.0, h=0.25, s=s, n=n, rng=rng)
        fits.append(prob.fit_mixture(x, bucket="S"))
    return fits


def test_tau_stability_does_not_reject_a_stationary_series():
    st = prob.tau_stability(_period_fits(41, [0.18] * 24), seed=5)
    assert not st.moves, st


def test_tau_stability_detects_a_regime_shift():
    """The other direction. Half the periods at twice the mid error.

    Doubling ``s`` QUADRUPLES tau, so a test that cannot see this cannot see
    anything.
    """
    st = prob.tau_stability(_period_fits(43, [0.18] * 12 + [0.36] * 12), seed=5)
    assert st.moves, st
    assert st.spread_ratio > 2.0


def test_the_two_stability_nulls_agree():
    """The chi-square null leans on the SE; the bootstrap null does not.

    If they disagreed, the SE would be the suspect. They are run against each
    other on the same data so that a wrong SE cannot pass unnoticed.
    """
    stationary = _period_fits(41, [0.18] * 8)
    shifted = _period_fits(43, [0.18] * 4 + [0.36] * 4)
    assert not prob.tau_stability(stationary, method="bootstrap",
                                  reps=60, seed=5).moves
    assert prob.tau_stability(shifted, method="bootstrap", reps=60, seed=5).moves


def test_a_failed_bootstrap_replicate_is_not_counted_as_evidence_for_the_null():
    """A replicate that could not be fitted is not a draw from the null.

    ``_bootstrap_q_pvalue`` skipped such replicates but kept ``reps`` in the
    denominator, so each one scored silently as "not worse than observed" and
    pushed the p-value down -- towards rejecting the null that ``tau`` is
    constant. Stated as an invariant that does not depend on the sampling: with
    ``q_obs = 0`` every valid replicate is at least as extreme, so the p-value
    is 1.0 by construction. Measured before the fix at these settings: 0.122.
    """
    fits = [prob.MixtureFit(f"P{i}", 60, 60, 0.0, 0.18, 0.18, 0.0,
                            se_log_tau=0.2) for i in range(3)]
    p, used = prob._bootstrap_q_pvalue(fits, 0.0, reps=40, seed=3)
    assert p == pytest.approx(1.0)
    # ...and replicates really did fail here, or the invariant pins nothing
    assert 0 < used < 40, used


def test_the_bootstrap_refuses_to_rule_when_every_replicate_failed():
    """Zero valid replicates is not a null distribution.

    With one observation per period every replicate fit is degenerate and has
    no standard error, so all of them were skipped -- and the old arithmetic
    returned ``1/(reps+1) = 0.024``, i.e. ``TauStability(moves=True)``, a
    verdict manufactured out of total estimation failure. This is the check
    that is supposed to be independent of ``se_log_tau``, so failing towards
    "the SE-based test was right" is the worst available direction.
    """
    fits = [prob.MixtureFit(f"P{i}", 1, 1, 0.0, 0.18, 0.18, 0.0,
                            se_log_tau=0.2) for i in range(3)]
    with pytest.raises(ValueError, match="replicate"):
        prob._bootstrap_q_pvalue(fits, 1e9, reps=20, seed=1)


def test_tau_stability_says_how_many_fits_it_threw_away():
    """Every fallback fit has ``se_log_tau = None``, and on real data that is all
    of them. Dropping them is right -- weighting by a fabricated SE would not
    be -- but reporting ``k`` without the count makes a test on 2 of 30 periods
    look like a test on the series."""
    with_se = [prob.MixtureFit(f"S{i}", 800, 800, 0.0, 0.25, 0.18, 0.0,
                               se_log_tau=0.08) for i in range(4)]
    without = [prob.MixtureFit(f"N{i}", 800, 800, 0.0, 0.25, 0.18 + 0.01 * i,
                               0.0) for i in range(6)]
    st = prob.tau_stability(with_se + without)
    assert st.k == 4
    assert st.n_dropped == 6


def test_report_of_a_calibration_with_no_fits_still_has_its_columns():
    """A column-less frame raises far from the cause, in the caller's code."""
    rep = prob.Calibration({}).report()
    assert rep.empty
    for col in ("bucket", "n", "n_trimmed", "b0_bps", "tau_bps", "fit_flags"):
        assert col in rep.columns


def test_the_report_lets_a_reader_reconstruct_tau_from_the_columns_beside_it():
    """``separation`` is ``h/s`` on the RAW ``h``; ``tau`` uses ``h`` floored at
    ``MIN_SEPARATION * s``. On a floored bucket the two disagree by the floor,
    so a reviewer reading ``separation = 0.014`` next to ``tau = 4.879`` cannot
    get from one to the other. The floored ``h`` is reported too."""
    rng = _rng(29)
    x = rng.normal(0.0, 0.2, 3000)                # no spread at all -> floored
    cal = prob.Calibration({"FLAT": prob.fit_mixture(x, bucket="FLAT", min_n=0)})
    row = cal.report().iloc[0]
    assert row["h_used_bps"] >= row["h_bps"]
    assert row["tau_bps"] == pytest.approx(
        row["s_bps"] ** 2 / (2 * row["h_used_bps"]))


def test_a_rolling_calibration_that_classifies_nothing_raises():
    """An empty dict is indistinguishable from success at the call site.

    Measured: 200 rows over 10 days returns ``{}`` with no exception, no
    warning and no flag, and a caller that iterates it classifies nothing and
    reports a clean run.
    """
    import pandas as pd
    rng = _rng(51)
    frames = []
    for d in pd.bdate_range("2026-01-01", periods=10):
        x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=20, rng=rng)
        f = prob.frame(x, venue="D2C", rate_index="SOFR",
                       structure="OUTRIGHT", tenor_band="2Y-3Y")
        f["as_of_date"] = d.date()
        frames.append(f)
    with pytest.raises(ValueError, match="no calibration window"):
        prob.rolling_calibrations(pd.concat(frames, ignore_index=True),
                                  window_days=5, min_gap_days=1)


def test_a_rolling_calibration_says_how_many_days_it_could_not_calibrate():
    """The partial case. The first days of any window have nothing behind them,
    which is expected -- but the count has to be visible, because the same
    silence covers a genuine hole in the middle of the sample."""
    import pandas as pd
    rng = _rng(53)
    frames = []
    for d in pd.bdate_range("2026-01-01", periods=40):
        x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=300, rng=rng)
        f = prob.frame(x, venue="D2C", rate_index="SOFR",
                       structure="OUTRIGHT", tenor_band="2Y-3Y")
        f["as_of_date"] = d.date()
        frames.append(f)
    df = pd.concat(frames, ignore_index=True)
    with pytest.warns(UserWarning, match=r"skipped \d+ of \d+"):
        windows = prob.rolling_calibrations(df, window_days=10, min_gap_days=1)
    assert 0 < len(windows) < 40


def test_the_rolling_window_never_looks_ahead():
    """A calibration that contains the day it classifies is not a calibration."""
    import pandas as pd
    rng = _rng(47)
    frames = []
    for d in pd.bdate_range("2026-01-01", periods=60):
        x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=120, rng=rng)
        f = prob.frame(x, venue="D2C", rate_index="SOFR",
                       structure="OUTRIGHT", tenor_band="2Y-3Y")
        f["as_of_date"] = d.date()
        frames.append(f)
    df = pd.concat(frames, ignore_index=True)

    windows = prob.rolling_calibrations(df, window_days=20, min_gap_days=1)
    assert windows
    for as_of, (lo, hi, _cal) in windows.items():
        assert hi < as_of, f"calibration for {as_of} used data up to {hi}"
        assert (as_of - lo).days >= 20


# --------------------------------------------------------------------------
# 8. Calibration -- the killer test, run where labels exist.
# --------------------------------------------------------------------------

def test_p_is_calibrated_on_simulated_data_where_labels_exist():
    """Among trades with p ~ 0.7, about 70% must really be on that side.

    This is measurable ONLY here, because simulation has labels and the tape
    does not. Fitted on one half, evaluated on the other, so the reliability
    is out of sample.
    """
    rng = _rng(53)
    x_fit, _ = prob.simulate(b0=0.01, h=0.24, s=0.19, n=40_000, rng=rng)
    x_test, paid = prob.simulate(b0=0.01, h=0.24, s=0.19, n=40_000, rng=rng)

    fit = prob.fit_mixture(x_fit, bucket="CAL")
    rel = prob.reliability(prob.p_customer_paid(x_test, fit), paid, n_bins=10)

    assert rel["n"].sum() == 40_000
    dense = rel[rel["n"] >= 500]
    assert len(dense) >= 6
    assert (dense["realised"] - dense["mean_p"]).abs().max() < 0.05
    assert prob.brier(prob.p_customer_paid(x_test, fit), paid) < 0.25


def test_calibration_degrades_measurably_under_asymmetric_flow():
    """What the fixed-0.5 weight costs when the assumption is false.

    Requirement 1 fixes the weight because a free one is not identifiable from
    ``b0`` and would book a curve bias as a flow imbalance -- the error that
    inverts calls. The price is that genuine 65/35 flow is read as a curve
    bias instead. That price is a number, so it is measured: the reliability
    curve shifts, and the direction of the shift is towards 0.5, i.e. the model
    UNDER-calls the busy side. Under-calling is the safe failure.
    """
    rng = _rng(59)
    b0, h, s = 0.0, 0.25, 0.18
    x, paid = prob.simulate(b0=b0, h=h, s=s, n=60_000, rng=rng, weight_paid=0.65)
    fit = prob.fit_mixture(x, bucket="ASYM")

    # the imbalance is absorbed into b0, exactly as DESIGN 1.2 warns
    assert fit.b0 > 0.02
    rel = prob.reliability(prob.p_customer_paid(x, fit), paid, n_bins=10)
    dense = rel[rel["n"] >= 1000]
    gap = (dense["realised"] - dense["mean_p"])
    assert gap.abs().max() > 0.05                 # it IS miscalibrated
    assert gap.mean() > 0                         # and it under-calls, not over


def test_implied_split_is_a_real_out_of_sample_check_not_a_tautology():
    """``mean(p) == 0.5`` is imposed in-sample and free out of sample.

    So it detects the thing it needs to detect: the calibration window's bias
    no longer describing the day being classified.
    """
    rng = _rng(61)
    x_fit, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=30_000, rng=rng)
    fit = prob.fit_mixture(x_fit, bucket="IS")

    same, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=30_000, rng=rng)
    assert prob.implied_split(same, fit).mean_p == pytest.approx(0.5, abs=0.02)

    shifted, _ = prob.simulate(b0=0.30, h=0.25, s=0.18, n=30_000, rng=rng)
    drifted = prob.implied_split(shifted, fit)
    assert drifted.mean_p > 0.65
    assert not drifted.consistent


def test_goodness_of_fit_rejects_a_bucket_the_mixture_does_not_describe():
    """Evaluated out of sample, because in sample the KS p-value is not valid.

    Three parameters spent on the same points makes the statistic
    anti-conservative -- it would reject a correct fit too often. So the fit
    and the test use different draws, which is also how it would be used for
    real: calibrate on the window, test on the day.
    """
    rng = _rng(67)
    x_fit, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=8000, rng=rng)
    x_test, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=8000, rng=rng)
    good = prob.fit_mixture(x_fit, bucket="G")
    assert prob.gof_ks(x_test, good).p_value > 0.01

    lump = np.concatenate([x_test, rng.normal(0.0, 2.5, 2000)])
    assert prob.gof_ks(lump, good).p_value < 1e-6


# --------------------------------------------------------------------------
# 9. Degeneracies that must be refused rather than absorbed.
# --------------------------------------------------------------------------

def test_no_separation_gives_no_information_and_says_so():
    """``h -> 0`` means the two sides are indistinguishable. p must go to 0.5."""
    rng = _rng(71)
    x = rng.normal(0.0, 0.2, 20_000)          # one component, no spread at all
    fit = prob.fit_mixture(x, bucket="FLAT")
    assert prob.FIT_UNSEPARATED in fit.flags
    assert abs(prob.p_customer_paid(0.3, fit) - 0.5) < 0.10


@pytest.mark.parametrize("x", [
    np.array([0.25]),                       # a singleton bucket
    np.zeros(40),                           # every print exactly at mid
    np.full(500, -0.5),                     # every print on one lattice point
])
def test_a_zero_dispersion_bucket_gives_no_information_instead_of_a_nan(x):
    """783 of 1,689 real legacy buckets hit this, and it produced a NaN tau.

    The EM divides by ``s^2`` and there is no ``s`` when every trimmed print
    sits on one value. A NaN then propagates silently: the pooling rule steps
    past these on size, but ``report()`` and ``tau_stability`` do not.

    The direction of the fallback is the part that matters. Flooring ``s`` at
    something tiny makes ``p`` a step function at ``b0`` -- maximal confidence
    out of a bucket containing no information whatsoever. It has to go the
    other way.
    """
    fit = prob.fit_mixture(x, bucket="DEGEN", min_n=0)

    assert math.isfinite(fit.tau) and fit.tau > 0
    assert prob.FIT_UNSEPARATED in fit.flags
    assert not fit.mle_reliable
    for dev in (-2.0, 0.0, 2.0):
        assert abs(prob.p_customer_paid(dev, fit) - 0.5) < 0.15


def test_no_bucket_shape_makes_the_fit_emit_a_numpy_warning():
    """Warnings are how this class of defect announced itself, so they are errors.

    ``invalid value encountered in divide`` was the only visible symptom of the
    NaN above -- the fits still returned, still looked plausible in a table,
    and 46% of real buckets were affected.
    """
    rng = _rng(191)
    shapes = [np.array([1.0]), np.zeros(3), np.full(20, 2.5),
              np.array([0.0, 0.0, 0.0, 9e3]), rng.normal(0, 1e-12, 50),
              np.array([1e-300, -1e-300]), np.concatenate([np.zeros(400),
                                                           np.full(400, 1e-9)])]
    # Underflow is excluded deliberately: ``exp`` of a very negative number
    # going to zero is the logistic working, not failing. ``divide``,
    # ``invalid`` and ``over`` are the three that mean a NaN or an infinity is
    # about to be handed to a consumer.
    with np.errstate(divide="raise", invalid="raise", over="raise"), \
            warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        for x in shapes:
            fit = prob.fit_mixture(x, bucket="EDGE", min_n=0)
            assert math.isfinite(fit.tau), x[:3]
            assert 0.0 <= prob.p_customer_paid(0.1, fit) <= 1.0


def test_an_undersized_sample_is_flagged_and_not_silently_fitted():
    x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=30, rng=_rng(73))
    fit = prob.fit_mixture(x, bucket="TINY")
    assert prob.FIT_UNDERSIZED in fit.flags


def test_fit_rejects_an_empty_or_all_nan_sample():
    with pytest.raises(ValueError):
        prob.fit_mixture(np.array([]), bucket="E")
    with pytest.raises(ValueError):
        prob.fit_mixture(np.array([np.nan, np.nan]), bucket="N")


def test_the_likelihood_is_invariant_under_the_label_swap_the_em_relies_on():
    """``h -> -h`` with the components swapped is the same model.

    This is the algebra behind ``MixtureFit``'s "h is positive by construction"
    and behind the sign branch in ``_em``: the data cannot choose the sign, the
    economics does. If the likelihood were NOT invariant, ``h > 0`` would be a
    constraint the fit is paying for rather than a labelling convention, and
    the EM's negation would be changing the answer instead of naming it.
    """
    x, _ = prob.simulate(b0=0.07, h=0.30, s=0.20, n=4000, rng=_rng(5))
    for b0, h, s in [(0.07, 0.30, 0.20), (-0.4, 0.12, 0.31), (0.0, 0.6, 0.1)]:
        assert prob.loglik(x, b0, h, s) == pytest.approx(
            prob.loglik(x, b0, -h, s), rel=1e-12)
    assert prob.fit_mixture(x, bucket="SW").h > 0


def test_the_em_reaches_at_least_the_moment_solutions_likelihood():
    """EM is monotone, so it cannot end below a competing start point."""
    x, _ = prob.simulate(b0=0.05, h=0.3, s=0.2, n=20_000, rng=_rng(79))
    fit = prob.fit_mixture(x, bucket="LL")
    xt = x[prob.trim_mask(x)]
    mc = prob.moment_estimates(xt)
    assert mc.real
    assert fit.loglik >= prob.loglik(xt, float(np.median(xt)),
                                     mc.h_moment, mc.s_moment) - 1e-8


@pytest.mark.parametrize("weight_paid", [0.5, 0.65])
def test_the_fit_is_a_stationary_point_of_the_likelihood(weight_paid):
    """No perturbation of the answer may raise the likelihood.

    A general check on the M-step algebra, and it exists because a specific
    mutation survived everything else: dropping the ``1 / (1 - mean(u)^2)``
    factor from the ``h`` update. On a symmetric sample ``mean(u)`` is ~0 and
    the factor is ~1, so the defect is invisible -- it only bites when the
    sample's location is shifted, which is exactly the case the fixed 0.5
    weight is there to handle. Hence the asymmetric parametrisation: the
    symmetric run alone would not catch it, and did not.
    """
    x, _ = prob.simulate(b0=0.0, h=0.25, s=0.18, n=40_000, rng=_rng(1013),
                         weight_paid=weight_paid)
    xt = x[prob.trim_mask(x)]
    fit = prob.fit_mixture(x, bucket="ST")
    base = prob.loglik(xt, fit.b0, fit.h, fit.s)

    for name in ("b0", "h", "s"):
        val = getattr(fit, name)
        step = 0.02 * (fit.s if name == "b0" else val)
        for sign in (+1, -1):
            kw = dict(b0=fit.b0, h=fit.h, s=fit.s)
            kw[name] = val + sign * step
            assert prob.loglik(xt, **kw) <= base + 1e-6, (name, sign)


def test_changing_the_dead_zone_cannot_move_the_ladder():
    """The invariant DESIGN 1.3 rests on, stated as a test.

    ``signed_weight`` is a function of ``p`` alone. If a future edit ever made
    the aggregation weight depend on ``in_dead_zone``, the dead zone would stop
    being a reporting flag and start being a model parameter, and every
    published ladder would depend on a constant nobody calibrated.
    """
    fit = prob.MixtureFit("DZ", 1000, 1000, 0.0, 0.25, 0.20, 0.0)
    for dev in (-0.4, -0.01, 0.0, 0.005, 0.9):
        weights = {prob.direction_probability(dev, fit, d).signed_weight
                   for d in (0.001, 0.05, 0.30, 0.49)}
        assert len(weights) == 1
    # ...while the FLAG does move, or it would not be a filter at all
    assert prob.direction_probability(0.02, fit, 0.49).in_dead_zone
    assert not prob.direction_probability(0.02, fit, 0.001).in_dead_zone


def test_the_pooling_order_is_derived_from_data_not_asserted():
    """`rank_bucket_dimensions` must rank a dimension that matters above one
    that does not -- otherwise the default order is decoration."""
    import pandas as pd
    rng = _rng(83)
    parts = []
    for band, s in [("1Y-2Y", 0.10), ("10Y-15Y", 0.60)]:      # tenor matters
        for venue in ("D2C", "D2D"):                          # venue does not
            x, _ = prob.simulate(b0=0.0, h=0.25, s=s, n=2000, rng=rng)
            parts.append(prob.frame(x, venue=venue, rate_index="SOFR",
                                    structure="OUTRIGHT", tenor_band=band))
    ranked = prob.rank_bucket_dimensions(pd.concat(parts, ignore_index=True))
    order = list(ranked["dimension"])
    assert order.index("venue_class") < order.index("tenor_band")


def test_the_default_pooling_order_is_a_permutation_of_the_bucket_columns():
    assert sorted(prob.DEFAULT_POOLING_ORDER) == sorted(prob.BUCKET_COLS)


def test_p_is_monotone_and_bounded():
    fit = prob.MixtureFit("MB", 1000, 1000, -0.1, 0.3, 0.2, 0.0)
    xs = np.linspace(-5, 5, 2001)
    ps = prob.p_customer_paid(xs, fit)
    assert np.all(np.diff(ps) >= 0)
    assert ps.min() >= 0.0 and ps.max() <= 1.0
    assert ps[0] < 1e-6 and ps[-1] > 1 - 1e-6


def test_the_sign_convention_survives_the_probability_layer():
    """Above mid -> customer paid -> dealer received. Pinned end to end."""
    fit = prob.MixtureFit("SC", 1000, 1000, 0.0, 0.25, 0.15, 0.0)
    above = prob.direction_probability(+0.5, fit)
    below = prob.direction_probability(-0.5, fit)
    assert above.p > 0.9 and below.p < 0.1
    assert conv.dealer_side(+0.5) == conv.DEALER_RECEIVED
    assert above.signed_weight > 0 > below.signed_weight
    assert above.signed_weight == pytest.approx(conv.signed_weight(above.p))


def conv_venue():
    from SDRUtils.dealer_direction import types as t
    return t.VENUE_D2C
