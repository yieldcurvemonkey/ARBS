"""Quick focused OBI grid search — runs in ~5 minutes."""
from __future__ import annotations
import sys, time
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OBI.config import BacktestConfig, POLYMARKET_5M_BTC, KALSHI_15M_BTC, build_config
from OBI.backtest import run_backtest, run_grid_search, select_best_configs
from OBI.tearsheet import plot_tearsheet, plot_grid_search_heatmap, format_best_configs

OUT = Path(__file__).resolve().parent / "obi_grid_results"
OUT.mkdir(exist_ok=True)

print("=" * 60)
print("OBI QUICK GRID SEARCH")
print("=" * 60)

# --- Generate synthetic BTC data (1 week, instant) ---
print("\n[1] Generating synthetic BTC data (1 week)...")
idx = pd.date_range("2025-05-25", "2025-06-01", freq="1min", tz="UTC")
np.random.seed(42)
rets = np.random.normal(0, 0.0003, len(idx))
px = 108000 * np.exp(np.cumsum(rets))
btc = pd.DataFrame({
    "open": px,
    "high": px * (1 + np.abs(np.random.normal(0, 0.0002, len(idx)))),
    "low": px * (1 - np.abs(np.random.normal(0, 0.0002, len(idx)))),
    "close": px * (1 + np.random.normal(0, 0.0001, len(idx))),
    "volume": np.random.lognormal(10, 1, len(idx)),
}, index=idx)
print(f"  {len(btc)} candles generated")

# --- Polymarket 5m grid ---
print("\n[2] Polymarket 5m BTC grid search...")
poly_base = build_config(POLYMARKET_5M_BTC, {"start_date": "2025-05-25", "end_date": "2025-06-01"})

POLY_GRID = {
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [15, 30, 60],
    "obi_depth_levels": [3, 5, 10],
    "obi_variant": ["raw", "normalized", "weighted"],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20, 0.25],
}
n = 1
for v in POLY_GRID.values():
    n *= len(v)
print(f"  {n} combinations")

t0 = time.time()
poly_df = run_grid_search(poly_base, POLY_GRID, btc_prices=btc, progress=True)
print(f"  Done in {time.time()-t0:.1f}s ({(time.time()-t0)/n*1000:.0f}ms/run)")
poly_df.to_csv(OUT / "polymarket_5m_grid.csv", index=False)

# --- Kalshi 15m grid ---
print("\n[3] Kalshi 15m BTC grid search...")
kalshi_base = build_config(KALSHI_15M_BTC, {"start_date": "2025-05-25", "end_date": "2025-06-01"})

KALSHI_GRID = {
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50],
    "signal_mode": ["follow", "fade"],
    "entry_delay_seconds": [30, 60, 120],
    "obi_depth_levels": [3, 5, 10],
    "obi_variant": ["raw", "normalized", "weighted"],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20, 0.25],
}

t0 = time.time()
kalshi_df = run_grid_search(kalshi_base, KALSHI_GRID, btc_prices=btc, progress=True)
print(f"  Done in {time.time()-t0:.1f}s")
kalshi_df.to_csv(OUT / "kalshi_15m_grid.csv", index=False)

# --- Best configs ---
print("\n[4] Best configurations:")
for label, df, base in [("Polymarket 5m", poly_df, poly_base), ("Kalshi 15m", kalshi_df, kalshi_base)]:
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")

    valid = df.dropna(subset=["sharpe"])
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]

    print(f"  Total runs: {len(valid)}")
    print(f"  Profitable: {(valid['total_pnl'] > 0).sum()} ({(valid['total_pnl'] > 0).mean():.1%})")
    print(f"  Sharpe > 0: {(valid['sharpe'] > 0).sum()} ({(valid['sharpe'] > 0).mean():.1%})")
    print(f"  Sharpe range: {valid['sharpe'].min():.3f} to {valid['sharpe'].max():.3f}")
    print(f"  Win rate range: {valid['win_rate'].min():.2%} to {valid['win_rate'].max():.2%}")

    best = select_best_configs(valid)
    print(format_best_configs(best))

    # --- Run best sharpe tearsheet ---
    if "best_sharpe" in best:
        row = best["best_sharpe"]
        param_cols = [c for c in POLY_GRID.keys() if c in row.index]
        overrides = {c: row[c] for c in param_cols}
        cfg = build_config(base, overrides)
        result = run_backtest(cfg, btc_prices=btc)
        fig = plot_tearsheet(result, title=f"{label}: Best Sharpe Tearsheet")
        if fig:
            fig.savefig(OUT / f"{label.lower().replace(' ', '_')}_best_tearsheet.png", dpi=150, bbox_inches="tight")
            plt.close(fig)

    # --- Top 10 table ---
    print(f"\n  Top 10 by Sharpe:")
    top10 = valid.nlargest(10, "sharpe")
    param_cols = [c for c in df.columns if c in list(POLY_GRID.keys()) + list(KALSHI_GRID.keys())]
    for i, (_, row) in enumerate(top10.iterrows()):
        params = {c: row[c] for c in param_cols if c in row.index}
        print(f"  {i+1:2d}. Sharpe={row['sharpe']:7.3f}  WR={row['win_rate']:.2%}  "
              f"PnL=${row['total_pnl']:8.0f}  DD={row['max_drawdown_pct']:5.1f}%  "
              f"Trades={int(row['n_trades'])}  | {params}")

# --- Heatmaps ---
print("\n[5] Generating heatmaps...")
for label, df in [("polymarket_5m", poly_df), ("kalshi_15m", kalshi_df)]:
    valid = df.dropna(subset=["sharpe"])
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]
    if valid.empty:
        continue

    for metric in ["sharpe", "win_rate"]:
        try:
            fig = plot_grid_search_heatmap(
                valid, "entry_threshold", "signal_mode", metric,
                title=f"{label}: {metric} by threshold & mode"
            )
            fig.savefig(OUT / f"{label}_{metric}_threshold_mode.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception:
            pass

        try:
            fig = plot_grid_search_heatmap(
                valid, "entry_threshold", "sim_obi_predictive_power", metric,
                title=f"{label}: {metric} by threshold & predictive power"
            )
            fig.savefig(OUT / f"{label}_{metric}_threshold_pp.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception:
            pass

print(f"\n  Results saved to: {OUT}")
print("=" * 60)
print("DONE")
