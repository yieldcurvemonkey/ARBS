r"""GV block — QueryDrivenBacktest wiring for IMM-dated legs.

Generalises ``cavf_engine`` to this block's two leg kinds (an IMM-dated or spot
FLY, and a forward CURVE) and to this block's quoted conventions.  The CA side
reuses ``cavf_universe``'s contract resolution unchanged: same packs, same
matched-swap window, same sign map, already tested.

**The factor of two that must not be lost.**  ``cavf`` quotes a fly as
``b - 0.5(f+k)`` and this block quotes it as ``2b - f - k`` (the timeseries
layer's own ``FLY RATE``).  With ``risk_weights=[0.5, 1, 0.5]`` and ``bpv`` on
the belly, the package earns ``bpv/2`` per bp of THIS block's fly, so::

    belly_bpv = 2 * leg_dv01_signed          (fly)
    back_bpv  =     leg_dv01_signed          (curve, quoted back - front)

``leg_dv01_signed = -side * beta * ca_dv01`` reproduces the panel identity
``P&L = side*(dCA - beta*dleg)*ca_dv01``.  Getting the 2 wrong is a silent
halving of exactly the leg this block exists to re-size, so it is asserted in
``tests/test_convexity_rv_gv_engine.py`` against a hand-computed package.

Sign map, inherited and unchanged:

* ``side = -1`` (short the spread, Citi's book): BUY the futures, PAY the
  matched swap, and take ``-side*beta`` of the leg;
* direction rides the **risk weight** with ``contracts`` kept positive -- a
  negative ``contracts`` on a ``STIRFutureQuery`` silently goes LONG, because
  the outright builder flips the weight AND the rateslib leg carries the
  negative notional and the two negations cancel.
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
from RVUtils.ConvexityRV.gv_universe import (
    CA_DV01_DEFAULT,
    CURVE,
    LEGS,
    matched_imm_rank,
)

__all__ = [
    "GVLeg",
    "GVTradeSpec",
    "add_years",
    "leg_dates",
    "spec_from_episode",
    "build_trade_queries",
    "run_backtest",
    "assert_ran",
]


def add_years(d: datetime.date, years: float) -> datetime.date:
    """28th-capped calendar add.  What matters is that the instrument is
    PINNED, not which holiday rule pins it -- the schedule builder applies its
    own business-day roll downstream."""
    months = int(round(years * 12))
    y, m = divmod((d.month - 1) + months, 12)
    return datetime.date(d.year + y, m + 1, min(d.day, 28))


def _years(tenor: str) -> float:
    t = tenor.strip().upper().rstrip("Y")
    return float(t)


@dataclass(frozen=True)
class GVLeg:
    kind: str                                   # "fly" | "curve"
    dates: Tuple[Tuple[datetime.date, datetime.date], ...]
    leg_dv01_signed: float                      # USD per bp of the QUOTED combo


@dataclass(frozen=True)
class GVTradeSpec:
    label: str
    side: int
    entry: datetime.date
    exit: datetime.date
    symbols: Tuple[str, ...]
    contracts_per_leg: int
    swap_start: datetime.date
    swap_end: datetime.date
    ca_dv01: float
    leg: Optional[GVLeg]
    leg_id: Optional[str]
    tag: str


def leg_dates(leg_id: str, structure: Optional[str], entry: datetime.date
              ) -> List[Tuple[datetime.date, datetime.date]]:
    """Explicit ``(effective, maturity)`` per leg, resolved AT ENTRY.

    An IMM leg is pinned to the IMM date its rank resolves to on the entry
    date, so the held instrument does not re-resolve at the next roll -- which
    is the whole point of an IMM-dated position and the defect a relative tenor
    reintroduces (a relative tenor re-resolves at every mark and prices a fresh
    at-market package forever).
    """
    from Query.Base.imm_resolution import resolve_imm_token

    spec = LEGS[leg_id]
    if spec.start in ("immF", "imm2", "immM"):
        k = {"immF": 1, "imm2": 2}.get(spec.start) or matched_imm_rank(structure)
        eff = resolve_imm_token(f"IMM_{k}", entry)
        eff = eff.date() if hasattr(eff, "date") else eff
        return [(eff, add_years(eff, _years(t))) for t in spec.tenors]
    if spec.start == "spot":
        return [(entry, add_years(entry, _years(t))) for t in spec.tenors]
    # "fwd": tenors are AYxBY strings
    out = []
    for t in spec.tenors:
        a, b = t.upper().split("X")
        e = add_years(entry, _years(a))
        out.append((e, add_years(e, _years(b))))
    return out


def spec_from_episode(*, structure: str, leg_id: Optional[str], side: int,
                      entry: datetime.date, exit: datetime.date,
                      beta_entry: float, ca_dv01: float = CA_DV01_DEFAULT,
                      root: str = "SR3", tag: Optional[str] = None
                      ) -> GVTradeSpec:
    eff, mat = swap_window(structure, entry)
    leg = None
    if leg_id is not None and beta_entry:
        d = leg_dates(leg_id, structure, entry)
        # SIGNED beta: the panel P&L is side*(dCA - beta*dleg)*dv01, so the leg
        # position is -side*beta.  A negative beta FLIPS the leg; it does not
        # shrink it (that abs() shipped once in block 3 and certified at -0.005).
        leg = GVLeg(kind=LEGS[leg_id].kind, dates=tuple(d),
                    leg_dv01_signed=-float(side) * float(beta_entry) * ca_dv01)
    return GVTradeSpec(
        label=structure, side=int(side), entry=entry, exit=exit,
        symbols=tuple(contracts_for(structure, entry, root=root)),
        contracts_per_leg=contracts_per_leg(structure, ca_dv01),
        swap_start=eff, swap_end=mat, ca_dv01=float(ca_dv01), leg=leg,
        leg_id=leg_id,
        tag=tag or f"gv_{structure}_{entry:%Y%m%d}_{'S' if side < 0 else 'L'}")


def build_trade_queries(spec: GVTradeSpec) -> List[Any]:
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
    from Query.STIRFutures.STIRFutureValue import STIRFutureValue

    out: List[Any] = []
    direction = float(-spec.side)
    for sym in spec.symbols:
        out.append(STIRFutureQuery(
            structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
            symbol=sym,
            structure_kwargs={"contracts": int(spec.contracts_per_leg),
                              "risk_weights": [direction]},
            tags=(spec.tag,)))
    out.append(IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV, curve=CURVE,
        effective_date=spec.swap_start, maturity_date=spec.swap_end,
        structure_kwargs={"bpv": float(-spec.side * spec.ca_dv01)},
        tags=(spec.tag,)))
    if spec.leg is not None:
        L = spec.leg
        if L.kind == "fly":
            (fe, fm), (be, bm), (ke, km) = L.dates
            out.append(IRSwapQuery(
                structure=IRSwapStructure.FLY, value=IRSwapValue.NPV, curve=CURVE,
                structure_kwargs={
                    "front_effective_date": fe, "front_maturity_date": fm,
                    "belly_effective_date": be, "belly_maturity_date": bm,
                    "back_effective_date": ke, "back_maturity_date": km,
                    # FRESH list: _build_fly mutates risk_weights in place.
                    "risk_weights": [0.5, 1.0, 0.5],
                    # x2: this block quotes the fly as 2b-f-k, and a [0.5,1,0.5]
                    # package earns bpv/2 per bp of that.
                    "bpv": 2.0 * float(L.leg_dv01_signed)},
                tags=(spec.tag,)))
        else:
            (fe, fm), (be, bm) = L.dates
            out.append(IRSwapQuery(
                structure=IRSwapStructure.CURVE, value=IRSwapValue.NPV, curve=CURVE,
                structure_kwargs={
                    "front_effective_date": fe, "front_maturity_date": fm,
                    "back_effective_date": be, "back_maturity_date": bm,
                    "risk_weights": [1.0, 1.0],
                    # bpv is relative to the BACK leg and the quote is
                    # back - front, so it is 1x, not 2x.
                    "bpv": float(L.leg_dv01_signed)},
                tags=(spec.tag,)))
    return out


def run_backtest(specs: Sequence[GVTradeSpec],
                 trading_days: Sequence[pd.Timestamp], *,
                 futures_mdp: Any = None, swaps_mdp: Any = None,
                 fee_by_tag: Optional[Dict[str, float]] = None,
                 name: str = "gv", show_progress: bool = False) -> Any:
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
        qs = build_trade_queries(spec)
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[spec.entry]),
            actions=[AddQueryAction(query=q, meta={"tags": [spec.tag]})
                     for q in qs]))
        triggers.append(DateTrigger(
            DateTriggerRequirements(dates=[spec.exit]),
            actions=[UnwindPositionsAction(
                match_tag=spec.tag, fee=float(fee_by_tag.get(spec.tag, 0.0)))]))

    grid = TimeGrid([pd.Timestamp(d) for d in trading_days])
    strat = QueryStrategy(name=name, triggers=triggers)
    strat.mdps = {"STIRFUTURE": futures_mdp, "IRS": swaps_mdp}
    strat.default_mdp = swaps_mdp
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=swaps_mdp,
                             show_progress=show_progress)
    bt.run()
    return bt


def assert_ran(bt: Any, specs: Sequence[GVTradeSpec], *,
               expect_days: Optional[int] = None) -> pd.Series:
    """``QueryDrivenBacktest.run()`` swallows exceptions and prints them, so a
    failed backtest looks like a flat equity curve.  Prove the book traded."""
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
    n_min = sum(len(s.symbols) + 1 + (1 if s.leg is not None else 0)
                for s in specs)
    assert len(closed) >= n_min, (
        f"{len(closed)} closed positions < {n_min} legs planned -- an unwind "
        "never matched its tag")
    return eq
