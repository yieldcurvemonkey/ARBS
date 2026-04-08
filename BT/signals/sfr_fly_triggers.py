"""Trigger adapter wiring SFRCalSpreadRV fly screener into QueryDrivenBacktest.

Pre-computes a signal table (dict[date, list[FlySignal]]) from the screener
analytics, then triggers do simple date-based lookups for entry/exit.

Pattern follows pca_rv_triggers.py exactly.
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from BT.event import TriggerInfo
from BT.triggers import Trigger, TriggerRequirements
from BT.query_order import QueryOrder, UnwindOrder

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Signal Table
# ═══════════════════════════════════════════════════════════════════

@dataclass
class FlySignal:
    """A single fly signal at a point in time."""
    fly_id: str            # e.g., "SFR1/SFR2/SFR3" or "M26/U26/Z26"
    level: float           # fly level in bps
    zscore: float
    vol: float             # annualized realized vol
    roll: float            # carry/roll in bps
    risk_adj_roll: float
    direction: str         # "buy_belly" or "sell_belly"
    passes_entry: bool     # passes all entry filters


def build_signal_table(
    fly_ts: pd.DataFrame,
    zscore_ts: pd.DataFrame,
    vol_ts: pd.DataFrame,
    roll_ts: pd.DataFrame,
    risk_adj_roll_ts: pd.DataFrame,
    config: dict,
) -> Dict[pd.Timestamp, List[FlySignal]]:
    """Build a date-keyed signal table from pre-computed analytics.

    Parameters
    ----------
    fly_ts : DataFrame of fly levels (dates x fly_ids), in bps.
    zscore_ts : DataFrame of z-scores.
    vol_ts : DataFrame of annualized vol.
    roll_ts : DataFrame of roll/carry.
    risk_adj_roll_ts : DataFrame of risk-adjusted roll.
    config : BACKTEST_CONFIG dict with entry thresholds.

    Returns
    -------
    Dict mapping pd.Timestamp -> list of FlySignal for that date.
    """
    signal_table: Dict[pd.Timestamp, List[FlySignal]] = {}

    for dt_idx in fly_ts.index:
        signals = []
        for col in fly_ts.columns:
            level = fly_ts.loc[dt_idx, col]
            z = zscore_ts.loc[dt_idx, col] if dt_idx in zscore_ts.index else np.nan
            vol = vol_ts.loc[dt_idx, col] if dt_idx in vol_ts.index else np.nan
            roll = roll_ts.loc[dt_idx, col] if dt_idx in roll_ts.index else np.nan
            radj = risk_adj_roll_ts.loc[dt_idx, col] if dt_idx in risk_adj_roll_ts.index else np.nan

            if np.isnan(z) or np.isnan(level):
                continue

            # Direction: z < 0 → fly cheap → buy belly; z > 0 → fly rich → sell belly
            direction = "buy_belly" if z < 0 else "sell_belly"

            # Entry filters
            passes = True

            if abs(z) < config.get("entry_min_zscore", 1.5):
                passes = False

            if config.get("entry_max_vol") and not np.isnan(vol):
                if vol > config["entry_max_vol"]:
                    passes = False

            if config.get("entry_require_carry") and not np.isnan(roll):
                carry_aligned = (direction == "buy_belly" and roll > 0) or \
                                (direction == "sell_belly" and roll < 0)
                if not carry_aligned:
                    passes = False
                if config.get("entry_min_risk_adj_roll", 0) > 0 and not np.isnan(radj):
                    if abs(radj) < config["entry_min_risk_adj_roll"]:
                        passes = False

            signals.append(FlySignal(
                fly_id=col,
                level=float(level),
                zscore=float(z),
                vol=float(vol) if not np.isnan(vol) else 0.0,
                roll=float(roll) if not np.isnan(roll) else 0.0,
                risk_adj_roll=float(radj) if not np.isnan(radj) else 0.0,
                direction=direction,
                passes_entry=passes,
            ))

        if signals:
            signal_table[pd.Timestamp(dt_idx)] = signals

    return signal_table


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _match_signal_table(signal_table, state_dt):
    """Find signals matching a given datetime (handles tz mismatches)."""
    ts = pd.Timestamp(state_dt)
    signals = signal_table.get(ts, [])
    if signals:
        return signals
    ts_naive = ts.tz_localize(None) if ts.tzinfo is not None else ts
    signals = signal_table.get(ts_naive, [])
    if signals:
        return signals
    target_date = ts.date()
    for key, val in signal_table.items():
        if pd.Timestamp(key).date() == target_date:
            return val
    return []


def _fly_tag(signal: FlySignal) -> str:
    """Deterministic tag for a fly position."""
    return f"sfr_fly_{signal.fly_id.replace('/', '_')}"


def _sfr_to_imm_tenor(label: str) -> str:
    """Convert SFR rank label to IMM tenor.

    'SFR1' -> 'IMM_1xIMM_2'
    'M26'  -> 'M26' (pass through specific contract labels)
    """
    import re
    m = re.match(r"^SFR(\d+)$", label)
    if m:
        rank = int(m.group(1))
        return f"IMM_{rank}xIMM_{rank + 1}"
    return label


def _make_fly_query(signal: FlySignal, config: dict):
    """Build an IRSwapQuery for the SOFR fly.

    Handles both CM labels (SFR1/SFR2/SFR3 -> IMM tenors)
    and specific contract labels (M26/U26/Z26 -> pass-through).
    """
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure

    parts = signal.fly_id.split("/")
    if len(parts) != 3:
        raise ValueError(f"Expected 3-leg fly id, got: {signal.fly_id}")

    front_tenor = _sfr_to_imm_tenor(parts[0])
    belly_tenor = _sfr_to_imm_tenor(parts[1])
    back_tenor = _sfr_to_imm_tenor(parts[2])

    bpv = config.get("belly_bpv", 100_000)
    direction_sign = 1.0 if signal.direction == "buy_belly" else -1.0

    curve = config.get("curve", "USD-SOFR-1D-Q12STIRT")

    return IRSwapQuery(
        structure=IRSwapStructure.FLY,
        curve=curve,
        structure_kwargs={
            "front_tenor": front_tenor,
            "belly_tenor": belly_tenor,
            "back_tenor": back_tenor,
            "bpv": direction_sign * bpv,
        },
        tags=[_fly_tag(signal)],
    )


# ═══════════════════════════════════════════════════════════════════
# Actions (pass-through pattern from pca_rv_triggers.py)
# ═══════════════════════════════════════════════════════════════════

class _SFRFlyEntryAction:
    """Extract entry orders from TriggerInfo."""
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return info.get(_SFRFlyEntryAction, [])


class _SFRFlyExitAction:
    """Extract exit/unwind orders from TriggerInfo."""
    risk: Optional[str] = None

    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        return info.get(_SFRFlyExitAction, [])


# ═══════════════════════════════════════════════════════════════════
# Entry Trigger
# ═══════════════════════════════════════════════════════════════════

@dataclass
class _SFRFlyEntryReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[FlySignal]] = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        signals = _match_signal_table(self.signal_table, state)
        passing = [s for s in signals if s.passes_entry]

        if not passing:
            return TriggerInfo(False)

        # Filter out flies already in portfolio
        max_concurrent = self.config.get("max_concurrent_trades")
        if backtest is not None:
            open_tags = set()
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))

            if self.config.get("no_duplicate_flies", True):
                passing = [s for s in passing if _fly_tag(s) not in open_tags]

            if max_concurrent is not None:
                n_open = len(backtest.portfolio.positions)
                if n_open >= max_concurrent:
                    return TriggerInfo(False)
                passing = passing[:max_concurrent - n_open]

        if not passing:
            return TriggerInfo(False)

        # Build orders
        orders = []
        for s in passing:
            try:
                q = _make_fly_query(s, self.config)
                orders.append(QueryOrder(
                    timestamp=state,
                    query=q,
                    meta={
                        "action": "sfr_fly_entry",
                        "tags": [_fly_tag(s)],
                        "direction": s.direction,
                        "entry_zscore": s.zscore,
                        "entry_level": s.level,
                        "entry_vol": s.vol,
                        "entry_roll": s.roll,
                    },
                ))
            except Exception as exc:
                logger.debug("Failed to build query for %s: %s", s.fly_id, exc)

        if not orders:
            return TriggerInfo(False)

        return TriggerInfo(True, {_SFRFlyEntryAction: orders})


@dataclass
class SFRFlyEntryTrigger(Trigger):
    """Fires when SFR fly screener identifies passing trades."""

    def __init__(self, signal_table, config, actions=None):
        reqs = _SFRFlyEntryReqs(signal_table=signal_table, config=config)
        super().__init__(
            trigger_requirements=reqs,
            actions=actions or [_SFRFlyEntryAction()],
        )


# ═══════════════════════════════════════════════════════════════════
# Exit Trigger
# ═══════════════════════════════════════════════════════════════════

@dataclass
class _SFRFlyExitReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[FlySignal]] = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        if backtest is None or not backtest.portfolio.positions:
            return TriggerInfo(False)

        ts = pd.Timestamp(state)
        signals_today = _match_signal_table(self.signal_table, state)
        signal_by_tag = {_fly_tag(s): s for s in signals_today}

        unwinds = []
        for pos in backtest.portfolio.positions:
            tags = set((pos.meta or {}).get("tags", []))
            sfr_tags = [t for t in tags if t.startswith("sfr_fly_")]
            if not sfr_tags:
                continue

            tag = sfr_tags[0]
            entry_meta = pos.meta or {}
            exit_reason = None

            if tag in signal_by_tag:
                sig = signal_by_tag[tag]
                entry_z = entry_meta.get("entry_zscore", 0)
                direction = entry_meta.get("direction", sig.direction)
                current_z = sig.zscore

                # Mean reversion: z-score crossed zero
                if self.config.get("exit_mean_reversion", True):
                    if direction == "buy_belly" and current_z >= 0:
                        exit_reason = "mean_reversion"
                    elif direction == "sell_belly" and current_z <= 0:
                        exit_reason = "mean_reversion"

                # Take profit: z-score decayed below threshold
                tp_z = self.config.get("exit_take_profit_zscore")
                if not exit_reason and tp_z is not None:
                    if abs(current_z) < tp_z:
                        exit_reason = "tp_zscore"

                # Stop-loss: z-score worsened by N sigma
                stop_sd = self.config.get("exit_stop_loss_sd")
                if not exit_reason and stop_sd is not None:
                    if abs(current_z) - abs(entry_z) > stop_sd:
                        exit_reason = "stop_zscore"

            # Take profit: earned enough bps (check unrealized via MTM)
            # (approximated via level change since entry)
            if not exit_reason and tag in signal_by_tag:
                sig = signal_by_tag[tag]
                entry_lvl = entry_meta.get("entry_level", 0)
                direction = entry_meta.get("direction", "buy_belly")
                dir_sign = 1 if direction == "buy_belly" else -1
                unrealized = dir_sign * (sig.level - entry_lvl)

                tp_bp = self.config.get("exit_take_profit_bp")
                if tp_bp is not None and unrealized >= tp_bp:
                    exit_reason = "tp_bp"

                sl_bp = self.config.get("exit_stop_loss_bp")
                if not exit_reason and sl_bp is not None and unrealized <= sl_bp:
                    exit_reason = "stop_bp"

            # Max holding period
            if exit_reason is None and hasattr(pos, "opened"):
                max_hold = self.config.get("exit_max_holding_days", 22)
                if max_hold is not None:
                    days_held = (ts - pd.Timestamp(pos.opened)).days
                    if days_held >= max_hold:
                        exit_reason = "max_holding"

            if exit_reason is not None:
                _tag = tag
                unwinds.append(UnwindOrder(
                    timestamp=state,
                    selector=lambda p, _t=_tag: _t in set((p.meta or {}).get("tags", [])),
                    meta={"action": "sfr_fly_exit", "reason": exit_reason},
                ))

        if not unwinds:
            return TriggerInfo(False)

        return TriggerInfo(True, {_SFRFlyExitAction: unwinds})


@dataclass
class SFRFlyExitTrigger(Trigger):
    """Fires when open SFR fly positions hit exit conditions."""

    def __init__(self, signal_table, config, actions=None):
        reqs = _SFRFlyExitReqs(signal_table=signal_table, config=config)
        super().__init__(
            trigger_requirements=reqs,
            actions=actions or [_SFRFlyExitAction()],
        )
