"""The pre-registered STRG75 richness fade, ported to QueryDrivenBacktest.

The research replay (famb_common / famb_grid) stays the historical-evidence
artifact; THIS is the forward instrument: positions are
``STIRFutureOptionQuery`` STRADDLE packages (put low / call high = the
strangle) resolved and marked through the production MDP pricers, entries
and exits fire through Triggers, and the portfolio/PnL bookkeeping is the
engine's own.

Pre-registered parameters (findings doc 2026-08-04, unchanged):
    book STRG75, rank 1 (front quarterly), enter when richness >= 4bp,
    fade only (sell the rich strangle), exit at 25% of entry richness or
    15 sessions or the holding roll, one open position, lag-1 signals.

The SIGNAL still comes from the lattice machinery (listed premium minus
ZQ-tree fair, struck at the holding roll) — signals are strategy-side by
design; the engine owns marks, portfolio and realized PnL.

Costs: both sides' half-ticks are booked as the unwind fee
(2 sides x 2 contracts x 0.125bp x $25/bp per package by default).
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
import pytz

from BT.data_handler import TimeGrid
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.triggers import FlowSignalTriggerRequirements, Trigger
from Query.STIRFutureOptions.STIRFutureOptionQuery import STIRFutureOptionQuery
from Query.STIRFutureOptions.STIRFutureOptionStructure import (
    STIRFutureOptionStructure,
)
from Query.STIRFutureOptions.STIRFutureOptionValue import STIRFutureOptionValue

NY = pytz.timezone("America/New_York")

PRE_REGISTERED = dict(book="STRG75", rank=1, thr_bp=4.0, exit_frac=0.25,
                      max_hold=15)


def opt_label(symbol: str, right: str, strike_price: float) -> str:
    """'SFRZ26' + 'P' + 95.00 -> 'SFRZ26|9500P' (strikes on the 0.25 grid)."""
    return f"{symbol}|{int(round(strike_price * 100))}{right}"


def build_signal_panel(start=None, end=None, cfg: Dict = PRE_REGISTERED,
                       return_holdings: bool = False):
    """One row per session: the active holding's strangle legs + richness.

    Reuses the famb spine (parity-completed surface, rolled book, tree-fair
    via the MeetingProb pricer). The legs are FIXED within each holding —
    exactly the object the pre-registered rule watches.
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
    rows = []
    for h in holdings:
        put = next((l for l in h.legs if l[0] == "P"), None)
        call = next((l for l in h.legs if l[0] == "C"), None)
        if put is None or call is None:
            continue
        rich = (h.marks - h.fair).dropna()
        for ts, r in rich.items():
            rows.append({
                "as_of": ts, "symbol": h.symbol,
                "put_label": opt_label(h.symbol, "P", put[1]),
                "call_label": opt_label(h.symbol, "C", call[1]),
                "rich_bp": float(r),
                "holding_start": h.marks.index[0],
            })
    panel = pd.DataFrame(rows).sort_values("as_of").reset_index(drop=True)
    return (panel, holdings) if return_holdings else panel


def _session_ts(d: pd.Timestamp, hour: int = 17) -> datetime.datetime:
    return NY.localize(datetime.datetime(d.year, d.month, d.day, hour, 0))


@dataclass
class FadeState:
    """Mutable cross-trigger state the closures share."""

    panel: pd.DataFrame
    session_of: Dict[datetime.datetime, int] = field(default_factory=dict)
    entry_session: Optional[int] = None
    entry_rich: Optional[float] = None
    entry_legs: Optional[tuple] = None


def make_fade_backtest(
    panel: pd.DataFrame,
    mdp,
    *,
    contracts: float = 1.0,
    thr_bp: float = PRE_REGISTERED["thr_bp"],
    exit_frac: float = PRE_REGISTERED["exit_frac"],
    max_hold: int = PRE_REGISTERED["max_hold"],
    fee_per_side_usd: float = 2 * 0.125 * 25.0,   # 2 contracts x half-tick
    show_progress: bool = True,
) -> QueryDrivenBacktest:
    """Wire the pre-registered rule into triggers on a daily TimeGrid."""
    panel = panel.sort_values("as_of").reset_index(drop=True)
    sessions = [_session_ts(d) for d in panel["as_of"]]
    state = FadeState(panel=panel,
                      session_of={ts: i for i, ts in enumerate(sessions)})

    # --- exit trigger (dynamic; evaluated before entries) ---------------
    def exit_signal(now, backtest):
        if not backtest.portfolio.positions or now not in state.session_of:
            return False
        i = state.session_of[now]
        row = panel.iloc[i]
        legs_now = (row["put_label"], row["call_label"])
        if state.entry_legs is not None and legs_now != state.entry_legs:
            return True                              # holding rolled
        held = i - (state.entry_session or i)
        if held >= max_hold:
            return True
        if state.entry_rich is not None and \
                abs(row["rich_bp"]) <= exit_frac * abs(state.entry_rich):
            return True
        return False

    exit_trigger = Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=exit_signal),
        actions=[UnwindPositionsAction(match_all=True,
                                       fee=2 * fee_per_side_usd)],
    )

    # --- entry triggers (one per session, lag-1: signal row i-1) --------
    entry_triggers: List[Trigger] = []
    for i in range(1, len(panel)):
        sig, tod = panel.iloc[i - 1], panel.iloc[i]
        if sig["rich_bp"] < thr_bp:
            continue
        if (sig["put_label"], sig["call_label"]) != \
                (tod["put_label"], tod["call_label"]):
            continue                                 # roll between signal+entry
        q = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.STRADDLE,
            value=STIRFutureOptionValue.PRICE,
            contracts=contracts,
            structure_kwargs={
                "put_symbol": sig["put_label"],
                "call_symbol": sig["call_label"],
                "risk_weights": [-1.0, -1.0],        # SELL the strangle
            },
            tags=("famb_fade",),
        )
        _ts = sessions[i]
        _i, _rich = i, float(sig["rich_bp"])
        _legs = (sig["put_label"], sig["call_label"])

        def _entry(now, backtest, __ts=_ts, __i=_i, __rich=_rich,
                   __legs=_legs):
            if now != __ts or backtest.portfolio.positions:
                return False
            state.entry_session, state.entry_rich = __i, __rich
            state.entry_legs = __legs
            return True

        entry_triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=_entry),
            actions=[AddQueryAction(
                query=q, meta={"entry_rich_bp": _rich,
                               "entry_session": _i})],
        ))

    strategy = QueryStrategy(
        name="famb pre-registered STRG75 fade",
        triggers=[exit_trigger] + entry_triggers,
    )
    return QueryDrivenBacktest(
        time_grid=TimeGrid(sessions), mdp=mdp, strategy=strategy,
        show_progress=show_progress,
        progress_desc="STRG75 fade (QDB)",
    )


def closed_positions_frame(bt: QueryDrivenBacktest) -> pd.DataFrame:
    log = getattr(bt.portfolio, "closed_positions_log", [])
    if not log:
        return pd.DataFrame()
    df = pd.DataFrame(log)
    for c in ("opened_at", "closed_at"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df
