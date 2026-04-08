"""Trigger adapters wiring SFRCalSpreadRV screener into QueryDrivenBacktest.

Supports both:
  - FLY triggers: 3-leg butterflies (SFRFlyEntryTrigger / SFRFlyExitTrigger)
  - SPREAD triggers: 2-leg calendar spreads (SFRSpreadEntryTrigger / SFRSpreadExitTrigger)

Pre-computes a signal table (dict[date, list[Signal]]) from the screener
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


# ═══════════════════════════════════════════════════════════════════════
# REGIME FILTERS
# ═══════════════════════════════════════════════════════════════════════

def compute_hurst_exponent(series: pd.Series, max_lag: int = 20) -> pd.Series:
    """Rolling Hurst exponent via rescaled range (R/S) method.

    H < 0.5 → mean-reverting, H = 0.5 → random walk, H > 0.5 → trending.
    Returns Series aligned to input index (NaN during warmup).
    """
    n = len(series)
    hurst = pd.Series(np.nan, index=series.index)
    window = max(max_lag * 3, 60)  # need enough data for R/S regression

    for i in range(window, n):
        ts = series.iloc[i - window:i].dropna().values
        if len(ts) < window // 2:
            continue
        lags = range(2, max_lag + 1)
        rs_values = []
        for lag in lags:
            # Split into sub-series of length lag
            n_sub = len(ts) // lag
            if n_sub < 1:
                continue
            rs_list = []
            for j in range(n_sub):
                sub = ts[j * lag:(j + 1) * lag]
                mean_sub = sub.mean()
                devs = np.cumsum(sub - mean_sub)
                r = devs.max() - devs.min()
                s = sub.std(ddof=1)
                if s > 0:
                    rs_list.append(r / s)
            if rs_list:
                rs_values.append((np.log(lag), np.log(np.mean(rs_list))))

        if len(rs_values) >= 4:
            x = np.array([v[0] for v in rs_values])
            y = np.array([v[1] for v in rs_values])
            # OLS: y = H * x + c
            n_pts = len(x)
            H = (n_pts * (x * y).sum() - x.sum() * y.sum()) / \
                (n_pts * (x * x).sum() - x.sum() ** 2)
            hurst.iloc[i] = float(np.clip(H, 0, 1))

    return hurst


def compute_adx(series: pd.Series, window: int = 14) -> pd.Series:
    """Simplified ADX (Average Directional Index) for a single series.

    Uses absolute changes as proxy for directional movement since we
    don't have OHLC — just daily closes.

    Higher ADX → stronger trend. >25 = trending, <20 = range-bound.
    """
    changes = series.diff()
    pos_dm = changes.clip(lower=0)
    neg_dm = (-changes).clip(lower=0)

    atr = series.diff().abs().rolling(window, min_periods=window // 2).mean()
    atr = atr.replace(0, np.nan)

    pos_di = (pos_dm.rolling(window, min_periods=window // 2).mean() / atr) * 100
    neg_di = (neg_dm.rolling(window, min_periods=window // 2).mean() / atr) * 100

    dx = (abs(pos_di - neg_di) / (pos_di + neg_di).replace(0, np.nan)) * 100
    adx = dx.rolling(window, min_periods=window // 2).mean()

    return adx


# FOMC meeting dates 2020-2027 (announcement days)
_FOMC_DATES = [
    # 2020
    "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-10",
    "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-17",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
]
_FOMC_DATES_PARSED = [pd.Timestamp(d) for d in _FOMC_DATES]


def days_to_next_fomc(dt: pd.Timestamp) -> int:
    """Business days until the next FOMC announcement."""
    dt_date = pd.Timestamp(dt).normalize()
    for fomc in _FOMC_DATES_PARSED:
        if fomc >= dt_date:
            return max(0, len(pd.bdate_range(dt_date, fomc)) - 1)
    return 999  # no upcoming FOMC in the list


def compute_regime_filters(
    spread_ts: pd.DataFrame,
    rates: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """Compute regime filters for each date.

    Returns DataFrame with columns:
      - hurst_{col}: Hurst exponent per spread (H < 0.5 = mean-reverting)
      - adx: ADX of the mid-curve strip rate (>25 = trending)
      - days_to_fomc: business days until next FOMC
      - regime_ok: bool, True if all enabled filters pass

    Config keys:
      - regime_hurst_max: max Hurst to allow entry (e.g., 0.5). None=disabled.
      - regime_adx_max: max ADX to allow entry (e.g., 25). None=disabled.
      - regime_fomc_blackout_days: no entries within N bdays of FOMC. None=disabled.
      - regime_adx_column: which rate column for ADX (default: mid-curve).
      - regime_hurst_window: lag depth for Hurst (default: 20).
      - regime_adx_window: ADX window (default: 14).
    """
    hurst_max = config.get("regime_hurst_max")
    adx_max = config.get("regime_adx_max")
    fomc_blackout = config.get("regime_fomc_blackout_days")

    result = pd.DataFrame(index=spread_ts.index)

    # Hurst per spread
    if hurst_max is not None:
        hurst_lag = config.get("regime_hurst_window", 20)
        for col in spread_ts.columns:
            result[f"hurst_{col}"] = compute_hurst_exponent(spread_ts[col], max_lag=hurst_lag)

    # ADX on mid-curve strip rate
    if adx_max is not None:
        adx_window = config.get("regime_adx_window", 14)
        # Use mid-curve contract (SFR5 or 5th column) as proxy for regime
        rate_cols = list(rates.columns)
        mid_col = rate_cols[min(4, len(rate_cols) - 1)]
        adx_col = config.get("regime_adx_column", mid_col)
        if adx_col in rates.columns:
            result["adx"] = compute_adx(rates[adx_col], window=adx_window)
        else:
            result["adx"] = compute_adx(rates[mid_col], window=adx_window)

    # FOMC proximity
    if fomc_blackout is not None:
        result["days_to_fomc"] = [days_to_next_fomc(dt) for dt in spread_ts.index]

    # Composite: regime_ok
    result["regime_ok"] = True

    if hurst_max is not None:
        hurst_cols = [c for c in result.columns if c.startswith("hurst_")]
        if hurst_cols:
            # Per-spread hurst is checked at entry time in signal table builder;
            # here we set a global flag based on the average hurst
            avg_hurst = result[hurst_cols].mean(axis=1)
            result["avg_hurst"] = avg_hurst
            result["regime_ok"] = result["regime_ok"] & (avg_hurst <= hurst_max)

    if adx_max is not None and "adx" in result.columns:
        result["regime_ok"] = result["regime_ok"] & (result["adx"] <= adx_max)

    if fomc_blackout is not None and "days_to_fomc" in result.columns:
        result["regime_ok"] = result["regime_ok"] & (result["days_to_fomc"] > fomc_blackout)

    return result


def build_spread_signal_table_with_regime(
    spread_ts: pd.DataFrame,
    zscore_ts: pd.DataFrame,
    vol_ts: pd.DataFrame,
    roll_ts: pd.DataFrame,
    risk_adj_roll_ts: pd.DataFrame,
    rates: pd.DataFrame,
    config: dict,
) -> Dict[pd.Timestamp, List["SpreadSignal"]]:
    """Build spread signal table WITH regime filters.

    Same as build_spread_signal_table but additionally applies:
      - Hurst exponent filter (per-spread: H < regime_hurst_max)
      - ADX filter (global: ADX < regime_adx_max)
      - FOMC blackout (global: days_to_fomc > regime_fomc_blackout_days)

    Falls back to build_spread_signal_table if no regime filters are configured.
    """
    has_regime = any(config.get(k) is not None for k in [
        "regime_hurst_max", "regime_adx_max", "regime_fomc_blackout_days",
    ])

    if not has_regime:
        return build_spread_signal_table(
            spread_ts, zscore_ts, vol_ts, roll_ts, risk_adj_roll_ts, config
        )

    regime = compute_regime_filters(spread_ts, rates, config)
    hurst_max = config.get("regime_hurst_max")

    signal_table: Dict[pd.Timestamp, List[SpreadSignal]] = {}

    for dt_idx in spread_ts.index:
        # Global regime check
        if dt_idx in regime.index and not regime.loc[dt_idx, "regime_ok"]:
            continue

        signals = []
        for col in spread_ts.columns:
            level = spread_ts.loc[dt_idx, col]
            z = zscore_ts.loc[dt_idx, col] if dt_idx in zscore_ts.index else np.nan
            vol = vol_ts.loc[dt_idx, col] if dt_idx in vol_ts.index else np.nan
            roll = roll_ts.loc[dt_idx, col] if dt_idx in roll_ts.index else np.nan
            radj = risk_adj_roll_ts.loc[dt_idx, col] if dt_idx in risk_adj_roll_ts.index else np.nan

            if np.isnan(z) or np.isnan(level):
                continue

            direction = "pay_spread" if z < 0 else "receive_spread"

            passes = True
            if abs(z) < config.get("entry_min_zscore", 1.5):
                passes = False
            if config.get("entry_max_vol") and not np.isnan(vol):
                if vol > config["entry_max_vol"]:
                    passes = False
            if config.get("entry_require_carry") and not np.isnan(roll):
                carry_aligned = (direction == "pay_spread" and roll > 0) or \
                                (direction == "receive_spread" and roll < 0)
                if not carry_aligned:
                    passes = False

            # Per-spread Hurst filter
            if passes and hurst_max is not None:
                hurst_col = f"hurst_{col}"
                if hurst_col in regime.columns and dt_idx in regime.index:
                    h = regime.loc[dt_idx, hurst_col]
                    if not np.isnan(h) and h > hurst_max:
                        passes = False

            signals.append(SpreadSignal(
                spread_id=col, level=float(level), zscore=float(z),
                vol=float(vol) if not np.isnan(vol) else 0.0,
                roll=float(roll) if not np.isnan(roll) else 0.0,
                risk_adj_roll=float(radj) if not np.isnan(radj) else 0.0,
                direction=direction, passes_entry=passes,
            ))

        if signals:
            signal_table[pd.Timestamp(dt_idx)] = signals

    return signal_table


# ═══════════════════════════════════════════════════════════════════════
# CALENDAR SPREAD (2-leg) TRIGGERS
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class SpreadSignal:
    """A single calendar spread signal at a point in time."""
    spread_id: str         # e.g., "SFR1/SFR2" or "M26/U26"
    level: float           # spread level in bps (back - front)
    zscore: float
    vol: float
    roll: float
    risk_adj_roll: float
    direction: str         # "pay_spread" (steepener) or "receive_spread" (flattener)
    passes_entry: bool


def build_spread_signal_table(
    spread_ts: pd.DataFrame,
    zscore_ts: pd.DataFrame,
    vol_ts: pd.DataFrame,
    roll_ts: pd.DataFrame,
    risk_adj_roll_ts: pd.DataFrame,
    config: dict,
) -> Dict[pd.Timestamp, List[SpreadSignal]]:
    """Build a date-keyed signal table for calendar spreads.

    Convention: z < 0 → spread is cheap (too flat) → pay spread (steepener)
                z > 0 → spread is rich (too steep)  → receive spread (flattener)
    """
    signal_table: Dict[pd.Timestamp, List[SpreadSignal]] = {}

    for dt_idx in spread_ts.index:
        signals = []
        for col in spread_ts.columns:
            level = spread_ts.loc[dt_idx, col]
            z = zscore_ts.loc[dt_idx, col] if dt_idx in zscore_ts.index else np.nan
            vol = vol_ts.loc[dt_idx, col] if dt_idx in vol_ts.index else np.nan
            roll = roll_ts.loc[dt_idx, col] if dt_idx in roll_ts.index else np.nan
            radj = risk_adj_roll_ts.loc[dt_idx, col] if dt_idx in risk_adj_roll_ts.index else np.nan

            if np.isnan(z) or np.isnan(level):
                continue

            direction = "pay_spread" if z < 0 else "receive_spread"

            passes = True
            if abs(z) < config.get("entry_min_zscore", 1.5):
                passes = False
            if config.get("entry_max_vol") and not np.isnan(vol):
                if vol > config["entry_max_vol"]:
                    passes = False
            if config.get("entry_require_carry") and not np.isnan(roll):
                carry_aligned = (direction == "pay_spread" and roll > 0) or \
                                (direction == "receive_spread" and roll < 0)
                if not carry_aligned:
                    passes = False

            signals.append(SpreadSignal(
                spread_id=col, level=float(level), zscore=float(z),
                vol=float(vol) if not np.isnan(vol) else 0.0,
                roll=float(roll) if not np.isnan(roll) else 0.0,
                risk_adj_roll=float(radj) if not np.isnan(radj) else 0.0,
                direction=direction, passes_entry=passes,
            ))

        if signals:
            signal_table[pd.Timestamp(dt_idx)] = signals

    return signal_table


def _spread_tag(signal: SpreadSignal) -> str:
    return f"sfr_spd_{signal.spread_id.replace('/', '_')}"


def _make_spread_query(signal: SpreadSignal, config: dict):
    """Build an IRSwapQuery CURVE for a 2-leg calendar spread."""
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapStructure import IRSwapStructure

    parts = signal.spread_id.split("/")
    if len(parts) != 2:
        raise ValueError(f"Expected 2-leg spread id, got: {signal.spread_id}")

    front_tenor = _sfr_to_imm_tenor(parts[0])
    back_tenor = _sfr_to_imm_tenor(parts[1])

    bpv = config.get("belly_bpv", 100_000)
    # pay_spread = long the spread (steepener): receive back, pay front → positive bpv
    # receive_spread = short the spread (flattener): pay back, receive front → negative bpv
    direction_sign = 1.0 if signal.direction == "pay_spread" else -1.0

    curve = config.get("curve", "USD-SOFR-1D-Q12STIRT")

    return IRSwapQuery(
        structure=IRSwapStructure.CURVE,
        curve=curve,
        structure_kwargs={
            "front_tenor": front_tenor,
            "back_tenor": back_tenor,
            "bpv": direction_sign * bpv,
        },
        tags=[_spread_tag(signal)],
    )


# ── Spread Actions ────────────────────────────────────────────────

class _SFRSpreadEntryAction:
    risk: Optional[str] = None
    def __call__(self, *, now, backtest, info) -> List[QueryOrder]:
        return info.get(_SFRSpreadEntryAction, [])


class _SFRSpreadExitAction:
    risk: Optional[str] = None
    def __call__(self, *, now, backtest, info) -> List[UnwindOrder]:
        return info.get(_SFRSpreadExitAction, [])


# ── Spread Entry Trigger ──────────────────────────────────────────

@dataclass
class _SFRSpreadEntryReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[SpreadSignal]] = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        signals = _match_signal_table(self.signal_table, state)
        passing = [s for s in signals if isinstance(s, SpreadSignal) and s.passes_entry]

        if not passing:
            return TriggerInfo(False)

        max_concurrent = self.config.get("max_concurrent_trades")
        if backtest is not None:
            open_tags = set()
            for pos in backtest.portfolio.positions:
                open_tags.update((pos.meta or {}).get("tags", []))

            if self.config.get("no_duplicate_flies", True):
                passing = [s for s in passing if _spread_tag(s) not in open_tags]

            if max_concurrent is not None:
                n_open = len(backtest.portfolio.positions)
                if n_open >= max_concurrent:
                    return TriggerInfo(False)
                passing = passing[:max_concurrent - n_open]

        if not passing:
            return TriggerInfo(False)

        orders = []
        for s in passing:
            try:
                q = _make_spread_query(s, self.config)
                orders.append(QueryOrder(
                    timestamp=state, query=q,
                    meta={
                        "action": "sfr_spread_entry",
                        "tags": [_spread_tag(s)],
                        "direction": s.direction,
                        "entry_zscore": s.zscore,
                        "entry_level": s.level,
                        "entry_vol": s.vol,
                        "entry_roll": s.roll,
                    },
                ))
            except Exception as exc:
                logger.debug("Failed spread query for %s: %s", s.spread_id, exc)

        if not orders:
            return TriggerInfo(False)
        return TriggerInfo(True, {_SFRSpreadEntryAction: orders})


@dataclass
class SFRSpreadEntryTrigger(Trigger):
    """Fires when SFR spread screener identifies passing trades."""
    def __init__(self, signal_table, config, actions=None):
        reqs = _SFRSpreadEntryReqs(signal_table=signal_table, config=config)
        super().__init__(trigger_requirements=reqs, actions=actions or [_SFRSpreadEntryAction()])


# ── Spread Exit Trigger ───────────────────────────────────────────

@dataclass
class _SFRSpreadExitReqs(TriggerRequirements):
    signal_table: Dict[pd.Timestamp, List[SpreadSignal]] = field(default_factory=dict)
    config: dict = field(default_factory=dict)

    def has_triggered(self, state: dt.datetime, backtest=None) -> TriggerInfo:
        if backtest is None or not backtest.portfolio.positions:
            return TriggerInfo(False)

        ts = pd.Timestamp(state)
        signals_today = _match_signal_table(self.signal_table, state)
        signal_by_tag = {_spread_tag(s): s for s in signals_today if isinstance(s, SpreadSignal)}

        unwinds = []
        for pos in backtest.portfolio.positions:
            tags = set((pos.meta or {}).get("tags", []))
            spd_tags = [t for t in tags if t.startswith("sfr_spd_")]
            if not spd_tags:
                continue

            tag = spd_tags[0]
            entry_meta = pos.meta or {}
            exit_reason = None

            if tag in signal_by_tag:
                sig = signal_by_tag[tag]
                entry_z = entry_meta.get("entry_zscore", 0)
                direction = entry_meta.get("direction", sig.direction)
                current_z = sig.zscore
                entry_lvl = entry_meta.get("entry_level", 0)
                entry_vol = entry_meta.get("entry_vol", 0)
                dir_sign = 1 if direction == "pay_spread" else -1
                unrealized = dir_sign * (sig.level - entry_lvl)

                # Track peak unrealized (stored in meta, updated each step)
                peak_unreal = entry_meta.get("_peak_unrealized", 0.0)
                if unrealized > peak_unreal:
                    peak_unreal = unrealized
                    pos.meta["_peak_unrealized"] = peak_unreal

                # Track consecutive adverse z-score moves
                prev_z = entry_meta.get("_prev_zscore", entry_z)
                z_improving = (dir_sign > 0 and current_z > prev_z) or \
                              (dir_sign < 0 and current_z < prev_z)
                if z_improving:
                    pos.meta["_adverse_streak"] = 0
                else:
                    pos.meta["_adverse_streak"] = entry_meta.get("_adverse_streak", 0) + 1
                pos.meta["_prev_zscore"] = current_z
                adverse_streak = pos.meta.get("_adverse_streak", 0)

                # ── Exit checks (priority order) ──

                # 1. Mean reversion: z-score crossed zero
                if self.config.get("exit_mean_reversion", True):
                    if direction == "pay_spread" and current_z >= 0:
                        exit_reason = "mean_reversion"
                    elif direction == "receive_spread" and current_z <= 0:
                        exit_reason = "mean_reversion"

                # 2. Take profit: z-score decayed below threshold
                tp_z = self.config.get("exit_take_profit_zscore")
                if not exit_reason and tp_z is not None:
                    if abs(current_z) < tp_z:
                        exit_reason = "tp_zscore"

                # 3. Stop-loss: z-score worsened by N sigma
                stop_sd = self.config.get("exit_stop_loss_sd")
                if not exit_reason and stop_sd is not None:
                    if abs(current_z) - abs(entry_z) > stop_sd:
                        exit_reason = "stop_zscore"

                # 4. Fixed bp take-profit
                tp_bp = self.config.get("exit_take_profit_bp")
                if not exit_reason and tp_bp is not None and unrealized >= tp_bp:
                    exit_reason = "tp_bp"

                # 5. Fixed bp stop-loss
                sl_bp = self.config.get("exit_stop_loss_bp")
                if not exit_reason and sl_bp is not None and unrealized <= sl_bp:
                    exit_reason = "stop_bp"

                # 6. Trailing stop: exit if given back X% of peak unrealized
                trail_pct = self.config.get("exit_trailing_stop_pct")
                if not exit_reason and trail_pct is not None and peak_unreal > 0:
                    giveback = peak_unreal - unrealized
                    if giveback > peak_unreal * trail_pct:
                        exit_reason = "trailing_stop"

                # 7. Trailing stop in bp: exit if drawdown from peak exceeds threshold
                trail_bp = self.config.get("exit_trailing_stop_bp")
                if not exit_reason and trail_bp is not None and peak_unreal > 0:
                    giveback = peak_unreal - unrealized
                    if giveback > trail_bp:
                        exit_reason = "trailing_stop_bp"

                # 8. Momentum exit: z-score moved against us for N consecutive days
                mom_days = self.config.get("exit_adverse_momentum_days")
                if not exit_reason and mom_days is not None:
                    if adverse_streak >= mom_days:
                        exit_reason = "adverse_momentum"

                # 9. Vol-scaled stop: stop if unrealized loss exceeds N * entry_vol
                vol_stop_mult = self.config.get("exit_vol_scaled_stop")
                if not exit_reason and vol_stop_mult is not None and entry_vol > 0:
                    # Convert daily vol to the holding-period vol
                    vol_threshold = entry_vol * vol_stop_mult / np.sqrt(252)
                    if unrealized < -vol_threshold:
                        exit_reason = "vol_stop"

                # 10. Time-decay stop: tighten stop as max hold approaches
                time_decay_stop = self.config.get("exit_time_decay_stop")
                if not exit_reason and time_decay_stop and hasattr(pos, "opened"):
                    max_hold = self.config.get("exit_max_holding_days", 22)
                    if max_hold:
                        days_held = (ts - pd.Timestamp(pos.opened)).days
                        pct_elapsed = min(days_held / max_hold, 1.0)
                        # Stop tightens linearly: at day 0 = full stop, at max_hold = 0
                        base_stop = self.config.get("exit_stop_loss_bp", -5.0) or -5.0
                        tightened_stop = base_stop * (1.0 - 0.7 * pct_elapsed)
                        if unrealized < tightened_stop:
                            exit_reason = "time_decay_stop"

                # 11. Breakeven stop: after earning X bp, don't let it go negative
                be_threshold = self.config.get("exit_breakeven_after_bp")
                if not exit_reason and be_threshold is not None:
                    if peak_unreal >= be_threshold and unrealized <= 0:
                        exit_reason = "breakeven_stop"

            # 12. Max holding period (always last)
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
                    meta={"action": "sfr_spread_exit", "reason": exit_reason},
                ))

        if not unwinds:
            return TriggerInfo(False)
        return TriggerInfo(True, {_SFRSpreadExitAction: unwinds})


@dataclass
class SFRSpreadExitTrigger(Trigger):
    """Fires when open SFR spread positions hit exit conditions."""
    def __init__(self, signal_table, config, actions=None):
        reqs = _SFRSpreadExitReqs(signal_table=signal_table, config=config)
        super().__init__(trigger_requirements=reqs, actions=actions or [_SFRSpreadExitAction()])
