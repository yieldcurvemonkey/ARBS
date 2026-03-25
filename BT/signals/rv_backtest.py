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
from collections import defaultdict
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
    trade_belly_bpv: float = 100_000.0
    ranking_method: str = "abs_zscore"
    sizing_method: str = "equal_belly_bpv"
    # Entry triggers
    entry_min_rsq: float = 0.60
    entry_min_fit: Optional[float] = None
    entry_min_residual_bp: float = 4.0  # in basis points
    entry_min_zscore: float = 1.5
    entry_use_carry_filter: bool = False
    # Exit triggers
    exit_mean_reversion: bool = True
    exit_stop_loss_sd: float = 2.0
    exit_max_holding_days: int = 22
    exit_carry_adjusted: bool = False
    # Portfolio rules
    max_concurrent_trades: Optional[int] = None
    no_duplicate_flies: bool = True
    reentry_after_stop: bool = True
    # Optional stationarity gating
    stationarity_filter_enabled: bool = False
    stationarity_max_adf_pvalue: float = 0.05
    stationarity_max_half_life_days: Optional[float] = None
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


@dataclass
class RVQueryBacktestResult:
    """Query-driven RV backtest output using repo pricing infrastructure."""

    query_backtest: Any
    daily_pnl: pd.Series
    daily_pnl_ccy: pd.Series
    daily_pnl_by_category: pd.DataFrame
    daily_pnl_by_category_ccy: pd.DataFrame
    cumulative_pnl: pd.Series
    cumulative_pnl_ccy: pd.Series
    drawdown: pd.Series
    trades: pd.DataFrame
    metrics: Dict[str, float]


def _compute_query_metrics(trades: pd.DataFrame, daily_pnl: pd.Series) -> Dict[str, float]:
    clean = daily_pnl.dropna()
    total_pnl = float(clean.sum()) if len(clean) else 0.0
    n_trades = int(len(trades))
    hit_rate = float((trades["realized_pnl"] > 0).mean()) if n_trades else 0.0
    avg_pnl = float(trades["realized_pnl"].mean()) if n_trades else 0.0
    std_daily = float(clean.std()) if len(clean) else 0.0
    sharpe = float(clean.mean() / std_daily * np.sqrt(252)) if std_daily > 0 else 0.0
    cum = clean.cumsum()
    drawdown = cum - cum.cummax()
    max_dd = float(drawdown.min()) if len(drawdown) else 0.0
    avg_holding = float(trades["holding_days"].mean()) if n_trades and "holding_days" in trades.columns else 0.0
    return {
        "total_pnl": total_pnl,
        "n_trades": n_trades,
        "hit_rate": hit_rate,
        "avg_pnl": avg_pnl,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "avg_holding_days": avg_holding,
    }


class _AlwaysOnRequirements:
    calc_type = "rv_query"

    def has_triggered(self, state, backtest=None):
        from BT.event import TriggerInfo

        return TriggerInfo(True, info={})


