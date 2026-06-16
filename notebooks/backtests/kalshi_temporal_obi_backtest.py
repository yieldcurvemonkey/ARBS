"""
Kalshi Temporal OBI Backtest — Multiple Market Types
=====================================================
Tests OBI velocity signals across BTC, sports, and other Kalshi markets
using real trade data collected via WebSocket.

Approach: For each market, compute OBI from trade flow (taker_side)
over early windows, then test if early flow velocity predicts final
settlement direction.
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
from scipy import stats
from tqdm import tqdm

from OBI.kalshi_lob.storage import LOBStorage
import datetime

OUT = Path(__file__).resolve().parent / "obi_grid_results"
OUT.mkdir(exist_ok=True)

print("=" * 60)
print("KALSHI TEMPORAL OBI BACKTEST")
print("=" * 60)

# ===================================================================
# 1. Load trades
# ===================================================================
print("\n[1/5] Loading Kalshi trade data...")
storage = LOBStorage()
trades = storage.read_trades(datetime.date(2026, 6, 4))
print(f"  {len(trades)} trades across {trades['market_ticker'].nunique()} markets")

# Categorize markets
trades["prefix"] = trades["market_ticker"].str.extract(r"^(KX[A-Z0-9]+)")

# Focus on high-volume categories with resolution data
CATEGORIES = {
    "BTC_hourly": trades["market_ticker"].str.match(r"KXBTC-"),
    "BTC_daily": trades["market_ticker"].str.match(r"KXBTCD-"),
    "BTC_15m": trades["market_ticker"].str.match(r"KXBTC15M-"),
    "MLB": trades["prefix"] == "KXMLBGAME",
    "Soccer": trades["prefix"].isin(["KXINTLFRIENDLYGAME", "KXWTAMATCH", "KXITFWMATCH", "KXITFMATCH"]),
    "Tennis": trades["prefix"].isin(["KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH"]),
    "Esports": trades["prefix"].isin(["KXMVESPORTSMULTIGAMEEXTENDED", "KXCS"]),
    "ETH": trades["prefix"] == "KXETH",
}

for cat, mask in CATEGORIES.items():
    sub = trades[mask]
    print(f"  {cat}: {sub['market_ticker'].nunique()} markets, {len(sub)} trades, "
          f"{sub['count'].sum():.0f} contracts")

# ===================================================================
# 2. Build per-market temporal features from trade flow
# ===================================================================
print("\n[2/5] Building temporal features from trade flow...")


def build_trade_features(market_trades: pd.DataFrame, ticker: str) -> dict:
    """Compute temporal OBI features from a market's trade stream.

    OBI is computed from taker_side: 'yes' = buyer aggressor (bullish),
    'no' = seller aggressor (bearish).
    """
    mt = market_trades.sort_values("ts")
    if len(mt) < 3:
        return None

    t0 = mt["ts"].min()
    mt["elapsed_s"] = (mt["ts"] - t0).dt.total_seconds()
    total_duration = mt["elapsed_s"].max()

    if total_duration < 10:
        return None

    def window_obi(df, t_start, t_end):
        w = df[(df["elapsed_s"] >= t_start) & (df["elapsed_s"] < t_end)]
        if w.empty:
            return 0.0, 0, 0, 0
        yes_vol = w[w["taker_side"] == "yes"]["count"].sum()
        no_vol = w[w["taker_side"] == "no"]["count"].sum()
        total = yes_vol + no_vol
        obi = (yes_vol - no_vol) / total if total > 0 else 0.0
        return obi, yes_vol, no_vol, len(w)

    # Early windows
    obi_10, yv10, nv10, n10 = window_obi(mt, 0, 10)
    obi_30, yv30, nv30, n30 = window_obi(mt, 0, 30)
    obi_60, yv60, nv60, n60 = window_obi(mt, 0, 60)
    obi_30_60, _, _, _ = window_obi(mt, 30, 60)

    # Last trade price as proxy for settlement direction
    last_yes = mt["yes_price"].iloc[-1]
    first_yes = mt["yes_price"].iloc[0]
    price_direction = 1 if last_yes > 0.5 else 0

    # Volume-weighted average price
    vwap_yes = (mt["yes_price"] * mt["count"]).sum() / mt["count"].sum() if mt["count"].sum() > 0 else 0.5

    # Mid-price drift
    early_price = mt[mt["elapsed_s"] < 30]["yes_price"].mean() if n30 > 0 else 0.5
    late_price = mt[mt["elapsed_s"] >= max(total_duration * 0.7, 30)]["yes_price"].mean()
    if pd.isna(late_price):
        late_price = last_yes
    mid_drift = late_price - early_price

    # OBI velocity
    vel_10_30 = (obi_30 - obi_10) / 20.0 if n10 > 0 else 0.0
    vel_30_60 = (obi_60 - obi_30) / 30.0 if n30 > 0 and n60 > 0 else 0.0

    # Trade rate
    trade_rate_0_30 = n30 / 30.0
    trade_rate_30_60 = (n60 - n30) / 30.0 if n60 > n30 else 0.0

    return {
        "ticker": ticker,
        "n_trades": len(mt),
        "total_volume": mt["count"].sum(),
        "total_duration": total_duration,
        "obi_10s": obi_10,
        "obi_30s": obi_30,
        "obi_60s": obi_60,
        "obi_vel_10_30": vel_10_30,
        "obi_vel_30_60": vel_30_60,
        "mid_drift": mid_drift,
        "trade_rate_0_30": trade_rate_0_30,
        "trade_rate_accel": trade_rate_30_60 - trade_rate_0_30,
        "first_yes_price": first_yes,
        "last_yes_price": last_yes,
        "vwap_yes": vwap_yes,
        "outcome": price_direction,  # 1 = settled YES, 0 = settled NO
    }


all_features = {}
for cat, mask in CATEGORIES.items():
    cat_trades = trades[mask]
    feats = []
    for ticker, group in cat_trades.groupby("market_ticker"):
        f = build_trade_features(group, ticker)
        if f:
            f["category"] = cat
            feats.append(f)
    all_features[cat] = feats
    print(f"  {cat}: {len(feats)} markets with features")

# Combine
all_feats = []
for feats in all_features.values():
    all_feats.extend(feats)
feat_df = pd.DataFrame(all_feats)
feat_df.to_csv(OUT / "kalshi_temporal_features.csv", index=False)
print(f"  Total: {len(feat_df)} markets with features")

# ===================================================================
# 3. Signal analysis per category
# ===================================================================
print("\n[3/5] Signal analysis by market category...")

signals = ["obi_10s", "obi_30s", "obi_60s", "obi_vel_10_30",
           "obi_vel_30_60", "mid_drift", "trade_rate_accel"]

for cat in CATEGORIES:
    cdf = feat_df[feat_df["category"] == cat]
    if len(cdf) < 20:
        continue
    up = cdf[cdf["outcome"] == 1]
    dn = cdf[cdf["outcome"] == 0]
    if len(up) < 5 or len(dn) < 5:
        continue

    print(f"\n  {cat} ({len(cdf)} markets, {up.shape[0]} YES / {dn.shape[0]} NO):")
    for sig in signals:
        if sig not in cdf.columns:
            continue
        u = up[sig].dropna()
        d = dn[sig].dropna()
        if len(u) < 3 or len(d) < 3:
            continue
        t_s, p_v = stats.ttest_ind(u, d)
        diff = u.mean() - d.mean()
        star = "***" if p_v < 0.001 else ("**" if p_v < 0.01 else ("*" if p_v < 0.05 else ""))
        print(f"    {sig:<20} diff={diff:+.4f}  t={t_s:+.2f}  p={p_v:.4f} {star}")

# ===================================================================
# 4. Backtest per category
# ===================================================================
print("\n[4/5] Backtesting per category...")

GRID = {
    "signal_col": ["obi_vel_10_30", "obi_vel_30_60", "mid_drift", "obi_30s"],
    "threshold": [0.001, 0.005, 0.01, 0.05],
    "signal_mode": ["follow", "fade"],
}
combos = list(itertools.product(*GRID.values()))

results_by_cat = {}
for cat in CATEGORIES:
    cdf = feat_df[feat_df["category"] == cat]
    if len(cdf) < 20:
        continue

    cat_results = []
    for combo in combos:
        params = dict(zip(GRID.keys(), combo))
        sig_col = params["signal_col"]
        threshold = params["threshold"]
        mode = params["signal_mode"]

        eligible = cdf[cdf[sig_col].abs() >= threshold].copy()
        if eligible.empty:
            continue

        capital = 10_000.0
        current = capital
        pnls = []

        for _, row in eligible.iterrows():
            sig = row[sig_col]
            direction = 1 if sig > 0 else -1
            if mode == "fade":
                direction = -direction

            side = "YES" if direction > 0 else "NO"
            entry = row["first_yes_price"] if side == "YES" else (1 - row["first_yes_price"])
            entry = np.clip(entry, 0.01, 0.99)

            qty = min(10, current * 0.95 / max(entry, 0.01))
            qty = max(1, int(qty))

            won = (side == "YES" and row["outcome"] == 1) or (side == "NO" and row["outcome"] == 0)
            pnl = qty * ((1.0 if won else 0.0) - entry)
            fee = qty * entry * 0.07  # Kalshi fees
            net = pnl - fee
            current += net
            pnls.append({"net_pnl": net, "won": won})

        if not pnls:
            continue

        pnl_arr = np.array([p["net_pnl"] for p in pnls])
        wins = sum(p["won"] for p in pnls)
        n = len(pnl_arr)
        mu = pnl_arr.mean()
        sigma = pnl_arr.std() if n > 1 else 1e-8
        sharpe = mu / max(sigma, 1e-8) * np.sqrt(252 * 24)

        cat_results.append({
            **params,
            "n_trades": n,
            "win_rate": round(wins / n, 4),
            "total_pnl": round(pnl_arr.sum(), 2),
            "sharpe": round(sharpe, 4),
            "avg_pnl": round(mu, 4),
        })

    if cat_results:
        rdf = pd.DataFrame(cat_results)
        results_by_cat[cat] = rdf
        rdf.to_csv(OUT / f"kalshi_temporal_{cat}_grid.csv", index=False)

# ===================================================================
# 5. Results
# ===================================================================
print("\n" + "=" * 60)
print(" KALSHI TEMPORAL OBI — RESULTS BY MARKET")
print("=" * 60)

for cat, rdf in results_by_cat.items():
    traded = rdf[rdf["n_trades"] > 0]
    if traded.empty:
        continue

    profitable = traded[traded["total_pnl"] > 0]
    print(f"\n  {cat.upper()}")
    print(f"  {'='*50}")
    print(f"    Configs: {len(traded)}  Profitable: {len(profitable)} ({len(profitable)/len(traded):.0%})")
    print(f"    Sharpe: {traded['sharpe'].min():.1f} to {traded['sharpe'].max():.1f}")
    print(f"    Win rate: {traded['win_rate'].min():.1%} to {traded['win_rate'].max():.1%}")

    for mode in ["follow", "fade"]:
        sub = traded[traded["signal_mode"] == mode]
        if not sub.empty:
            p = (sub["total_pnl"] > 0).sum()
            print(f"    {mode}: {p}/{len(sub)} profitable, avg Sharpe={sub['sharpe'].mean():.1f}")

    top3 = traded.nlargest(3, "sharpe")
    print(f"    Top 3:")
    for _, row in top3.iterrows():
        p = {c: row[c] for c in GRID.keys()}
        print(f"      S={row['sharpe']:7.1f} WR={row['win_rate']:.1%} "
              f"PnL=${row['total_pnl']:7.0f} N={int(row['n_trades'])} | {p}")

# Summary table
print(f"\n  {'='*60}")
print(f"  SUMMARY")
print(f"  {'='*60}")
print(f"  {'Category':<15} {'Configs':>8} {'Profitable':>11} {'Best Sharpe':>12} {'Best WR':>8}")
for cat, rdf in results_by_cat.items():
    traded = rdf[rdf["n_trades"] > 0]
    p = (traded["total_pnl"] > 0).sum()
    print(f"  {cat:<15} {len(traded):>8} {p:>8} ({p/max(len(traded),1):.0%}) "
          f"{traded['sharpe'].max():>12.1f} {traded['win_rate'].max():>7.1%}")

# Plot
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle("Kalshi Temporal OBI — Multi-Market Results", fontsize=14, fontweight="bold")

ax = axes[0, 0]
cat_sharpes = {c: r["sharpe"].max() for c, r in results_by_cat.items() if len(r) > 0}
if cat_sharpes:
    cats = sorted(cat_sharpes.keys(), key=lambda x: cat_sharpes[x])
    vals = [cat_sharpes[c] for c in cats]
    colors = ["green" if v > 0 else "red" for v in vals]
    ax.barh(cats, vals, color=colors)
    ax.axvline(0, color="black", linestyle="--")
    ax.set_xlabel("Best Sharpe")
    ax.set_title("Best Sharpe by Market Category")

ax = axes[0, 1]
cat_pct = {c: (r["total_pnl"] > 0).mean() for c, r in results_by_cat.items() if len(r) > 0}
if cat_pct:
    cats = sorted(cat_pct.keys(), key=lambda x: cat_pct[x])
    vals = [cat_pct[c] * 100 for c in cats]
    ax.barh(cats, vals, color="steelblue")
    ax.axvline(50, color="red", linestyle="--")
    ax.set_xlabel("% Configs Profitable")
    ax.set_title("Profitability Rate by Market")

ax = axes[1, 0]
for cat, rdf in results_by_cat.items():
    if len(rdf) < 5:
        continue
    agg = rdf.groupby("signal_col")["sharpe"].mean()
    ax.plot(range(len(agg)), agg.values, "o-", label=cat, markersize=4)
    ax.set_xticks(range(len(agg)))
    ax.set_xticklabels(agg.index, rotation=45, ha="right")
ax.axhline(0, color="red", linestyle="--")
ax.set_ylabel("Avg Sharpe")
ax.set_title("Signal Performance by Market")
ax.legend(fontsize=7, loc="best")

ax = axes[1, 1]
for cat, rdf in results_by_cat.items():
    if len(rdf) < 5:
        continue
    f = rdf[rdf["signal_mode"] == "follow"]["sharpe"].mean()
    d = rdf[rdf["signal_mode"] == "fade"]["sharpe"].mean()
    ax.scatter(f, d, s=100, label=cat)
ax.plot([-100, 100], [-100, 100], "k--", alpha=0.3)
ax.set_xlabel("Follow Sharpe")
ax.set_ylabel("Fade Sharpe")
ax.set_title("Follow vs Fade by Market")
ax.legend(fontsize=7)
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(OUT / "kalshi_temporal_obi_results.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Plot saved: {OUT / 'kalshi_temporal_obi_results.png'}")
print("DONE")
