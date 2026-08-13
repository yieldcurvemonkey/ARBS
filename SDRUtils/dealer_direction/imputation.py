"""Capped-notional imputation: the largest prints are the ones whose size is missing.

Part 43 §43.4(h) publishes a block trade's notional at a **cap** rather than at
its true size, so the tape's most informative prints -- the ones that move a
dealer's book -- are exactly the ones whose notional cannot be read. 68,946 of
2,289,646 flow legs (3.01%) are capped (`is_capped` == `is_notional_capped`,
exactly, on every row), and they carry ~14% of the tape's DV01 *at the cap
value*, i.e. before any correction (14.7% measured on the tape's own
``sum(|risk|)``, 14.2% on the ``notional·tenor·1e-4`` proxy used below -- the
proxy is the one every share in this module is computed against, and the two
agreeing to half a point is itself a check).

This module turns that into a number and a flag. It does not turn it into a
silently bigger notional.

WHAT WAS MEASURED (probes in ``scratch/partB_*.py`` and ``scratch/imp*.py``,
recorded as LEDGER F-7 "Notional right-censoring", the one at LEDGER.md:839)
--------------------------------------------------------------------------------

The cap is a function of tenor at **nine** bands, not the four the brief
assumed, and the whole schedule was re-set mid-sample: last print under the old
values 2024-10-04, first under the new 2024-10-07, simultaneous across all nine
bands with zero overlap. That is the CFTC Division of Data's recalibrated
post-initial block-and-cap sizes taking effect 2024-10-07, to the day. The
schedule below was derived from the capped prints themselves -- their
``notional`` **is** the cap -- and matched to the regulation afterwards, not the
other way round. p10 = p50 = p90 = the cap in every band; purity 96.3-100%.

THE ESTIMATOR, AND WHY IT IS THE CENSORED ONE
---------------------------------------------

The estimand is ``E[notional | notional > C]``. The sub-cap sample is not a
clean draw from the tail: it is right-truncated at C. Two estimators were run
per cell; only one is defensible.

* **truncation-only MLE** -- fits ``[u, C)`` and never sees how many prints
  landed at the cap, so nothing ties its implied tail mass to the observed one.
  Measured error on the capped count: **-72% to +2400%**.
* **censored MLE** -- fits ``[u, C)`` *plus* the observed count of capped prints
  as mass on ``[C, inf)``. Strictly more information, and its predicted capped
  count reproduces the observed one to **±19% in every cell**. This is what
  ships.

Family: lognormal, threshold ``u = C/4``.

**The family is not chosen by fit quality, and pretending otherwise would hide
the biggest uncertainty here.** KS favours the lognormal in 13 of 18 cells at
``u = C/10``, but at the shipped ``u = C/4`` it splits **7 lognormal / 9 Pareto
/ 2 exact ties**, with the largest gap between the two statistics being 0.035
against absolute KS of 0.07-0.29 -- i.e. neither family fits, and they fail
about equally. AIC cannot discriminate over a single decade at all (gap of 11 on
a log-likelihood of 3.7e6 in the self-test). What actually decides it is that
the Pareto has **no estimand** in 2 of 18 cells at this threshold (alpha <= 1,
mean undefined) and in 10 of 18 at ``u = C/10``, while the censored lognormal
returns a finite number whose implied capped count matches the observed one.
Choosing the family that can answer is a choice, not a measurement, so the
quoted sensitivity band is *within-family* and family risk sits outside it.

AND IN FIVE CELLS A BOUND DECIDES THE ANSWER, NOT THE DATA
-----------------------------------------------------------

In V1 3m-6m, V1 5y-10y, V2 <=46d, V2 3m-6m and V2 5y-10y the censored fit runs
to ``sigma = LN_SIGMA_MAX`` with mu far below ``ln(u)``: over one decade that is
a lognormal imitating a power law. Its unconstrained maximum does exist, but it
is a long way outside the box and the ridge leading there is **flat** -- for V1
5y-10y, lifting the sigma bound to 12 moves the optimum to (mu = -82.7,
sigma = 9.15) and buys 0.45 of log-likelihood out of 779,525, while the
multiplier goes 4.218 -> 4.804 (+14%). The data does not identify the estimand
in these cells; the modelling choice ``sigma <= 6`` does, and 14% of the
multiplier is what that choice costs. A control cell fitted interior (V1 2y-5y)
does not move by a digit under the same test.

So those cells carry ``ln_degenerate = True`` and their multipliers are **lower
bounds**. They are **55.3% of the imputed excess DV01**, which is why this is a
section and not a footnote.

Until this was fixed the deciding bound was :data:`LN_MU_SLACK`, an undocumented
numerical guard, in six cells -- and ``ln_degenerate`` watched only sigma, so it
reported all six clean *because* the guard stopped the optimiser before sigma
could reach its own threshold. Unbinding it moves V1 5y-10y from 3.954 to 4.218
(+6.7%) and the headline from 0.1541 to 0.1597. The remaining bound is at least
the documented one, and the flag now fires on any wall of the box.

THE HEADLINE
------------

Multipliers ``E[N | N > C] / C`` run 1.64-4.22 by cell, and the share of the
tape's DV01 that is **imputed rather than observed** is:

===========  ======================  =================
bucket       imputed DV01 share      across thresholds
===========  ======================  =================
<=2y         22.0%                   16.5% - 22.0%
2-10y        17.5%                    9.5% - 17.5%
10-30y        9.2%                    9.2% - 18.3%
>30y          8.2%                    3.8% -  8.2%
**overall**  **16.0%**               **10.6% - 16.8%**
===========  ======================  =================

Applied leg by leg over the production population (68,945 capped legs, keyed on
notional) rather than over the 67,619 the fit was calibrated on, the overall
figure is **16.22%** -- the two populations differ by 1.96% and the headline by
0.25pp, which is the right order for a coverage difference and a useful check
that neither number is a coding accident. Notional shares are much larger
(27.8% overall) and much less relevant: a $17bn three-week print is a rounding
error in duration terms.

A cross-check that uses none of the likelihood: capped prints carry **14.2%** of
the tape's DV01 proxy at the cap value (14.17% measured leg by leg), and for a
flat multiplier k the imputed share is just
``(k-1)·0.142 / (1 + (k-1)·0.142)`` -- 12.4% at k = 2.0, 13.5% at k = 2.1. The
fit's DV01-weighted effective multiplier is 2.37, which that formula turns into
16.2%, exactly the leg-by-leg figure. So the headline is arithmetic on two
numbers a reader can check in one query, and the tail model only supplies the k.

THE MULTIPLIERS ARE IN-SAMPLE FOR EVERY DAY THEY ARE APPLIED TO
----------------------------------------------------------------

:data:`CAP_BANDS` is fitted over 2024-03-01..2026-08-07 and :func:`impute`
applies it to every leg inside that window, so a ladder for 2024-06-01 carries
an uplift estimated partly from prints that had not happened yet. For a
descriptive note on the whole sample that is what you want -- it is the best
estimate of the censoring, and the cap schedule itself is a published constant,
not a fitted quantity. For a backtest it is lookahead, and the honest fix is a
vintage per as-of date rather than a caveat. Nothing in this module does that.

THE INFINITE-MEAN TRAP -- IT FIRED, AND IT STAYS DOCUMENTED
-----------------------------------------------------------

A Pareto fit at ``u = C/10`` returned **alpha < 1 in 10 of 18 cells**, i.e. no
mean at all. The correct reading is not that swap notionals have a monstrous
tail; it is that ``[C/10, C)`` is the **body** of the distribution, where a
Pareto has no business being fitted. At defensible thresholds the median alpha
is 1.32-1.44 and the mean exists in 16-17 of 18 cells; at the shipped
``u = C/4`` the median is 1.32 and two short-tenor V1 cells are still below 1.
So every band carries :attr:`CapBand.tail_index` and
:attr:`CapBand.tail_mean_exists` next to its multiplier, and
:func:`pareto_mean_above` returns ``inf`` rather than a number when the mean
does not exist. The lognormal headline does not depend on any of it -- that is
the point of reporting both.

IS THE CENSORING DIRECTIONALLY NEUTRAL? NOT ESTABLISHED
--------------------------------------------------------

(Probes: ``scratch/imp07_neutrality.py``, ``imp08_neutrality_ci.py``,
``imp09_mh_curve_only.py`` -- not the ``partB_*`` set, which is the size model.)

This is the difference between a caveat and a bias. A ~16% DV01 uplift spread
evenly over both sides widens the ladder; a ~16% uplift concentrated on one side
*tilts* it. Measured on the only direction labels that exist today -- the frozen
``arbs_stir_direction_v1`` classifier, 75,255 joined flow legs, 2026-01-12..07-29
-- capped prints carry a **RECEIVED** label 34.4% of the time against 28.1% for
uncapped ones: odds ratio **1.344, 95% CI [1.210, 1.493]**, Fisher p < 1e-4. It
is not a composition effect either; holding the classification method fixed
(Mantel-Haenszel) *raises* it to 1.43.

But the skew lives entirely in the two methods that reprice against a curve.
Pooled over those two (``RATE_VS_MID`` 1.474 and ``NPV_VS_UPFRONT`` 1.662, which
are statistically homogeneous -- z = -0.96, p = 0.34, so pooling is legitimate)
the odds ratio is **1.532 [1.368, 1.716]**. Their curve is the old Barchart mid,
measured biased ~0.5bp high with ~7x the dispersion of the Citi minute curve,
which is why ``RATE_VS_MID`` reads 78% PAID overall. ``TICK_RULE``, the one
method that never touches a curve, gives **0.882 [0.642, 1.212]** on 154 capped
prints -- and those two intervals are **disjoint**, so this is not one estimate
with noise around it. A mid bias pushes labels toward PAID, and prints that trade
further from mid (bigger ones, i.e. capped ones) are less affected by it, so
their labels drift back toward the 50/50 ``TICK_RULE`` reports. That is exactly
the pattern observed, so the leading explanation for the whole effect is the
biased mid rather than directional flow.

``is_block`` × direction settles how much these labels can be trusted at all: the
two curve methods point in **opposite** directions (``RATE_VS_MID`` 0.707
[0.546, 0.916] vs ``NPV_VS_UPFRONT`` 1.820 [1.498, 2.211], homogeneity
z = -5.72, p < 1e-8), which cannot both be a fact about blocks, and their pooled
1.242 is therefore meaningless. The all-methods 1.188 is on top of that a Simpson
artefact of blocks routing to ``NPV_VS_UPFRONT`` 46.7% of the time against 18.7%
for non-blocks.

**Conclusion: unresolved, leaning artefact.** The 2x2 must be re-run against this
package's own repriced direction (unbiased Citi minute curve, no 3.02y cutoff)
before the imputation can be called neutral, and the window above is entirely
inside the V2 vintage, so it says nothing about V1. Until then the per-row flag
is what protects the consumer: the ladder can be produced with and without the
imputed DV01, and the note reports it as a separate line rather than folding it
into the headline.

THE OVERLAP WITH LEGS THAT CANNOT BE CLASSIFIED AT ALL
-------------------------------------------------------

The imputation and the direction inference fail on overlapping populations, so
the two coverage gaps are not independent. Capped legs carry a NULL
``fixed_rate`` **5.87%** of the time against **1.21%** for uncapped legs -- 4.85x
-- and a leg with no fixed rate cannot be repriced, so neither the rate rule nor
the upfront rule can call it. 4,050 flow legs are both. In DV01 terms the
intersection is smaller than the count ratio suggests (those legs are shorter
than the average capped leg): 3.99% of the imputed *excess* DV01 and 3.70% of all
post-imputation capped DV01. The number that matters for the note runs the other
way round -- **46.2% of all unclassifiable DV01 is imputed capped DV01** -- so
the two gaps are largely the same gap, and reporting them as separate
independent deductions would double-count the coverage loss.

HOW THE MULTIPLIER IS APPLIED
-----------------------------

**To the signed KRD, after direction inference. Never to notional.** The tape's
``risk`` column and any repriced KRD are computed *from* the capped notional, so
they are right-censored in exactly the same proportion; scaling notional up
front and then pricing runs the multiplier through the pricing path a second
time. :func:`apply_to_signed_krd` is the only application helper in this module,
and there is deliberately no notional-scaling counterpart -- no function, and no
column that can be mistaken for one. ``notional × multiplier`` does exist, as a
number to report a size with, and it is spelled ``expected_notional`` on
:class:`Imputation` and ``notional_expected_reporting_only`` on the frame,
because a column sitting next to ``notional`` gets selected without anybody
reading a docstring.

The imputed value never overwrites anything either: :func:`impute` returns a
separate expected notional plus ``notional_imputed`` / ``notional_impute_factor``
for :class:`~.types.Provenance`, so a consumer can drop every imputed row and
get the observed-only ladder back.

Every function on the calibration path is validated against simulated data whose
parameters are known before it is allowed near the tape --
``tests/test_dealer_direction_imputation.py`` sections 1-2, which cover both
lognormal MLEs, both Pareto estimators, both truncated cdfs, the KS statistic
and :func:`fit_frequency_table` itself. A censored MLE that is quietly wrong
still returns a number, and so does a cdf that has lost its renormalisation.
"""
from __future__ import annotations

