"""
OBI Event Contracts Grid Search
================================
Comprehensive parameter optimization for order book imbalance strategy
on binary prediction market contracts (Polymarket 5m BTC, Kalshi 15m BTC).

Usage:
    conda run -n stir python notebooks/backtests/obi_event_contracts_grid_search.py

Outputs:
    - Grid search CSV results
    - Best config reports for each objective
    - Heatmap visualizations
"""
from __future__ import annotations

import itertools
import os
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OBI.config import (
    BacktestConfig,
    POLYMARKET_5M_BTC,
    KALSHI_15M_BTC,
    build_config,
)
from OBI.backtest import (
    BacktestResult,
    fetch_btc_prices,
    run_backtest,
    run_grid_search,
    select_best_configs,
)
from OBI.tearsheet import (
    plot_tearsheet,
    plot_grid_search_heatmap,
    plot_grid_comparison,
    format_best_configs,
    build_trades_df,
)

OUT_DIR = Path(__file__).resolve().parent / "obi_grid_results"
OUT_DIR.mkdir(exist_ok=True)

# ===========================================================================
# 1. Fetch BTC price data (shared across all grid runs)
# ===========================================================================
print("=" * 60)
print("OBI EVENT CONTRACTS GRID SEARCH")
print("=" * 60)

print("\n[1/6] Fetching BTC price data...")
t0 = time.time()

DATA_START = "2025-05-15"
DATA_END = "2025-06-01"
USE_SYNTHETIC = os.environ.get("OBI_SYNTHETIC", "0") == "1"

if USE_SYNTHETIC:
    print(f"  Using synthetic data ({DATA_START} to {DATA_END})...")
    idx = pd.date_range(DATA_START, DATA_END, freq="1min", tz="UTC")
    np.random.seed(42)
    returns = np.random.normal(0, 0.0003, len(idx))
    prices = 105000 * np.exp(np.cumsum(returns))
    btc_5m = pd.DataFrame({
        "open": prices,
        "high": prices * (1 + np.abs(np.random.normal(0, 0.0002, len(idx)))),
        "low": prices * (1 - np.abs(np.random.normal(0, 0.0002, len(idx)))),
        "close": prices * (1 + np.random.normal(0, 0.0001, len(idx))),
        "volume": np.random.lognormal(10, 1, len(idx)),
    }, index=idx)
    print(f"  Generated {len(btc_5m)} synthetic 1-min candles")
else:
    try:
        btc_5m = fetch_btc_prices(
            start=DATA_START,
            end=DATA_END,
            source="ccxt",
            exchange="binance",
            timeframe="1m",
        )
        print(f"  Fetched {len(btc_5m)} 1-min candles from Binance ({time.time()-t0:.1f}s)")
    except Exception as e:
        print(f"  ccxt/Binance failed ({e}), falling back to synthetic...")
        idx = pd.date_range(DATA_START, DATA_END, freq="1min", tz="UTC")
        np.random.seed(42)
        returns = np.random.normal(0, 0.0003, len(idx))
        prices = 105000 * np.exp(np.cumsum(returns))
        btc_5m = pd.DataFrame({
            "open": prices,
            "high": prices * (1 + np.abs(np.random.normal(0, 0.0002, len(idx)))),
            "low": prices * (1 - np.abs(np.random.normal(0, 0.0002, len(idx)))),
            "close": prices * (1 + np.random.normal(0, 0.0001, len(idx))),
            "volume": np.random.lognormal(10, 1, len(idx)),
        }, index=idx)
        print(f"  Generated {len(btc_5m)} synthetic 1-min candles")

# ===========================================================================
# 2. Polymarket 5-min BTC grid search
# ===========================================================================
print("\n[2/6] Running Polymarket 5-min BTC grid search...")

poly_base = build_config(POLYMARKET_5M_BTC, {"start_date": DATA_START, "end_date": DATA_END})
kalshi_base = build_config(KALSHI_15M_BTC, {"start_date": DATA_START, "end_date": DATA_END})

