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


def _signal_table_by_tag(sigs: List[BacktestSignal]) -> Dict[str, BacktestSignal]:
    return {f"sfr_screener_{s.structure_def.structure_id}": s for s in sigs}


def _position_pnl_bp(pos: Any, backtest: Any, bpv: float, now: Any = None) -> Optional[float]:
    """Per-position MTM in bp via the engine's pricer.

    Uses the position's PositionHandler to value the position at ``now`` and
    divides by ``bpv``. Position NPV at construction is 0 (par swap), so
    NPV at ``now`` = realized + unrealized P&L expressed in dollars; dividing
    by bpv ($/bp) yields the move in bp.

    Falls back to the portfolio-level mtm_history short-circuit (single-
    position only) on any pricer exception so the rest of the pipeline
    keeps moving.
    """
    if bpv <= 0:
        return None
    try:
        engine_now = now if now is not None else getattr(backtest, "_now", None)
        if engine_now is None:
            return None
        h = backtest._handler_for_position(pos)
        npv = h.value_position(
            pos,
            lambda q: backtest._pricer_for_query(q, engine_now),
            engine_now,
            backtest,
        )
        return float(npv) / float(bpv)
    except Exception:
        try:
            mtm_history = getattr(backtest, "mtm_history", {}) or {}
            if not mtm_history:
                return None
            n_open = len(getattr(backtest.portfolio, "positions", []) or [])
            if n_open != 1:
                return None
            latest_dt = max(mtm_history.keys())
            return float(mtm_history[latest_dt]) / float(bpv)
        except Exception:
            return None


def _exit_signal_fn(table, config):
    def fn(state: datetime.datetime, backtest=None):
        if backtest is None or not backtest.portfolio.positions:
            return TriggerInfo(False)

        target_date = state.date()
        sigs_today = table.get(target_date) or []
        signal_by_tag = _signal_table_by_tag(sigs_today)

        unwinds: List[UnwindOrder] = []
        for pos in backtest.portfolio.positions:
            tags = set((pos.meta or {}).get("tags", []))
            screener_tags = [t for t in tags if t.startswith("sfr_screener_")]
            if not screener_tags:
                continue
            tag = screener_tags[0]
            structure_id = (pos.meta or {}).get(
                "structure_id", tag.replace("sfr_screener_", "", 1),
            )
            entry_meta = pos.meta or {}
            exit_reason = None

            sig_today = signal_by_tag.get(tag)

            # 1. Asymmetry decay
            if sig_today is not None and config.exit_asymmetry_threshold is not None:
                a = float(sig_today.asymmetry_ratio)
                if a > 0:
                    edge = (1.0 / a) if entry_meta.get("flip") else a
                    if edge < config.exit_asymmetry_threshold:
                        exit_reason = "asymmetry_decay"

            # 2. Take profit / stop loss via per-position pricer
            if exit_reason is None and (config.exit_take_profit_bp is not None
                                         or config.exit_stop_loss_bp is not None):
                pnl_bp = _position_pnl_bp(pos, backtest, config.bpv_per_trade, now=state)
                if pnl_bp is not None:
                    if (config.exit_take_profit_bp is not None
                            and pnl_bp >= config.exit_take_profit_bp):
                        exit_reason = "tp_bp"
                    elif (config.exit_stop_loss_bp is not None
                            and pnl_bp <= config.exit_stop_loss_bp):
                        exit_reason = "stop_bp"

            # 3. Max holding
            if exit_reason is None and config.exit_max_holding_days is not None:
                opened = getattr(pos, "opened", None)
                if opened is not None:
                    if hasattr(opened, "date"):
                        held = (state.date() - opened.date()).days
                    else:
                        held = (state.date() - opened).days
                    if held >= config.exit_max_holding_days:
                        exit_reason = "max_holding"

            if exit_reason is None:
                continue

            _t = tag
            unwinds.append(
                UnwindOrder(
                    timestamp=state,
                    selector=lambda p, _t=_t: _t in set((p.meta or {}).get("tags", [])),
                    meta={
                        "action": "sfr_screener_exit",
                        "reason": exit_reason,
                        "structure_id": structure_id,
                        "fee": float(config.round_trip_cost_bp),
                    },
                )
            )

        if not unwinds:
            return TriggerInfo(False)
        return TriggerInfo(True, {UnwindPositionsAction: unwinds})

    return fn


class _PassThroughExitAction:
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        return list(info.get(UnwindPositionsAction, []))


def build_exit_trigger(
    signal_table: Dict[datetime.date, List[BacktestSignal]],
    config: SFRScreenerBacktestConfig,
) -> Trigger:
    """Wire a FlowSignalTriggerRequirements that emits UnwindPositionsAction orders."""
    reqs = FlowSignalTriggerRequirements(signal_fn=_exit_signal_fn(signal_table, config))
    return Trigger(trigger_requirements=reqs, actions=[_PassThroughExitAction()])
