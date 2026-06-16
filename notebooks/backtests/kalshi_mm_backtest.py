"""
Kalshi OBI Market-Making Backtest — Multiple Market Types
==========================================================
Tests market-making with OBI inventory skew across BTC, sports,
and other Kalshi markets using real trade data.

Approach: For each market, simulate posting resting orders at bid/ask.
Use trade flow (taker_side) to determine fills and OBI to skew quotes
for inventory management.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from tqdm import tqdm

from OBI.kalshi_lob.storage import LOBStorage
import datetime

OUT = Path(__file__).resolve().parent / "obi_grid_results"
OUT.mkdir(exist_ok=True)

print("=" * 60)
print("KALSHI MARKET-MAKING BACKTEST")
print("=" * 60)

# ===================================================================
# 1. Load trades
# ===================================================================
print("\n[1/4] Loading Kalshi trade data...")
storage = LOBStorage()
trades = storage.read_trades(datetime.date(2026, 6, 4))
trades["prefix"] = trades["market_ticker"].str.extract(r"^(KX[A-Z0-9]+)")
print(f"  {len(trades)} trades, {trades['market_ticker'].nunique()} markets")

CATEGORIES = {
    "BTC_hourly": trades["market_ticker"].str.match(r"KXBTC-"),
    "BTC_daily": trades["market_ticker"].str.match(r"KXBTCD-"),
    "MLB": trades["prefix"] == "KXMLBGAME",
    "Soccer": trades["prefix"].isin(["KXINTLFRIENDLYGAME", "KXWTAMATCH"]),
    "Tennis": trades["prefix"].isin(["KXATPCHALLENGERMATCH", "KXWTACHALLENGERMATCH"]),
    "Esports": trades["prefix"].isin(["KXMVESPORTSMULTIGAMEEXTENDED", "KXCS"]),
}

# ===================================================================
# 2. Market-making simulation per market
# ===================================================================
print("\n[2/4] Running market-making simulation...")


def simulate_mm_market(
    market_trades: pd.DataFrame,
    ticker: str,
    half_spread: float = 0.02,
    obi_skew_factor: float = 1.0,
    qty_per_quote: float = 5.0,
    obi_window: int = 10,
    fee_pct: float = 0.07,
) -> dict:
    """Simulate market-making on one market using trade-by-trade data.

    For each trade:
    1. Compute running OBI from last N trades
    2. Set our bid/ask around the running mid, skewed by OBI
    3. If the trade crosses our level, we get filled
    4. Track inventory and mark to market
    """
    mt = market_trades.sort_values("ts").reset_index(drop=True)
    if len(mt) < 10:
        return None

    inventory = 0.0
    cash = 0.0
    total_fees = 0.0
    n_fills_bid = 0
    n_fills_ask = 0
    spread_earned = 0.0
    trades_list = []

    # Running OBI from taker_side
    yes_vol_window = []
    no_vol_window = []

    for idx, row in mt.iterrows():
        trade_price = row["yes_price"]
        trade_side = row["taker_side"]
        trade_qty = row["count"]

        # Update running OBI
        if trade_side == "yes":
            yes_vol_window.append(trade_qty)
            no_vol_window.append(0)
        else:
            yes_vol_window.append(0)
            no_vol_window.append(trade_qty)

        if len(yes_vol_window) > obi_window:
            yes_vol_window = yes_vol_window[-obi_window:]
            no_vol_window = no_vol_window[-obi_window:]

        total_yes = sum(yes_vol_window)
        total_no = sum(no_vol_window)
        total = total_yes + total_no
        obi = (total_yes - total_no) / total if total > 0 else 0.0

        # Our quotes
        mid = trade_price
        skew = obi * obi_skew_factor * half_spread
        our_bid = mid - half_spread + skew
        our_ask = mid + half_spread + skew
        our_bid = np.clip(our_bid, 0.01, 0.98)
        our_ask = np.clip(our_ask, 0.02, 0.99)

        if our_ask <= our_bid:
            continue

        # Fill logic: if trade price <= our_bid, buyer lifted us (we sell)
        # if trade price >= our_ask, seller hit us (we buy)
        filled = False

        if trade_side == "yes" and trade_price >= our_ask:
            # Aggressive buyer lifts our ask — we SELL YES (go short)
            fill_qty = min(qty_per_quote, trade_qty)
            inventory -= fill_qty
            cash += fill_qty * our_ask
            fee = fill_qty * our_ask * fee_pct
            cash -= fee
            total_fees += fee
            n_fills_ask += 1
            filled = True

        elif trade_side == "no" and trade_price <= our_bid:
            # Aggressive seller hits our bid — we BUY YES (go long)
            fill_qty = min(qty_per_quote, trade_qty)
            inventory += fill_qty
            cash -= fill_qty * our_bid
            fee = fill_qty * our_bid * fee_pct
            cash -= fee
            total_fees += fee
            n_fills_bid += 1
            filled = True

        if filled and abs(inventory) > 0:
            # Check if we crossed (both sides filled in sequence)
            if n_fills_bid > 0 and n_fills_ask > 0:
                se = min(n_fills_bid, n_fills_ask) * (our_ask - our_bid) * qty_per_quote
                spread_earned = max(spread_earned, se)

    # Mark remaining inventory to last price
    last_price = mt["yes_price"].iloc[-1]
    settlement = 1.0 if last_price > 0.5 else 0.0
    mtm = inventory * settlement
    total_pnl = cash + mtm

    return {
        "ticker": ticker,
        "n_trades_seen": len(mt),
        "n_fills_bid": n_fills_bid,
        "n_fills_ask": n_fills_ask,
        "n_fills_total": n_fills_bid + n_fills_ask,
        "inventory_final": inventory,
        "cash": cash,
        "mtm": mtm,
        "total_pnl": total_pnl,
        "total_fees": total_fees,
        "spread_earned": spread_earned,
        "profitable": total_pnl > 0,
    }


# ===================================================================
# 3. Grid search per category
# ===================================================================
print("\n[3/4] Grid search per category...")

GRID = {
    "half_spread": [0.01, 0.02, 0.03, 0.05],
    "obi_skew_factor": [0.0, 0.5, 1.0, 2.0],
    "qty_per_quote": [5.0, 10.0],
    "obi_window": [5, 10, 20],
}
combos = list(itertools.product(*GRID.values()))

results_by_cat = {}
for cat, mask in CATEGORIES.items():
    cat_trades = trades[mask]
    markets = list(cat_trades.groupby("market_ticker"))
    # Sample top markets by trade count
    market_counts = [(t, len(g)) for t, g in markets]
    market_counts.sort(key=lambda x: -x[1])
    top_markets = [(t, cat_trades[cat_trades["market_ticker"] == t])
                   for t, _ in market_counts[:100]]

    if len(top_markets) < 5:
        continue

    print(f"\n  {cat}: {len(top_markets)} markets, {len(combos)} param combos")
    cat_results = []

    for combo in tqdm(combos, desc=f"  {cat}"):
        params = dict(zip(GRID.keys(), combo))
        market_pnls = []

        for ticker, mkt_trades in top_markets:
            result = simulate_mm_market(mkt_trades, ticker, **params)
            if result and result["n_fills_total"] > 0:
                market_pnls.append(result)

        if not market_pnls:
            continue

        agg_pnl = sum(r["total_pnl"] for r in market_pnls)
        agg_fills = sum(r["n_fills_total"] for r in market_pnls)
        n_profitable = sum(1 for r in market_pnls if r["profitable"])
        n_markets = len(market_pnls)

        pnl_arr = np.array([r["total_pnl"] for r in market_pnls])
        mu = pnl_arr.mean()
        sigma = pnl_arr.std() if len(pnl_arr) > 1 else 1e-8
        sharpe = mu / max(sigma, 1e-8) * np.sqrt(252)

        cat_results.append({
            **params,
            "n_markets": n_markets,
            "n_fills": agg_fills,
            "n_profitable": n_profitable,
            "pct_profitable": round(n_profitable / n_markets, 4),
            "total_pnl": round(agg_pnl, 2),
            "avg_pnl_per_market": round(mu, 4),
            "sharpe": round(sharpe, 4),
            "total_spread_earned": round(sum(r["spread_earned"] for r in market_pnls), 2),
            "total_fees": round(sum(r["total_fees"] for r in market_pnls), 2),
        })

    if cat_results:
        rdf = pd.DataFrame(cat_results)
        results_by_cat[cat] = rdf
        rdf.to_csv(OUT / f"kalshi_mm_{cat}_grid.csv", index=False)

# ===================================================================
# 4. Results
# ===================================================================
print("\n" + "=" * 60)
print(" KALSHI MARKET-MAKING — RESULTS BY MARKET")
print("=" * 60)

for cat, rdf in results_by_cat.items():
    profitable = rdf[rdf["total_pnl"] > 0]
    print(f"\n  {cat.upper()}")
    print(f"  {'='*50}")
    print(f"    Configs: {len(rdf)}  Profitable: {len(profitable)} ({len(profitable)/len(rdf):.0%})")
    print(f"    Sharpe: {rdf['sharpe'].min():.2f} to {rdf['sharpe'].max():.2f}")
    print(f"    Avg mkt profitable: {rdf['pct_profitable'].mean():.1%}")

    # Impact of OBI skew
    for sf in sorted(GRID["obi_skew_factor"]):
        sub = rdf[rdf["obi_skew_factor"] == sf]
        if not sub.empty:
            p = (sub["total_pnl"] > 0).sum()
            print(f"    skew={sf:.1f}: {p}/{len(sub)} profitable  "
                  f"Sharpe={sub['sharpe'].mean():.2f}  "
                  f"PnL=${sub['total_pnl'].mean():.0f}")

    top3 = rdf.nlargest(3, "sharpe")
    print(f"    Top 3:")
    for _, row in top3.iterrows():
        p = {c: row[c] for c in GRID.keys()}
        print(f"      S={row['sharpe']:7.2f} PnL=${row['total_pnl']:8.0f} "
              f"Fills={int(row['n_fills'])} MktProf={row['pct_profitable']:.0%} | {p}")

# Summary
print(f"\n  {'='*60}")
print(f"  {'Category':<15} {'Profitable':>12} {'Best Sharpe':>12} {'Best PnL':>10} {'OBI helps?':>10}")
for cat, rdf in results_by_cat.items():
    p = (rdf["total_pnl"] > 0).sum()
    no_skew = rdf[rdf["obi_skew_factor"] == 0.0]["sharpe"].mean() if len(rdf[rdf["obi_skew_factor"] == 0.0]) > 0 else 0
    with_skew = rdf[rdf["obi_skew_factor"] > 0]["sharpe"].mean() if len(rdf[rdf["obi_skew_factor"] > 0]) > 0 else 0
    helps = "YES" if with_skew > no_skew else "NO"
    print(f"  {cat:<15} {p:>5}/{len(rdf):<4} ({p/len(rdf):.0%}) "
          f"{rdf['sharpe'].max():>12.2f} ${rdf['total_pnl'].max():>9.0f} {helps:>10}")

# Plot
fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle("Kalshi Market-Making — Multi-Market Results", fontsize=14, fontweight="bold")

ax = axes[0, 0]
cats = sorted(results_by_cat.keys(), key=lambda c: results_by_cat[c]["sharpe"].max())
vals = [results_by_cat[c]["sharpe"].max() for c in cats]
colors = ["green" if v > 0 else "red" for v in vals]
ax.barh(cats, vals, color=colors)
ax.axvline(0, color="black", linestyle="--")
ax.set_xlabel("Best Sharpe")
ax.set_title("Best MM Sharpe by Market Category")

ax = axes[0, 1]
for cat, rdf in results_by_cat.items():
    agg = rdf.groupby("obi_skew_factor")["sharpe"].mean()
    ax.plot(agg.index, agg.values, "o-", label=cat, linewidth=1.5)
ax.axhline(0, color="red", linestyle="--")
ax.set_xlabel("OBI Skew Factor")
ax.set_ylabel("Avg Sharpe")
ax.set_title("OBI Skew Impact by Market")
ax.legend(fontsize=7)
ax.grid(True, alpha=0.3)

ax = axes[1, 0]
for cat, rdf in results_by_cat.items():
    agg = rdf.groupby("half_spread")["total_pnl"].mean()
    ax.plot(agg.index, agg.values, "o-", label=cat, linewidth=1.5)
ax.axhline(0, color="red", linestyle="--")
ax.set_xlabel("Half Spread")
ax.set_ylabel("Avg Total PnL ($)")
ax.set_title("PnL by Spread Width")
ax.legend(fontsize=7)
ax.grid(True, alpha=0.3)

ax = axes[1, 1]
for cat, rdf in results_by_cat.items():
    pcts = rdf.groupby("half_spread")["pct_profitable"].mean()
    ax.plot(pcts.index, pcts.values * 100, "o-", label=cat, linewidth=1.5)
ax.axhline(50, color="red", linestyle="--")
ax.set_xlabel("Half Spread")
ax.set_ylabel("% Markets Profitable")
ax.set_title("Market Win Rate by Spread")
ax.legend(fontsize=7)
ax.grid(True, alpha=0.3)

plt.tight_layout()
fig.savefig(OUT / "kalshi_mm_results.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"\n  Plot saved: {OUT / 'kalshi_mm_results.png'}")
print("DONE")
