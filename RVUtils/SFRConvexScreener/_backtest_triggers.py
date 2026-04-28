"""Entry/exit triggers for the SFR Convex Screener backtest.

Both triggers wrap ``FlowSignalTriggerRequirements`` with a ``signal_fn`` that
looks up the date-keyed signal table and emits orders/unwinds. Entry uses
``AddQueryAction``; exit uses ``UnwindPositionsAction``.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from BT.event import TriggerInfo
from BT.query_actions import AddQueryAction, UnwindPositionsAction
from BT.query_order import QueryOrder, UnwindOrder
from BT.triggers import FlowSignalTriggerRequirements, Trigger

from RVUtils.SFRConvexScreener._backtest_query import (
    structure_position_tag,
    structure_to_query,
)
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal

logger = logging.getLogger(__name__)


@dataclass
class SFRScreenerBacktestConfig:
    # --- Curve / sizing ---
    curve: str = "USD-SOFR-1D-Q12STIRT"
    bpv_per_trade: float = 100_000.0

    # --- Entry filters ---
    entry_min_asymmetry: float = 1.5  # uses max(A, 1/A) so direction-agnostic
    entry_min_composite_score: float = 0.0
    skip_stale: bool = True
    structure_types: Tuple[str, ...] = ("outright", "calendar", "butterfly")
    max_concurrent: int = 5
    rebalance_dow: Optional[int] = None  # 0=Mon ... 4=Fri; None = every day

    # --- Exit conditions (first match wins) ---
    exit_asymmetry_threshold: float = 1.10  # asymmetry decays below -> exit
    exit_take_profit_bp: Optional[float] = None  # exit if MTM >= +X bp
    exit_stop_loss_bp: Optional[float] = None    # exit if MTM <= -X bp
    exit_max_holding_days: int = 22

    # --- Costs (passed through via UnwindOrder fee) ---
    round_trip_cost_bp: float = 0.5


def _asym_magnitude(a: float) -> float:
    if a is None or not (a == a):  # NaN-safe
        return 0.0
    if a <= 0:
        return 0.0
    return max(a, 1.0 / a)


def _entry_signal_fn(table, config):
    def fn(state: datetime.datetime, backtest=None):
        if config.rebalance_dow is not None and state.weekday() != config.rebalance_dow:
            return TriggerInfo(False)
        target_date = state.date()
        sigs = table.get(target_date) or []
        if not sigs:
            return TriggerInfo(False)

        passing: List[BacktestSignal] = []
        for s in sigs:
            if s.structure_def.structure_type.value not in config.structure_types:
                continue
            if config.skip_stale and s.is_stale:
                continue
            if _asym_magnitude(s.asymmetry_ratio) < config.entry_min_asymmetry:
                continue
            if s.composite_score < config.entry_min_composite_score:
                continue
            passing.append(s)
        if not passing:
            return TriggerInfo(False)

        passing.sort(key=lambda s: s.composite_score, reverse=True)

        open_tags: set = set()
        if backtest is not None:
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))
        passing = [s for s in passing if structure_position_tag(s) not in open_tags]
        if not passing:
            return TriggerInfo(False)

        n_open = len(backtest.portfolio.positions) if backtest is not None else 0
        slots = max(0, config.max_concurrent - n_open)
        if slots == 0:
            return TriggerInfo(False)
        passing = passing[:slots]

        orders: List[QueryOrder] = []
        for s in passing:
            try:
                q = structure_to_query(
                    s, curve=config.curve, bpv=config.bpv_per_trade,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "failed to build entry query for %s: %s",
                    s.structure_def.structure_id, exc,
                )
                continue
            orders.append(
                QueryOrder(
                    timestamp=state,
                    query=q,
                    meta={
                        "action": "sfr_screener_entry",
                        "tags": [structure_position_tag(s)],
                        "structure_id": s.structure_def.structure_id,
                        "structure_type": s.structure_def.structure_type.value,
                        "direction": s.direction,
                        "flip": s.flip,
                        "entry_asymmetry": s.asymmetry_ratio,
                        "entry_composite": s.composite_score,
                        "entry_mean_bp": s.mean_bp,
                        "entry_carry_3m_bp": s.carry_3m_bp,
                        "entry_rolldown_bp": s.rolldown_bp,
                    },
                )
            )
        if not orders:
            return TriggerInfo(False)
        return TriggerInfo(True, {AddQueryAction: orders})

    return fn


class _PassThroughEntryAction:
    """Returns the entry orders that were pre-staged by the signal_fn."""

    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return list(info.get(AddQueryAction, []))


def build_entry_trigger(
    signal_table: Dict[datetime.date, List[BacktestSignal]],
    config: SFRScreenerBacktestConfig,
) -> Trigger:
    """Wire a FlowSignalTriggerRequirements that emits AddQueryAction orders."""
    reqs = FlowSignalTriggerRequirements(signal_fn=_entry_signal_fn(signal_table, config))
    return Trigger(trigger_requirements=reqs, actions=[_PassThroughEntryAction()])
