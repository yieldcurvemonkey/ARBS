"""Trigger adapter wiring IRSwap PCA RV scanner into QueryDrivenBacktest.

Follows the proven _JPMRVQuerySignalAction pattern from jpm_rv_backtest.py:
  - Single unified action handles both entry and exit
  - TriggerRequirements always fires; action contains all logic
  - Exit checks use LIVE curve pricer (not pre-computed signal table)
  - Entry checks do simple date-based lookups into pre-computed signal table
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

from BT.event import TriggerInfo
from BT.triggers import Trigger, TriggerRequirements
from BT.query_order import QueryOrder, UnwindOrder
from BT.signals.irswap_pca_rv_scanner import IRSwapAnalyzedTrade, IRSwapPCARVConfig

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _fly_tag(trade: IRSwapAnalyzedTrade) -> str:
    """Deterministic tag for a fly position."""
    fwd = trade.candidate.forward_start or "spot"
    left, belly, right = trade.candidate.tenors
    return f"pca_rv_{fwd}_{left}_{belly}_{right}"


def _match_signal_table(signal_table: dict, state_dt) -> List[IRSwapAnalyzedTrade]:
    """Find trades in signal_table matching the given state datetime.

    Handles tz-naive vs tz-aware mismatches by comparing date components.
    """
    ts = pd.Timestamp(state_dt)

    # Direct lookup
    trades = signal_table.get(ts, [])
    if trades:
        return trades

    # Strip tz and try again
    ts_naive = ts.tz_localize(None) if ts.tzinfo is not None else ts
    trades = signal_table.get(ts_naive, [])
    if trades:
        return trades

    # Fallback: match by calendar date
    target_date = ts.date()
    for key, val in signal_table.items():
        if pd.Timestamp(key).date() == target_date:
            return val

    return []


def _build_fly_query(
    trade: IRSwapAnalyzedTrade,
    config: IRSwapPCARVConfig,
) -> Any:
    """Build an IRSwapQuery for the PCA butterfly."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure

    left_t, belly_t, right_t = trade.candidate.tenors
    fwd = trade.candidate.forward_start

    # Build tenor strings with forward start
    if fwd:
        front = f"{fwd}x{left_t}"
        belly = f"{fwd}x{belly_t}"
        back = f"{fwd}x{right_t}"
    else:
        front = left_t
        belly = belly_t
        back = right_t

    w_left, _, w_right = trade.candidate.weights

    # Direction: receive_belly → positive bpv (receive fixed on belly)
    #            pay_belly     → negative bpv (pay fixed on belly)
    direction_sign = 1.0 if trade.candidate.direction == "receive_belly" else -1.0
    signed_bpv = direction_sign * config.trade_belly_bpv

    # Risk weights: absolute values of PCA weights
    # The sign convention is handled by signed_bpv
    risk_weights = [abs(w_left), 1.0, abs(w_right)]

    return IRSwapQuery(
        structure=IRSwapStructure.FLY,
        curve=config.curve,
        structure_kwargs={
            "front_tenor": front,
            "belly_tenor": belly,
            "back_tenor": back,
            "bpv": signed_bpv,
            "risk_weights": risk_weights,
        },
        tags=tuple(["pca_rv", _fly_tag(trade)]),
    )