import bisect
import dataclasses
import datetime
import warnings
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import optimize
from scipy.special import ndtr

# ===========================================================================
# The measured schedule
# ===========================================================================

VINTAGE_V1 = "V1"
VINTAGE_V2 = "V2"

#: First day of the recalibrated schedule. Derived from the tape (last V1 print
#: 2024-10-04, first V2 print 2024-10-07, the weekend between) and only then
#: checked against CFTC release 8913-24, which gives the same date.
CAP_SCHEDULE_SWITCH = datetime.date(2024, 10, 7)

#: Tail threshold the shipped calibration was fitted at, ``u = C / DIVISOR``.
#: Not a free parameter to twiddle per cell: the sensitivity across
#: C/2, C/4, C/10, C/20, q0.90 and q0.95 is reported instead
#: (:data:`SENSITIVITY_DV01_SHARE`).
THRESHOLD_DIVISOR = 4.0

#: Below this weight in ``[u, C)`` a cell is not fitted at all. A wide prior on
#: forty observations produces a confident multiplier out of nothing.
MIN_TAIL_WEIGHT = 200.0
MIN_TAIL_POINTS = 5

#: log-notional sd bound. 6 is already absurd for money; a fit that pins here
#: has collapsed onto a power-law mimic that fits inside [u, C) and extrapolates
#: to nonsense. **This is the one bound allowed to bind** -- it is a modelling
#: choice, not a numerical guard -- and where it does bind,
#: :attr:`CapBand.ln_degenerate` says so: 5 of 18 cells at the shipped
#: threshold, carrying 55.3% of the imputed excess DV01. Measured price of the
#: choice in the worst cell (V1 5y-10y): the unconstrained optimum is at
#: sigma = 9.15 with multiplier 4.804 against the shipped 4.218, and it is
#: better by 0.45 of log-likelihood out of 779,525.
LN_SIGMA_MAX = 6.0

#: How far below ``ln(u)`` mu may wander before the likelihood is walled off.
#: A numerical guard on Nelder-Mead, **not** a modelling choice, so it must not
#: be what decides an estimate -- and at the 30.0 this module shipped with, it
#: was: six cells sat on this wall to within 4e-7 and their multipliers were a
#: function of the guard (V1 5y-10y 3.954, V2 46d-3m 3.763). Measured on the
#: shipped frequency cache, the calibration is unchanged at 150 / 300 in every
#: printed digit at u = C/4 *and* at all six sensitivity thresholds, so 150 is
#: past the point where the wall touches anything; relaxing it moves the fit
#: onto :data:`LN_SIGMA_MAX`, which is documented and reported.
LN_MU_SLACK = 150.0

#: Distance from a box wall inside which a fit counts as pinned to it. The
#: optimiser either lands on a wall to numerical precision or nowhere near one
#: -- measured gaps on the shipped calibration are <= 4.4e-7 or >= 13.0 -- so
#: anything in between separates them.
LN_BOX_TOL = 1e-3


