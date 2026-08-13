"""Capped-notional imputation: the largest prints are the ones whose size is missing.

Part 43 Â§43.4(h) publishes a block trade's notional at a **cap** rather than at
its true size, so the tape's most informative prints -- the ones that move a
dealer's book -- are exactly the ones whose notional cannot be read. 68,946 of
2,289,646 flow legs (3.01%) are capped (`is_capped` == `is_notional_capped`,
exactly, on every row), and they carry ~14% of the tape's DV01 *at the cap
value*, i.e. before any correction (14.7% measured on the tape's own
``sum(|risk|)``, 14.2% on the ``notionalÂ·tenorÂ·1e-4`` proxy used below -- the
proxy is the one every share in this module is computed against, and the two
agreeing to half a point is itself a check).

This module turns that into a number and a flag. It does not turn it into a
silently bigger notional.

WHAT WAS MEASURED (probes in ``scratch/partB_*.py``, recorded as LEDGER F-7/F-17)
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
  count reproduces the observed one to **Â±19% in every cell**. This is what
  ships.

Family: lognormal, threshold ``u = C/4``.

**The family is not chosen by fit quality, and pretending otherwise would hide
the biggest uncertainty here.** KS favours the lognormal in 13 of 18 cells at
``u = C/10``, but at the shipped ``u = C/4`` it splits **6 lognormal / 10 Pareto
/ 2 exact ties**, with the largest gap between the two statistics being 0.020
against absolute KS of 0.07-0.28 -- i.e. neither family fits, and they fail
about equally. AIC cannot discriminate over a single decade at all (gap of 11 on
a log-likelihood of 3.7e6 in the self-test). What actually decides it is that
the Pareto has **no estimand** in 2 of 18 cells at this threshold (alpha <= 1,
mean undefined) and in 10 of 18 at ``u = C/10``, while the censored lognormal
returns a finite number whose implied capped count matches the observed one.
Choosing the family that can answer is a choice, not a measurement, so the
quoted sensitivity band is *within-family* and family risk sits outside it.

THE HEADLINE
------------

Multipliers ``E[N | N > C] / C`` run 1.64-3.95 by cell, and the share of the
tape's DV01 that is **imputed rather than observed** is:

===========  ======================  =================
bucket       imputed DV01 share      across thresholds
===========  ======================  =================
<=2y         21.8%                   16.3% - 21.8%
2-10y        16.6%                    9.5% - 16.6%
10-30y        9.2%                    9.2% - 17.1%
>30y          8.2%                    3.6% -  8.2%
**overall**  **15.4%**               **10.6% - 16.0%**
===========  ======================  =================

Applied leg by leg over the production population (68,945 capped legs, keyed on
notional) rather than over the 67,619 the fit was calibrated on, the overall
figure is **15.65%** -- the two populations differ by 1.96% and the headline by
0.25pp, which is the right order for a coverage difference and a useful check
that neither number is a coding accident. Notional shares are much larger
(27.2% overall) and much less relevant: a $17bn three-week print is a rounding
error in duration terms.

A cross-check that uses none of the likelihood: capped prints carry **14.2%** of
the tape's DV01 proxy at the cap value, and for a flat multiplier k the imputed
share is just ``(k-1)Â·0.142 / (1 + (k-1)Â·0.142)`` -- 12.4% at k = 2.0, 13.5% at
k = 2.1. The fit's DV01-weighted effective multiplier is 2.31, which that formula
turns into 15.65%, exactly the leg-by-leg figure. So the headline is arithmetic
on two numbers a reader can check in one query, and the tail model only supplies
the k.

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

This is the difference between a caveat and a bias. A ~15% DV01 uplift spread
evenly over both sides widens the ladder; a ~15% uplift concentrated on one side
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

``is_block`` Ã— direction settles how much these labels can be trusted at all: the
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
and there is deliberately no notional-scaling counterpart.

The imputed value never overwrites anything either: :func:`impute` returns a
separate expected notional plus ``notional_imputed`` / ``notional_impute_factor``
for :class:`~.types.Provenance`, so a consumer can drop every imputed row and
get the observed-only ladder back.

The fitter is validated against simulated data whose parameters are known before
it is allowed near the tape -- ``tests/test_dealer_direction_imputation.py``,
sections 1-2. A censored MLE that is quietly wrong still returns a number.
"""
from __future__ import annotations

