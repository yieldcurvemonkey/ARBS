"""Does factor-neutral sizing isolate the convexity edge, or delete it?

The question this module exists to settle
------------------------------------------
The cross-strategy factor attribution (``factor_attribution.py``) found that a
DV01-neutral long-end flattener is **not** factor-neutral, and that the amount of
unwanted factor it carries is not a property of the DV01-neutral rule at all --
it is a property of how far apart the two legs sit in PC-loading space. At
$100,000 of package DV01 the four long-end structures carry, per unit of PC2::

    5Y/30Y            $56,249      88.9% of the package's own factor variance
    30Y/50Y            $2,463      29.3%
    20Yx5Y/25Yx5Y      $2,178      14.7%
    10Yx10Y/20Yx10Y      $409       0.2%

a 137x spread from one sizing rule. The user's inference was "we are sizing these
incorrectly". This module tests that constructively: it builds the alternative
sizings, runs them over the same window, the same cohorts and the same engine,
and asks the only question that decides it --

    **after neutralising the dominant factor FOR THAT STRUCTURE, does a positive
    convexity edge remain, or does the P&L simply go to zero?**

Both answers are reportable and only one of them is good news. If an edge
survives, the incumbent sizing was diluting a real convexity trade with a factor
bet. If the P&L collapses, the convexity was never the earner and the honest
conclusion is that DV01-neutral sizing was not "wrong" so much as the thesis was.


The dominant factor is NOT the same factor for all four structures
------------------------------------------------------------------
That last sentence used to read "after neutralising slope", and the attribution
is what changed it. Reading the same four packages as a share of their OWN
factor variance rather than as a dollar exposure::

    structure          level   slope   curv    slope/convex   slope $/unit
    5Y/30Y              5.1%   88.9%   6.0%       7.077          56,249
    30Y/50Y            43.3%   29.3%  27.4%       0.387           2,463
    20Yx5Y/25Yx5Y      69.0%   14.7%  16.4%       0.589           2,178
    10Yx10Y/20Yx10Y    61.3%    0.2%  38.5%       0.055             409

The original premise -- "DV01-neutral leaves a dominant SLOPE bet" -- is true for
**5Y/30Y and nothing else**. For the three tight forward pairs the dominant
unwanted exposure is **LEVEL**: 43-69% of their own factor variance, in a
construction whose entire purpose was to remove level exposure.

The reason is that DV01-neutrality removes level only if PC1's loadings are
FLAT, and they are not. PC1 is humped -- 0.279 at 2Y, 0.334 at 7Y, 0.272 at 50Y
-- so two legs of equal and opposite DV01 leave a residual
``dv01 * (v1_front - v1_back)``, measured at 3.8-16.7% of a same-size outright's
level exposure. A tight pair has small slope and curvature differences, so that
small absolute level residue is a LARGE share of what little exposure the
package has, and the incumbent sizing's least-defensible risk is the one it
claims to have removed.

So the sizing this module leads with for the three tight pairs is
``pc1_neutral``: a TWO-leg trade with one constraint, ``f_PC1 = 0``, plus a
normalisation. It is deliberately **not** DV01-neutral -- that is the point. It
is the same object ``pca_rv.curve_weights(short, long, neutralize=("PC1",))``
computes, and :func:`pc1_neutral_weights` is tied out against that function
rather than merely resembling it.


One engine pass per LEG, not per package -- and why that is exact
-----------------------------------------------------------------
``strat1_longend_listed`` established that every gate's P&L is recoverable from
one unit engine run because swap NPV is linear in ``bpv``. The same linearity
buys something strictly stronger here. A package is a *weighted sum of legs*, so
if the engine is run once per LEG at a fixed unit DV01, with each leg carrying
its own tag, then **every sizing of every structure is a linear combination of
the same eight mark series**::

    equity_s(t) = sum_k sum_L  (r_{s,k,L} / UNIT_DV01) * contrib_{L,k}(t)  -  fees_s(t)

    contrib_{L,k}(t) = mark_{L,k}(t)                    while the leg is open
                     = gross_realized_{L,k}             once it has unwound

That is not an approximation of the package run, it *is* the package run:
``resolve_pricable`` solves notional off pv01 linearly, ``rl.IRS.npv`` is linear
in notional, and no cash is realised mid-hold, so scaling a leg's bpv by ``k``
scales every one of its marks by exactly ``k``. :func:`certify_dv01_neutral`
measures that claim against the four stored ``strat1_le_unit_equity_*`` runs --
genuine ``QueryDrivenBacktest`` passes of the incumbent package, produced by a
different code path months earlier -- and the agreement is machine precision.

The payoff is that a sizing comparison costs no extra engine time. Walk-forward
weights, full-sample weights, gamma-matched rescales, a monthly-rebalanced hedge
overlay: all of them are re-weightings of eight fixed mark matrices. Nothing in
the comparison is a re-run, so nothing in it can differ for a reason other than
the weights, which is the whole point of a sizing experiment.

The eight legs are the union of the four structures' own legs plus one hedge
point (:data:`HEDGE_LEG`), and the four structures share a grid and a cohort
schedule -- asserted, not assumed, by :func:`assert_shared_schedule`, because
``cohort_dates`` picks the first grid day of each month and a single missing day
in one structure's panel would shift its entries and silently de-align the legs.


The four sizings
----------------
Every sizing trades the SAME 91 monthly cohorts on the SAME 1-year holds as
strategy 1's always-on control. Only the leg weights differ.

``dv01_neutral`` (the incumbent)
    ``r_front = +D``, ``r_back = -D``. Zeroes net DV01. Leaves whatever PC1,
    PC2 and PC3 the two legs' loading difference happens to imply -- which for
    5Y/30Y is 88.9% slope, and for 10Yx10Y/20Yx10Y is 61.3% *level*, the risk
    DV01-neutrality was supposed to have removed.

``pc1_neutral``  <- the headline for the three tight pairs
    Two legs, back held at ``-D``, front solved so ``f_PC1 = 0`` exactly.
    ``r_front = +D * v1_back / v1_front``. Net DV01 is NOT zero and is not meant
    to be: the package is neutral to the level FACTOR, which is the thing the
    curve actually moves by, rather than to a parallel shift the curve never
    performs. Residual exposure: PC2, PC3 and convexity.

    For the three tight pairs this is the whole story and it works: the level
    share of package variance falls 0.433 -> 0.214, 0.690 -> 0.102 and
    0.613 -> 0.083, and the level regressor's incremental R^2 on realised daily
    P&L falls 0.0111 -> 0.0005, 0.162 -> 0.019 and 0.215 -> 0.073.

    For 5Y/30Y it is reported and then DISQUALIFIED. Level is only 5.1% of that
    book's variance, so the constraint is not binding on anything that matters,
    and the walk-forward PC1 shape moves enough over 2019-2026 (the 5Y leg
    ranges $70,557 to $134,875 against a full-sample $85,700) that the rule
    scores +1408 bp walk-forward against -66 bp full-sample. A 1474 bp gap
    between two estimates of one sizing is the estimator moving, not a trade.

``pc12_neutral``
    A THIRD leg at :data:`HEDGE_LEG` and a re-solve of the front leg, chosen so
    ``f_PC1 = f_PC2 = 0`` exactly, holding the back leg at ``-D``. Two equations,
    two unknowns, one normalisation. Residual exposure: PC3 (curvature), PC4+,
    and convexity -- which is the intended residual.

``slope_beta_hedged``
    The empirical variant. The incumbent package, plus a DV01-neutral 5s30s
    overlay sized by the beta of the book's own daily P&L on dPC2, estimated on
    a TRAILING window and rebalanced monthly. Residual exposure: PC1, PC3, the
    beta's own estimation error, and whatever slope the trailing window failed to
    see. Costs a round trip on the overlay every month, which is charged.

``vega_neutral`` (analytic only -- see :func:`straddle_sizing_table`)
    The note's own funded-straddle version. Not run: ``build_backtest`` refuses
    ``trade_straddle=True`` with a measured reason (median $4.17 of underlying
    DV01 for 20Yx5Y/25Yx5Y against $17,169 for 5Y/30Y), and this module does not
    add an untested engine path to answer an optional part of the question. The
    sizing is reported analytically so the reader can see what it would be.

:data:`SCORED_SIZINGS` is the pre-committed set the multiple-testing correction
counts: four. The hedge-tenor sweep in :func:`hedge_tenor_frontier` is
deliberately ANALYTIC -- exposures and gamma, no P&L -- because ranking nine
hedge tenors on realised P&L and reporting the winner would be nine trials
wearing one trial's clothes.


Two bases, and they must not be confused
-----------------------------------------
There are two PCAs in this module and they do different jobs.

The **weight** basis is walk-forward: re-fitted at every cohort entry on data
strictly before it, because a weight is a decision and a decision cannot use
tomorrow's covariance. Every ``pc1_neutral`` and ``pc12_neutral`` weight, and
every ``slope_beta_hedged`` beta, comes off that basis.

The **measurement** basis is the committed full-sample ``FactorModel`` from
``factor_attribution`` -- the same eigenvectors the attribution report used.
Every exposure table, every variance share and the re-run attribution use it and
only it. Re-fitting a different PCA to score the new books would make the
"did the level share move toward zero?" comparison a comparison of two bases
instead of two sizings.

The distinction is not pedantry: it is the difference between "what could the
trader have known" (weights) and "on one fixed ruler, what did the hedge do"
(measurement).


Where the weights come from, and the look-ahead that would have been free
-------------------------------------------------------------------------
The PC loadings that define ``pc12_neutral`` are estimated from the curve's own
history. Fitting them on the full 2019-2026 sample is what the attribution
report did -- correct there, because that is a description of what happened --
and would be look-ahead here, because a 2019 cohort would be sized with 2026's
covariance.

So the primary weights are **walk-forward**: at each cohort entry the PCA is
re-fitted on data strictly before that date (expanding, with
``min_fit_days`` minimum), and the eigenvectors are mapped to PC1/PC2/PC3 by
:func:`RVUtils.pca_rv.align_eigenvectors` against the previous fit and then
checked with ``factor_attribution.classify_pcs`` -- **never by index**. An
expanding fit on eleven months of 2019 can genuinely rotate PC2 and PC3, and
sign-pinning alone does not catch a rotation, only a flip.

The full-sample variant is computed too, for free, and reported beside it. If
the two agree the look-ahead was immaterial and the comparison is like-for-like;
if they do not, the walk-forward one is the answer and the gap is the cost of
not knowing the covariance in advance. Measured, not asserted.


Costs: one model, exactly backward compatible
----------------------------------------------
The incumbent charges ``2 * cost_bp_one_way * package_dv01`` = $100,000 per
cohort round trip at the committed 0.5 bp. That is a per-PACKAGE fee and it
cannot price a package whose gross DV01 is 1.8x bigger. The generalisation used
here is per-LEG and reproduces the incumbent exactly::

    fee_round_trip = 2 * (cost_bp_one_way / 2) * sum_L |r_L|

At ``r = (+100k, -100k)`` that is ``2 * 0.25 * 200,000 = $100,000``. The
``/ 2`` is not a fudge: ``cost_bp_one_way`` is documented as the cost per
*leg-pair*, so half of it is the cost per leg, and a three-leg package pays for
three legs. Every number quoted below is net of this, and net of carry, because
carry is not modelled at all -- the engine holds real swaps for a year and marks
them, so realised P&L already contains it.
"""

from __future__ import annotations

import dataclasses
import datetime
import math
import pathlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV import factor_attribution as fa

__all__ = [
    "LEG_UNIVERSE",
    "HEDGE_LEG",
    "HEDGE_CANDIDATES",
    "GREEK_LEGS",
    "SLOPE_INSTRUMENT",
    "SLOPE_CANDIDATES",
    "SIZINGS",
    "SCORED_SIZINGS",
    "STATIC_SIZINGS",
    "ATTRIBUTION_VARIANCE_SHARES",
    "HEADLINE_SIZING",
    "UNIT_DV01",
    "FactorNeutralConfig",
    "safe_leg",
    "assert_shared_schedule",
    "build_leg_backtest",
    "run_leg",
    "LegRun",
    "load_leg_runs",
    "load_leg_greeks",
    "leg_pc_loadings",
    "leg_gamma_bp",
    "leg_carry_bp",
    "dv01_neutral_weights",
    "pc1_neutral_weights",
    "pc12_neutral_weights",
    "slope_instrument_weights",
    "slope_hedge_ratio",
    "package_pc_exposure",
    "package_variance_shares",
    "gamma_match_scale",
    "walk_forward_loadings",
    "full_sample_loadings",
    "cohort_weights",
    "leg_cost_bp_one_way",
    "compose_book",
    "compose_overlay",
    "add_overlay",
    "live_packages",
    "slope_beta_path",
    "walk_forward_scores",
    "certify_dv01_neutral",
    "certify_engine",
    "dominant_factor_table",
    "hedge_tenor_frontier",
    "slope_instrument_table",
    "straddle_sizing_table",
    "residual_exposure_table",
    "weights_summary",
    "sizing_series",
    "book_stats",
    "breakeven_cost_bp",
    "cost_sensitivity",
    "overlay_cost_sensitivity",
    "n_eff_report",
    "sharpe_scoreboard",
    "attribution_shares",
    "verdict",
]


# ===========================================================================
# Universe
# ===========================================================================
#: Every leg the engine is run on, once each, at :data:`UNIT_DV01`. The union of
#: the four long-end structures' own legs plus the hedge point. Order is the
#: engine launch order (slowest first: a 50Y spot has ten times the cashflows of
#: a 25Yx5Y forward and dominates the wall clock).
LEG_UNIVERSE: Tuple[str, ...] = (
    "50Y", "30Y", "10Y", "5Y",
    "25Yx5Y", "20Yx5Y", "20Yx10Y", "10Yx10Y",
)

#: Hedge tenors swept ANALYTICALLY by :func:`hedge_tenor_frontier`. Every one of
#: them is on the PCA grid, so its loading vector is exact rather than
#: annuity-decomposed. The sweep is reported in exposures, gamma and carry and
#: NEVER in realised P&L -- see :data:`SCORED_SIZINGS`.
HEDGE_CANDIDATES: Tuple[str, ...] = ("2Y", "3Y", "5Y", "7Y", "10Y", "15Y",
                                     "20Y", "25Y", "30Y")

