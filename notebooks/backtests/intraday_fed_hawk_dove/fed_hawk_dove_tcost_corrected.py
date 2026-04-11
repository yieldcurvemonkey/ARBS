# -*- coding: utf-8 -*-
"""
Corrected t-cost sensitivity.
BPV = $100,000 means a 1bp rate move generates $100,000 P&L.
Transaction cost of X bp slippage = X * BPV_of_position.
The original notebook formula divided by 10,000 — this is incorrect.
Correct:  cost($) = cost_bps * |bucket| * BASE_BPV
Original: cost($) = cost_bps * |bucket| * BASE_BPV / 10_000  ← 10,000x too small
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd

SIG = r"C:\Users\chris\clee\ARBS\notebooks\backtests\sig_closed.csv"
sig = pd.read_csv(SIG)
sig["opened_at"] = pd.to_datetime(sig["opened_at"], utc=True, errors="coerce")
sig["profitable"] = sig["realized_pnl"] > 0
BASE_BPV = 100_000

n = len(sig)
yrs = max((sig["opened_at"].max()-sig["opened_at"].min()).days/365.25, 0.5)
tpy = n/yrs
avg0 = sig["realized_pnl"].mean()
std0 = sig["realized_pnl"].std()
sr0  = avg0/std0*np.sqrt(tpy)

print("="*75)
print("  T-COST SENSITIVITY — CORRECTED (cost_bps * BPV, no /10000)")
print(f"  Base: SR={sr0:.2f}, Avg P&L=${avg0:,.0f}, {n} trades, {tpy:.0f}/yr")
print("="*75)
print(f"  Breakeven at ~{avg0/BASE_BPV*100:.2f} bps RT per $100k DV01 unit")
print()
print(f"  {'Cost(bps RT)':>12} {'Cost/trade (bkt=1)':>20} {'Cum P&L':>14} {'Avg P&L':>12} {'Hit':>7} {'Sharpe':>8} {'dSharpe':>9}")
print(f"  {'-'*87}")

for bps in [0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, 1.0, 1.5, 2.0]:
    # CORRECT formula: cost = bps * |bucket| * BASE_BPV
    rt = sig["bucket"].abs() * BASE_BPV * bps
    adj = sig["realized_pnl"] - rt
    a_avg=adj.mean(); a_std=adj.std()
    a_sr=(a_avg/a_std*np.sqrt(tpy)) if a_std>0 else 0
    a_cum = adj.sum()
    note = " <- breakeven" if abs(a_cum) < 500_000 and a_cum > 0 and bps > 0 else ""
    note = " <- NEGATIVE"  if a_cum < 0 else note
    print(f"  {bps:>12.2f} ${BASE_BPV*bps:>18,.0f} ${a_cum:>13,.0f} ${a_avg:>10,.0f} "
          f"{(adj>0).mean():>6.1%} {a_sr:>8.2f} {a_sr-sr0:>+9.2f}{note}")

# Exact breakeven
for bps100 in range(0,201):
    bps = bps100/100
    rt = sig["bucket"].abs() * BASE_BPV * bps
    if (sig["realized_pnl"] - rt).sum() <= 0:
        print(f"\n  Exact breakeven (cum P&L=0): {bps:.2f} bps RT")
        break

print()
print("  COMPARISON: original notebook formula (BUG - divides by 10,000):")
print(f"  {'Cost(bps RT)':>12} {'Bug cost/trade':>16} {'Correct cost/trade':>20}")
print(f"  {'-'*55}")
for bps in [0.25, 0.5, 1.0, 2.0]:
    bug_cost = BASE_BPV * bps / 10_000
    correct_cost = BASE_BPV * bps
    print(f"  {bps:>12.2f} ${bug_cost:>14,.0f} ${correct_cost:>18,.0f}")

print("\n  The original t-cost table understated costs by 10,000x.")
print(f"  At realistic 0.25bp RT, cost=${BASE_BPV*0.25:,.0f}/trade vs avg P&L ${avg0:,.0f}")
print(f"  → {BASE_BPV*0.25/avg0*100:.0f}% of average gross P&L consumed by t-costs at 0.25bp")
