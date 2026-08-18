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

    **after neutralising slope, does a positive convexity edge remain, or does
    the P&L simply go to zero?**

Both answers are reportable and only one of them is good news. If an edge
survives, the incumbent sizing was diluting a real convexity trade with a slope
bet. If the P&L collapses, the convexity was never the earner and the honest
conclusion is that DV01-neutral sizing was not "wrong" so much as the thesis was.


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
counts: three. The hedge-tenor sweep in :func:`hedge_tenor_frontier` is
deliberately ANALYTIC -- exposures and gamma, no P&L -- because ranking nine
hedge tenors on realised P&L and reporting the winner would be nine trials
wearing one trial's clothes.


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
    "SLOPE_INSTRUMENT",
    "SIZINGS",
    "SCORED_SIZINGS",
    "UNIT_DV01",
    "FactorNeutralConfig",
    "safe_leg",
    "assert_shared_schedule",
    "build_leg_backtest",
    "run_leg",
    "LegRun",
    "load_leg_runs",
    "leg_pc_loadings",
    "leg_gamma_bp",
    "dv01_neutral_weights",
    "pc12_neutral_weights",
    "slope_instrument_weights",
    "slope_hedge_ratio",
    "walk_forward_loadings",
    "cohort_weights",
    "compose_book",
    "compose_overlay",
    "certify_dv01_neutral",
    "certify_engine",
    "hedge_tenor_frontier",
    "slope_instrument_table",
    "straddle_sizing_table",
    "residual_exposure_table",
    "sizing_series",
    "book_stats",
    "sharpe_scoreboard",
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

#: The sizings built. ``vega_neutral`` is absent by design -- see the module
#: docstring and :func:`straddle_sizing_table`.
SIZINGS: Tuple[str, ...] = ("dv01_neutral", "pc12_neutral", "slope_beta_hedged")

#: What the multiple-testing correction counts. Identical to :data:`SIZINGS`:
#: three distinct sizings, three trials. The walk-forward/full-sample pair is
#: ONE trial, not two -- they are the same sizing rule estimated two ways, and
#: the full-sample one is reported to quantify look-ahead, never to be picked.
SCORED_SIZINGS: Tuple[str, ...] = SIZINGS

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
        return pd.DataFrame(cols, index=idx)

    def open_mark(self) -> pd.DataFrame:
        """``date x cohort`` of the OPEN position's mark only, no realised P&L.

        This is what the monthly slices of the ``slope_beta_hedged`` overlay are
        built from: a position opened at ``entry`` and closed a month later has,
        as its P&L, exactly this column's value at that later date.
        """
        idx = self.index
        cols: Dict[int, np.ndarray] = {}
        for _, r in self.cohorts.iterrows():
            k, tag = int(r["cohort"]), str(r["tag"])
            cols[k] = (self.marks[tag].reindex(idx).fillna(0.0).to_numpy(float)
                       if tag in self.marks.columns else np.zeros(len(idx)))
        return pd.DataFrame(cols, index=idx)


