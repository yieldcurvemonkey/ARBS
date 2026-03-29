"""JPM RV query-driven backtest engine for USD SOFR butterflies.

Supports two modes:
- mdp=None: lightweight vectorized backtest using approximate P&L
  (frozen entry weights x daily rate changes). Fast for grid search.
- mdp provided: full curve-based MTM via QueryDrivenBacktest.

Key fixes vs. rv_backtest.py:
- Stop-loss uses directional worsening (not absolute zscore growth)
- OOS residual computed via frozen entry betas (EntrySnapshot)

Reference: J.P. Morgan "RV on the EUR swap yield curve" (Apr 2021).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from BT.signals.regression_rv import (
    EntrySnapshot,
    RegressionSignalTable,
    frozen_residual,
)

logger = logging.getLogger(__name__)


@dataclass
class JPMRVBacktestConfig:
    """Configuration for JPM RV backtest engine."""
    # Entry triggers
    entry_min_rsq: float = 0.60
    entry_min_residual_bp: float = 4.0
    entry_min_zscore: float = 1.5
    # Exit triggers
    exit_mean_reversion: bool = True
    exit_stop_loss_sd: float = 2.0
    exit_max_holding_days: int = 22
    # Portfolio rules
    max_concurrent_trades: Optional[int] = None
    no_duplicate_flies: bool = True
    reentry_after_stop: bool = True
    # Sizing
    trade_belly_bpv: float = 100_000.0
    # Costs
    round_trip_cost_bp: float = 0.5


@dataclass
class JPMRVBacktestResult:
    """Output of JPM RV backtest."""
    daily_pnl: pd.Series
    daily_pnl_ccy: pd.Series
    daily_pnl_by_category: pd.DataFrame
    cumulative_pnl: pd.Series
    cumulative_pnl_ccy: pd.Series
    drawdown: pd.Series
    trades: pd.DataFrame
    metrics: Dict[str, float]


def _compute_metrics(trades: pd.DataFrame, daily_pnl: pd.Series) -> Dict[str, float]:
    """Compute summary performance metrics."""
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


# ---------------------------------------------------------------------------
# Lightweight vectorized backtest (mdp=None mode)
# ---------------------------------------------------------------------------

@dataclass
class _VectorizedTrade:
    """Internal trade record for vectorized backtest."""
    fly_id: str
    category: str
    entry_date: pd.Timestamp
    entry_residual: float
    entry_zscore: float
    entry_std: float
    direction: int  # +1 receive belly, -1 pay belly
    snapshot: EntrySnapshot
    exit_date: Optional[pd.Timestamp] = None
    exit_reason: Optional[str] = None
    daily_pnls: list = field(default_factory=list)
    realized_pnl: float = 0.0


def _run_vectorized_backtest(
    signal_table: RegressionSignalTable,
    regime: pd.Series,
    config: JPMRVBacktestConfig,
) -> JPMRVBacktestResult:
    """Run a lightweight vectorized backtest without curve pricing."""
    fly_ids = sorted(signal_table.residuals.keys())
    if not fly_ids:
        empty = pd.Series(dtype=float)
        return JPMRVBacktestResult(
            daily_pnl=empty, daily_pnl_ccy=empty,
            daily_pnl_by_category=pd.DataFrame(),
            cumulative_pnl=empty, cumulative_pnl_ccy=empty,
            drawdown=empty,
            trades=pd.DataFrame(),
            metrics=_compute_metrics(pd.DataFrame(), empty),
        )

    all_dates = signal_table.residuals[fly_ids[0]].index
    categories = sorted(set(signal_table.fly_categories.values()))

    open_trades: List[_VectorizedTrade] = []
    closed_trades: List[_VectorizedTrade] = []
    daily_pnl = pd.Series(0.0, index=all_dates)
    daily_pnl_cat = pd.DataFrame(0.0, index=all_dates, columns=categories) if categories else pd.DataFrame(index=all_dates)

    stopped_yesterday: set = set()

    for i, dt in enumerate(all_dates):
        day_pnl = 0.0
        stopped_today: set = set()

        # --- MTM and exit checks for open trades ---
        still_open: List[_VectorizedTrade] = []
        for trade in open_trades:
            # Approximate daily P&L: change in residual × BPV (in bp)
            fid = trade.fly_id
            if i > 0 and fid in signal_table.fly_series:
                fly_today = signal_table.fly_series[fid].iloc[i]
                fly_prev = signal_table.fly_series[fid].iloc[i - 1]
                body_today = signal_table.body_series[fid].iloc[i]
                body_prev = signal_table.body_series[fid].iloc[i - 1]
                curve_today = signal_table.curve_series[fid].iloc[i]
                curve_prev = signal_table.curve_series[fid].iloc[i - 1]

                # P&L = direction × change_in_fly × 10000 (convert to bp)
                # For butterfly: pay belly = short belly, so direction=-1 means short belly
                # Approximate: frozen_residual change gives the exposure-adjusted P&L
                oos_today = frozen_residual(trade.snapshot, fly_today, body_today, curve_today)
                oos_prev = frozen_residual(trade.snapshot, fly_prev, body_prev, curve_prev)
                trade_daily = trade.direction * (oos_today - oos_prev) * 10_000
            else:
                trade_daily = 0.0
                oos_today = np.nan

            trade.daily_pnls.append(trade_daily)
            day_pnl += trade_daily
            cat = signal_table.fly_categories.get(fid, "unknown")
            if cat in daily_pnl_cat.columns:
                daily_pnl_cat.loc[dt, cat] += trade_daily

            # --- Exit checks ---
            holding_days = len(pd.bdate_range(trade.entry_date, dt)) - 1
            exit_reason = None

            # Compute OOS residual for exit logic
            if fid in signal_table.fly_series:
                fly_t = signal_table.fly_series[fid].iloc[i]
                body_t = signal_table.body_series[fid].iloc[i]
                curve_t = signal_table.curve_series[fid].iloc[i]
                oos_residual = frozen_residual(trade.snapshot, fly_t, body_t, curve_t)
            else:
                oos_residual = np.nan

            # Mean reversion: OOS residual crosses zero
            if config.exit_mean_reversion and np.isfinite(oos_residual):
                if trade.entry_residual > 0 and oos_residual <= 0:
                    exit_reason = "mean_reversion"
                elif trade.entry_residual < 0 and oos_residual >= 0:
                    exit_reason = "mean_reversion"

            # Stop-loss: directional worsening
            if exit_reason is None and np.isfinite(oos_residual) and np.isfinite(trade.entry_std) and trade.entry_std > 0:
                if trade.entry_residual > 0:
                    # We are short (pay belly). Worsening = residual goes MORE positive.
                    stop_level = trade.entry_residual + config.exit_stop_loss_sd * trade.entry_std
                    if oos_residual > stop_level:
                        exit_reason = "stop_loss"
                elif trade.entry_residual < 0:
                    # We are long (receive belly). Worsening = residual goes MORE negative.
                    stop_level = trade.entry_residual - config.exit_stop_loss_sd * trade.entry_std
                    if oos_residual < stop_level:
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

        # --- Entry checks ---
        regime_state = regime.get(dt, np.nan)
        if regime_state != "green":
            daily_pnl.iloc[i] = day_pnl
            stopped_yesterday = stopped_today
            continue

        open_fly_ids = {t.fly_id for t in open_trades}

        candidates: List[Tuple[float, str]] = []
        for fid in fly_ids:
            if config.no_duplicate_flies and fid in open_fly_ids:
                continue
            if not config.reentry_after_stop and fid in (stopped_yesterday | stopped_today):
                continue

            res_val = signal_table.residuals[fid].iloc[i]
            zs_val = signal_table.zscores[fid].iloc[i]
            rsq_val = signal_table.rsq[fid].iloc[i]

            if pd.isna(res_val) or pd.isna(zs_val) or pd.isna(rsq_val):
                continue
            if rsq_val < config.entry_min_rsq:
                continue
            if abs(res_val) * 10_000 < config.entry_min_residual_bp:
                continue
            if abs(zs_val) < config.entry_min_zscore:
                continue

            # Need entry snapshot
            if fid not in signal_table.entry_snapshots:
                continue
            snapshot = signal_table.entry_snapshots[fid].get(dt)
            if snapshot is None:
                continue

            candidates.append((abs(float(zs_val)), fid))

        # Rank by absolute zscore
        candidates.sort(key=lambda x: x[0], reverse=True)

        if config.max_concurrent_trades is not None:
            available = max(0, config.max_concurrent_trades - len(open_trades))
            candidates = candidates[:available]

        for _, fid in candidates:
            res_val = float(signal_table.residuals[fid].iloc[i])
            zs_val = float(signal_table.zscores[fid].iloc[i])
            snapshot = signal_table.entry_snapshots[fid][dt]
            direction = -1 if res_val > 0 else 1

            entry_std = snapshot.residual_std if np.isfinite(snapshot.residual_std) else 0.0

            trade = _VectorizedTrade(
                fly_id=fid,
                category=signal_table.fly_categories.get(fid, "unknown"),
                entry_date=dt,
                entry_residual=res_val,
                entry_zscore=zs_val,
                entry_std=entry_std,
                direction=direction,
                snapshot=snapshot,
            )
            open_trades.append(trade)
            open_fly_ids.add(fid)

        daily_pnl.iloc[i] = day_pnl
        stopped_yesterday = stopped_today

    # Close remaining open trades
    for trade in open_trades:
        trade.exit_date = all_dates[-1]
        trade.exit_reason = "end_of_backtest"
        trade.realized_pnl = sum(trade.daily_pnls) - config.round_trip_cost_bp
        closed_trades.append(trade)

    # Build trades DataFrame
    if closed_trades:
        records = []
        for t in closed_trades:
            records.append({
                "fly_id": t.fly_id,
                "category": t.category,
                "entry_date": t.entry_date,
                "exit_date": t.exit_date,
                "exit_reason": t.exit_reason,
                "entry_residual": t.entry_residual,
                "entry_zscore": t.entry_zscore,
                "direction": t.direction,
                "realized_pnl": t.realized_pnl,
                "holding_days": len(pd.bdate_range(t.entry_date, t.exit_date)) - 1 if t.exit_date else 0,
            })
        trades_df = pd.DataFrame(records).sort_values(["entry_date", "fly_id"]).reset_index(drop=True)
    else:
        trades_df = pd.DataFrame(columns=[
            "fly_id", "category", "entry_date", "exit_date", "exit_reason",
            "entry_residual", "entry_zscore", "direction", "realized_pnl", "holding_days",
        ])

    # Ensure DatetimeIndex for downstream resampling
    if not isinstance(daily_pnl.index, pd.DatetimeIndex):
        daily_pnl.index = pd.to_datetime(daily_pnl.index)
        daily_pnl_cat.index = pd.to_datetime(daily_pnl_cat.index)

    cumulative_pnl = daily_pnl.cumsum()
    drawdown = cumulative_pnl - cumulative_pnl.cummax()
    daily_pnl_ccy = daily_pnl * config.trade_belly_bpv / 10_000
    cumulative_pnl_ccy = daily_pnl_ccy.cumsum()
    metrics = _compute_metrics(trades_df, daily_pnl)

    return JPMRVBacktestResult(
        daily_pnl=daily_pnl,
        daily_pnl_ccy=daily_pnl_ccy,
        daily_pnl_by_category=daily_pnl_cat,
        cumulative_pnl=cumulative_pnl,
        cumulative_pnl_ccy=cumulative_pnl_ccy,
        drawdown=drawdown,
        trades=trades_df,
        metrics=metrics,
    )


# ---------------------------------------------------------------------------
# Query-driven backtest (mdp provided mode)
# ---------------------------------------------------------------------------


class _AlwaysOnRequirements:
    calc_type = "jpm_rv_query"

    def has_triggered(self, state, backtest=None):
        from BT.event import TriggerInfo
        return TriggerInfo(True, info={})


@dataclass
class _JPMRVQuerySignalAction:
    """Signal action for JPM RV query-driven backtest."""
    signal_table: RegressionSignalTable
    config: JPMRVBacktestConfig
    regime: pd.Series
    _trade_seq: int = field(default=0, init=False)
    _last_dt: Optional[pd.Timestamp] = field(default=None, init=False)
    _stopped_today: set = field(default_factory=set, init=False)
    _stopped_yesterday: set = field(default_factory=set, init=False)

    def _roll_date(self, dt: pd.Timestamp) -> None:
        if self._last_dt is None or dt != self._last_dt:
            self._stopped_yesterday = set(self._stopped_today)
            self._stopped_today = set()
            self._last_dt = dt

    @staticmethod
    def _selector(position_id: str):
        return lambda p, position_id=position_id: p.meta.get("rv_position_id") == position_id

    def __call__(self, *, now, backtest, info) -> list:
        from BT.query_order import QueryOrder, UnwindOrder
        from Query.IRSwaps.IRSwapQuery import IRSwapQuery
        from Query.IRSwaps.IRSwapStructure import IRSwapStructure
        from Query.IRSwaps.IRSwapValue import IRSwapValue

        dt = pd.Timestamp(now).normalize()
        # Signal tables are keyed by datetime.date; convert for lookups
        dk = dt.date() if hasattr(dt, "date") else dt
        self._roll_date(dt)
        table = self.signal_table
        config = self.config

        orders: list = []
        current_positions = [
            p for p in backtest.portfolio.iter_positions()
            if p.meta.get("rv_position_id") is not None
        ]

        positions_to_exit: set = set()
        for pos in current_positions:
            meta = pos.meta
            if meta.get("is_hedge"):
                continue
            fid = meta.get("fly_id")
            if fid is None:
                continue

            entry_dt = pd.Timestamp(meta.get("entry_signal_date", pos.opened)).normalize()
            entry_dk = entry_dt.date() if hasattr(entry_dt, "date") else entry_dt
            snapshot_dict = table.entry_snapshots.get(fid, {})
            snapshot = snapshot_dict.get(entry_dk) or snapshot_dict.get(entry_dt)
            if snapshot is None:
                continue

            exit_reason = None
            oos_residual = np.nan

            # Compute OOS residual
            if fid in table.fly_series and dk in table.fly_series[fid].index:
                fly_t = float(table.fly_series[fid].loc[dk])
                body_t = float(table.body_series[fid].loc[dk])
                curve_t = float(table.curve_series[fid].loc[dk])
                oos_residual = frozen_residual(snapshot, fly_t, body_t, curve_t)

            entry_residual = float(meta.get("entry_residual", 0.0))
            entry_std = float(meta.get("entry_residual_std", np.nan))

            # Mean reversion
            if config.exit_mean_reversion and np.isfinite(oos_residual):
                if entry_residual > 0 and oos_residual <= 0:
                    exit_reason = "mean_reversion"
                elif entry_residual < 0 and oos_residual >= 0:
                    exit_reason = "mean_reversion"

            # Stop-loss: directional worsening
            if exit_reason is None and np.isfinite(oos_residual) and np.isfinite(entry_std) and entry_std > 0:
                if entry_residual > 0:
                    stop_level = entry_residual + config.exit_stop_loss_sd * entry_std
                    if oos_residual > stop_level:
                        exit_reason = "stop_loss"
                elif entry_residual < 0:
                    stop_level = entry_residual - config.exit_stop_loss_sd * entry_std
                    if oos_residual < stop_level:
                        exit_reason = "stop_loss"

            # Max holding
            holding_days = len(pd.bdate_range(pos.opened.date(), dt.date())) - 1
            if exit_reason is None and holding_days >= config.exit_max_holding_days:
                exit_reason = "max_hold"

            if exit_reason is None:
                continue

            position_id = meta.get("rv_position_id")
            positions_to_exit.add(position_id)
            orders.append(
                UnwindOrder(
                    timestamp=now,
                    selector=self._selector(position_id),
                    meta={"action": "unwind", "reason": exit_reason, "fee": 0.0},
                )
            )
            if exit_reason == "stop_loss":
                self._stopped_today.add(fid)

        # --- Entry ---
        regime_state = self.regime.get(dk, np.nan)
        if regime_state != "green":
            return orders

        open_after_exit = [
            p for p in current_positions
            if p.meta.get("rv_position_id") not in positions_to_exit
            and not p.meta.get("is_hedge")
        ]
        open_fly_ids = {p.meta.get("fly_id") for p in open_after_exit}

        candidates: list = []
        for fid in sorted(table.residuals):
            if config.no_duplicate_flies and fid in open_fly_ids:
                continue
            if not config.reentry_after_stop and fid in (self._stopped_yesterday | self._stopped_today):
                continue

            res_val = table.residuals[fid].get(dk, np.nan)
            zs_val = table.zscores[fid].get(dk, np.nan)
            rsq_val = table.rsq[fid].get(dk, np.nan)
            if pd.isna(res_val) or pd.isna(zs_val) or pd.isna(rsq_val):
                continue
            if rsq_val < config.entry_min_rsq:
                continue
            if abs(float(res_val)) * 10_000 < config.entry_min_residual_bp:
                continue
            if abs(float(zs_val)) < config.entry_min_zscore:
                continue

            snapshot = table.entry_snapshots.get(fid, {}).get(dk)
            if snapshot is None:
                continue

            candidates.append((abs(float(zs_val)), fid, float(res_val), float(zs_val), snapshot))

        candidates.sort(key=lambda x: x[0], reverse=True)
        if config.max_concurrent_trades is not None:
            available = max(0, config.max_concurrent_trades - len(open_after_exit))
            candidates = candidates[:available]

        for _, fid, res_val, zs_val, snapshot in candidates:
            direction = -1 if res_val > 0 else 1

            # Build butterfly query
            # Parse fly_id to extract tenors
            parts = fid.split("_")
            # Expected format: jpm_rv_{category}_{fwd}_{left}_{belly}_{right}
            left_tenor = parts[-3]
            belly_tenor = parts[-2]
            right_tenor = parts[-1]

            # direction encodes through bpv sign:
            #   direction=+1 (residual < 0, fly cheap) -> positive bpv -> profit when fly increases
            #   direction=-1 (residual > 0, fly rich)  -> negative bpv -> profit when fly decreases
            # FLY NPV change = bpv * Δ(fly_spread), so bpv must be proportional to direction.
            signed_bpv = config.trade_belly_bpv * direction
            query = IRSwapQuery(
                structure=IRSwapStructure.FLY,
                value=IRSwapValue.NPV,
                curve="USD-SOFR-1D",
                structure_kwargs={
                    "front_tenor": left_tenor,
                    "belly_tenor": belly_tenor,
                    "back_tenor": right_tenor,
                    "bpv": signed_bpv,
                },
            )

            stats_row = table.residual_stats.get(fid)
            entry_mean = 0.0
            entry_std = np.nan
            if stats_row is not None and dk in stats_row.index:
                entry_mean = float(stats_row.loc[dk, "mean"])
                entry_std = float(stats_row.loc[dk, "std"])

            self._trade_seq += 1
            trade_id = f"{fid}|{dt.date().isoformat()}|{self._trade_seq}"

            fly_meta = {
                "strategy": "jpm_rv_query",
                "rv_position_id": trade_id,
                "fly_id": fid,
                "category": table.fly_categories.get(fid, "unknown"),
                "entry_signal_date": dt,
                "entry_residual": res_val,
                "entry_zscore": zs_val,
                "entry_residual_mean": entry_mean,
                "entry_residual_std": entry_std,
                "direction": direction,
            }
            orders.append(
                QueryOrder(timestamp=now, query=query, meta=fly_meta)
            )

            # --- Regression beta hedges ---
            # The fly has exposure: fly ~ beta_body * body + beta_curve * curve
            # where body = belly rate, curve = back_rate - front_rate.
            # To isolate the residual, hedge out body and curve exposure
            # with outright swaps sized by the entry betas.
            #
            # The butterfly BPV is signed_bpv on the belly.
            # Body hedge: outright at belly tenor opposing body beta
            # Curve hedge: outright at back/front tenors opposing curve beta
            #   curve = back - front, so curve beta gives:
            #     +beta_curve exposure at back, -beta_curve at front
            #   hedge is the negative of that.
            belly_bpv_abs = abs(config.trade_belly_bpv)

            hedge_base_meta = {
                "strategy": "jpm_rv_query",
                "rv_position_id": trade_id,
                "fly_id": fid,
                "category": table.fly_categories.get(fid, "unknown"),
                "is_hedge": True,
            }

            # Body hedge: strip out the beta_body exposure from the total position
            # Outright NPV change = -bpv * Δrate, so to get -direction*belly_bpv*β_body*Δbody,
            # we need body_bpv = direction * β_body * belly_bpv.
            body_hedge_bpv = direction * snapshot.beta_body * belly_bpv_abs
            if abs(body_hedge_bpv) > 1.0:
                body_query = IRSwapQuery(
                    structure=IRSwapStructure.OUTRIGHT,
                    value=IRSwapValue.NPV,
                    curve="USD-SOFR-1D",
                    tenor=belly_tenor,
                    structure_kwargs={"bpv": body_hedge_bpv},
                )
                orders.append(
                    QueryOrder(timestamp=now, query=body_query, meta={**hedge_base_meta, "hedge_type": "body"})
                )

            # Curve hedge (back leg): strip out beta_curve at back tenor
            curve_back_bpv = direction * snapshot.beta_curve * belly_bpv_abs
            if abs(curve_back_bpv) > 1.0:
                curve_back_query = IRSwapQuery(
                    structure=IRSwapStructure.OUTRIGHT,
                    value=IRSwapValue.NPV,
                    curve="USD-SOFR-1D",
                    tenor=right_tenor,
                    structure_kwargs={"bpv": curve_back_bpv},
                )
                orders.append(
                    QueryOrder(timestamp=now, query=curve_back_query, meta={**hedge_base_meta, "hedge_type": "curve_back"})
                )

            # Curve hedge (front leg): strip out -beta_curve at front tenor
            curve_front_bpv = -direction * snapshot.beta_curve * belly_bpv_abs
            if abs(curve_front_bpv) > 1.0:
                curve_front_query = IRSwapQuery(
                    structure=IRSwapStructure.OUTRIGHT,
                    value=IRSwapValue.NPV,
                    curve="USD-SOFR-1D",
                    tenor=left_tenor,
                    structure_kwargs={"bpv": curve_front_bpv},
                )
                orders.append(
                    QueryOrder(timestamp=now, query=curve_front_query, meta={**hedge_base_meta, "hedge_type": "curve_front"})
                )

        return orders


def run_jpm_rv_backtest(
    *,
    signal_table: RegressionSignalTable,
    regime: pd.Series,
    mdp: Any,
    config: JPMRVBacktestConfig,
    show_progress: bool = False,
) -> JPMRVBacktestResult:
    """Run JPM RV backtest.

    Parameters
    ----------
    signal_table : RegressionSignalTable
        Pre-computed signals from build_jpm_signal_table().
    regime : Series
        "green"/"red" regime indicator.
    mdp : IRSwapsMDP or None
        If None, runs lightweight vectorized backtest.
        If provided, runs full curve-based QueryDrivenBacktest.
    config : JPMRVBacktestConfig
    show_progress : bool

    Returns
    -------
    JPMRVBacktestResult
    """
    if mdp is None:
        return _run_vectorized_backtest(signal_table, regime, config)

    # Full curve-based backtest using QueryDrivenBacktest infrastructure
    from BT.data_handler import TimeGrid
    from BT.query_strategy import QueryStrategy
    from BT.signals.rv_backtest import RVQueryDrivenBacktest, _finalize_query_trades
    from BT.triggers import Trigger

    if not signal_table.residuals:
        empty = pd.Series(dtype=float)
        return JPMRVBacktestResult(
            daily_pnl=empty, daily_pnl_ccy=empty,
            daily_pnl_by_category=pd.DataFrame(),
            cumulative_pnl=empty, cumulative_pnl_ccy=empty,
            drawdown=empty,
            trades=pd.DataFrame(),
            metrics={},
        )

    first_fid = next(iter(signal_table.residuals))
    dates = sorted(pd.Timestamp(d).to_pydatetime() for d in signal_table.residuals[first_fid].index)

    action = _JPMRVQuerySignalAction(
        signal_table=signal_table,
        config=config,
        regime=regime,
    )
    trigger = Trigger(trigger_requirements=_AlwaysOnRequirements(), actions=[action])
    strategy = QueryStrategy(name="jpm_rv_query_backtest", triggers=[trigger])

    backtest = RVQueryDrivenBacktest(
        time_grid=TimeGrid(dates),
        strategy=strategy,
        mdp=mdp,
        show_progress=show_progress,
        progress_desc="JPM RV QUERY BACKTEST",
    )
    backtest.run()

    mtm_series_ccy = pd.Series(backtest._base.mtm_history).sort_index()
    daily_pnl_ccy = mtm_series_ccy.diff().fillna(mtm_series_ccy)
    normalizer = float(config.trade_belly_bpv) if config.trade_belly_bpv else 1.0
    daily_pnl = daily_pnl_ccy / normalizer
    cumulative_pnl = daily_pnl.cumsum()
    cumulative_pnl_ccy = mtm_series_ccy
    drawdown = cumulative_pnl - cumulative_pnl.cummax()

    cat_ccy = pd.DataFrame(backtest.mtm_history_by_category).T.sort_index()
    if cat_ccy.empty:
        cat_ccy = pd.DataFrame(index=mtm_series_ccy.index)
    cat_ccy = cat_ccy.ffill().fillna(0.0)
    daily_cat_ccy = cat_ccy.diff().fillna(cat_ccy)
    daily_cat = daily_cat_ccy / normalizer

    last_dt = pd.Timestamp(mtm_series_ccy.index[-1]).normalize()
    trades = _finalize_query_trades(backtest, last_dt)
    metrics = _compute_metrics(trades, daily_pnl)
    metrics["total_pnl_ccy"] = float(daily_pnl_ccy.sum()) if len(daily_pnl_ccy) else 0.0

    return JPMRVBacktestResult(
        daily_pnl=daily_pnl,
        daily_pnl_ccy=daily_pnl_ccy,
        daily_pnl_by_category=daily_cat,
        cumulative_pnl=cumulative_pnl,
        cumulative_pnl_ccy=cumulative_pnl_ccy,
        drawdown=drawdown,
        trades=trades,
        metrics=metrics,
    )
