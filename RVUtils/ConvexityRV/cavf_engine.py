r"""QueryDrivenBacktest wiring for the CA-vs-fly block.

Generalises ``strat2_sofr_convexity``'s engine recipe to any structure in
``cavf_universe`` (packs, CME bundles, outrights), BOTH sides of the spread,
and any declared fly (spot or forward-starting), with the fly legs pinned to
explicit dates at entry — a relative tenor re-resolves at every mark and prices
a fresh at-market package forever (the w4 defect), and the aged-swap drift of a
tenor-resolved fly is exactly why the previous grid's hedged dollars would not
certify.

Sign map (one place, asserted by the notebook's live sign probe):

===========  ==================  =====================  ======================
``side``     futures contracts   matched swap ``bpv``   fly belly ``bpv``
===========  ==================  =====================  ======================
−1 (short    ``+n`` per leg      ``+CA_DV01`` (payer)   ``+belly_dv01`` (pay
spread,      (long futures)                             the belly)
Citi's book)
+1 (long     ``−n`` per leg      ``−CA_DV01``           ``−belly_dv01``
spread)      (short futures)     (receiver)             (receive the belly)
===========  ==================  =====================  ======================

Short spread = short CA + long β·fly: buy the pack, pay the matched swap, pay
the belly — Citi's ticket verbatim. ``P&L ≈ side·(ΔCA − β·Δfly)·CA_DV01``.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from RVUtils.ConvexityRV.cavf_universe import (
    CA_DV01_DEFAULT,
    contracts_for,
    contracts_per_leg,
    structure_by_label,
    swap_window,
)
from RVUtils.ConvexityRV.strat2_fly_universe import FlySpec, tenor_key

__all__ = [
    "CavfFlyLeg",
    "CavfTradeSpec",
    "assert_ran",
    "build_trade_queries",
    "fly_leg_dates",
    "run_backtest",
    "spec_from_episode",
]


@dataclass(frozen=True)
class CavfFlyLeg:
    """The fly attached to one epoch, resolved and signed at entry."""

    front: Tuple[datetime.date, datetime.date]
    belly: Tuple[datetime.date, datetime.date]
    back: Tuple[datetime.date, datetime.date]
    w_front: float
    w_back: float
    belly_dv01: float          # SIGNED: >0 pays the belly


@dataclass(frozen=True)
class CavfTradeSpec:
    label: str
    side: int
    entry: datetime.date
    exit: datetime.date
    symbols: Tuple[str, ...]
    contracts_per_leg: int
    swap_start: datetime.date
    swap_end: datetime.date
    ca_dv01: float
    fly: Optional[CavfFlyLeg]
    tag: str


def _add_years(d: datetime.date, years: float) -> datetime.date:
    months = int(round(years * 12))
    y, m = divmod((d.month - 1) + months, 12)
    out = datetime.date(d.year + y, m + 1, min(d.day, 28))
    return out


def fly_leg_dates(fly: FlySpec, entry: datetime.date
                  ) -> Dict[str, Tuple[datetime.date, datetime.date]]:
    """Explicit (effective, maturity) per leg, resolved AT ENTRY.

    Spot legs start at entry; a forward start shifts the effective date. The
    day-of-month convention is the 28th-capped calendar add — the engine's
    schedule builder applies its own business-day roll, and what matters here
    is that the instrument is PINNED, not which holiday rule pins it.
    """
    eff0 = _add_years(entry, fly.forward_start_y) if fly.forward_start_y else entry
    out = {}
    for name, tenor_y in (("front", fly.front_y), ("belly", fly.belly_y),
                          ("back", fly.back_y)):
        out[name] = (eff0, _add_years(eff0, tenor_y))
    return out


def spec_from_episode(*, label: str, side: int, entry: datetime.date,
                      exit: datetime.date, beta_entry: float,
                      fly: Optional[FlySpec],
                      ca_dv01: float = CA_DV01_DEFAULT,
                      root: str = "SR3", tag: Optional[str] = None
                      ) -> CavfTradeSpec:
    """Resolve one panel episode into engine instruments, all as of ENTRY."""
    eff, mat = swap_window(label, entry)
    fly_leg = None
    if fly is not None and beta_entry != 0.0:
        d = fly_leg_dates(fly, entry)
        # SIGNED β: the panel P&L is side·(ΔCA − β·Δfly)·dv01, so the fly
        # position is −side·β — a negative β flips the belly, it does not
        # shrink it. An abs() here shipped once and certified at corr −0.005.
        fly_leg = CavfFlyLeg(
            front=d["front"], belly=d["belly"], back=d["back"],
            w_front=0.5, w_back=0.5,
            belly_dv01=-side * beta_entry * ca_dv01)
    return CavfTradeSpec(
        label=label, side=side, entry=entry, exit=exit,
        symbols=tuple(contracts_for(label, entry, root=root)),
        contracts_per_leg=contracts_per_leg(label, ca_dv01),
        swap_start=eff, swap_end=mat, ca_dv01=ca_dv01, fly=fly_leg,
        tag=tag or f"cavf_{label}_{entry:%Y%m%d}_{'S' if side < 0 else 'L'}")


def build_trade_queries(spec: CavfTradeSpec) -> List[Any]:
    """N futures legs + the matched swap + (optionally) the date-pinned fly.

    Futures legs are SEPARATE OUTRIGHT queries — the STIR handler marks a
    multi-leg package with the unweighted PV01 sum against the risk-weighted
    price sum, which multiplies a pack's P&L by its leg count. ``risk_weights``
    for the fly is a FRESH list: ``_build_fly`` mutates it in place.
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
    from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
    from Query.STIRFutures.STIRFutureValue import STIRFutureValue

    out: List[Any] = []
    # Direction rides the RISK WEIGHT with contracts kept positive. A negative
    # ``contracts`` is a measured trap: the outright builder flips the weight
    # to −1 AND the rateslib leg carries the negative size, so the two
    # negations cancel and the "short" book is long — certified at corr −0.005
    # before this was found. −side: short spread (−1) buys the futures.
    direction = float(-spec.side)
    for sym in spec.symbols:
        out.append(STIRFutureQuery(
            structure=STIRFutureStructure.OUTRIGHT, value=STIRFutureValue.PRICE,
            symbol=sym,
            structure_kwargs={"contracts": int(spec.contracts_per_leg),
                              "risk_weights": [direction]},
            tags=(spec.tag,)))
    out.append(IRSwapQuery(
        structure=IRSwapStructure.OUTRIGHT, value=IRSwapValue.NPV,
        curve="USD-SOFR-1D",
        effective_date=spec.swap_start, maturity_date=spec.swap_end,
        structure_kwargs={"bpv": float(-spec.side * spec.ca_dv01)},
        tags=(spec.tag,)))
    if spec.fly is not None:
        f = spec.fly
        out.append(IRSwapQuery(
            structure=IRSwapStructure.FLY, value=IRSwapValue.NPV,
            curve="USD-SOFR-1D",
            structure_kwargs={
                "front_effective_date": f.front[0], "front_maturity_date": f.front[1],
                "belly_effective_date": f.belly[0], "belly_maturity_date": f.belly[1],
                "back_effective_date": f.back[0], "back_maturity_date": f.back[1],
                "risk_weights": [float(f.w_front), 1.0, float(f.w_back)],
                "bpv": float(f.belly_dv01)},
            tags=(spec.tag,)))
    return out