@dataclasses.dataclass(frozen=True)
class CapBand:
    """One (tenor band × schedule vintage) cell, with its fitted tail.

    ``lo``/``hi`` are the **empirical** edges the fit was run on, kept verbatim
    so a refit reproduces the shipped numbers. They are not the lookup edges:
    the merge that produced them dropped bins with n < 25, leaving a hole at
    V1 10.5-10.75y and nothing capped past 41y, and a lookup with a hole in it
    returns nothing on a live print. :func:`band_for_tenor` therefore runs each
    band from its own ``lo`` to the *next* band's ``lo``, the last to infinity.

    ``ln_degenerate`` is not decoration. In those cells the censored fit sits on
    the ``sigma <= LN_SIGMA_MAX`` wall -- a lognormal imitating a power law
    inside ``[u, C)`` -- with its unconstrained maximum far outside the box along
    a nearly flat ridge, so the reported multiplier is what the modelling bound
    allows and is a **lower bound** on what the family would say if released
    (measured: V1 5y-10y 4.218 -> 4.804 for 0.45 of log-likelihood).
    """

    vintage: str
    lo: float                    # years, inclusive -- the fit window
    hi: float                    # years, exclusive -- the fit window
    cap: float                   # USD notional; this is what the tape prints
    label: str                   # the regulator's band, for reporting
    ln_mu: float                 # censored-MLE lognormal parameters ...
    ln_sigma: float              # ... at u = cap / THRESHOLD_DIVISOR
    multiplier: float            # E[notional | notional > cap] / cap
    tail_index: float            # Pareto alpha, censored MLE -- REPORTED, not used
    capped_count_error: float    # predicted / observed capped count - 1
    ks_lognormal: float          # both KS statistics are taken against the
    ks_pareto: float             # TRUNCATION-only fits -- see the docstring
    ln_degenerate: bool          # censored fit pinned on a box wall (sigma, here)
    n_capped: int                # capped prints the fit was calibrated on

    @property
    def tail_mean_exists(self) -> bool:
        """Whether the *Pareto* mean exists. See the module docstring."""
        return bool(self.tail_index > 1.0)

    @property
    def expected_notional(self) -> float:
        return self.multiplier * self.cap


#: The nine bands × two vintages, with the shipped lognormal censored fit at
#: u = C/4. Generated by ``scratch/imp_fix01_sweep.py`` (which reproduces the
#: previous table exactly at the old ``LN_MU_SLACK`` before it is believed at the
#: new one) rather than typed -- 18 × 9 hand-copied numbers is how a calibration
#: acquires a typo no test can see. The multiplier is re-derivable from
#: (ln_mu, ln_sigma, cap), and the test suite re-derives it.
CAP_BANDS: tuple[CapBand, ...] = (
    CapBand("V1", 0.0, 0.12, 6400000000.0, "<=46d",
            ln_mu=21.673910117757686, ln_sigma=1.1379457947596319,
            multiplier=2.2980866817521064, tail_index=0.7550953662487064,
            capped_count_error=-0.003014906343644652,
            ks_lognormal=0.13299421519345422, ks_pareto=0.11958024031062198,
            ln_degenerate=False, n_capped=1411),
    CapBand("V1", 0.12, 0.3, 2100000000.0, "46d-3m",
            ln_mu=21.373393800030634, ln_sigma=0.9127106834118958,
            multiplier=2.381485662172644, tail_index=0.46458307914595526,
            capped_count_error=0.03674900340890752,
            ks_lognormal=0.15202089774803174, ks_pareto=0.150298847716689,
            ln_degenerate=False, n_capped=3984),
    CapBand("V1", 0.3, 0.54, 1200000000.0, "3m-6m",
            ln_mu=-27.06362633038566, ln_sigma=5.999999999397983,
            multiplier=3.4265241620443434, tail_index=1.3281950998136864,
            capped_count_error=-0.003173506511767843,
            ks_lognormal=0.12438625204582651, ks_pareto=0.12438625204582651,
            ln_degenerate=True, n_capped=229),
    CapBand("V1", 0.54, 1.04, 1100000000.0, "6m-1y",
            ln_mu=2.4104131959100323, ln_sigma=3.77969017016506,
            multiplier=3.166839233056532, tail_index=1.2790758042247652,
            capped_count_error=0.0029053772193325944,
            ks_lognormal=0.10199319472824953, ks_pareto=0.10211673608591032,
            ln_degenerate=False, n_capped=959),
    CapBand("V1", 1.04, 2.25, 460000000.0, "1y-2y",
            ln_mu=12.929935375442675, ln_sigma=2.5387806185354767,
            multiplier=3.237850817848236, tail_index=1.0846980309845464,
            capped_count_error=-0.0035608644833040604,
            ks_lognormal=0.0942612221293912, ks_pareto=0.089425179042007,
            ln_degenerate=False, n_capped=4569),
    CapBand("V1", 2.25, 5.25, 240000000.0, "2y-5y",
            ln_mu=18.264477128997147, ln_sigma=0.8979268449241443,
            multiplier=1.7066855964459757, tail_index=1.032704763300416,
            capped_count_error=-0.07641277401894431,
            ks_lognormal=0.133296314305011, ks_pareto=0.12488846828932226,
            ln_degenerate=False, n_capped=10587),
    CapBand("V1", 5.25, 10.5, 170000000.0, "5y-10y",
            ln_mu=-24.767397503298625, ln_sigma=5.999999999939118,
            multiplier=4.217577034379514, tail_index=1.212393511465417,
            capped_count_error=-0.012346121691816148,
            ks_lognormal=0.10649691847465309, ks_pareto=0.1136192098866631,
            ln_degenerate=True, n_capped=9484),
    CapBand("V1", 10.75, 31.0, 120000000.0, "10y-30y",
            ln_mu=16.78364106282918, ln_sigma=1.2289181834921472,
            multiplier=1.9925855972069415, tail_index=1.098841755844256,
            capped_count_error=-0.016048785103818464,
            ks_lognormal=0.06979560598420564, ks_pareto=0.07880549683394117,
            ln_degenerate=False, n_capped=4010),
    CapBand("V1", 31.0, 41.0, 75000000.0, ">30y",
            ln_mu=16.49878270359823, ln_sigma=0.992932951230848,
            multiplier=1.6445688942026644, tail_index=1.3275939250309252,
            capped_count_error=-0.06550132677326148,
            ks_lognormal=0.16575221619830333, ks_pareto=0.15936459187822843,
            ln_degenerate=False, n_capped=60),
    CapBand("V2", 0.0, 0.12, 17000000000.0, "<=46d",
            ln_mu=-29.250683374038683, ln_sigma=5.999999999997461,
            multiplier=2.875813920057447, tail_index=1.4597407419545152,
            capped_count_error=-0.0916988314736692,
            ks_lognormal=0.2861061946902655, ks_pareto=0.2753833579380677,
            ln_degenerate=True, n_capped=1875),
    CapBand("V2", 0.12, 0.3, 7500000000.0, "46d-3m",
            ln_mu=-8.690435140149537, ln_sigma=5.0312585983566915,
            multiplier=3.7638380409952434, tail_index=1.238831001927781,
            capped_count_error=0.09965245723510674,
            ks_lognormal=0.21981993877721492, ks_pareto=0.21957690936701177,
            ln_degenerate=False, n_capped=2616),
    CapBand("V2", 0.3, 0.54, 2000000000.0, "3m-6m",
            ln_mu=-30.649753786370106, ln_sigma=5.999999999985699,
            multiplier=2.9444652085779435, tail_index=1.438748075353826,
            capped_count_error=-0.18642750311011425,
            ks_lognormal=0.26277372262773724, ks_pareto=0.26277372262773724,
            ln_degenerate=True, n_capped=603),
    CapBand("V2", 0.54, 1.04, 1700000000.0, "6m-1y",
            ln_mu=12.674357249688168, ln_sigma=2.351091793210915,
            multiplier=2.200633428982075, tail_index=1.4984419454951228,
            capped_count_error=-0.0157270019071033,
            ks_lognormal=0.1324182777401722, ks_pareto=0.14184252309921658,
            ln_degenerate=False, n_capped=1852),
    CapBand("V2", 1.04, 2.25, 1100000000.0, "1y-2y",
            ln_mu=17.047362332517515, ln_sigma=1.5688914206365658,
            multiplier=1.9614262516420764, tail_index=1.41339169822191,
            capped_count_error=-0.01459436720688978,
            ks_lognormal=0.09801285321842623, ks_pareto=0.09823459980961446,
            ln_degenerate=False, n_capped=4246),
    CapBand("V2", 2.25, 5.25, 650000000.0, "2y-5y",
            ln_mu=17.812647974918, ln_sigma=1.16954914037899,
            multiplier=1.6692104963931502, tail_index=1.531070698605684,
            capped_count_error=-0.04613107304044506,
            ks_lognormal=0.07666980543803213, ks_pareto=0.09447442587066139,
            ln_degenerate=False, n_capped=7623),
    CapBand("V2", 5.25, 11.0, 470000000.0, "5y-10y",
            ln_mu=-34.823733790401164, ln_sigma=5.999999999907314,
            multiplier=2.7125333989717215, tail_index=1.5146517606744674,
            capped_count_error=0.016089281975294245,
            ks_lognormal=0.16588248518619628, ks_pareto=0.13072586710733408,
            ln_degenerate=True, n_capped=8472),
    CapBand("V2", 11.0, 31.0, 250000000.0, "10y-30y",
            ln_mu=17.461912846755226, ln_sigma=1.092603400209808,
            multiplier=1.723388554360291, tail_index=1.31727959135829,
            capped_count_error=-0.04813279373681012,
            ks_lognormal=0.08805599598440872, ks_pareto=0.0717410691535581,
            ln_degenerate=False, n_capped=4996),
    CapBand("V2", 31.0, 45.0, 160000000.0, ">30y",
            ln_mu=9.059939434754272, ln_sigma=2.226704041493988,
            multiplier=1.8192484132974658, tail_index=1.8878916161045562,
            capped_count_error=-0.06765064706026824,
            ks_lognormal=0.21224937722332027, ks_pareto=0.23198974451801396,
            ln_degenerate=False, n_capped=43),
)

