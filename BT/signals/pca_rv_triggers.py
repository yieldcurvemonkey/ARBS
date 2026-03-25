"""Trigger adapter wiring PCA RV scanner into QueryDrivenBacktest.

Pre-computes a signal_table (dict[date, list[AnalyzedTrade]]) before
the backtest runs, then triggers do simple date-based lookups.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from BT.event import TriggerInfo
from BT.triggers import Trigger, TriggerRequirements
from BT.query_order import QueryOrder, UnwindOrder
from BT.signals.pca_rv_scanner import AnalyzedTrade, PCARVScannerConfig

logger = logging.getLogger(__name__)


def _match_signal_table(signal_table, state_dt):
    """Find trades in signal_table matching the given state datetime.

    Handles tz-naive vs tz-aware mismatches by comparing date components.
    """
    ts = pd.Timestamp(state_dt)

    # Direct lookup first
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


def _fly_tag(trade: AnalyzedTrade) -> str:
    """Deterministic tag for a fly position."""
    fwd = trade.candidate.forward_start or "spot"
    left, belly, right = trade.candidate.tenors
    return f"pca_rv_{fwd}_{left}_{belly}_{right}"


def _make_fly_query(trade: AnalyzedTrade, config: PCARVScannerConfig, bpv: float = 100_000):
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

    # Direction: receive_belly → positive bpv on belly (receive fixed),
    #            pay_belly → negative bpv on belly
    direction_sign = 1.0 if trade.candidate.direction == "receive_belly" else -1.0

    return IRSwapQuery(
        structure=IRSwapStructure.FLY,
        curve=config.curve,
        structure_kwargs={
            "front_tenor": front,
            "belly_tenor": belly,
            "back_tenor": back,
            "weights": (w_left, 1.0, w_right),
            "bpv": direction_sign * bpv,
        },
        tags=[_fly_tag(trade)],
    )


# ── Pass-through actions ─────────────────────────────────────────
# The QueryDrivenBacktest dispatches orders through trig.actions.
# These simple callables extract pre-built orders from info dict.

class _PCARVEntryAction:
    """Extract entry orders from TriggerInfo."""
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return info.get(_PCARVEntryAction, [])


class _PCARVExitAction:
    """Extract exit orders from TriggerInfo."""
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        return info.get(_PCARVExitAction, [])


# ── Entry Trigger ────────────────────────────────────────────────

@dataclass
class _PCARVEntryReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]] = field(default_factory=dict)
    config: PCARVScannerConfig = field(default_factory=PCARVScannerConfig)
    bpv: float = 100_000
    max_concurrent: int = 5

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        trades = _match_signal_table(self.signal_table, state)
        passing = [t for t in trades if t.passes_filter]

        if not passing:
            return TriggerInfo(False)

        # Filter out flies already in portfolio
        if backtest is not None:
            open_tags = set()
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))
            passing = [t for t in passing if _fly_tag(t) not in open_tags]

            # Respect max concurrent
            n_open = len(backtest.portfolio.positions)
            if n_open >= self.max_concurrent:
                return TriggerInfo(False)
            passing = passing[: self.max_concurrent - n_open]

        if not passing:
            return TriggerInfo(False)

        # Build orders
        orders = []
        for t in passing:
            try:
                q = _make_fly_query(t, self.config, self.bpv)
                orders.append(QueryOrder(
                    timestamp=state,
                    query=q,
                    meta={
                        "action": "pca_rv_entry",
                        "tags": [_fly_tag(t)],
                        "direction": t.candidate.direction,
                        "lifetime_zscore": t.lifetime_zscore,
                        "target": t.target_level,
                        "stop_loss": t.stop_loss_level,
                        "investment_horizon": t.investment_horizon_days,
                    },
                ))
            except Exception as exc:
                logger.debug("Failed to build query for %s: %s", t.candidate.tenors, exc)

        if not orders:
            return TriggerInfo(False)

        return TriggerInfo(True, {_PCARVEntryAction: orders})


@dataclass
class PCARVEntryTrigger(Trigger):
    """Fires when PCA RV scanner identifies passing trades on a date."""

    def __init__(
        self,
        signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]],
        config: PCARVScannerConfig,
        bpv: float = 100_000,
        max_concurrent: int = 5,
        actions=None,
    ):
        reqs = _PCARVEntryReqs(
            signal_table=signal_table,
            config=config,
            bpv=bpv,
            max_concurrent=max_concurrent,
        )
        super().__init__(
            trigger_requirements=reqs,
            actions=actions or [_PCARVEntryAction()],
        )


# ── Exit Trigger ─────────────────────────────────────────────────

@dataclass
class _PCARVExitReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]] = field(default_factory=dict)
    config: PCARVScannerConfig = field(default_factory=PCARVScannerConfig)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        if backtest is None or not backtest.portfolio.positions:
            return TriggerInfo(False)

        ts = pd.Timestamp(state)
        trades_today = _match_signal_table(self.signal_table, state)
        trade_by_tag = {_fly_tag(t): t for t in trades_today}

        unwinds = []
        for pos in backtest.portfolio.positions:
            tags = set((pos.meta or {}).get("tags", []))
            pca_tags = [t for t in tags if t.startswith("pca_rv_")]
            if not pca_tags:
                continue

            tag = pca_tags[0]
            entry_meta = pos.meta or {}

            # Check exit conditions
            exit_reason = None

            if tag in trade_by_tag:
                trade = trade_by_tag[tag]
                target = entry_meta.get("target", trade.target_level)
                stop = entry_meta.get("stop_loss", trade.stop_loss_level)
                direction = entry_meta.get("direction", trade.candidate.direction)

                current = trade.current_level

                # Mean reversion: crossed target
                if direction == "receive_belly":
                    if current <= target:
                        exit_reason = "mean_reversion"
                    elif current >= stop:
                        exit_reason = "stop_loss"
                else:
                    if current >= target:
                        exit_reason = "mean_reversion"
                    elif current <= stop:
                        exit_reason = "stop_loss"

            # Max holding period
            if exit_reason is None and hasattr(pos, "opened"):
                days_held = (ts - pd.Timestamp(pos.opened)).days
                horizon = entry_meta.get("investment_horizon", 90)
                if days_held >= horizon:
                    exit_reason = "max_holding"

            if exit_reason is not None:
                _tag = tag  # capture for closure
                unwinds.append(UnwindOrder(
                    timestamp=state,
                    selector=lambda p, _t=_tag: _t in set((p.meta or {}).get("tags", [])),
                    meta={"action": "pca_rv_exit", "reason": exit_reason},
                ))

        if not unwinds:
            return TriggerInfo(False)

        return TriggerInfo(True, {_PCARVExitAction: unwinds})


@dataclass
class PCARVExitTrigger(Trigger):
    """Fires when open PCA RV positions hit target, stop-loss, or max holding."""

    def __init__(
        self,
        signal_table: Dict[pd.Timestamp, List[AnalyzedTrade]],
        config: PCARVScannerConfig,
        actions=None,
    ):
        reqs = _PCARVExitReqs(signal_table=signal_table, config=config)
        super().__init__(
            trigger_requirements=reqs,
            actions=actions or [_PCARVExitAction()],
        )
