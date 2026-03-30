"""Compatibility vectorized backtest helpers built on the walk-forward pipeline."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import product as itertools_product
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class VectorizedResult:
    """Container for a single vectorized backtest run."""

    pnl_series: pd.Series
    total_return: float
    sharpe: float
    max_drawdown: float
    n_trades: int
    win_rate: float
    avg_holding_periods: float
    signal_series: pd.Series
    config_label: str = ""


def vectorized_backtest(
    rate_series: pd.Series,
    signals: pd.Series,
    *,
    bpv: float = 1.0,
    tc_bps: float = 0.0,
    annualization_factor: Optional[float] = None,
) -> VectorizedResult:
    """Run a vectorized receiver-long backtest for one contract."""
    aligned = pd.DataFrame({"rate": rate_series, "signal": signals}).dropna(subset=["rate"])
    aligned["signal"] = aligned["signal"].fillna(0.0).astype(float).clip(-1.0, 1.0)

    delta_rate = aligned["rate"].diff().fillna(0.0)
    position = aligned["signal"].shift(1).fillna(0.0)
    gross_pnl = -position * delta_rate * float(bpv) * 100.0

    trade_sides = aligned["signal"].diff().abs()
    if len(trade_sides):
        trade_sides.iloc[0] = abs(float(aligned["signal"].iloc[0]))
    costs = trade_sides.fillna(0.0) * float(tc_bps) * float(bpv)
    net_pnl = gross_pnl - costs
    cumulative = net_pnl.cumsum()

    ann_factor = annualization_factor or _annualization_factor(aligned.index)
    std = float(net_pnl.std())
    sharpe = float(net_pnl.mean() / std * np.sqrt(ann_factor)) if std > 0.0 else 0.0
    drawdown = cumulative - cumulative.cummax()

    active_mask = position != 0.0
    win_rate = float((net_pnl[active_mask] > 0.0).mean()) if active_mask.any() else 0.0
    avg_holding = _average_holding_period(aligned["signal"])

    return VectorizedResult(
        pnl_series=cumulative,
        total_return=float(cumulative.iloc[-1]) if len(cumulative) else 0.0,
        sharpe=sharpe,
        max_drawdown=float(drawdown.min()) if len(drawdown) else 0.0,
        n_trades=int(trade_sides.sum()),
        win_rate=win_rate,
        avg_holding_periods=avg_holding,
        signal_series=aligned["signal"],
    )


def grid_search(
    rate_df: pd.DataFrame,
    param_grid: Dict[str, List[Any]],
    contracts: Optional[List[str]] = None,
    *,
    bpv: float = 1.0,
    tc_bps: float = 0.0,
    annualization_factor: Optional[float] = None,
    min_observations: int = 500,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """Search walk-forward PCA momentum hyperparameters without leakage."""
    from BT.signals.pca_momentum import PCAMomentumConfig, walk_forward_pca_momentum

    contracts = contracts or list(rate_df.columns)
    param_keys = sorted(param_grid)
    param_values = [param_grid[key] for key in param_keys]
    combos = list(itertools_product(*param_values))
    pairs = [(contract, combo) for contract in contracts for combo in combos]
    iterator = _make_iterator(pairs, show_tqdm)

    rows: list[dict[str, Any]] = []
    for contract, combo in iterator:
        series = rate_df[contract].dropna()
        if len(series) < min_observations:
            continue

        params = dict(zip(param_keys, combo))
        cfg = PCAMomentumConfig(**params)
        row: dict[str, Any] = {"contract": contract, **params}

        try:
            walk_forward = walk_forward_pca_momentum(series.to_frame(contract), config=cfg)
            backtest = vectorized_backtest(
                rate_series=series,
                signals=walk_forward.signal_panel[contract],
                bpv=bpv,
                tc_bps=tc_bps,
                annualization_factor=annualization_factor,
            )
            row.update(
                {
                    "total_return": backtest.total_return,
                    "sharpe": backtest.sharpe,
                    "max_drawdown": backtest.max_drawdown,
                    "n_trades": backtest.n_trades,
                    "win_rate": backtest.win_rate,
                    "avg_hold": backtest.avg_holding_periods,
                }
            )
        except Exception as exc:
            logger.warning("Grid search failed for %s / %s: %s", contract, params, exc)
            row["error"] = str(exc)

        rows.append(row)

    return pd.DataFrame(rows)


def _make_iterator(pairs, show_tqdm):
    if show_tqdm:
        try:
            from tqdm import tqdm

            return tqdm(pairs, desc="PCA momentum grid search")
        except Exception:
            pass
    return pairs


def _annualization_factor(index: pd.Index) -> float:
    if len(index) == 0:
        return 252.0

    session_keys = pd.Series([_session_key(ts) for ts in index], index=index)
    counts = session_keys.groupby(session_keys).size()
    bars_per_session = float(counts.median()) if not counts.empty else 1.0
    return max(1.0, bars_per_session) * 252.0


def _average_holding_period(signal_series: pd.Series) -> float:
    shifted = signal_series.fillna(0.0)
    changes = shifted.ne(shifted.shift())
    runs = changes.cumsum()
    active = shifted != 0.0
    if not active.any():
        return 0.0
    return float(active.groupby(runs).sum()[active.groupby(runs).sum() > 0].mean())


def _session_key(timestamp: Any):
    stamp = pd.Timestamp(timestamp)
    if stamp.tzinfo is None:
        return stamp.date()
    stamp = stamp.tz_convert("America/Chicago")
    if stamp.hour >= 17:
        return (stamp + pd.Timedelta(days=1)).date()
    return stamp.date()