_BANDS_BY_VINTAGE: dict[str, tuple[CapBand, ...]] = {
    v: tuple(b for b in CAP_BANDS if b.vintage == v) for v in (VINTAGE_V1, VINTAGE_V2)
}
_LO_EDGES: dict[str, list[float]] = {
    v: [b.lo for b in bands] for v, bands in _BANDS_BY_VINTAGE.items()
}
#: (vintage, cap) -> band. Caps are unique within a vintage, which is what makes
#: the notional the primary key for a capped print. Cross-vintage they are NOT
#: unique ($1.1bn is V1 6m-1y and V2 1y-2y), so the date is always needed first.
_BY_CAP: dict[tuple[str, float], CapBand] = {(b.vintage, b.cap): b for b in CAP_BANDS}


# ===========================================================================
# The headline, so the written note and the code cannot drift apart
# ===========================================================================

#: Share of the tape's DV01 proxy (Σ notional·tenor·1e-4) that is imputed rather
#: than observed, at the shipped u = C/4. A proxy and not a repriced KRD on
#: purpose: it is model-free given the notional, so it does not inherit the
#: pricing path's own errors on top of the imputation's.
IMPUTED_DV01_SHARE = 0.1597
IMPUTED_NOTIONAL_SHARE = 0.2783

#: The same headline over the production population -- all 68,945 capped legs
#: keyed on notional, not the 67,619 the per-tenor fit was calibrated on -- with
#: the two numbers the model-free cross-check needs: the DV01 proxy share
#: capped prints carry *at the cap value*, and the DV01-weighted effective
#: multiplier. These three are one identity apart,
#: ``share = (k-1)·c / (1 + (k-1)·c)``, and the test suite evaluates it: a
#: headline edited without the fit behind it stops satisfying its own
#: arithmetic. Measured by ``scratch/imp_fix06_end_to_end.py`` through the
#: public API, which is a second code path from the frequency-table fit above.
IMPUTED_DV01_SHARE_LEG_BY_LEG = 0.1622
CAPPED_AT_CAP_DV01_SHARE = 0.1417
EFFECTIVE_MULTIPLIER = 2.3664

#: Same, per coarse Part 43 tenor bucket: (imputed notional share, imputed DV01
#: share). The <=2y bucket dominates the notional number and not the DV01 one --
#: a $17bn 3-week print is a rounding error in duration terms.
IMPUTED_SHARE_BY_BUCKET: dict[str, tuple[float, float]] = {
    "<=2y": (0.3095, 0.2195),
    "2-10y": (0.1565, 0.1749),
    "10-30y": (0.1034, 0.0917),
    ">30y": (0.0835, 0.0818),
}

#: Per-bucket DV01 share across the same six thresholds. A single bucket moves
#: much more than the aggregate does, which is the reason the aggregate is what
#: gets quoted. ``>30y`` is the honest exception: it holds 103 capped prints in
#: total and its tail window falls below :data:`MIN_TAIL_WEIGHT` at two of the
#: six thresholds, so it is unfittable there -- the band below covers the four
#: thresholds where a fit exists, and "no fit" must never be read as "no
#: imputation".
SENSITIVITY_DV01_SHARE_BY_BUCKET: dict[str, tuple[float, float]] = {
    "<=2y": (0.1645, 0.2195),
    "2-10y": (0.0949, 0.1749),
    "10-30y": (0.0917, 0.1825),
    ">30y": (0.0377, 0.0818),
}

#: Range across the six thresholds tried (u = C/2, C/4, C/10, C/20, cell-q0.90,
#: cell-q0.95). **Within-lognormal-family only, and threshold is not the only
#: axis inside the family**: the fitter's own numerical box is a second one. At
#: the ``LN_MU_SLACK = 30`` this module shipped with, the box bound six cells and
#: the same sweep read (0.1058, 0.1603) with a headline of 0.1541; unbinding it
#: (see :data:`LN_MU_SLACK`) moves the headline to 0.1597 and the top of the band
#: to 0.1684, i.e. roughly a third of the band's width came from a guard rather
#: than from the tape. Absolute KS is 0.0698-0.2861 for the lognormal and
#: 0.0717-0.2754 for the Pareto, so neither family fits well and family risk sits
#: OUTSIDE this band, not inside it. Individual cells swing far more than the
#: aggregate (V1 5y-10y moves 1.8x-4.2x); the aggregate is the number to quote.
SENSITIVITY_DV01_SHARE = (0.1058, 0.1684)
SENSITIVITY_NOTIONAL_SHARE = (0.1653, 0.2783)

#: The direction-neutrality 2x2, as (odds ratio, lo95, hi95) on the frozen
#: classifier's labels: odds that a print is labelled RECEIVED, capped vs
#: uncapped. Two estimates, deliberately kept apart, because they disagree and
#: the disagreement is the finding -- see the module docstring. The curve-based
#: figure is the pooled Mantel-Haenszel estimate over ``RATE_VS_MID`` and
#: ``NPV_VS_UPFRONT``; the curve-free one is ``TICK_RULE`` alone.
CAPPED_RECEIVED_ODDS_RATIO_CURVE_BASED = (1.532, 1.368, 1.716)
CAPPED_RECEIVED_ODDS_RATIO_CURVE_FREE = (0.882, 0.642, 1.212)

#: Share of the imputed *excess* DV01 sitting on legs with a NULL ``fixed_rate``,
#: i.e. DV01 that gets a size correction it can never get a direction for.
UNCLASSIFIABLE_SHARE_OF_IMPUTED_DV01 = 0.0399
#: ... and the same intersection seen from the other side, which is the larger
#: number: the imputed capped DV01's share of ALL unclassifiable DV01.
IMPUTED_SHARE_OF_UNCLASSIFIABLE_DV01 = 0.462


# ===========================================================================
# Schedule lookup
# ===========================================================================

def _as_date(value) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return pd.Timestamp(value).date()


def vintage_for(as_of_date) -> str:
    """Which cap schedule was in force on this day.

    **Which clock**: the tape's ``as_of_date``, i.e. the reporting day. The cap
    is applied by the SDR when it publishes the print, so the schedule in force
    is the one in force *then*, not on the execution date -- and the two differ
    on backloaded rows, where :attr:`~.types.Clocks.execution` "can be years
    stale". A backloaded print that straddles :data:`CAP_SCHEDULE_SWITCH` gets
    the wrong cap table if it is keyed on execution, and the wrong table means
    the wrong multiplier or none at all. The switch date itself was *derived*
    from ``as_of_date``, which is the other reason it is the right key here.
    """
    return VINTAGE_V1 if _as_date(as_of_date) < CAP_SCHEDULE_SWITCH else VINTAGE_V2


