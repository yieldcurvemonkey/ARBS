"""Deviation from mid -> a calibrated probability that the customer paid fixed.

This is the statistical core. It turns one number per unit -- ``x = P_traded -
P_mid`` in basis points, produced by :mod:`.midprice` -- into ``p``, and it is
the module where a wrong answer is hardest to see: a mis-estimated ``tau``
produces a complete, monotone, plausible probability that is simply the wrong
width, and nothing downstream can tell. Every quantity here therefore carries
an independent check, and every check is tested in both directions.

THE MODEL
---------

For a bucket with dealer-to-client half-spread ``h > 0``, mid-measurement
error ``s``, and a systematic mid bias ``b0``::

    x | customer paid fixed      ~  N(b0 + h, s^2)
    x | customer received fixed  ~  N(b0 - h, s^2)

With the mixture weight fixed at 0.5, Bayes gives exactly a logistic::

    p(customer paid | x) = sigma( 2h(x - b0) / s^2 ) = sigma( (x - b0) / tau )

                        tau = s^2 / (2h)

**``tau`` is the mid-measurement variance over twice the half-spread, not the
half-spread.** DESIGN.md 1.1 derives it. Two consequences that the half-spread
reading gets backwards:

* a bucket with a **wider** spread is **more** decidable -- ``tau`` shrinks as
  ``h`` grows;
* mid quality enters **quadratically** -- halving ``s`` quarters ``tau``.

That second one is why the curve work was the blocker and not a nicety. The
legacy Barchart mid is biased ~0.5 bp with ~7x the dispersion of the Citi
minute curve (LEDGER F-20); on the ``tau`` scale that is not a 7x penalty, it
is a ~50x one, and it is the arithmetic reason 78% of the legacy labels came
out PAID.

WHY THE MIXTURE WEIGHT IS PINNED AT 0.5
---------------------------------------

See :func:`fit_mixture`. Short version: a free weight is not identifiable from
``b0``, and letting it float books a curve bias as a flow imbalance -- which
inverts calls rather than degrading them.

THE F-20 COMPARISON IS NOT AN EXTERNAL CHECK, AND SAYING SO IS THE POINT
------------------------------------------------------------------------

This section used to be headed "what has been checked against a number this
module did not produce". It is kept, with the numbers unchanged, because the
comparison is worth having -- but it does not validate the estimator, and
reading it as though it does is the exact error this module is built to
prevent.

On the legacy deviations (``scratch/prob05_real.py``) the fitted ``b0`` sits
beside LEDGER F-20's independently measured Barchart tenor gradient::

    bucket    F-20 median    fitted b0
    3M            -0.136       -0.129
    1Y            -0.246       -0.228
    2Y            -0.524       -0.395
    3Y            -1.237       -1.114
    IMM_2Y        -6.840       -6.584

**Every one of those buckets is flagged ``ROBUST_SCALE_FALLBACK``, where
``b0 := median(trimmed sample)``** (:func:`_anchored_decomposition`). F-20's
number is the raw median of the same rows. So the two columns are the trimmed
and untrimmed median of one sample, and the EM never produced the right-hand
column at all. What agrees is a statistic with itself under a trim.

That is still worth reporting -- it measures TRIM STABILITY, and the 25%
compression at 2Y-3Y is the trim removing an asymmetric tail that the raw
median keeps, which is a real property of that bucket -- but it is not
evidence that the mixture fit recovers a bias. The evidence for that is
:func:`test_recovers_known_parameters`, on simulated data where ``b0`` is set.
An external check on real deviations needs either labels (the D2D-print
monitor, ``health.py``, which does not exist yet) or a bucket whose MLE
survives, which on the Barchart curve is 1 in 22.

WHAT THIS MODULE DOES NOT CLAIM
-------------------------------

``p`` is **calibrated** only where it has been measured against labels, and
the tape has no labels. :func:`reliability` is exercised on simulated data,
where the answer is set, and it shows both that the estimator is calibrated
when the model holds and by how much it is not when the equal-weight
assumption is false. On real deviations the honest checks are
:func:`implied_split` (out-of-sample, non-circular) and :func:`gof_ks`
(distributional). A genuine labelled check needs the D2D-print monitor
(``health.py``), which does not exist yet. Nothing here should be read as
"p is calibrated on the tape".

The second independent check -- ``h`` against the tick lattice -- is
**implemented and currently unexercised on real data**. On the legacy Barchart
deviations the mixture MLE fails in 21 of 22 sub-3y buckets, so there is no
independent quantity left to compare the tick against, and
:attr:`SpreadCrossCheck.comparable` is False for all of them. That is the
correct report rather than a passing one, and it is a statement about the
Barchart curve, not about the check. It has to be re-run against Citi minute
deviations, and until then the ``h`` estimates beyond the reach of the moment
check rest on the fit alone.
"""
from __future__ import annotations

import dataclasses
import datetime
import math
import typing
import warnings

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import conventions as conv

# --------------------------------------------------------------------------
# Constants. Every one of these is measured or derived; none is a round number
# chosen because it looked reasonable.
# --------------------------------------------------------------------------

#: Trim radius, in robust scales, applied before the fit.
#:
#: A *quantile* trim is the obvious choice and it is a trap: removing a fixed
#: fraction from a clean two-component mixture makes the sample MORE
#: platykurtic, which makes the moment check below pass more readily and biases
#: ``s`` and ``h`` down -- so ``tau`` comes out too small and every ``p`` is
#: overconfident. A robust-scale trim removes ~nothing from clean data (<0.5%
#: at k=6, measured in ``test_the_trim_does_not_bias_a_clean_fit``) while still
#: taking out the legacy tape's genuine pathologies, which run to 1e4 bp.
TRIM_MAD_K = 6.0

#: 1 / Phi^-1(0.75). Turns a median absolute deviation into a normal-consistent
#: standard deviation.
MAD_TO_SIGMA = 1.4826

#: Minimum sample size for an **unanchored** 3-parameter mixture fit. Below
#: this the bucket pools into its parent (:class:`Calibration`).
#:
#: MEASURED, not asserted -- ``scratch/prob08_floor.py``, 500 reps per cell at
#: ``s = 0.18`` bp. The headline p90 error is BIMODAL near the floor (most
#: draws separate cleanly, a minority refuse and are pinned at the
#: no-information limit), so it swung 0.319 -> 20.3 between two seeds at
#: ``n = 400`` and is useless as a criterion. The refusal RATE is the
#: underlying quantity and it is smooth::
#:
#:     refusal rate           p90 error, non-refusing draws
#:     n \ h/s  0.75  1.00      n \ h/s  0.75   1.00
#:     ----------------------   ---------------------------
#:     200      .752  .306      200      0.492  0.318
#:     400      .600  .124      400      0.371  0.249
#:     600      .530  .036      600      0.306  0.251
#:     800      .444  .008      800      0.266  0.223
#:     1200     .276  .000      1200     0.199  0.202
#:
#: 800 is the smallest gridded ``n`` where, at ``h/s = 1``, the fit both stops
#: refusing (0.8%) and lands inside :data:`TAU_RECOVERY_TOLERANCE` (0.223). At
#: 600 it is neither (3.6% and 0.251). And ``h/s ~ 1`` is what a Citi-quality
#: bucket looks like -- F-15's total dispersion of ~0.20 bp with a plausible
#: ``h ~ 0.15`` leaves ``s ~ 0.13``.
#:
#: THE REFUSALS ARE NOT AN ESTIMATOR WEAKNESS, THEY ARE IDENTIFIABILITY. At
#: ``h/s = 0.75`` the fit still refuses 18% of the time at n = 1600, and at
#: ``h/s = 0.5`` it refuses essentially always. The arithmetic: the population
#: excess kurtosis at ``h/s = 0.5`` is -0.080 against a sampling standard error
#: of ``sqrt(24/n)``, so separating ``h`` from ``s`` out of the sample's own
#: moments needs ``n > 34,000``. **Below ``h/s ~ 1`` the mixture is not
#: identifiable and only an external anchor can rescue it** -- which is what
#: :data:`MIN_BUCKET_N_ANCHORED` and :func:`crosscheck_against_tick` are for,
#: and why "validate the fit where a second opinion is available" turned out to
#: be load-bearing rather than hygiene.
MEASURED_MIN_BUCKET_N = 800
MIN_BUCKET_N = MEASURED_MIN_BUCKET_N

#: Minimum sample size when ``h`` comes from outside the sample -- which means
#: the tick lattice sub-3y, and nothing else. Less than half the unanchored
#: floor, because only ``s`` is being estimated and it comes out of one second
#: moment rather than a three-parameter likelihood. Measured the same way --
#: ``scratch/prob06_anchored.py``, p90 ``tau`` error with an exact anchor::
#:
#:     n \ h/s    0.50    0.75    1.00    1.50    2.50
#:     ------------------------------------------------
#:     100        0.292   0.332   0.404   0.531   0.832
#:     200        0.218   0.259   0.306   0.405   0.637
#:     400        0.159   0.188   0.209   0.278   0.427
#:     800        0.091   0.107   0.119   0.166   0.278
#:
#: 400 is the smallest ``n`` inside tolerance across the whole ``h/s <= 1``
#: range, which is the range the anchor is actually used in.
#:
#: THE ANCHOR HAS TO BE RIGHT, AND THAT SENSITIVITY IS NOT SYMMETRIC. ``s`` is
#: a difference of two larger numbers, so an anchor 25% too LOW inflates
#: ``tau`` by 1.0x at ``h/s = 0.5`` and by **4.4x** at ``h/s = 2.5``, while the
#: same error high mostly collapses ``s`` to its floor. :data:`CROSSCHECK_TOLERANCE`
#: is a factor of two, and it is a FLAGGING threshold -- it must never be read
#: as "an anchor inside 2x is accurate enough to use blindly". What keeps that
#: honest is :data:`MAX_SE_LOG_TAU`: the anchor is only consulted where the
#: sample's own likelihood cannot pin ``tau`` down, which is precisely the
#: low-separation regime where the anchor is least sensitive.
#:
#: A PARENT BUCKET'S ``h`` IS NOT AN OUTSIDE ESTIMATE AND NO LONGER EARNS THIS
#: FLOOR. It used to: a thin child with no tick borrowed its parent's fitted
#: ``h``, took :data:`FIT_ANCHORED_H`, and the floor halved. The parent's
#: sample is a strict SUPERSET of the child's rows, so the borrowed number is
#: not independent of anything, and the sensitivity above applies to it at full
#: force. Measured end to end through :meth:`Calibration.fit`
#: (``scratch/pf02_calfit.py``), child ``h = 0.07``, ``s = 0.20`` --
#: ``tau_true = 0.286`` bp -- under a parent whose ``h`` is 0.20::
#:
#:     child n     parent-anchored tau     unanchored tau     admitted?
#:     450         0.0058  (49x narrow)    2.07  (7x wide)    yes / no (pooled)
#:     2000        0.0406  ( 7x narrow)    2.00  (7x wide)    yes / yes
#:     6000        0.0157  (18x narrow)    1.90  (7x wide)    yes / yes
#:
#: At ``tau = 0.0058`` a 0.02 bp deviation -- noise on any curve -- is called at
#: ``p = 0.97``. Note the second and third rows: above the floor the bucket is
#: served on its own, so relabelling the provenance and restoring the 800 floor
#: would not have moved either number. The route had to go, not be renamed.
#: Borrowing from the parent is what the pooling ladder is for, and it borrows
#: the parent's whole coherent ``(b0, h, s)`` -- in the 450-row case above,
#: ``tau = 0.100`` against a true 0.286 -- rather than splicing the parent's
#: ``h`` onto the child's second moment, which is what produced a ``tau``
#: narrower than either bucket's own fit.
MEASURED_MIN_BUCKET_N_ANCHORED = 400
MIN_BUCKET_N_ANCHORED = MEASURED_MIN_BUCKET_N_ANCHORED

