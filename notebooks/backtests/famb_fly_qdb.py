"""The FLY25 carry book, fully ported to QueryDrivenBacktest.

Always-on short (or long) 1/-2/1 butterfly on the front quarterly, struck
at the ZQ-tree mode, rolled at expiry-3d — the vol leg is a first-class
``STIRFutureOptionStructure.FLY`` query marked through the MDP's QL
pricers. The optional LINEAR leg is an SR3 futures delta hedge
(``STIRFutureQuery`` OUTRIGHT) rebalanced when the package delta drifts
beyond a threshold, sized dynamically through ``AddQueryFactoryAction``.

T-costs are configurable per leg type:

* ``tcost_vol_bp`` — per OPTION contract per side (half-tick 0.125bp
  default; a 1-lot fly is 4 contracts, so a package round trip is
  ``2 x 4 x tcost_vol_bp x $25``). Booked inside the engine as the roll
  unwind fee.
* ``tcost_linear_bp`` — per FUTURES contract per side (half-tick 0.25bp
  default). Hedge trade sizes are path-dependent, so linear costs are
  accumulated on the strategy state (``state.linear_traded_contracts``)
  and reported/deducted analytically — disclosed, not hidden.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz

from BT.data_handler import TimeGrid
from BT.query_actions import (AddQueryAction, AddQueryFactoryAction,
                              UnwindPositionsAction)
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import FlowSignalTriggerRequirements, Trigger
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import (
    STIRFutureOptionStructure,
)
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue
from Query.STIRFutures.STIRFutureQuery import STIRFutureQuery
from Query.STIRFutures.STIRFutureStructure import STIRFutureStructure
from Query.STIRFutures.STIRFutureValue import STIRFutureValue

from famb_fade_qdb import opt_label

NY = pytz.timezone("America/New_York")

FLY_CFG = dict(book="FLY25", rank=1, side="short")


def build_roll_schedule(start=None, end=None, cfg: Dict = FLY_CFG,
                        return_holdings: bool = False):
    """(schedule frame, session index) from the famb rolled book.

    One row per holding: option leg labels (all-call fly at the tree-modal
    strike), futures underlying, and the first/last session of the holding
    (the last session IS the roll).
    """
    from famb_common import (TreeCtx, build_book, load_quotes,
                             premium_surface, sr3_forwards)

    quotes = load_quotes()
    if start is not None:
        quotes = quotes[quotes["as_of"] >= pd.Timestamp(start)]
    if end is not None:
        quotes = quotes[quotes["as_of"] <= pd.Timestamp(end)]
    symbols = sorted(quotes["symbol"].unique())
    fwd = sr3_forwards(symbols)
    fwd["as_of"] = pd.to_datetime(fwd["as_of"])
    surface = premium_surface(quotes, fwd)
    fwd_idx = fwd.set_index(["as_of", "symbol"])["fwd_rate"].sort_index()
    dates = pd.DatetimeIndex(sorted(quotes["as_of"].unique()))
    tree = TreeCtx([d.date() for d in dates])
    holdings = build_book(cfg["book"], cfg["rank"], dates, surface, fwd_idx,
                          tree)
    rows, sessions = [], set()
    for h in holdings:
        ks = sorted(k for _, k, _ in h.legs)
        if len(ks) != 3:
            continue
        rows.append({
            "symbol": h.symbol,
            "future": "SR3" + h.symbol[3:],
            "low": opt_label(h.symbol, "C", ks[0]),
            "mid": opt_label(h.symbol, "C", ks[1]),
            "high": opt_label(h.symbol, "C", ks[2]),
            "start": h.marks.index[0], "end": h.marks.index[-1],
        })
        sessions.update(h.marks.index)
    out = (pd.DataFrame(rows).sort_values("start").reset_index(drop=True),
           pd.DatetimeIndex(sorted(sessions)))
    return (*out, holdings) if return_holdings else out


def _ts(d: pd.Timestamp, hour: int = 17) -> datetime.datetime:
    return NY.localize(datetime.datetime(d.year, d.month, d.day, hour, 0))


@dataclass
class FlyState:
    """Strategy-side bookkeeping the engine does not own."""

    hedge_contracts: float = 0.0        # signed, current
    hedge_target: float = 0.0
    linear_traded_contracts: float = 0.0
    n_rebalances: int = 0
    deltas: Dict[datetime.datetime, float] = field(default_factory=dict)


def package_delta(bt: QueryDrivenBacktest, now: datetime.datetime) -> float:
    """Signed futures-equivalent delta of the open FLY package(s)."""
    total = 0.0
    for pos in bt.portfolio.positions:
        tags = set(pos.meta.get("tags", ())) | \
            set(getattr(pos.source_query, "tags", ()) or ())
        if "famb_fly" not in tags:
            continue
        pr = bt._pricer_for_query(pos.source_query, now)
        for leg, rw in zip(pos.package, pos.weights):
            plist = pr.get(leg.symbol()) if hasattr(pr, "get") else None
            if not plist:
                continue
            p = plist[0]
            d = p.delta() if callable(p.delta) else p.delta
            total += float(rw) * float(leg.quantity()) * float(d)
    return total


def make_fly_backtest(
    schedule: pd.DataFrame,
    sessions: pd.DatetimeIndex,
    opt_mdp,
    fut_mdp=None,
    *,
    contracts: float = 1.0,
    side: str = FLY_CFG["side"],
    tcost_vol_bp: float = 0.125,
    tcost_linear_bp: float = 0.25,
    hedge: bool = False,
    hedge_threshold: float = 0.5,       # rebalance when |target-current| >=
    show_progress: bool = True,
) -> Tuple[QueryDrivenBacktest, FlyState]:
    ts_list = [_ts(d) for d in sessions]
    session_of = {t: i for i, t in enumerate(ts_list)}
    state = FlyState()
    weights = [1.0, -2.0, 1.0] if side == "long" else [-1.0, 2.0, -1.0]
    opt_fee_side = 4.0 * contracts * tcost_vol_bp * 25.0

    triggers: List[Trigger] = []
    for i, row in schedule.iterrows():
        t_in, t_out = _ts(row["start"]), _ts(row["end"])
        q = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.FLY,
            value=STIRFutureOptionValue.PRICE,
            contracts=contracts,
            structure_kwargs={
                "low_symbol": row["low"], "mid_symbol": row["mid"],
                "high_symbol": row["high"], "risk_weights": list(weights),
            },
            tags=("famb_fly", f"h{i}"),
        )
        # roll out of the holding at its last session (both sides' option
        # costs booked here; entries themselves are fee-free by symmetry)
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=lambda now, bt, __t=t_out: now == __t),
            actions=[UnwindPositionsAction(match_tag=f"h{i}",
                                           fee=2.0 * opt_fee_side)],
        ))

        # each holding enters exactly at its start session; the exit trigger
        # for the PREVIOUS holding sits earlier in the trigger list, so the
        # roll day executes [unwind old, add new] in one batch — no gate on
        # open positions (it would see the outgoing package and refuse)
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=lambda now, bt, __t=t_in: now == __t),
            actions=[AddQueryAction(query=q, meta={"holding": int(i)})],
        ))

    if hedge:
        if fut_mdp is None:
            raise ValueError("hedge=True requires fut_mdp")

        def _needs_rebalance(now, bt):
            if now not in session_of or not bt.portfolio.positions:
                return False
            delta = package_delta(bt, now)
            state.deltas[now] = delta
            state.hedge_target = -delta
            return abs(state.hedge_target
                       - state.hedge_contracts) >= hedge_threshold

        def _hedge_factory(*, now, backtest, info):
            tgt = state.hedge_target
            state.linear_traded_contracts += abs(tgt - state.hedge_contracts)
            state.n_rebalances += 1
            state.hedge_contracts = tgt
            if abs(tgt) < 1e-9:
                return None
            fut_row = schedule[[_ts(s) <= now <= _ts(e) for s, e in
                                zip(schedule["start"], schedule["end"])]]
            fut = fut_row.iloc[-1]["future"] if len(fut_row) else \
                schedule.iloc[-1]["future"]
            return STIRFutureQuery(
                structure=STIRFutureStructure.OUTRIGHT,
                value=STIRFutureValue.PRICE,
                symbol=fut,
                structure_kwargs={"contracts": abs(tgt),
                                  "risk_weights": [float(np.sign(tgt))]},
                tags=("fly_hedge",),
            )

        triggers.insert(0, Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=_needs_rebalance),
            actions=[UnwindPositionsAction(match_tag="fly_hedge", fee=0.0),
                     AddQueryFactoryAction(query_factory=_hedge_factory)],
        ))

    strategy = QueryStrategy(
        name=f"famb {side} FLY25 carry" + (" + delta hedge" if hedge else ""),
        triggers=triggers,
        mdps={"STIRFUTUREOPTION": opt_mdp, "STIRFUTURE": fut_mdp}
        if fut_mdp is not None else None,
        default_mdp=opt_mdp,
    )
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(ts_list), mdp=opt_mdp, strategy=strategy,
        show_progress=show_progress,
        progress_desc=f"{side} FLY25 carry (QDB)",
    )
    return bt, state


def linear_cost_usd(state: FlyState, tcost_linear_bp: float) -> float:
    """Analytic linear-leg cost: traded futures contracts x per-side cost."""
    return state.linear_traded_contracts * tcost_linear_bp * 25.0
