"""Vectorized RV backtest engine with dual P&L modes.

Supports:
- "approximate" mode: fast, uses frozen entry weights × daily rate changes
- "curve" mode: full NPV-based MTM using pre-loaded curve objects

Entry triggers (all must be met): R² ≥ threshold, |residual| ≥ threshold,
|Z-score| ≥ threshold, regime = "green", fly not already in portfolio.

Exit triggers (first met wins): residual crosses zero (mean reversion),
residual worsens by stop_loss_sd (stop-loss), max holding period reached.

Reference: J.P. Morgan "RV on the EUR swap yield curve" (Apr 2021).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class RVBacktestConfig:
    """Configuration for RV backtest engine."""
    # MTM mode
    mtm_mode: str = "approximate"       # "approximate" or "curve"
    # Entry triggers
    entry_min_rsq: float = 0.60
    entry_min_residual_bp: float = 4.0  # in basis points
    entry_min_zscore: float = 1.5
    # Exit triggers
    exit_mean_reversion: bool = True
    exit_stop_loss_sd: float = 2.0
    exit_max_holding_days: int = 22
    exit_carry_adjusted: bool = False
    # Portfolio rules
    max_concurrent_trades: Optional[int] = None
    no_duplicate_flies: bool = True
    reentry_after_stop: bool = True
    # Costs
    round_trip_cost_bp: float = 0.5
    min_profit_to_cost_ratio: float = 2.0


@dataclass
class Trade:
    """A single RV trade record."""
    fly_id: str
    category: str
    entry_date: pd.Timestamp
    entry_residual: float
    entry_zscore: float
    entry_weights: np.ndarray
    direction: int                      # +1 (receive belly) or -1 (pay belly)
    # Curve MTM mode
    package: Optional[List[Any]] = None
    entry_npv: float = 0.0
    prev_npv: float = 0.0
    # Approximate mode
    entry_rates: Optional[np.ndarray] = None
    # Common
    exit_date: Optional[pd.Timestamp] = None
    exit_reason: Optional[str] = None
    realized_pnl: float = 0.0
    carry_bp: float = 0.0
    daily_pnls: List[float] = field(default_factory=list)


@dataclass
class RVBacktestResult:
    """Output of the RV backtest."""
    trades: List[Trade]
    daily_pnl: pd.Series
    daily_pnl_by_category: pd.DataFrame
    cumulative_pnl: pd.Series
    metrics: Dict[str, float]


def _compute_metrics(trades: List[Trade], daily_pnl: pd.Series) -> Dict[str, float]:
    """Compute summary performance metrics."""
    clean = daily_pnl.dropna()
    total_pnl = clean.sum()
    n_trades = len(trades)
    completed = [t for t in trades if t.exit_date is not None]
    winning = [t for t in completed if t.realized_pnl > 0]
    hit_rate = len(winning) / len(completed) if completed else 0.0
    avg_pnl = np.mean([t.realized_pnl for t in completed]) if completed else 0.0
    std_daily = clean.std()
    sharpe = (clean.mean() / std_daily * np.sqrt(252)) if std_daily > 0 else 0.0
    cum = clean.cumsum()
    drawdown = cum - cum.cummax()
    max_dd = drawdown.min() if len(drawdown) > 0 else 0.0
    avg_holding = (
        np.mean([len(pd.bdate_range(t.entry_date, t.exit_date)) - 1 for t in completed])
        if completed
        else 0.0
    )
    return {
        "total_pnl_bp": total_pnl,
        "n_trades": n_trades,
        "n_completed": len(completed),
        "hit_rate": hit_rate,
        "avg_pnl_bp": avg_pnl,
        "sharpe": sharpe,
        "max_drawdown_bp": max_dd,
        "avg_holding_days": avg_holding,
    }


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
    residuals : dict of fly_id -> Series of residuals (in rate units, e.g., 0.0004 = 4bp)
    zscores : dict of fly_id -> Series of Z-scored residuals
    rsq : dict of fly_id -> Series of R-squared values
    weights : dict of fly_id -> DataFrame [dates x 3] of PCA/regression weights
    rates : dict of fly_id -> DataFrame [dates x 3] of raw rates
    regime : Series of "green"/"red" regime state
    fly_categories : dict of fly_id -> category name
    config : RVBacktestConfig
    carry : optional dict of fly_id -> Series of carry in bp
    curves : optional dict of date -> curve object (for "curve" MTM mode)
    build_package_fn : optional callable(curve, fly_id, weights, direction)
        -> (package, entry_npv) for "curve" mode

    Returns
    -------
    RVBacktestResult
    """
    fly_ids = sorted(residuals.keys())
    all_dates = residuals[fly_ids[0]].index
    categories = sorted(set(fly_categories.values()))

    open_trades: List[Trade] = []
    closed_trades: List[Trade] = []
    daily_pnl = pd.Series(0.0, index=all_dates)
    daily_pnl_cat = pd.DataFrame(0.0, index=all_dates, columns=categories)

    # Track flies that were stopped out yesterday (for reentry logic)
    stopped_yesterday: set = set()

    for i, dt in enumerate(all_dates):
        day_pnl = 0.0
        stopped_today: set = set()

        # --- Mark-to-market and check exits for open trades ---
        still_open: List[Trade] = []
        for trade in open_trades:
            # Compute daily P&L
            if config.mtm_mode == "curve" and curves is not None and trade.package is not None:
                curve_t = curves.get(dt if not hasattr(dt, 'date') else dt.date() if hasattr(dt, 'date') else dt)
                if curve_t is not None:
                    npv_t = sum(curve_t.npv(leg) for leg in trade.package)
                    trade_daily = npv_t - trade.prev_npv
                    trade.prev_npv = npv_t
                else:
                    trade_daily = 0.0
            else:
                # Approximate mode: frozen weights × rate changes
                if trade.entry_rates is not None and trade.fly_id in rates:
                    current_rates = rates[trade.fly_id].loc[dt].values
                    if i > 0:
                        prev_rates = rates[trade.fly_id].iloc[i - 1].values
                        delta = current_rates - prev_rates
                        trade_daily = trade.direction * np.sum(trade.entry_weights * delta) * 10_000
                    else:
                        trade_daily = 0.0
                else:
                    trade_daily = 0.0

            trade.daily_pnls.append(trade_daily)
            day_pnl += trade_daily
            cat = fly_categories.get(trade.fly_id, categories[0] if categories else "unknown")
            if cat in daily_pnl_cat.columns:
                daily_pnl_cat.loc[dt, cat] += trade_daily

            # Check exit conditions
            holding_days = len(pd.bdate_range(trade.entry_date, dt)) - 1
            exit_reason = None

            fid = trade.fly_id
            if fid in residuals and not pd.isna(residuals[fid].get(dt, np.nan)):
                current_residual = residuals[fid].loc[dt]
                current_zscore = zscores[fid].loc[dt] if fid in zscores else np.nan

                # Mean reversion: residual crosses zero (opposite sign from entry)
                if config.exit_mean_reversion:
                    if trade.entry_residual > 0 and current_residual <= 0:
                        exit_reason = "mean_reversion"
                    elif trade.entry_residual < 0 and current_residual >= 0:
                        exit_reason = "mean_reversion"

                # Stop loss: residual worsens by exit_stop_loss_sd
                if exit_reason is None and not pd.isna(current_zscore):
                    if abs(current_zscore) > abs(trade.entry_zscore) + config.exit_stop_loss_sd:
                        # Check it's in the same direction (worsening)
                        if np.sign(current_zscore) == np.sign(trade.entry_zscore):
                            exit_reason = "stop_loss"

            # Max holding period
            if exit_reason is None and holding_days >= config.exit_max_holding_days:
                exit_reason = "max_hold"

            if exit_reason is not None:
                trade.exit_date = dt
                trade.exit_reason = exit_reason
                trade.realized_pnl = sum(trade.daily_pnls) - config.round_trip_cost_bp
                closed_trades.append(trade)
                if exit_reason == "stop_loss":
                    stopped_today.add(trade.fly_id)
            else:
                still_open.append(trade)

        open_trades = still_open

        # --- Check entry criteria for new trades ---
        regime_state = regime.get(dt, np.nan)
        if regime_state != "green":
            daily_pnl.iloc[i] = day_pnl
            stopped_yesterday = stopped_today
            continue

        open_fly_ids = {t.fly_id for t in open_trades}

        for fid in fly_ids:
            # Skip if already in portfolio
            if config.no_duplicate_flies and fid in open_fly_ids:
                continue

            # Skip if stopped out yesterday and reentry not allowed
            if not config.reentry_after_stop and fid in stopped_yesterday:
                continue

            # Max concurrent trades
            if config.max_concurrent_trades is not None:
                if len(open_trades) >= config.max_concurrent_trades:
                    break

            # Get current signals
            res_val = residuals[fid].get(dt, np.nan)
            zs_val = zscores[fid].get(dt, np.nan)
            rsq_val = rsq[fid].get(dt, np.nan)

            if pd.isna(res_val) or pd.isna(zs_val) or pd.isna(rsq_val):
                continue

            # Check entry criteria
            if rsq_val < config.entry_min_rsq:
                continue
            if abs(res_val) * 10_000 < config.entry_min_residual_bp:
                continue
            if abs(zs_val) < config.entry_min_zscore:
                continue

            # Profit-to-cost filter
            expected_profit = abs(res_val) * 10_000  # rough bp estimate
            if expected_profit < config.min_profit_to_cost_ratio * config.round_trip_cost_bp:
                continue

            # Direction: fade the residual
            direction = -1 if res_val > 0 else 1  # if cheap (positive), pay belly; if rich, receive

            # Get weights for this date
            if fid not in weights:
                continue
            w = weights[fid].loc[dt].values if dt in weights[fid].index else None
            if w is None or np.any(np.isnan(w)):
                continue

            # Build trade
            trade = Trade(
                fly_id=fid,
                category=fly_categories.get(fid, "unknown"),
                entry_date=dt,
                entry_residual=res_val,
                entry_zscore=zs_val,
                entry_weights=w.copy(),
                direction=direction,
            )

            if config.mtm_mode == "curve" and curves is not None and build_package_fn is not None:
                curve_t = curves.get(dt if not hasattr(dt, 'date') else dt.date() if hasattr(dt, 'date') else dt)
                if curve_t is not None:
                    pkg, entry_npv = build_package_fn(curve_t, fid, w, direction)
                    trade.package = pkg
                    trade.entry_npv = entry_npv
                    trade.prev_npv = entry_npv
            else:
                trade.entry_rates = rates[fid].loc[dt].values.copy() if fid in rates else None

            if carry and fid in carry:
                c_val = carry[fid].get(dt, 0.0)
                trade.carry_bp = c_val if not pd.isna(c_val) else 0.0

            open_trades.append(trade)
            open_fly_ids.add(fid)

        daily_pnl.iloc[i] = day_pnl
        stopped_yesterday = stopped_today

    # Close any remaining open trades at end
    for trade in open_trades:
        trade.exit_date = all_dates[-1]
        trade.exit_reason = "end_of_backtest"
        trade.realized_pnl = sum(trade.daily_pnls) - config.round_trip_cost_bp
        closed_trades.append(trade)

    all_trades = closed_trades
    cumulative_pnl = daily_pnl.cumsum()
    metrics = _compute_metrics(all_trades, daily_pnl)

    return RVBacktestResult(
        trades=all_trades,
        daily_pnl=daily_pnl,
        daily_pnl_by_category=daily_pnl_cat,
        cumulative_pnl=cumulative_pnl,
        metrics=metrics,
    )
