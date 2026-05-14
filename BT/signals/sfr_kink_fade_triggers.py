"""Trigger adapters for the SFR Kink-Fading Strategy.

Supports BF (3-leg), DF (4-leg as two opposing flies), and CF (4-leg as two opposing spreads).

For 4-leg structures (DF, CF) the backtest decomposes into paired IRSwapQuery
orders because the Query layer only supports up to 3-leg FLY structures:
  - DF (+1:-3:+3:-1) = buy near BF + sell far BF
  - CF (+1:-1:-1:+1) = buy near spread + sell far spread

This decomposition is exact for P&L tracking and matches how these structures
trade as listed CME spreads (which are themselves portfolios of legs).
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from BT.event import TriggerInfo
from BT.triggers import Trigger, TriggerRequirements
from BT.query_order import QueryOrder, UnwindOrder
from BT.signals.sfr_kink_fade import KinkFadeConfig, KinkSignal, KinkStructure

logger = logging.getLogger(__name__)


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


def _kink_tag(signal: KinkSignal) -> str:
    """Deterministic tag for a kink position."""
    clean_id = signal.structure_id.replace("/", "_").replace("|", "__")
    return f"kink_{signal.structure_type.value}_{clean_id}"


def _sfr_to_imm_tenor(label: str) -> str:
    """Convert SFR rank label to IMM tenor. Pass through specific codes."""
    m = re.match(r"^SFR(\d+)$", label)
    if m:
        rank = int(m.group(1))
        return f"IMM_{rank}xIMM_{rank + 1}"
    return label


def _parse_structure_legs(structure_id: str, structure_type: KinkStructure) -> List[str]:
    """Parse structure_id into individual contract/tenor labels.

    BF: "SFR1/SFR2/SFR3" -> ["SFR1", "SFR2", "SFR3"]
    DF: "SFR1/SFR2/SFR3|SFR2/SFR3/SFR4" -> ["SFR1", "SFR2", "SFR3", "SFR4"]
    CF: "SFR1/SFR2/SFR3/SFR4" -> ["SFR1", "SFR2", "SFR3", "SFR4"]
    """
    if "|" in structure_id:
        # DF notation: near_fly|far_fly
        parts = structure_id.split("|")
        near_legs = parts[0].split("/")
        far_legs = parts[1].split("/")
        # Deduplicate while preserving order
        all_legs = list(dict.fromkeys(near_legs + far_legs))
        return all_legs
    return structure_id.split("/")


def _make_bf_query(
    front: str, belly: str, back: str,
    direction_sign: float,
    config: KinkFadeConfig,
    tags: List[str],
):
    """Build IRSwapQuery for a 3-leg butterfly."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure

    return IRSwapQuery(
        structure=IRSwapStructure.FLY,
        curve=config.curve,
        structure_kwargs={
            "front_tenor": _sfr_to_imm_tenor(front),
            "belly_tenor": _sfr_to_imm_tenor(belly),
            "back_tenor": _sfr_to_imm_tenor(back),
            "bpv": direction_sign * config.belly_bpv,
        },
        tags=tags,
    )