def bands_for_vintage(vintage: str) -> tuple[CapBand, ...]:
    try:
        return _BANDS_BY_VINTAGE[vintage]
    except KeyError:
        raise ValueError(f"unknown cap schedule vintage {vintage!r}") from None


def band_for_tenor(tenor_years: float, as_of_date) -> CapBand:
    """The band a tenor falls in. Total: every non-negative tenor has one."""
    try:
        t = float(tenor_years)
    except (TypeError, ValueError):
        t = float("nan")   # None and "7y" land here, and get the same message
    if not np.isfinite(t) or t < 0:
        raise ValueError(f"tenor_years must be a non-negative number, got {tenor_years!r}")
    vintage = vintage_for(as_of_date)
    i = bisect.bisect_right(_LO_EDGES[vintage], t) - 1
    return _BANDS_BY_VINTAGE[vintage][max(i, 0)]


def cap_for(tenor_years: float, as_of_date) -> float:
    """The §43.4 cap that applied to this tenor on this day."""
    return band_for_tenor(tenor_years, as_of_date).cap


def band_for_capped_notional(notional: float, as_of_date) -> CapBand | None:
    """The band a *capped* print belongs to, keyed on the printed notional.

    The printed notional of a capped print IS the cap, and caps are unique
    within a vintage, so this is an exact identification -- it succeeds on
    68,945 of the 68,946 capped flow legs.

    Tenor is the weaker key, and not only at the edges. The two keys disagree on
    **1,326 legs (1.92%)**, and the disagreements are not all narrow: 173 legs
    carry the V1 5y-10y cap of $170mm at tenors from 5.06y to 25.02y, and 330
    carry the V1 2y-5y cap at tenors out to 15.01y. The regulator's tenor is not
    the tape's date-derived ``tenor_years`` -- most likely the cap was applied to
    the reported transaction (a package, with its own tenor) rather than to this
    leg. Since the cap that was actually applied is observed and the tenor band
    is only how the sub-cap population happened to be partitioned for fitting,
    the notional wins. ``None`` means the notional matches no cap in force that
    day, which is not something to paper over -- see :func:`impute`.
    """
    return _BY_CAP.get((vintage_for(as_of_date), float(notional)))


def tenor_band_agrees(notional: float, tenor_years: float, as_of_date) -> bool | None:
    """Audit hook: does the tenor put this capped print in the band its notional does?

    ``None`` when the notional matches no cap. Disagreement is not a defect --
    it is the 1.92% measured above -- but those are exactly the legs the
    per-tenor fit dropped (67,619 agreeing legs, which is precisely the
    calibration population), so a consumer reconciling against the fit needs to
    be able to count them rather than discover them.
    """
    by_notional = band_for_capped_notional(notional, as_of_date)
    if by_notional is None:
        return None
    return by_notional.cap == band_for_tenor(tenor_years, as_of_date).cap


# ===========================================================================
# The per-leg result
# ===========================================================================

REASON_NOT_CAPPED = "NOT_CAPPED"
REASON_IMPUTED = "IMPUTED"
#: Flagged capped, but the printed notional is not a cap in force that day. One
#: such leg exists on the whole tape ($78,613,002 at 0.25y on 2025-09-17, where
#: the V2 cap is $7.5bn). Nothing about that print says how it was censored, so
#: it gets no multiplier -- it gets a name.
REASON_CAP_UNRECOGNISED = "CAP_VALUE_UNRECOGNISED"


@dataclasses.dataclass(frozen=True)
class Imputation:
    """What the cap correction knows about one leg. Never a replacement value."""

    notional_imputed: bool
    notional_impute_factor: float | None
    #: ``factor × printed notional``, for reporting a size. **Not a pricing
    #: input**: ``risk`` and any repriced KRD are already computed from the
    #: capped notional, so pricing off this number and then spending the factor
    #: again in :func:`apply_to_signed_krd` squares the correction. The frame
    #: path names the same quantity ``notional_expected_reporting_only`` for
    #: exactly that reason -- a column gets selected without reading a comment.
    expected_notional: float | None
    band_label: str | None
    tail_index: float | None
    tail_mean_exists: bool | None
    reason: str

    def provenance_fields(self) -> dict:
        """The two fields :class:`~.types.Provenance` declares, ready to splat.

        Keeping this as one call means the flag and the multiplier travel
        together; a row cannot end up with a scaled KRD and no record of why.
        """
        return {"notional_imputed": self.notional_imputed,
                "notional_impute_factor": self.notional_impute_factor}


_NOT_CAPPED = Imputation(False, None, None, None, None, None, REASON_NOT_CAPPED)


def impute(notional: float, as_of_date, is_capped: bool,
           tenor_years: float | None = None) -> Imputation:
    """Expected true size of one leg, flagged.

    ``expected = multiplier × printed notional`` rather than the cell's
    ``E[N | N > C]`` outright: the two are the same wherever the print sits
    exactly on its cap (96.3-100% of a band, and 99.998% of the tape once the
    notional is used as the key), and where they differ the scale-free form
    degrades gracefully instead of asserting a size the print contradicts.

    ``tenor_years`` is optional and is *not* used to pick the band for a capped
    print -- see :func:`band_for_capped_notional` for why the notional is the
    stronger key.
    """
    if not is_capped:
        return _NOT_CAPPED
    band = band_for_capped_notional(notional, as_of_date)
    if band is None:
        return Imputation(False, None, None, None, None, None,
                          REASON_CAP_UNRECOGNISED)
    return Imputation(
        notional_imputed=True,
        notional_impute_factor=band.multiplier,
        expected_notional=band.multiplier * float(notional),
        band_label=f"{band.vintage} {band.label}",
        tail_index=band.tail_index,
        tail_mean_exists=band.tail_mean_exists,
        reason=REASON_IMPUTED,
    )


def impute_frame(legs: pd.DataFrame, *, notional: str = "notional",
                 as_of_date: str = "as_of_date", is_capped: str = "is_capped",
                 tenor_years: str | None = "tenor_years") -> pd.DataFrame:
    """Vectorised :func:`impute` over a leg frame. Adds columns, edits none.

    Returns a copy carrying ``notional_imputed``, ``notional_impute_factor``,
    ``notional_expected_reporting_only`` and ``notional_impute_reason``.
    ``notional`` itself is passed through untouched, because the pricing path
    reads it and the whole point of the separate column is that the two can be
    told apart afterwards.

    The fourth column is spelled that way on purpose. It **is**
    ``notional × multiplier``, which is the one vector this module must not hand
    to a pricer: ``risk`` and any repriced KRD are already built from the capped
    notional, so pricing off an inflated notional and then calling
    :func:`apply_to_signed_krd` applies the correction twice. A column named
    ``notional_expected`` sitting next to ``notional`` is one careless
    ``df[...]`` from doing exactly that; this one has to be typed deliberately.
    Use it to report a size, never to compute risk.

    Non-imputed rows carry ``NaN`` in the two float columns where the scalar
    :func:`impute` returns ``None`` -- a float column cannot hold ``None`` --
    so a consumer must test ``pd.isna`` here and ``is None`` there.
    :func:`apply_to_signed_krd` rejects both.

    When a tenor column is present a fifth column, ``notional_cell_tenor_mismatch``,
    reports the legs whose tenor puts them in a different band from the one their
    cap value names -- measured at **1,326 of 68,945 (1.92%)** on the flow tape,
    and they are *exactly* the legs the original per-tenor fit dropped. They are
    still imputed, off their own cap, because the cap is observed and the tenor
    band is only how the sub-cap population was partitioned. But a consumer who
    wants the calibration's own population back can filter on this column, so it
    is surfaced rather than left as a footnote.
    """
    out = legs.copy()
    dates = pd.to_datetime(out[as_of_date])
    vintages = np.where(dates < pd.Timestamp(CAP_SCHEDULE_SWITCH),
                        VINTAGE_V1, VINTAGE_V2)
    capped = out[is_capped].astype("boolean").fillna(False).to_numpy(dtype=bool)
    values = out[notional].to_numpy(dtype=float)

    # only the 3% of legs that are capped need a lookup, so the dict walk is
    # over those and not over the whole tape
    factors = np.full(len(out), np.nan)
    where = np.flatnonzero(capped)
    if len(where):
        factors[where] = [
            _BY_CAP[key].multiplier if key in _BY_CAP else np.nan
            for key in zip(vintages[where], values[where])
        ]

    matched = np.isfinite(factors)
    out["notional_imputed"] = matched
    out["notional_impute_factor"] = factors
    out["notional_expected_reporting_only"] = out[notional].astype(float) * factors
    out["notional_impute_reason"] = np.where(
        matched, REASON_IMPUTED,
        np.where(capped, REASON_CAP_UNRECOGNISED, REASON_NOT_CAPPED))

    if tenor_years is not None and tenor_years in out.columns:
        mismatch = pd.array([None] * len(out), dtype="boolean")
        tenors = out[tenor_years].to_numpy(dtype=float)
        for i in np.flatnonzero(matched):
            t = tenors[i]
            if not np.isfinite(t) or t < 0:
                continue
            mismatch[i] = bool(cap_for(t, dates.iloc[i]) != values[i])
        out["notional_cell_tenor_mismatch"] = mismatch
    return out