def load_leg_runs(data_dir: Any, legs: Sequence[str] = LEG_UNIVERSE
                  ) -> Dict[str, "LegRun"]:
    """Load every cached leg run and check they share one grid and one schedule.

    The check is not ceremony. The composition adds legs cohort by cohort; two
    legs whose cohort 7 opened on different days would compose a package that
    was never a package, and the equity curve would look entirely plausible.
    """
    d = pathlib.Path(data_dir)
    out: Dict[str, LegRun] = {}
    ref_idx: Optional[pd.DatetimeIndex] = None
    ref_sched: Optional[Tuple[Any, Any]] = None
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
        if ref_idx is None:
            ref_idx, ref_sched = idx, sched
        elif not idx.equals(ref_idx):
            raise AssertionError(f"leg {leg}: mark grid differs from {legs[0]}")
        elif sched != ref_sched:
            raise AssertionError(f"leg {leg}: cohort schedule differs from {legs[0]}")
        out[leg] = LegRun(leg=leg, equity=eq, cohorts=co, marks=mk.reindex(idx))
    return out


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
                          min_fit_days: int = 250, n_pcs: int = 3,
                          ) -> Tuple[Dict[pd.Timestamp, pd.DataFrame], pd.DataFrame]:
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

    Returns ``(loadings_by_date, diagnostics)``. The diagnostics frame carries
    the fit length, the explained-variance split, the ``classify_pcs`` label of
    each PC, and ``label_ok`` -- False on any date where the structural test does
    not return level/slope/curvature, which is the failure this function exists
    to make visible rather than to hide.
    """
    from RVUtils.pca_rv import align_eigenvectors

    panel = rate_panel.sort_index()
    cols = [t for t in cfg.tenors if t in panel.columns]
    out: Dict[pd.Timestamp, pd.DataFrame] = {}
    diag: List[Dict[str, Any]] = []
    V_ref: Optional[np.ndarray] = None
    for d in pd.to_datetime(list(dates)):
        hist = panel.loc[panel.index < d, cols].dropna(how="any")
        short = len(hist) < int(min_fit_days)
        if len(hist) < 30:
            raise ValueError(f"{d.date()}: only {len(hist)} usable curve days before it")
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
        ok = list(lab["label"].values[:3]) == ["level", "slope", "curvature"]
        diag.append({
            "date": d, "n_fit_days": int(len(hist)), "short_fit": bool(short),
            **{f"label_{p}": lab.loc[p, "label"] for p in pcs},
            **{f"ev_{p}": float(lam[i] / lam.sum()) for i, p in enumerate(pcs)},
            "label_ok": bool(ok),
            **{f"f_{p}_dv01n": float("nan") for p in pcs},
        })
    return out, pd.DataFrame(diag)


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
                   sizings: Sequence[str] = ("dv01_neutral", "pc12_neutral"),
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
def slope_beta_path(gross_equity: pd.Series, weight: pd.Series, fm: fa.FactorModel,
                    rebalance_dates: Sequence[Any], *, window: int = 252,
                    ) -> pd.DataFrame:
    """Trailing beta of the book's own daily P&L on PC2, per package.

    At each rebalance the regression is

        ``y_t = a + b * (w_t * dPC2_t) + e_t``

    over the ``window`` scored days STRICTLY BEFORE that date -- the same
    ``w_t``-signed design ``factor_attribution.daily_design`` uses, so ``b`` is
    dollars per unit of PC2 per LIVE PACKAGE and is directly comparable with the
    analytic ``f_PC2`` of one package.

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
    idx = y_all.index.intersection(fm.scores.index)
    y_all = y_all.reindex(idx)
    x_all = (weight.reindex(idx).astype(float).fillna(0.0).to_numpy()
             * fm.scores.loc[idx, "PC2"].to_numpy(float))
    x_all = pd.Series(x_all, index=idx)
    live = weight.reindex(idx).fillna(0.0) != 0.0

    rows: List[Dict[str, Any]] = []
    for d in pd.to_datetime(list(rebalance_dates)):
        m = (idx < d) & live.to_numpy()
        sub_y, sub_x = y_all[m], x_all[m]
        if len(sub_y) > int(window):
            sub_y, sub_x = sub_y.iloc[-int(window):], sub_x.iloc[-int(window):]
        n = int(len(sub_y))
        if n < 20 or float(sub_x.std(ddof=1) or 0.0) <= 0:
            rows.append({"date": d, "n_days": n, "beta_usd_per_pc2": 0.0,
                         "t_stat": np.nan, "r2": np.nan, "short_window": True})
            continue
        fit = sm.OLS(sub_y.to_numpy(float),
                     sm.add_constant(sub_x.to_numpy(float))).fit()
        rows.append({"date": d, "n_days": n, "beta_usd_per_pc2": float(fit.params[1]),
                     "t_stat": float(fit.tvalues[1]), "r2": float(fit.rsquared),
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