def _make_spread_query(
    front: str, back: str,
    direction_sign: float,
    config: KinkFadeConfig,
    tags: List[str],
):
    """Build IRSwapQuery for a 2-leg spread."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure

    return IRSwapQuery(
        structure=IRSwapStructure.CURVE,
        curve=config.curve,
        structure_kwargs={
            "front_tenor": _sfr_to_imm_tenor(front),
            "back_tenor": _sfr_to_imm_tenor(back),
            "bpv": direction_sign * config.belly_bpv,
        },
        tags=tags,
    )


def _build_orders_for_signal(
    signal: KinkSignal,
    config: KinkFadeConfig,
    timestamp: dt.datetime,
) -> List[QueryOrder]:
    """Build QueryOrder(s) for a kink signal.

    BF: single 3-leg fly query.
    DF: two opposing fly queries (near BF + far BF).
    CF: two opposing spread queries.
    """
    tag = _kink_tag(signal)
    legs = _parse_structure_legs(signal.structure_id, signal.structure_type)
    # sell_kink = fade rich = short the structure; buy_kink = fade cheap = long
    direction_sign = -1.0 if signal.direction == "sell_kink" else 1.0

    meta = {
        "action": "kink_fade_entry",
        "tags": [tag],
        "structure_type": signal.structure_type.value,
        "direction": signal.direction,
        "entry_zscore": signal.zscore,
        "entry_level": signal.level,
        "entry_vol": signal.vol,
        "entry_roll": signal.roll,
        "entry_percentile": signal.percentile,
        "entry_xsection_rank": signal.xsection_rank,
        "entry_composite": signal.composite_score,
        "entry_half_life": signal.half_life if not np.isnan(signal.half_life) else None,
    }

    orders = []

    if signal.structure_type in (KinkStructure.BF_3M, KinkStructure.BF_6M):
        if len(legs) != 3:
            logger.warning("BF needs 3 legs, got %d: %s", len(legs), signal.structure_id)
            return []
        q = _make_bf_query(legs[0], legs[1], legs[2], direction_sign, config, [tag])
        orders.append(QueryOrder(timestamp=timestamp, query=q, meta=meta))

    elif signal.structure_type in (KinkStructure.DF_3M, KinkStructure.DF_6M):
        # DF = near_BF - far_BF
        # structure_id format: "front/belly1/back1|belly1/belly2/back2"
        if "|" in signal.structure_id:
            near_parts = signal.structure_id.split("|")[0].split("/")
            far_parts = signal.structure_id.split("|")[1].split("/")
        elif len(legs) == 4:
            gap = 1 if signal.structure_type == KinkStructure.DF_3M else 2
            near_parts = [legs[0], legs[1], legs[2]]
            far_parts = [legs[1], legs[2], legs[3]]
        else:
            logger.warning("DF needs 4 legs, got %d: %s", len(legs), signal.structure_id)
            return []

        # DF buy = buy near BF + sell far BF
        tag_near = f"{tag}_near"
        tag_far = f"{tag}_far"

        q_near = _make_bf_query(
            near_parts[0], near_parts[1], near_parts[2],
            direction_sign, config, [tag, tag_near],
        )
        q_far = _make_bf_query(
            far_parts[0], far_parts[1], far_parts[2],
            -direction_sign, config, [tag, tag_far],
        )

        meta_near = {**meta, "df_leg": "near"}
        meta_far = {**meta, "df_leg": "far"}

        orders.append(QueryOrder(timestamp=timestamp, query=q_near, meta=meta_near))
        orders.append(QueryOrder(timestamp=timestamp, query=q_far, meta=meta_far))

    elif signal.structure_type in (KinkStructure.CF_3M, KinkStructure.CF_6M):
        # CF (+1:-1:-1:+1) = buy near spread + sell far spread
        if len(legs) != 4:
            logger.warning("CF needs 4 legs, got %d: %s", len(legs), signal.structure_id)
            return []

        tag_near = f"{tag}_near"
        tag_far = f"{tag}_far"

        # Near spread: legs[0]/legs[1], Far spread: legs[2]/legs[3]
        q_near = _make_spread_query(
            legs[0], legs[1],
            direction_sign, config, [tag, tag_near],
        )
        q_far = _make_spread_query(
            legs[2], legs[3],
            -direction_sign, config, [tag, tag_far],
        )

        meta_near = {**meta, "cf_leg": "near"}
        meta_far = {**meta, "cf_leg": "far"}

        orders.append(QueryOrder(timestamp=timestamp, query=q_near, meta=meta_near))
        orders.append(QueryOrder(timestamp=timestamp, query=q_far, meta=meta_far))

    return orders


# ═══════════════════════════════════════════════════════════════════
# Actions
# ═══════════════════════════════════════════════════════════════════

class _KinkFadeEntryAction:
    risk: Optional[str] = None
    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return info.get(_KinkFadeEntryAction, [])


class _KinkFadeExitAction:
    risk: Optional[str] = None
    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        return info.get(_KinkFadeExitAction, [])


# ═══════════════════════════════════════════════════════════════════
# Entry Trigger
# ═══════════════════════════════════════════════════════════════════

@dataclass
class _KinkFadeEntryReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[KinkSignal]] = field(default_factory=dict)
    config: KinkFadeConfig = field(default_factory=KinkFadeConfig)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        signals = _match_signal_table(self.signal_table, state)
        passing = [s for s in signals if s.passes_entry]

        if not passing:
            return TriggerInfo(False)

        # Deduplicate: no duplicate structures in portfolio
        if backtest is not None:
            open_tags = set()
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))

            if self.config.no_duplicate_structures:
                passing = [s for s in passing if _kink_tag(s) not in open_tags]

            if self.config.max_concurrent_trades is not None:
                n_open = len(backtest.portfolio.positions)
                # For DF/CF, each signal generates 2 positions
                effective_open = n_open
                if effective_open >= self.config.max_concurrent_trades:
                    return TriggerInfo(False)
                remaining = self.config.max_concurrent_trades - effective_open
                passing = passing[:remaining]

        if not passing:
            return TriggerInfo(False)

        all_orders = []
        for s in passing:
            try:
                orders = _build_orders_for_signal(s, self.config, state)
                all_orders.extend(orders)
            except Exception as exc:
                logger.debug("Failed to build query for %s: %s", s.structure_id, exc)

        if not all_orders:
            return TriggerInfo(False)

        return TriggerInfo(True, {_KinkFadeEntryAction: all_orders})


@dataclass
class KinkFadeEntryTrigger(Trigger):
    """Fires when kink-fading screener identifies passing trades."""

    def __init__(self, signal_table, config, actions=None):
        reqs = _KinkFadeEntryReqs(signal_table=signal_table, config=config)
        super().__init__(
            trigger_requirements=reqs,
            actions=actions or [_KinkFadeEntryAction()],
        )


# ═══════════════════════════════════════════════════════════════════
# Exit Trigger
# ═══════════════════════════════════════════════════════════════════

@dataclass
class _KinkFadeExitReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[KinkSignal]] = field(default_factory=dict)
    config: KinkFadeConfig = field(default_factory=KinkFadeConfig)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        if backtest is None or not backtest.portfolio.positions:
            return TriggerInfo(False)

        ts = pd.Timestamp(state)
        signals_today = _match_signal_table(self.signal_table, state)
        signal_by_tag = {_kink_tag(s): s for s in signals_today}

        unwinds = []
        # Group positions by parent tag (DF/CF have near+far legs sharing a parent)
        seen_parents = set()

        for pos in backtest.portfolio.positions:
            tags = set((pos.meta or {}).get("tags", []))
            kink_tags = [t for t in tags if t.startswith("kink_")]
            if not kink_tags:
                continue

            # Find parent tag (shortest kink_ tag, which is the parent)
            parent_tag = min(kink_tags, key=len)
            if parent_tag in seen_parents:
                continue

            entry_meta = pos.meta or {}
            exit_reason = None

            # Look up current signal for this structure
            sig = signal_by_tag.get(parent_tag)
            if sig is not None:
                entry_z = entry_meta.get("entry_zscore", 0)
                direction = entry_meta.get("direction", sig.direction)
                current_z = sig.zscore

                # 1. Mean reversion: z-score crossed zero
                if self.config.exit_mean_reversion:
                    if direction == "sell_kink" and current_z <= 0:
                        exit_reason = "mean_reversion"
                    elif direction == "buy_kink" and current_z >= 0:
                        exit_reason = "mean_reversion"

                # 2. Take profit: z-score below threshold
                if not exit_reason and self.config.exit_take_profit_zscore is not None:
                    if abs(current_z) < self.config.exit_take_profit_zscore:
                        exit_reason = "tp_zscore"

                # 3. Stop-loss: z-score worsened
                if not exit_reason and self.config.exit_stop_loss_sd is not None:
                    if abs(current_z) - abs(entry_z) > self.config.exit_stop_loss_sd:
                        exit_reason = "stop_zscore"

                # 4. Fixed bp take-profit
                if not exit_reason and self.config.exit_take_profit_bp is not None:
                    entry_lvl = entry_meta.get("entry_level", 0)
                    dir_sign = -1 if direction == "sell_kink" else 1
                    unrealized = dir_sign * (sig.level - entry_lvl)
                    if unrealized >= self.config.exit_take_profit_bp:
                        exit_reason = "tp_bp"

                # 5. Fixed bp stop-loss
                if not exit_reason and self.config.exit_stop_loss_bp is not None:
                    entry_lvl = entry_meta.get("entry_level", 0)
                    dir_sign = -1 if direction == "sell_kink" else 1
                    unrealized = dir_sign * (sig.level - entry_lvl)
                    if unrealized <= self.config.exit_stop_loss_bp:
                        exit_reason = "stop_bp"

            # 6. Max holding period
            if exit_reason is None and hasattr(pos, "opened"):
                if self.config.exit_max_holding_days is not None:
                    days_held = (ts - pd.Timestamp(pos.opened)).days
                    if days_held >= self.config.exit_max_holding_days:
                        exit_reason = "max_holding"

            # 7. Half-life based exit: hold for 2× half-life
            if exit_reason is None and self.config.exit_halflife_based and hasattr(pos, "opened"):
                entry_hl = entry_meta.get("entry_half_life")
                if entry_hl is not None and entry_hl > 0:
                    target_hold = entry_hl * 2
                    days_held = (ts - pd.Timestamp(pos.opened)).days
                    if days_held >= target_hold:
                        exit_reason = "halflife_expiry"

            if exit_reason is not None:
                seen_parents.add(parent_tag)
                _ptag = parent_tag
                unwinds.append(UnwindOrder(
                    timestamp=state,
                    selector=lambda p, _t=_ptag: _t in set((p.meta or {}).get("tags", [])),
                    meta={"action": "kink_fade_exit", "reason": exit_reason},
                ))

        if not unwinds:
            return TriggerInfo(False)

        return TriggerInfo(True, {_KinkFadeExitAction: unwinds})


@dataclass
class KinkFadeExitTrigger(Trigger):
    """Fires when open kink-fading positions hit exit conditions."""

    def __init__(self, signal_table, config, actions=None):
        reqs = _KinkFadeExitReqs(signal_table=signal_table, config=config)
        super().__init__(
            trigger_requirements=reqs,
            actions=actions or [_KinkFadeExitAction()],
        )