#: Legs the light greeks pass prices: the traded universe plus every hedge
#: candidate, so the frontier's gamma column is MEASURED by repricing rather
#: than approximated by an annuity derivative.
GREEK_LEGS: Tuple[str, ...] = tuple(
    dict.fromkeys(("50Y", "30Y", "10Y", "5Y", "25Yx5Y", "20Yx5Y", "20Yx10Y",
                   "10Yx10Y", "2Y", "3Y", "7Y", "15Y", "20Y", "25Y")))

#: The third leg of every ``pc12_neutral`` package. Pre-committed to 10Y, and
#: the reason is stated so it cannot be mistaken for a fitted choice: it is the
#: single most liquid point on the USD curve, it sits in the MIDDLE of the PCA
#: grid so its loading vector is genuinely independent of both long-end legs
#: (PC1 0.328, PC2 -0.016, PC3 -0.362 -- near-zero slope, strong curvature), and
#: it produces a well-conditioned solve for all four structures
#: (cond 2.1-2.7). :func:`hedge_tenor_frontier` shows the whole sweep in
#: exposures and gamma, WITHOUT P&L, so the choice is checkable without being a
#: nine-way search over realised returns.
HEDGE_LEG: str = "10Y"

#: The slope overlay for ``slope_beta_hedged``: a DV01-neutral 5s30s, expressed
#: as leg DV01s per $1 of instrument size. Pre-committed on three stated grounds
#: -- it is the canonical long-end slope trade, both legs are already in
#: :data:`LEG_UNIVERSE` so it costs no extra engine time, and of the candidates
#: it injects the least curvature per unit of slope hedged (|PC3/PC2| = 0.99
#: against 1.66 for 2s10s and 2.08 for 10s30s). :func:`slope_instrument_table`
#: reports that comparison from the fitted loadings rather than from this note.
#:
#: For the 5Y/30Y book this overlay is close to an UNWIND of the position
#: itself, and that is not a defect of the choice -- it is the finding. A book
#: whose slope share is 259.6% of its P&L has no slope hedge that is not
#: essentially its own reverse.
SLOPE_INSTRUMENT: Tuple[Tuple[str, float], ...] = (("5Y", +1.0), ("30Y", -1.0))

#: The slope instruments compared ANALYTICALLY by :func:`slope_instrument_table`
#: -- on curvature injected per unit of slope hedged, never on P&L. Reported so
#: the pre-committed choice above is checkable rather than merely asserted.
SLOPE_CANDIDATES: Tuple[Tuple[str, Tuple[Tuple[str, float], ...]], ...] = (
    ("5s30s", (("5Y", +1.0), ("30Y", -1.0))),
    ("2s10s", (("2Y", +1.0), ("10Y", -1.0))),
    ("10s30s", (("10Y", +1.0), ("30Y", -1.0))),
    ("5s10s", (("5Y", +1.0), ("10Y", -1.0))),
    ("10s20s", (("10Y", +1.0), ("20Y", -1.0))),
)

#: The sizings built. ``vega_neutral`` is absent by design -- see the module
#: docstring and :func:`straddle_sizing_table`.
#:
#: ``pc1_neutral`` was added AFTER the attribution finished and it is the
#: headline sizing for the three tight forward pairs, because the attribution
#: measured their dominant unwanted exposure as LEVEL (43-69% of their own
#: factor variance), not slope. It is a two-leg trade -- one constraint plus a
#: normalisation -- and it is deliberately NOT DV01-neutral. That is the point:
#: DV01-neutrality only removes level exposure when PC1's loadings are flat, and
#: they are not (0.279 at 2Y, 0.334 at 7Y, 0.272 at 50Y).
SIZINGS: Tuple[str, ...] = ("dv01_neutral", "pc1_neutral", "pc12_neutral",
                            "slope_beta_hedged")

#: What the multiple-testing correction counts. Identical to :data:`SIZINGS`:
#: four distinct sizings, four trials. Three things are deliberately NOT counted
#: and the reason is the same in each case -- they are not free choices over
#: which a best could be picked:
#:
#: * the walk-forward/full-sample pair is ONE trial, not two. Same sizing rule
#:   estimated two ways, and the full-sample one is reported to quantify
#:   look-ahead, never to be selected.
#: * ``vega_neutral`` is analytic-only and produces no P&L to rank.
#: * the hedge-tenor frontier is reported in exposures and gamma and NEVER in
#:   realised P&L, so nine tenors do not become nine trials.
SCORED_SIZINGS: Tuple[str, ...] = SIZINGS

#: Sizings whose weights are a per-cohort leg table (as opposed to an overlay on
#: another sizing's package). ``slope_beta_hedged`` is absent because its base
#: package IS ``dv01_neutral`` and what it adds is a monthly overlay, which does
#: not fit a per-cohort weight table -- see :func:`compose_overlay`.
STATIC_SIZINGS: Tuple[str, ...] = ("dv01_neutral", "pc1_neutral", "pc12_neutral")

#: Which factor each structure's own attribution found DOMINANT at the incumbent
#: DV01-neutral sizing, as a share of that package's own factor variance. Copied
#: from the committed attribution run so the retarget is checkable against its
#: source rather than asserted here; :func:`dominant_factor_table` RE-MEASURES
#: all of it from the fitted model and prints both side by side.
ATTRIBUTION_VARIANCE_SHARES: Dict[str, Dict[str, float]] = {
    "5Y/30Y":          {"level": 0.051, "slope": 0.889, "curvature": 0.060},
    "30Y/50Y":         {"level": 0.433, "slope": 0.293, "curvature": 0.274},
    "20Yx5Y/25Yx5Y":   {"level": 0.690, "slope": 0.147, "curvature": 0.164},
    "10Yx10Y/20Yx10Y": {"level": 0.613, "slope": 0.002, "curvature": 0.385},
}

#: The sizing this study nominates as the headline test for each structure --
#: the one that neutralises THAT structure's own dominant factor. Pre-committed
#: from :data:`ATTRIBUTION_VARIANCE_SHARES`, which was measured before any P&L
#: in this module existed, so it is not a pick over realised returns.
HEADLINE_SIZING: Dict[str, str] = {
    "5Y/30Y":          "pc12_neutral",
    "30Y/50Y":         "pc1_neutral",
    "20Yx5Y/25Yx5Y":   "pc1_neutral",
    "10Yx10Y/20Yx10Y": "pc1_neutral",
}

#: The DV01 each leg is opened at in its unit engine run, $ per bp. Every
#: composed weight is divided by this, so it is a pure normalisation and the
#: number itself never reaches a result.
UNIT_DV01: float = 100_000.0


@dataclasses.dataclass(frozen=True)
class FactorNeutralConfig:
    """Every knob of THIS study. Nothing here is tuned on realised P&L.

    The backtest knobs are deliberately absent and are taken from
    ``strat1_longend_listed.strat1_config()`` -- strategy 1's committed base run
    ($100k package DV01, monthly cohorts, 1-year hold, 0.5 bp one-way, no
    force-close, 2019-01-02..2026-08-14). Restating them here is how two configs
    drift apart and how "directly comparable to the incumbent" quietly stops
    being true.
    """

    #: The sizings built and scored.
    sizings: Tuple[str, ...] = SIZINGS
    #: Trials the multiple-testing correction counts.
    scored_sizings: Tuple[str, ...] = SCORED_SIZINGS
    #: Third leg of the PC1+PC2-neutral package.
    hedge_leg: str = HEDGE_LEG
    #: Legs run through the engine.
    legs: Tuple[str, ...] = LEG_UNIVERSE
    #: PCs held to zero by ``pc12_neutral``. Two, because two legs plus a
    #: normalisation give exactly two free weights. Neutralising PC3 as well
    #: would need a fourth leg and is reported as residual instead.
    neutralize: Tuple[str, ...] = ("PC1", "PC2")
    #: Weight estimation. ``"walk_forward"`` re-fits the PCA on data strictly
    #: before each cohort entry; ``"full_sample"`` uses the attribution report's
    #: own basis and is reported beside it to price the look-ahead.
    weight_mode: str = "walk_forward"
    #: Minimum days in the expanding PCA before a cohort may be sized. 250 is
    #: one business year -- enough for an 11-tenor covariance to be identified.
    #: Cohorts earlier than this are NOT dropped (dropping them would change the
    #: trade set and stop this being a sizing comparison); they are sized on the
    #: shortest admissible fit and flagged in ``weights_frame``.
    min_fit_days: int = 250
    #: The HARD floor, below which a fit is refused outright. Cohort 0 enters
    #: 2019-02-01 and the panel starts 2019-01-02, so it has ~20 daily changes
    #: and nothing can be done about that -- ``FactorConfig.start`` is the first
    #: day the full 2Y..50Y grid prices locally, so the window cannot be
    #: extended backwards. 15 admits it; :func:`weights_summary` reports which
    #: cohorts sit between this and ``min_fit_days``, and the notebook re-scores
    #: the books excluding them as a robustness row.
    hard_fit_floor: int = 15
    #: Trailing window for the ``slope_beta_hedged`` beta, business days.
    #: One year, matching the holding period, and re-estimated at every monthly
    #: rebalance from data strictly before it.
    beta_window: int = 252
    #: Rebalance cadence of the slope overlay. Monthly, on the cohort dates, so
    #: the overlay's month slices come from the same leg runs.
    overlay_rebalance: str = "monthly"
    #: Business days per year for annualising the daily-MTM Sharpe.
    business_days_per_year: float = 252.0
    #: The structure re-run through a GENUINE 3-leg engine pass to certify the
    #: composed ``pc12_neutral`` book. 5Y/30Y because it is the structure the
    #: whole premise rests on and the one whose weights move most.
    certify_structure: str = "5Y/30Y"
    certify_sizing: str = "pc12_neutral"
    #: Cost multiples on ``strat1_config().cost_bp_one_way`` (0.5 bp one way).
    #: ``1.0`` is the headline; ``0.0`` isolates gross so the hedge's own cost is
    #: visible as a subtraction rather than inferred.
    cost_multipliers: Tuple[float, ...] = (0.0, 0.5, 1.0, 2.0)

    def as_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def safe_leg(leg: str) -> str:
    """Filesystem-safe leg label. ``"10Yx10Y"`` is already safe; ``"5Y/30Y"``
    is not, and this is used for both."""
    return str(leg).replace("/", "-").replace(" ", "_")


# ===========================================================================
# 1. Schedule identity -- the precondition for sharing legs
# ===========================================================================
def assert_shared_schedule(data_dir: Any,
                           structures: Sequence[Tuple[str, str, str]] = fa.STRAT1_STRUCTURES,
                           ) -> pd.DataFrame:
    """Every structure must use the SAME grid and the SAME cohort schedule.

    The per-leg design has one precondition and it is not cosmetic: 30Y serves
    both ``5Y/30Y`` and ``30Y/50Y``, so a single 30Y leg run can only stand in
    for both if both structures open and close their cohorts on identical dates.
    ``cohort_dates`` takes the FIRST grid day of each month, so one missing day
    in one structure's signal panel shifts that structure's entries by a day and
    every composed book built from a shared leg would be wrong -- quietly, with
    a plausible-looking equity curve.

    Returns the comparison frame; raises on any disagreement.
    """
    d = pathlib.Path(data_dir)
    rows: List[Dict[str, Any]] = []
    ref_entry = ref_exit = None
    for label, _f, _b in structures:
        p = d / f"strat1_le_unit_cohorts_{safe_leg(label)}.parquet"
        if not p.exists():
            raise FileNotFoundError(f"unit cohorts missing for {label}: {p}")
        c = pd.read_parquet(p)
        entry = tuple(pd.to_datetime(c["entry"]))
        exit_ = tuple(pd.to_datetime(c["exit"]))
        if ref_entry is None:
            ref_entry, ref_exit = entry, exit_
        rows.append({
            "structure": label, "n_cohorts": int(len(c)),
            "n_closed": int(c["closed"].sum()),
            "entries_match": entry == ref_entry,
            "exits_match": exit_ == ref_exit,
        })
    out = pd.DataFrame(rows)
    bad = out[~(out["entries_match"] & out["exits_match"])]
    if len(bad):
        raise AssertionError(
            "structures do not share a cohort schedule, so per-leg runs cannot "
            f"be shared:\n{bad.to_string(index=False)}")
    return out


# ===========================================================================
# 2. The engine pass -- one per leg
# ===========================================================================
def build_leg_backtest(mdp: Any, cfg: s1.Strat1Config, leg: str,
                       grid_dates: Sequence[Any]) -> Tuple[Any, pd.DataFrame]:
    """One leg, opened at ``+UNIT_DV01`` on every cohort date, held ``horizon``.

    Deliberately a near-copy of ``strat1_curve_gamma.build_backtest`` with one
    leg instead of two and no fee, rather than a call into it: that function
    hard-wires a two-leg DV01-neutral package and the whole point here is to
    take the package apart. Everything it gets right is preserved --

    * the cohort grid comes from ``s1.cohort_dates`` / ``s1.cohort_schedule``, so
      the entries and exits are bit-identical to the stored unit runs;
    * each cohort gets its OWN tag, because unwinds process after fills and a
      shared tag would let one cohort's unwind close another's position;
    * ``DateTriggerRequirements`` is fed ``datetime.date``, never a
      ``pd.Timestamp`` -- the requirement tests ``state.date() in set(dates)``
      and a Timestamp never compares equal to a date, which makes the trigger a
      SILENT no-op;
    * a cohort whose horizon falls past the sample end gets no unwind and stays
      marked to the end.

    The one deliberate difference is ``fee=0.0``. Cost is re-applied in
    :func:`compose_book`, per leg and per sizing, because a three-leg package
    does not pay a two-leg package's fee and the engine's flat per-cohort fee
    cannot express that.
    """
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    grid = pd.DatetimeIndex([pd.Timestamp(d) for d in grid_dates]).sort_values()
    # The stored unit runs lag the +1 signal by one day, which drops the very
    # first grid day and leaves 91 cohorts, not 92. Reproduced exactly here by
    # dropping the first grid day from the entry candidates.
    entries = [d for d in s1.cohort_dates(grid, cfg.cohort_freq)
               if pd.Timestamp(d) > grid[0]]
    sched = s1.cohort_schedule(grid, entries, cfg.horizon)

    triggers: List[Any] = []
    rows: List[Dict[str, Any]] = []
    for k, (entry, exit_) in enumerate(sched):
        tag = f"{safe_leg(leg)}_c{k:04d}"
        q = IRSwapQuery(structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
                        tenor=leg, curve=cfg.curve,
                        structure_kwargs={"bpv": float(UNIT_DV01)}, tags=(tag,))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[entry]),
            actions=[AddQueryAction(query=q, meta={"tags": [tag]})]))
        if exit_ is not None:
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[exit_]),
                actions=[UnwindPositionsAction(match_tag=tag, fee=0.0)]))
        rows.append({"tag": tag, "leg": leg, "cohort": k,
                     "entry": pd.Timestamp(entry),
                     "exit": pd.NaT if exit_ is None else pd.Timestamp(exit_),
                     "live_at_end": exit_ is None})

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(list(grid)),
        strategy=QueryStrategy(name=f"leg_{safe_leg(leg)}", triggers=triggers),
        mdp=mdp, show_progress=False,
    )
    return bt, pd.DataFrame(rows)


