"""
Performance analytics and visualization for OBI backtest results.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

from OBI.backtest import BacktestResult, TradeRecord


def build_trades_df(trades: List[TradeRecord]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    records = []
    for t in trades:
        records.append({
            "contract_idx": t.contract_idx,
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "side": t.side,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "quantity": t.quantity,
            "pnl": t.pnl,
            "fees": t.fees,
            "net_pnl": t.net_pnl,
            "obi_at_entry": t.obi_at_entry,
            "signal_strength": t.signal_strength,
            "outcome": t.outcome,
            "won": t.won,
        })
    return pd.DataFrame(records)


def plot_tearsheet(result: BacktestResult, title: str = "OBI Strategy Tearsheet"):
    """Generate a 6-panel tearsheet for an OBI backtest result."""
    trades_df = build_trades_df(result.trades)
    if trades_df.empty:
        print("No trades to plot.")
        return

    fig, axes = plt.subplots(3, 2, figsize=(16, 14))
    fig.suptitle(title, fontsize=16, fontweight="bold")

    # 1. Equity curve
    ax = axes[0, 0]
    ax.plot(result.equity_curve.values, color="steelblue", linewidth=1.5)
    ax.axhline(result.config.capital, color="gray", linestyle="--", alpha=0.5)
    ax.set_title("Equity Curve")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Capital ($)")
    ax.grid(True, alpha=0.3)

    # 2. Drawdown
    ax = axes[0, 1]
    eq = result.equity_curve
    cummax = eq.cummax()
    dd = (eq - cummax) / cummax.clip(lower=1e-8) * 100
    ax.fill_between(range(len(dd)), dd.values, color="salmon", alpha=0.6)
    ax.set_title(f"Drawdown (max: {result.metrics.get('max_drawdown_pct', 0):.2f}%)")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.3)

    # 3. PnL distribution
    ax = axes[1, 0]
    pnls = trades_df["net_pnl"]
    ax.hist(pnls, bins=50, color="steelblue", alpha=0.7, edgecolor="white")
    ax.axvline(0, color="red", linestyle="--")
    ax.axvline(pnls.mean(), color="green", linestyle="--", label=f"Mean: {pnls.mean():.3f}")
    ax.set_title("PnL Distribution")
    ax.set_xlabel("Net PnL per trade")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 4. Win rate by OBI bucket
    ax = axes[1, 1]
    trades_df["obi_bucket"] = pd.cut(trades_df["obi_at_entry"], bins=10)
    win_by_bucket = trades_df.groupby("obi_bucket", observed=True)["won"].mean()
    win_by_bucket.plot(kind="bar", ax=ax, color="steelblue", alpha=0.7)
    ax.axhline(0.5, color="red", linestyle="--", alpha=0.5)
    ax.set_title("Win Rate by OBI Bucket")
    ax.set_xlabel("OBI at Entry")
    ax.set_ylabel("Win Rate")
    ax.tick_params(axis="x", rotation=45)
    ax.grid(True, alpha=0.3)

    # 5. Cumulative PnL by side
    ax = axes[2, 0]
    for side in ["YES", "NO"]:
        mask = trades_df["side"] == side
        if mask.any():
            cum = trades_df.loc[mask, "net_pnl"].cumsum()
            ax.plot(cum.values, label=side, linewidth=1.5)
    ax.set_title("Cumulative PnL by Side")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Cumulative PnL ($)")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 6. Metrics summary table
    ax = axes[2, 1]
    ax.axis("off")
    m = result.metrics
    rows = [
        ["Total Trades", f"{m.get('n_trades', 0)}"],
        ["Win Rate", f"{m.get('win_rate', 0):.2%}"],
        ["Sharpe Ratio", f"{m.get('sharpe', 0):.3f}"],
        ["Sortino Ratio", f"{m.get('sortino', 0):.3f}"],
        ["Total PnL", f"${m.get('total_pnl', 0):.2f}"],
        ["ROI", f"{m.get('roi_pct', 0):.2f}%"],
        ["Max Drawdown", f"{m.get('max_drawdown_pct', 0):.2f}%"],
        ["Profit Factor", f"{m.get('profit_factor', 0):.3f}"],
        ["Avg Win", f"${m.get('avg_win', 0):.4f}"],
        ["Avg Loss", f"${m.get('avg_loss', 0):.4f}"],
        ["Expectancy", f"${m.get('expectancy', 0):.4f}"],
        ["Win Streak", f"{m.get('win_streak', 0)}"],
        ["Loss Streak", f"{m.get('loss_streak', 0)}"],
        ["Total Fees", f"${m.get('total_fees', 0):.2f}"],
    ]
    table = ax.table(cellText=rows, colLabels=["Metric", "Value"],
                     loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.4)
    ax.set_title("Performance Summary", pad=20)

    plt.tight_layout()
    return fig


def plot_grid_search_heatmap(
    grid_df: pd.DataFrame,
    x_param: str,
    y_param: str,
    metric: str = "sharpe",
    title: Optional[str] = None,
):
    """Plot heatmap of grid search results for two parameters."""
    pivot = grid_df.pivot_table(values=metric, index=y_param, columns=x_param, aggfunc="mean")

    fig, ax = plt.subplots(figsize=(12, 8))
    sns.heatmap(
        pivot, annot=True, fmt=".3f", cmap="RdYlGn", center=0,
        ax=ax, linewidths=0.5,
    )
    ax.set_title(title or f"Grid Search: {metric} by {x_param} vs {y_param}")
    plt.tight_layout()
    return fig


def plot_grid_comparison(
    grid_df: pd.DataFrame,
    param: str,
    metrics: List[str] = None,
):
    """Plot how a single parameter affects multiple metrics."""
    if metrics is None:
        metrics = ["sharpe", "win_rate", "total_pnl", "max_drawdown_pct"]

    valid = grid_df.dropna(subset=["sharpe"])
    n_metrics = len(metrics)
    fig, axes = plt.subplots(1, n_metrics, figsize=(5 * n_metrics, 4))
    if n_metrics == 1:
        axes = [axes]

    for ax, m in zip(axes, metrics):
        agg = valid.groupby(param)[m].mean()
        agg.plot(kind="bar", ax=ax, color="steelblue", alpha=0.7)
        ax.set_title(m)
        ax.set_xlabel(param)
        ax.grid(True, alpha=0.3)

    fig.suptitle(f"Impact of {param}", fontsize=14, fontweight="bold")
    plt.tight_layout()
    return fig


def format_best_configs(best: Dict[str, pd.Series]) -> str:
    """Format best configs into a readable string."""
    lines = []
    for name, row in best.items():
        lines.append(f"\n{'='*50}")
        lines.append(f" {name.upper()}")
        lines.append(f"{'='*50}")
        for k, v in row.items():
            if isinstance(v, float):
                lines.append(f"  {k}: {v:.4f}")
            else:
                lines.append(f"  {k}: {v}")
    return "\n".join(lines)