def _build_rate_query_for_tenor(tenor: str, fwd: Optional[str], config: IRSwapPCARVConfig) -> Any:
    """Build a simple rate query for computing live fly levels."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue

    t = f"{fwd}x{tenor}" if fwd else tenor
    return IRSwapQuery(curve=config.curve, tenor=t, value=IRSwapValue.RATE)


# ═══════════════════════════════════════════════════════════════════
# Unified Signal Action (entry + exit in one pass)
# ═══════════════════════════════════════════════════════════════════

class IRSwapPCARVSignalAction:
    """Combined entry/exit action for PCA RV butterflies.

    Called each timestep by QueryDrivenBacktest via Trigger.actions.
    Handles:
      1. Exit checks for open positions (target, stop-loss, max hold)
      2. Entry checks for new candidates from signal table
    """

    def __init__(
        self,
        signal_table: Dict[pd.Timestamp, List[IRSwapAnalyzedTrade]],
        config: IRSwapPCARVConfig,
    ):
        self.signal_table = signal_table
        self.config = config
        self.risk = None  # Required by Trigger action interface

    def __call__(self, *, now, backtest, info) -> List[Union[QueryOrder, UnwindOrder]]:
        orders: List[Union[QueryOrder, UnwindOrder]] = []
        ts = pd.Timestamp(now)

        # ── EXITS: check all open PCA RV positions ──────────────
        positions_to_check = [
            pos for pos in backtest.portfolio.positions
            if self._is_pca_rv_position(pos)
        ]

        for pos in positions_to_check:
            exit_reason = self._check_exit(pos, now, backtest)
            if exit_reason is not None:
                tag = self._get_position_tag(pos)
                orders.append(UnwindOrder(
                    timestamp=now,
                    selector=lambda p, _t=tag: _t in set((p.meta or {}).get("tags", [])),
                    meta={"action": "pca_rv_exit", "reason": exit_reason},
                ))

        # ── ENTRIES: look up signal table for new candidates ────
        trades_today = _match_signal_table(self.signal_table, now)
        passing = [t for t in trades_today if t.passes_filter]

        if passing:
            # Filter out flies already in portfolio
            open_tags = set()
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))

            passing = [t for t in passing if _fly_tag(t) not in open_tags]

            # Respect max concurrent positions
            n_open = len(backtest.portfolio.positions)
            remaining_slots = max(0, self.config.max_concurrent_positions - n_open)
            passing = passing[:remaining_slots]

            # Rank by absolute lifetime Z-score (strongest signals first)
            passing.sort(key=lambda t: abs(t.lifetime_zscore), reverse=True)

            for trade in passing:
                try:
                    q = _build_fly_query(trade, self.config)
                    orders.append(QueryOrder(
                        timestamp=now,
                        query=q,
                        meta={
                            "action": "pca_rv_entry",
                            "tags": [_fly_tag(trade)],
                            "direction": trade.candidate.direction,
                            "tenors": list(trade.candidate.tenors),
                            "weights": list(trade.candidate.weights),
                            "forward_start": trade.candidate.forward_start,
                            "lifetime_zscore": trade.lifetime_zscore,
                            "target": trade.target_level,
                            "stop_loss": trade.stop_loss_level,
                            "investment_horizon": trade.investment_horizon_days,
                            "half_life": trade.half_life_days,
                            "entry_level": trade.current_level,
                            "ou_mean": trade.ou_mean,
                            "carry_roll_bps": trade.carry_roll_bps,
                        },
                    ))
                except Exception as exc:
                    logger.debug("Failed to build query for %s: %s", trade.candidate.tenors, exc)

        return orders

    def _is_pca_rv_position(self, pos) -> bool:
        """Check if a position was opened by this strategy."""
        tags = (pos.meta or {}).get("tags", [])
        return any(t.startswith("pca_rv_") for t in tags)

    def _get_position_tag(self, pos) -> str:
        """Get the pca_rv tag from a position."""
        tags = (pos.meta or {}).get("tags", [])
        pca_tags = [t for t in tags if t.startswith("pca_rv_")]
        return pca_tags[0] if pca_tags else ""

    def _compute_live_fly_level(self, pos, now, backtest) -> Optional[float]:
        """Compute current fly level from live curve via pricer.

        Falls back to signal table if live pricing fails.
        """
        meta = pos.meta or {}
        tenors = meta.get("tenors")
        weights = meta.get("weights")
        fwd = meta.get("forward_start")

        if tenors is None or weights is None:
            return None

        try:
            rates = []
            for tenor in tenors:
                q = _build_rate_query_for_tenor(tenor, fwd, self.config)
                pricer = backtest._pricer_for_query(q, now)
                from Query.Base.query_resolution import resolve_query
                resolved = resolve_query(q, pricer_or_curve=pricer)
                val = resolved.value()
                if val is None or (hasattr(val, '__len__') and len(val) == 0):
                    return None
                rates.append(float(val) if not hasattr(val, '__len__') else float(val[0]))

            # Compute PCA-weighted fly level
            fly_level = weights[0] * rates[0] + weights[1] * rates[1] + weights[2] * rates[2]
            return fly_level

        except Exception as exc:
            logger.debug("Live fly level computation failed: %s", exc)
            # Fallback: try signal table
            trades_today = _match_signal_table(self.signal_table, now)
            tag = self._get_position_tag(pos)
            for t in trades_today:
                if _fly_tag(t) == tag:
                    return t.current_level
            return None

    def _check_exit(self, pos, now, backtest) -> Optional[str]:
        """Check exit conditions for an open position.

        Returns exit reason string or None.
        """
        meta = pos.meta or {}
        target = meta.get("target")
        stop = meta.get("stop_loss")
        direction = meta.get("direction")
        horizon = meta.get("investment_horizon", 90)

        # Compute current fly level from live curve
        current = self._compute_live_fly_level(pos, now, backtest)

        if current is not None and target is not None and stop is not None:
            if direction == "receive_belly":
                # Expecting fly to decrease toward target
                if current <= target:
                    return "mean_reversion"
                if current >= stop:
                    return "stop_loss"
            else:  # pay_belly
                # Expecting fly to increase toward target
                if current >= target:
                    return "mean_reversion"
                if current <= stop:
                    return "stop_loss"

        # Max holding period
        if hasattr(pos, "opened"):
            ts = pd.Timestamp(now)
            days_held = (ts - pd.Timestamp(pos.opened)).days
            if days_held >= horizon:
                return "max_holding"

        return None


# ═══════════════════════════════════════════════════════════════════
# Trigger Wrappers
# ═══════════════════════════════════════════════════════════════════

class _IRSwapPCARVAlwaysReqs(TriggerRequirements):
    """Requirements that always trigger — action handles all logic."""

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        return TriggerInfo(True, {})


@dataclass
class IRSwapPCARVTrigger(Trigger):
    """Single trigger handling both entry and exit for PCA RV butterflies.

    Usage:
        signal_table = build_signal_table(panels, config, ...)
        trigger = IRSwapPCARVTrigger(signal_table, config)
        strategy = QueryStrategy("pca_rv", triggers=[trigger], default_mdp=mdp)
        bt = QueryDrivenBacktest(time_grid=grid, strategy=strategy, mdp=mdp)
        bt.run()
    """

    def __init__(
        self,
        signal_table: Dict[pd.Timestamp, List[IRSwapAnalyzedTrade]],
        config: IRSwapPCARVConfig,
    ):
        action = IRSwapPCARVSignalAction(signal_table, config)
        super().__init__(
            trigger_requirements=_IRSwapPCARVAlwaysReqs(),
            actions=[action],
        )


# ═══════════════════════════════════════════════════════════════════
# Convenience: run_irswap_pca_rv_backtest
# ═══════════════════════════════════════════════════════════════════

def run_irswap_pca_rv_backtest(
    signal_table: Dict[pd.Timestamp, List[IRSwapAnalyzedTrade]],
    config: IRSwapPCARVConfig,
    mdp,
    bt_dates: list,
) -> Any:
    """Convenience function to wire and run the full backtest.

    Parameters
    ----------
    signal_table : output of build_signal_table()
    config : IRSwapPCARVConfig
    mdp : MarketDataProvider (e.g., IRSwapsMDP)
    bt_dates : list of datetime objects for the time grid

    Returns
    -------
    QueryDrivenBacktest instance (already run)
    """
    from BT.query_engine import QueryDrivenBacktest
    from BT.query_strategy import QueryStrategy
    from BT.data_handler import TimeGrid

    trigger = IRSwapPCARVTrigger(signal_table, config)
    strategy = QueryStrategy(
        "irswap_pca_rv",
        triggers=[trigger],
        default_mdp=mdp,
    )

    bt = QueryDrivenBacktest(
        time_grid=TimeGrid(bt_dates),
        strategy=strategy,
        mdp=mdp,
    )
    bt.run()
    return bt