def apply_to_signed_krd(krd, factor: float | None):
    """Scale a **signed** key-rate profile by an imputation multiplier.

    The only sanctioned way to spend the multiplier, and it is spent here --
    after direction inference -- for a mechanical reason: ``risk`` and any
    repriced KRD are computed from the capped notional, so they are censored in
    the same proportion the notional is. Scaling notional first and then pricing
    applies the correction twice, once through the number and once through the
    pricing path.

    Direction is already in the sign, and a multiplier ≥ 1 cannot change it: a
    cap correction makes a position bigger, never smaller and never the other
    way round. A factor below 1 is therefore rejected rather than clipped.
    """
    if factor is None or not np.isfinite(factor) or factor < 1.0:
        raise ValueError(
            f"an imputation multiplier is >= 1 by construction, got {factor!r}; "
            "a leg with no imputation carries factor None and must not be scaled")
    f = float(factor)
    if isinstance(krd, Mapping):
        return {k: v * f for k, v in krd.items()}
    if isinstance(krd, pd.Series):
        return krd * f
    if isinstance(krd, np.ndarray):
        return krd * f
    if isinstance(krd, Sequence):
        return np.asarray(krd, dtype=float) * f
    raise TypeError(f"cannot scale a key-rate profile of type {type(krd).__name__}")


# ===========================================================================
# The fitter. Kept in the shipped module, not in scratch, because the
# calibration has to be reproducible from the tape by the code that uses it.
# ===========================================================================

_LOG2PI = float(np.log(2.0 * np.pi))


def _suffstats(log_x: np.ndarray, w: np.ndarray) -> tuple[float, float, float]:
    """(W, Σw·lnx, Σw·ln²x) -- makes every likelihood evaluation O(1).

    The tape arrives as (notional, count) pairs on a round-number lattice, so
    the weighted form is the primary one; the unweighted path is the same
    estimator with w = 1, pinned by test.
    """
    W = float(np.sum(w))
    return W, float(np.sum(w * log_x)), float(np.sum(w * log_x * log_x))


def _ln_negll(p, S, log_u, log_C, n_cap: float | None) -> float:
    """Negative log-likelihood of ``[u, C)`` observations, optionally censored.

    ``n_cap = None`` is the truncation-only likelihood (the estimator this
    module rejects, kept so the rejection is testable); a count is the censored
    one, which adds ``n_cap · log(S(C)/S(u))`` -- the prints known only to be
    somewhere above the cap.
    """
    W, S1, S2 = S
    mu, log_sigma = p[0], p[1]
    if (log_sigma < -3.0 or log_sigma > np.log(LN_SIGMA_MAX)
            or mu < log_u - LN_MU_SLACK or mu > log_C + 10.0):
        return 1e12
    sigma = np.exp(log_sigma)
    quad = (S2 - 2.0 * mu * S1 + mu * mu * W) / (sigma * sigma)
    base = -0.5 * quad - 0.5 * W * _LOG2PI - W * log_sigma - S1
    if n_cap is None:
        mass = float(ndtr((log_C - mu) / sigma) - ndtr((log_u - mu) / sigma))
        if mass <= 1e-300:
            return 1e12
        ll = base - W * np.log(mass)
    else:
        s_u = float(ndtr(-(log_u - mu) / sigma))
        s_C = float(ndtr(-(log_C - mu) / sigma))
        if s_u <= 1e-300 or s_C <= 1e-300:
            return 1e12
        ll = base - W * np.log(s_u) + n_cap * (np.log(s_C) - np.log(s_u))
    return -ll if np.isfinite(ll) else 1e12


def _ln_on_box_wall(mu: float, sigma: float, u: float, C: float) -> bool:
    """Did this fit land on a wall of the (mu, log sigma) box rather than inside?

    All four walls, not just sigma. The wall that bit on the shipped calibration
    was ``mu >= ln(u) - LN_MU_SLACK``, and a detector that only watched sigma
    reported those six cells clean *because* the undetected bound stopped the
    optimiser before sigma could reach its own threshold.
    """
    return bool(sigma > 0.98 * LN_SIGMA_MAX
                or sigma < np.exp(-3.0) * 1.02
                or mu < np.log(u) - LN_MU_SLACK + LN_BOX_TOL
                or mu > np.log(C) + 10.0 - LN_BOX_TOL)


def _ln_mle(x, w, u: float, C: float, n_cap: float | None, *,
            require_converged: bool) -> tuple[float, float, bool]:
    """(mu, sigma, converged). ``require_converged`` selects among the restarts.

    Measured over the 103 fits of the six-threshold sweep: for the **censored**
    likelihood, restricting the choice to converged runs costs at most 4.7e-10
    of negative log-likelihood (on values of order 1e5), so it is free and it
    is what ships -- an optimum that hit ``maxiter`` is not an optimum, and the
    module's own refit instructions warn that a censored MLE which has silently
    stopped converging still returns numbers. For the **truncation-only**
    likelihood it is not free: the best run is the non-converged one in 16 of
    103 fits, by up to 6.3e3 of negative log-likelihood, because on the
    degenerate ridge Nelder-Mead is still descending when ``maxiter`` bites.
    Discarding a materially better fit to satisfy a status flag would make the
    comparator worse, so that path keeps the best run and reports the flag
    instead (:attr:`CellFit.ln_truncated_converged`).
    """
    log_x, log_u, log_C = np.log(x), np.log(u), np.log(C)
    S = _suffstats(log_x, np.asarray(w, dtype=float))
    W, S1, S2 = S
    m0 = S1 / W
    s0 = float(np.sqrt(max(S2 / W - m0 * m0, 1e-6)))
    runs = []
    # A restart grid, not a single start: the censored likelihood is genuinely
    # multimodal in (mu, sigma) once the window is one decade wide, and several
    # fitted cells sit at mu far below ln(u) with a large sigma -- a power-law
    # mimic inside the window. Those are the cells a single start misses.
    for mu0 in (m0, m0 - 1.0, m0 - 3.0, log_u):
        for sigma0 in (s0, 2 * s0, 1.0, 2.5):
            runs.append(optimize.minimize(
                _ln_negll, [mu0, np.log(sigma0)],
                args=(S, log_u, log_C, n_cap), method="Nelder-Mead",
                options={"maxiter": 4000, "xatol": 1e-9, "fatol": 1e-9}))
    pool = [r for r in runs if r.success] if require_converged else runs
    if not pool:
        raise RuntimeError(
            f"none of the {len(runs)} restarts of the lognormal MLE converged "
            f"(best status: {min(runs, key=lambda r: r.fun).message!r}); the fit "
            "would be whatever Nelder-Mead happened to be standing on")
    best = min(pool, key=lambda r: r.fun)
    return float(best.x[0]), float(np.exp(best.x[1])), bool(best.success)


