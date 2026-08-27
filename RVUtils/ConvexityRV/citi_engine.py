r"""``QueryDrivenBacktest`` wiring for Citi's published trade, on dated instruments.

The panel is a signal tool and the engine is the number.  This module turns one
:class:`citi_rule.CitiEpisode` into the real package the note describes --

    "buy 2000 of H0-Z0 Eurodollar packs (2000 of each of the four contracts) and
    pay $2bn on a matched-maturity (3/18/20-3/17/21) CME cleared swap at 8.8bp of
    spread ... We hedge the trade by paying the belly of the 2s5s10s swap fly
    with notional weights of $147mm/-$85.6mm/$20.89mm (0.705/-1/0.465 DV01
    weights)"

-- as separate queries through the engine, and prices it on instruments that
AGE.  That is the whole point: a constant-rank par-rate panel cannot represent a
four-month hold across a contract roll, and this package has certified that it
overstates hedged Sharpes by 1.5-6x when it tries.

Two things this module adds over ``gv_engine``
----------------------------------------------
**1. A fly with FITTED weights.**  ``gv_engine`` quotes its fly as ``2b - f - k``
with DV01-neutral 50/50 wings, so a ``[0.5, 1, 0.5]`` package earns ``bpv/2`` per
bp and the ``bpv`` carries a factor of two.  Citi's fly is
``r5 - w2*r2 - w10*r10`` with **fitted** weights, so a ``[w2, 1, w10]`` package
earns exactly ``bpv`` per bp of that combination and the ``bpv`` is **1x**::

    P&L = D*dr5 - w2*D*dr2 - w10*D*dr10 = D * d(combo)   ->   D = leg_dv01

Getting that factor wrong is a silent halving of exactly the leg the note's
method exists to size, so it is asserted against a hand-computed package in
``tests/test_convexity_rv_citi_engine.py``.

**2. Per-segment tags, because the hedge is RE-STRUCK.**  Citi re-fits at each
quarterly roll and the hedge moves with it.  ``UnwindPositionsAction`` matches a
tag by exact set membership, so each fly incarnation carries its own tag and can
be unwound and replaced without touching the futures pack or the matched swap.
A book that shared one tag across all legs could not express a re-strike at all.

Sign map, established empirically and never read off the code
-------------------------------------------------------------
* ``side = -1`` is SHORT the CA -- Citi's book: **buy** the futures pack, **pay**
  the matched swap.
* Futures direction rides the **risk weight** with ``contracts`` kept positive.
  A negative ``contracts`` on a ``STIRFutureQuery`` silently goes LONG, because
  the outright builder flips the weight AND the rateslib leg carries the negative
  notional, and the two negations cancel.
* ``bpv = -side * ca_dv01`` on the matched swap: positive is PAY.
* ``leg_dv01_signed = -side * beta * ca_dv01`` on the fly, so a NEGATIVE beta
  flips the leg rather than shrinking it -- which is what the fitted scale doing
  after mid-2023 demands.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from RVUtils.ConvexityRV.cavf_universe import (
    contracts_for,
    contracts_per_leg,
    swap_window,
)
from RVUtils.ConvexityRV.gv_engine import add_years

__all__ = [
    "CURVE",
    "FLY_TENORS",
    "CitiFlySegment",
    "CitiTradeSpec",
    "assert_ran",
    "build_queries",
    "fly_leg_dates",
    "run_backtest",
    "spec_from_episode",
]

CURVE = "USD-SOFR-1D"
#: Citi's Figure-6 regressors are SPOT 2y / 5y / 10y par swaps.
FLY_TENORS: Tuple[float, float, float] = (2.0, 5.0, 10.0)


@dataclass(frozen=True)
class CitiFlySegment:
    """One incarnation of the hedge: struck on *start*, unwound on *end*."""

    start: datetime.date
    end: datetime.date
    dates: Tuple[Tuple[datetime.date, datetime.date], ...]   # (eff, mat) x 3
    w2: float
    w10: float
    leg_dv01_signed: float       # USD per bp of ``r5 - w2*r2 - w10*r10``

    @property
    def risk_weights(self) -> List[float]:
        # a FRESH list every time: ``_build_fly`` mutates it in place
        return [float(self.w2), 1.0, float(self.w10)]

    @property
    def charged_dv01(self) -> float:
        """Sum of |per-leg DV01| -- the base a per-leg cost is charged on."""
        d = abs(float(self.leg_dv01_signed))
        return d * (1.0 + abs(float(self.w2)) + abs(float(self.w10)))


@dataclass(frozen=True)
class CitiTradeSpec:
    label: str
    side: int
    entry: datetime.date
    exit: datetime.date
    symbols: Tuple[str, ...]
    contracts_per_leg: int
    swap_start: datetime.date
    swap_end: datetime.date
    ca_dv01: float
    fly_segments: Tuple[CitiFlySegment, ...]
    tag: str

    def fly_tag(self, i: int) -> str:
        return f"{self.tag}#f{i}"


def fly_leg_dates(struck: datetime.date,
                  tenors: Sequence[float] = FLY_TENORS
                  ) -> List[Tuple[datetime.date, datetime.date]]:
    """Explicit ``(effective, maturity)`` per fly leg, resolved AT THE STRIKE.

    A relative tenor re-resolves at every mark and prices a fresh at-market
    package forever, whose NPV is ~0 by construction and which therefore never
    ages -- one of the two documented ways a ``QueryDrivenBacktest`` returns a
    perfectly flat equity curve while reporting success.
    """
    return [(struck, add_years(struck, float(t))) for t in tenors]


def spec_from_episode(*, structure: str, side: int, entry: datetime.date,
                      exit: datetime.date, ca_dv01: float,
                      hedge_path: Sequence[Tuple[datetime.date, float, float,
                                                 float]],
                      root: str = "SR3", tag: Optional[str] = None
                      ) -> CitiTradeSpec:
    """Build the traded package.

    ``hedge_path`` is ``[(struck_date, beta, w2, w10), ...]`` in ascending date
    order: one entry for the hedge put on at entry, plus one per re-strike.  An
    empty path is the unhedged variant and produces no fly leg at all.
    """
    eff, mat = swap_window(structure, entry)
    segs: List[CitiFlySegment] = []
    path = [h for h in hedge_path if h[0] <= exit]
    for i, (struck, beta, w2, w10) in enumerate(path):
        end = path[i + 1][0] if i + 1 < len(path) else exit
        if end <= struck or not beta:
            continue
        segs.append(CitiFlySegment(
            start=struck, end=end, dates=tuple(fly_leg_dates(struck)),
            w2=float(w2), w10=float(w10),
            leg_dv01_signed=-float(side) * float(beta) * float(ca_dv01)))
    return CitiTradeSpec(
        label=structure, side=int(side), entry=entry, exit=exit,
        symbols=tuple(contracts_for(structure, entry, root=root)),
        contracts_per_leg=contracts_per_leg(structure, ca_dv01),
        swap_start=eff, swap_end=mat, ca_dv01=float(ca_dv01),
        fly_segments=tuple(segs),
        tag=tag or f"citi_{structure}_{entry:%Y%m%d}_"
                   f"{'S' if side < 0 else 'L'}")


def build_queries(spec: CitiTradeSpec) -> Dict[str, List[Any]]:
    """``{tag: [queries]}`` -- the CA legs under the trade tag, each fly
    incarnation under its own."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
    from Query.STIRFutures.STIRFutureValue import STIRFutureValue

    out: Dict[str, List[Any]] = {spec.tag: []}
    direction = float(-spec.side)          # short the CA => BUY the futures
    for sym in spec.symbols:
        out[spec.tag].append(STIRFutureQuery(
            structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
            symbol=sym,
            structure_kwargs={"contracts": int(spec.contracts_per_leg),
                              "risk_weights": [direction]},
            tags=(spec.tag,)))
    out[spec.tag].append(IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, curve=CURVE,
        effective_date=spec.swap_start, maturity_date=spec.swap_end,
        structure_kwargs={"bpv": float(-spec.side * spec.ca_dv01)},
        tags=(spec.tag,)))
    for i, seg in enumerate(spec.fly_segments):
        (fe, fm), (be, bm), (ke, km) = seg.dates
        t = spec.fly_tag(i)
        out[t] = [IRSwapQuery(
            structure=IRSwapStructure.FLY, value=IRSwapValue.NPV, curve=CURVE,
            structure_kwargs={
                "front_effective_date": fe, "front_maturity_date": fm,
                "belly_effective_date": be, "belly_maturity_date": bm,
                "back_effective_date": ke, "back_maturity_date": km,
                "risk_weights": seg.risk_weights,
                # 1x, NOT 2x: this fly is quoted r5 - w2*r2 - w10*r10 and a
                # [w2, 1, w10] package earns exactly bpv per bp of it.
                "bpv": float(seg.leg_dv01_signed)},
            tags=(t,))]
    return out