#: The p90 relative error in ``tau`` that the floors were chosen to hold. 25%
#: of ``tau`` is roughly 6 percentage points of ``p`` at the half-confident
#: point, which is the precision the ladder can actually use.
TAU_RECOVERY_TOLERANCE = 0.25

#: Largest ``se_log_tau`` at which the sample's own likelihood is allowed to
#: supply ``tau``; above it, an anchor is used if one exists.
#:
#: This replaced a rule that consulted the anchor only when the separation test
#: FAILED, and the replacement was forced by measurement. At ``h/s = 0.5`` and
#: n = 400 the separation test passes by chance a fraction of the time, and the
#: fits it passes with are exactly the ones whose ``h`` came out too big --
#: so conditioning on "the test passed" SELECTS the bad fits, and the p90 error
#: at n = 400 (0.498) came out worse than at n = 200 (0.251). A precision
#: threshold has no such selection effect, because it asks about this fit
#: rather than about whether a hypothesis test happened to clear.
#:
#: ``TAU_RECOVERY_TOLERANCE / 1.6449`` -- the tolerance expressed as an SE.
#:
#: THE QUANTILE HAS TO MATCH THE QUANTITY. :data:`TAU_RECOVERY_TOLERANCE` is a
#: p90 of an **absolute** relative error: :func:`_tau_errors` takes ``abs``
#: and :func:`tau_recovery_error` then takes the 0.90 quantile. The p90 of
#: ``|N(0, s)|`` is ``1.6449 s`` -- the 95th percentile of the signed error --
#: not the 1.2816 that the p90 of the signed error would give. Coded with
#: 1.2816 this gate stood at 0.1951, 28.3% looser than the tolerance it claims
#: to express, and every fit with ``se_log_tau`` in (0.152, 0.195] kept its own
#: over-confident ``tau`` instead of being routed to the anchor or the pool.
#:
#: The normal-theory factor is itself slightly conservative on this estimator:
#: measured over 300 fits at n = 800, ``h/s = 1.39``, the realised p90 of
#: ``|log tau - log tau_true|`` is 1.49 analytic SEs rather than 1.6449, the
#: log-tau error not being quite normal. That errs towards consulting the
#: anchor a little too readily, which is the safe direction.
MAX_SE_LOG_TAU = TAU_RECOVERY_TOLERANCE / 1.6449

#: Default dead-zone half-width in probability space. Reporting only --
#: ``signed_weight = 2p-1`` already makes a coin flip contribute zero, so the
#: aggregation does not depend on this. See :func:`dead_zone_half_width_bps`
#: for the cross-check against the brief's 0.05-0.1 bp expectation, which does
#: NOT reconcile at this delta on a good curve.
DEAD_ZONE_DELTA = 0.05

#: Below this ``h/s`` the two components are not separated and the bucket
#: carries essentially no information. ``tau`` is capped and the fit is
#: flagged rather than reported as a confident wide spread.
MIN_SEPARATION = 0.05

#: Significance for the "is there a spread at all" likelihood-ratio test.
#: A bucket that fails it has ``h`` forced to the no-information floor, so
#: ``p`` stays within a few points of 0.5 -- see :func:`_separation_pvalue`.
SEPARATION_ALPHA = 0.05

#: How many standard errors of positive excess kurtosis before the moment
#: check is called a model failure rather than sampling noise.
#:
#: The sign of the excess kurtosis alone is NOT a usable diagnostic, and the
#: arithmetic says why: at ``h/s = 0.5`` the population excess kurtosis of this
#: mixture is only **-0.080**, while its sampling standard error is
#: ``sqrt(24/n)`` = 0.035 at n = 20,000 and 0.245 at n = 400. A sign test would
#: therefore fire on roughly a coin flip for every overlapping bucket at the
#: sample sizes the tape provides -- a diagnostic that fires at random is worse
#: than none, because it routes good buckets into the robust fallback.
LEPTOKURTOSIS_Z = 3.0

#: How far the fitted ``h`` may sit from an independent spread estimate before
#: :func:`crosscheck_against_tick` calls it a disagreement. A factor of two,
#: because the independent estimate is itself a proxy: ``tick/2`` assumes every
#: consecutive-print move is a full bid-offer traverse, which is an upper
#: bound on ``h`` in a quiet bucket and a lower bound in a trending one.
CROSSCHECK_TOLERANCE = 2.0

# --- fit flags. One vocabulary, so the provenance accounting adds up. -------
FIT_OK = "OK"
FIT_LEPTOKURTIC = "LEPTOKURTIC_MOMENT_CHECK_FAILED"
FIT_ROBUST_FALLBACK = "ROBUST_SCALE_FALLBACK"
FIT_ANCHORED_H = "H_FROM_INDEPENDENT_ESTIMATE"
FIT_POOLED = "POOLED_TO_PARENT"
FIT_UNDERSIZED = "N_BELOW_MINIMUM"
FIT_UNSEPARATED = "SEPARATION_BELOW_FLOOR"
FIT_SCALE_FLOOR = "SCALE_AT_FLOOR"
FIT_CROSSCHECK_DISAGREES = "CROSSCHECK_DISAGREES"
FIT_IMPRECISE = "TAU_SE_ABOVE_TOLERANCE"

#: The bucket label the pooling ladder terminates at.
GLOBAL_BUCKET = "GLOBAL"

#: Columns of :meth:`Calibration.report`, named once so that a calibration with
#: no fits returns an EMPTY frame with them rather than a column-less one.
REPORT_COLUMNS = (
    "bucket", "n", "n_trimmed", "b0_bps", "h_bps", "s_bps", "tau_bps",
    "h_used_bps", "separation", "se_log_tau", "dead_zone_bps",
    "excess_kurtosis", "excess_kurtosis_z", "moment_h", "moment_s",
    "crosscheck_ratio_h", "crosscheck_comparable", "separation_pvalue",
    "fit_flags",
)

#: Column names :class:`Calibration` expects.
DEVIATION_COL = "deviation_bps"
BUCKET_COLS = ("venue_class", "rate_index", "structure",
               "special_tenor_type", "tenor_band")

#: Tenor bands. **The same spine as the KRD ladder** (LEDGER D9: the Basel GIRR
#: vertices extended with the short-end structure the tape actually carries),
#: because two different tenor grids inside one package is a bug generator --
#: a bucket that means one thing to the calibration and another to the risk
#: aggregation is exactly the kind of mismatch that produces a plausible wrong
#: ladder. Bands are ``(lo, hi]``.
TENOR_BAND_EDGES = (0.0, 1 / 12, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 7.0, 10.0,
                    15.0, 20.0, 30.0, float("inf"))
TENOR_BAND_LABELS = ("0-1M", "1M-3M", "3M-6M", "6M-1Y", "1Y-2Y", "2Y-3Y",
                     "3Y-5Y", "5Y-7Y", "7Y-10Y", "10Y-15Y", "15Y-20Y",
                     "20Y-30Y", "30Y+")

#: Order in which bucket dimensions are dropped when a bucket is too thin.
#:
#: Chosen from the data, not from taste: :func:`rank_bucket_dimensions` measures
#: the size-weighted between-level variance of ``log(scale)`` for each
#: dimension, and the least-explanatory one is dropped first. Measured on the
#: legacy deviations (``scratch/prob04_grid.py``)::
#:
#:     dimension            n_levels   between_var   measured drop order
#:     venue_class                 1           n/a   1  (legacy set is D2C-only)
#:     structure                   3       0.00699   2
#:     rate_index                  2       0.01888   3
#:     special_tenor_type          3       0.05407   4
#:     tenor_band                104       0.73361   5
#:
#: **ONE DELIBERATE OVERRIDE, STATED LOUDLY: ``rate_index`` measures third and
#: is used fifth.** Two reasons, and the first is that the measurement is
#: confounded -- almost the whole legacy FED_FUNDS population is FOMC-dated, so
#: ``rate_index`` and ``special_tenor_type`` are nearly the same split there and
#: the variance attributable to the index alone is understated. The second is
#: the cost asymmetry: SOFR and Fed Funds have different minimum ticks (0.25 vs
#: 0.50 bp -- ``stir_flow.config.futures_tick_bps`` already splits them), so
#: pooling across the index hands a Fed Funds print a SOFR half-spread, and a
#: wrong ``tau`` is worse than a thin bucket. The measured order for the other
#: four dimensions is used unchanged.
#:
#: Both the ranking function and this constant are parameters of
#: :meth:`Calibration.fit`, so the order should be re-derived on real Citi
#: deviations and passed in rather than edited here.
DEFAULT_POOLING_ORDER = ("venue_class", "structure", "special_tenor_type",
                         "tenor_band", "rate_index")


class BucketKey(typing.NamedTuple):
    """The full calibration key. Field order matches :data:`BUCKET_COLS`."""

    venue_class: str
    rate_index: str
    structure: str
    special_tenor_type: str
    tenor_band: str

    def label(self) -> str:
        """The canonical bucket string. Same spelling the fits are keyed on."""
        return _label(dict(zip(BUCKET_COLS, self)))


# --------------------------------------------------------------------------
# 1. The fit object and its derived quantities.
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class MomentCheck:
    """The closed-form moment solution, and whether it exists at all.

    With ``m2``, ``m4`` the central moments of the equal-weight mixture::

        m2 = h^2 + s^2
        m4 = h^4 + 6 h^2 s^2 + 3 s^4
        =>  s^2 = m2 - sqrt(m2^2 - (m4 - m2^2)/2),   h^2 = m2 - s^2

    Real **only when the excess kurtosis is negative**: the discriminant is
    ``m2^2 - (m4 - m2^2)/2 >= 0``, i.e. ``m4 <= 3 m2^2``. A separated mixture
    is platykurtic; a leptokurtic bucket is telling us the two-component model
    does not hold there. That is a diagnostic that fires, not a fit that
    quietly degrades.
    """

    m2: float
    m4: float
    excess_kurtosis: float
    real: bool
    s_moment: float | None = None
    h_moment: float | None = None
    #: ``excess_kurtosis / sqrt(24/n)``. The sign alone is not a diagnostic --
    #: see :data:`LEPTOKURTOSIS_Z`.
    excess_kurtosis_z: float | None = None

    @property
    def significantly_leptokurtic(self) -> bool:
        z = self.excess_kurtosis_z
        return (not self.real) and z is not None and z > LEPTOKURTOSIS_Z