def run_leg(mdp: Any, cfg: s1.Strat1Config, leg: str, grid_dates: Sequence[Any],
            *, log: Any = print) -> Tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """Run one leg and return ``(equity, cohorts, marks)``.

    ``marks`` is ``date x tag`` of the position's mark while open -- tapped off
    ``_position_value``, which the engine calls exactly once per position per
    mark inside ``mark_to_market``, so the instrumentation is free rather than a
    second repricing pass.

    Two guards, both of which have fired on this code base before:

    * ``QueryDrivenBacktest.run()`` SWALLOWS exceptions, so a dead run is an
      empty ``mtm_history`` and never a traceback. Asserted.
    * the per-tag decomposition ``mtm(t) == sum_k contribution_k(t)`` is an
      identity only while no cash is realised mid-hold. Asserted per run, so a
      future instrument that breaks it fails the build instead of composing
      wrong curves.
    """
    import time
    import types

    bt, cohorts = build_leg_backtest(mdp, cfg, leg, grid_dates)
    log(f"{leg}: {len(cohorts)} cohorts over {len(grid_dates)} grid dates", flush=True)

    tag_value: Dict[str, Dict] = {}
    _orig = bt._position_value

    def _tapped(self, pos, now):
        v = _orig(pos, now)
        tags = list((getattr(pos, "meta", None) or {}).get("tags", []) or [])
        if tags:
            d = tag_value.setdefault(str(tags[0]), {})
            d[now] = d.get(now, 0.0) + float(v)
        return v

    bt._position_value = types.MethodType(_tapped, bt)

    t0 = time.time()
    bt.run()
    if not getattr(bt, "mtm_history", None):
        raise RuntimeError(f"{leg}: engine produced no mtm_history -- run() failed")
    log(f"{leg}: ran in {time.time() - t0:.0f}s, {len(bt.mtm_history)} marks", flush=True)

    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    eq = eq.sort_index()

    by_tag: Dict[str, float] = {}
    for rec in (getattr(bt.portfolio, "closed_positions_log", []) or []):
        tags = list((rec.get("position_meta") or {}).get("tags", []) or [])
        if tags:
            by_tag[str(tags[0])] = by_tag.get(str(tags[0]), 0.0) + float(
                rec.get("gross_realized_pnl", 0.0))
    cohorts = cohorts.copy()
    cohorts["closed"] = [t in by_tag for t in cohorts["tag"]]
    cohorts["gross_pnl_ccy"] = [by_tag.get(t, float("nan")) for t in cohorts["tag"]]
    cohorts["gross_pnl_bp"] = cohorts["gross_pnl_ccy"] / UNIT_DV01

    marks = (pd.DataFrame({t: pd.Series(v) for t, v in tag_value.items()})
             if tag_value else pd.DataFrame(index=eq.index))
    marks.index = pd.to_datetime(marks.index)
    marks = marks.reindex(eq.index).sort_index()

    recon = pd.Series(0.0, index=eq.index)
    for _, r in cohorts.iterrows():
        tag = str(r["tag"])
        if tag in marks.columns:
            recon = recon.add(marks[tag].fillna(0.0), fill_value=0.0)
        if bool(r["closed"]):
            recon.loc[eq.index >= pd.Timestamp(r["exit"])] += float(r["gross_pnl_ccy"])
    scale = max(float(eq.abs().max()), 1.0)
    err = float((recon - eq).abs().max())
    log(f"{leg}: per-tag decomposition max abs err ${err:,.6f} "
        f"({err / scale:.3e} relative)", flush=True)
    if err > 1e-6 * scale:
        raise AssertionError(
            f"{leg}: per-tag decomposition FAILED (${err:,.2f}) -- every composed "
            "book would be wrong. Cash is being realised mid-hold.")
    return eq, cohorts, marks


# ===========================================================================
# 3. Loading the engine runs
# ===========================================================================
@dataclasses.dataclass
class LegRun:
    """One leg's unit engine pass: daily equity, cohort table, per-cohort marks.

    ``marks`` columns are the cohort TAGS; ``cohorts`` carries the tag ->
    (cohort index, entry, exit, closed, gross_pnl_ccy) mapping. Everything is at
    :data:`UNIT_DV01`, so a weight of ``r`` dollars per bp scales every number
    here by ``r / UNIT_DV01`` -- exactly, not approximately.
    """

    leg: str
    equity: pd.Series
    cohorts: pd.DataFrame
    marks: pd.DataFrame
    #: Memoised :meth:`contribution` / :meth:`open_mark`. Sixteen books are
    #: composed from eight legs, so without this the same 91x1907 matrix is
    #: rebuilt dozens of times; the contents are a pure function of the fields
    #: above and never vary between calls.
    _cache: Dict[str, pd.DataFrame] = dataclasses.field(
        default_factory=dict, repr=False, compare=False)

    @property
    def index(self) -> pd.DatetimeIndex:
        return pd.DatetimeIndex(self.equity.index)

    def contribution(self) -> pd.DataFrame:
        """``date x cohort`` of the leg's contribution at :data:`UNIT_DV01`.

        The mark while open, plus the gross realised P&L from the exit day
        onward. Fee-free by construction -- the unit runs charge nothing, and
        cost is re-applied per sizing in :func:`compose_book`, because a
        three-leg package does not pay a two-leg package's fee.
        """
        if "contribution" in self._cache:
            return self._cache["contribution"]
        idx = self.index
        cols: Dict[int, np.ndarray] = {}
        for _, r in self.cohorts.iterrows():
            k, tag = int(r["cohort"]), str(r["tag"])
            col = (self.marks[tag].reindex(idx).fillna(0.0).to_numpy(float)
                   if tag in self.marks.columns else np.zeros(len(idx)))
            if bool(r["closed"]):
                col = col + (idx >= pd.Timestamp(r["exit"])).astype(float) * float(
                    r["gross_pnl_ccy"])
            cols[k] = col
        out = pd.DataFrame(cols, index=idx)
        self._cache["contribution"] = out
        return out

    def open_mark(self) -> pd.DataFrame:
        """``date x cohort`` of the OPEN position's mark only, no realised P&L.

        This is what the monthly slices of the ``slope_beta_hedged`` overlay are
        built from: a position opened at ``entry`` and closed a month later has,
        as its P&L, exactly this column's value at that later date.
        """
        if "open_mark" in self._cache:
            return self._cache["open_mark"]
        idx = self.index
        cols: Dict[int, np.ndarray] = {}
        for _, r in self.cohorts.iterrows():
            k, tag = int(r["cohort"]), str(r["tag"])
            cols[k] = (self.marks[tag].reindex(idx).fillna(0.0).to_numpy(float)
                       if tag in self.marks.columns else np.zeros(len(idx)))
        out = pd.DataFrame(cols, index=idx)
        self._cache["open_mark"] = out
        return out


def load_leg_runs(data_dir: Any, legs: Sequence[str] = LEG_UNIVERSE,
                  *, log: Optional[Any] = None
                  ) -> Tuple[Dict[str, "LegRun"], pd.DatetimeIndex]:
    """Load every cached leg run onto ONE common mark grid, with one schedule.

    The schedule check is not ceremony. The composition adds legs cohort by
    cohort; two legs whose cohort 7 opened on different days would compose a
    package that was never a package, and the equity curve would look entirely
    plausible. That check is an equality and it raises.

    The mark GRID is different and it is a measurement, not an assertion. The
    engine's ``mtm_history`` carries a day only if the curve priced that leg on
    it, and on **2019-04-19 (Good Friday) the local SOFR curve prices 5Y and
    25Yx5Y but not 10Y, 30Y or 50Y**. Requiring bit-identical indices would
    refuse to load a cache that is perfectly usable; silently unioning them would
    forward-fill a mark that was never taken. So the legs are INTERSECTED, and
    the intersection is returned so the caller can report it.

    That is the same treatment ``factor_attribution.align_to_factor_calendar``
    already applies to this exact day, and it costs nothing here: the
    intersection is 1907 days, which is precisely the grid the four stored
    two-leg engine runs use, so :func:`certify_dv01_neutral` compares like with
    like. Dropping a mid-week day turns one daily change into a two-day change
    and moves no P&L, because equity is a cumulative level; the terminal value
    is untouched. No cohort entry or exit falls on a dropped day -- asserted.

    Returns ``(leg_runs, common_index)``.
    """
    d = pathlib.Path(data_dir)
    raw: Dict[str, Tuple[pd.Series, pd.DataFrame, pd.DataFrame]] = {}
    ref_sched: Optional[Tuple[Any, Any]] = None
    common: Optional[pd.DatetimeIndex] = None
    union: Optional[pd.DatetimeIndex] = None
    for leg in legs:
        s = safe_leg(leg)
        eq = pd.read_parquet(d / f"fns_leg_equity_{s}.parquet")["equity_usd"]
        eq.index = pd.to_datetime(eq.index)
        eq = eq.sort_index()
        co = pd.read_parquet(d / f"fns_leg_cohorts_{s}.parquet")
        mk = pd.read_parquet(d / f"fns_leg_marks_{s}.parquet")
        mk.index = pd.to_datetime(mk.index)
        idx = pd.DatetimeIndex(eq.index)
        sched = (tuple(pd.to_datetime(co["entry"])),
                 tuple(pd.to_datetime(co["exit"]).fillna(pd.Timestamp("2100-01-01"))))
        if ref_sched is None:
            ref_sched = sched
        elif sched != ref_sched:
            raise AssertionError(
                f"leg {leg}: cohort schedule differs from {legs[0]} -- per-leg "
                "runs cannot be composed into a package")
        common = idx if common is None else common.intersection(idx)
        union = idx if union is None else union.union(idx)
        raw[leg] = (eq, co, mk)

    assert common is not None and union is not None and len(common) > 0
    dropped = union.difference(common)
    if len(dropped):
        # A dropped day that carried a cohort entry or exit would shift a trade,
        # not just a mark. That must never pass silently.
        ent = set(pd.to_datetime(raw[legs[0]][1]["entry"]))
        exi = set(pd.to_datetime(raw[legs[0]][1]["exit"]).dropna())
        clash = sorted((ent | exi) & set(dropped))
        if clash:
            raise AssertionError(
                f"cohort entry/exit dates {[str(c)[:10] for c in clash]} are "
                "missing from at least one leg's marks -- the trade set is not "
                "shared and the legs cannot be composed")
        if log is not None:
            log(f"leg grids intersected to {len(common)} marks; dropped "
                f"{[str(x)[:10] for x in dropped]} (priced for some legs only)")

    out: Dict[str, LegRun] = {}
    for leg, (eq, co, mk) in raw.items():
        out[leg] = LegRun(leg=leg, equity=eq.reindex(common), cohorts=co,
                          marks=mk.reindex(common))
    return out, common


def load_leg_greeks(data_dir: Any) -> pd.DataFrame:
    """The light greeks pass: gamma and 1-year carry per $1 of leg DV01.

    ``gamma_per_dv01`` is P&L-dollars per bp^2 per dollar of leg DV01, so a
    package's dollar gamma is ``sum_L r_L * gamma_per_dv01_L``. ``carry_bp`` is
    the leg's own 1-year carry-and-roll in bp of its own DV01, so the package's
    carry in dollars is ``sum_L r_L * carry_bp_L``. Both linear, both composable,
    both measured on the cohort's own entry date rather than averaged.
    """
    df = pd.read_parquet(pathlib.Path(data_dir) / "fns_leg_greeks.parquet")
    df["date"] = pd.to_datetime(df["date"])
    return df


# ===========================================================================
# 4. Factor loadings of a LEG, and the weight solves
# ===========================================================================
def leg_pc_loadings(fm: fa.FactorModel, legs: Sequence[str],
                    rates_bp: Optional[Mapping[str, float]] = None,
                    n_pcs: int = 3) -> pd.DataFrame:
    """Each leg's PC exposure per $1 of its own DV01. ``legs x PC1..PCn``.

    A SPOT leg on the PCA grid has an exact loading -- it *is* a row of ``V``. A
    FORWARD leg is spread over two spot tenors by
    ``factor_attribution.spot_ladder_for_leg``, which replicates ``AxB`` as long
    spot ``A+B`` / short spot ``A`` at equal notional and splits the DV01 by par
    annuity. That is an approximation, and it was checked rather than trusted:
    regressing each stored unit flattener's daily P&L on the PC scores gives
    fitted betas (PC1 / PC2 / PC3) against the analytic ladder of

        5Y/30Y           1,967 / 56,779 / -52,498   vs   4,713 / 56,249 / -55,900
        20Yx5Y/25Yx5Y    1,797 /  2,091 /  -9,263   vs   1,645 /  2,178 /  -8,802

    -- within 1% on the slope of the decisive structure and within 5% on a
    forward pair. The residual gap on 30Y/50Y and 10Yx10Y/20Yx10Y is cohort
    AGEING rather than the annuity split: the analytic number is the exposure at
    inception, the fitted one is the average over a book whose cohorts are up to
    a year old. ``slope_beta_hedged`` uses the fitted exposure instead, and is
    the sizing that answers that objection rather than arguing with it.
    """
    rates = dict(rates_bp) if rates_bp is not None else fm.rates_bp.mean().to_dict()
    rows = {leg: fa.package_pc_exposure(fa.spot_ladder_for_leg(leg, 1.0, rates),
                                        fm, n_pcs=n_pcs)
            for leg in legs}
    return pd.DataFrame(rows).T[[f"PC{i + 1}" for i in range(n_pcs)]]