def run_backtest(specs: Sequence[CitiTradeSpec],
                 trading_days: Sequence[pd.Timestamp], *,
                 futures_mdp: Any = None, swaps_mdp: Any = None,
                 fee_by_tag: Optional[Dict[str, float]] = None,
                 name: str = "citi", show_progress: bool = False) -> Any:
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    # The CME settle, co-timed with the 15:00 ET Citi curve below. Was
    # "BARCHART_STIRF-RL" (the 15:59 CT Globex close) until 2026-08-27 --
    # see RVUtils.ConvexityRV.strat2_sofr_convexity.assert_settle_source.
    futures_mdp = futures_mdp or STIRFutureMDP(source="BARCHART_STIRF_SETTLE-RL")
    swaps_mdp = swaps_mdp or IRSwapsMDP(source="citivelo_excel_rl")
    fee_by_tag = fee_by_tag or {}

    triggers = []
    for spec in specs:
        by_tag = build_queries(spec)
        # the CA package: on at entry, off at exit
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[spec.entry]),
            actions=[AddQueryAction(query=q, meta={"tags": [spec.tag]})
                     for q in by_tag[spec.tag]]))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[spec.exit]),
            actions=[UnwindPositionsAction(
                match_tag=spec.tag, fee=float(fee_by_tag.get(spec.tag, 0.0)))]))
        # each hedge incarnation: on when struck, off when re-struck or at exit
        for i, seg in enumerate(spec.fly_segments):
            t = spec.fly_tag(i)
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[seg.start]),
                actions=[AddQueryAction(query=q, meta={"tags": [t]})
                         for q in by_tag[t]]))
            triggers.append(DateTrigger(
                DateTriggerRequirements(dates=[seg.end]),
                actions=[UnwindPositionsAction(
                    match_tag=t, fee=float(fee_by_tag.get(t, 0.0)))]))

    grid = TimeGrid([pd.Timestamp(d) for d in trading_days])
    strat = QueryStrategy(name=name, triggers=triggers)
    strat.mdps = {"STIRFUTURE": futures_mdp, "IRS": swaps_mdp}
    strat.default_mdp = swaps_mdp
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=swaps_mdp,
                             show_progress=show_progress)
    bt.run()
    return bt