import bisect
import dataclasses
import datetime
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
#: to nonsense, which is what ``ln_degenerate`` reports.
LN_SIGMA_MAX = 6.0
LN_MU_SLACK = 30.0


@dataclasses.dataclass(frozen=True)
class CapBand:
    """One (tenor band Ã— schedule vintage) cell, with its fitted tail.

    ``lo``/``hi`` are the **empirical** edges the fit was run on, kept verbatim
    so a refit reproduces the shipped numbers. They are not the lookup edges:
    the merge that produced them dropped bins with n < 25, leaving a hole at
    V1 10.5-10.75y and nothing capped past 41y, and a lookup with a hole in it
    returns nothing on a live print. :func:`band_for_tenor` therefore runs each
    band from its own ``lo`` to the *next* band's ``lo``, the last to infinity.
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
    ks_lognormal: float          # both families are carried: at this threshold
    ks_pareto: float             # they are near-indistinguishable, see the docstring
    n_capped: int                # capped prints the fit was calibrated on

    @property
    def tail_mean_exists(self) -> bool:
        """Whether the *Pareto* mean exists. See the module docstring."""
        return bool(self.tail_index > 1.0)

    @property
    def expected_notional(self) -> float:
        return self.multiplier * self.cap


#: The nine bands Ã— two vintages, with the shipped lognormal censored fit at
#: u = C/4. Generated from ``scratch/partB_final_imputation_Cdiv4.csv`` rather
#: than typed -- 18 Ã— 8 hand-copied numbers is how a calibration acquires a typo
#: no test can see. The multiplier is re-derivable from (ln_mu, ln_sigma, cap),
#: and the test suite re-derives it.
CAP_BANDS: tuple[CapBand, ...] = (
    CapBand("V1", 0.0, 0.12, 6400000000.0, "<=46d",
            ln_mu=21.67391011775769, ln_sigma=1.137945794759632,
            multiplier=2.2980866817521064, tail_index=0.7550953662487064,
            capped_count_error=-0.0030149063436446,
            ks_lognormal=0.1329942151934542, ks_pareto=0.1195802403106219,
            n_capped=1411),
    CapBand("V1", 0.12, 0.3, 2100000000.0, "46d-3m",
            ln_mu=21.373393800030637, ln_sigma=0.9127106834118958,
            multiplier=2.381485662172644, tail_index=0.4645830791459552,
            capped_count_error=0.0367490034089075,
            ks_lognormal=0.1520208977480317, ks_pareto=0.150298847716689,
            n_capped=3984),
    CapBand("V1", 0.3, 0.54, 1200000000.0, "3m-6m",
            ln_mu=-10.480706967087528, ln_sigma=4.848816514389658,
            multiplier=3.2377425878991244, tail_index=1.3281950998136864,
            capped_count_error=-0.0078588887966773,
            ks_lognormal=0.1243862520458265, ks_pareto=0.1243862520458265,
            n_capped=229),
    CapBand("V1", 0.54, 1.04, 1100000000.0, "6m-1y",
            ln_mu=2.4104131959100323, ln_sigma=3.77969017016506,
            multiplier=3.166839233056532, tail_index=1.2790758042247652,
            capped_count_error=0.0029053772193325,
            ks_lognormal=0.1021386960433519, ks_pareto=0.1021167360859103,
            n_capped=959),
    CapBand("V1", 1.04, 2.25, 460000000.0, "1y-2y",
            ln_mu=12.929935375442676, ln_sigma=2.5387806185354767,
            multiplier=3.237850817848236, tail_index=1.0846980309845464,
            capped_count_error=-0.003560864483304,
            ks_lognormal=0.0942612221293912, ks_pareto=0.089425179042007,
            n_capped=4569),
    CapBand("V1", 2.25, 5.25, 240000000.0, "2y-5y",
            ln_mu=18.264477128997147, ln_sigma=0.8979268449241443,
            multiplier=1.7066855964459755, tail_index=1.032704763300416,
            capped_count_error=-0.0764127740189443,
            ks_lognormal=0.133296314305011, ks_pareto=0.1248884682893222,
            n_capped=10587),
    CapBand("V1", 5.25, 10.5, 170000000.0, "5y-10y",
            ln_mu=-12.434985364219369, ln_sigma=5.081854081526698,
            multiplier=3.953688569779932, tail_index=1.212393511465417,
            capped_count_error=-0.0155758565293488,
            ks_lognormal=0.106496918474653, ks_pareto=0.1136192098866631,
            n_capped=9484),
    CapBand("V1", 10.75, 31.0, 120000000.0, "10y-30y",
            ln_mu=16.78364106282918, ln_sigma=1.2289181834921472,
            multiplier=1.9925855972069413, tail_index=1.098841755844256,
            capped_count_error=-0.0160487851038184,
            ks_lognormal=0.0697956059842056, ks_pareto=0.0788054968339411,
            n_capped=4010),
    CapBand("V1", 31.0, 41.0, 75000000.0, ">30y",
            ln_mu=16.49878270359823, ln_sigma=0.992932951230848,
            multiplier=1.6445688942026644, tail_index=1.3275939250309252,
            capped_count_error=-0.0655013267732614,
            ks_lognormal=0.1657522161983033, ks_pareto=0.1593645918782284,
            n_capped=60),
    CapBand("V2", 0.0, 0.12, 17000000000.0, "<=46d",
            ln_mu=-7.82981518002242, ln_sigma=4.62119751428005,
            multiplier=2.745669361490126, tail_index=1.4597407419545152,
            capped_count_error=-0.0948496817948088,
            ks_lognormal=0.2756435845220786, ks_pareto=0.2753833579380677,
            n_capped=1875),
    CapBand("V2", 0.12, 0.3, 7500000000.0, "46d-3m",
            ln_mu=-8.648125065283327, ln_sigma=5.027861576852723,
            multiplier=3.7628812110810657, tail_index=1.238831001927781,
            capped_count_error=0.0996369644756467,
            ks_lognormal=0.2200719135768759, ks_pareto=0.2195769093670117,
            n_capped=2616),
    CapBand("V2", 0.3, 0.54, 2000000000.0, "3m-6m",
            ln_mu=-9.969881343551842, ln_sigma=4.655530961699787,
            multiplier=2.8101158756591085, tail_index=1.438748075353826,
            capped_count_error=-0.1882068205912145,
            ks_lognormal=0.2627737226277372, ks_pareto=0.2627737226277372,
            n_capped=603),
    CapBand("V2", 0.54, 1.04, 1700000000.0, "6m-1y",
            ln_mu=12.674357249688168, ln_sigma=2.351091793210915,
            multiplier=2.200633428982075, tail_index=1.4984419454951228,
            capped_count_error=-0.0157270019071033,
            ks_lognormal=0.1324182777401722, ks_pareto=0.1418425230992165,
            n_capped=1852),
    CapBand("V2", 1.04, 2.25, 1100000000.0, "1y-2y",
            ln_mu=17.047362332517515, ln_sigma=1.5688914206365658,
            multiplier=1.9614262516420764, tail_index=1.41339169822191,
            capped_count_error=-0.0145943672068897,
            ks_lognormal=0.0980128532184262, ks_pareto=0.0982345998096144,
            n_capped=4246),
    CapBand("V2", 2.25, 5.25, 650000000.0, "2y-5y",
            ln_mu=17.812647974918, ln_sigma=1.16954914037899,
            multiplier=1.6692104963931502, tail_index=1.531070698605684,
            capped_count_error=-0.046131073040445,
            ks_lognormal=0.0766698054380321, ks_pareto=0.0944744258706613,
            n_capped=7623),
    CapBand("V2", 5.25, 11.0, 470000000.0, "5y-10y",
            ln_mu=-11.418051107910458, ln_sigma=4.5327185318658,
            multiplier=2.59270396612489, tail_index=1.5146517606744674,
            capped_count_error=0.0090549986607884,
            ks_lognormal=0.1308897622057124, ks_pareto=0.130725867107334,
            n_capped=8472),
    CapBand("V2", 11.0, 31.0, 250000000.0, "10y-30y",
            ln_mu=17.461912846755226, ln_sigma=1.092603400209808,
            multiplier=1.723388554360291, tail_index=1.31727959135829,
            capped_count_error=-0.0481327937368101,
            ks_lognormal=0.0880559959844087, ks_pareto=0.0717410691535581,
            n_capped=4996),
    CapBand("V2", 31.0, 45.0, 160000000.0, ">30y",
            ln_mu=9.059939434754272, ln_sigma=2.226704041493988,
            multiplier=1.8192484132974656, tail_index=1.887891616104556,
            capped_count_error=-0.0676506470602682,
            ks_lognormal=0.2122493772233202, ks_pareto=0.2319897445180139,
            n_capped=43),
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

#: Share of the tape's DV01 proxy (Î£ notionalÂ·tenorÂ·1e-4) that is imputed rather
#: than observed, at the shipped u = C/4. A proxy and not a repriced KRD on
#: purpose: it is model-free given the notional, so it does not inherit the
#: pricing path's own errors on top of the imputation's.
IMPUTED_DV01_SHARE = 0.1541
IMPUTED_NOTIONAL_SHARE = 0.2721

#: Same, per coarse Part 43 tenor bucket: (imputed notional share, imputed DV01
#: share). The <=2y bucket dominates the notional number and not the DV01 one --
#: a $17bn 3-week print is a rounding error in duration terms.
IMPUTED_SHARE_BY_BUCKET: dict[str, tuple[float, float]] = {
    "<=2y": (0.3034, 0.2177),
    "2-10y": (0.1495, 0.1659),
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
    "<=2y": (0.1633, 0.2177),
    "2-10y": (0.0949, 0.1659),
    "10-30y": (0.0917, 0.1714),
    ">30y": (0.0363, 0.0818),
}

#: Range across the six thresholds tried (u = C/2, C/4, C/10, C/20, cell-q0.90,
#: cell-q0.95). **Within-lognormal-family only.** Absolute KS is 0.0698-0.2756
#: for the lognormal and 0.0717-0.2754 for the Pareto, so neither family fits
#: well and family risk sits OUTSIDE this band, not inside it. Individual cells
#: swing far more than the aggregate (V1 5y-10y moves 1.8x-4.0x); the aggregate
#: is the number to quote.
SENSITIVITY_DV01_SHARE = (0.1058, 0.1603)
SENSITIVITY_NOTIONAL_SHARE = (0.1634, 0.2721)

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
    """Which cap schedule was in force on this day."""
    return VINTAGE_V1 if _as_date(as_of_date) < CAP_SCHEDULE_SWITCH else VINTAGE_V2


def bands_for_vintage(vintage: str) -> tuple[CapBand, ...]:
    try:
        return _BANDS_BY_VINTAGE[vintage]
    except KeyError:
        raise ValueError(f"unknown cap schedule vintage {vintage!r}") from None


def band_for_tenor(tenor_years: float, as_of_date) -> CapBand:
    """The band a tenor falls in. Total: every non-negative tenor has one."""
    if not np.isfinite(tenor_years) or tenor_years < 0:
        raise ValueError(f"tenor_years must be a non-negative number, got {tenor_years!r}")
    vintage = vintage_for(as_of_date)
    i = bisect.bisect_right(_LO_EDGES[vintage], float(tenor_years)) - 1
    return _BANDS_BY_VINTAGE[vintage][max(i, 0)]


def cap_for(tenor_years: float, as_of_date) -> float:
    """The Â§43.4 cap that applied to this tenor on this day."""
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
    #: ``factor Ã— printed notional``, in its own field. The consumer decides.
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

    ``expected = multiplier Ã— printed notional`` rather than the cell's
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
    ``notional_expected`` and ``notional_impute_reason``. ``notional`` itself is
    passed through untouched, because the pricing path reads it and the whole
    point of the separate column is that the two can be told apart afterwards.

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
    out["notional_expected"] = out[notional].astype(float) * factors
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

    Direction is already in the sign, and a multiplier â‰¥ 1 cannot change it: a
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
    """(W, Î£wÂ·lnx, Î£wÂ·lnÂ²x) -- makes every likelihood evaluation O(1).

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
    one, which adds ``n_cap Â· log(S(C)/S(u))`` -- the prints known only to be
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


