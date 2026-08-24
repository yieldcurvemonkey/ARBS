"""Vectorized backtests for fading the strip peak via calendar spreads and butterflies."""
from __future__ import annotations

import numpy as np
import pandas as pd


def backtest_spread(
    strip_df: pd.DataFrame,
    peak_df: pd.DataFrame,
    hold_days: int = 21,
    cost_bp: float = 2.0,
    require_interior: bool = True,
) -> pd.DataFrame:
    """Backtest: sell peak contract, buy peak+1 (one-quarter-out).

    P&L in bp: positive = peak rate fell relative to peak+1 (flattener won).
    Spread P&L = (peak_rate_entry - peak_rate_exit) - (next_rate_entry - next_rate_exit)
               = delta(peak) - delta(next)  [in rate terms, selling peak]

    For a flattener (sell peak rate, buy next rate):
      pnl = -(change in peak rate) + (change in next rate)
          = (peak_rate_entry - peak_rate_exit) - (next_rate_entry - next_rate_exit)
    Wait — sell peak rate means RECEIVE peak rate at entry, PAY at exit.
    If peak rate falls, we profit (entered high, exited low).
    pnl_peak_leg = (entry_peak - exit_peak) [positive when rate falls]
    pnl_next_leg = -(entry_next - exit_next) = (exit_next - entry_next) [we bought next]
    total = (entry_peak - exit_peak) + (exit_next - entry_next)
    """
    cols = list(strip_df.columns)
    records = []

    for i, (date, row) in enumerate(peak_df.iterrows()):
        if require_interior and not row["is_interior"]:
            continue
        peak_idx = int(row["peak_idx"])
        if peak_idx >= len(cols) - 1:
            continue  # no next contract

        exit_i = i + hold_days
        if exit_i >= len(strip_df):
            continue

        peak_sym = cols[peak_idx]
        next_sym = cols[peak_idx + 1]
        exit_date = strip_df.index[exit_i]

        entry_peak = strip_df.at[date, peak_sym]
        exit_peak = strip_df.at[exit_date, peak_sym]
        entry_next = strip_df.at[date, next_sym]
        exit_next = strip_df.at[exit_date, next_sym]

        pnl = (entry_peak - exit_peak) + (exit_next - entry_next)
        pnl_bp = pnl * 100 - cost_bp

        records.append({
            "entry_date": date,
            "exit_date": exit_date,
            "peak_contract": peak_sym,
            "next_contract": next_sym,
            "entry_spread_bp": (entry_peak - entry_next) * 100,
            "exit_spread_bp": (exit_peak - exit_next) * 100,
            "pnl_bp": pnl_bp,
            "prominence": row["prominence"],
        })

    return pd.DataFrame(records)


def backtest_butterfly(
    strip_df: pd.DataFrame,
    peak_df: pd.DataFrame,
    hold_days: int = 21,
    cost_bp: float = 4.0,
    require_interior: bool = True,
) -> pd.DataFrame:
    """Backtest: buy peak-1, sell 2x peak, buy peak+1.

    Butterfly P&L in bp (selling the peak curvature):
      pnl = 1*(prev_change) - 2*(peak_change) + 1*(next_change)
      where change = exit_rate - entry_rate (positive = rate rose)

    We are SHORT the peak and LONG the wings in rate terms.
    If the peak rate falls more than the wings, we profit.
    pnl = (entry_fly - exit_fly) where fly = 2*peak - prev - next
    """
    cols = list(strip_df.columns)
    records = []

    for i, (date, row) in enumerate(peak_df.iterrows()):
        if require_interior and not row["is_interior"]:
            continue
        peak_idx = int(row["peak_idx"])
        if peak_idx == 0 or peak_idx >= len(cols) - 1:
            continue

        exit_i = i + hold_days
        if exit_i >= len(strip_df):
            continue

        prev_sym = cols[peak_idx - 1]
        peak_sym = cols[peak_idx]
        next_sym = cols[peak_idx + 1]
        exit_date = strip_df.index[exit_i]

        entry_fly = (
            2 * strip_df.at[date, peak_sym]
            - strip_df.at[date, prev_sym]
            - strip_df.at[date, next_sym]
        )
        exit_fly = (
            2 * strip_df.at[exit_date, peak_sym]
            - strip_df.at[exit_date, prev_sym]
            - strip_df.at[exit_date, next_sym]
        )
        pnl = (entry_fly - exit_fly) * 100 - cost_bp

        records.append({
            "entry_date": date,
            "exit_date": exit_date,
            "peak_contract": peak_sym,
            "entry_fly_bp": entry_fly * 100,
            "exit_fly_bp": exit_fly * 100,
            "pnl_bp": pnl,
            "prominence": row["prominence"],
        })

    return pd.DataFrame(records)


def summary_stats(bt_df: pd.DataFrame) -> dict:
    """Compute summary statistics for a backtest result DataFrame."""
    if bt_df.empty:
        return {"n_trades": 0, "hit_rate": 0, "avg_pnl_bp": 0, "sharpe": 0, "total_pnl_bp": 0}
    pnl = bt_df["pnl_bp"]
    return {
        "n_trades": len(pnl),
        "hit_rate": (pnl > 0).mean(),
        "avg_pnl_bp": pnl.mean(),
        "sharpe": pnl.mean() / pnl.std() * np.sqrt(252 / max(1, len(pnl))) if pnl.std() > 0 else 0,
        "total_pnl_bp": pnl.sum(),
        "median_pnl_bp": pnl.median(),
        "max_dd_bp": (pnl.cumsum() - pnl.cumsum().cummax()).min(),
    }
