"""
OBI Multi-Asset Grid Search: ETH & SOL on Polymarket 5-min Up/Down
===================================================================
Comprehensive parameter optimization for the OBI strategy across
BTC, ETH, and SOL — identical grid applied to each asset so results
are directly comparable.

Usage:
    conda run -n stir python notebooks/backtests/obi_multi_asset_grid_search.py

    Set OBI_SYNTHETIC=1 to use synthetic data (fast, no API needed).

Outputs:
    - Per-asset grid CSV in notebooks/backtests/obi_multi_asset_grid_results/
    - Best-config reports
    - Heatmap PNGs
    - Cross-asset comparison table
"""
from __future__ import annotations

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OBI.config import (
    ASSET_CONFIGS,
    BacktestConfig,
    POLYMARKET_5M_BTC,
    POLYMARKET_5M_ETH,
    POLYMARKET_5M_SOL,
    build_config,
)
from OBI.backtest import (
    fetch_crypto_prices,
    run_backtest,
    run_grid_search,
    select_best_configs,
)
from OBI.tearsheet import (
    plot_tearsheet,
    plot_grid_search_heatmap,
    plot_grid_comparison,
    format_best_configs,
)

OUT_DIR = Path(__file__).resolve().parent / "obi_multi_asset_grid_results"
OUT_DIR.mkdir(exist_ok=True)

# ===========================================================================
# Parameters
# ===========================================================================

DATA_START = "2025-05-15"
DATA_END = "2025-06-01"
USE_SYNTHETIC = os.environ.get("OBI_SYNTHETIC", "0") == "1"

ASSET_PRESETS = {
    "BTC": POLYMARKET_5M_BTC,
    "ETH": POLYMARKET_5M_ETH,
    "SOL": POLYMARKET_5M_SOL,
}

GRID = {
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [10, 20, 30, 45, 60],
    "obi_depth_levels": [3, 5, 8, 10],
    "obi_variant": ["raw", "normalized", "weighted"],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20, 0.25],
    "sizing_mode": ["fixed", "scaled"],
}

n_combos = 1
for v in GRID.values():
    n_combos *= len(v)


def _generate_synthetic(base_price: float, start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="1min", tz="UTC")
    np.random.seed(42)
    vol = 0.0003 if base_price > 10_000 else (0.0005 if base_price > 500 else 0.0008)
    returns = np.random.normal(0, vol, len(idx))
    prices = base_price * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "open": prices,
        "high": prices * (1 + np.abs(np.random.normal(0, 0.0002, len(idx)))),
        "low": prices * (1 - np.abs(np.random.normal(0, 0.0002, len(idx)))),
        "close": prices * (1 + np.random.normal(0, 0.0001, len(idx))),
        "volume": np.random.lognormal(10, 1, len(idx)),
    }, index=idx)


# ===========================================================================
# Main loop: grid search per asset
# ===========================================================================

print("=" * 70)
print("OBI MULTI-ASSET GRID SEARCH")
print(f"  Assets: {', '.join(ASSET_PRESETS.keys())}")
print(f"  Grid: {n_combos:,} combinations per asset")
print(f"  Period: {DATA_START} — {DATA_END}")
print(f"  Data: {'SYNTHETIC' if USE_SYNTHETIC else 'Binance via ccxt'}")
print("=" * 70)

all_grid_dfs = {}