@dataclasses.dataclass(frozen=True)
class SpreadCrossCheck:
    """The fitted ``h`` against an estimate that does not come from this module.

    Sub-3y the tape has a tick lattice, so ``stir_flow.tick_size`` can measure a
    consecutive-print tick and ``stir_flow.confidence.sigma_mid`` performs this
    exact variance decomposition by hand. Beyond 3y there is no lattice, which
    is precisely why the fit has to be validated where a second opinion exists.

    ``h_fit`` IS THE MLE, NOT ``MixtureFit.h``, and the distinction is the
    difference between a check and a tautology. When the anchored route runs,
    ``MixtureFit.h`` *is* the tick estimate, so comparing them returns exactly
    1.000 -- which is what the first version did, on 21 of 22 real buckets.
    """

    h_fit: float
    h_independent: float | None
    s_fit: float
    s_independent: float | None
    source: str
    ratio_h: float | None
    ratio_s: float | None
    agrees: bool
    #: False when this bucket's own likelihood could not pin ``h`` down, in
    #: which case ``agrees`` is not a statement about anything. Beyond 3y there
    #: is no tick at all and the cross-check does not run; here the tick exists
    #: but the thing it would be checked against does not.
    comparable: bool = True


@dataclasses.dataclass(frozen=True)
class MixtureFit:
    """One bucket's calibration.

    ``h`` is positive by construction. The likelihood is invariant under
    ``h -> -h`` with the component labels swapped, so the sign is fixed by the
    economics -- printed above mid means the customer paid -- and not by the
    data. If a bucket's deviations genuinely wanted ``h < 0``, that would be a
    sign-convention failure upstream, not a negative half-spread.
    """

    bucket: str
    n: int
    n_trimmed: int
    b0: float
    h: float
    s: float
    loglik: float
    flags: tuple[str, ...] = (FIT_OK,)
    moment: MomentCheck | None = None
    crosscheck: SpreadCrossCheck | None = None
    pooled_from: str | None = None
    se_log_tau: float | None = None
    as_of: datetime.date | None = None
    #: The sample-size floor that applied to THIS fit. Anchored fits get a
    #: smaller one, so the pooling rule has to read it off the fit rather than
    #: off a module constant -- otherwise an anchored bucket that is perfectly
    #: well estimated at n=300 gets pooled away into its parent.
    min_n_required: int = MIN_BUCKET_N
    #: p-value of the ``h = 0`` likelihood-ratio test, on the MLE.
    separation_pvalue: float | None = None
    #: The unanchored MLE, kept even when a fallback replaced it. Without this
    #: the tick cross-check has nothing independent left to compare against --
    #: an anchored fit's ``h`` IS the tick estimate.
    h_mle: float | None = None
    s_mle: float | None = None
    #: Did the sample's own likelihood pin ``tau`` down? Decides whether the
    #: cross-check is a statement or noise.
    mle_reliable: bool = True

    @property
    def tau(self) -> float:
        """``s^2 / (2h)``. NOT the half-spread -- see the module docstring."""
        h = max(float(self.h), _h_floor(self.s))
        return float(self.s) ** 2 / (2.0 * h)

    @property
    def separation(self) -> float:
        """``h/s``. Below :data:`MIN_SEPARATION` the bucket carries no signal."""
        return float(self.h) / max(float(self.s), 1e-300)

    @property
    def ok(self) -> bool:
        return self.flags == (FIT_OK,)


def _h_floor(s: float) -> float:
    """Smallest ``h`` that keeps ``tau`` finite and meaningful.

    ``h -> 0`` is the no-information limit and ``tau -> inf`` is the correct
    answer there, but an infinite ``tau`` propagates as a NaN rather than as
    ``p = 0.5``. Flooring ``h`` at ``MIN_SEPARATION * s`` caps ``tau`` at
    ``s / (2 * MIN_SEPARATION)``, which is wide enough that ``p`` stays inside
    a few percent of 0.5 across the whole plausible range of ``x``.
    """
    return MIN_SEPARATION * max(float(s), 1e-300)


# --------------------------------------------------------------------------
# 2. Likelihood, moments, trimming.
# --------------------------------------------------------------------------

_LOG_SQRT_2PI = 0.5 * math.log(2.0 * math.pi)


def loglik(x, b0: float, h: float, s: float) -> float:
    """Total log-likelihood of the equal-weight symmetric mixture."""
    x = np.asarray(x, dtype=float)
    s = max(float(s), 1e-300)
    z1 = (x - b0 - h) / s
    z2 = (x - b0 + 2.0 * h) / s
    per = np.logaddexp(-0.5 * z1 * z1, -0.5 * z2 * z2)
    return float(np.sum(per) - x.size * (math.log(2.0) + math.log(s) + _LOG_SQRT_2PI))


def mixture_cdf(x, b0: float, h: float, s: float):
    """``0.5 Phi((x-b0-h)/s) + 0.5 Phi((x-b0+h)/s)``, used by :func:`gof_ks`."""
    from scipy.special import ndtr

    x = np.asarray(x, dtype=float)
    s = max(float(s), 1e-300)
    return 0.5 * ndtr((x - b0 - h) / s) + 0.5 * ndtr((x - b0 + h) / s)


def robust_scale(x) -> float:
    """Normal-consistent scale from the MAD. Immune to the 1e4 bp outliers.

    **Used to set the trim radius, and for nothing else.** In particular it is
    NOT an estimate of ``sqrt(m2) = sqrt(h^2 + s^2)``, and using it as one is a
    quiet, severe error: the 1.4826 factor is normal-consistent, and a
    separated mixture is not normal. At ``h/s = 2.5`` the MAD of the mixture is
    almost exactly ``h``, so ``1.4826 * MAD`` overstates ``sqrt(m2)`` by 38%,
    and after subtracting ``h^2`` the residual error in ``s^2`` is a factor of 7 --
    which measured as a p90 ``tau`` error of 7.8 even with a *perfect* anchor
    (``scratch/prob06_anchored.py``, first draft). :func:`trimmed_dispersion`
    is the quantity the decomposition needs.
    """
    x = np.asarray(x, dtype=float)
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    return MAD_TO_SIGMA * mad


def trimmed_dispersion(xt) -> float:
    """``sqrt(m2)`` of an already-trimmed sample: the RMS about its own mean.

    This is what ``h^2 + s^2`` decomposes, and it is what
    ``stir_flow.confidence.sigma_mid`` is handed (``disp_jns`` in
    ``tick_size.compute_dispersion`` is an RMS, not a MAD). Robustness comes
    from the trim having already run, not from the statistic -- which is the
    right division of labour, because a robust *scale* and a second *moment*
    are different quantities and only one of them is the one being decomposed.
    """
    xt = np.asarray(xt, dtype=float)
    c = xt - xt.mean()
    return float(math.sqrt(float((c * c).mean())))


def trim_mask(x, k: float = TRIM_MAD_K):
    """Keep observations within ``k`` robust scales of the median.

    Robust-scale, not quantile -- see :data:`TRIM_MAD_K` for why the obvious
    choice biases ``tau`` down and makes the moment diagnostic pass spuriously.
    """
    x = np.asarray(x, dtype=float)
    if not math.isfinite(k):
        return np.isfinite(x)
    scale = robust_scale(x)
    if scale <= 0:
        # A degenerate bucket (every print on one lattice point). Keeping
        # everything is right: there is nothing to trim, and the fit will
        # flag itself on separation instead.
        return np.isfinite(x)
    return np.isfinite(x) & (np.abs(x - float(np.median(x))) <= k * scale)


def moment_estimates_from_moments(m2: float, m4: float,
                                  n: int | None = None) -> MomentCheck:
    """The closed form, from population or sample central moments."""
    m2 = float(m2)
    m4 = float(m4)
    ex_kurt = (m4 / (m2 * m2) - 3.0) if m2 > 0 else float("nan")
    # Sampling SE of the sample excess kurtosis under normality, sqrt(24/n).
    # Used only to decide whether a positive value MEANS anything; the
    # underlying mixture is not normal, but at the near-boundary separations
    # where this decision matters it is close enough that the alternative --
    # a bare sign test -- is demonstrably worse.
    z = (ex_kurt / math.sqrt(24.0 / n)) if (n and n > 0 and math.isfinite(ex_kurt)) else None
    disc = m2 * m2 - (m4 - m2 * m2) / 2.0
    if not math.isfinite(disc) or disc < 0.0 or m2 <= 0.0:
        return MomentCheck(m2=m2, m4=m4, excess_kurtosis=ex_kurt, real=False,
                           excess_kurtosis_z=z)
    s2 = m2 - math.sqrt(disc)
    h2 = m2 - s2
    if s2 < 0.0 or h2 < 0.0:
        return MomentCheck(m2=m2, m4=m4, excess_kurtosis=ex_kurt, real=False,
                           excess_kurtosis_z=z)
    return MomentCheck(m2=m2, m4=m4, excess_kurtosis=ex_kurt, real=True,
                       s_moment=math.sqrt(s2), h_moment=math.sqrt(h2),
                       excess_kurtosis_z=z)


def moment_estimates(x) -> MomentCheck:
    """Sample version. Central moments about the sample mean."""
    x = np.asarray(x, dtype=float)
    c = x - x.mean()
    return moment_estimates_from_moments(float((c ** 2).mean()),
                                         float((c ** 4).mean()), n=int(x.size))


def _separation_pvalue(x, b0: float, h: float, s: float) -> float:
    """Likelihood-ratio test of ``h = 0``: is there a spread here at all?

    A hard ``h/s`` threshold cannot answer this, because whether a given
    ``h/s`` is real depends on the sample size. The LR statistic does, and it
    needs no extra machinery -- both likelihoods are already computable.

    ``h = 0`` sits on the boundary of the parameter space, so the null
    distribution is the standard 50:50 mixture of a point mass at zero and a
    chi-square with one degree of freedom, giving
    ``p = 0.5 * erfc(sqrt(LR/2))``. Written with :func:`math.erfc` rather than
    ``scipy.stats.chi2.sf`` so the hot path of the fit stays import-free.
    """
    x = np.asarray(x, dtype=float)
    ll1 = loglik(x, b0, h, s)
    ll0 = loglik(x, float(x.mean()), 0.0, float(x.std()) or 1e-12)
    lr = 2.0 * (ll1 - ll0)
    if not math.isfinite(lr) or lr <= 0.0:
        return 1.0
    return 0.5 * math.erfc(math.sqrt(lr / 2.0))