def assert_ran(bt: Any, specs: Sequence[CitiTradeSpec], *,
               expect_days: Optional[int] = None) -> pd.Series:
    """``QueryDrivenBacktest.run()`` swallows exceptions and prints them, so a
    failed backtest looks like a flat equity curve.  Prove the book traded.

    The diagnostic that separates the two known causes of a silent zero is the
    CLOSED-POSITION count, not the equity: zero positions means no trigger ever
    fired (``DateTrigger`` never matches a ``pd.Timestamp``), while positions
    that opened and closed at zero P&L means a relative tenor re-resolved at
    every mark.
    """
    assert len(specs) > 0, (
        "no specs were planned -- a flat equity curve here is a planning "
        "failure upstream, not a trading result")
    eq = pd.Series(bt.mtm_history)
    assert len(eq) > 0, "mtm_history is empty -- the engine swallowed an exception"
    if expect_days is not None:
        assert len(eq) == expect_days, f"expected {expect_days} marks, got {len(eq)}"
    eq.index = pd.to_datetime(eq.index)
    eq = eq.sort_index()
    assert float(eq.abs().max()) > 0.0, (
        "equity is identically zero -- no trigger ever fired; check that the "
        "trigger dates are datetime.date and inside the time grid")
    closed = bt.portfolio.closed_positions_log
    n_min = sum(len(s.symbols) + 1 + len(s.fly_segments) for s in specs)
    assert len(closed) >= n_min, (
        f"{len(closed)} closed positions < {n_min} legs planned -- an unwind "
        "never matched its tag")
    return eq
