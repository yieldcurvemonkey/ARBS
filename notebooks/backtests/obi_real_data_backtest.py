"""
OBI Real-Data Backtest using PMXT Polymarket Order Book Archive
================================================================
Streaming approach: processes one hour at a time, never loads full dataset.
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

from OBI.pmxt_fetcher import load_btc_5m_meta, fetch_pmxt_hour
from OBI.config import BacktestConfig

OUT = Path(__file__).resolve().parent / "obi_grid_results"
OUT.mkdir(exist_ok=True)

print("=" * 60)
print("OBI REAL-DATA BACKTEST (PMXT — streaming)")
print("=" * 60)

# ===================================================================
# 1. Load metadata — group contracts by hour of resolution
# ===================================================================
print("\n[1/4] Loading metadata...")
meta = load_btc_5m_meta(start_date="2026-05-20", end_date="2026-05-26")
meta["res_hour"] = meta["resolution_time_utc"].dt.floor("h")
meta["open_hour"] = meta["period_open_utc"].dt.floor("h")
print(f"  {len(meta)} contracts, {meta['outcome'].sum():.0f} up / {len(meta)-meta['outcome'].sum():.0f} down")

# Build lookup: yes_token_id -> contract info
contract_map = {}
for _, row in meta.iterrows():
    contract_map[row["yes_token_id"]] = {
        "outcome": float(row["outcome"]),
        "resolution_time": row["resolution_time_utc"],
        "period_open": row["period_open_utc"],
        "volume": row.get("volume", 0),
    }

# Group tokens by hour they're active in (open hour)
hour_tokens = {}
for _, row in meta.iterrows():
    # Contract is active during the hour it opens in
    h_key = row["open_hour"].strftime("%Y-%m-%dT%H")
    hour_tokens.setdefault(h_key, set()).add(row["yes_token_id"])
    # Also the resolution hour if different
    rh_key = row["res_hour"].strftime("%Y-%m-%dT%H")
    hour_tokens.setdefault(rh_key, set()).add(row["yes_token_id"])

# ===================================================================
# 2. Stream through hours, build per-contract OBI summaries
# ===================================================================
print("\n[2/4] Streaming PMXT data hour-by-hour...")

contract_obi = {}  # token_id -> {cum_bid, cum_ask, n_ticks, mid_prices, spreads, ...}

dates = pd.date_range("2026-05-20", "2026-05-26", freq="D")
hours_ok = 0
hours_miss = 0
total_ticks = 0
t_start = time.time()

for date in dates:
    ds = date.strftime("%Y-%m-%d")
    for h in range(24):
        h_key = f"{ds}T{h:02d}"
        relevant_tokens = hour_tokens.get(h_key, set())
        if not relevant_tokens:
            hours_miss += 1
            continue

        df = fetch_pmxt_hour(ds, h, token_ids=list(relevant_tokens), cache=True)
        if df.empty:
            hours_miss += 1
            continue

        hours_ok += 1
        total_ticks += len(df)

        # Process each contract's ticks in this hour
        for token_id, group in df.groupby("asset_id"):
            if token_id not in contract_map:
                continue

            info = contract_map[token_id]
            g = group.sort_values("timestamp")

            valid = g.dropna(subset=["best_bid", "best_ask"])
            valid = valid[(valid["best_bid"] > 0) & (valid["best_ask"] > 0)]

            if valid.empty:
                continue

            buys = valid[valid["side"] == "BUY"]["size"].sum() if "side" in valid.columns else 0
            sells = valid[valid["side"] == "SELL"]["size"].sum() if "side" in valid.columns else 0
            spreads = (valid["best_ask"] - valid["best_bid"]).values
            mids = ((valid["best_bid"] + valid["best_ask"]) / 2).values
            bids_arr = valid["best_bid"].values
            asks_arr = valid["best_ask"].values

            if token_id not in contract_obi:
                contract_obi[token_id] = {
                    "cum_buy": 0, "cum_sell": 0, "n_ticks": 0,
                    "spreads": [], "mids": [], "bids": [], "asks": [],
                    "outcome": info["outcome"],
                    "resolution_time": info["resolution_time"],
                    "period_open": info["period_open"],
                }

            c = contract_obi[token_id]
            c["cum_buy"] += buys
            c["cum_sell"] += sells
            c["n_ticks"] += len(valid)
            c["spreads"].extend(spreads.tolist())
            c["mids"].extend(mids.tolist())
            c["bids"].extend(bids_arr.tolist())
            c["asks"].extend(asks_arr.tolist())

        if hours_ok % 10 == 0:
            elapsed = time.time() - t_start
            print(f"  {hours_ok} hours done | {total_ticks:,} ticks | "
                  f"{len(contract_obi)} contracts | {elapsed:.0f}s")

        del df  # free memory

elapsed = time.time() - t_start
print(f"  Done: {hours_ok} hours, {hours_miss} missed, {total_ticks:,} ticks, "
      f"{len(contract_obi)} contracts ({elapsed:.0f}s)")

# ===================================================================
# 3. Build contract-level feature table
# ===================================================================
print("\n[3/4] Building contract features...")
rows = []
for token_id, c in contract_obi.items():
    total_flow = c["cum_buy"] + c["cum_sell"]
    obi = (c["cum_buy"] - c["cum_sell"]) / total_flow if total_flow > 0 else 0
    med_spread = float(np.median(c["spreads"])) if c["spreads"] else 0
    med_mid = float(np.median(c["mids"])) if c["mids"] else 0.5
    last_bid = c["bids"][-1] if c["bids"] else 0
    last_ask = c["asks"][-1] if c["asks"] else 1

    rows.append({
        "token_id": token_id,
        "obi": obi,
        "cum_buy": c["cum_buy"],
        "cum_sell": c["cum_sell"],
        "total_flow": total_flow,
        "n_ticks": c["n_ticks"],
        "median_spread": med_spread,
        "median_mid": med_mid,
        "last_bid": last_bid,
        "last_ask": last_ask,
        "outcome": c["outcome"],
    })

features = pd.DataFrame(rows)
features.to_csv(OUT / "polymarket_5m_real_features.csv", index=False)
print(f"  {len(features)} contracts with features")
print(f"  OBI range: [{features['obi'].min():.4f}, {features['obi'].max():.4f}]")
print(f"  Median spread: {features['median_spread'].median():.4f}")
print(f"  Median ticks/contract: {features['n_ticks'].median():.0f}")
print(f"  Contracts with >100 ticks: {(features['n_ticks'] > 100).sum()}")

# ===================================================================
# 4. Grid search backtest on real features
# ===================================================================
print("\n[4/4] Running grid search...")


def backtest_features(
    df: pd.DataFrame,
    entry_threshold: float = 0.15,
    signal_mode: str = "follow",
    max_spread: float = 0.10,
    min_ticks: int = 10,
    fixed_size: float = 10.0,
    entry_fee_pct: float = 0.02,
    capital: float = 10_000.0,
) -> dict:
    eligible = df[(df["n_ticks"] >= min_ticks) & (df["median_spread"] <= max_spread)].copy()
    if eligible.empty:
        return {"n_trades": 0, "win_rate": 0, "total_pnl": 0, "sharpe": 0,
                "max_drawdown_pct": 0, "profit_factor": 0, "n_eligible": 0}

    triggered = eligible[eligible["obi"].abs() >= entry_threshold].copy()
    if triggered.empty:
        return {"n_trades": 0, "win_rate": 0, "total_pnl": 0, "sharpe": 0,
                "max_drawdown_pct": 0, "profit_factor": 0,
                "n_eligible": len(eligible)}

    # Generate trades
    trades = []
    current_capital = capital
    for _, row in triggered.iterrows():
        obi = row["obi"]
        signal = 1 if obi > 0 else -1
        if signal_mode == "fade":
            signal = -signal

        side = "YES" if signal > 0 else "NO"
        entry_price = row["last_ask"] if side == "YES" else (1.0 - row["last_bid"])
        entry_price = np.clip(entry_price, 0.01, 0.99)

        qty = min(fixed_size, current_capital * 0.95 / max(entry_price, 0.01))
        qty = max(1, int(qty))

        won = (side == "YES" and row["outcome"] == 1) or (side == "NO" and row["outcome"] == 0)
        exit_price = 1.0 if won else 0.0
        pnl = qty * (exit_price - entry_price)
        fee = qty * entry_price * entry_fee_pct
        net = pnl - fee
        current_capital += net
        trades.append({"net_pnl": net, "won": won, "side": side, "spread": row["median_spread"]})

    tdf = pd.DataFrame(trades)
    n = len(tdf)
    wins = int(tdf["won"].sum())
    pnls = tdf["net_pnl"].values

    eq = capital + np.cumsum(pnls)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / np.clip(peak, 1, None)
    max_dd = abs(dd.min()) * 100

    mu, sigma = pnls.mean(), pnls.std() if n > 1 else 1e-8
    sharpe = mu / max(sigma, 1e-8) * np.sqrt(252 * 288)

    wins_pnl = pnls[pnls > 0].sum()
    loss_pnl = abs(pnls[pnls <= 0].sum())
    pf = wins_pnl / max(loss_pnl, 1e-8)

    return {
        "n_eligible": len(eligible),
        "n_trades": n,
        "n_wins": wins,
        "win_rate": round(wins / n, 4),
        "total_pnl": round(pnls.sum(), 2),
        "roi_pct": round(pnls.sum() / capital * 100, 2),
        "sharpe": round(sharpe, 4),
        "max_drawdown_pct": round(max_dd, 2),
        "profit_factor": round(pf, 4),
        "avg_pnl": round(mu, 4),
        "avg_spread": round(tdf["spread"].mean(), 4),
        "pct_yes": round((tdf["side"] == "YES").mean(), 4),
    }


GRID = {
    "entry_threshold": [0.01, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50],
    "signal_mode": ["follow", "fade"],
    "max_spread": [0.03, 0.05, 0.10, 0.20],
    "min_ticks": [5, 10, 50, 100],
}

combos = list(itertools.product(*GRID.values()))
print(f"  Grid: {len(combos)} combinations")

results = []
for combo in tqdm(combos, desc="Grid"):
    params = dict(zip(GRID.keys(), combo))
    try:
        m = backtest_features(features, **params)
        results.append({**params, **m})
    except Exception as e:
        results.append({**params, "error": str(e)})

grid_df = pd.DataFrame(results)
grid_df.to_csv(OUT / "polymarket_5m_real_grid.csv", index=False)

# ===================================================================
# Results
# ===================================================================
print("\n" + "=" * 60)
print(" REAL-DATA RESULTS")
print("=" * 60)

valid = grid_df.dropna(subset=["sharpe"])
if "error" in valid.columns:
    valid = valid[valid["error"].isna()]
traded = valid[valid["n_trades"] > 0]

print(f"  Configs tested: {len(valid)}")
print(f"  Configs with trades: {len(traded)}")

if traded.empty:
    print("  No configs produced trades.")
else:
    print(f"  Profitable: {(traded['total_pnl'] > 0).sum()} ({(traded['total_pnl'] > 0).mean():.1%})")
    print(f"  Win rate range: {traded['win_rate'].min():.2%} — {traded['win_rate'].max():.2%}")
    print(f"  Sharpe range: {traded['sharpe'].min():.3f} — {traded['sharpe'].max():.3f}")
    print(f"  Trades/config: {traded['n_trades'].min()} — {traded['n_trades'].max()}")
    print(f"  Avg spread: {traded['avg_spread'].mean():.4f}")

    # Follow vs Fade
    for mode in ["follow", "fade"]:
        m = traded[traded["signal_mode"] == mode]
        if not m.empty:
            print(f"\n  {mode.upper()}:")
            print(f"    Avg WR={m['win_rate'].mean():.2%}  Avg Sharpe={m['sharpe'].mean():.3f}  "
                  f"Avg PnL=${m['total_pnl'].mean():.0f}")

    print(f"\n  Top 10 by Sharpe:")
    for i, (_, row) in enumerate(traded.nlargest(10, "sharpe").iterrows()):
        params = {c: row[c] for c in GRID.keys() if c in row.index}
        print(f"  {i+1:2d}. S={row['sharpe']:7.3f} WR={row['win_rate']:.2%} "
              f"PnL=${row['total_pnl']:7.0f} DD={row['max_drawdown_pct']:5.1f}% "
              f"N={int(row['n_trades'])} | {params}")

    print(f"\n  Top 5 by Win Rate (min 20 trades):")
    wr_eligible = traded[traded["n_trades"] >= 20]
    for i, (_, row) in enumerate(wr_eligible.nlargest(5, "win_rate").iterrows()):
        params = {c: row[c] for c in GRID.keys() if c in row.index}
        print(f"  {i+1}. WR={row['win_rate']:.2%} S={row['sharpe']:7.3f} "
              f"PnL=${row['total_pnl']:7.0f} N={int(row['n_trades'])} | {params}")

    # OBI distribution by outcome
    print(f"\n  OBI Distribution (real data):")
    up = features[features["outcome"] == 1]["obi"]
    dn = features[features["outcome"] == 0]["obi"]
    print(f"    UP contracts:   mean OBI={up.mean():.4f}  median={up.median():.4f}  std={up.std():.4f}")
    print(f"    DOWN contracts: mean OBI={dn.mean():.4f}  median={dn.median():.4f}  std={dn.std():.4f}")
    diff = up.mean() - dn.mean()
    print(f"    Difference: {diff:.4f}  (positive = OBI is informative)")

    from scipy import stats
    t_stat, p_val = stats.ttest_ind(up.dropna(), dn.dropna())
    print(f"    t-test: t={t_stat:.3f}  p={p_val:.4f}  {'SIGNIFICANT' if p_val < 0.05 else 'not significant'}")

print(f"\nAll results saved to: {OUT}")
print("DONE")