def _ln_mle(x, w, u: float, C: float, n_cap: float | None) -> tuple[float, float]:
    log_x, log_u, log_C = np.log(x), np.log(u), np.log(C)
    S = _suffstats(log_x, np.asarray(w, dtype=float))
    W, S1, S2 = S
    m0 = S1 / W
    s0 = float(np.sqrt(max(S2 / W - m0 * m0, 1e-6)))
    best = None
    # A restart grid, not a single start: the censored likelihood is genuinely
    # multimodal in (mu, sigma) once the window is one decade wide, and several
    # fitted cells sit at mu far below ln(u) with a large sigma -- a power-law
    # mimic inside the window. Those are the cells a single start misses.
    for mu0 in (m0, m0 - 1.0, m0 - 3.0, log_u):
        for sigma0 in (s0, 2 * s0, 1.0, 2.5):
            r = optimize.minimize(_ln_negll, [mu0, np.log(sigma0)],
                                  args=(S, log_u, log_C, n_cap),
                                  method="Nelder-Mead",
                                  options={"maxiter": 4000, "xatol": 1e-9,
                                           "fatol": 1e-9})
            if best is None or r.fun < best.fun:
                best = r
    return float(best.x[0]), float(np.exp(best.x[1]))


def lognormal_censored_mle(x, w, u: float, C: float, n_cap: float) -> tuple[float, float]:
    """(mu, sigma) from the sub-cap observations PLUS the observed capped count.

    The shipped estimator. The capped count is data -- it is the one thing the
    cap does not hide -- and using it is what keeps the fit's implied tail mass
    from disagreeing with the tape's.
    """
    return _ln_mle(x, w, u, C, float(n_cap))