# --------------------------------------------------------------------------
# 3. The fit.
# --------------------------------------------------------------------------

def fit_mixture(
    x,
    *,
    bucket: str,
    trim_k: float = TRIM_MAD_K,
    min_n: int = MIN_BUCKET_N,
    tick_stats=None,
    max_iter: int = 500,
    tol: float = 1e-11,
    as_of: datetime.date | None = None,
) -> MixtureFit:
    """Fit ``(b0, h, s)`` by maximum likelihood, **with the weight fixed at 0.5**.

    THE WEIGHT IS NOT FITTED, AND THAT IS THE POINT
    -----------------------------------------------

    The free-weight mixture ``w N(b0+h, s^2) + (1-w) N(b0-h, s^2)`` has mean
    ``b0 + (2w-1)h``, so ``w`` and ``b0`` enter the location through one
    combination and are not separately identifiable at the separations this
    data has (``h/s`` of order 1, not 5). An optimiser handed both will happily
    split the sample's location shift between them, and the split it chooses is
    arbitrary.

    That is not a precision problem, it is a **sign** problem. Suppose the mid
    is biased 0.5 bp low, as the legacy Barchart curve was biased 0.5 bp high
    (LEDGER F-20). With ``w`` free, the fit can explain the whole shift as
    ``w = 0.78`` -- "78% of customers paid fixed" -- leaving ``b0 = 0``. Every
    subsequent ``p`` is then computed against an unbiased mid that is not
    unbiased, and marginal calls invert rather than degrade. Fixing ``w = 0.5``
    forces the shift into ``b0``, where it belongs and where it is visible.

    The price is real and is measured, not waved away: genuine flow imbalance
    is booked as curve bias, so the model under-calls the busy side. See
    ``test_calibration_degrades_measurably_under_asymmetric_flow``, which
    quantifies it at 65/35 flow. Under-calling is the safe direction of failure
    and mis-orientation is not, so the trade is taken deliberately.

    ESTIMATION
    ----------

    EM, which for this model has a closed-form M step. With responsibilities
    ``w_i = sigma((x_i - b0)/tau)`` and ``u_i = 2 w_i - 1``::

        h  = (mean(u x) - mean(x) mean(u)) / (1 - mean(u)^2)
        b0 = mean(x) - h mean(u)
        s^2 = mean((x-b0)^2) - h^2

    EM is preferred to a general optimiser because it is monotone in the
    likelihood, so a bad start degrades the answer rather than diverging, and
    because the M step above costs three passes over the data. Several starts
    are tried and the highest likelihood wins; the moment solution supplies one
    of them whenever it is real.

    ``tick_stats`` is the fallback for a bucket that fails the moment check --
    see :data:`FIT_ROBUST_FALLBACK`. It is the only anchor there is: a parent
    bucket's ``h`` used to be a second one and was removed, because a parent's
    sample contains the child's rows and the spliced ``tau`` came out up to 49x
    too narrow (:data:`MIN_BUCKET_N_ANCHORED`). Pooling, not anchoring, is how
    a bucket borrows from its parent.
    """
    x = np.asarray(x, dtype=float).ravel()
    x = x[np.isfinite(x)]
    if x.size == 0:
        raise ValueError(f"bucket {bucket!r}: no finite deviations to fit")

    keep = trim_mask(x, trim_k)
    xt = x[keep]
    if xt.size == 0:
        raise ValueError(f"bucket {bucket!r}: trim removed every observation")

    # An h from outside this sample -- the tick lattice sub-3y -- changes what
    # has to be estimated, and therefore how much data it takes. See
    # MIN_BUCKET_N's docstring for why that matters so much, and for the
    # measurement that removed the parent bucket as a second source of one.
    anchor_h = _independent_half_spread(tick_stats) if tick_stats is not None else None
    min_n_given = min_n
    flags: list[str] = []

    # A bucket whose trimmed prints are all on ONE value has no dispersion to
    # decompose, and the EM divides by s^2. Measured on the legacy frame: 783
    # of 1,689 full-key buckets, almost all of them singletons, every one
    # returning a NaN tau that then propagates silently -- `for_key` would pool
    # past them on size, but `report()` and `tau_stability` would not.
    #
    # The safe direction here is a WIDE tau, not a narrow one. Flooring s at
    # something tiny would make p a step function at b0, i.e. maximal
    # confidence from a bucket that contains no information at all; taking the
    # scale from the untrimmed sample and pinning h at the separation floor
    # keeps p within a few points of 0.5, which is what "no information" has
    # to mean.
    if not trimmed_dispersion(xt) > 0:
        s_deg = float(np.std(x)) if x.size > 1 else 0.0
        s_deg = s_deg if s_deg > 0 else 1.0        # nominal 1 bp, flagged
        return MixtureFit(
            bucket=bucket, n=int(x.size), n_trimmed=int(xt.size),
            b0=float(np.median(xt)), h=MIN_SEPARATION * s_deg, s=s_deg,
            loglik=float("nan"),
            flags=(FIT_UNDERSIZED, FIT_UNSEPARATED, FIT_SCALE_FLOOR),
            moment=None, as_of=as_of, min_n_required=int(min_n),
            mle_reliable=False)

    mc = moment_estimates(xt)
    if mc.significantly_leptokurtic:
        flags.append(FIT_LEPTOKURTIC)

    scale = robust_scale(xt)
    if scale <= 0:
        scale = float(np.std(xt)) or 1e-9
    med = float(np.median(xt))

    # Starts: the moment solution when it exists, plus a fan of h/scale splits
    # so a single bad basin cannot decide the answer.
    starts: list[tuple[float, float, float]] = []
    if mc.real and mc.h_moment and mc.s_moment:
        starts.append((med, mc.h_moment, mc.s_moment))
    for frac in (0.3, 0.55, 0.8):
        h0 = frac * scale
        s0 = math.sqrt(max(scale * scale - h0 * h0, (0.1 * scale) ** 2))
        starts.append((med, h0, s0))

    best: tuple[float, float, float, float] | None = None
    for b0_0, h_0, s_0 in starts:
        cand = _em(xt, b0_0, max(h_0, 1e-12), max(s_0, 1e-12), max_iter, tol)
        if best is None or cand[3] > best[3]:
            best = cand
    assert best is not None
    b0, h, s, ll = best

    s_floor = 1e-6 * max(scale, 1e-12)
    if s <= s_floor:
        s = s_floor
        flags.append(FIT_SCALE_FLOOR)

    # Is there a spread here at all? Asked of the MLE, and asked BEFORE any
    # fallback can overwrite it: a fallback ``(b0, h, s)`` is not a
    # maximum-likelihood triple, so a likelihood ratio against the ``h = 0``
    # MLE is not a test of anything -- it comes out negative and every fallback
    # bucket reports "no separation". That is exactly what the first draft did,
    # and it turned a tick-anchored ``h`` of 0.20 bp into 0.012 bp on a bucket
    # that was in fact separated 2.5:1.
    sep_p = _separation_pvalue(xt, b0, h, s)
    unseparated = sep_p > SEPARATION_ALPHA or h < MIN_SEPARATION * s
    if unseparated:
        flags.append(FIT_UNSEPARATED)

    # Does this sample pin tau down on its own? Asked of the MLE, before any
    # fallback replaces it. See MAX_SE_LOG_TAU: routing on "the separation test
    # failed" instead selects the bad fits and measured WORSE at larger n.
    se_mle = None if unseparated else _se_log_tau(xt, b0, h, s)
    imprecise = se_mle is None or se_mle > MAX_SE_LOG_TAU
    h_mle, s_mle = float(h), float(s)

    se = se_mle
    if FIT_LEPTOKURTIC in flags or unseparated or imprecise:
        if anchor_h is not None:
            # The rescue. With h asserted from outside, only the total
            # dispersion has to come from this sample, and one second moment
            # needs a few hundred observations rather than the many thousands
            # the three-parameter likelihood needs at h/s ~ 1.
            b0, h, s, extra = _anchored_decomposition(xt, anchor_h, external=True)
        elif FIT_LEPTOKURTIC in flags:
            # Same decomposition, but h is this sample's own MLE -- so it is
            # NOT an independent estimate and must not be labelled as one.
            b0, h, s, extra = _anchored_decomposition(xt, h, external=False)
        elif unseparated:
            # No anchor and no separation: the honest answer is "no
            # information", and the honest way to say that in this model is a
            # WIDE tau. Leaving a small h where the EM dropped it would produce
            # a NARROW tau and therefore confident calls out of noise -- the
            # inversion this whole branch exists to prevent.
            h, extra = MIN_SEPARATION * s, []
        else:
            # Imprecise, but nothing better is available. Keep the MLE and say
            # so; the pooling floor is what actually keeps it out of the ladder.
            extra = [FIT_IMPRECISE]
        flags.extend(extra)
        ll = loglik(xt, b0, h, s)
        # A standard error for a parameter that was forced or imported rather
        # than fitted would be a fabrication, and tau_stability weights by it.
        if FIT_IMPRECISE not in extra:
            se = None

    anchored = FIT_ANCHORED_H in flags
    min_n = (MIN_BUCKET_N_ANCHORED if (anchored and min_n_given == MIN_BUCKET_N)
             else min_n_given)
    if xt.size < min_n:
        flags.insert(0, FIT_UNDERSIZED)

    xcheck = None
    if tick_stats is not None:
        xcheck = crosscheck_against_tick(
            MixtureFit(bucket, int(x.size), int(xt.size), b0, h, s, ll,
                       h_mle=h_mle, s_mle=s_mle, mle_reliable=not imprecise),
            tick_stats)
        if xcheck.comparable and not xcheck.agrees:
            flags.append(FIT_CROSSCHECK_DISAGREES)

    return MixtureFit(
        bucket=bucket,
        n=int(x.size),
        n_trimmed=int(xt.size),
        b0=float(b0),
        h=float(h),
        s=float(s),
        loglik=float(ll),
        flags=tuple(flags) if flags else (FIT_OK,),
        moment=mc,
        crosscheck=xcheck,
        se_log_tau=se,
        as_of=as_of,
        min_n_required=int(min_n),
        separation_pvalue=float(sep_p),
        h_mle=h_mle,
        s_mle=s_mle,
        mle_reliable=not imprecise,
    )