POLY_GRID = {
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [10, 20, 30, 45, 60],
    "obi_depth_levels": [3, 5, 8, 10],
    "obi_variant": ["raw", "normalized", "weighted"],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20, 0.25],
    "sizing_mode": ["fixed", "scaled"],
}

n_poly = 1
for v in POLY_GRID.values():
    n_poly *= len(v)
print(f"  Parameter space: {n_poly:,} combinations")
print(f"  Running...")

t0 = time.time()
poly_results = run_grid_search(
    base_config=poly_base,
    grid=POLY_GRID,
    btc_prices=btc_5m,
    progress=True,
)
poly_time = time.time() - t0
print(f"  Completed {len(poly_results)} runs in {poly_time:.1f}s ({poly_time/len(poly_results)*1000:.0f}ms/run)")

poly_csv = OUT_DIR / "polymarket_5m_btc_grid.csv"
poly_results.to_csv(poly_csv, index=False)
print(f"  Saved: {poly_csv}")

# ===========================================================================
# 3. Kalshi 15-min BTC grid search
# ===========================================================================
print("\n[3/6] Running Kalshi 15-min BTC grid search...")

KALSHI_GRID = {
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [30, 60, 90, 120, 180],
    "obi_depth_levels": [3, 5, 8, 10],
    "obi_variant": ["raw", "normalized", "weighted"],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20, 0.25],
    "sizing_mode": ["fixed", "scaled"],
}

n_kalshi = 1
for v in KALSHI_GRID.values():
    n_kalshi *= len(v)
print(f"  Parameter space: {n_kalshi:,} combinations")
print(f"  Running...")

t0 = time.time()
kalshi_results = run_grid_search(
    base_config=kalshi_base,
    grid=KALSHI_GRID,
    btc_prices=btc_5m,
    progress=True,
)
kalshi_time = time.time() - t0
print(f"  Completed {len(kalshi_results)} runs in {kalshi_time:.1f}s ({kalshi_time/len(kalshi_results)*1000:.0f}ms/run)")

kalshi_csv = OUT_DIR / "kalshi_15m_btc_grid.csv"
kalshi_results.to_csv(kalshi_csv, index=False)
print(f"  Saved: {kalshi_csv}")

# ===========================================================================
# 4. Select best configs
# ===========================================================================
print("\n[4/6] Selecting best configurations...")

for label, df, base_cfg in [
    ("Polymarket 5m", poly_results, POLYMARKET_5M_BTC),
    ("Kalshi 15m", kalshi_results, KALSHI_15M_BTC),
]:
    print(f"\n  --- {label} ---")
    best = select_best_configs(df)
    if not best:
        print(f"  No valid results for {label}")
        continue

    report = format_best_configs(best)
    print(report)

    report_path = OUT_DIR / f"{label.lower().replace(' ', '_')}_best_configs.txt"
    with open(report_path, "w") as f:
        f.write(f"Best Configs: {label}\n")
        f.write(f"Generated: {pd.Timestamp.now()}\n")
        f.write(report)
    print(f"\n  Saved: {report_path}")

# ===========================================================================
# 5. Generate visualizations
# ===========================================================================
print("\n[5/6] Generating visualizations...")

