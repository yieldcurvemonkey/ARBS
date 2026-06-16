"""Generate tearsheets and heatmaps from grid search results."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from OBI.config import BacktestConfig
from OBI.backtest import run_backtest
from OBI.tearsheet import plot_tearsheet, plot_grid_search_heatmap

out = Path(__file__).resolve().parent / "obi_grid_results"

idx = pd.date_range("2025-05-28", "2025-06-01", freq="1min", tz="UTC")
np.random.seed(42)
px = 108000 * np.exp(np.cumsum(np.random.normal(0, 0.0003, len(idx))))
btc = pd.DataFrame({
    "open": px, "high": px * 1.001, "low": px * 0.999,
    "close": px * (1 + np.random.normal(0, 0.0001, len(idx))),
    "volume": np.random.lognormal(10, 1, len(idx)),
}, index=idx)

# Polymarket best tearsheet
print("Generating Polymarket tearsheet...")
r = run_backtest(BacktestConfig(
    venue="polymarket", contract_duration_minutes=5,
    entry_threshold=0.15, signal_mode="follow", obi_depth_levels=3,
    obi_variant="normalized", sim_obi_predictive_power=0.2,
    entry_fee_pct=0.02, start_date="2025-05-28", end_date="2025-06-01",
), btc_prices=btc)
fig = plot_tearsheet(r, "Polymarket 5m BTC: Best Sharpe Config")
fig.savefig(out / "polymarket_best_tearsheet.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"  Saved. trades={r.metrics['n_trades']} sharpe={r.metrics['sharpe']:.1f} wr={r.metrics['win_rate']:.2%}")

# Kalshi best tearsheet
print("Generating Kalshi tearsheet...")
r2 = run_backtest(BacktestConfig(
    venue="kalshi", contract_duration_minutes=15,
    entry_threshold=0.05, signal_mode="follow", obi_depth_levels=3,
    obi_variant="raw", sim_obi_predictive_power=0.2,
    entry_fee_pct=0.07, start_date="2025-05-28", end_date="2025-06-01",
), btc_prices=btc)
fig2 = plot_tearsheet(r2, "Kalshi 15m BTC: Best Sharpe Config")
fig2.savefig(out / "kalshi_best_tearsheet.png", dpi=150, bbox_inches="tight")
plt.close(fig2)
print(f"  Saved. trades={r2.metrics['n_trades']} sharpe={r2.metrics['sharpe']:.1f} wr={r2.metrics['win_rate']:.2%}")

# Heatmaps from CSV
print("Generating heatmaps...")
for label in ["polymarket_5m", "kalshi_15m"]:
    csv = out / f"{label}_grid.csv"
    if not csv.exists():
        continue
    df = pd.read_csv(csv).dropna(subset=["sharpe"])
    for metric in ["sharpe", "win_rate"]:
        try:
            fig = plot_grid_search_heatmap(df, "entry_threshold", "signal_mode", metric, f"{label}: {metric}")
            fig.savefig(out / f"{label}_{metric}_mode.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception as e:
            print(f"  {label}/{metric}/mode: {e}")
        try:
            fig = plot_grid_search_heatmap(df, "entry_threshold", "sim_obi_predictive_power", metric, f"{label}: {metric}")
            fig.savefig(out / f"{label}_{metric}_pp.png", dpi=150, bbox_inches="tight")
            plt.close(fig)
        except Exception as e:
            print(f"  {label}/{metric}/pp: {e}")

import os
files = [f for f in os.listdir(out) if f.endswith((".png", ".csv"))]
print(f"\nAll files in {out}:")
for f in sorted(files):
    print(f"  {f}")
print("DONE")