def _em(x, b0: float, h: float, s: float, max_iter: int, tol: float):
    """Closed-form EM. Returns ``(b0, h, s, loglik)``; ``h >= 0`` always."""
    n = x.size
    ll_prev = -np.inf
    ll = loglik(x, b0, h, s)
    for _ in range(max_iter):
        # E step. u = 2w - 1 = tanh(h (x - b0) / s^2), written as tanh because
        # it is the numerically stable spelling of the sigmoid difference.
        u = np.tanh(h * (x - b0) / (s * s))
        ubar = float(u.mean())
        xbar = float(x.mean())
        denom = 1.0 - ubar * ubar
        if denom < 1e-12:
            # Responsibilities collapsed onto one component: b0 and h are no
            # longer separable. Stop rather than divide by ~0 and report a
            # confident spread that is really a location shift.
            break
        h_new = (float((u * x).mean()) - xbar * ubar) / denom
        b0_new = xbar - h_new * ubar
        if h_new < 0.0:
            # Label swap. The likelihood is invariant; h > 0 is the convention.
            h_new = -h_new
            b0_new = xbar - (-h_new) * ubar
        d = x - b0_new
        s2_new = float((d * d).mean()) - h_new * h_new
        if not math.isfinite(s2_new) or s2_new <= 0.0:
            # Over-separated step: back off to the total dispersion, which is
            # an upper bound on s and always admissible.
            s2_new = float((d * d).mean()) * 0.25
        b0, h, s = b0_new, h_new, math.sqrt(s2_new)
        ll_prev, ll = ll, loglik(x, b0, h, s)
        if abs(ll - ll_prev) <= tol * max(1.0, abs(ll_prev)):
            break
    _ = n
    return b0, abs(h), s, ll


def _anchored_decomposition(xt, h_anchor: float, *, external: bool):
    """``h`` asserted, ``s`` by subtraction from a robust total dispersion.

    Deliberately the **frozen predecessor's own arithmetic**
    (``confidence.sigma_mid``: ``sqrt(disp_jns^2 - half^2)``), with the
    dispersion made robust. Using the same decomposition as the module this one
    is cross-checked against means the fallback and the check cannot drift
    apart, and it is what makes the sub-3y agreement in
    :func:`crosscheck_against_tick` a meaningful statement rather than a
    comparison of two unrelated numbers.

    Two things this fixes that the unanchored fit cannot. First, a leptokurtic
    bucket's MLE ``s`` is inflated by whatever contaminated it, and a robust
    scale is not. Second -- the bigger one -- at ``h/s`` around 1 the mixture
    is not identifiable from its own moments at tape-realistic sample sizes at
    all (see :data:`MIN_BUCKET_N`), so an ``h`` from outside is not a
    convenience, it is the only route to a ``tau`` in those buckets.

    ``external`` MUST be False when ``h_anchor`` is the sample's own MLE, which
    is what a leptokurtic bucket with no tick gets. Emitting ``FIT_ANCHORED_H``
    there would claim an independent estimate that does not exist, and -- worse
    than the cosmetic lie -- it would grant the bucket
    :data:`MIN_BUCKET_N_ANCHORED`, a floor measured only for an external and
    approximately correct ``h``. The bucket would then refuse to pool on the
    strength of the one number in it that cannot be trusted. It is
    keyword-only and has no default for the same reason: a caller that forgets
    to say gets a TypeError rather than an independence claim.

    ``b0`` is the trimmed sample's median, and it is the estimate every real
    bucket ends up with -- every bucket in ``scratch/prob05_real.py`` takes
    this path. It is a bias term, so an error in it does not widen ``p``, it
    moves the point where ``p`` crosses 0.5, which is a sign change for every
    deviation between the true and assumed bias.
    """
    extra = [FIT_ROBUST_FALLBACK] + ([FIT_ANCHORED_H] if external else [])
    h_fb = float(h_anchor)
    scale = trimmed_dispersion(xt)
    if scale <= 0:
        scale = float(np.std(xt)) or 1e-9
    var = scale * scale - h_fb * h_fb
    if var <= 0:
        # sigma_mid's own branch: when the dispersion does not exceed the half
        # spread the decomposition has no room left, and it falls back to half
        # a tick. Same idea, expressed against h because that is what is here.
        s_fb = 0.5 * h_fb
        extra.append(FIT_SCALE_FLOOR)
    else:
        s_fb = math.sqrt(var)
    return float(np.median(xt)), h_fb, s_fb, extra


def _se_log_tau(x, b0, h, s) -> float | None:
    """Standard error of ``log tau`` from the observed information.

    Taken in ``(b0, log h, log s)`` so that ``log tau = 2 log s - log 2 - log h``
    has the constant gradient ``(0, -1, 2)`` and the delta method needs no
    Jacobian of its own. Numeric central differences: the analytic Hessian of a
    mixture likelihood is three pages and one sign error in it would be exactly
    the kind of invisible defect this module is built to avoid, whereas a
    finite difference is checkable against the empirical spread of repeated
    fits -- which ``test_se_log_tau_matches_the_empirical_spread`` does.
    """
    if h <= 0 or s <= 0:
        return None
    eta = np.array([b0, math.log(h), math.log(s)], dtype=float)
    steps = np.array([1e-3 * max(s, 1e-12), 1e-3, 1e-3])

    def f(e):
        return loglik(x, e[0], math.exp(e[1]), math.exp(e[2]))

    hess = np.zeros((3, 3))
    f0 = f(eta)
    for i in range(3):
        for j in range(i, 3):
            ei = np.zeros(3); ei[i] = steps[i]
            ej = np.zeros(3); ej[j] = steps[j]
            if i == j:
                val = (f(eta + ei) - 2 * f0 + f(eta - ei)) / (steps[i] ** 2)
            else:
                val = (f(eta + ei + ej) - f(eta + ei - ej)
                       - f(eta - ei + ej) + f(eta - ei - ej)) / (4 * steps[i] * steps[j])
            hess[i, j] = hess[j, i] = val
    try:
        cov = np.linalg.inv(-hess)
    except np.linalg.LinAlgError:
        return None
    g = np.array([0.0, -1.0, 2.0])
    var = float(g @ cov @ g)
    if not math.isfinite(var) or var <= 0:
        return None
    return math.sqrt(var)


# --------------------------------------------------------------------------
# 4. Probability, dead zone, and the per-trade call.
# --------------------------------------------------------------------------

def p_customer_paid(deviation_bps, fit: MixtureFit):
    """``sigma((x - b0) / tau)`` = p(customer paid fixed) = p(dealer received).

    One convention, pinned in :mod:`.conventions`: ``p > 0.5`` pushes the
    ladder positive. Scalar in, scalar out; array in, array out.
    """
    x = np.asarray(deviation_bps, dtype=float)
    z = (x - fit.b0) / fit.tau
    out = _sigmoid(z)
    return float(out) if np.ndim(deviation_bps) == 0 else out


def _sigmoid(z):
    """Stable in both tails, and shape-preserving for 0-d input.

    Written against ``exp(-|z|)`` so neither tail ever exponentiates a large
    positive number. The branchless ``np.where`` spelling is deliberate: the
    masked-assignment version silently mis-handles a 0-d array, which is what a
    single deviation arrives as.
    """
    z = np.asarray(z, dtype=float)
    e = np.exp(-np.abs(z))
    return np.where(z >= 0, 1.0 / (1.0 + e), e / (1.0 + e))


def dead_zone_half_width_bps(tau: float, delta: float = DEAD_ZONE_DELTA) -> float:
    """Deviation from ``b0`` at which ``|p - 0.5|`` first reaches ``delta``.

    Inverting the logistic: ``|x - b0| = tau * log((0.5+delta)/(0.5-delta))``.

    THE CROSS-CHECK AGAINST THE BRIEF, WHICH DOES NOT RECONCILE
    -----------------------------------------------------------

    The brief expects a dead zone of 0.05-0.1 bp. On Citi-quality mids that is
    an enormous ``delta``, not a small one. F-15 measured the printed-minus-mid
    IQR at 0.266 bp with 40.5% of prints inside +-0.1 bp, which is a plausible
    ``h ~ 0.15``, ``s ~ 0.13``, hence ``tau ~ 0.056`` bp. At ``delta = 0.05``
    the dead zone is then **0.0113 bp** on each side -- four to nine times
    narrower than the brief's range. Going the other way: 0.05 bp needs
    ``delta = 0.208`` (abstain on everything between ``p = 0.29`` and
    ``p = 0.71``) and 0.1 bp needs ``delta = 0.355`` (``p`` between 0.145 and
    0.855). Those are not dead zones, they are most of the distribution.

    Both readings cannot be right, and the disagreement is informative rather
    than a calibration to be nudged: the brief's 0.05-0.1 bp is a sensible dead
    zone **for a curve whose mid error is of that order**, which the Barchart
    curve's is (median ``|s2m|`` 0.71 bp) and the Citi curve's is not. The
    number to report per bucket is :func:`Calibration.report`'s
    ``dead_zone_bps``; the number to compare it against is that bucket's own
    ``s``, not a constant.
    """
    if delta <= 0.0 or delta >= 0.5:
        raise ValueError(f"delta must lie in (0, 0.5), got {delta!r}")
    return float(tau) * math.log((0.5 + delta) / (0.5 - delta))


def delta_for_dead_zone_bps(tau: float, half_width_bps: float) -> float:
    """Inverse of :func:`dead_zone_half_width_bps`. The other half of the check."""
    if tau <= 0:
        raise ValueError(f"tau must be positive, got {tau!r}")
    e = math.exp(float(half_width_bps) / float(tau))
    return 0.5 * (e - 1.0) / (e + 1.0)


@dataclasses.dataclass(frozen=True)
class ProbabilityCall:
    """What this module contributes to a :class:`.types.DirectionCall`.

    Deliberately not a ``DirectionCall`` itself: that carries ``unit_key`` and
    ``rule``, which belong to the caller. This is the probability layer's
    output and nothing else.
    """

    p: float
    signed_weight: float
    deviation_bps: float
    tau_bps: float
    mid_bias_bps: float
    tau_bucket: str
    in_dead_zone: bool
    dead_zone_half_width_bps: float
    flags: tuple[str, ...]


def direction_probability(deviation_bps: float, fit: MixtureFit,
                          delta: float = DEAD_ZONE_DELTA) -> ProbabilityCall:
    """One deviation -> one probability, with everything a consumer needs to gate.

    The dead-zone flag is **reporting only**. ``signed_weight = 2p - 1`` is
    already zero at ``p = 0.5``, so a marginal call contributes nothing to the
    ladder whether or not it is flagged (DESIGN 1.3). The flag exists for
    health monitoring and for consumers who want a hard filter; nothing in the
    aggregation depends on it, and a change to ``delta`` must not move the
    ladder. That invariant is tested.
    """
    p = p_customer_paid(float(deviation_bps), fit)
    half = dead_zone_half_width_bps(fit.tau, delta)
    return ProbabilityCall(
        p=p,
        signed_weight=conv.signed_weight(p),
        deviation_bps=float(deviation_bps),
        tau_bps=fit.tau,
        mid_bias_bps=fit.b0,
        tau_bucket=fit.bucket,
        in_dead_zone=abs(p - 0.5) < delta,
        dead_zone_half_width_bps=half,
        flags=fit.flags,
    )


