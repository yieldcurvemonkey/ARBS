"""Inspect collected Kalshi LOB data to understand market structure."""
import sys
from pathlib import Path
sys.stdout.reconfigure(line_buffering=True)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import datetime
import pandas as pd
from OBI.kalshi_lob.storage import LOBStorage

storage = LOBStorage()
date = datetime.date(2026, 6, 4)

print("=== TRADES ===")
trades = storage.read_trades(date)
print(f"Total: {len(trades)} rows")
if not trades.empty:
    print(f"Columns: {list(trades.columns)}")
    print(f"Markets: {trades['market_ticker'].nunique()}")
    print(f"Time range: {trades['ts'].min()} to {trades['ts'].max()}")
    # Market categories
    trades["prefix"] = trades["market_ticker"].str.extract(r'^(KX[A-Z]+)')
    cats = trades.groupby("prefix").agg(
        n_trades=("market_ticker", "count"),
        n_markets=("market_ticker", "nunique"),
        total_count=("count", "sum"),
    ).sort_values("n_trades", ascending=False)
    print(f"\nTop market categories:")
    print(cats.head(20).to_string())

    # BTC-specific
    btc = trades[trades["market_ticker"].str.contains("BTC", case=False)]
    print(f"\nBTC trades: {len(btc)} across {btc['market_ticker'].nunique()} markets")
    if not btc.empty:
        print(f"  Tickers: {btc['market_ticker'].unique()[:10]}")
        print(f"  Total contracts: {btc['count'].sum():.0f}")
        print(f"  Avg yes_price: {btc['yes_price'].mean():.4f}")

print("\n=== DELTAS ===")
deltas = storage.read_deltas(date)
print(f"Total: {len(deltas)} rows")
if not deltas.empty:
    print(f"Markets: {deltas['market_ticker'].nunique()}")
    deltas["prefix"] = deltas["market_ticker"].str.extract(r'^(KX[A-Z]+)')
    dcat = deltas.groupby("prefix").agg(
        n_deltas=("market_ticker", "count"),
        n_markets=("market_ticker", "nunique"),
    ).sort_values("n_deltas", ascending=False)
    print(f"\nDelta categories:")
    print(dcat.head(15).to_string())

print("\n=== SNAPSHOTS ===")
snaps = storage.read_snapshots(date)
print(f"Total: {len(snaps)} rows")
if not snaps.empty:
    print(f"Markets: {snaps['market_ticker'].nunique()}")

# Find markets with BOTH trades and deltas for backtesting
print("\n=== BACKTEST CANDIDATES ===")
if not trades.empty and not deltas.empty:
    trade_mkts = set(trades["market_ticker"].unique())
    delta_mkts = set(deltas["market_ticker"].unique())
    both = trade_mkts & delta_mkts
    print(f"Markets with both trades + deltas: {len(both)}")

    # Volume leaders
    vol = trades.groupby("market_ticker")["count"].sum().sort_values(ascending=False)
    vol_both = vol[vol.index.isin(both)]
    print(f"\nTop 20 markets by volume (with delta data):")
    for ticker, v in vol_both.head(20).items():
        nd = len(deltas[deltas["market_ticker"] == ticker])
        nt = len(trades[trades["market_ticker"] == ticker])
        print(f"  {ticker}: vol={v:.0f}  trades={nt}  deltas={nd}")