def leg_gamma_bp(greeks: pd.DataFrame, on: Optional[Any] = None) -> pd.Series:
    """Gamma per $1 of leg DV01, P&L-dollars per bp^2. Sample mean, or one date.

    Second central difference of the leg's own ``payoff_profile`` at +/-25 bp --
    the repricing route ``curve_ops`` mandates, because ``GAMMA_01`` raises
    ``NotImplementedError`` on the rateslib backend. A carry level on the profile
    cancels exactly in a second difference, so this is a clean gamma and not a
    gamma contaminated by theta.
    """
    if on is None:
        return greeks.groupby("leg")["gamma_per_dv01"].mean()
    sub = greeks[greeks["date"] == pd.Timestamp(on)]
    if sub.empty:
        raise KeyError(f"no greeks on {on}")
    return sub.set_index("leg")["gamma_per_dv01"]


def leg_carry_bp(greeks: pd.DataFrame, on: Optional[Any] = None) -> pd.Series:
    """1-year carry-and-roll per $1 of leg DV01, in bp. Sample mean, or one date."""
    if on is None:
        return greeks.groupby("leg")["carry_bp"].mean()
    sub = greeks[greeks["date"] == pd.Timestamp(on)]
    if sub.empty:
        raise KeyError(f"no greeks on {on}")
    return sub.set_index("leg")["carry_bp"]


def dv01_neutral_weights(front: str, back: str, dv01: float = UNIT_DV01
                         ) -> Dict[str, float]:
    """The incumbent: pay the front leg, receive the back, equal DV01.

    Sign convention is this package's, verified empirically and restated in
    ``ConvexityRV/__init__``: OUTRIGHT ``bpv > 0`` is a PAYER, and the FLATTENER
    pays the front leg and receives the back. That is the long-convexity side.
    """
    return {front: +float(dv01), back: -float(dv01)}


def pc1_neutral_weights(front: str, back: str, loadings: pd.DataFrame, *,
                        dv01: float = UNIT_DV01,
                        neutralize: Sequence[str] = ("PC1",)) -> Dict[str, float]:
    """Two legs sized so the LEVEL factor comes out at exactly zero.

    This is the sizing the attribution retargeted the study onto. One constraint
    and one normalisation give a unique ratio, so it needs no third leg::

        r_back  = -dv01                     (the normalisation)
        r_front = +dv01 * v1_back / v1_front  (so f_PC1 = 0 exactly)

    where ``v1_L`` is leg ``L``'s PC1 exposure per $1 of its own DV01. The
    package is therefore **not** DV01-neutral, by ``dv01 * (v1_back/v1_front - 1)``,
    and that is the construction rather than a defect of it. DV01-neutrality
    removes level only under a flat PC1; the fitted PC1 is humped, so the two
    definitions of "no level risk" genuinely disagree and this one is neutral to
    the move the curve actually makes.

    The normalisation is the same anchor :func:`pc12_neutral_weights` uses --
    the RECEIVED long-dated leg, the one carrying the convexity, held at the
    incumbent's size -- so all three static sizings sit on the same position and
    everything that differs between them is the hedge. Because every P&L here is
    exactly linear in the weights, any other normalisation is a rescale: it moves
    totals but leaves Sharpe, hit rate and every attribution SHARE untouched.

    Tie-out, not resemblance: for a pair of SPOT legs on the PCA grid this is
    ``pca_rv.curve_weights(short, long, neutralize=("PC1",))`` scaled by
    ``-dv01``. ``curve_weights`` returns ``{short: -v1_long/v1_short, long: 1}``;
    multiply by ``-dv01`` and the short leg reads ``+dv01 * v1_long/v1_short``,
    which is the line above. ``tests/test_convexity_rv_factor_neutral.py`` pins
    that against a real ``make_pca_rv_builder`` fit rather than against this
    docstring.

    Raises when the front leg has no exposure to the neutralised PC -- the ratio
    is then undefined, and returning an enormous weight instead of raising is how
    an ill-posed hedge reaches a P&L table looking like a result.
    """
    ks = list(neutralize)
    if len(ks) != 1:
        raise ValueError(
            f"pc1_neutral is a TWO-leg trade and can zero exactly one factor; "
            f"got neutralize={ks}. Use pc12_neutral (three legs) for two.")
    for leg in (front, back):
        if leg not in loadings.index:
            raise KeyError(f"no loadings for leg {leg!r}")
    k = ks[0]
    v_f = float(loadings.loc[front, k])
    v_b = float(loadings.loc[back, k])
    scale = max(abs(v_f), abs(v_b))
    if scale <= 0 or abs(v_f) < 1e-6 * scale:
        raise np.linalg.LinAlgError(
            f"pc1_neutral solve for {front}/{back} is degenerate: the front leg's "
            f"{k} exposure is {v_f:.6g} against a package scale of {scale:.6g}, "
            "so no finite front size zeroes the factor")
    r_b = -float(dv01)
    return {front: -r_b * v_b / v_f, back: r_b}


def pc12_neutral_weights(front: str, back: str, hedge: str,
                         loadings: pd.DataFrame, *, dv01: float = UNIT_DV01,
                         neutralize: Sequence[str] = ("PC1", "PC2"),
                         ) -> Dict[str, float]:
    """Three legs sized so both neutralised PCs come out at exactly zero.

    Held fixed: the BACK leg at ``-dv01``. Two constraints plus one
    normalisation give exactly two free weights, which is why the package needs
    a third leg at all -- a two-leg package has one free ratio and can zero one
    factor, not two. Zeroing PC1 alone is what
    ``pca_rv.curve_weights(short, long, neutralize=("PC1",))`` does, and the
    attribution showed it is not enough: three of the four structures carry more
    PC1 variance than PC2.

    The normalisation is stated rather than buried. Holding the back leg at
    ``-dv01`` keeps the RECEIVED long-dated leg -- the one carrying the convexity
    -- at the incumbent's size, so the two books are anchored on the same
    position and everything that differs between them is the hedge. Any other
    normalisation is a rescale, and because every P&L here is exactly linear in
    the weights, a rescale moves totals but leaves Sharpe, hit rate and every
    attribution SHARE untouched. :func:`gamma_match_scale` reports the
    equal-convexity alternative as a multiplier instead of a fourth backtest.

    Raises on a singular or ill-conditioned solve. Two free legs whose loading
    vectors are collinear in the neutralised subspace cannot span it, and
    returning enormous weights rather than raising is how an ill-posed hedge
    reaches a P&L table looking like a result.
    """
    ks = list(neutralize)
    for leg in (front, back, hedge):
        if leg not in loadings.index:
            raise KeyError(f"no loadings for leg {leg!r}")
    if hedge in (front, back):
        raise ValueError(f"hedge leg {hedge!r} is already a leg of the package")
    f_f = loadings.loc[front, ks].to_numpy(float)
    f_b = loadings.loc[back, ks].to_numpy(float)
    f_h = loadings.loc[hedge, ks].to_numpy(float)
    r_b = -float(dv01)
    M = np.column_stack([f_f, f_h])
    cond = float(np.linalg.cond(M))
    if cond > 1e6:
        raise np.linalg.LinAlgError(
            f"pc12_neutral solve for {front}/{back} with hedge {hedge} is "
            f"ill-conditioned (cond={cond:.1e}); the two free legs do not span "
            f"{ks}")
    r_f, r_h = np.linalg.solve(M, -r_b * f_b)
    return {front: float(r_f), back: r_b, hedge: float(r_h)}


def slope_instrument_weights(size: float = 1.0) -> Dict[str, float]:
    """:data:`SLOPE_INSTRUMENT` scaled to ``size`` dollars of DV01 per leg."""
    out: Dict[str, float] = {}
    for leg, w in SLOPE_INSTRUMENT:
        out[leg] = out.get(leg, 0.0) + float(w) * float(size)
    return out


def slope_hedge_ratio(beta_usd_per_pc2: float, loadings: pd.DataFrame) -> float:
    """Instrument size, $ of DV01 per leg, that cancels ``beta_usd_per_pc2``.

    ``beta`` is the book's MEASURED dollars per unit of PC2, from a trailing
    regression of its own daily P&L. The instrument's PC2 exposure per $1 of
    size is ``sum_L w_L * f_L,PC2`` from the loadings; the hedge is minus their
    ratio.

    Mixing a measured numerator with an analytic denominator is deliberate. The
    numerator is the quantity in doubt -- a package's realised slope exposure
    drifts as its cohorts age -- while the denominator is a fresh at-market
    spread whose exposure at inception is exactly what the loadings say it is.
    """
    f2 = float(sum(w * float(loadings.loc[leg, "PC2"])
                   for leg, w in slope_instrument_weights(1.0).items()))
    if abs(f2) < 1e-12:
        raise ValueError("slope instrument has no PC2 exposure")
    return -float(beta_usd_per_pc2) / f2


def package_pc_exposure(weights: Mapping[str, float], loadings: pd.DataFrame
                        ) -> pd.Series:
    """A weighted leg package's PC exposure, $ per unit of PC score."""
    idx = loadings.columns
    out = pd.Series(0.0, index=idx, dtype=float)
    for leg, r in weights.items():
        out = out + float(r) * loadings.loc[leg, idx].astype(float)
    return out


def package_variance_shares(weights: Mapping[str, float], loadings: pd.DataFrame,
                            eigenvalues: pd.Series) -> pd.Series:
    """Share of the package's own factor variance coming from each PC.

    ``f_k^2 * lambda_k / sum_j f_j^2 * lambda_j`` -- the same decomposition
    ``factor_attribution.sizing_diagnosis`` reports, and the column the whole
    retarget rests on. It exists because a dollars-per-unit exposure is NOT
    comparable across PCs: PC1 carries most of the daily variance and PC3 under
    1%, so a package can look "mostly slope" in dollars and be mostly level in
    risk. Reported for every sizing so a successful hedge is visible as the
    neutralised PC's share going to zero rather than as a claim.
    """
    f = package_pc_exposure(weights, loadings).astype(float)
    lam = eigenvalues.reindex(f.index).astype(float)
    contrib = (f.to_numpy() ** 2) * lam.to_numpy()
    tot = float(np.nansum(contrib))
    out = contrib / tot if tot > 0 else np.full(len(contrib), np.nan)
    return pd.Series(out, index=f.index, name="variance_share")


def gamma_match_scale(weights: Mapping[str, float], reference: Mapping[str, float],
                      gamma: Mapping[str, float]) -> float:
    """Multiplier giving ``weights`` the same dollar gamma as ``reference``.

    Every P&L here is exactly linear in the weights, so scaling a sizing by this
    number scales its totals, its costs and its factor contributions by the same
    amount and leaves Sharpe, hit rate, R^2 and every attribution SHARE
    unchanged. That is why the comparison runs at natural scale and the
    gamma-matched view is a reported multiplier, not a fourth backtest.
    """
    g_w = float(sum(r * float(gamma.get(l, np.nan)) for l, r in weights.items()))
    g_r = float(sum(r * float(gamma.get(l, np.nan)) for l, r in reference.items()))
    if not np.isfinite(g_w) or abs(g_w) < 1e-12:
        return float("nan")
    return g_r / g_w


