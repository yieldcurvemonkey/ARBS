"""Minimal OBI grid search — small grid, fast results."""
import sys, time, itertools
from pathlib import Path
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from OBI.config import BacktestConfig, build_config
from OBI.backtest import run_backtest, select_best_configs

# --- synthetic BTC data (3 days) ---
print("Generating synthetic BTC data...")
idx = pd.date_range("2025-05-28", "2025-06-01", freq="1min", tz="UTC")
np.random.seed(42)
rets = np.random.normal(0, 0.0003, len(idx))
px = 108000 * np.exp(np.cumsum(rets))
btc = pd.DataFrame({
    "open": px, "high": px * 1.001, "low": px * 0.999,
    "close": px * (1 + np.random.normal(0, 0.0001, len(idx))),
    "volume": np.random.lognormal(10, 1, len(idx)),
}, index=idx)
print(f"  {len(btc)} candles")

# --- grid ---
GRID = {
    "entry_threshold": [0.05, 0.10, 0.15, 0.20, 0.30, 0.50],
    "signal_mode": ["follow", "fade"],
    "obi_depth_levels": [3, 5, 10],
    "obi_variant": ["raw", "normalized", "weighted"],
    "sim_obi_predictive_power": [0.05, 0.10, 0.15, 0.20],
}
combos = list(itertools.product(*GRID.values()))
print(f"Grid: {len(combos)} combinations")

# --- POLYMARKET 5m ---
print("\n=== POLYMARKET 5m BTC ===")
poly_base = BacktestConfig(
    venue="polymarket", contract_duration_minutes=5,
    entry_fee_pct=0.02, spread_cost=0.02,
    start_date="2025-05-28", end_date="2025-06-01",
)
results = []
t0 = time.time()
for i, combo in enumerate(combos):
    overrides = dict(zip(GRID.keys(), combo))
    cfg = build_config(poly_base, overrides)
    try:
        r = run_backtest(cfg, btc_prices=btc)
        row = {**overrides, **r.metrics}
    except Exception as e:
        row = {**overrides, "error": str(e)}
    results.append(row)
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(combos)} ({time.time()-t0:.0f}s)")

poly_df = pd.DataFrame(results)
elapsed = time.time() - t0
print(f"  Done: {len(poly_df)} runs in {elapsed:.1f}s ({elapsed/len(poly_df)*1000:.0f}ms/run)")

# --- KALSHI 15m ---
print("\n=== KALSHI 15m BTC ===")
kalshi_base = BacktestConfig(
    venue="kalshi", contract_duration_minutes=15,
    entry_fee_pct=0.07, spread_cost=0.03,
    start_date="2025-05-28", end_date="2025-06-01",
)
kalshi_results = []
t0 = time.time()
for i, combo in enumerate(combos):
    overrides = dict(zip(GRID.keys(), combo))
    cfg = build_config(kalshi_base, overrides)
    try:
        r = run_backtest(cfg, btc_prices=btc)
        row = {**overrides, **r.metrics}
    except Exception as e:
        row = {**overrides, "error": str(e)}
    kalshi_results.append(row)
    if (i + 1) % 50 == 0:
        print(f"  {i+1}/{len(combos)} ({time.time()-t0:.0f}s)")

kalshi_df = pd.DataFrame(kalshi_results)
elapsed = time.time() - t0
print(f"  Done: {len(kalshi_df)} runs in {elapsed:.1f}s ({elapsed/len(kalshi_df)*1000:.0f}ms/run)")

# --- Save ---
out = Path(__file__).resolve().parent / "obi_grid_results"
out.mkdir(exist_ok=True)
poly_df.to_csv(out / "polymarket_5m_grid.csv", index=False)
kalshi_df.to_csv(out / "kalshi_15m_grid.csv", index=False)

# --- Report ---
for label, df in [("POLYMARKET 5m", poly_df), ("KALSHI 15m", kalshi_df)]:
    valid = df.dropna(subset=["sharpe"])
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]

    print(f"\n{'='*60}")
    print(f" {label} RESULTS")
    print(f"{'='*60}")
    print(f"  Configs tested: {len(valid)}")
    print(f"  Profitable: {(valid['total_pnl'] > 0).sum()} ({(valid['total_pnl'] > 0).mean():.1%})")
    print(f"  Sharpe > 0: {(valid['sharpe'] > 0).sum()} ({(valid['sharpe'] > 0).mean():.1%})")
    print(f"  Win rate: {valid['win_rate'].min():.2%} — {valid['win_rate'].max():.2%}")
    print(f"  Sharpe: {valid['sharpe'].min():.3f} — {valid['sharpe'].max():.3f}")
    print(f"  Max PnL: ${valid['total_pnl'].max():.2f}")
    print(f"  Avg trades/config: {valid['n_trades'].mean():.0f}")

    best = select_best_configs(valid)
    for name, row in best.items():
        params = {c: row[c] for c in GRID.keys() if c in row.index}
        print(f"\n  {name.upper()}:")
        print(f"    Sharpe={row.get('sharpe',0):.3f}  WR={row.get('win_rate',0):.2%}  "
              f"PnL=${row.get('total_pnl',0):.0f}  DD={row.get('max_drawdown_pct',0):.1f}%  "
              f"Trades={int(row.get('n_trades',0))}")
        print(f"    Params: {params}")

    print(f"\n  Top 5 by Sharpe:")
    for i, (_, row) in enumerate(valid.nlargest(5, "sharpe").iterrows()):
        params = {c: row[c] for c in GRID.keys() if c in row.index}
        print(f"  {i+1}. S={row['sharpe']:7.3f} WR={row['win_rate']:.2%} "
              f"PnL=${row['total_pnl']:7.0f} DD={row['max_drawdown_pct']:5.1f}% | {params}")

    print(f"\n  Top 5 by Win Rate:")
    for i, (_, row) in enumerate(valid.nlargest(5, "win_rate").iterrows()):
        params = {c: row[c] for c in GRID.keys() if c in row.index}
        print(f"  {i+1}. S={row['sharpe']:7.3f} WR={row['win_rate']:.2%} "
              f"PnL=${row['total_pnl']:7.0f} DD={row['max_drawdown_pct']:5.1f}% | {params}")

print(f"\nCSVs saved to {out}")
print("DONE")