def lognormal_truncated_mle(x, w, u: float, C: float) -> tuple[float, float]:
    """(mu, sigma) from the sub-cap observations only. **Not** what ships.

    Kept because "the censored fit is better" is a claim, and a claim needs the
    rejected estimator available to test against: measured -72% to +2400% error
    on the capped count.
    """
    return _ln_mle(x, w, u, C, None)


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

    Closed form ``alpha = W / (WÂ·m + n_capÂ·ln(C/u))``: the Hill estimator with
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
    emitted ``alphaÂ·C/(alpha-1)`` with a negative denominator would have
    produced *negative* imputed sizes and a plausible-looking table.
    """
    if not np.isfinite(alpha) or alpha <= 1.0:
        return float("inf")
    return float(alpha * C / (alpha - 1.0))


def predicted_capped_count(n_sub: float, tail_ratio: float) -> float:
    """Capped prints the fit implies, given the sub-cap count. ``nÂ·p/(1-p)``.

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
    ks_lognormal: float
    ks_pareto: float
    ln_degenerate: bool

    @property
    def multiplier(self) -> float:
        return self.mean_above_lognormal / self.cap

    @property
    def capped_count_error(self) -> float:
        return self.predicted_n_cap_censored / self.n_cap - 1.0

    @property
    def pareto_mean_exists(self) -> bool:
        return bool(np.isfinite(self.pareto_alpha_censored)
                    and self.pareto_alpha_censored > 1.0)


