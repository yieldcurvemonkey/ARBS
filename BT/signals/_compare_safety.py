"""Compare best-per-package between original grid and safety-filtered grid."""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

orig = pd.read_csv(r"C:\Users\chris\clee\ARBS\BT\results\asia_fade_grid\best_per_package.csv")
safe = pd.read_csv(r"C:\Users\chris\clee\ARBS\BT\results\asia_fade_grid_safe\best_per_package.csv")

print(f"{'package':<22} | {'polarity_pre':>9} | {'SR_pre':>7} | {'$_pre M':>9} | n_pre | "
      f"{'polarity_safe':>10} | {'SR_safe':>8} | {'$_safe M':>10} | n_safe | "
      f"{'ΔSharpe':>8} | {'Δ% PnL':>7} | verdict")
print("-" * 178)

merged = orig.merge(safe, on="package", suffixes=("_pre", "_safe"))
merged = merged.sort_values("sharpe_safe", ascending=False)

for _, r in merged.iterrows():
    d_sharpe = r["sharpe_safe"] - r["sharpe_pre"]
    pct_pnl_loss = (r["total_usd_safe"] - r["total_usd_pre"]) / abs(r["total_usd_pre"]) * 100 if r["total_usd_pre"] else 0

    if r["sharpe_safe"] > 1.0 and pct_pnl_loss > -20:
        v = "ROBUST ✓"
    elif r["sharpe_safe"] > 0.5 and pct_pnl_loss > -40:
        v = "survives"
    elif pct_pnl_loss < -40 or r["sharpe_safe"] < 0.3:
        v = "DEGRADED ⚠️"
    else:
        v = "weak"

    print(f"{r['package']:<22} | {r['polarity_pre']:>9} | {r['sharpe_pre']:>+7.2f} | "
          f"{r['total_usd_pre']/1e6:>+8.2f}M | {int(r['n_trades_pre']):>5} | "
          f"{r['polarity_safe']:>10} | {r['sharpe_safe']:>+8.2f} | "
          f"{r['total_usd_safe']/1e6:>+9.2f}M | {int(r['n_trades_safe']):>6} | "
          f"{d_sharpe:>+8.2f} | {pct_pnl_loss:>+6.1f}% | {v}")