@dataclass
class _RVQuerySignalAction:
    residuals: Dict[str, pd.Series]
    zscores: Dict[str, pd.Series]
    fit_quality: Dict[str, pd.Series]
    weights: Dict[str, pd.DataFrame]
    fly_categories: Dict[str, str]
    entry_snapshots: Dict[str, Dict[pd.Timestamp, Any]]
    residual_stats: Dict[str, pd.DataFrame]
    query_factory: Callable[[str, np.ndarray, int], Any]
    frozen_residual_getter: Callable[[str, pd.Timestamp, Any], float]
    config: RVBacktestConfig
    regime: pd.Series
    carry_roll: Optional[Dict[str, pd.Series]] = None
    stationarity_pvalues: Optional[Dict[str, pd.Series]] = None
    stationarity_half_lives: Optional[Dict[str, pd.Series]] = None
    _trade_seq: int = field(default=0, init=False)
    _last_dt: Optional[pd.Timestamp] = field(default=None, init=False)
    _stopped_today: set = field(default_factory=set, init=False)
    _stopped_yesterday: set = field(default_factory=set, init=False)

    def _roll_date(self, dt: pd.Timestamp) -> None:
        if self._last_dt is None or dt != self._last_dt:
            self._stopped_yesterday = set(self._stopped_today)
            self._stopped_today = set()
            self._last_dt = dt

    def _cost_ccy(self, weights: np.ndarray) -> float:
        gross_bpv = float(self.config.trade_belly_bpv) * float(np.abs(weights).sum())
        return gross_bpv * float(self.config.round_trip_cost_bp)

    def _cost_bp_equiv(self, weights: np.ndarray) -> float:
        return float(self.config.round_trip_cost_bp) * float(np.abs(weights).sum())

    def _fit_threshold(self) -> float:
        if self.config.entry_min_fit is not None:
            return float(self.config.entry_min_fit)
        return float(self.config.entry_min_rsq)

    @staticmethod
    def _selector(position_id: str):
        return lambda p, position_id=position_id: p.meta.get("rv_position_id") == position_id

    def __call__(self, *, now, backtest, info) -> List[Any]:
        from BT.query_order import QueryOrder, UnwindOrder

        dt = pd.Timestamp(now).normalize()
        self._roll_date(dt)

        orders: List[Any] = []
        current_positions = [
            p for p in backtest.portfolio.iter_positions()
            if p.meta.get("rv_position_id") is not None
        ]

        positions_to_exit: set[str] = set()
        for pos in current_positions:
            meta = pos.meta
            fid = meta.get("fly_id")
            if fid is None:
                continue

            entry_dt = pd.Timestamp(meta.get("entry_signal_date", pos.opened)).normalize()
            snapshot = self.entry_snapshots.get(fid, {}).get(entry_dt)
            if snapshot is None:
                continue

            exit_reason = None
            current_residual = np.nan
            current_zscore = np.nan
            try:
                current_residual = float(self.frozen_residual_getter(fid, dt, snapshot))
                entry_mean = float(meta.get("entry_residual_mean", 0.0))
                entry_std = float(meta.get("entry_residual_std", np.nan))
                if np.isfinite(entry_std) and entry_std > 0:
                    current_zscore = (current_residual - entry_mean) / entry_std
            except Exception:
                current_residual = np.nan

            if self.config.exit_mean_reversion and np.isfinite(current_residual):
                if float(meta.get("entry_residual", 0.0)) > 0 and current_residual <= 0:
                    exit_reason = "mean_reversion"
                elif float(meta.get("entry_residual", 0.0)) < 0 and current_residual >= 0:
                    exit_reason = "mean_reversion"

            if exit_reason is None and np.isfinite(current_zscore):
                entry_zscore = float(meta.get("entry_zscore", np.nan))
                if (
                    np.isfinite(entry_zscore)
                    and abs(current_zscore) > abs(entry_zscore) + float(self.config.exit_stop_loss_sd)
                    and np.sign(current_zscore) == np.sign(entry_zscore)
                ):
                    exit_reason = "stop_loss"

            holding_days = len(pd.bdate_range(pos.opened.date(), dt.date())) - 1
            if exit_reason is None and holding_days >= int(self.config.exit_max_holding_days):
                exit_reason = "max_hold"

            if exit_reason is None:
                continue

            position_id = meta.get("rv_position_id")
            positions_to_exit.add(position_id)
            weights = np.asarray(meta.get("base_weights", []), dtype=float)
            fee = self._cost_ccy(weights) if weights.size else 0.0
            orders.append(
                UnwindOrder(
                    timestamp=now,
                    selector=self._selector(position_id),
                    meta={"action": "unwind", "reason": exit_reason, "fee": fee},
                )
            )
            if exit_reason == "stop_loss":
                self._stopped_today.add(fid)

        regime_state = self.regime.get(dt, np.nan)
        if regime_state != "green":
            return orders

        open_after_exit = [
            p for p in current_positions
            if p.meta.get("rv_position_id") not in positions_to_exit
        ]
        open_fly_ids = {p.meta.get("fly_id") for p in open_after_exit}

        candidates: List[Tuple[float, str, float, float, float, np.ndarray, Any]] = []
        for fid in sorted(self.residuals):
            if self.config.no_duplicate_flies and fid in open_fly_ids:
                continue
            if not self.config.reentry_after_stop and fid in (self._stopped_yesterday | self._stopped_today):
                continue

            res_val = self.residuals[fid].get(dt, np.nan)
            z_val = self.zscores[fid].get(dt, np.nan)
            fit_val = self.fit_quality[fid].get(dt, np.nan)
            if pd.isna(res_val) or pd.isna(z_val) or pd.isna(fit_val):
                continue
            if fit_val < self._fit_threshold():
                continue
            if abs(float(res_val)) * 10_000 < float(self.config.entry_min_residual_bp):
                continue
            if abs(float(z_val)) < float(self.config.entry_min_zscore):
                continue

            if self.config.stationarity_filter_enabled:
                pval = np.nan if self.stationarity_pvalues is None else self.stationarity_pvalues.get(fid, pd.Series(dtype=float)).get(dt, np.nan)
                half_life = np.nan if self.stationarity_half_lives is None else self.stationarity_half_lives.get(fid, pd.Series(dtype=float)).get(dt, np.nan)
                if pd.isna(pval) or float(pval) > float(self.config.stationarity_max_adf_pvalue):
                    continue
                if self.config.stationarity_max_half_life_days is not None:
                    if pd.isna(half_life) or float(half_life) > float(self.config.stationarity_max_half_life_days):
                        continue

            if fid not in self.weights or dt not in self.weights[fid].index:
                continue
            w = self.weights[fid].loc[dt].to_numpy(dtype=float)
            if np.any(np.isnan(w)):
                continue

            direction = -1 if float(res_val) > 0 else 1
            expected_edge_bp = abs(float(res_val)) * 10_000
            if self.config.entry_use_carry_filter and self.carry_roll is not None and fid in self.carry_roll:
                carry_val = self.carry_roll[fid].get(dt, np.nan)
                if pd.notna(carry_val):
                    expected_edge_bp += direction * float(carry_val)

            if expected_edge_bp < float(self.config.min_profit_to_cost_ratio) * self._cost_bp_equiv(w):
                continue

            snapshot = self.entry_snapshots.get(fid, {}).get(dt)
            if snapshot is None:
                continue
            candidates.append((abs(float(z_val)), fid, float(res_val), float(z_val), float(fit_val), w, snapshot))

        candidates.sort(key=lambda item: item[0], reverse=True)
        if self.config.max_concurrent_trades is not None:
            available_slots = max(0, int(self.config.max_concurrent_trades) - len(open_after_exit))
            candidates = candidates[:available_slots]

        for _, fid, res_val, z_val, fit_val, w, snapshot in candidates:
            direction = -1 if res_val > 0 else 1
            query = self.query_factory(fid, w, direction)
            carry_roll_val = np.nan
            if self.carry_roll is not None and fid in self.carry_roll:
                carry_roll_val = self.carry_roll[fid].get(dt, np.nan)

            stats_row = self.residual_stats.get(fid)
            entry_mean = np.nan
            entry_std = np.nan
            if stats_row is not None and dt in stats_row.index:
                entry_mean = float(stats_row.loc[dt, "mean"])
                entry_std = float(stats_row.loc[dt, "std"])

            self._trade_seq += 1
            trade_id = f"{fid}|{dt.date().isoformat()}|{self._trade_seq}"
            orders.append(
                QueryOrder(
                    timestamp=now,
                    query=query,
                    meta={
                        "strategy": "rv_query",
                        "rv_position_id": trade_id,
                        "fly_id": fid,
                        "category": self.fly_categories.get(fid, "unknown"),
                        "entry_signal_date": dt,
                        "entry_residual": res_val,
                        "entry_zscore": z_val,
                        "entry_fit_quality": fit_val,
                        "entry_model_snapshot": snapshot,
                        "entry_residual_mean": entry_mean,
                        "entry_residual_std": entry_std,
                        "base_weights": [float(x) for x in w],
                        "direction": direction,
                        "carry_roll_bp": None if pd.isna(carry_roll_val) else float(carry_roll_val),
                    },
                )
            )

        return orders