# --------------------------------------------------------------------------
# 5. Check two -- against the frozen predecessor's decomposition.
# --------------------------------------------------------------------------

def _independent_half_spread(stats) -> float | None:
    """``tick / 2``, with ``stir_flow.confidence._tick``'s own fallback rule.

    Reproduced in two lines rather than imported, because importing a private
    name out of a frozen module makes the freeze meaningless -- the tie-out
    needs ``stir_flow`` runnable unchanged, and that includes not depending on
    its internals.
    """
    t = getattr(stats, "median_tick_bps", None)
    if t is None or not (t > 0):
        t = getattr(stats, "futures_tick_bps", None)
    if t is None or not (t > 0):
        return None
    return float(t) / 2.0


def tick_stats_implied_by(fit: MixtureFit, futures_tick_bps: float = 0.25,
                          include_bias_in_dispersion: bool = False):
    """The ``TickStats`` this fit implies, for round-tripping through `sigma_mid`.

    ``sigma_mid`` computes ``sqrt(disp_jns^2 - (tick/2)^2)``. Feeding it
    ``tick = 2h`` and ``disp_jns = sqrt(h^2 + s^2)`` must return exactly ``s``
    -- the two modules are then provably decomposing the same quantity, and
    that identity is tested at float tolerance.

    ``include_bias_in_dispersion`` reproduces what ``compute_dispersion``
    actually feeds it: ``disp_jns`` there is the DV01-weighted RMS of ``s2m``
    about **zero**, not about the mean, so a biased curve inflates it by
    ``b0^2`` and ``sigma_mid`` books the entire bias as mid-measurement error.
    With the measured -0.48 bp Barchart bias that roughly doubles ``s`` and so
    **quadruples** ``tau``. That is not a criticism of the frozen code, which
    had no ``b0`` to subtract; it is the reason the new fit estimates one.
    """
    from SDRUtils.stir_flow.confidence import TickStats

    m2 = fit.h ** 2 + fit.s ** 2
    if include_bias_in_dispersion:
        m2 += fit.b0 ** 2
    return TickStats(median_tick_bps=2.0 * fit.h,
                     disp_jns=math.sqrt(m2),
                     futures_tick_bps=float(futures_tick_bps))


def crosscheck_against_tick(fit: MixtureFit, stats) -> SpreadCrossCheck:
    """Fitted ``h`` and ``s`` against the tick-lattice estimate of each.

    Sub-3y both exist and must roughly agree. Beyond 3y there is no lattice and
    ``stats`` will be ``None`` at the call site -- which is exactly why the fit
    has to be validated here, where a second opinion is available, before it is
    trusted where none is.

    The tolerance is a factor of two and that is not slack for its own sake:
    ``tick/2`` assumes every consecutive-print move traverses the full
    bid-offer, an over-estimate of ``h`` in a bucket where prints cluster on
    one side and an under-estimate in a trending one.

    **The comparison is against the MLE, not against ``fit.h``.** An anchored
    fit's ``h`` came FROM this tick, so comparing them is comparing a number to
    itself. The first version did exactly that and reported perfect agreement
    -- ``ratio_h`` of 1.000 to three decimals -- on 21 of 22 real buckets,
    which is what a vacuous check looks like from the outside.
    """
    from SDRUtils.stir_flow.confidence import sigma_mid

    h_ind = _independent_half_spread(stats)
    s_ind = None
    if getattr(stats, "disp_jns", None) is not None:
        s_ind = float(sigma_mid(stats))

    h_own = fit.h if fit.h_mle is None else fit.h_mle
    s_own = fit.s if fit.s_mle is None else fit.s_mle
    ratio_h = (h_own / h_ind) if h_ind else None
    ratio_s = (s_own / s_ind) if s_ind else None
    agrees = True
    for r in (ratio_h, ratio_s):
        if r is not None and not (1.0 / CROSSCHECK_TOLERANCE <= r <= CROSSCHECK_TOLERANCE):
            agrees = False
    return SpreadCrossCheck(h_fit=h_own, h_independent=h_ind, s_fit=s_own,
                            s_independent=s_ind, source="stir_flow.tick_size",
                            ratio_h=ratio_h, ratio_s=ratio_s, agrees=agrees,
                            comparable=bool(fit.mle_reliable))


# --------------------------------------------------------------------------
# 6. Buckets, pooling, calibration.
# --------------------------------------------------------------------------

def tenor_band(years) -> str:
    """Band label for a tenor in years. Bands are ``(lo, hi]``.

    A tenor that is zero, negative or infinite is not a tenor, and it gets
    ``UNKNOWN`` rather than the nearest band. The first band is ``(0, 1M]``, so
    zero is not a member of it -- and it is the tightest bucket on the grid,
    hence the most confident ``tau``, which is the worst possible place to put
    a term that is broken or mis-signed. UNKNOWN has no fit, so such a unit
    pools instead of being called.
    """
    if years is None or (isinstance(years, float) and years != years):
        return "UNKNOWN"
    y = float(years)
    if not math.isfinite(y) or y <= 0.0:
        return "UNKNOWN"
    for i in range(len(TENOR_BAND_LABELS)):
        if TENOR_BAND_EDGES[i] < y <= TENOR_BAND_EDGES[i + 1]:
            return TENOR_BAND_LABELS[i]
    return TENOR_BAND_LABELS[-1]


def frame(deviation_bps, *, venue: str, rate_index: str, structure: str,
          tenor_band: str, special_tenor_type: str = "STANDARD",
          as_of_date=None) -> pd.DataFrame:
    """A one-bucket calibration frame. Convenience for tests and probes."""
    x = np.asarray(deviation_bps, dtype=float).ravel()
    df = pd.DataFrame({
        DEVIATION_COL: x,
        "venue_class": venue,
        "rate_index": rate_index,
        "structure": structure,
        "special_tenor_type": special_tenor_type,
        "tenor_band": tenor_band,
    })
    if as_of_date is not None:
        df["as_of_date"] = as_of_date
    return df


def pooling_ladder(key: BucketKey,
                   order: tuple[str, ...] = DEFAULT_POOLING_ORDER) -> list[str]:
    """Bucket labels from most specific to :data:`GLOBAL_BUCKET`.

    Each step drops one dimension, in the order the data says matters least
    (:func:`rank_bucket_dimensions`). Always terminates at the global fit, so
    every unit gets a ``tau`` from somewhere and the source is always named.
    """
    dims = dict(zip(BUCKET_COLS, key))
    labels = [_label(dims)]
    for dropped in order:
        dims = {k: v for k, v in dims.items() if k != dropped}
        labels.append(_label(dims) if dims else GLOBAL_BUCKET)
    if labels[-1] != GLOBAL_BUCKET:
        labels.append(GLOBAL_BUCKET)
    return labels


def _label(dims: dict) -> str:
    return "|".join(f"{k}={dims[k]}" for k in BUCKET_COLS if k in dims)


def rank_bucket_dimensions(df: pd.DataFrame,
                           value_col: str = DEVIATION_COL) -> pd.DataFrame:
    """How much of the dispersion in robust scale each dimension explains.

    The pooling order is a data question, not a taste question: the dimension
    to drop first is the one whose levels have the most similar spread, because
    pooling across it costs least. Measured as the between-level variance of
    ``log(robust_scale)`` weighted by level size, which is scale-free and so
    comparable across dimensions with different level counts.

    Exposed rather than baked in so that the order can be re-derived on real
    Citi deviations. :data:`DEFAULT_POOLING_ORDER` was set from a run on the
    legacy Barchart deviations, which are a shape exercise only.
    """
    rows = []
    for dim in BUCKET_COLS:
        if dim not in df.columns:
            continue
        scales, weights = [], []
        for _, g in df.groupby(dim, dropna=False):
            if len(g) < 30:
                continue
            sc = robust_scale(g[value_col].to_numpy(float))
            if sc > 0:
                scales.append(math.log(sc))
                weights.append(len(g))
        if len(scales) < 2:
            rows.append(dict(dimension=dim, n_levels=len(scales),
                             between_var=float("nan")))
            continue
        w = np.asarray(weights, float)
        v = np.asarray(scales, float)
        mu = float((w * v).sum() / w.sum())
        rows.append(dict(dimension=dim, n_levels=len(scales),
                         between_var=float((w * (v - mu) ** 2).sum() / w.sum())))
    out = pd.DataFrame(rows).sort_values("between_var", na_position="first")
    out["drop_order"] = range(1, len(out) + 1)
    return out.reset_index(drop=True)