def fit_cell(x, w, u: float, C: float, n_cap: float) -> CellFit | None:
    """Fit one (band Ã— vintage) cell. ``None`` when the tail is too thin to fit.

    ``x``/``w`` are the sub-cap notionals and their counts; only ``[u, C)`` is
    used, and ``n_cap`` is the number of prints sitting exactly on the cap.
    """
    x = np.asarray(x, dtype=float)
    w = np.asarray(w, dtype=float)
    keep = (x >= u) & (x < C)
    x, w = x[keep], w[keep]
    W = float(w.sum())
    if W < MIN_TAIL_WEIGHT or len(x) < MIN_TAIL_POINTS:
        return None

    mu_c, sigma_c = lognormal_censored_mle(x, w, u, C, n_cap)
    mu_t, sigma_t = lognormal_truncated_mle(x, w, u, C)
    alpha_c = pareto_censored_mle(x, w, u, C, n_cap)
    alpha_t = pareto_truncated_mle(x, w, u, C)

    return CellFit(
        u=u, cap=C, n_sub=W, n_cap=float(n_cap),
        ln_mu_censored=mu_c, ln_sigma_censored=sigma_c,
        ln_mu_truncated=mu_t, ln_sigma_truncated=sigma_t,
        pareto_alpha_censored=alpha_c, pareto_alpha_truncated=alpha_t,
        mean_above_lognormal=lognormal_mean_above(mu_c, sigma_c, C),
        mean_above_pareto=pareto_mean_above(alpha_c, C),
        predicted_n_cap_censored=predicted_capped_count(
            W, lognormal_tail_ratio(mu_c, sigma_c, u, C)),
        predicted_n_cap_truncated=predicted_capped_count(
            W, lognormal_tail_ratio(mu_t, sigma_t, u, C)),
        ks_lognormal=weighted_ks(
            x, w, lambda q: lognormal_cdf_truncated(q, mu_t, sigma_t, u, C)),
        ks_pareto=weighted_ks(x, w, lambda q: pareto_cdf_truncated(q, alpha_t, u, C)),
        ln_degenerate=bool(sigma_t > 0.98 * LN_SIGMA_MAX
                           or sigma_c > 0.98 * LN_SIGMA_MAX),
    )