def run_backtest(specs: Sequence[CavfTradeSpec],
                 trading_days: Sequence[pd.Timestamp], *,
                 futures_mdp: Any = None, swaps_mdp: Any = None,
                 fee_by_tag: Optional[Dict[str, float]] = None,
                 name: str = "cavf", show_progress: bool = False) -> Any:
    """The QDB wiring, per the house recipe. Caller must ``assert_ran``."""
    from BT.data_handler import TimeGrid
    from BT.query_actions import AddQueryAction, UnwindPositionsAction
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.triggers import DateTrigger, DateTriggerRequirements
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

    futures_mdp = futures_mdp or STIRFutureMDP(source="BARCHART_STIRF-RL")
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
            actions=[UnwindPositionsAction(match_tag=spec.tag,
                                           fee=float(fee_by_tag.get(spec.tag, 0.0)))]))

    grid = TimeGrid([pd.Timestamp(d) for d in trading_days])
    strat = QueryStrategy(name=name, triggers=triggers)
    strat.mdps = {"STIRFUTURE": futures_mdp, "IRS": swaps_mdp}
    strat.default_mdp = swaps_mdp
    bt = QueryDrivenBacktest(time_grid=grid, strategy=strat, mdp=swaps_mdp,
                             show_progress=show_progress)
    bt.run()
    return bt


def assert_ran(bt: Any, specs: Sequence[CavfTradeSpec], *,
               expect_days: Optional[int] = None) -> pd.Series:
    """``run()`` swallows exceptions — prove the book actually traded."""
    assert len(specs) > 0, (
        "no specs were planned — a flat equity curve here is a planning "
        "failure upstream, not a trading result")
    eq = pd.Series(bt.mtm_history)
    assert len(eq) > 0, "mtm_history is empty — the engine swallowed an exception"
    if expect_days is not None:
        assert len(eq) == expect_days, f"expected {expect_days} marks, got {len(eq)}"
    eq.index = pd.to_datetime(eq.index)
    eq = eq.sort_index()
    assert float(eq.abs().max()) > 0.0, (
        "equity is identically zero — no trigger ever fired; check that the "
        "trigger dates are datetime.date and inside the time grid")
    closed = bt.portfolio.closed_positions_log
    n_legs_min = sum(
        len(s.symbols) + 1 + (1 if s.fly is not None else 0) for s in specs)
    assert len(closed) >= n_legs_min, (
        f"{len(closed)} closed positions < {n_legs_min} legs planned — an "
        "unwind never matched its tag")
    return eq