class Calibration:
    """Per-bucket fits plus the pooling rule that fills the thin ones.

    Built once per calibration window and then consulted per trade. Nothing in
    here reads the row being classified, so a calibration is safe to reuse and
    safe to cache; :func:`rolling_calibrations` is what keeps it out of the
    future.
    """

    def __init__(self, fits: dict[str, MixtureFit],
                 order: tuple[str, ...] = DEFAULT_POOLING_ORDER,
                 min_n: int = MIN_BUCKET_N):
        self.fits = fits
        self.order = order
        self.min_n = min_n

    # -- construction ------------------------------------------------------
    @classmethod
    def fit(cls, df: pd.DataFrame, *, order: tuple[str, ...] = DEFAULT_POOLING_ORDER,
            min_n: int = MIN_BUCKET_N, trim_k: float = TRIM_MAD_K,
            tick_stats_by_bucket: dict | None = None,
            as_of: datetime.date | None = None) -> "Calibration":
        """Fit every bucket at every level of the ladder.

        Coarse levels are fitted too, not just the leaves -- a parent that only
        materialises when a child turns out thin would be fitted on a different
        sample depending on which children happened to be thin that window,
        which is a silent dependence of one bucket's ``tau`` on another
        bucket's activity. They are also what :meth:`for_key` pools into, and
        pooling is the ONLY way a bucket borrows from a coarser one: see
        :data:`MIN_BUCKET_N_ANCHORED` for the measurement that removed the
        alternative.
        """
        missing = [c for c in (DEVIATION_COL,) + BUCKET_COLS if c not in df.columns]
        if missing:
            raise ValueError(f"calibration frame is missing {missing}")

        fits: dict[str, MixtureFit] = {}
        levels: list[list[str]] = [list(BUCKET_COLS)]
        for dropped in order:
            nxt = [c for c in levels[-1] if c != dropped]
            levels.append(nxt)

        # Coarsest first. Nothing depends on the order any more -- each level
        # is fitted on its own rows and the global is just another level -- but
        # it is kept so that a `fits` dict is never half-built when a coarse
        # fit raises, and so the global, the one bucket `for_key` must always
        # find, exists before anything can look for it.
        fits[GLOBAL_BUCKET] = fit_mixture(
            df[DEVIATION_COL].to_numpy(float), bucket=GLOBAL_BUCKET,
            trim_k=trim_k, min_n=min_n, as_of=as_of)

        for cols in reversed(levels):
            if not cols:
                continue
            for keyvals, g in df.groupby(list(cols), dropna=False):
                if not isinstance(keyvals, tuple):
                    keyvals = (keyvals,)
                dims = dict(zip(cols, keyvals))
                label = _label(dims)
                if label in fits:
                    continue
                ts = (tick_stats_by_bucket or {}).get(label)
                fits[label] = fit_mixture(
                    g[DEVIATION_COL].to_numpy(float), bucket=label,
                    trim_k=trim_k, min_n=min_n, tick_stats=ts, as_of=as_of)

        return cls(fits, order=order, min_n=min_n)

    # -- lookup ------------------------------------------------------------
    def for_key(self, key: BucketKey) -> MixtureFit:
        """The fit that governs this key, pooling up until one is big enough.

        The returned object always names where its numbers came from: a pooled
        fit carries the requested bucket as its label and the donor as
        ``pooled_from``, so provenance records the bucket that was *asked for*
        and the bucket that *answered*.
        """
        want = _label(dict(zip(BUCKET_COLS, key)))
        for label in pooling_ladder(key, self.order):
            fit = self.fits.get(label)
            if fit is None:
                continue
            # The floor is read off the FIT, not off the module constant: an
            # anchored fit is well estimated at a few hundred observations and
            # would otherwise be pooled away into a parent that describes it
            # worse. See MIN_BUCKET_N_ANCHORED.
            if fit.n_trimmed < fit.min_n_required and label != GLOBAL_BUCKET:
                continue
            if label == want:
                return fit
            return dataclasses.replace(
                fit, bucket=want, pooled_from=label,
                flags=tuple(dict.fromkeys(fit.flags + (FIT_POOLED,))))
        raise KeyError(f"no fit reachable for {key}; was Calibration.fit given data?")

    def call(self, deviation_bps: float, key: BucketKey,
             delta: float = DEAD_ZONE_DELTA) -> ProbabilityCall:
        return direction_probability(deviation_bps, self.for_key(key), delta)

    # -- reporting ---------------------------------------------------------
    def report(self, delta: float = DEAD_ZONE_DELTA) -> pd.DataFrame:
        """One row per fitted bucket. This is the artefact a reviewer reads.

        ``h_used_bps`` is there because ``separation`` and ``tau_bps`` are not
        computed from the same ``h``: ``separation`` is the raw ``h/s`` and
        ``tau`` floors ``h`` at ``MIN_SEPARATION * s`` (:func:`_h_floor`), so on
        a floored bucket the report showed ``separation = 0.014`` beside a
        ``tau`` that implies 0.05 and a reader could not get from one to the
        other. Both are wanted -- the raw ratio is the diagnostic, the floored
        one is what ``p`` was computed with -- so both are printed.

        An empty calibration returns an empty frame WITH these columns. A
        column-less ``DataFrame([])`` raises in whatever touches it next,
        which is a long way from the calibration that produced nothing.
        """
        rows = []
        for label, f in sorted(self.fits.items()):
            rows.append(dict(
                bucket=label, n=f.n, n_trimmed=f.n_trimmed,
                b0_bps=f.b0, h_bps=f.h, s_bps=f.s, tau_bps=f.tau,
                h_used_bps=max(float(f.h), _h_floor(f.s)),
                separation=f.separation, se_log_tau=f.se_log_tau,
                dead_zone_bps=dead_zone_half_width_bps(f.tau, delta),
                excess_kurtosis=(f.moment.excess_kurtosis if f.moment else None),
                excess_kurtosis_z=(f.moment.excess_kurtosis_z if f.moment else None),
                moment_h=(f.moment.h_moment if f.moment else None),
                moment_s=(f.moment.s_moment if f.moment else None),
                crosscheck_ratio_h=(f.crosscheck.ratio_h if f.crosscheck else None),
                crosscheck_comparable=(f.crosscheck.comparable if f.crosscheck
                                       else None),
                separation_pvalue=f.separation_pvalue,
                # NOT ``flags``: ``DataFrame.flags`` is a pandas property, so a
                # column of that name is unreachable as an attribute and
                # ``rep.flags`` silently returns pandas' own Flags object.
                fit_flags=",".join(f.flags),
            ))
        return pd.DataFrame(rows, columns=list(REPORT_COLUMNS))


# --------------------------------------------------------------------------
# 7. Time variation.
# --------------------------------------------------------------------------

def rolling_calibrations(df: pd.DataFrame, *, window_days: int = 60,
                         min_gap_days: int = 1, step_days: int = 1,
                         date_col: str = "as_of_date", **fit_kwargs
                         ) -> dict[datetime.date, tuple]:
    """A calibration per classification date, from a strictly prior window.

    WHY ROLLING AND NOT PER-MONTH OR REGIME-SPLIT
    ---------------------------------------------

    Half-spreads are not constant and the tape says so. On the legacy
    deviations the per-month median moves from -0.30 bp (2026-03) to -1.79 bp
    (2026-06) -- and that is ``b0``, the quantity a static fit would freeze;
    ``tau`` inherits the same instability through ``s``.

    Three candidates, one chosen:

    * **per-month** is what the existing pipeline does
      (``backfill_stir_direction --calib-start/--calib-end``) and it has a
      boundary discontinuity by construction: the 1st of a month is calibrated
      on data ending 30 days ago while the 30th is calibrated on data ending
      yesterday. Every month boundary is a step change in ``tau`` that is an
      artefact of the calendar.
    * **regime-split** needs the regimes named in advance. The two the tape
      actually has -- the 2024-07 lifecycle ingest change (F-8) and the
      2024-10-07 cap reset (F-17) -- are not spread regimes, and choosing
      breakpoints from the same data that is being fitted is how a fit gets
      to look better than it is.
    * **rolling** has neither problem, at the cost of refitting. Cost is the
      only real objection and it is bounded: the EM is three passes over a
      window, and ``step_days`` amortises it when a window is not worth
      refitting daily.

    ``min_gap_days >= 1`` is not decoration. A calibration window that includes
    the day being classified contains the very prints whose direction is being
    inferred, which makes ``b0`` partly a function of the answer.

    A DAY WITH TOO LITTLE HISTORY BEHIND IT IS REPORTED, NOT DROPPED IN
    SILENCE. The first days of any sample have nothing before them and are
    expected to be skipped -- but the same silence covers a genuine hole in the
    middle, and a caller iterating the returned dict sees a clean run either
    way. Measured: 200 rows over 10 days returned ``{}`` with no exception and
    no warning. So a partial result warns with the count, and a result with no
    calibrations at all raises.

    Returns ``{as_of_date: (window_lo, window_hi, Calibration)}``.
    """
    if min_gap_days < 1:
        raise ValueError("a calibration window must end strictly before the "
                         f"day it classifies; got min_gap_days={min_gap_days}")
    if date_col not in df.columns:
        raise ValueError(f"rolling calibration needs a {date_col!r} column")

    dates = sorted({pd.Timestamp(d).date() for d in df[date_col]})
    d = pd.to_datetime(df[date_col]).dt.date.to_numpy()

    min_rows = fit_kwargs.get("min_n", MIN_BUCKET_N)
    out: dict[datetime.date, tuple] = {}
    considered = 0
    thin: list[datetime.date] = []
    for i, as_of in enumerate(dates):
        if i % step_days:
            continue                      # not asked for, so not a failure
        considered += 1
        hi = as_of - datetime.timedelta(days=min_gap_days)
        lo = hi - datetime.timedelta(days=window_days)
        sel = (d >= lo) & (d <= hi)
        window = df.loc[sel]
        if not sel.any() or len(window) < min_rows:
            thin.append(as_of)
            continue
        out[as_of] = (lo, hi, Calibration.fit(window, as_of=as_of, **fit_kwargs))
    if not out:
        raise ValueError(
            f"no calibration window in {considered} candidate dates held the "
            f"{min_rows} rows a fit needs (window_days={window_days}, "
            f"min_gap_days={min_gap_days}, dates "
            f"{dates[0]}..{dates[-1]}); returning an empty mapping here would "
            "look identical to a run that classified everything")
    if thin:
        warnings.warn(
            f"rolling_calibrations skipped {len(thin)} of {considered} dates "
            f"whose prior window held fewer than {min_rows} rows "
            f"({thin[0]}..{thin[-1]}); those days have no calibration and "
            "cannot be classified",
            stacklevel=2)
    return out


@dataclasses.dataclass(frozen=True)
class TauStability:
    """Does ``tau`` actually move, or is the variation sampling noise?"""

    k: int
    q: float
    dof: int
    p_value: float
    moves: bool
    spread_ratio: float
    pooled_tau: float
    method: str
    #: Fits handed in that had no ``se_log_tau`` and were therefore not tested.
    #: Every fallback fit has none -- and on real deviations that is all of
    #: them -- so ``k`` alone can make a test on 2 of 30 periods read as a test
    #: on the series.
    n_dropped: int = 0
    #: Bootstrap only: replicates that produced a usable Q. A replicate whose
    #: fits failed is not a draw from the null and is not in the denominator.
    bootstrap_reps_used: int | None = None


def tau_stability(fits, *, alpha: float = 0.05, method: str = "chi2",
                  reps: int = 200, seed: int = 0) -> TauStability:
    """Test the null that one ``tau`` describes every period.

    Cochran's Q on ``log tau`` with inverse-variance weights from each fit's
    own :attr:`MixtureFit.se_log_tau`. Under the null ``Q ~ chi2(k-1)``.

    The whole test rests on those standard errors being right, which is a
    finite-difference Hessian and therefore exactly the sort of thing that can
    be quietly wrong. So it is validated two ways before being used:
    ``test_se_log_tau_matches_the_empirical_spread`` checks the SE against the
    spread of repeated fits at known parameters, and ``method="bootstrap"``
    builds the null by resimulating from the pooled fit -- which needs no SE at
    all and must agree.
    """
    fits = list(fits)
    usable = [f for f in fits if f.se_log_tau and math.isfinite(f.se_log_tau)]
    dropped = len(fits) - len(usable)
    if len(usable) < 2:
        raise ValueError(
            f"tau_stability needs at least two fits with standard errors; got "
            f"{len(usable)} usable out of {len(fits)} ({dropped} have none). A "
            "forced or imported (b0, h, s) has no standard error by "
            "construction, so a window of fallback fits cannot be tested this "
            "way at all")

    y = np.array([math.log(f.tau) for f in usable])
    se = np.array([f.se_log_tau for f in usable], dtype=float)
    w = 1.0 / (se ** 2)
    mu = float((w * y).sum() / w.sum())
    q = float((w * (y - mu) ** 2).sum())
    dof = len(usable) - 1
    taus = np.array([f.tau for f in usable])
    spread = float(taus.max() / max(taus.min(), 1e-300))

    used = None
    if method == "chi2":
        from scipy import stats as sps
        p = float(sps.chi2.sf(q, dof))
    elif method == "bootstrap":
        p, used = _bootstrap_q_pvalue(usable, q, reps=reps, seed=seed)
    else:
        raise ValueError(f"unknown method {method!r}")

    return TauStability(k=len(usable), q=q, dof=dof, p_value=p,
                        moves=p < alpha, spread_ratio=spread,
                        pooled_tau=float(math.exp(mu)), method=method,
                        n_dropped=dropped, bootstrap_reps_used=used)


