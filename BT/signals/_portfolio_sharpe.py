"""Compute equal-weight portfolio Sharpe across the 12 SFR outrights."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, r"C:\Users\chris\clee\ARBS")

ALL = Path(r"C:\Users\chris\clee\ARBS\BT\results\asia_fade_grid_outrights\all_trades.parquet")
t = pd.read_parquet(ALL)
t["date"] = pd.to_datetime(t["date"])

# Flip net_usd to momentum convention (panel built with fade by default)
t["net_mom"]   = -t["net_usd"]
t["gross_mom"] = -t["gross_usd"]

# Per-package daily P&L (one trade per day per package max)
pkgs = sorted(t["package"].unique())
print(f"Packages: {pkgs}")
print(f"Trade dates: {t['date'].min().date()} → {t['date'].max().date()}")

# Pivot: each row = date, each col = package, value = net momentum P&L
daily = t.pivot_table(index="date", columns="package", values="net_mom",
                      aggfunc="sum", fill_value=0.0).sort_index()
print(f"\nDaily P&L panel shape: {daily.shape}  (rows=dates, cols=packages)")
print(f"  rows with trades: {(daily != 0).any(axis=1).sum()}")

# Per-package totals
print("\nPer-package totals (MOMENTUM, no-filter, after safety blackout):")
print(f"  {'pkg':<16} {'n':>5} {'avg $':>11} {'std $':>11} {'total $':>14} {'Sharpe':>7}")
for pkg in pkgs:
    s = daily[pkg]
    s_active = s[s != 0]
    n = len(s_active)
    avg = s_active.mean() if n else 0
    std = s_active.std() if n else 0
    sr = avg / std * np.sqrt(252 * n / len(daily)) if std > 0 else 0
    print(f"  {pkg:<16} {n:>5} ${avg:>+9,.0f} ${std:>10,.0f} ${s.sum():>+13,.0f}  {sr:>+7.2f}")

# Equal-weight portfolio: average daily P&L across all 12 packages
# (treats it as if you held 1 unit per package — same notional weights)
port_daily = daily.mean(axis=1)
port_daily = port_daily[port_daily != 0]
print(f"\n── Equal-weight portfolio of all 12 outrights (MOMENTUM, no filter) ──")
print(f"  active days: {len(port_daily)}")
print(f"  avg $/day:     ${port_daily.mean():+,.0f}")
print(f"  std $/day:     ${port_daily.std():,.0f}")
print(f"  total $:       ${port_daily.sum() * 12:+,.0f}   (×12 for full notional)")
print(f"  daily Sharpe:  {port_daily.mean()/port_daily.std()*np.sqrt(252):+.2f}")

# Now check correlation matrix between packages' daily P&Ls
print(f"\nCorrelation matrix of daily P&L (momentum):")
corr = daily.corr()
print(corr.round(2).to_string())

# Average pairwise corr
n = len(pkgs)
off_diag = corr.values[np.triu_indices(n, k=1)]
print(f"\nAvg pairwise correlation: {off_diag.mean():.3f}")
print(f"Min pairwise corr:        {off_diag.min():.3f}")
print(f"Max pairwise corr:        {off_diag.max():.3f}")

# What does a "deep-only" portfolio (SFR3-SFR12) look like? (avoid SFR1 since
# it's so good it might mask others)
deep = ["SFR3_outright","SFR4_outright","SFR5_outright","SFR6_outright","SFR7_outright",
        "SFR8_outright","SFR9_outright","SFR10_outright","SFR11_outright","SFR12_outright"]
dport = daily[deep].mean(axis=1)
dport_active = dport[dport != 0]
print(f"\n── 'Deep-only' equal-weight portfolio (SFR3-SFR12, 10 packages) ──")
print(f"  active days: {len(dport_active)}")
print(f"  total $:       ${dport_active.sum() * 10:+,.0f}")
print(f"  daily Sharpe:  {dport_active.mean()/dport_active.std()*np.sqrt(252):+.2f}")

# And what if you weight by inverse vol (risk parity)?
vols = daily[daily != 0].std()
weights = (1.0 / vols)
weights = weights / weights.sum()
rp_daily = (daily * weights).sum(axis=1)
rp_active = rp_daily[rp_daily != 0]
print(f"\n── Risk-parity (inverse-vol) portfolio across 12 outrights ──")
print(f"  weights: {weights.round(3).to_dict()}")
print(f"  active days: {len(rp_active)}")
print(f"  daily Sharpe: {rp_active.mean()/rp_active.std()*np.sqrt(252):+.2f}")
print(f"  notional-equivalent total $: ${rp_active.sum() / weights.sum():+,.0f}")
