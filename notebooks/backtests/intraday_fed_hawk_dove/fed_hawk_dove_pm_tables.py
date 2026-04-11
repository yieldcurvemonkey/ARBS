# -*- coding: utf-8 -*-
"""
Fast analysis from checkpoints — no backtest re-run needed.
Writes results to a UTF-8 text file to avoid cp1252 issues.
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

SIG = r"C:\Users\chris\clee\ARBS\notebooks\backtests\sig_closed.csv"
NAV = r"C:\Users\chris\clee\ARBS\notebooks\backtests\nav_closed.csv"
OUT = r"C:\Users\chris\clee\ARBS\notebooks\backtests\pm_feedback_results.txt"

sig = pd.read_csv(SIG)
nav = pd.read_csv(NAV)
for df in [sig, nav]:
    for col in ["opened_at","closed_at"]:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
sig["profitable"] = sig["realized_pnl"] > 0
nav["profitable"] = nav["realized_pnl"] > 0
sig["year"] = sig["opened_at"].dt.year
nav["year"] = nav["opened_at"].dt.year

BASE_BPV = 100_000

def metrics(cl):
    n = len(cl)
    yrs = max((cl["opened_at"].max()-cl["opened_at"].min()).days/365.25, 0.5)
    tpy = n/yrs; avg=cl["realized_pnl"].mean(); std=cl["realized_pnl"].std()
    sr = (avg/std*np.sqrt(tpy)) if std>0 else 0
    cum = cl["realized_pnl"].sum(); hit = cl["profitable"].mean()
    mdd = (cl["realized_pnl"].cumsum()-cl["realized_pnl"].cumsum().cummax()).min()
    return {"n":n,"cum":cum,"avg":avg,"std":std,"hit":hit,"sr":sr,"tpy":tpy,"mdd":mdd}

sm = metrics(sig)
nm = metrics(nav)

lines = []
lines.append("=" * 65)
lines.append("  1. NAIVE BENCHMARK vs SCORED SIGNAL")
lines.append("=" * 65)
lines.append(f"  {'Metric':<30} {'Signal':>15} {'Naive':>15}")
lines.append(f"  {'-'*60}")
lines.append(f"  {'Trades':<30} {sm['n']:>15d} {nm['n']:>15d}")
lines.append(f"  {'Trades/year':<30} {sm['tpy']:>15.0f} {nm['tpy']:>15.0f}")
lines.append(f"  {'Cumulative P&L':<30} ${sm['cum']:>14,.0f} ${nm['cum']:>14,.0f}")
lines.append(f"  {'Avg P&L/trade':<30} ${sm['avg']:>14,.0f} ${nm['avg']:>14,.0f}")
lines.append(f"  {'Std P&L/trade':<30} ${sm['std']:>14,.0f} ${nm['std']:>14,.0f}")
lines.append(f"  {'Hit Rate':<30} {sm['hit']:>14.1%} {nm['hit']:>14.1%}")
lines.append(f"  {'Sharpe':<30} {sm['sr']:>15.2f} {nm['sr']:>15.2f}")
lines.append(f"  {'Max Drawdown':<30} ${sm['mdd']:>14,.0f} ${nm['mdd']:>14,.0f}")

lines.append("")
lines.append(f"  {'Year P&L':<30} {'Signal':>15} {'Naive':>15}")
lines.append(f"  {'-'*60}")
sig_yr = sig.groupby("year")["realized_pnl"].sum()
nav_yr = nav.groupby("year")["realized_pnl"].sum()
for yr in sorted(set(sig_yr.index)|set(nav_yr.index)):
    sp = sig_yr.get(yr,0); np_ = nav_yr.get(yr,0)
    lines.append(f"  {str(yr):<30} ${sp:>14,.0f} ${np_:>14,.0f}")

lines.append("")
lines.append("  INTERPRETATION:")
sr_diff = sm['sr'] - nm['sr']
if sr_diff > 0.2:
    lines.append(f"  Signal SR={sm['sr']:.2f} vs Naive SR={nm['sr']:.2f} (+{sr_diff:.2f})")
    lines.append("  JPM scores ADD material alpha beyond the raw event effect.")
elif sr_diff > 0:
    lines.append(f"  Signal SR={sm['sr']:.2f} vs Naive SR={nm['sr']:.2f} (+{sr_diff:.2f})")
    lines.append("  Modest improvement — labels help but event itself carries most of the alpha.")
else:
    lines.append(f"  Signal SR={sm['sr']:.2f} vs Naive SR={nm['sr']:.2f} ({sr_diff:.2f})")
    lines.append("  WARNING: Scored signal does NOT outperform flat pay-fixed.")
    lines.append("  Alpha is structural (event drift), not from label quality.")

# ── 2. Waller Decay ───────────────────────────────────────────────────────────
lines.append("")
lines.append("=" * 65)
lines.append("  2. WALLER CHRONOLOGICAL P&L")
lines.append("=" * 65)
waller = sig[sig["speaker"]=="Waller"].sort_values("opened_at").reset_index(drop=True)
if waller.empty:
    lines.append("  No Waller trades found.")
else:
    waller["cum_pnl"] = waller["realized_pnl"].cumsum()
    pivot = pd.Timestamp("2025-06-01", tz="UTC")
    pre  = waller[waller["opened_at"] <  pivot]
    post = waller[waller["opened_at"] >= pivot]

    lines.append(f"  Total: {len(waller)} trades | P&L ${waller['realized_pnl'].sum():,.0f} | Hit {waller['profitable'].mean():.1%}")
    if not pre.empty:
        lines.append(f"  Pre  Jun-2025 ({len(pre):2d} trades): ${pre['realized_pnl'].sum():,.0f}  hit={pre['profitable'].mean():.0%}")
    if not post.empty:
        lines.append(f"  Post Jun-2025 ({len(post):2d} trades): ${post['realized_pnl'].sum():,.0f}  hit={post['profitable'].mean():.0%}")
    lines.append("")
    lines.append(f"  {'#':>3} {'Date':<12} {'Score':>7} {'Bkt':>4} {'P&L':>12} {'CumP&L':>14}  Sign")
    lines.append(f"  {'-'*60}")
    for i, row in waller.iterrows():
        sc = f"{row['raw_score']:.0f}" if not pd.isna(row['raw_score']) else "N/A"
        win = "WIN" if row["realized_pnl"] > 0 else "loss"
        pivot_mark = " << POST-PIVOT" if row["opened_at"] >= pivot and (i==0 or waller.loc[i-1,"opened_at"] < pivot) else ""
        lines.append(f"  {i+1:>3} {str(row['opened_at'].date()):<12} {sc:>7} {int(row['bucket']):>+4d} "
                     f"${row['realized_pnl']:>10,.0f} ${row['cum_pnl']:>12,.0f}  {win}{pivot_mark}")

# ── 3. T-Cost Sensitivity ─────────────────────────────────────────────────────
lines.append("")
lines.append("=" * 65)
lines.append("  3. TRANSACTION COST SENSITIVITY")
lines.append("=" * 65)
lines.append(f"  {'Cost(bps RT)':>12} {'Avg Cost/trade':>16} {'Cum P&L':>14} {'Avg P&L':>12} {'Hit':>7} {'Sharpe':>8} {'dSharpe':>9}")
lines.append(f"  {'-'*83}")
for bps in [0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0]:
    rt = sig["bucket"].abs() * BASE_BPV * bps / 10_000
    adj = sig["realized_pnl"] - rt
    a_avg=adj.mean(); a_std=adj.std()
    a_sr=(a_avg/a_std*np.sqrt(sm["tpy"])) if a_std>0 else 0
    lines.append(f"  {bps:>12.2f} ${rt.mean():>14,.0f} ${adj.sum():>13,.0f} ${a_avg:>10,.0f} "
                 f"{(adj>0).mean():>6.1%} {a_sr:>8.2f} {a_sr-sm['sr']:>+9.2f}")

# Breakeven
for bps10 in range(0, 51):
    bps = bps10/10
    rt = sig["bucket"].abs() * BASE_BPV * bps / 10_000
    if (sig["realized_pnl"] - rt).sum() <= 0:
        lines.append(f"\n  Breakeven P&L=0 at ~{bps:.1f} bps RT")
        break
else:
    lines.append("\n  Strategy P&L positive through 5.0 bps RT")

lines.append(f"\n  1 bp RT ~ ${BASE_BPV/10_000:,.0f}/unit vs gross avg ${sm['avg']:,.0f} = "
             f"{BASE_BPV/10_000/sm['avg']*100:.1f}% of avg gross P&L per 1bp")

output = "\n".join(lines)
print(output)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(output)
print(f"\n  Results written to {OUT}")