def _bootstrap_q_pvalue(fits, q_obs: float, *, reps: int,
                        seed: int) -> tuple[float, int]:
    """Null distribution of Q by resimulating each period from the pooled fit.

    Returns ``(p_value, replicates_used)``.

    A REPLICATE THAT COULD NOT BE FITTED IS NOT A DRAW FROM THE NULL. It used
    to be counted in the denominator anyway, so every failure scored silently
    as "not worse than observed" and pushed ``p`` down -- towards rejecting the
    null that ``tau`` is constant. Measured at ``h/s = 0.75``, n = 400: 4 of 60
    replicates skipped, a 6.7% downward bias. The degenerate case is worse than
    the bias: with every replicate failing, ``(0 + 1)/(reps + 1) = 0.016``
    returned ``moves=True`` from zero replicates -- and this test exists
    precisely to be the check that does NOT depend on ``se_log_tau``, so
    failing towards agreement with the SE-based test is the worst direction
    available.
    """
    rng = np.random.default_rng(seed)
    h = float(np.median([f.h for f in fits]))
    s = float(np.median([f.s for f in fits]))
    b0 = float(np.median([f.b0 for f in fits]))
    ns = [f.n_trimmed for f in fits]
    worse = 0
    used = 0
    for _ in range(reps):
        ys, ses = [], []
        for n in ns:
            x, _lab = simulate(b0=b0, h=h, s=s, n=n, rng=rng)
            f = fit_mixture(x, bucket="BOOT")
            if not f.se_log_tau:
                continue
            ys.append(math.log(f.tau))
            ses.append(f.se_log_tau)
        if len(ys) < 2:
            continue
        used += 1
        y = np.asarray(ys); w = 1.0 / np.asarray(ses) ** 2
        mu = float((w * y).sum() / w.sum())
        worse += float((w * (y - mu) ** 2).sum()) >= q_obs
    if used == 0:
        raise ValueError(
            f"the bootstrap null is empty: all {reps} replicate sets failed to "
            f"produce two fits with standard errors at n={ns}. There is no "
            "distribution to compare Q against, and returning the smallest "
            "attainable p-value here would report that tau moves on the "
            "strength of nothing at all")
    return (worse + 1) / (used + 1), used


# --------------------------------------------------------------------------
# 8. Validation. Public, because the tests and the runner use the same code.
# --------------------------------------------------------------------------

def simulate(*, b0: float, h: float, s: float, n: int, rng,
             weight_paid: float = 0.5):
    """Draw from the model. Returns ``(x, customer_paid)``.

    ``weight_paid`` exists to violate the fitted model on purpose: the fit
    imposes 0.5, so drawing at 0.65 is how the cost of that assumption gets
    measured instead of asserted.
    """
    paid = rng.random(n) < weight_paid
    x = b0 + np.where(paid, h, -h) + rng.normal(0.0, s, n)
    return x, paid


def _tau_errors(*, n: int, b0: float, h: float, s: float, reps: int, seed: int):
    rng = np.random.default_rng(seed)
    truth = s * s / (2.0 * h)
    out = np.empty(reps)
    for i in range(reps):
        x, _lab = simulate(b0=b0, h=h, s=s, n=n, rng=rng)
        out[i] = abs(fit_mixture(x, bucket="REC", min_n=0).tau / truth - 1.0)
    return out


def tau_recovery_error(*, n: int, b0: float, h: float, s: float,
                       reps: int = 200, seed: int = 0,
                       quantile: float = 0.90) -> float:
    """p90 relative error in ``tau`` over ``reps`` draws at sample size ``n``.

    This is the function :data:`MIN_BUCKET_N` was set from. Reported as a high
    quantile rather than a mean because the failure that matters is a bucket
    whose ``tau`` is badly wrong, not the average bucket.
    """
    return float(np.quantile(
        _tau_errors(n=n, b0=b0, h=h, s=s, reps=reps, seed=seed), quantile))


def recovery_grid(ns=(50, 100, 200, 400, 800, 1600, 3200),
                  separations=(0.5, 0.75, 1.0, 1.5, 2.5),
                  s: float = 0.18, b0: float = 0.0,
                  reps: int = 200, seed: int = 0) -> pd.DataFrame:
    """Recovery across a realistic grid of sample size and separation ``h/s``.

    The grid is the evidence for :data:`MIN_BUCKET_N`: read off the smallest
    ``n`` whose p90 error is inside :data:`TAU_RECOVERY_TOLERANCE` at the
    separations the tape plausibly has.
    """
    rows = []
    for sep in separations:
        h = sep * s
        for n in ns:
            e = _tau_errors(n=n, b0=b0, h=h, s=s, reps=reps, seed=seed)
            rows.append(dict(
                n=n, separation=sep, h=h, s=s, tau_true=s * s / (2 * h),
                p50_rel_err=float(np.quantile(e, 0.50)),
                p90_rel_err=float(np.quantile(e, 0.90)),
            ))
    return pd.DataFrame(rows)


def reliability(p, paid, n_bins: int = 10) -> pd.DataFrame:
    """Reliability table: among trades with ``p ~ 0.7``, how many really paid?

    **Requires labels, and the tape has none.** This runs on simulation, and
    it will run on the D2D-print monitor when that exists (a D2D print has both
    sides on the tape, so its direction is observable). Anything that calls it
    on real data without labels is measuring nothing.
    """
    p = np.asarray(p, dtype=float)
    paid = np.asarray(paid).astype(bool)
    if p.shape != paid.shape:
        raise ValueError(f"p and paid must align, got {p.shape} vs {paid.shape}")
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        rows.append(dict(bin_lo=edges[b], bin_hi=edges[b + 1], n=int(m.sum()),
                         mean_p=float(p[m].mean()) if m.any() else float("nan"),
                         realised=float(paid[m].mean()) if m.any() else float("nan")))
    return pd.DataFrame(rows)


def brier(p, paid) -> float:
    p = np.asarray(p, dtype=float)
    paid = np.asarray(paid).astype(float)
    return float(np.mean((p - paid) ** 2))


@dataclasses.dataclass(frozen=True)
class ImpliedSplit:
    """Mean ``p`` on data the fit did not see. Zero-label, non-circular."""

    n: int
    mean_p: float
    se: float
    z: float
    consistent: bool


def implied_split(x, fit: MixtureFit, z_max: float = 3.0) -> ImpliedSplit:
    """Does the fitted mixture still describe this sample's location?

    ``mean(p) = 0.5`` is imposed in sample by the equal-weight constraint and
    is **free out of sample**, so this is a genuine check and not a tautology.
    What it detects is the calibration window's ``b0`` no longer describing the
    day being classified -- a curve regime change, a session anomaly, or real
    one-way flow. It cannot tell those apart, which is why it is a monitor and
    not a correction: correcting it would re-introduce the free weight the
    model deliberately does not have.
    """
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    p = p_customer_paid(x, fit)
    n = int(p.size)
    mean_p = float(p.mean())
    se = float(p.std(ddof=1) / math.sqrt(n)) if n > 1 else float("nan")
    z = (mean_p - 0.5) / se if se and math.isfinite(se) and se > 0 else float("nan")
    return ImpliedSplit(n=n, mean_p=mean_p, se=se, z=float(z),
                        consistent=bool(math.isfinite(z) and abs(z) <= z_max))


@dataclasses.dataclass(frozen=True)
class GofResult:
    statistic: float
    p_value: float
    n: int


def gof_ks(x, fit: MixtureFit) -> GofResult:
    """KS of the sample against the fitted mixture CDF.

    Valid as stated only on data the fit did not see. On the fitting sample the
    p-value is anti-conservative, because three parameters were spent on the
    same points -- so it will reject too often, which is the safe direction but
    is not the stated test. Callers evaluating in sample should read the
    statistic, not the p-value.
    """
    from scipy import stats as sps

    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    res = sps.kstest(x, lambda v: mixture_cdf(v, fit.b0, fit.h, fit.s))
    return GofResult(statistic=float(res.statistic), p_value=float(res.pvalue),
                     n=int(x.size))


__all__ = [
    "BUCKET_COLS", "BucketKey", "CROSSCHECK_TOLERANCE", "Calibration",
    "DEAD_ZONE_DELTA", "DEFAULT_POOLING_ORDER", "DEVIATION_COL",
    "FIT_ANCHORED_H", "FIT_IMPRECISE", "MAX_SE_LOG_TAU", "trimmed_dispersion",
    "FIT_CROSSCHECK_DISAGREES", "FIT_LEPTOKURTIC", "FIT_OK", "FIT_POOLED",
    "FIT_ROBUST_FALLBACK", "FIT_SCALE_FLOOR", "FIT_UNDERSIZED",
    "FIT_UNSEPARATED", "GLOBAL_BUCKET", "GofResult", "ImpliedSplit",
    "LEPTOKURTOSIS_Z", "SEPARATION_ALPHA", "MEASURED_MIN_BUCKET_N_ANCHORED",
    "MIN_BUCKET_N_ANCHORED",
    "MAD_TO_SIGMA", "MEASURED_MIN_BUCKET_N", "MIN_BUCKET_N", "MIN_SEPARATION",
    "MixtureFit", "MomentCheck", "ProbabilityCall", "SpreadCrossCheck",
    "TAU_RECOVERY_TOLERANCE", "TENOR_BAND_EDGES", "TENOR_BAND_LABELS",
    "TRIM_MAD_K", "TauStability", "brier", "crosscheck_against_tick",
    "dead_zone_half_width_bps", "delta_for_dead_zone_bps",
    "direction_probability", "fit_mixture", "frame", "gof_ks", "implied_split",
    "loglik", "mixture_cdf", "moment_estimates", "moment_estimates_from_moments",
    "p_customer_paid", "pooling_ladder", "rank_bucket_dimensions",
    "recovery_grid", "reliability", "robust_scale", "rolling_calibrations",
    "simulate", "tau_recovery_error", "tau_stability", "tenor_band",
    "tick_stats_implied_by", "trim_mask",
]