def lognormal_censored_mle(x, w, u: float, C: float, n_cap: float) -> tuple[float, float]:
    """(mu, sigma) from the sub-cap observations PLUS the observed capped count.

    The shipped estimator. The capped count is data -- it is the one thing the
    cap does not hide -- and using it is what keeps the fit's implied tail mass
    from disagreeing with the tape's. Raises rather than returning a number when
    no restart converged.
    """
    return _ln_mle(x, w, u, C, float(n_cap), require_converged=True)[:2]


def lognormal_truncated_mle(x, w, u: float, C: float) -> tuple[float, float]:
    """(mu, sigma) from the sub-cap observations only. **Not** what ships.

    Kept because "the censored fit is better" is a claim, and a claim needs the
    rejected estimator available to test against: measured -72% to +2400% error
    on the capped count. Unlike the censored fit this one accepts a restart that
    stopped on ``maxiter`` -- see :func:`_ln_mle` for the measurement that says
    it must.
    """
    return _ln_mle(x, w, u, C, None, require_converged=False)[:2]


def lognormal_cdf_truncated(q, mu: float, sigma: float, u: float, C: float):
    """P(X <= q | u <= X < C). The cdf the KS statistic is taken against."""
    q = np.asarray(q, dtype=float)
    F = ndtr((np.log(q) - mu) / sigma)
    F_u = ndtr((np.log(u) - mu) / sigma)
    F_C = ndtr((np.log(C) - mu) / sigma)
    return (F - F_u) / (F_C - F_u)


def lognormal_tail_ratio(mu: float, sigma: float, u: float, C: float) -> float:
    """S(C)/S(u): the share of the fitted tail that the cap swallows."""
    return float(ndtr(-(np.log(C) - mu) / sigma) / ndtr(-(np.log(u) - mu) / sigma))


def lognormal_mean_above(mu: float, sigma: float, C: float) -> float:
    """E[X | X > C]. The estimand; ``multiplier = this / C``."""
    z = (np.log(C) - mu) / sigma
    sf = float(ndtr(-z))
    if sf <= 0:
        return float("nan")
    return float(np.exp(mu + 0.5 * sigma * sigma) * ndtr(-(z - sigma)) / sf)


def pareto_truncated_mle(x, w, u: float, C: float) -> float:
    """alpha on ``[u, C)``, carrying the (1 - (u/C)^alpha) truncation term.

    Without that term this is the naive Hill estimator, which reads the tail as
    thinner than it is because it treats the cap-shaped hole as an absence of
    large trades. Measured bias in the self-test: +53%/+23%/+6% at
    alpha = 0.8/1.2/1.8.
    """
    w = np.asarray(w, dtype=float)
    W = float(np.sum(w))
    rho = np.log(C / u)
    m = float(np.sum(w * np.log(np.asarray(x, dtype=float) / u)) / W)

    def score(a: float) -> float:
        if abs(a) < 1e-9:
            return rho / 2.0 - m
        return 1.0 / a - rho / np.expm1(a * rho) - m

    lo, hi = -5.0, 200.0
    if score(lo) * score(hi) > 0:
        return float("nan")
    return float(optimize.brentq(score, lo, hi, xtol=1e-10))


def pareto_censored_mle(x, w, u: float, C: float, n_cap: float) -> float:
    """alpha from the sub-cap observations plus the mass at/above C.

    Closed form ``alpha = W / (W·m + n_cap·ln(C/u))``: the Hill estimator with
    each censored print contributing its known log-excess ``ln(C/u)`` and no
    more, which is exactly what is known about it.
    """
    w = np.asarray(w, dtype=float)
    W = float(np.sum(w))
    rho = np.log(C / u)
    m = float(np.sum(w * np.log(np.asarray(x, dtype=float) / u)) / W)
    denom = W * m + float(n_cap) * rho
    return float(W / denom) if denom > 0 else float("nan")


def pareto_cdf_truncated(q, alpha: float, u: float, C: float):
    q = np.asarray(q, dtype=float)
    return (1.0 - (u / q) ** alpha) / (1.0 - (u / C) ** alpha)


def pareto_tail_ratio(alpha: float, u: float, C: float) -> float:
    return float((u / C) ** alpha)


def pareto_mean_above(alpha: float, C: float) -> float:
    """E[X | X > C] for a Pareto tail -- ``inf`` when alpha <= 1.

    Returning ``inf`` rather than a large number is the whole discipline: at
    u = C/10 ten of eighteen cells came back below 1, and a fitter that quietly
    emitted ``alpha·C/(alpha-1)`` with a negative denominator would have
    produced *negative* imputed sizes and a plausible-looking table.
    """
    if not np.isfinite(alpha) or alpha <= 1.0:
        return float("inf")
    return float(alpha * C / (alpha - 1.0))


def predicted_capped_count(n_sub: float, tail_ratio: float) -> float:
    """Capped prints the fit implies, given the sub-cap count. ``n·p/(1-p)``.

    The censored fit's own falsification test: it is fitted *using* the observed
    count, so a large disagreement here means the family is wrong, not that the
    optimiser wandered.
    """
    if not 0.0 < tail_ratio < 1.0:
        return float("nan")
    return float(n_sub) * tail_ratio / (1.0 - tail_ratio)


def weighted_ks(x, w, cdf) -> float:
    """Weighted two-sided KS against a continuous cdf.

    Reported, never used to switch families row by row. Absolute KS is 0.07-0.28
    for both the lognormal and the Pareto, because notional is rounded onto a
    round-number lattice and no continuous law fits a lattice well; the
    statistic is only informative as a *comparison* between the two.
    """
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    if not len(x) or not w.sum() > 0:
        # otherwise this is 0/0: two RuntimeWarnings and a nan that reads as a
        # statistic wherever it is printed.
        raise ValueError("weighted_ks needs at least one point of positive weight")
    order = np.argsort(x)
    xs, ws = x[order], w[order]
    upper = np.cumsum(ws) / ws.sum()
    lower = upper - ws / ws.sum()
    F = np.asarray(cdf(xs), dtype=float)
    return float(max(np.max(np.abs(upper - F)), np.max(np.abs(F - lower))))


@dataclasses.dataclass(frozen=True)
class CellFit:
    """Both families, both estimators, for one cell. The refit's output row."""

    u: float
    cap: float
    n_sub: float
    n_cap: float
    ln_mu_censored: float
    ln_sigma_censored: float
    ln_mu_truncated: float
    ln_sigma_truncated: float
    pareto_alpha_censored: float
    pareto_alpha_truncated: float
    mean_above_lognormal: float
    mean_above_pareto: float
    predicted_n_cap_censored: float
    predicted_n_cap_truncated: float
    #: both taken against the TRUNCATION-only fits, which is not a detail: KS is
    #: a statement about the shape inside ``[u, C)`` and the truncation-only MLE
    #: is the maximiser of exactly that in-window likelihood, while the censored
    #: one also pays for the mass above C. And the censored parameters cannot
    #: carry a KS at all in the degenerate cells -- with mu ~ -29 and sigma = 6
    #: the whole window sits 8+ sigma into the tail, ``F(C) - F(u)`` underflows
    #: to zero, and the statistic is 0/0: measured ``nan`` in exactly the three
    #: cells whose censored fit is furthest onto the wall. Where it is
    #: computable it moves things by 0.003-0.027 and flips no conclusion
    #: (lognormal 8 / Pareto 6 of the 15 evaluable, worst 0.222).
    ks_lognormal: float
    ks_pareto: float
    #: the CENSORED fit -- the one that produces the multiplier -- sits on a box
    #: wall, so its estimate is bound-determined rather than a maximum.
    ln_degenerate: bool
    #: same for the truncation-only comparator, which only feeds ``ks_lognormal``
    #: and the rejected-estimator diagnostic. Carried separately because it pins
    #: in cells where the shipped fit is perfectly interior (V2 46d-3m), and one
    #: flag covering both would overstate how much of the table is on a wall.
    ln_degenerate_truncated: bool
    #: whether the truncation-only optimum came from a converged restart; the
    #: censored one raises instead, see :func:`_ln_mle`.
    ln_truncated_converged: bool

    @property
    def multiplier(self) -> float:
        return self.mean_above_lognormal / self.cap

    @property
    def capped_count_error(self) -> float:
        """predicted / observed - 1. ``nan`` when nothing was censored.

        ``n_cap = 0`` is refused upstream by :func:`fit_cell`; this stays
        divide-safe anyway, because a diagnostic that raises is a diagnostic
        nobody can read.
        """
        if not self.n_cap:
            return float("nan")
        return self.predicted_n_cap_censored / self.n_cap - 1.0

    @property
    def pareto_mean_exists(self) -> bool:
        return bool(np.isfinite(self.pareto_alpha_censored)
                    and self.pareto_alpha_censored > 1.0)


