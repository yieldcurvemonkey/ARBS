"""
OBI Kelly Criterion Backtest — Real Data
=========================================
Uses the contract-level features already computed from PMXT data.
Calibrates OBI→P(YES) on train set, then applies Kelly betting on test set.

The key insight: raw OBI is informative (t=51.6) but the market prices it in.
Kelly naturally handles this — it only bets when estimated p diverges from
market price c, sizing proportional to the edge (p - c).
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
from tqdm import tqdm

from OBI.kelly import (
    backtest_kelly,
    calibrate_obi_logistic,
    logistic_prob,
    kelly_fraction,
    calibrate_obi_to_prob,
)

OUT = Path(__file__).resolve().parent / "obi_grid_results"
FEATURES_PATH = OUT / "polymarket_5m_real_features.csv"

print("=" * 60)
print("OBI KELLY CRITERION BACKTEST (Real Data)")
print("=" * 60)

# ===================================================================
# 1. Load features
# ===================================================================
print("\n[1/5] Loading real-data features...")
features = pd.read_csv(FEATURES_PATH)
print(f"  {len(features)} contracts")
print(f"  OBI range: [{features['obi'].min():.4f}, {features['obi'].max():.4f}]")
print(f"  Outcome: {features['outcome'].sum():.0f} up / {len(features)-features['outcome'].sum():.0f} down")

# ===================================================================
# 2. Calibration analysis
# ===================================================================
print("\n[2/5] Calibration analysis...")

# Logistic fit
a, b = calibrate_obi_logistic(features)
print(f"  Logistic: P(YES) = sigmoid({a:.4f} * OBI + {b:.4f})")

# Show calibration curve
obi_range = np.linspace(-0.7, 1.0, 50)
probs = [logistic_prob(x, a, b) for x in obi_range]
print(f"  P(YES | OBI=-0.5) = {logistic_prob(-0.5, a, b):.3f}")
print(f"  P(YES | OBI= 0.0) = {logistic_prob(0.0, a, b):.3f}")
print(f"  P(YES | OBI= 0.5) = {logistic_prob(0.5, a, b):.3f}")
print(f"  P(YES | OBI= 0.8) = {logistic_prob(0.8, a, b):.3f}")

# Binned calibration
interp = calibrate_obi_to_prob(features, n_bins=15)
print(f"\n  Binned calibration (15 bins):")
for obi_val in [-0.3, 0.0, 0.3, 0.5, 0.7, 0.9]:
    print(f"    OBI={obi_val:+.1f} → P(YES)={float(interp(obi_val)):.3f}")

# Edge analysis: where does p diverge from market price?
print(f"\n  Edge analysis (logistic calibration):")
df = features.dropna(subset=["obi", "outcome", "last_bid", "last_ask"]).copy()
df["p_est"] = df["obi"].apply(lambda x: logistic_prob(x, a, b))
df["market_mid"] = (df["last_bid"] + df["last_ask"]) / 2
df["edge"] = df["p_est"] - df["market_mid"]
df["abs_edge"] = df["edge"].abs()
print(f"    Mean edge: {df['edge'].mean():.4f}")
print(f"    Median edge: {df['edge'].median():.4f}")
print(f"    Std edge: {df['edge'].std():.4f}")
print(f"    Contracts with |edge| > 0.01: {(df['abs_edge'] > 0.01).sum()}")
print(f"    Contracts with |edge| > 0.05: {(df['abs_edge'] > 0.05).sum()}")
print(f"    Contracts with |edge| > 0.10: {(df['abs_edge'] > 0.10).sum()}")

# Kelly fraction distribution
df["kelly_f"] = df.apply(lambda r: kelly_fraction(r["p_est"], r["market_mid"]), axis=1)
print(f"\n  Kelly fraction distribution:")
print(f"    Mean: {df['kelly_f'].mean():.4f}")
print(f"    Median: {df['kelly_f'].median():.4f}")
print(f"    % positive (bet YES): {(df['kelly_f'] > 0).mean():.1%}")
print(f"    % negative (bet NO): {(df['kelly_f'] < 0).mean():.1%}")
print(f"    % near-zero (|f|<0.01): {(df['kelly_f'].abs() < 0.01).mean():.1%}")

# ===================================================================
# 3. Grid search over Kelly parameters
# ===================================================================
print("\n[3/5] Kelly grid search...")

GRID = {
    "kelly_frac": [0.10, 0.25, 0.50, 1.0],
    "max_bet_pct": [0.01, 0.02, 0.05, 0.10],
    "min_edge": [0.001, 0.005, 0.01, 0.02, 0.05, 0.10],
    "calibration": ["logistic", "binned"],
    "train_frac": [0.5, 0.6, 0.7],
}

combos = list(itertools.product(*GRID.values()))
print(f"  {len(combos)} combinations")

results = []
for combo in tqdm(combos, desc="Kelly grid"):
    params = dict(zip(GRID.keys(), combo))
    try:
        m = backtest_kelly(features, **params)
        results.append({**params, **m})
    except Exception as e:
        results.append({**params, "error": str(e), "n_trades": 0})

grid_df = pd.DataFrame(results)
grid_df.to_csv(OUT / "polymarket_5m_kelly_grid.csv", index=False)

# ===================================================================
# 4. Results
# ===================================================================
print("\n[4/5] Results")
print("=" * 60)

valid = grid_df[grid_df["n_trades"] > 0].copy()
if "error" in valid.columns:
    valid = valid[valid["error"].isna()]

print(f"  Configs tested: {len(grid_df)}")
print(f"  Configs with trades: {len(valid)}")

if valid.empty:
    print("  Kelly found no edge in any configuration.")
    print("  This means the market is pricing OBI information efficiently.")
else:
    profitable = valid[valid["total_pnl"] > 0]
    print(f"  Profitable: {len(profitable)} ({len(profitable)/len(valid):.1%})")
    print(f"  Trade count range: {valid['n_trades'].min()} — {valid['n_trades'].max()}")
    print(f"  Sharpe range: {valid['sharpe'].min():.3f} — {valid['sharpe'].max():.3f}")
    print(f"  Win rate range: {valid['win_rate'].min():.2%} — {valid['win_rate'].max():.2%}")
    print(f"  Avg edge: {valid['avg_edge'].mean():.4f}")
    print(f"  Avg Kelly f: {valid['avg_kelly_f'].mean():.4f}")
    print(f"  Avg dollar bet: ${valid['avg_dollar_bet'].mean():.2f}")

    # By calibration method
    for cal in ["logistic", "binned"]:
        c = valid[valid["calibration"] == cal]
        if not c.empty:
            print(f"\n  {cal.upper()} calibration:")
            print(f"    Profitable: {(c['total_pnl'] > 0).sum()}/{len(c)}")
            print(f"    Avg Sharpe: {c['sharpe'].mean():.3f}")
            print(f"    Avg PnL: ${c['total_pnl'].mean():.2f}")
            print(f"    Avg WR: {c['win_rate'].mean():.2%}")

    # Top configs
    print(f"\n  Top 10 by Sharpe:")
    for i, (_, row) in enumerate(valid.nlargest(10, "sharpe").iterrows()):
        params = {c: row[c] for c in GRID.keys() if c in row.index}
        print(f"  {i+1:2d}. S={row['sharpe']:8.3f} WR={row['win_rate']:.2%} "
              f"PnL=${row['total_pnl']:8.2f} DD={row['max_drawdown_pct']:5.1f}% "
              f"N={int(row['n_trades']):4d} Edge={row['avg_edge']:.4f} "
              f"$Bet={row['avg_dollar_bet']:.1f}")
        print(f"      {params}")

    print(f"\n  Top 5 by PnL:")
    for i, (_, row) in enumerate(valid.nlargest(5, "total_pnl").iterrows()):
        params = {c: row[c] for c in GRID.keys() if c in row.index}
        print(f"  {i+1}. PnL=${row['total_pnl']:8.2f} S={row['sharpe']:7.3f} "
              f"WR={row['win_rate']:.2%} N={int(row['n_trades'])} "
              f"Final=${row.get('final_capital', 0):.0f}")

    # Impact of min_edge
    print(f"\n  Impact of min_edge threshold:")
    for me in sorted(GRID["min_edge"]):
        sub = valid[valid["min_edge"] == me]
        if not sub.empty:
            print(f"    min_edge={me:.3f}: "
                  f"avg trades={sub['n_trades'].mean():.0f}  "
                  f"avg Sharpe={sub['sharpe'].mean():.3f}  "
                  f"profitable={(sub['total_pnl'] > 0).sum()}/{len(sub)}")

# ===================================================================
# 5. Plots
# ===================================================================
print("\n[5/5] Generating plots...")

# Calibration curve plot
fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("OBI Kelly Criterion Analysis", fontsize=14, fontweight="bold")

# 1. Calibration curve
ax = axes[0, 0]
obi_vals = np.linspace(-0.7, 1.0, 100)
ax.plot(obi_vals, [logistic_prob(x, a, b) for x in obi_vals], "b-", label="Logistic", linewidth=2)
try:
    ax.plot(obi_vals, [float(interp(x)) for x in obi_vals], "r--", label="Binned", linewidth=1.5)
except:
    pass
ax.axhline(0.5, color="gray", linestyle=":", alpha=0.5)
ax.axvline(0, color="gray", linestyle=":", alpha=0.5)
ax.set_xlabel("OBI")
ax.set_ylabel("P(YES wins)")
ax.set_title("OBI → Probability Calibration")
ax.legend()
ax.grid(True, alpha=0.3)

# 2. Edge distribution
ax = axes[0, 1]
if "edge" in df.columns:
    ax.hist(df["edge"], bins=50, color="steelblue", alpha=0.7, edgecolor="white")
    ax.axvline(0, color="red", linestyle="--")
    ax.set_xlabel("Edge (p_est - market_price)")
    ax.set_title(f"Edge Distribution (mean={df['edge'].mean():.4f})")
    ax.grid(True, alpha=0.3)

# 3. Kelly fraction by outcome
ax = axes[1, 0]
if "kelly_f" in df.columns:
    up = df[df["outcome"] == 1]["kelly_f"]
    dn = df[df["outcome"] == 0]["kelly_f"]
    ax.hist(up, bins=40, alpha=0.5, label="UP (won)", color="green")
    ax.hist(dn, bins=40, alpha=0.5, label="DOWN (won)", color="red")
    ax.axvline(0, color="black", linestyle="--")
    ax.set_xlabel("Kelly Fraction (f*)")
    ax.set_title("Kelly Fraction by Actual Outcome")
    ax.legend()
    ax.grid(True, alpha=0.3)

# 4. Sharpe vs min_edge
ax = axes[1, 1]
if not valid.empty:
    for cal in ["logistic", "binned"]:
        sub = valid[valid["calibration"] == cal]
        if not sub.empty:
            agg = sub.groupby("min_edge")["sharpe"].mean()
            ax.plot(agg.index, agg.values, "o-", label=cal, linewidth=2)
    ax.axhline(0, color="red", linestyle="--", alpha=0.5)
    ax.set_xlabel("min_edge threshold")
    ax.set_ylabel("Avg Sharpe")
    ax.set_title("Sharpe vs Min Edge Threshold")
    ax.legend()
    ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(OUT / "polymarket_5m_kelly_analysis.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"  Saved: {OUT / 'polymarket_5m_kelly_analysis.png'}")

# Equity curve for best config
if not valid.empty:
    best = valid.nlargest(1, "sharpe").iloc[0]
    params = {c: best[c] for c in GRID.keys() if c in best.index}
    print(f"\n  Best config: {params}")
    print(f"  Sharpe={best['sharpe']:.3f} WR={best['win_rate']:.2%} PnL=${best['total_pnl']:.2f}")

print(f"\nAll results saved to: {OUT}")
print("=" * 60)
print("DONE")
