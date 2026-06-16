"""
OBI Temporal Velocity + Market-Making Backtest (Real PMXT Data)
===============================================================
Two strategies:
1. Temporal OBI: early flow velocity in first 30-60s of contract life
2. Market-Making: earn spread with OBI-guided inventory skew
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from dataclasses import asdict
from tqdm import tqdm

from OBI.pmxt_fetcher import load_btc_5m_meta, fetch_pmxt_hour
from OBI.temporal_obi import (
    extract_temporal_features,
    backtest_temporal_obi,
    backtest_market_maker,
    TemporalFeatures,
)

OUT = Path(__file__).resolve().parent / "obi_grid_results"
OUT.mkdir(exist_ok=True)

print("=" * 60)
print("OBI TEMPORAL + MARKET-MAKING BACKTEST")
print("=" * 60)

# ===================================================================
# 1. Load metadata
# ===================================================================
print("\n[1/5] Loading metadata...")
meta = load_btc_5m_meta(start_date="2026-05-20", end_date="2026-05-26")
print(f"  {len(meta)} contracts")

contract_map = {}
for _, row in meta.iterrows():
    contract_map[row["yes_token_id"]] = {
        "outcome": float(row["outcome"]),
        "resolution_time": row["resolution_time_utc"],
        "period_open": row["period_open_utc"],
    }

hour_tokens = {}
for _, row in meta.iterrows():
    for col in ["period_open_utc", "resolution_time_utc"]:
        h_key = row[col].floor("h").strftime("%Y-%m-%dT%H")
        hour_tokens.setdefault(h_key, set()).add(row["yes_token_id"])

# ===================================================================
# 2. Stream PMXT data — extract temporal features per contract
# ===================================================================
print("\n[2/5] Extracting temporal features from PMXT ticks...")

temporal_features: dict = {}  # token_id -> TemporalFeatures
dates = pd.date_range("2026-05-20", "2026-05-26", freq="D")
hours_ok = 0
t_start = time.time()

for date in dates:
    ds = date.strftime("%Y-%m-%d")
    for h in range(24):
        h_key = f"{ds}T{h:02d}"
        relevant = hour_tokens.get(h_key, set())
        if not relevant:
            continue

        df = fetch_pmxt_hour(ds, h, token_ids=list(relevant), cache=True)
        if df.empty:
            continue

        hours_ok += 1
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        for token_id, group in df.groupby("asset_id"):
            if token_id not in contract_map:
                continue
            if token_id in temporal_features:
                continue  # already extracted from an earlier hour

            info = contract_map[token_id]
            feat = extract_temporal_features(
                group, token_id, info["outcome"], info["period_open"]
            )
            if feat is not None:
                temporal_features[token_id] = feat

        del df

        if hours_ok % 10 == 0:
            print(f"  {hours_ok} hours | {len(temporal_features)} contracts extracted | "
                  f"{time.time()-t_start:.0f}s")

feats = list(temporal_features.values())
print(f"  Done: {len(feats)} contracts with temporal features ({time.time()-t_start:.0f}s)")

# Save features for analysis
feat_df = pd.DataFrame([asdict(f) for f in feats])
feat_df.to_csv(OUT / "polymarket_5m_temporal_features.csv", index=False)

# ===================================================================
# 3. Feature analysis
# ===================================================================
print("\n[3/5] Feature analysis...")

up = feat_df[feat_df["outcome"] == 1]
dn = feat_df[feat_df["outcome"] == 0]

signals = ["obi_10s", "obi_30s", "obi_60s", "obi_vel_10_30", "obi_vel_30_60",
           "obi_accel", "mid_drift", "flow_accel", "buy_rate_0_30"]

from scipy import stats

print(f"\n  {'Signal':<20} {'UP mean':>10} {'DN mean':>10} {'Diff':>10} {'t-stat':>8} {'p-val':>8} {'Info':>6}")
print(f"  {'-'*80}")
for sig in signals:
    if sig not in feat_df.columns:
        continue
    u = up[sig].dropna()
    d = dn[sig].dropna()
    if len(u) < 5 or len(d) < 5:
        continue
    t_stat, p_val = stats.ttest_ind(u, d)
    diff = u.mean() - d.mean()
    info = "***" if p_val < 0.001 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
    print(f"  {sig:<20} {u.mean():>10.4f} {d.mean():>10.4f} {diff:>10.4f} {t_stat:>8.2f} {p_val:>8.4f} {info:>6}")

# ===================================================================
# 4A. Strategy 1: Temporal OBI grid search
# ===================================================================
print("\n[4A/5] Temporal OBI velocity backtest...")

TEMPORAL_GRID = {
    "signal_col": ["obi_vel_10_30", "obi_vel_30_60", "obi_accel",
                    "flow_accel", "obi_30s", "mid_drift"],
    "threshold": [0.0001, 0.0005, 0.001, 0.005, 0.01],
    "signal_mode": ["follow", "fade"],
    "max_spread": [0.05, 0.10],
}

combos = list(itertools.product(*TEMPORAL_GRID.values()))
print(f"  {len(combos)} combinations")

temporal_results = []
for combo in tqdm(combos, desc="Temporal OBI"):
    params = dict(zip(TEMPORAL_GRID.keys(), combo))
    try:
        m = backtest_temporal_obi(feats, **params)
        temporal_results.append({**params, **m})
    except Exception as e:
        temporal_results.append({**params, "error": str(e), "n_trades": 0})

tgrid = pd.DataFrame(temporal_results)
tgrid.to_csv(OUT / "polymarket_5m_temporal_grid.csv", index=False)

# ===================================================================
# 4B. Strategy 2: Market-Making grid search
# ===================================================================
print("\n[4B/5] Market-making backtest...")

MM_GRID = {
    "half_spread": [0.005, 0.01, 0.015, 0.02, 0.03],
    "obi_skew_factor": [0.0, 0.25, 0.5, 1.0, 2.0],
    "contracts_per_quote": [5.0, 10.0, 20.0],
}

mm_combos = list(itertools.product(*MM_GRID.values()))
print(f"  {len(mm_combos)} combinations")

mm_results = []
for combo in tqdm(mm_combos, desc="Market-Making"):
    params = dict(zip(MM_GRID.keys(), combo))
    try:
        m = backtest_market_maker(feats, **params)
        mm_results.append({**params, **m})
    except Exception as e:
        mm_results.append({**params, "error": str(e), "n_trades": 0})

mgrid = pd.DataFrame(mm_results)
mgrid.to_csv(OUT / "polymarket_5m_mm_grid.csv", index=False)

# ===================================================================
# 5. Results
# ===================================================================
print("\n" + "=" * 60)
print(" STRATEGY 1: TEMPORAL OBI VELOCITY")
print("=" * 60)

tv = tgrid[tgrid["n_trades"] > 0].copy()
if "error" in tv.columns:
    tv = tv[tv["error"].isna()]

print(f"  Configs with trades: {len(tv)}")
if not tv.empty:
    profitable = tv[tv["total_pnl"] > 0]
    print(f"  Profitable: {len(profitable)} ({len(profitable)/len(tv):.1%})")
    print(f"  Sharpe range: {tv['sharpe'].min():.3f} to {tv['sharpe'].max():.3f}")
    print(f"  Win rate range: {tv['win_rate'].min():.2%} to {tv['win_rate'].max():.2%}")

    # By signal
    for sig in TEMPORAL_GRID["signal_col"]:
        sub = tv[tv["signal_col"] == sig]
        if not sub.empty:
            p = (sub["total_pnl"] > 0).sum()
            print(f"\n  {sig}:")
            print(f"    Profitable: {p}/{len(sub)}  Avg Sharpe: {sub['sharpe'].mean():.3f}  "
                  f"Avg WR: {sub['win_rate'].mean():.2%}  Avg PnL: ${sub['total_pnl'].mean():.0f}")

    # Follow vs fade
    for mode in ["follow", "fade"]:
        sub = tv[tv["signal_mode"] == mode]
        if not sub.empty:
            print(f"\n  {mode.upper()}: Profitable {(sub['total_pnl'] > 0).sum()}/{len(sub)}  "
                  f"Avg Sharpe={sub['sharpe'].mean():.3f}")

    print(f"\n  Top 10 by Sharpe:")
    for i, (_, row) in enumerate(tv.nlargest(10, "sharpe").iterrows()):
        p = {c: row[c] for c in TEMPORAL_GRID.keys() if c in row.index}
        print(f"  {i+1:2d}. S={row['sharpe']:8.3f} WR={row['win_rate']:.2%} "
              f"PnL=${row['total_pnl']:8.0f} N={int(row['n_trades']):4d} | {p}")

print("\n" + "=" * 60)
print(" STRATEGY 2: OBI MARKET-MAKING")
print("=" * 60)

mv = mgrid[mgrid["n_trades"] > 0].copy()
if "error" in mv.columns:
    mv = mv[mv["error"].isna()]

print(f"  Configs with trades: {len(mv)}")
if not mv.empty:
    profitable = mv[mv["total_pnl"] > 0]
    print(f"  Profitable: {len(profitable)} ({len(profitable)/len(mv):.1%})")
    print(f"  Sharpe range: {mv['sharpe'].min():.3f} to {mv['sharpe'].max():.3f}")
    print(f"  Win rate range: {mv['win_rate'].min():.2%} to {mv['win_rate'].max():.2%}")
    print(f"  Avg spread earned: ${mv['total_spread_earned'].mean():.2f}")
    print(f"  Avg both-fill rate: {mv['pct_flat'].mean():.2%}")

    # By skew factor
    print(f"\n  Impact of OBI skew:")
    for sf in sorted(MM_GRID["obi_skew_factor"]):
        sub = mv[mv["obi_skew_factor"] == sf]
        if not sub.empty:
            p = (sub["total_pnl"] > 0).sum()
            print(f"    skew={sf:.2f}: Profitable {p}/{len(sub)}  "
                  f"Avg Sharpe={sub['sharpe'].mean():.3f}  "
                  f"Avg PnL=${sub['total_pnl'].mean():.0f}  "
                  f"Avg WR={sub['win_rate'].mean():.2%}")

    print(f"\n  Top 10 by Sharpe:")
    for i, (_, row) in enumerate(mv.nlargest(10, "sharpe").iterrows()):
        p = {c: row[c] for c in MM_GRID.keys() if c in row.index}
        print(f"  {i+1:2d}. S={row['sharpe']:8.3f} WR={row['win_rate']:.2%} "
              f"PnL=${row['total_pnl']:8.0f} SpreadEarned=${row['total_spread_earned']:.0f} "
              f"BothFill={row['pct_flat']:.0%} N={int(row['n_trades'])} | {p}")

    print(f"\n  Top 5 by Total PnL:")
    for i, (_, row) in enumerate(mv.nlargest(5, "total_pnl").iterrows()):
        p = {c: row[c] for c in MM_GRID.keys() if c in row.index}
        print(f"  {i+1}. PnL=${row['total_pnl']:8.2f} S={row['sharpe']:7.3f} "
              f"WR={row['win_rate']:.2%} N={int(row['n_trades'])} | {p}")

# ===================================================================
# Plots
# ===================================================================
print("\nGenerating plots...")

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle("Temporal OBI + Market-Making Analysis", fontsize=14, fontweight="bold")

# 1. Signal informativeness
ax = axes[0, 0]
sig_stats = []
for sig in signals:
    if sig not in feat_df.columns:
        continue
    u = up[sig].dropna()
    d = dn[sig].dropna()
    if len(u) < 5 or len(d) < 5:
        continue
    t_s, p_v = stats.ttest_ind(u, d)
    sig_stats.append({"signal": sig, "t_stat": abs(t_s), "p_val": p_v})
if sig_stats:
    sdf = pd.DataFrame(sig_stats).sort_values("t_stat", ascending=True)
    colors = ["green" if p < 0.05 else "gray" for p in sdf["p_val"]]
    ax.barh(sdf["signal"], sdf["t_stat"], color=colors)
    ax.axvline(1.96, color="red", linestyle="--", alpha=0.5, label="p=0.05")
    ax.set_xlabel("|t-statistic|")
    ax.set_title("Signal Informativeness (UP vs DOWN)")
    ax.legend()

# 2. Temporal OBI: Sharpe by signal type
ax = axes[0, 1]
if not tv.empty:
    agg = tv.groupby("signal_col")["sharpe"].mean().sort_values()
    agg.plot(kind="barh", ax=ax, color="steelblue")
    ax.axvline(0, color="red", linestyle="--")
    ax.set_xlabel("Avg Sharpe")
    ax.set_title("Temporal OBI: Sharpe by Signal")

# 3. MM: Sharpe by skew factor
ax = axes[1, 0]
if not mv.empty:
    agg = mv.groupby("obi_skew_factor")["sharpe"].mean()
    ax.plot(agg.index, agg.values, "o-", color="steelblue", linewidth=2)
    ax.axhline(0, color="red", linestyle="--")
    ax.set_xlabel("OBI Skew Factor")
    ax.set_ylabel("Avg Sharpe")
    ax.set_title("Market-Making: Sharpe by OBI Skew")
    ax.grid(True, alpha=0.3)

# 4. MM: PnL by half_spread
ax = axes[1, 1]
if not mv.empty:
    for sf in [0.0, 0.5, 1.0, 2.0]:
        sub = mv[mv["obi_skew_factor"] == sf]
        if not sub.empty:
            agg = sub.groupby("half_spread")["total_pnl"].mean()
            ax.plot(agg.index, agg.values, "o-", label=f"skew={sf}", linewidth=1.5)
    ax.axhline(0, color="red", linestyle="--")
    ax.set_xlabel("Half Spread")
    ax.set_ylabel("Avg Total PnL ($)")
    ax.set_title("MM PnL by Spread Width & Skew")
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(OUT / "polymarket_temporal_mm_analysis.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"  Saved: {OUT / 'polymarket_temporal_mm_analysis.png'}")

print(f"\nAll CSVs saved to: {OUT}")
print("=" * 60)
print("DONE")