def fit_cell(x, w, u: float, C: float, n_cap: float) -> CellFit | None:
    """Fit one (band × vintage) cell. ``None`` when the tail is too thin to fit.

    ``x``/``w`` are the sub-cap notionals and their counts; only ``[u, C)`` is
    used, and ``n_cap`` is the number of prints sitting exactly on the cap.

    ``n_cap <= 0`` is refused rather than fitted. With no mass above C the
    "censored" likelihood *is* the truncation-only one, and the cell would come
    back with a confident multiplier from the estimator this module rejects,
    plus a ``capped_count_error`` of ``nan`` to check it with. It happens for a
    real reason -- if every capped print in the cell sits a dollar off C, the
    cap value assumed for the cell is wrong -- so it is a stop, not a warning.
    """
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    if not float(n_cap) > 0:
        raise ValueError(
            f"fit_cell needs the censored count and got n_cap={n_cap!r}; with no "
            "mass above the cap this is the truncation-only estimator, which "
            "this module rejects -- call lognormal_truncated_mle explicitly if "
            "that is what you want, and check the cell's cap value first")
    keep = (x >= u) & (x < C)
    x, w = x[keep], w[keep]
    W = float(w.sum())
    if W < MIN_TAIL_WEIGHT or len(x) < MIN_TAIL_POINTS:
        return None

    mu_c, sigma_c = lognormal_censored_mle(x, w, u, C, n_cap)
    mu_t, sigma_t, conv_t = _ln_mle(x, w, u, C, None, require_converged=False)
    alpha_c = pareto_censored_mle(x, w, u, C, n_cap)
    alpha_t = pareto_truncated_mle(x, w, u, C)

    mean_ln = lognormal_mean_above(mu_c, sigma_c, C)
    if not np.isfinite(mean_ln):
        # ndtr(-z) underflows to 0 once the fit runs far enough out; the
        # estimand is then unevaluable and the multiplier would be nan. A nan
        # multiplier reads as a fit in every table it lands in.
        raise ValueError(
            f"the censored lognormal fit (mu={mu_c!r}, sigma={sigma_c!r}) has no "
            f"evaluable E[X | X > {C!r}]")

    return CellFit(
        u=u, cap=C, n_sub=W, n_cap=float(n_cap),
        ln_mu_censored=mu_c, ln_sigma_censored=sigma_c,
        ln_mu_truncated=mu_t, ln_sigma_truncated=sigma_t,
        pareto_alpha_censored=alpha_c, pareto_alpha_truncated=alpha_t,
        mean_above_lognormal=mean_ln,
        mean_above_pareto=pareto_mean_above(alpha_c, C),
        predicted_n_cap_censored=predicted_capped_count(
            W, lognormal_tail_ratio(mu_c, sigma_c, u, C)),
        predicted_n_cap_truncated=predicted_capped_count(
            W, lognormal_tail_ratio(mu_t, sigma_t, u, C)),
        ks_lognormal=weighted_ks(
            x, w, lambda q: lognormal_cdf_truncated(q, mu_t, sigma_t, u, C)),
        ks_pareto=weighted_ks(x, w, lambda q: pareto_cdf_truncated(q, alpha_t, u, C)),
        ln_degenerate=_ln_on_box_wall(mu_c, sigma_c, u, C),
        ln_degenerate_truncated=_ln_on_box_wall(mu_t, sigma_t, u, C),
        ln_truncated_converged=conv_t,
    )


def fit_frequency_table(freq: pd.DataFrame, *,
                        threshold_divisor: float = THRESHOLD_DIVISOR,
                        ) -> dict[tuple[str, float], CellFit]:
    """Refit every cell from a (cell × notional) frequency table.

    ``freq`` needs ``vintage``, ``lo``, ``cap``, ``notional``, ``is_capped``,
    ``n``. This is how :data:`CAP_BANDS` was produced and how it is regenerated
    when the tape extends: the shipped constants are a snapshot of this function
    over 2024-03-01..2026-08-07, not a separate model.

    Keyed by ``(vintage, lo)`` because a cell is a band in a vintage, and caps
    repeat across vintages.

    **A missing key is not "no imputation", and it must not be discoverable only
    by counting the dict.** Cells with no capped prints at all, and cells whose
    ``[u, C)`` window falls below :data:`MIN_TAIL_WEIGHT`, are skipped -- with a
    warning naming them, because a partial refit of 16 cells is otherwise
    indistinguishable from a complete one of 18. A table that yields nothing at
    all raises: that is never a calibration.

    Before trusting a refit, re-run the fitter's own validation --
    ``pytest tests/test_dealer_direction_imputation.py`` -- which recovers known
    parameters from simulated censored samples and covers every function on this
    path, the two cdfs and the KS statistic included. The whole file, with no
    ``-k``: it is 20 seconds and offline, and a selector is how the previous
    version of this instruction ended up naming two tests that touch nothing on
    this path. A censored MLE that has silently stopped converging still returns
    numbers, and they will look like a plausible new calibration.

    A refit also re-pins the frozen table, and those tests will then fail on the
    numbers rather than on the code -- ``scratch/imp_fix01_sweep.py`` regenerates
    the :data:`CAP_BANDS` literal and every headline constant from a frequency
    cache, and validates itself against the shipped table before it is believed
    at new inputs.
    """
    required = {"vintage", "lo", "cap", "notional", "is_capped", "n"}
    missing = required - set(freq.columns)
    if missing:
        raise ValueError(f"frequency table is missing {sorted(missing)}")

    fits: dict[tuple[str, float], CellFit] = {}
    skipped: list[str] = []
    for (vintage, lo), g in freq.groupby(["vintage", "lo"], sort=True):
        C = float(g["cap"].iloc[0])
        u = C / threshold_divisor
        capped = g[g["is_capped"].astype(bool)]
        # capped prints not sitting exactly on C are band-edge noise; the cap is
        # a single discrete value per cell (p10 = p50 = p90 = C), so anything
        # else in here came from a neighbouring band's tenor fuzz.
        n_cap = float(capped.loc[capped["notional"].astype(float) == C, "n"].sum())
        sub = g[~g["is_capped"].astype(bool)]
        if not n_cap:
            # nothing censored: no estimand. Distinguish the two ways that
            # happens -- an uncensored cell is ordinary, a cell whose capped
            # prints all sit OFF its cap means the cap value is wrong, and
            # fit_cell is the one that refuses that.
            if capped["n"].sum():
                fit_cell(sub["notional"].to_numpy(dtype=float),
                         sub["n"].to_numpy(dtype=float), u, C, n_cap)
            skipped.append(f"{vintage} lo={lo} (no capped prints at C={C:g})")
            continue
        fit = fit_cell(sub["notional"].to_numpy(dtype=float),
                       sub["n"].to_numpy(dtype=float), u, C, n_cap)
        if fit is None:
            skipped.append(f"{vintage} lo={lo} (tail below MIN_TAIL_WEIGHT"
                           f"/MIN_TAIL_POINTS at u={u:g})")
            continue
        fits[(str(vintage), float(lo))] = fit
    if skipped:
        warnings.warn(
            f"fit_frequency_table fitted {len(fits)} of {len(fits) + len(skipped)} "
            f"cells; NOT fitted: {'; '.join(skipped)}. An absent key means no "
            "estimate, never no imputation -- those legs are still capped.",
            RuntimeWarning, stacklevel=2)
    if not fits:
        raise ValueError(
            "no cell in this frequency table could be fitted, so there is no "
            "calibration to return; an empty dict here would look like a "
            "complete refit of a tape with nothing in it")
    return fits
