"""Vectorized backtest engine and grid search for PCA momentum research.

Designed for fast iteration during grid search: the entire backtest for one
parameter combination runs in ~1ms once signals are computed (no pricer
rebuilds, no event loop). Use QueryDrivenBacktest for production fidelity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from itertools import product as itertools_product
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

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
    bpv: float = 1.0,
    tc_bps: float = 0.0,
    annualization_factor: float = 252.0,
) -> VectorizedResult:
    """Run a vectorized backtest from signal and rate time series.

    P&L model: position[t] = signal[t-1], pnl[t] = position[t] * Δrate[t] * bpv * 100.
    Transaction costs deducted on every position change.

    Parameters
    ----------
    rate_series : pd.Series
        Rate time series (e.g., swap rates in %).
    signals : pd.Series
        Trading signals: +1 (receive / long), -1 (pay / short), 0 or NaN (flat).
    bpv : float
        Basis point value per unit signal (dollar P&L per 1bp move).
    tc_bps : float
        Round-trip transaction cost in basis points per trade.
    annualization_factor : float
        For Sharpe: 252 (daily), 252*16 (30min with 8h sessions), etc.

    Returns
    -------
    VectorizedResult
    """
    aligned = pd.DataFrame({"rate": rate_series, "signal": signals}).dropna(subset=["rate"])
    aligned["signal"] = aligned["signal"].fillna(0)

    rate_changes = aligned["rate"].diff()
    position = aligned["signal"].shift(1).fillna(0)

    # P&L: position * rate change (in %) * bpv * 100 (convert % to bps)
    pnl_per_period = position * rate_changes * bpv * 100

    # Transaction costs on position changes
    position_changes = position.diff().fillna(0).abs()
    tc_per_period = position_changes * tc_bps * bpv

    net_pnl = pnl_per_period - tc_per_period
    cum_pnl = net_pnl.cumsum()

    total_return = float(cum_pnl.iloc[-1]) if len(cum_pnl) > 0 else 0.0

    mean_ret = net_pnl.mean()
    std_ret = net_pnl.std()
    sharpe = (mean_ret / std_ret * np.sqrt(annualization_factor)) if std_ret > 0 else 0.0

    running_max = cum_pnl.cummax()
    drawdown = cum_pnl - running_max
    max_dd = float(drawdown.min()) if len(drawdown) > 0 else 0.0

    trades = int((position.diff().abs() > 0).sum())

    winning_periods = net_pnl[position != 0]
    win_rate = float((winning_periods > 0).sum() / max(1, len(winning_periods)))

    if trades > 0:
        position_runs = (position != position.shift()).cumsum()
        avg_hold = float(position.groupby(position_runs).count().mean())
    else:
        avg_hold = 0.0

    return VectorizedResult(
        pnl_series=cum_pnl,
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_dd,
        n_trades=trades,
        win_rate=win_rate,
        avg_holding_periods=avg_hold,
        signal_series=aligned["signal"],
    )


def grid_search(
    rate_df: pd.DataFrame,
    param_grid: Dict[str, List[Any]],
    contracts: Optional[List[str]] = None,
    bpv: float = 1.0,
    tc_bps: float = 0.0,
    annualization_factor: float = 252.0,
    min_observations: int = 500,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    """Grid search over PCA momentum hyperparameters and contract selection.

    Parameters
    ----------
    rate_df : pd.DataFrame
        Rate time series DataFrame (timestamps × contracts).
    param_grid : dict
        Keys are PCAMomentumConfig field names, values are lists to search.
        Example: {"n_components": [2, 3], "classifier_C": [0.1, 1.0, 10.0]}
    contracts : list of str, optional
        Column names from rate_df to search over. If None, searches all columns.
    bpv, tc_bps, annualization_factor : float
        Backtest parameters.
    min_observations : int
        Minimum non-NaN observations required per contract.
    show_tqdm : bool
        Show progress bar.

    Returns
    -------
    pd.DataFrame
        One row per (contract, param_combo) with backtest metrics.
    """
    from BT.signals.pca_momentum import (
        PCAMomentumConfig,
        fit_pca_momentum,
        generate_labels,
        generate_ma_features,
        predict_signals,
    )

    if contracts is None:
        contracts = list(rate_df.columns)

    # Build parameter combos
    param_keys = sorted(param_grid.keys())
    param_values = [param_grid[k] for k in param_keys]
    combos = list(itertools_product(*param_values))

    total = len(contracts) * len(combos)
    results_rows: List[Dict[str, Any]] = []

    iterator = _make_iterator(contracts, combos, total, show_tqdm)

    for contract, combo in iterator:
        series = rate_df[contract].dropna()
        if len(series) < min_observations:
            continue

        params = dict(zip(param_keys, combo))
        config = PCAMomentumConfig(**params)

        row: Dict[str, Any] = {"contract": contract, **params}

        try:
            features = generate_ma_features(
                series,
                ewma_short_spans=config.ewma_short_spans,
                ewma_long_spans=config.ewma_long_spans,
            )
            labels = generate_labels(
                series,
                forward_window=config.label_forward_window,
                z_lookback=config.label_lookback,
                z_threshold=config.label_z_threshold,
            )
            pipeline, _ = fit_pca_momentum(features, labels, config)
            sigs = predict_signals(pipeline, features, smoothing=config.signal_smoothing)

            result = vectorized_backtest(
                series, sigs,
                bpv=bpv, tc_bps=tc_bps,
                annualization_factor=annualization_factor,
            )

            pca_step = pipeline.named_steps["pca"]
            row["total_return"] = result.total_return
            row["sharpe"] = result.sharpe
            row["max_drawdown"] = result.max_drawdown
            row["n_trades"] = result.n_trades
            row["win_rate"] = result.win_rate
            row["avg_hold"] = result.avg_holding_periods
            row["pca_var_explained"] = sum(pca_step.explained_variance_ratio_)

        except Exception as e:
            logger.warning("Grid search failed for %s / %s: %s", contract, params, e)
            row["error"] = str(e)

        results_rows.append(row)

    return pd.DataFrame(results_rows)


def _make_iterator(contracts, combos, total, show_tqdm):
    """Build an iterator over (contract, combo) pairs with optional tqdm."""
    pairs = [(c, combo) for c in contracts for combo in combos]
    if show_tqdm:
        try:
            from tqdm.auto import tqdm
            return tqdm(pairs, total=total, desc="Grid search")
        except ImportError:
            pass
    return pairs
