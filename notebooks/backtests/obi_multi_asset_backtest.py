"""
OBI Multi-Asset Backtest: ETH & SOL on Polymarket 5-min Up/Down
================================================================
Runs the OBI strategy on ETH and SOL using the same framework as the
existing BTC backtest.  Fetches real 1-min candles from Binance via ccxt
(falls back to synthetic GBM if ccxt unavailable).

Usage:
    conda run -n stir python notebooks/backtests/obi_multi_asset_backtest.py

Outputs:
    - Per-asset backtest summary printed to stdout
    - CSV results in notebooks/backtests/obi_multi_asset_results/
    - Tearsheet PNGs per asset
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from OBI.config import (
    ASSET_CONFIGS,
    BacktestConfig,
    POLYMARKET_5M_BTC,
    POLYMARKET_5M_ETH,
    POLYMARKET_5M_SOL,
    build_config,
)
from OBI.backtest import (
    BacktestResult,
    fetch_crypto_prices,
    run_backtest,
    select_best_configs,
)
from OBI.tearsheet import plot_tearsheet, build_trades_df

OUT_DIR = Path(__file__).resolve().parent / "obi_multi_asset_results"
OUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_START = "2025-05-15"
DATA_END = "2025-06-01"
USE_SYNTHETIC = os.environ.get("OBI_SYNTHETIC", "0") == "1"

ASSETS = {
    "BTC": {
        "preset": POLYMARKET_5M_BTC,
        "base_price": ASSET_CONFIGS["BTC"]["base_price"],
    },
    "ETH": {
        "preset": POLYMARKET_5M_ETH,
        "base_price": ASSET_CONFIGS["ETH"]["base_price"],
    },
    "SOL": {
        "preset": POLYMARKET_5M_SOL,
        "base_price": ASSET_CONFIGS["SOL"]["base_price"],
    },
}

# ---------------------------------------------------------------------------
# Sweep configs: test multiple thresholds and signal modes per asset
# ---------------------------------------------------------------------------

CONFIGS_PER_ASSET = [
    {"entry_threshold": 0.10, "signal_mode": "follow", "obi_variant": "normalized"},
    {"entry_threshold": 0.15, "signal_mode": "follow", "obi_variant": "normalized"},
    {"entry_threshold": 0.20, "signal_mode": "follow", "obi_variant": "normalized"},
    {"entry_threshold": 0.25, "signal_mode": "follow", "obi_variant": "normalized"},
    {"entry_threshold": 0.10, "signal_mode": "fade", "obi_variant": "normalized"},
    {"entry_threshold": 0.15, "signal_mode": "fade", "obi_variant": "normalized"},
    {"entry_threshold": 0.20, "signal_mode": "fade", "obi_variant": "normalized"},
    {"entry_threshold": 0.10, "signal_mode": "follow", "obi_variant": "raw"},
    {"entry_threshold": 0.15, "signal_mode": "follow", "obi_variant": "raw"},
    {"entry_threshold": 0.10, "signal_mode": "follow", "obi_variant": "weighted"},
    {"entry_threshold": 0.15, "signal_mode": "follow", "obi_variant": "weighted"},
]


def _generate_synthetic(base_price: float, start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start, end, freq="1min", tz="UTC")
    np.random.seed(42)
    drift = base_price * 0.0001 / (24 * 60)
    vol = 0.0003 if base_price > 10_000 else (0.0005 if base_price > 500 else 0.0008)
    returns = np.random.normal(drift, vol, len(idx))
    prices = base_price * np.exp(np.cumsum(returns))
    return pd.DataFrame({
        "open": prices,
        "high": prices * (1 + np.abs(np.random.normal(0, 0.0002, len(idx)))),
        "low": prices * (1 - np.abs(np.random.normal(0, 0.0002, len(idx)))),
        "close": prices * (1 + np.random.normal(0, 0.0001, len(idx))),
        "volume": np.random.lognormal(10, 1, len(idx)),
    }, index=idx)


# ===========================================================================
# Main
# ===========================================================================

print("=" * 70)
print("OBI MULTI-ASSET BACKTEST: BTC / ETH / SOL  (Polymarket 5-min)")
print("=" * 70)

all_summaries = []

for asset_name, asset_info in ASSETS.items():
    print(f"\n{'─' * 70}")
    print(f"  ASSET: {asset_name}")
    print(f"{'─' * 70}")

    # --- fetch prices ---
    preset = asset_info["preset"]
    acfg = ASSET_CONFIGS[asset_name]
    t0 = time.time()

    if USE_SYNTHETIC:
        prices = _generate_synthetic(asset_info["base_price"], DATA_START, DATA_END)
        print(f"  [data] Synthetic {len(prices):,} 1-min candles")
    else:
        try:
            prices = fetch_crypto_prices(
                symbol=acfg["symbol"],
                start=DATA_START,
                end=DATA_END,
                source="ccxt",
                exchange="binance",
                timeframe="1m",
            )
            print(f"  [data] Fetched {len(prices):,} 1-min candles from Binance ({time.time()-t0:.1f}s)")
        except Exception as e:
            print(f"  [data] ccxt failed ({e}), using synthetic...")
            prices = _generate_synthetic(asset_info["base_price"], DATA_START, DATA_END)
            print(f"  [data] Synthetic {len(prices):,} 1-min candles")

    # --- run config sweep ---
    print(f"  [backtest] Running {len(CONFIGS_PER_ASSET)} configs...")
    results_rows = []

    for i, overrides in enumerate(CONFIGS_PER_ASSET):
        cfg = build_config(preset, {
            "start_date": DATA_START,
            "end_date": DATA_END,
            **overrides,
        })
        try:
            result = run_backtest(cfg, prices=prices)
            row = {
                "asset": asset_name,
                **overrides,
                **result.metrics,
            }
            results_rows.append(row)

            tag = f"{overrides['signal_mode'][:3]}|{overrides['obi_variant'][:4]}|t={overrides['entry_threshold']}"
            status = "+" if result.metrics.get("total_pnl", 0) > 0 else "-"
            print(
                f"    [{status}] {tag:30s}  "
                f"trades={result.metrics['n_trades']:>4d}  "
                f"WR={result.metrics['win_rate']:.2%}  "
                f"PnL=${result.metrics['total_pnl']:>8.2f}  "
                f"Sharpe={result.metrics['sharpe']:>7.3f}  "
                f"DD={result.metrics['max_drawdown_pct']:.1f}%"
            )
        except Exception as e:
            print(f"    [!] {overrides} — error: {e}")
            results_rows.append({"asset": asset_name, **overrides, "error": str(e)})

    df = pd.DataFrame(results_rows)
    csv_path = OUT_DIR / f"{asset_name.lower()}_polymarket_5m_backtest.csv"
    df.to_csv(csv_path, index=False)
    print(f"  [saved] {csv_path}")
    all_summaries.append(df)

    # --- tearsheet for best sharpe config ---
    valid = df.dropna(subset=["sharpe"]) if "sharpe" in df.columns else df
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]
    if not valid.empty and "sharpe" in valid.columns:
        best_row = valid.loc[valid["sharpe"].idxmax()]
        best_overrides = {
            k: best_row[k] for k in ["entry_threshold", "signal_mode", "obi_variant"]
            if k in best_row.index
        }
        best_cfg = build_config(preset, {
            "start_date": DATA_START,
            "end_date": DATA_END,
            **best_overrides,
        })
        try:
            best_result = run_backtest(best_cfg, prices=prices)
            fig = plot_tearsheet(
                best_result,
                title=f"{asset_name} Polymarket 5m — Best Sharpe Config Tearsheet",
            )
            if fig:
                fig.savefig(
                    OUT_DIR / f"{asset_name.lower()}_best_sharpe_tearsheet.png",
                    dpi=150, bbox_inches="tight",
                )
                plt.close(fig)
                print(f"  [saved] {asset_name.lower()}_best_sharpe_tearsheet.png")
        except Exception as e:
            print(f"  [!] Tearsheet error: {e}")


# ===========================================================================
# Cross-asset summary
# ===========================================================================

print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

for asset_name, df in zip(ASSETS.keys(), all_summaries):
    valid = df.dropna(subset=["sharpe"]) if "sharpe" in df.columns else pd.DataFrame()
    if "error" in valid.columns:
        valid = valid[valid["error"].isna()]

    if valid.empty:
        print(f"\n  {asset_name}: No valid results")
        continue

    print(f"\n  {asset_name}:")
    print(f"    Configs tested:   {len(valid)}")
    print(f"    Profitable:       {(valid['total_pnl'] > 0).sum()}/{len(valid)} ({(valid['total_pnl'] > 0).mean():.0%})")
    print(f"    Best Sharpe:      {valid['sharpe'].max():.4f}")
    print(f"    Best Win Rate:    {valid['win_rate'].max():.2%}")
    print(f"    Best PnL:         ${valid['total_pnl'].max():.2f}")
    print(f"    Max Drawdown:     {valid['max_drawdown_pct'].min():.2f}% — {valid['max_drawdown_pct'].max():.2f}%")

    best = valid.loc[valid["sharpe"].idxmax()]
    print(f"    ── Best config:   mode={best.get('signal_mode','?')}, "
          f"variant={best.get('obi_variant','?')}, "
          f"threshold={best.get('entry_threshold','?')}")
    print(f"       Sharpe={best['sharpe']:.4f}  WR={best['win_rate']:.2%}  "
          f"PnL=${best['total_pnl']:.2f}  DD={best['max_drawdown_pct']:.1f}%")

print(f"\n  Results saved to: {OUT_DIR}")
print("=" * 70)
print("DONE")
