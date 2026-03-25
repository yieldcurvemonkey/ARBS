"""Vectorized-loop backtest engine for relative value strategies.

Manages trade entries/exits based on signal criteria (Z-score, R-squared, residual bp).
Supports dual MTM modes:
- "approximate": frozen entry weights x daily rate changes x 10000 (fast, for param sweeps)
- "curve": full NPV repricing via pre-loaded curve objects (accurate, for final runs)

Reference: J.P. Morgan "RV on the EUR swap yield curve" (Apr 2021).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RVBacktestConfig:
    """Configuration for RV backtest engine."""

    # MTM mode
    mtm_mode: str = "approximate"  # "approximate" or "curve"
    # Entry triggers
    entry_min_rsq: float = 0.60
    entry_min_residual_bp: float = 4.0
    entry_min_zscore: float = 1.5
    # Exit triggers
    exit_mean_reversion: bool = True
    exit_stop_loss_sd: float = 2.0
    exit_max_holding_days: int = 22
    exit_carry_adjusted: bool = False
    # Portfolio constraints
    max_concurrent_trades: Optional[int] = None
    no_duplicate_flies: bool = True
    # Costs
    round_trip_cost_bp: float = 0.5
    min_profit_to_cost_ratio: float = 2.0


@dataclass
class Trade:
    """A single RV trade."""

    fly_id: str
    category: str
    entry_date: pd.Timestamp
    entry_residual: float
    entry_zscore: float
    entry_weights: np.ndarray  # [left, belly, right] DV01 weights
    direction: int  # +1 (buy fly) or -1 (sell fly)
    # Curve MTM mode fields
    package: Optional[List[Any]] = None
    entry_npv: float = 0.0
    prev_npv: float = 0.0
    # Approximate mode fields
    entry_rates: Optional[np.ndarray] = None
    prev_rates: Optional[np.ndarray] = None
    # Common
    exit_date: Optional[pd.Timestamp] = None
    exit_reason: Optional[str] = None
    realized_pnl: float = 0.0
    carry_bp: float = 0.0


@dataclass
class RVBacktestResult:
    """Output of RV backtest."""

    trades: List[Trade]
    daily_pnl: pd.Series
    daily_pnl_by_category: pd.DataFrame
    cumulative_pnl: pd.Series
    metrics: Dict[str, float]


def run_rv_backtest(
    residuals: Dict[str, pd.Series],
    zscores: Dict[str, pd.Series],
    rsq: Dict[str, pd.Series],
    weights: Dict[str, pd.DataFrame],
    rates: Dict[str, pd.DataFrame],
    regime: pd.Series,
    fly_categories: Dict[str, str],
    config: RVBacktestConfig,
    carry: Optional[Dict[str, pd.Series]] = None,
    curves: Optional[Dict] = None,
    build_package_fn: Optional[Callable] = None,
) -> RVBacktestResult:
    """Run the RV backtest.

    Parameters
    ----------
    residuals : dict of fly_id -> Series of OOS residuals
    zscores : dict of fly_id -> Series of Z-scores
    rsq : dict of fly_id -> Series of rolling R-squared
    weights : dict of fly_id -> DataFrame [dates x 3] of DV01 weights
    rates : dict of fly_id -> DataFrame [dates x 3] of rates
    regime : Series of "green"/"red" per date
    fly_categories : dict of fly_id -> category string
    config : RVBacktestConfig
    carry : optional dict of fly_id -> Series of carry in bp
    curves : optional dict of date -> curve object (for "curve" MTM mode)
    build_package_fn : optional callable(fly_id, date, weights, curve) -> package

    Returns
    -------
    RVBacktestResult
    """
    fly_ids = list(residuals.keys())
    all_dates = residuals[fly_ids[0]].index

    all_trades: List[Trade] = []
    active_trades: List[Trade] = []
    daily_pnl = pd.Series(0.0, index=all_dates)

    categories = sorted(set(fly_categories.values()))
    daily_pnl_by_cat = pd.DataFrame(0.0, index=all_dates, columns=categories)

    for dt_idx, dt in enumerate(all_dates):
        # --- 1. MTM active trades ---
        closed_today: List[Trade] = []
        for trade in active_trades:
            fid = trade.fly_id

            if config.mtm_mode == "approximate":
                curr_rates = rates[fid].loc[dt].values
                if trade.prev_rates is None:
                    trade.prev_rates = trade.entry_rates.copy()
                rate_change = curr_rates - trade.prev_rates
                day_pnl = (
                    trade.direction
                    * np.sum(trade.entry_weights * rate_change)
                    * 10000
                )
                trade.realized_pnl += day_pnl
                trade.prev_rates = curr_rates.copy()
                daily_pnl.loc[dt] += day_pnl
                cat = fly_categories[fid]
                daily_pnl_by_cat.loc[dt, cat] += day_pnl
            elif (
                config.mtm_mode == "curve"
                and curves is not None
                and trade.package is not None
            ):
                if dt in curves:
                    curve = curves[dt]
                    curr_npv = sum(curve.npv(p) for p in trade.package)
                    day_pnl = curr_npv - trade.prev_npv
                    trade.realized_pnl += day_pnl
                    trade.prev_npv = curr_npv
                    daily_pnl.loc[dt] += day_pnl
                    cat = fly_categories[fid]
                    daily_pnl_by_cat.loc[dt, cat] += day_pnl

            # --- 2. Check exit conditions ---
            holding_days = len(pd.bdate_range(trade.entry_date, dt)) - 1

            # Max holding period
            if holding_days >= config.exit_max_holding_days:
                trade.exit_date = dt
                trade.exit_reason = "max_hold"
                closed_today.append(trade)
                continue

            # Mean reversion exit
            if config.exit_mean_reversion:
                curr_zscore = (
                    zscores[fid].loc[dt] if dt in zscores[fid].index else 0
                )
                if trade.direction * curr_zscore <= 0:
                    trade.exit_date = dt
                    trade.exit_reason = "mean_reversion"
                    closed_today.append(trade)
                    continue

            # Stop loss
            curr_zscore = (
                zscores[fid].loc[dt] if dt in zscores[fid].index else 0
            )
            if abs(curr_zscore) > abs(trade.entry_zscore) * config.exit_stop_loss_sd:
                trade.exit_date = dt
                trade.exit_reason = "stop_loss"
                closed_today.append(trade)
                continue

        # Remove closed trades from active
        for t in closed_today:
            t.realized_pnl -= config.round_trip_cost_bp
            active_trades.remove(t)

        # --- 3. Check entry conditions ---
        if regime.loc[dt] == "red":
            continue

        for fid in fly_ids:
            # Skip if we already have this fly on
            if config.no_duplicate_flies:
                if any(t.fly_id == fid for t in active_trades):
                    continue

            # Max concurrent trades
            if config.max_concurrent_trades is not None:
                if len(active_trades) >= config.max_concurrent_trades:
                    break

            # Get signals
            res_val = (
                residuals[fid].loc[dt]
                if dt in residuals[fid].index
                else np.nan
            )
            zs_val = (
                zscores[fid].loc[dt]
                if dt in zscores[fid].index
                else np.nan
            )
            rsq_val = (
                rsq[fid].loc[dt] if dt in rsq[fid].index else np.nan
            )

            if np.isnan(res_val) or np.isnan(zs_val) or np.isnan(rsq_val):
                continue

            # Entry filters
            if rsq_val < config.entry_min_rsq:
                continue
            if abs(res_val) * 10000 < config.entry_min_residual_bp:
                continue
            if abs(zs_val) < config.entry_min_zscore:
                continue

            # Direction: sell fly if residual > 0 (rich), buy if < 0 (cheap)
            direction = -1 if res_val > 0 else 1

            w = (
                weights[fid].loc[dt].values
                if dt in weights[fid].index
                else None
            )
            if w is None:
                continue

            entry_rates_val = rates[fid].loc[dt].values.copy()

            trade = Trade(
                fly_id=fid,
                category=fly_categories[fid],
                entry_date=dt,
                entry_residual=res_val,
                entry_zscore=zs_val,
                entry_weights=w.copy(),
                direction=direction,
                entry_rates=entry_rates_val,
                prev_rates=entry_rates_val.copy(),
            )

            # Build curve package if in curve mode
            if (
                config.mtm_mode == "curve"
                and curves is not None
                and build_package_fn is not None
            ):
                if dt in curves:
                    package = build_package_fn(fid, dt, w, curves[dt])
                    if package is not None:
                        trade.package = package
                        trade.entry_npv = sum(
                            curves[dt].npv(p) for p in package
                        )
                        trade.prev_npv = trade.entry_npv

            active_trades.append(trade)
            all_trades.append(trade)

    # Close any remaining open trades at the end
    for trade in active_trades:
        trade.exit_date = all_dates[-1]
        trade.exit_reason = "end_of_data"
        trade.realized_pnl -= config.round_trip_cost_bp

    # Compute metrics
    cumulative_pnl = daily_pnl.cumsum()

    n_trades = len(all_trades)
    if n_trades > 0:
        wins = sum(1 for t in all_trades if t.realized_pnl > 0)
        hit_rate = wins / n_trades
        avg_pnl = np.mean([t.realized_pnl for t in all_trades])

        daily_std = daily_pnl.std()
        sharpe = (
            (daily_pnl.mean() / daily_std * np.sqrt(252))
            if daily_std > 0
            else 0.0
        )

        running_max = cumulative_pnl.cummax()
        drawdown = cumulative_pnl - running_max
        max_dd = drawdown.min()
    else:
        hit_rate = 0.0
        avg_pnl = 0.0
        sharpe = 0.0
        max_dd = 0.0

    metrics = {
        "sharpe": float(sharpe),
        "hit_rate": float(hit_rate),
        "avg_pnl": float(avg_pnl),
        "max_drawdown": float(max_dd),
        "n_trades": n_trades,
        "total_pnl": (
            float(cumulative_pnl.iloc[-1]) if len(cumulative_pnl) > 0 else 0.0
        ),
    }

    return RVBacktestResult(
        trades=all_trades,
        daily_pnl=daily_pnl,
        daily_pnl_by_category=daily_pnl_by_cat,
        cumulative_pnl=cumulative_pnl,
        metrics=metrics,
    )