def fit_frequency_table(freq: pd.DataFrame, *,
                        threshold_divisor: float = THRESHOLD_DIVISOR,
                        ) -> dict[tuple[str, float], CellFit]:
    """Refit every cell from a (cell Ã— notional) frequency table.

    ``freq`` needs ``vintage``, ``lo``, ``cap``, ``notional``, ``is_capped``,
    ``n``. This is how :data:`CAP_BANDS` was produced and how it is regenerated
    when the tape extends: the shipped constants are a snapshot of this function
    over 2024-03-01..2026-08-07, not a separate model.

    Keyed by ``(vintage, lo)`` because a cell is a band in a vintage, and caps
    repeat across vintages.

    Before trusting a refit, re-run the fitter's own validation --
    ``pytest tests/test_dealer_direction_imputation.py -k "recovers or grouped"``
    -- which recovers known parameters from simulated censored samples. A
    censored MLE that has silently stopped converging still returns numbers, and
    they will look like a plausible new calibration.
    """
    required = {"vintage", "lo", "cap", "notional", "is_capped", "n"}
    missing = required - set(freq.columns)
    if missing:
        raise ValueError(f"frequency table is missing {sorted(missing)}")

    fits: dict[tuple[str, float], CellFit] = {}
    for (vintage, lo), g in freq.groupby(["vintage", "lo"], sort=True):
        C = float(g["cap"].iloc[0])
        u = C / threshold_divisor
        capped = g[g["is_capped"].astype(bool)]
        # capped prints not sitting exactly on C are band-edge noise; the cap is
        # a single discrete value per cell (p10 = p50 = p90 = C), so anything
        # else in here came from a neighbouring band's tenor fuzz.
        n_cap = float(capped.loc[capped["notional"].astype(float) == C, "n"].sum())
        sub = g[~g["is_capped"].astype(bool)]
        fit = fit_cell(sub["notional"].to_numpy(dtype=float),
                       sub["n"].to_numpy(dtype=float), u, C, n_cap)
        if fit is not None:
            fits[(str(vintage), float(lo))] = fit
    return fits