for label, df in [("polymarket_5m", poly_results), ("kalshi_15m", kalshi_results)]:
    valid = df.dropna(subset=["sharpe"])
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]

    if valid.empty:
        print(f"  Skipping {label}: no valid results")
        continue

    # --- Heatmap: threshold vs signal_mode ---
    try:
        fig = plot_grid_search_heatmap(
            valid, "entry_threshold", "signal_mode", "sharpe",
            title=f"{label}: Sharpe by Threshold & Signal Mode",
        )
        fig.savefig(OUT_DIR / f"{label}_heatmap_threshold_mode.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        print(f"  Heatmap error ({label}): {e}")

    # --- Heatmap: threshold vs obi_depth ---
    try:
        fig = plot_grid_search_heatmap(
            valid, "entry_threshold", "obi_depth_levels", "sharpe",
            title=f"{label}: Sharpe by Threshold & Depth",
        )
        fig.savefig(OUT_DIR / f"{label}_heatmap_threshold_depth.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        print(f"  Heatmap error ({label}): {e}")

    # --- Heatmap: threshold vs predictive power ---
    try:
        fig = plot_grid_search_heatmap(
            valid, "entry_threshold", "sim_obi_predictive_power", "win_rate",
            title=f"{label}: Win Rate by Threshold & Predictive Power",
        )
        fig.savefig(OUT_DIR / f"{label}_heatmap_threshold_pp.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as e:
        print(f"  Heatmap error ({label}): {e}")

    # --- Parameter impact plots ---
    for param in ["entry_threshold", "signal_mode", "obi_variant", "obi_depth_levels"]:
        if param in valid.columns:
            try:
                fig = plot_grid_comparison(valid, param)
                fig.savefig(OUT_DIR / f"{label}_impact_{param}.png", dpi=150, bbox_inches="tight")
                plt.close(fig)
            except Exception:
                pass

    # --- Best config tearsheet ---
    best = select_best_configs(valid)
    if "best_sharpe" in best:
        row = best["best_sharpe"]
        param_cols = [c for c in POLY_GRID.keys() if c in row.index]
        overrides = {c: row[c] for c in param_cols}
        base = POLYMARKET_5M_BTC if "polymarket" in label else KALSHI_15M_BTC
        cfg = build_config(base, overrides)
        try:
            result = run_backtest(cfg, btc_prices=btc_5m)
            fig = plot_tearsheet(result, title=f"{label}: Best Sharpe Config Tearsheet")
            if fig:
                fig.savefig(OUT_DIR / f"{label}_best_sharpe_tearsheet.png", dpi=150, bbox_inches="tight")
                plt.close(fig)
        except Exception as e:
            print(f"  Tearsheet error ({label}): {e}")

    print(f"  {label} visualizations saved")

# ===========================================================================
# 6. Summary report
# ===========================================================================
print("\n[6/6] Summary Report")
print("=" * 60)

for label, df in [("Polymarket 5m BTC", poly_results), ("Kalshi 15m BTC", kalshi_results)]:
    valid = df.dropna(subset=["sharpe"])
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]

    if valid.empty:
        print(f"\n{label}: No valid results")
        continue

    print(f"\n{label}:")
    print(f"  Total configs tested: {len(valid):,}")
    print(f"  Profitable configs: {(valid['total_pnl'] > 0).sum():,} ({(valid['total_pnl'] > 0).mean():.1%})")
    print(f"  Sharpe > 0: {(valid['sharpe'] > 0).sum():,} ({(valid['sharpe'] > 0).mean():.1%})")
    print(f"  Sharpe > 1: {(valid['sharpe'] > 1).sum():,}")
    print(f"  Sharpe > 2: {(valid['sharpe'] > 2).sum():,}")
    print(f"  Win rate range: {valid['win_rate'].min():.2%} — {valid['win_rate'].max():.2%}")
    print(f"  Sharpe range: {valid['sharpe'].min():.3f} — {valid['sharpe'].max():.3f}")
    print(f"  Max PnL: ${valid['total_pnl'].max():.2f}")
    print(f"  Max drawdown range: {valid['max_drawdown_pct'].min():.2f}% — {valid['max_drawdown_pct'].max():.2f}%")

    print(f"\n  Top 5 by Sharpe:")
    top5 = valid.nlargest(5, "sharpe")
    param_cols = [c for c in df.columns if c not in [
        "n_trades", "n_wins", "n_losses", "win_rate", "total_pnl", "roi_pct",
        "sharpe", "sortino", "max_drawdown_pct", "calmar", "profit_factor",
        "avg_win", "avg_loss", "avg_entry_price", "total_fees", "win_streak",
        "loss_streak", "avg_pnl_per_trade", "expectancy", "error",
        "balanced_score",
    ]]
    for idx, row in top5.iterrows():
        params = {c: row[c] for c in param_cols if c in row.index}
        print(f"    Sharpe={row['sharpe']:.3f} WR={row['win_rate']:.2%} "
              f"PnL=${row['total_pnl']:.0f} DD={row['max_drawdown_pct']:.1f}% "
              f"| {params}")

print(f"\n  Results saved to: {OUT_DIR}")
print("=" * 60)
print("DONE")
