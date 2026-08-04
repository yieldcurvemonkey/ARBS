"""Both famb sleeves on ONE portfolio engine: the pre-registered STRG75
richness fade + the always-on short FLY25 carry, sharing a TimeGrid, a
portfolio, and the engine's MTM/realized bookkeeping.

The one wiring subtlety: the standalone fade gated entries on "no open
positions", which the always-open carry would jam forever — here every
gate is TAG-scoped ("famb_fade" vs "famb_fly"), so the sleeves coexist
and the closed-positions log splits cleanly by tag.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

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

from famb_fade_qdb import PRE_REGISTERED, _session_ts


def _has_tag(pos, tag: str) -> bool:
    tags = set(pos.meta.get("tags", ())) | \
        set(getattr(pos.source_query, "tags", ()) or ())
    return tag in tags


@dataclass
class CombinedState:
    entry_session: Optional[int] = None
    entry_rich: Optional[float] = None
    entry_legs: Optional[tuple] = None


def make_combined_backtest(
    panel: pd.DataFrame,            # fade signal panel (famb_fade_qdb)
    schedule: pd.DataFrame,         # fly roll schedule (famb_fly_qdb)
    opt_mdp,
    *,
    fade_thr_bp: float = PRE_REGISTERED["thr_bp"],
    fade_exit_frac: float = PRE_REGISTERED["exit_frac"],
    fade_max_hold: int = PRE_REGISTERED["max_hold"],
    contracts_fade: float = 1.0,
    contracts_fly: float = 1.0,
    fly_side: str = "short",
    tcost_vol_bp: float = 0.125,
    show_progress: bool = True,
):
    panel = panel.sort_values("as_of").reset_index(drop=True)
    grid_dates = pd.DatetimeIndex(sorted(
        set(panel["as_of"]) | set(schedule["start"]) | set(schedule["end"])))
    ts_list = [_session_ts(d) for d in grid_dates]
    fade_sessions = [_session_ts(d) for d in panel["as_of"]]
    fade_ix = {t: i for i, t in enumerate(fade_sessions)}
    state = CombinedState()
    triggers: List[Trigger] = []

    # ---------------- fade sleeve (tag famb_fade) -----------------------
    fade_fee_side = 2.0 * contracts_fade * tcost_vol_bp * 25.0

    def fade_exit(now, bt):
        open_fade = [p for p in bt.portfolio.positions
                     if _has_tag(p, "famb_fade")]
        if not open_fade or now not in fade_ix:
            return False
        i = fade_ix[now]
        row = panel.iloc[i]
        legs_now = (row["put_label"], row["call_label"])
        if state.entry_legs is not None and legs_now != state.entry_legs:
            return True
        if i - (state.entry_session or i) >= fade_max_hold:
            return True
        return (state.entry_rich is not None
                and abs(row["rich_bp"])
                <= fade_exit_frac * abs(state.entry_rich))

    triggers.append(Trigger(
        trigger_requirements=FlowSignalTriggerRequirements(
            signal_fn=fade_exit),
        actions=[UnwindPositionsAction(match_tag="famb_fade",
                                       fee=2.0 * fade_fee_side)],
    ))

    for i in range(1, len(panel)):
        sig, tod = panel.iloc[i - 1], panel.iloc[i]
        if sig["rich_bp"] < fade_thr_bp:
            continue
        if (sig["put_label"], sig["call_label"]) != \
                (tod["put_label"], tod["call_label"]):
            continue
        q = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.STRADDLE,
            value=STIRFutureOptionValue.PRICE,
            contracts=contracts_fade,
            structure_kwargs={"put_symbol": sig["put_label"],
                              "call_symbol": sig["call_label"],
                              "risk_weights": [-1.0, -1.0]},
            tags=("famb_fade",),
        )
        _t = fade_sessions[i]
        _i, _rich = i, float(sig["rich_bp"])
        _legs = (sig["put_label"], sig["call_label"])

        def _enter(now, bt, __t=_t, __i=_i, __rich=_rich, __legs=_legs):
            if now != __t:
                return False
            if any(_has_tag(p, "famb_fade") for p in bt.portfolio.positions):
                return False
            state.entry_session, state.entry_rich = __i, __rich
            state.entry_legs = __legs
            return True

        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=_enter),
            actions=[AddQueryAction(query=q,
                                    meta={"sleeve": "fade",
                                          "entry_rich_bp": _rich})],
        ))

    # ---------------- carry sleeve (tag famb_fly) -----------------------
    fly_weights = ([1.0, -2.0, 1.0] if fly_side == "long"
                   else [-1.0, 2.0, -1.0])
    fly_fee_side = 4.0 * contracts_fly * tcost_vol_bp * 25.0
    for j, row in schedule.iterrows():
        t_in, t_out = _session_ts(row["start"]), _session_ts(row["end"])
        q = STIRFutureOptionQuery(
            structure=STIRFutureOptionStructure.FLY,
            value=STIRFutureOptionValue.PRICE,
            contracts=contracts_fly,
            structure_kwargs={"low_symbol": row["low"],
                              "mid_symbol": row["mid"],
                              "high_symbol": row["high"],
                              "risk_weights": list(fly_weights)},
            tags=("famb_fly", f"h{j}"),
        )
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=lambda now, bt, __t=t_out: now == __t),
            actions=[UnwindPositionsAction(match_tag=f"h{j}",
                                           fee=2.0 * fly_fee_side)],
        ))
        triggers.append(Trigger(
            trigger_requirements=FlowSignalTriggerRequirements(
                signal_fn=lambda now, bt, __t=t_in: now == __t),
            actions=[AddQueryAction(query=q, meta={"sleeve": "carry",
                                                   "holding": int(j)})],
        ))

    strategy = QueryStrategy(name="famb combined book (fade + carry)",
                             triggers=triggers)
    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(ts_list), mdp=opt_mdp, strategy=strategy,
        show_progress=show_progress,
        progress_desc="famb combined (QDB)",
    )
    return bt, state


def split_by_sleeve(cl: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """Closed-positions frame -> {'fade': df, 'carry': df} via order meta."""
    if cl.empty:
        return {"fade": cl, "carry": cl}
    if "position_meta" not in cl.columns:
        raise KeyError("closed-positions frame lacks position_meta")
    sl = cl["position_meta"].apply(lambda m: (m or {}).get("sleeve"))
    return {k: cl[sl == k] for k in ("fade", "carry")}