@dataclass
class RVQueryDrivenBacktest:
    """Category-aware query backtest for RV studies."""

    time_grid: Any
    strategy: Any
    mdp: Optional[Any] = None
    exec_engine: Any = field(default_factory=lambda: __import__("BT.execution_engine", fromlist=["ExecutionEngine"]).ExecutionEngine())
    risk_fn: Callable = lambda p, g: {}
    portfolio: Any = field(default_factory=lambda: __import__("BT.query_portfolio", fromlist=["QueryPortfolio"]).QueryPortfolio())
    position_handlers: List[Any] = field(default_factory=list)
    dynamic_triggers: List[Any] = field(default_factory=list)
    _cache: Dict[Any, Any] = field(default_factory=dict)
    mtm_history: Dict[Any, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    realized_pnl_history: Dict[Any, float] = field(default_factory=dict)
    _now: Optional[Any] = None
    show_progress: bool = False
    progress_desc: str = "RV QUERY BACKTEST"
    mtm_history_by_category: Dict[Any, Dict[str, float]] = field(default_factory=dict)
    realized_pnl_by_category: Dict[str, float] = field(default_factory=dict)
    realized_pnl_by_category_history: Dict[Any, Dict[str, float]] = field(default_factory=dict)
    closed_trade_records: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        from BT.query_engine import QueryDrivenBacktest

        self._base = QueryDrivenBacktest(
            time_grid=self.time_grid,
            strategy=self.strategy,
            mdp=self.mdp,
            exec_engine=self.exec_engine,
            risk_fn=self.risk_fn,
            portfolio=self.portfolio,
            position_handlers=self.position_handlers,
            dynamic_triggers=self.dynamic_triggers,
            _cache=self._cache,
            mtm_history=self.mtm_history,
            realized_pnl=self.realized_pnl,
            realized_pnl_history=self.realized_pnl_history,
            _now=self._now,
            show_progress=self.show_progress,
            progress_desc=self.progress_desc,
        )

    def __getattr__(self, item):
        return getattr(self._base, item)

    def _record_realized_history(self, now) -> None:
        self.realized_pnl_history[now] = self._base.realized_pnl
        self.realized_pnl_by_category_history[now] = dict(self.realized_pnl_by_category)

    def _handle_unwind(self, order, now) -> None:
        to_close = self._base.portfolio.pop_matching(order.selector)
        if not to_close:
            self._record_realized_history(now)
            return

        fee = float((order.meta or {}).get("fee", 0.0))
        fee_per_position = fee / len(to_close) if to_close else 0.0

        pnl = 0.0
        for pos in to_close:
            handler = self._base._handler_for_position(pos)
            realized, triggers = handler.on_unwind(pos, lambda q: self._base._pricer_for_query(q, now), now, self._base)
            realized = float(realized) - fee_per_position
            pnl += realized
            category = pos.meta.get("category", "unknown")
            self.realized_pnl_by_category[category] = self.realized_pnl_by_category.get(category, 0.0) + realized
            if triggers:
                self._base.inject_triggers(triggers)
            self.closed_trade_records.append(
                {
                    "rv_position_id": pos.meta.get("rv_position_id"),
                    "fly_id": pos.meta.get("fly_id"),
                    "category": category,
                    "entry_date": pos.opened,
                    "exit_date": now,
                    "exit_reason": (order.meta or {}).get("reason", "unwind"),
                    "realized_pnl": realized,
                    "entry_residual": pos.meta.get("entry_residual"),
                    "entry_zscore": pos.meta.get("entry_zscore"),
                    "entry_fit_quality": pos.meta.get("entry_fit_quality"),
                    "carry_roll_bp": pos.meta.get("carry_roll_bp"),
                    "direction": pos.meta.get("direction"),
                    "base_weights": pos.meta.get("base_weights"),
                    "holding_days": len(pd.bdate_range(pos.opened.date(), pd.Timestamp(now).date())) - 1,
                }
            )

        self._base.realized_pnl += pnl
        self._record_realized_history(now)

    def mark_to_market(self, now) -> float:
        total = float(self._base.realized_pnl)
        cat_totals: Dict[str, float] = defaultdict(float)
        for category, realized in self.realized_pnl_by_category.items():
            cat_totals[category] += float(realized)

        new_positions = []
        for pos in self._base.portfolio.iter_positions():
            handler = self._base._handler_for_position(pos)
            p1, realized_delta, triggers = handler.on_mark(
                pos,
                lambda q: self._base._pricer_for_query(q, now),
                now,
                self._base,
                auto_roll=pos.meta.get("auto_roll", False),
            )

            if realized_delta:
                realized_delta = float(realized_delta)
                self._base.realized_pnl += realized_delta
                category = p1.meta.get("category", "unknown")
                self.realized_pnl_by_category[category] = self.realized_pnl_by_category.get(category, 0.0) + realized_delta
                self._record_realized_history(now)

            if triggers:
                self._base.inject_triggers(triggers)

            value = float(self._base._position_value(p1, now))
            total += value
            category = p1.meta.get("category", "unknown")
            cat_totals[category] += value
            new_positions.append(p1)

        self._base.portfolio.positions = new_positions
        self._base.mtm_history[now] = total
        self.mtm_history_by_category[now] = dict(cat_totals)
        return total

    def run(self) -> None:
        from BT.query_order import QueryOrder, UnwindOrder

        states = self._base._ensure_time_grid_cache()
        iterator = states
        if self._base.show_progress:
            import tqdm

            iterator = tqdm.tqdm(states, desc=self._base.progress_desc, total=len(states), unit="step")

        for now in iterator:
            self._base._now = now
            new_orders = self._base._evaluate_triggers(now)
            add_orders = [o for o in new_orders if isinstance(o, QueryOrder)]
            unwind_orders = [o for o in new_orders if isinstance(o, UnwindOrder)]

            fills = self._base.exec_engine.execute(add_orders)
            self._base.portfolio.orders_log.extend(add_orders)
            self._base.portfolio.trades_log.extend(fills)

            for order in fills:
                handler = self._base._handler_for_query(order.query)
                pos = handler.build_position(order, lambda q: self._base._pricer_for_query(q, now), now, self._base)
                self._base.portfolio.add(pos)

            for unwind_order in unwind_orders:
                self._handle_unwind(unwind_order, now)

            self.mark_to_market(now)


def _finalize_query_trades(backtest: RVQueryDrivenBacktest, last_dt: pd.Timestamp) -> pd.DataFrame:
    records = list(backtest.closed_trade_records)
    for pos in backtest.portfolio.iter_positions():
        current_value = float(backtest._base._position_value(pos, last_dt))
        records.append(
            {
                "rv_position_id": pos.meta.get("rv_position_id"),
                "fly_id": pos.meta.get("fly_id"),
                "category": pos.meta.get("category", "unknown"),
                "entry_date": pos.opened,
                "exit_date": last_dt,
                "exit_reason": "end_of_backtest",
                "realized_pnl": current_value,
                "entry_residual": pos.meta.get("entry_residual"),
                "entry_zscore": pos.meta.get("entry_zscore"),
                "entry_fit_quality": pos.meta.get("entry_fit_quality"),
                "carry_roll_bp": pos.meta.get("carry_roll_bp"),
                "direction": pos.meta.get("direction"),
                "base_weights": pos.meta.get("base_weights"),
                "holding_days": len(pd.bdate_range(pos.opened.date(), last_dt.date())) - 1,
            }
        )
    if not records:
        return pd.DataFrame(columns=["fly_id", "category", "entry_date", "exit_date", "exit_reason", "realized_pnl", "holding_days"])
    trades = pd.DataFrame(records)
    trades = trades.sort_values(["entry_date", "fly_id"]).reset_index(drop=True)
    return trades


def run_query_rv_backtest(
    *,
    residuals: Dict[str, pd.Series],
    zscores: Dict[str, pd.Series],
    fit_quality: Dict[str, pd.Series],
    weights: Dict[str, pd.DataFrame],
    fly_categories: Dict[str, str],
    entry_snapshots: Dict[str, Dict[pd.Timestamp, Any]],
    residual_stats: Dict[str, pd.DataFrame],
    regime: pd.Series,
    mdp: Any,
    query_factory: Callable[[str, np.ndarray, int], Any],
    frozen_residual_getter: Callable[[str, pd.Timestamp, Any], float],
    config: RVBacktestConfig,
    carry_roll: Optional[Dict[str, pd.Series]] = None,
    stationarity_pvalues: Optional[Dict[str, pd.Series]] = None,
    stationarity_half_lives: Optional[Dict[str, pd.Series]] = None,
    show_progress: bool = True,
) -> RVQueryBacktestResult:
    from BT.data_handler import TimeGrid
    from BT.query_strategy import QueryStrategy
    from BT.triggers import Trigger

    if not residuals:
        empty = pd.Series(dtype=float)
        empty_df = pd.DataFrame()
        return RVQueryBacktestResult(
            query_backtest=None,
            daily_pnl=empty,
            daily_pnl_ccy=empty,
            daily_pnl_by_category=empty_df,
            daily_pnl_by_category_ccy=empty_df,
            cumulative_pnl=empty,
            cumulative_pnl_ccy=empty,
            drawdown=empty,
            trades=pd.DataFrame(),
            metrics={},
        )

    dates = sorted(pd.Timestamp(d).to_pydatetime() for d in residuals[next(iter(residuals))].index)
    action = _RVQuerySignalAction(
        residuals=residuals,
        zscores=zscores,
        fit_quality=fit_quality,
        weights=weights,
        fly_categories=fly_categories,
        entry_snapshots=entry_snapshots,
        residual_stats=residual_stats,
        query_factory=query_factory,
        frozen_residual_getter=frozen_residual_getter,
        config=config,
        regime=regime,
        carry_roll=carry_roll,
        stationarity_pvalues=stationarity_pvalues,
        stationarity_half_lives=stationarity_half_lives,
    )
    trigger = Trigger(trigger_requirements=_AlwaysOnRequirements(), actions=[action])
    strategy = QueryStrategy(name="rv_query_backtest", triggers=[trigger])
    backtest = RVQueryDrivenBacktest(
        time_grid=TimeGrid(dates),
        strategy=strategy,
        mdp=mdp,
        show_progress=show_progress,
    )
    backtest.run()

    mtm_series_ccy = pd.Series(backtest._base.mtm_history).sort_index()
    daily_pnl_ccy = mtm_series_ccy.diff().fillna(mtm_series_ccy)
    normalizer = float(config.trade_belly_bpv) if float(config.trade_belly_bpv) else 1.0
    daily_pnl = daily_pnl_ccy / normalizer
    cumulative_pnl_ccy = mtm_series_ccy
    cumulative_pnl = daily_pnl.cumsum()
    drawdown = cumulative_pnl - cumulative_pnl.cummax()

    cat_ccy = pd.DataFrame(backtest.mtm_history_by_category).T.sort_index()
    if cat_ccy.empty:
        cat_ccy = pd.DataFrame(index=mtm_series_ccy.index)
    cat_ccy = cat_ccy.ffill().fillna(0.0)
    daily_cat_ccy = cat_ccy.diff().fillna(cat_ccy)
    daily_cat = daily_cat_ccy / normalizer

    last_dt = pd.Timestamp(mtm_series_ccy.index[-1]).normalize()
    trades = _finalize_query_trades(backtest, last_dt)
    metrics = _compute_query_metrics(trades, daily_pnl)
    metrics["total_pnl_ccy"] = float(daily_pnl_ccy.sum()) if len(daily_pnl_ccy) else 0.0

    return RVQueryBacktestResult(
        query_backtest=backtest,
        daily_pnl=daily_pnl,
        daily_pnl_ccy=daily_pnl_ccy,
        daily_pnl_by_category=daily_cat,
        daily_pnl_by_category_ccy=daily_cat_ccy,
        cumulative_pnl=cumulative_pnl,
        cumulative_pnl_ccy=cumulative_pnl_ccy,
        drawdown=drawdown,
        trades=trades,
        metrics=metrics,
    )