for asset_name, preset in ASSET_PRESETS.items():
    acfg = ASSET_CONFIGS[asset_name]
    print(f"\n{'━' * 70}")
    print(f"  {asset_name}  ({acfg['symbol']})")
    print(f"{'━' * 70}")

    # --- 1. Fetch data ---
    t0 = time.time()
    if USE_SYNTHETIC:
        prices = _generate_synthetic(acfg["base_price"], DATA_START, DATA_END)
        print(f"  [data] Synthetic {len(prices):,} candles")
    else:
        try:
            prices = fetch_crypto_prices(
                symbol=acfg["symbol"],
                start=DATA_START,
                end=DATA_END,
                source="ccxt",
                exchange="binance",
                timeframe="1m",
            )
            print(f"  [data] Fetched {len(prices):,} candles ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"  [data] ccxt failed ({e}), falling back to synthetic...")
            prices = _generate_synthetic(acfg["base_price"], DATA_START, DATA_END)
            print(f"  [data] Synthetic {len(prices):,} candles")

    # --- 2. Run grid search ---
    base = build_config(preset, {"start_date": DATA_START, "end_date": DATA_END})
    print(f"  [grid] Running {n_combos:,} parameter combinations...")

    t0 = time.time()
    grid_df = run_grid_search(
        base_config=base,
        grid=GRID,
        prices=prices,
        progress=True,
    )
    elapsed = time.time() - t0
    print(f"  [grid] Done in {elapsed:.1f}s ({elapsed/len(grid_df)*1000:.0f}ms/run)")

    grid_df.insert(0, "asset", asset_name)
    csv_path = OUT_DIR / f"{asset_name.lower()}_polymarket_5m_grid.csv"
    grid_df.to_csv(csv_path, index=False)
    print(f"  [saved] {csv_path}")
    all_grid_dfs[asset_name] = grid_df

    # --- 3. Best configs ---
    best = select_best_configs(grid_df)
    if best:
        report = format_best_configs(best)
        print(report)
        report_path = OUT_DIR / f"{asset_name.lower()}_best_configs.txt"
        with open(report_path, "w") as f:
            f.write(f"Best Configs: {asset_name} Polymarket 5m\n")
            f.write(f"Generated: {pd.Timestamp.now()}\n")
            f.write(f"Period: {DATA_START} — {DATA_END}\n\n")
            f.write(report)

    # --- 4. Heatmaps ---
    valid = grid_df.dropna(subset=["sharpe"])
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]

    if not valid.empty:
        for x_col, y_col, metric in [
            ("entry_threshold", "signal_mode", "sharpe"),
            ("entry_threshold", "obi_depth_levels", "sharpe"),
            ("entry_threshold", "sim_obi_predictive_power", "win_rate"),
            ("entry_threshold", "obi_variant", "sharpe"),
        ]:
            try:
                fig = plot_grid_search_heatmap(
                    valid, x_col, y_col, metric,
                    title=f"{asset_name}: {metric} by {x_col} & {y_col}",
                )
                fname = f"{asset_name.lower()}_heatmap_{x_col}_{y_col}_{metric}.png"
                fig.savefig(OUT_DIR / fname, dpi=150, bbox_inches="tight")
                plt.close(fig)
            except Exception:
                pass

        # --- tearsheet for best-sharpe config ---
        if "best_sharpe" in best:
            row = best["best_sharpe"]
            param_cols = [c for c in GRID.keys() if c in row.index]
            overrides = {c: row[c] for c in param_cols}
            cfg = build_config(preset, {
                "start_date": DATA_START,
                "end_date": DATA_END,
                **overrides,
            })
            try:
                result = run_backtest(cfg, prices=prices)
                fig = plot_tearsheet(
                    result,
                    title=f"{asset_name} Polymarket 5m — Best Sharpe Tearsheet",
                )
                if fig:
                    fig.savefig(
                        OUT_DIR / f"{asset_name.lower()}_best_sharpe_tearsheet.png",
                        dpi=150, bbox_inches="tight",
                    )
                    plt.close(fig)
            except Exception:
                pass

        print(f"  [saved] heatmaps + tearsheet")


# ===========================================================================
# Cross-asset comparison
# ===========================================================================

print("\n" + "=" * 70)
print("CROSS-ASSET COMPARISON")
print("=" * 70)

summary_rows = []
for asset_name, grid_df in all_grid_dfs.items():
    valid = grid_df.dropna(subset=["sharpe"])
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]

    if valid.empty:
        continue

    profitable = valid[valid["total_pnl"] > 0]
    best = valid.loc[valid["sharpe"].idxmax()]

    summary_rows.append({
        "asset": asset_name,
        "configs_tested": len(valid),
        "profitable_pct": f"{(valid['total_pnl'] > 0).mean():.1%}",
        "sharpe_max": f"{valid['sharpe'].max():.4f}",
        "sharpe_p50": f"{valid['sharpe'].median():.4f}",
        "win_rate_max": f"{valid['win_rate'].max():.2%}",
        "pnl_max": f"${valid['total_pnl'].max():.0f}",
        "best_mode": best.get("signal_mode", "?"),
        "best_variant": best.get("obi_variant", "?"),
        "best_threshold": best.get("entry_threshold", "?"),
        "best_dd": f"{best.get('max_drawdown_pct', 0):.1f}%",
    })

if summary_rows:
    summary_df = pd.DataFrame(summary_rows)
    print(f"\n{summary_df.to_string(index=False)}")
    summary_df.to_csv(OUT_DIR / "cross_asset_summary.csv", index=False)

# --- combined grid for downstream analysis ---
combined = pd.concat(all_grid_dfs.values(), ignore_index=True)
combined.to_csv(OUT_DIR / "all_assets_combined_grid.csv", index=False)
print(f"\n  Combined grid ({len(combined):,} rows) saved to all_assets_combined_grid.csv")

# --- cross-asset heatmap: best sharpe per asset × threshold ---
try:
    pivot_data = []
    for asset_name, grid_df in all_grid_dfs.items():
        valid = grid_df.dropna(subset=["sharpe"])
        if "error" in valid.columns:
            valid = valid[valid["error"].isna()]
        for thresh, grp in valid.groupby("entry_threshold"):
            pivot_data.append({
                "asset": asset_name,
                "threshold": thresh,
                "best_sharpe": grp["sharpe"].max(),
            })
    if pivot_data:
        pivot_df = pd.DataFrame(pivot_data)
        pivot = pivot_df.pivot(index="threshold", columns="asset", values="best_sharpe")
        fig, ax = plt.subplots(figsize=(10, 6))
        sns.heatmap(pivot, annot=True, fmt=".3f", cmap="RdYlGn", center=0, ax=ax)
        ax.set_title("Best Sharpe by Asset & Entry Threshold")
        fig.savefig(OUT_DIR / "cross_asset_sharpe_heatmap.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        print("  [saved] cross_asset_sharpe_heatmap.png")
except Exception as e:
    print(f"  [!] Cross-asset heatmap error: {e}")

print(f"\n  All results saved to: {OUT_DIR}")
print("=" * 70)
print("DONE")