# ===========================================================================
# 5. Walk-forward loadings -- the weights a trader could actually have used
# ===========================================================================
def _match_pcs(V_new: np.ndarray, V_ref: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Permutation and signs mapping ``V_new``'s columns onto ``V_ref``'s roles.

    ``pca_rv.align_eigenvectors`` fixes SIGN flips, which is the common case and
    not the dangerous one. The dangerous case is a ROTATION: on a short early
    window PC2 and PC3 can swap rank, and an eigenvalue-ordered pick would then
    call curvature "slope" and hedge the wrong factor with the right arithmetic.
    So columns are matched greedily on ``|cos|`` to the reference first, and only
    then sign-aligned. Every fit's labels are re-tested structurally afterwards
    by ``factor_attribution.classify_pcs``; nothing here trusts the order.
    """
    k = V_ref.shape[1]
    C = np.abs(V_new.T @ V_ref)              # new x ref
    perm = np.full(k, -1, dtype=int)
    used = set()
    for _ in range(k):
        i, j = np.unravel_index(np.argmax(C), C.shape)
        perm[j] = i
        used.add(i)
        C[i, :] = -1.0
        C[:, j] = -1.0
    signs = np.array([1.0 if (V_new[:, perm[j]] @ V_ref[:, j]) >= 0 else -1.0
                      for j in range(k)])
    return perm, signs


def walk_forward_loadings(rate_panel: pd.DataFrame, cfg: fa.FactorConfig,
                          dates: Sequence[Any], legs: Sequence[str], *,
                          min_fit_days: int = 250, hard_floor: int = 15,
                          n_pcs: int = 3,
                          ) -> Tuple[Dict[pd.Timestamp, pd.DataFrame], pd.DataFrame,
                                     Dict[pd.Timestamp, pd.DataFrame]]:
    """Leg PC loadings estimated on data strictly BEFORE each date.

    Fitting the PCA on the full 2019-2026 sample is right for the attribution
    report -- that is a description of what happened -- and would be look-ahead
    here, because a 2019 cohort would be sized with 2026's covariance. So the
    fit is expanding: at each cohort entry, everything the curve had printed by
    the previous close, and nothing after.

    Cohorts earlier than ``min_fit_days`` are NOT dropped. Dropping them would
    change the trade set and stop this being a sizing comparison at all; they are
    sized on the shortest admissible window and flagged ``short_fit`` so the
    reader can see which rows carry a thin covariance.

    ``hard_floor`` is the point below which a fit is refused outright, and it has
    to be low. Cohort 0 enters 2019-02-01 while the panel starts 2019-01-02, so
    it has roughly twenty daily changes and no amount of care changes that:
    ``FactorConfig.start`` is the first day the full 2Y..50Y grid prices locally,
    so the window cannot be extended backwards. Twenty changes on eleven tenors
    identify PC1 -- which is all ``pc1_neutral``, the headline sizing, consumes,
    and PC1 is the eigenvector most stable on a thin sample. They do NOT reliably
    separate PC2 from PC3, which is why ``label_ok`` is expected to read False on
    the earliest fits and why the notebook re-scores every book excluding cohorts
    under ``min_fit_days``. The flag is the mechanism working, not a bug to hide.

    Returns ``(loadings_by_date, diagnostics, V_by_date)``.

    ``V_by_date`` is the aligned eigenvector matrix (tenors x PC1..PCn) at each
    date, and it exists so :func:`walk_forward_scores` can build the trailing
    ``dPC2`` for ``slope_beta_hedged`` from a factor DEFINITION the trader had at
    the rebalance. Regressing on the full-sample scores would leave a look-ahead
    in the one sizing whose whole claim is that it uses only trailing data.

    The diagnostics frame carries the fit length, the explained-variance split,
    the ``classify_pcs`` label of each PC, and ``label_ok`` -- False on any date
    where the structural test does not return level/slope/curvature, which is the
    failure this function exists to make visible rather than to hide.
    """
    from RVUtils.pca_rv import align_eigenvectors

    panel = rate_panel.sort_index()
    cols = [t for t in cfg.tenors if t in panel.columns]
    out: Dict[pd.Timestamp, pd.DataFrame] = {}
    V_by_date: Dict[pd.Timestamp, pd.DataFrame] = {}
    diag: List[Dict[str, Any]] = []
    V_ref: Optional[np.ndarray] = None
    for d in pd.to_datetime(list(dates)):
        hist = panel.loc[panel.index < d, cols].dropna(how="any")
        short = len(hist) < int(min_fit_days)
        if len(hist) < int(hard_floor):
            raise ValueError(
                f"{d.date()}: only {len(hist)} usable curve days before it, below "
                f"the hard floor of {hard_floor}")
        fm_d = fa.fit_factor_model(hist, cfg)
        V = fm_d.loadings.to_numpy(float)[:, :n_pcs]
        if V_ref is None:
            V_ref = V.copy()
        else:
            perm, signs = _match_pcs(V, V_ref)
            V = V[:, perm] * signs
            V = align_eigenvectors(V, V_ref)
            V_ref = V.copy()
        lam = fm_d.model.eigenvalues.to_numpy(float)[:n_pcs]
        pcs = [f"PC{i + 1}" for i in range(n_pcs)]
        model = dataclasses.replace(
            fm_d,
            model=dataclasses.replace(
                fm_d.model,
                loadings=pd.DataFrame(V, index=fm_d.model.columns, columns=pcs),
                eigenvalues=pd.Series(lam, index=pcs)),
        )
        lab = fa.classify_pcs(model.loadings, model.tenors, n=n_pcs)
        rates_bp = hist.mul(100.0).mean().to_dict()
        out[d] = leg_pc_loadings(model, legs, rates_bp=rates_bp, n_pcs=n_pcs)
        V_by_date[d] = pd.DataFrame(V, index=list(model.model.columns), columns=pcs)
        ok = list(lab["label"].values[:3]) == ["level", "slope", "curvature"]
        diag.append({
            "date": d, "n_fit_days": int(len(hist)), "short_fit": bool(short),
            **{f"label_{p}": lab.loc[p, "label"] for p in pcs},
            **{f"ev_{p}": float(lam[i] / lam.sum()) for i, p in enumerate(pcs)},
            "label_ok": bool(ok),
        })
    return out, pd.DataFrame(diag), V_by_date


def walk_forward_scores(rate_panel: pd.DataFrame, cfg: fa.FactorConfig,
                        V: pd.DataFrame, upto: Any, *, window: int) -> pd.DataFrame:
    """Trailing PC scores on ONE date's walk-forward eigenvectors.

    ``dR_t @ V_d`` over the last ``window`` changes strictly before ``upto``,
    with ``V_d`` the basis fitted at ``upto`` -- so the regressor
    ``slope_beta_path`` sees at a rebalance is defined by information the trader
    had at that rebalance, not by the full-sample eigenvectors.

    This matters more than it looks. The BETA is trailing in the draft already;
    what was not trailing was the FACTOR the beta is a beta to. A hedge sized
    against a definition of "slope" that will only be estimable in 2026 is a
    look-ahead however carefully the window is truncated.
    """
    cols = [t for t in cfg.tenors if t in rate_panel.columns]
    lvl = (rate_panel[cols] * 100.0).sort_index().dropna(how="any")
    d_bp = lvl.diff().dropna(how="any")
    d_bp = d_bp.loc[d_bp.index < pd.Timestamp(upto)]
    if window and len(d_bp) > int(window):
        d_bp = d_bp.iloc[-int(window):]
    Vv = V.reindex(cols).to_numpy(float)
    return pd.DataFrame(d_bp.to_numpy(float) @ Vv, index=d_bp.index,
                        columns=list(V.columns))


def full_sample_loadings(rate_panel: pd.DataFrame, cfg: fa.FactorConfig,
                         legs: Sequence[str], n_pcs: int = 3) -> pd.DataFrame:
    """Leg loadings on the attribution report's own full-window basis.

    Look-ahead by construction, and reported for exactly that reason: the gap
    between this and :func:`walk_forward_loadings` IS the cost of not knowing
    the covariance in advance. It is never the sizing that gets picked.
    """
    fm = fa.fit_factor_model(rate_panel, cfg)
    return leg_pc_loadings(fm, legs, n_pcs=n_pcs)


# ===========================================================================
# 6. Per-cohort weights
# ===========================================================================
def cohort_weights(schedule: pd.DataFrame,
                   structures: Sequence[Tuple[str, str, str]],
                   loadings_by_date: Mapping[Any, pd.DataFrame],
                   *, hedge_leg: str = HEDGE_LEG, dv01: float = UNIT_DV01,
                   neutralize: Sequence[str] = ("PC1", "PC2"),
                   sizings: Sequence[str] = STATIC_SIZINGS,
                   ) -> pd.DataFrame:
    """Long frame of ``(structure, sizing, cohort, entry, exit, leg, dv01)``.

    ``schedule`` is any leg's cohort table -- they are identical by
    :func:`assert_shared_schedule` -- so the trade set is the same 91 cohorts on
    the same 1-year holds for every sizing. That identity is the experiment: the
    only thing that differs between two rows of the comparison is the weight.

    ``slope_beta_hedged`` is absent here on purpose. Its base package IS
    ``dv01_neutral``; what it adds is a MONTHLY overlay, which does not fit a
    per-cohort weight table and is composed by :func:`compose_overlay`.
    """
    rows: List[Dict[str, Any]] = []
    for _, c in schedule.iterrows():
        entry = pd.Timestamp(c["entry"])
        L = loadings_by_date[entry] if entry in loadings_by_date else None
        for label, front, back in structures:
            w_by_sizing: Dict[str, Dict[str, float]] = {}
            if "dv01_neutral" in sizings:
                w_by_sizing["dv01_neutral"] = dv01_neutral_weights(front, back, dv01)
            if "pc1_neutral" in sizings:
                if L is None:
                    raise KeyError(f"no loadings for cohort entry {entry.date()}")
                w_by_sizing["pc1_neutral"] = pc1_neutral_weights(
                    front, back, L, dv01=dv01, neutralize=(neutralize[0],))
            if "pc12_neutral" in sizings:
                if L is None:
                    raise KeyError(f"no loadings for cohort entry {entry.date()}")
                w_by_sizing["pc12_neutral"] = pc12_neutral_weights(
                    front, back, hedge_leg, L, dv01=dv01, neutralize=neutralize)
            for sizing, w in w_by_sizing.items():
                for leg, r in w.items():
                    rows.append({"structure": label, "sizing": sizing,
                                 "cohort": int(c["cohort"]), "entry": entry,
                                 "exit": pd.Timestamp(c["exit"]) if pd.notna(c["exit"])
                                 else pd.NaT,
                                 "closed": bool(c["closed"]),
                                 "leg": leg, "dv01": float(r)})
    return pd.DataFrame(rows)


# ===========================================================================
# 7. Composition -- every sizing from the same eight mark matrices
# ===========================================================================
def leg_cost_bp_one_way(cfg: s1.Strat1Config) -> float:
    """Per-LEG one-way cost in bp of that leg's own DV01.

    ``Strat1Config.cost_bp_one_way`` is documented as the cost per LEG-PAIR, so
    half of it is the cost per leg. At the committed 0.5 bp that is 0.25 bp per
    leg, and a two-leg package at $100k each pays
    ``2 * 0.25 * 200,000 = $100,000`` per round trip -- exactly the flat fee
    ``build_backtest`` charges. The generalisation is therefore not a new cost
    assumption; it is the same assumption written so a three-leg package can
    pay for three legs.
    """
    return float(cfg.cost_bp_one_way) / 2.0


def compose_book(leg_runs: Mapping[str, "LegRun"], weights: pd.DataFrame,
                 *, cfg: Optional[s1.Strat1Config] = None,
                 cost_bp_one_way: Optional[float] = None,
                 ) -> Tuple[pd.Series, pd.DataFrame]:
    """One (structure, sizing) book's daily equity and per-cohort round trips.

    ``weights`` is the subset of :func:`cohort_weights` for that pair. The
    arithmetic is the linearity the whole design rests on::

        equity(t) = sum_k sum_L (r_{k,L} / UNIT_DV01) * contribution_{L,k}(t)
                  - sum_k 2 * c_leg * (sum_L |r_{k,L}|) * 1{cohort k closed by t}

    Returns ``(equity_usd, book)``. ``book`` is deliberately
    ``strat1_longend_listed.book_stats``-compatible -- same column names,
    ``gate_direction`` pinned to +1 because every sizing trades the always-on
    flattener -- so the statistics are computed by the module that already has
    the overlap-adjusted t-stat and the deflated Sharpe wired in, rather than by
    a second implementation of them here.
    """
    cfg = cfg or _default_cfg()
    c_leg = float(cost_bp_one_way if cost_bp_one_way is not None
                  else leg_cost_bp_one_way(cfg))
    dv01_ref = float(cfg.package_dv01)
    legs = sorted(set(weights["leg"]))
    contrib = {lg: leg_runs[lg].contribution() for lg in legs}
    idx = contrib[legs[0]].index

    equity = pd.Series(0.0, index=idx)
    rows: List[Dict[str, Any]] = []
    for k, g in weights.groupby("cohort", sort=True):
        k = int(k)
        gross_dv01 = float(g["dv01"].abs().sum())
        fee = 2.0 * c_leg * gross_dv01
        closed = bool(g["closed"].iloc[0])
        exit_ = g["exit"].iloc[0]
        col = pd.Series(0.0, index=idx)
        realized = 0.0
        for _, r in g.iterrows():
            lg, w = str(r["leg"]), float(r["dv01"]) / UNIT_DV01
            col = col + w * contrib[lg][k]
            if closed:
                cr = leg_runs[lg].cohorts
                realized += w * float(cr.loc[cr["cohort"] == k, "gross_pnl_ccy"].iloc[0])
        step = ((idx >= pd.Timestamp(exit_)).astype(float) if closed
                else np.zeros(len(idx)))
        equity = equity + col - fee * step
        rows.append({
            "tag": f"{g['structure'].iloc[0]}_c{k:04d}",
            "structure": g["structure"].iloc[0], "sizing": g["sizing"].iloc[0],
            "cohort": k, "entry": g["entry"].iloc[0],
            "exit": pd.Timestamp(exit_) if closed else pd.NaT,
            "gate_direction": 1.0, "traded": True,
            "closed": closed, "gate_closed": closed,
            "gross_dv01": gross_dv01,
            "gross_bp": realized / dv01_ref if closed else np.nan,
            "cost_bp": fee / dv01_ref,
            "net_bp": (realized - fee) / dv01_ref if closed else np.nan,
            "marked_bp": np.nan if closed else float(col.iloc[-1]) / dv01_ref,
        })
    return equity, pd.DataFrame(rows)


def _default_cfg() -> s1.Strat1Config:
    from RVUtils.ConvexityRV import strat1_longend_listed as ll
    return ll.strat1_config()


def live_packages(schedule: pd.DataFrame, index: pd.DatetimeIndex) -> pd.Series:
    """Number of cohorts live on each mark, on the ``(entry, exit]`` convention.

    The engine adds a position at ``entry`` with a zero mark, so the first day it
    can move the equity is ``entry + 1`` -- the same half-open convention
    ``factor_attribution.interval_factors`` uses, and the reason the two agree
    about which factor move belongs to which day.
    """
    out = pd.Series(0.0, index=index)
    for _, r in schedule.iterrows():
        e = pd.Timestamp(r["entry"])
        x = pd.Timestamp(r["exit"]) if pd.notna(r["exit"]) else index[-1]
        out.loc[(index > e) & (index <= x)] += 1.0
    return out


# ===========================================================================
# 8. The slope-beta overlay
# ===========================================================================
def slope_beta_path(gross_equity: pd.Series, weight: pd.Series,
                    scores_at: Mapping[Any, pd.DataFrame],
                    rebalance_dates: Sequence[Any], *, window: int = 252,
                    pc: str = "PC2") -> pd.DataFrame:
    """Trailing beta of the book's own daily P&L on PC2, per package.

    At each rebalance the regression is

        ``y_t = a + b * (w_t * dPC2_t) + e_t``

    over the ``window`` scored days STRICTLY BEFORE that date -- the same
    ``w_t``-signed design ``factor_attribution.daily_design`` uses, so ``b`` is
    dollars per unit of PC2 per LIVE PACKAGE and is directly comparable with the
    analytic ``f_PC2`` of one package.

    ``scores_at`` maps each rebalance date to the trailing factor scores computed
    on THAT DATE'S walk-forward eigenvectors -- :func:`walk_forward_scores`. The
    draft regressed on ``fm.scores``, the full-sample scores, which left a
    look-ahead that truncating the window does not fix: the beta was trailing but
    the definition of the factor it was a beta TO came from the end of the
    sample. Everything the overlay consumes is now strictly historical.

    Regressed on GROSS P&L, not net: the cost model books a $100k step on the
    dozen days a cohort unwinds, and a step function is not a factor exposure --
    including it would bias the beta by whatever the curve happened to do on
    unwind days.

    Returns one row per rebalance with the beta, its t-stat, the R^2 and the
    number of days the window actually found. Early rebalances have short
    windows; they are flagged, not dropped, because dropping them would leave
    the first year of cohorts unhedged and turn a sizing comparison into a
    comparison of two different trade sets.
    """
    import statsmodels.api as sm

    y_all = gross_equity.sort_index().diff().dropna()
    w_all = weight.reindex(y_all.index).astype(float).fillna(0.0)

    rows: List[Dict[str, Any]] = []
    for d in pd.to_datetime(list(rebalance_dates)):
        sc = scores_at.get(d)
        if sc is None or pc not in getattr(sc, "columns", []):
            rows.append({"date": d, "n_days": 0, "beta_usd_per_pc2": 0.0,
                         "t_stat": np.nan, "r2": np.nan, "short_window": True})
            continue
        idx = y_all.index.intersection(pd.DatetimeIndex(sc.index))
        idx = idx[idx < d]
        w = w_all.reindex(idx)
        idx = idx[(w != 0.0).to_numpy()]
        if len(idx) > int(window):
            idx = idx[-int(window):]
        sub_y = y_all.reindex(idx).to_numpy(float)
        sub_x = (w_all.reindex(idx).to_numpy(float)
                 * sc.loc[idx, pc].to_numpy(float))
        n = int(len(sub_y))
        if n < 20 or not np.isfinite(sub_x).all() or float(np.std(sub_x, ddof=1)) <= 0:
            rows.append({"date": d, "n_days": n, "beta_usd_per_pc2": 0.0,
                         "t_stat": np.nan, "r2": np.nan, "short_window": True})
            continue
        fit = sm.OLS(sub_y, sm.add_constant(sub_x)).fit()
        rows.append({"date": d, "n_days": n,
                     "beta_usd_per_pc2": float(np.asarray(fit.params)[1]),
                     "t_stat": float(np.asarray(fit.tvalues)[1]),
                     "r2": float(fit.rsquared),
                     "short_window": n < int(window)})
    return pd.DataFrame(rows)


def compose_overlay(leg_runs: Mapping[str, "LegRun"], schedule: pd.DataFrame,
                    betas: pd.DataFrame,
                    loadings_by_date: Mapping[Any, pd.DataFrame], *,
                    cfg: Optional[s1.Strat1Config] = None,
                    cost_bp_one_way: Optional[float] = None,
                    ) -> Tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    """The monthly slope hedge, held PER PACKAGE, from the same leg runs.

    Each live cohort carries its own overlay: at every monthly rebalance it
    holds ``h_m = -beta_m / f2_instrument`` of :data:`SLOPE_INSTRUMENT`, sized
    per package. In aggregate that is one hedge of ``n_live * h_m``, and because
    cost is linear in size the two bookkeepings charge the same total -- but the
    per-package version gives every cohort a well-defined round trip, so
    Sharpe-per-trade and hit rate are computable for this sizing on exactly the
    same basis as the other two.

    The overlay's monthly P&L is read off the leg runs themselves. A position
    opened at cohort date ``e_m`` has, as its mark at any later ``t``, exactly
    the P&L of a position opened at ``e_m`` and closed at ``t``; a one-month
    hedge is therefore the ``(e_m, e_{m+1}]`` slice of the cohort opened at
    ``e_m``. Nothing is re-priced and nothing is interpolated.

    Cost is a FULL round trip every month on ``|h_m|`` of each of the
    instrument's two legs. That is deliberately the expensive reading: the
    overlay as constructed opens a fresh at-market spread each month rather than
    adjusting a held one, so it pays to get out and back in. It is the honest
    cost of the thing that was actually simulated, and
    :func:`overlay_cost_sensitivity` reports the cheaper delta-traded reading
    beside it.

    Returns ``(overlay_equity, per_cohort, hedge_path)``.
    """
    cfg = cfg or _default_cfg()
    c_leg = float(cost_bp_one_way if cost_bp_one_way is not None
                  else leg_cost_bp_one_way(cfg))
    inst_w = slope_instrument_weights(1.0)
    marks = {lg: leg_runs[lg].open_mark() for lg in inst_w}
    idx = leg_runs[next(iter(inst_w))].index

    sched = schedule.sort_values("cohort").reset_index(drop=True)
    entries = [pd.Timestamp(e) for e in sched["entry"]]
    beta_at = {pd.Timestamp(d): float(b) for d, b in
               zip(betas["date"], betas["beta_usd_per_pc2"])}

    hedge_rows: List[Dict[str, Any]] = []
    h_by_month: Dict[int, float] = {}
    for m, e in enumerate(entries):
        L = loadings_by_date[e]
        b = beta_at.get(e, 0.0)
        h = slope_hedge_ratio(b, L) if np.isfinite(b) else 0.0
        h_by_month[m] = float(h)
        hedge_rows.append({"cohort": m, "date": e, "beta_usd_per_pc2": b,
                           "hedge_dv01_per_leg": float(h)})

    overlay = pd.Series(0.0, index=idx)
    per: List[Dict[str, Any]] = []
    for _, c in sched.iterrows():
        k = int(c["cohort"])
        x = pd.Timestamp(c["exit"]) if pd.notna(c["exit"]) else idx[-1]
        pnl_k = 0.0
        cost_k = 0.0
        for m in range(k, len(entries)):
            a = entries[m]
            if a >= x:
                break
            nxt = entries[m + 1] if m + 1 < len(entries) else idx[-1]
            b_end = min(nxt, x)
            h = h_by_month[m]
            if h == 0.0:
                continue
            slice_ = pd.Series(0.0, index=idx)
            for lg, w in inst_w.items():
                col = marks[lg][m]
                slice_ = slice_ + w * (col - float(col.loc[a])) / UNIT_DV01
            seg = slice_.copy()
            seg.loc[idx <= a] = 0.0
            seg.loc[idx > b_end] = float(slice_.loc[b_end])
            fee = 2.0 * c_leg * sum(abs(h * w) for w in inst_w.values())
            step = (idx > b_end).astype(float)
            overlay = overlay + h * seg - fee * step
            pnl_k += h * float(slice_.loc[b_end])
            cost_k += fee
        per.append({"cohort": k, "structure": c.get("structure", ""),
                    "entry": c["entry"], "exit": c["exit"],
                    "closed": bool(c["closed"]),
                    "overlay_gross_usd": pnl_k, "overlay_cost_usd": cost_k,
                    "overlay_net_usd": pnl_k - cost_k})
    return overlay, pd.DataFrame(per), pd.DataFrame(hedge_rows)


def add_overlay(base_equity: pd.Series, base_book: pd.DataFrame,
                overlay_equity: pd.Series, overlay_book: pd.DataFrame,
                *, cfg: Optional[s1.Strat1Config] = None) -> Tuple[pd.Series, pd.DataFrame]:
    """``slope_beta_hedged`` = the incumbent package plus its overlay.

    Both pieces are already net of their own cost, so the sum is net of both --
    which is the number the question asks for: the edge NET of the hedge's own
    cost, not gross of it.
    """
    cfg = cfg or _default_cfg()
    dv01 = float(cfg.package_dv01)
    eq = base_equity.add(overlay_equity.reindex(base_equity.index).fillna(0.0),
                         fill_value=0.0)
    ov = overlay_book.set_index("cohort")
    book = base_book.copy()
    book["sizing"] = "slope_beta_hedged"
    g = ov["overlay_gross_usd"].reindex(book["cohort"]).to_numpy(float)
    c = ov["overlay_cost_usd"].reindex(book["cohort"]).to_numpy(float)
    book["overlay_gross_bp"] = g / dv01
    book["overlay_cost_bp"] = c / dv01
    book["gross_bp"] = book["gross_bp"].to_numpy(float) + g / dv01
    book["cost_bp"] = book["cost_bp"].to_numpy(float) + c / dv01
    book["net_bp"] = np.where(book["closed"].to_numpy(bool),
                              book["gross_bp"].to_numpy(float)
                              - book["cost_bp"].to_numpy(float), np.nan)
    return eq, book


# ===========================================================================
# 9. Certification -- the composition against genuine engine runs
# ===========================================================================
def certify_dv01_neutral(leg_runs: Mapping[str, "LegRun"], data_dir: Any,
                         structures: Sequence[Tuple[str, str, str]] = fa.STRAT1_STRUCTURES,
                         *, cfg: Optional[s1.Strat1Config] = None) -> pd.DataFrame:
    """Compose the INCUMBENT from leg runs and compare to the stored engine runs.

    ``strat1_le_unit_equity_<structure>.parquet`` are four genuine
    ``QueryDrivenBacktest`` passes of the two-leg DV01-neutral package, produced
    by a different code path (``strat1_longend_listed``) before any of this
    module existed. Rebuilding them as ``front - back`` out of the per-leg mark
    matrices, and charging the fee with :func:`leg_cost_bp_one_way` rather than
    the engine's flat per-cohort figure, tests three claims at once:

    * that swap NPV is linear in ``bpv``, so a package IS the sum of its legs;
    * that the leg runs share the stored runs' cohort schedule to the day;
    * that the generalised per-leg cost model reproduces the two-leg flat fee
      exactly, which is what lets a three-leg package be priced at all.

    The two numbers reported are the ones ``strat1_longend_listed`` certifies
    with -- terminal gap and correlation of daily changes -- because a
    composition can hit the terminal level by luck while taking a different path,
    and only the daily correlation refuses to let that pass.
    """
    cfg = cfg or _default_cfg()
    d = pathlib.Path(data_dir)
    c_leg = leg_cost_bp_one_way(cfg)
    rows: List[Dict[str, Any]] = []
    for label, front, back in structures:
        safe = safe_leg(label)
        p_eq = d / f"strat1_le_unit_equity_{safe}.parquet"
        if not p_eq.exists():
            continue
        eng = pd.read_parquet(p_eq)["equity_usd"].astype(float)
        eng.index = pd.to_datetime(eng.index)
        eng = eng.sort_index()

        sched = leg_runs[front].cohorts
        w = pd.DataFrame([
            {"structure": label, "sizing": "dv01_neutral", "cohort": int(c["cohort"]),
             "entry": pd.Timestamp(c["entry"]),
             "exit": pd.Timestamp(c["exit"]) if pd.notna(c["exit"]) else pd.NaT,
             "closed": bool(c["closed"]), "leg": leg, "dv01": r}
            for _, c in sched.iterrows()
            for leg, r in dv01_neutral_weights(front, back, cfg.package_dv01).items()])
        comp, _book = compose_book(leg_runs, w, cfg=cfg, cost_bp_one_way=c_leg)

        rows.append(certify_engine(eng, comp, label=label, sizing="dv01_neutral",
                                   cfg=cfg))
    return pd.DataFrame(rows)


def certify_engine(engine_equity: pd.Series, composed_equity: pd.Series, *,
                   label: str, sizing: str,
                   cfg: Optional[s1.Strat1Config] = None) -> Dict[str, Any]:
    """Composed daily equity against a GENUINE engine run of the same book.

    A thin adapter onto ``strat1_longend_listed.certify_composition`` rather than
    a second implementation of it: the certification arithmetic is already
    committed, already tested, and already the number every other study in this
    package quotes, and two implementations of a tolerance check is how the two
    quietly stop agreeing.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    out = ll.certify_composition(engine_equity, composed_equity, label=label,
                                 mode=sizing, cfg=cfg or _default_cfg())
    out["sizing"] = out.pop("gate_mode")
    return out


# ===========================================================================
# 10. The retarget, re-measured
# ===========================================================================
def dominant_factor_table(fm: fa.FactorModel,
                          structures: Sequence[Tuple[str, str, str]] = fa.STRAT1_STRUCTURES,
                          *, dv01: float = UNIT_DV01, n_pcs: int = 3) -> pd.DataFrame:
    """Which factor each DV01-neutral package is actually exposed to, re-measured.

    :data:`ATTRIBUTION_VARIANCE_SHARES` is copied from the committed attribution
    run and is the reason this study was retargeted. Copied numbers rot, so this
    recomputes all of them off the shared ``FactorModel`` and reports both, with
    the gap. If they disagree, the retarget's premise is what is wrong and every
    table below it needs re-reading -- which is exactly why the check is here
    rather than in a comment.

    ``pc1_leakage`` is the quieter half of the finding: the share of a same-size
    OUTRIGHT's level exposure that survives the DV01-neutral construction. It is
    what makes ``pc1_neutral`` a different trade rather than a rounding of the
    incumbent.
    """
    rates_bp = fm.rates_bp.mean().to_dict()
    lam = fm.model.eigenvalues.reindex(fm.pc_cols(n_pcs)).astype(float)
    legs = sorted({l for _lab, f, b in structures for l in (f, b)})
    L = leg_pc_loadings(fm, legs, rates_bp=rates_bp, n_pcs=n_pcs)
    rows: List[Dict[str, Any]] = []
    for label, front, back in structures:
        w = dv01_neutral_weights(front, back, dv01)
        f = package_pc_exposure(w, L)
        vs = package_variance_shares(w, L, lam)
        outright = package_pc_exposure({back: dv01}, L) if back in L.index else None
        prior = ATTRIBUTION_VARIANCE_SHARES.get(label, {})
        row = {
            "structure": label,
            "f_level_usd": float(f["PC1"]), "f_slope_usd": float(f["PC2"]),
            "f_curv_usd": float(f["PC3"]),
            "var_level": float(vs["PC1"]), "var_slope": float(vs["PC2"]),
            "var_curv": float(vs["PC3"]),
            "prior_var_level": prior.get("level", np.nan),
            "prior_var_slope": prior.get("slope", np.nan),
            "prior_var_curv": prior.get("curvature", np.nan),
            "dominant": str(pd.Series({"level": vs["PC1"], "slope": vs["PC2"],
                                       "curvature": vs["PC3"]}).idxmax()),
            "headline_sizing": HEADLINE_SIZING.get(label, ""),
            "pc1_leakage_vs_outright": (abs(float(f["PC1"])) / abs(float(outright["PC1"]))
                                        if outright is not None
                                        and float(outright["PC1"]) else np.nan),
        }
        row["max_abs_prior_gap"] = float(np.nanmax([
            abs(row["var_level"] - row["prior_var_level"]),
            abs(row["var_slope"] - row["prior_var_slope"]),
            abs(row["var_curv"] - row["prior_var_curv"])]))
        rows.append(row)
    return pd.DataFrame(rows)


def residual_exposure_table(weights: pd.DataFrame, fm: fa.FactorModel, *,
                            n_pcs: int = 3) -> pd.DataFrame:
    """What each (structure, sizing) is left exposed to, on the MEASUREMENT basis.

    The weights come off the walk-forward fits -- that is what a trader could
    have used -- but the exposures are measured on the committed full-sample
    ``FactorModel``, the one the attribution report used. Measuring a
    walk-forward-weighted package on its own walk-forward basis would report
    ``f_PC1 = 0`` by construction and prove nothing at all; the question is
    whether a weight chosen on 2019-2022 information is still level-neutral when
    scored on the ruler everything else in this package is scored on.

    Per-cohort exposures are computed and then averaged, rather than the average
    weight's exposure being computed once, because variance shares are not linear
    in the weights and "the typical cohort's risk mix" is the quantity meant.
    """
    pcs = fm.pc_cols(n_pcs)
    lam = fm.model.eigenvalues.reindex(pcs).astype(float)
    rates_bp = fm.rates_bp.mean().to_dict()
    legs = sorted(set(weights["leg"]))
    L = leg_pc_loadings(fm, legs, rates_bp=rates_bp, n_pcs=n_pcs)

    rows: List[Dict[str, Any]] = []
    for (label, sizing), g in weights.groupby(["structure", "sizing"], sort=False):
        f_rows, v_rows, gross = [], [], []
        for _k, gk in g.groupby("cohort", sort=True):
            w = dict(zip(gk["leg"], gk["dv01"].astype(float)))
            f_rows.append(package_pc_exposure(w, L).to_numpy(float))
            v_rows.append(package_variance_shares(w, L, lam).to_numpy(float))
            gross.append(float(np.abs(list(w.values())).sum()))
        F = np.asarray(f_rows, dtype=float)
        V = np.asarray(v_rows, dtype=float)
        row: Dict[str, Any] = {"structure": label, "sizing": sizing,
                               "n_cohorts": int(F.shape[0]),
                               "gross_dv01_mean": float(np.mean(gross)),
                               "n_legs": int(g["leg"].nunique())}
        for i, nm in enumerate(("level", "slope", "curv")[:n_pcs]):
            row[f"f_{nm}_mean"] = float(np.mean(F[:, i]))
            row[f"abs_f_{nm}_mean"] = float(np.mean(np.abs(F[:, i])))
            row[f"var_{nm}"] = float(np.mean(V[:, i]))
        rows.append(row)
    return pd.DataFrame(rows)


def weights_summary(weights: pd.DataFrame, diag: pd.DataFrame) -> pd.DataFrame:
    """Per (structure, sizing): the leg sizes actually used, and the fit quality.

    ``dv01_ratio`` is ``|r_front| / |r_back|`` -- 1.000 for the incumbent by
    definition, and its distance from 1 is how far the factor-neutral sizing sits
    from DV01-neutral. ``n_short_fit`` counts cohorts sized on a PCA shorter than
    ``min_fit_days``, and ``n_label_bad`` counts those whose PCs did not come back
    level/slope/curvature under the structural test. Both are reported rather
    than dropped: dropping them would change the trade set.
    """
    d = diag.set_index(pd.to_datetime(diag["date"]))
    rows: List[Dict[str, Any]] = []
    for (label, sizing), g in weights.groupby(["structure", "sizing"], sort=False):
        piv = g.pivot_table(index="cohort", columns="leg", values="dv01",
                            aggfunc="sum")
        entries = pd.to_datetime(g.groupby("cohort")["entry"].first())
        sub = d.reindex(pd.DatetimeIndex(entries.values))
        row: Dict[str, Any] = {
            "structure": label, "sizing": sizing,
            "n_cohorts": int(piv.shape[0]),
            "gross_dv01_mean": float(piv.abs().sum(axis=1).mean()),
            "net_dv01_mean": float(piv.sum(axis=1).mean()),
            "n_short_fit": int(sub["short_fit"].fillna(False).sum()),
            "n_label_bad": int((~sub["label_ok"].fillna(True).astype(bool)).sum()),
        }
        for leg in piv.columns:
            row[f"dv01_{leg}_mean"] = float(piv[leg].mean())
            row[f"dv01_{leg}_sd"] = float(piv[leg].std(ddof=1)) if len(piv) > 1 else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


# ===========================================================================
# 11. The analytic sweeps -- exposures and greeks, deliberately NOT P&L
# ===========================================================================
def hedge_tenor_frontier(fm: fa.FactorModel, gamma: Optional[pd.Series] = None,
                         carry: Optional[pd.Series] = None,
                         structures: Sequence[Tuple[str, str, str]] = fa.STRAT1_STRUCTURES,
                         candidates: Sequence[str] = HEDGE_CANDIDATES,
                         *, dv01: float = UNIT_DV01,
                         neutralize: Sequence[str] = ("PC1", "PC2")) -> pd.DataFrame:
    """Every admissible third leg, scored on conditioning, gamma and carry.

    Reported in EXPOSURES, GAMMA and CARRY and never in realised P&L. Ranking
    nine hedge tenors on P&L and reporting the winner would be nine trials
    wearing one trial's clothes, and :data:`HEDGE_LEG` is pre-committed for
    stated structural reasons precisely so this sweep can be a check rather than
    a search.

    ``cond`` is the condition number of the 2x2 solve. A large value means the
    two free legs nearly fail to span the neutralised subspace, so the hedge
    weight explodes and a tiny loading error becomes a large sizing error --
    which is a property of the geometry, knowable in advance, and the honest
    reason to prefer a middle-of-the-grid hedge.
    """
    rates_bp = fm.rates_bp.mean().to_dict()
    legs = sorted({l for _l, f, b in structures for l in (f, b)} | set(candidates))
    L = leg_pc_loadings(fm, legs, rates_bp=rates_bp, n_pcs=3)
    lam = fm.model.eigenvalues.reindex(fm.pc_cols(3)).astype(float)
    rows: List[Dict[str, Any]] = []
    for label, front, back in structures:
        for h in candidates:
            if h in (front, back):
                continue
            rec: Dict[str, Any] = {"structure": label, "hedge_leg": h}
            try:
                w = pc12_neutral_weights(front, back, h, L, dv01=dv01,
                                         neutralize=neutralize)
            except (np.linalg.LinAlgError, KeyError, ValueError) as exc:
                rec.update({"ok": False, "reason": f"{type(exc).__name__}"})
                rows.append(rec)
                continue
            M = np.column_stack([L.loc[front, list(neutralize)].to_numpy(float),
                                 L.loc[h, list(neutralize)].to_numpy(float)])
            vs = package_variance_shares(w, L, lam)
            rec.update({
                "ok": True, "reason": "",
                "cond": float(np.linalg.cond(M)),
                "dv01_front": w[front], "dv01_back": w[back], "dv01_hedge": w[h],
                "gross_dv01": float(sum(abs(v) for v in w.values())),
                "hedge_frac_of_gross": abs(w[h]) / float(sum(abs(v) for v in w.values())),
                "var_curv_residual": float(vs["PC3"]),
            })
            if gamma is not None:
                rec["gamma_usd_per_bp2"] = float(
                    sum(r * float(gamma.get(l, np.nan)) for l, r in w.items()))
                ref = dv01_neutral_weights(front, back, dv01)
                rec["gamma_vs_dv01n"] = (rec["gamma_usd_per_bp2"] / float(
                    sum(r * float(gamma.get(l, np.nan)) for l, r in ref.items()))
                    if sum(r * float(gamma.get(l, np.nan)) for l, r in ref.items()) else np.nan)
            if carry is not None:
                rec["carry_usd_1y"] = float(
                    sum(r * float(carry.get(l, np.nan)) for l, r in w.items()))
            rows.append(rec)
    return pd.DataFrame(rows)


def slope_instrument_table(fm: fa.FactorModel,
                           candidates: Sequence[Tuple[str, Tuple[Tuple[str, float], ...]]]
                           = SLOPE_CANDIDATES, *, n_pcs: int = 3) -> pd.DataFrame:
    """Curvature injected per unit of slope hedged, for each candidate overlay.

    A slope hedge that carries curvature does not remove risk, it swaps one
    factor for another, so ``|PC3/PC2|`` is the number that ranks these. Reported
    from the FITTED loadings so :data:`SLOPE_INSTRUMENT`'s pre-committed choice
    is checkable against the model rather than against a note.
    """
    rates_bp = fm.rates_bp.mean().to_dict()
    legs = sorted({l for _n, ws in candidates for l, _w in ws})
    L = leg_pc_loadings(fm, legs, rates_bp=rates_bp, n_pcs=n_pcs)
    rows: List[Dict[str, Any]] = []
    for name, ws in candidates:
        w: Dict[str, float] = {}
        for leg, x in ws:
            w[leg] = w.get(leg, 0.0) + float(x)
        f = package_pc_exposure(w, L)
        rows.append({
            "instrument": name,
            "legs": " / ".join(f"{l}{x:+.1f}" for l, x in ws),
            "f_level_per_unit": float(f["PC1"]),
            "f_slope_per_unit": float(f["PC2"]),
            "f_curv_per_unit": float(f["PC3"]),
            "abs_curv_per_slope": (abs(float(f["PC3"]) / float(f["PC2"]))
                                   if float(f["PC2"]) else np.inf),
            "abs_level_per_slope": (abs(float(f["PC1"]) / float(f["PC2"]))
                                    if float(f["PC2"]) else np.inf),
            "selected": bool(tuple(ws) == tuple(SLOPE_INSTRUMENT)),
        })
    return pd.DataFrame(rows).sort_values("abs_curv_per_slope").reset_index(drop=True)


def straddle_sizing_table(signal_panel: pd.DataFrame,
                          structures: Sequence[Tuple[str, str, str]] = fa.STRAT1_STRUCTURES,
                          *, dv01: float = UNIT_DV01) -> pd.DataFrame:
    """``vega_neutral``: the note's funded-straddle sizing, reported ANALYTICALLY.

    The optional fifth sizing is NOT run, and the reason is measured rather than
    asserted. ``strat1_curve_gamma.build_backtest`` raises on
    ``trade_straddle=True`` -- the swaption leg was never wired into the engine --
    so producing a ``vega_neutral`` P&L would mean adding an untested engine path
    to answer an optional part of the question, which is the wrong trade.

    What CAN be reported for free is the sizing itself. ``straddle_dv01`` is
    already on the signal panel: the underlying-swap DV01 whose ATMF straddle
    premium exactly funds the package's own 1-year carry
    (``straddle_dv01_for_carry``). Read as a fraction of the $100k package it
    funds, it is the whole story -- a structure whose carry is a rounding error
    funds a straddle that is also a rounding error, and calling that book
    "vega-neutral" would be calling an unhedged flattener vega-neutral.
    """
    rows: List[Dict[str, Any]] = []
    for label, _f, _b in structures:
        sub = signal_panel[signal_panel["structure"] == label]
        if sub.empty:
            continue
        sd = sub["straddle_dv01"].astype(float)
        cr = sub["carry_roll_bp"].astype(float)
        rows.append({
            "structure": label,
            "straddle_dv01_median": float(sd.median()),
            "straddle_dv01_mean": float(sd.mean()),
            "straddle_dv01_max": float(sd.max()),
            "frac_of_package_dv01_median": float(sd.median()) / float(dv01),
            "carry_roll_bp_median": float(cr.median()),
            "atmf_vol_bp_yr_median": float(sub["atmf_vol_bp_yr"].astype(float).median()),
            "runnable": False,
            "reason": "build_backtest raises on trade_straddle=True",
        })
    return pd.DataFrame(rows)


# ===========================================================================
# 12. Costs
# ===========================================================================
def cost_sensitivity(leg_runs: Mapping[str, "LegRun"], weights: pd.DataFrame, *,
                     cfg: Optional[s1.Strat1Config] = None,
                     multipliers: Sequence[float] = (0.0, 0.5, 1.0, 2.0)
                     ) -> pd.DataFrame:
    """One (structure, sizing) book's closed-cohort P&L at several cost levels.

    Only the fee term moves; the cohorts, the weights and the gross P&L are
    identical across rows, which is what makes this a sensitivity rather than
    four backtests. ``0.0`` is the column that prices the hedge: the gap between
    it and ``1.0`` is exactly what the extra legs cost to trade.
    """
    cfg = cfg or _default_cfg()
    base = leg_cost_bp_one_way(cfg)
    rows: List[Dict[str, Any]] = []
    for m in multipliers:
        eq, book = compose_book(leg_runs, weights, cfg=cfg,
                                cost_bp_one_way=base * float(m))
        cl = book[book["closed"].to_numpy(bool)]
        p = cl["net_bp"].to_numpy(float)
        p = p[np.isfinite(p)]
        rows.append({
            "cost_multiple": float(m),
            "cost_bp_one_way_pkg": float(cfg.cost_bp_one_way) * float(m),
            "n_closed": int(len(p)),
            "total_net_bp": float(p.sum()) if len(p) else np.nan,
            "mean_net_bp": float(p.mean()) if len(p) else np.nan,
            "hit_rate": float((p > 0).mean()) if len(p) else np.nan,
            "sharpe_per_trade": (float(p.mean() / p.std(ddof=1))
                                 if len(p) > 1 and p.std(ddof=1) > 0 else np.nan),
            "mtm_final_bp": float(eq.iloc[-1] / cfg.package_dv01) if len(eq) else np.nan,
        })
    return pd.DataFrame(rows)


def breakeven_cost_bp(book: pd.DataFrame, *, cfg: Optional[s1.Strat1Config] = None
                      ) -> float:
    """One-way cost, in bp of the LEG's own DV01, at which the book nets zero.

    ``strat1_longend_listed.breakeven_cost_bp`` divides by ``2 * n_closed``
    because every one of its packages is the same two legs at the same size. That
    is exactly what stops working here: the whole point of the comparison is that
    ``pc12_neutral`` trades three legs and ``pc1_neutral`` trades two legs of
    UNEQUAL size, so the cost per cohort is no longer a constant and a
    per-cohort count is the wrong denominator.

    The right one is the gross DV01 actually traded::

        total_net(c) = sum_k gross_k - 2 * c * sum_k grossdv01_k  =  0

    so ``c* = sum(gross_bp) * package_dv01 / (2 * sum(gross_dv01))``. Exact, not
    a search, because the total is linear in the cost. A NEGATIVE answer means
    the book loses money gross and no cost level rescues it -- reported as such
    rather than clipped, because that is a meaningful answer.
    """
    cfg = cfg or _default_cfg()
    cl = book[book["closed"].to_numpy(bool)]
    g = cl["gross_bp"].to_numpy(float)
    gd = cl["gross_dv01"].to_numpy(float)
    m = np.isfinite(g) & np.isfinite(gd)
    if not m.any() or float(gd[m].sum()) <= 0:
        return float("nan")
    return float(g[m].sum() * float(cfg.package_dv01) / (2.0 * float(gd[m].sum())))


def overlay_cost_sensitivity(overlay_book: pd.DataFrame, hedge_path: pd.DataFrame,
                             schedule: pd.DataFrame, *,
                             cfg: Optional[s1.Strat1Config] = None) -> pd.DataFrame:
    """The slope overlay's cost under both readings of "rebalance monthly".

    ``full_roundtrip`` is what :func:`compose_overlay` charges and is the
    expensive reading: every live cohort's overlay is closed and a fresh
    at-market 5s30s opened each month, so the desk pays to get out and back in.
    That is the honest cost of the thing actually simulated, and it is the
    headline.

    ``delta_traded`` is the cheap reading: the desk holds ONE aggregate spread of
    ``n_live(m) * h_m`` per leg and trades only the month-on-month CHANGE in it.
    It is a genuinely different trade -- the aggregate position is carried across
    the month boundary rather than re-struck at market -- so it is reported as a
    bound rather than substituted for the headline. Reporting either one alone
    would be picking the reading that suits the conclusion.

    Both are computed from the same hedge path, so the ratio between them is a
    measurement of how much of the monthly turnover is churn.
    """
    cfg = cfg or _default_cfg()
    c_leg = leg_cost_bp_one_way(cfg)
    inst = slope_instrument_weights(1.0)
    unit_gross = float(sum(abs(v) for v in inst.values()))

    hp = hedge_path.sort_values("cohort").reset_index(drop=True)
    sched = schedule.sort_values("cohort").reset_index(drop=True)
    entries = [pd.Timestamp(e) for e in sched["entry"]]
    exits = [pd.Timestamp(x) if pd.notna(x) else pd.Timestamp("2100-01-01")
             for x in sched["exit"]]
    h = hp["hedge_dv01_per_leg"].to_numpy(float)

    # Aggregate hedge held per leg over month m: every cohort still open at
    # entries[m] carries h_m.
    agg = np.array([float(np.sum([(e <= entries[m]) and (entries[m] < x)
                                  for e, x in zip(entries, exits)])) * h[m]
                    for m in range(len(entries))], dtype=float)
    turnover = np.abs(np.diff(np.concatenate([[0.0], agg, [0.0]]))).sum()

    full = float(overlay_book["overlay_cost_usd"].sum())
    delta = float(c_leg * unit_gross * turnover)
    return pd.DataFrame([
        {"reading": "full_roundtrip", "total_cost_usd": full,
         "note": "every live cohort's overlay re-struck at market each month "
                 "-- what compose_overlay charges and the headline"},
        {"reading": "delta_traded", "total_cost_usd": delta,
         "note": "one aggregate spread carried across months, only the change "
                 "traded -- a different trade, reported as a lower bound"},
        {"reading": "churn_ratio", "total_cost_usd": (full / delta if delta else np.nan),
         "note": "full / delta; how much of the monthly turnover is round-tripping"},
    ])


# ===========================================================================
# 13. Statistics
# ===========================================================================
def book_stats(equity: pd.Series, book: pd.DataFrame, *,
               cfg: Optional[s1.Strat1Config] = None,
               carry_bp: float = float("nan"),
               business_days_per_year: float = 252.0) -> Dict[str, Any]:
    """Headline statistics for one composed book.

    A thin adapter onto ``strat1_longend_listed.book_stats`` -- deliberately, and
    the reason is not laziness. That function already carries the two things this
    study must not get wrong: the overlap-adjusted t-statistic (monthly cohorts
    held a year share ~92% of their window, so the nominal count is an upper
    bound on the evidence and never the evidence itself), and the skew/kurtosis
    convention the deflated Sharpe expects (RAW fourth moment, 3.0 for a normal;
    feeding it an EXCESS kurtosis silently understates the deflation).
    :func:`compose_book` emits its book frame in that function's column names for
    exactly this reason.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    return ll.book_stats(equity, book, cfg=cfg or _default_cfg(), carry_bp=carry_bp,
                         business_days_per_year=business_days_per_year)


def n_eff_report(books: Mapping[str, pd.DataFrame], *,
                 cfg: Optional[s1.Strat1Config] = None) -> Dict[str, Any]:
    """Effective sample size, with BOTH haircuts measured on these books.

    Two independent haircuts, because the nominal cohort count overstates the
    evidence twice over, and both are measurements here rather than conventions:

    **Overlap in time.** Monthly cohorts held one year share ~92% of their
    window, so a structure's ~79 closed cohorts are ``span / horizon``
    non-overlapping observations. ``strat1_threeway.effective_independent_n``.

    **Overlap across structures.** The four long-end flatteners are overlapping
    segments of one curve. With ``k`` structures at mean pairwise P&L correlation
    ``rbar``, the equal-weight portfolio's variance ratio gives
    ``k_eff = k / (1 + (k-1) * rbar)``.

    ``rbar`` is measured on THESE books' closed-cohort net P&L, aligned on entry
    date -- not inherited from the incumbent's, because a sizing that changes the
    leg ratios changes what the four structures have in common, and assuming it
    did not would be assuming the answer to a question this study is asking.
    """
    from RVUtils.ConvexityRV import strat1_threeway as tw

    cfg = cfg or _default_cfg()
    per: Dict[str, float] = {}
    series: Dict[str, pd.Series] = {}
    for label, b in books.items():
        cl = b[b["closed"].to_numpy(bool)]
        if cl.empty:
            continue
        per[label] = float(tw.effective_independent_n(cl["entry"], cl["exit"],
                                                      cfg.horizon_years))
        s = pd.Series(cl["net_bp"].to_numpy(float),
                      index=pd.to_datetime(cl["entry"]))
        series[label] = s[~s.index.duplicated(keep="first")]
    if len(series) < 2:
        raise ValueError(f"need >= 2 structures, got {list(series)}")
    M = pd.DataFrame(series).dropna()
    corr = M.corr()
    labels = list(corr.columns)
    pairs = [(labels[i], labels[j], float(corr.iloc[i, j]))
             for i in range(len(labels)) for j in range(i + 1, len(labels))]
    off = [p[2] for p in pairs]
    rbar = float(np.mean(off))
    k = len(labels)
    k_eff = float(k / (1.0 + (k - 1) * rbar)) if (1.0 + (k - 1) * rbar) > 0 else float(k)
    n_per = float(np.nanmean(list(per.values())))
    lo = min(pairs, key=lambda p: p[2])
    hi = max(pairs, key=lambda p: p[2])
    return {
        "n_eff_per_structure": per,
        "n_eff_per_structure_mean": n_per,
        "n_structures": k,
        "mean_pairwise_r": rbar,
        "min_pairwise_r": lo[2], "min_pair": f"{lo[0]} vs {lo[1]}",
        "max_pairwise_r": hi[2], "max_pair": f"{hi[0]} vs {hi[1]}",
        "n_common_closed_cohorts": int(len(M)),
        "k_eff_structures": k_eff,
        "n_eff_pooled": float(n_per * k_eff),
        "n_nominal_pooled": int(sum(len(b) for b in books.values())),
        "corr_matrix": corr,
        "formula": "k_eff = k / (1 + (k-1)*rbar);  n_eff_pooled = mean(span/horizon) * k_eff",
    }


def sharpe_scoreboard(stats: pd.DataFrame, n_eff_pooled: float, *,
                      n_trials: int = len(SCORED_SIZINGS),
                      sharpe_col: str = "sharpe_per_trade") -> pd.DataFrame:
    """Every sizing's Sharpe against what the BEST of ``n_trials`` nulls gives.

    A thin adapter onto ``strat1_longend_listed.sharpe_scoreboard``, with
    ``n_trials`` defaulting to the number of DISTINCT sizings scored -- four.
    Three things are deliberately not counted, all for the same reason (they are
    not choices over which a best could be picked): the walk-forward/full-sample
    pair is one sizing estimated two ways; ``vega_neutral`` produces no P&L; and
    the hedge-tenor frontier is reported in exposures, never in returns.
    """
    from RVUtils.ConvexityRV import strat1_longend_listed as ll

    return ll.sharpe_scoreboard(stats, float(n_eff_pooled), n_trials=int(n_trials),
                                sharpe_col=sharpe_col)


# ===========================================================================
# 14. Re-running the attribution ON THE NEW BOOKS
# ===========================================================================
def sizing_series(label: str, sizing: str, equity: pd.Series, book: pd.DataFrame,
                  calendar: pd.DatetimeIndex, *,
                  cfg: Optional[s1.Strat1Config] = None,
                  carry_usd: Optional[pd.Series] = None
                  ) -> Dict[str, fa.StrategySeries]:
    """Wrap one composed book as ``factor_attribution.StrategySeries`` objects.

    This is the half of the test the P&L cannot answer. A hedge that moves the
    P&L to zero has not necessarily removed the factor, and a hedge that leaves
    the P&L alone has not necessarily failed to: the claim
    ``pc1_neutral`` makes is about the LEVEL SHARE, and the only way to check it
    is to put the new book back through the same regression the attribution ran
    and see the share move.

    Two levels, as everywhere else in this package. ``daily`` uses the engine's
    own marks folded onto the factor calendar (Good Friday and the like carried
    FORWARD, never dropped -- ``align_to_factor_calendar`` measured that at 30% of
    one book's P&L when done naively). ``trade`` uses closed cohorts only.

    ``weight`` is +1 per live package throughout: every sizing here trades the
    always-on flattener and never reverses, so the SIGN of the fitted convexity
    coefficient stays an output of the regression rather than an assumption fed
    in through the regressor.
    """
    cfg = cfg or _default_cfg()
    name = f"{label} {sizing}"
    out: Dict[str, fa.StrategySeries] = {}

    cl = book[book["closed"].to_numpy(bool)].reset_index(drop=True)
    entry, exit_ = pd.to_datetime(cl["entry"]), pd.to_datetime(cl["exit"])
    y_tr = (cl["net_bp"].astype(float) * float(cfg.package_dv01)).rename("pnl_usd")
    carry_tr = (carry_usd.reindex(entry).to_numpy(float)
                if carry_usd is not None else None)
    out[name] = fa.StrategySeries(
        name=name, level="trade", y=y_tr,
        weight=pd.Series(1.0, index=y_tr.index),
        carry=(pd.Series(carry_tr, index=y_tr.index) if carry_tr is not None else None),
        intervals=list(zip(entry, exit_)), raw_total=float(y_tr.sum()),
        note=f"{sizing}; closed cohorts only, net of this sizing's own cost")

    raw = equity.astype(float).diff().dropna()
    dy, dropped = fa.align_to_factor_calendar(raw, calendar)
    ce = pd.to_datetime(book["entry"])
    cx = pd.to_datetime(book["exit"]).fillna(pd.Timestamp(calendar[-1]))
    cd = pd.Series(1.0, index=book.index)
    w = fa._active_weight(dy.index, ce, cx, cd)
    cw = None
    if carry_usd is not None:
        cw = fa._active_weight(dy.index, ce, cx, cd,
                               values=carry_usd.reindex(ce).to_numpy(float)) / 252.0
    out[f"{name} [daily]"] = fa.StrategySeries(
        name=name, level="daily", y=dy, weight=w, carry=cw,
        raw_total=float(raw.sum()), off_calendar=dropped,
        note="net live packages; carry = package 1y carry at entry / 252")
    return out


def attribution_shares(fm: fa.FactorModel, series: Mapping[str, fa.StrategySeries],
                       fcfg: fa.FactorConfig, *, level: str = "trade",
                       convexity: str = "parallel_sq") -> pd.DataFrame:
    """Run the committed attribution on the composed books and tabulate shares.

    Uses ``factor_attribution.run_attribution`` unchanged and on the SHARED
    full-sample basis, so a share here is the same object as a share in the
    attribution report and the two tables can be read side by side. A successful
    hedge must move the neutralised factor's share toward zero; if it does not,
    the hedge is not doing what it claims regardless of what the P&L does, and
    that verdict is available from this table alone.
    """
    res = fa.run_attribution(fm, series, fcfg, convexity=convexity)
    tab = fa.decisive_table(res, level=level)
    if tab.empty:
        return tab
    keep = (["strategy", "level", "n_obs", "total_pnl", "r2"]
            + [f"share_{k}" for k in fa.FACTOR_ORDER] + ["share_unexplained"]
            + [f"gross_{k}" for k in fa.FACTOR_ORDER]
            + [f"incr_{k}" for k in fa.FACTOR_ORDER]
            + [f"t_{k}" for k in fa.FACTOR_ORDER]
            + ["denom_stability", "denom_unstable", "pnl_coverage"])
    return tab[[c for c in keep if c in tab.columns]]


# ===========================================================================
# 15. The verdict
# ===========================================================================
def verdict(cfg: FactorNeutralConfig, stats: pd.DataFrame, scoreboard: pd.DataFrame,
            residual: pd.DataFrame, shares: pd.DataFrame,
            certification: pd.DataFrame, neff: Mapping[str, Any],
            *, dominant: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
    """Everything the report has to state, as one JSON-able dict.

    Ordered by evidential weight rather than by interest: the certification
    first, because a composed curve that does not reproduce an engine run is not
    evidence of anything; then the exposure test, which is a measurement and
    survives a small sample; then the P&L, which at ~10 effective observations is
    the weakest thing here and is labelled as such.
    """
    def _clean(v: Any) -> Any:
        if isinstance(v, (np.floating, np.integer)):
            return float(v)
        if isinstance(v, (np.bool_, bool)):
            return bool(v)
        return v

    best = None
    if len(scoreboard):
        i = scoreboard["sharpe_per_trade"].astype(float).idxmax()
        best = {k: _clean(scoreboard.loc[i, k]) for k in scoreboard.columns
                if k != "corr_matrix"}
    return {
        "study": "factor-neutral sizing of the long-end convexity flatteners",
        "config": cfg.as_dict(),
        "certification": certification.to_dict("records") if len(certification) else [],
        "dominant_factor": (dominant.to_dict("records")
                            if dominant is not None and len(dominant) else []),
        "residual_exposure": residual.to_dict("records") if len(residual) else [],
        "attribution_shares": shares.to_dict("records") if len(shares) else [],
        "sample_size": {k: _clean(v) for k, v in neff.items() if k != "corr_matrix"},
        "n_trials_used_for_correction": len(cfg.scored_sizings),
        "scoreboard": scoreboard.drop(columns=[c for c in ("corr_matrix",)
                                               if c in scoreboard.columns]
                                      ).to_dict("records") if len(scoreboard) else [],
        "best_by_sharpe_per_trade": best,
        "anything_clears_max_null": (bool(scoreboard["clears_max_null"].any())
                                     if "clears_max_null" in scoreboard else None),
        "stats": stats.reset_index().to_dict("records") if len(stats) else [],
    }
