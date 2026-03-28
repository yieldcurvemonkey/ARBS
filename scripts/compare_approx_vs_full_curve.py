"""Compare Approximate (vectorized) vs Full Curve (QL and RL) JPM RV backtest.

Runs three modes with the primary config (R2>=80%, |res|>=2bp, |z|>=1.5)
and reports side-by-side metrics + P&L correlations.
"""

import datetime
import logging
import sys

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── Imports ──────────────────────────────────────────────────────────────
from BT.signals.regression_rv import (
    RegressionRVConfig,
    build_jpm_signal_table,
    default_fly_universe,
)
from BT.signals.regime_filter import RegimeFilterConfig, traffic_light
from BT.signals.jpm_rv_backtest import JPMRVBacktestConfig, run_jpm_rv_backtest

# ── Configuration ────────────────────────────────────────────────────────
CURVE = "USD-SOFR-1D"
SOURCE_RL = "ERIS_EOD_LIVE-RL_BASIC"
SOURCE_QL = "ERIS_EOD_LIVE-QL_BASIC"
START_DATE = datetime.date(2022, 1, 2)
END_DATE = datetime.date(2026, 3, 20)

REG_CONFIG = RegressionRVConfig(
    window_days=130,
    min_rsq=0.60,
    zscore_lookback_days=130,
)
UNIVERSE = default_fly_universe()

CONFIG = JPMRVBacktestConfig(
    entry_min_rsq=0.80,
    entry_min_residual_bp=2.0,
    entry_min_zscore=1.5,
    exit_mean_reversion=True,
    exit_stop_loss_sd=2.0,
    trade_belly_bpv=100_000.0,
)

# ── Build rate panels (using RL source for signal generation) ───────────
print("Loading rate data...")
from TB.TimeseriesBuilder import TimeseriesBuilder
from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from Query.IRSwaps.IRSwapQuery import IRSwapQuery

curve_mdp = IRSwapsMDP(source=SOURCE_RL)
ts_builder = TimeseriesBuilder()
router = {"IRS": IRSwapsTB(curve_mdp, show_tqdm=True)}

all_tenors = set()
for _, _, fwd, left, belly, right in UNIVERSE.iter_flies():
    for t in [left, belly, right]:
        key = t if "x" in t else (f"{fwd}x{t}" if fwd else t)
        all_tenors.add(key)

queries = [
    IRSwapQuery(curve=CURVE, tenor=tenor)
    for tenor in sorted(all_tenors)
]

rate_df = ts_builder.get_timeseries(
    queries=queries,
    start=START_DATE,
    end=END_DATE,
    routers=router,
)

rate_panels = {}
for q in queries:
    col = q.col_name()
    if col in rate_df.columns:
        rate_panels[q.tenor] = rate_df[col].dropna()

print(f"Loaded {len(rate_panels)} tenor series, date range: {rate_df.index[0]} -> {rate_df.index[-1]}")

# ── Build signals ────────────────────────────────────────────────────────
print("Building signal table...")
signal_table = build_jpm_signal_table(rate_panels, UNIVERSE, REG_CONFIG)
print(f"Built signals for {len(signal_table.residuals)} flies")

# ── Regime ───────────────────────────────────────────────────────────────
ref_fly_candidates = [fid for fid, cat in signal_table.fly_categories.items() if cat == "gap_mm"]
if not ref_fly_candidates:
    ref_fly_candidates = list(signal_table.fly_categories.keys())
REF_FLY = ref_fly_candidates[0]
print(f"Reference fly for traffic light: {REF_FLY}")

tl_config = RegimeFilterConfig(
    beta_vol_window_days=65,
    beta_vol_zscore_window_days=130,
    threshold=3.0,
)
tl_df = traffic_light(
    signal_table.betas_body[REF_FLY],
    signal_table.betas_curve[REF_FLY],
    tl_config,
)
regime = tl_df["regime"]
n_green = (regime == "green").sum()
n_red = (regime == "red").sum()
print(f"Regime: {n_green} green, {n_red} red days")

# ── Run Approximate (vectorized) backtest ────────────────────────────────
print("\n" + "=" * 70)
print("Running APPROXIMATE (vectorized) backtest...")
print("=" * 70)
result_approx = run_jpm_rv_backtest(
    signal_table=signal_table,
    regime=regime,
    mdp=None,
    config=CONFIG,
    show_progress=True,
)

# ── Run rateslib Full Curve backtest ─────────────────────────────────────
print("\n" + "=" * 70)
print(f"Running RATESLIB Full Curve (source={SOURCE_RL})...")
print("=" * 70)
mdp_rl = IRSwapsMDP(source=SOURCE_RL)
result_rl = run_jpm_rv_backtest(
    signal_table=signal_table,
    regime=regime,
    mdp=mdp_rl,
    config=CONFIG,
    show_progress=True,
)

# ── Run QuantLib Full Curve backtest ─────────────────────────────────────
print("\n" + "=" * 70)
print(f"Running QUANTLIB Full Curve (source={SOURCE_QL})...")
print("=" * 70)
mdp_ql = IRSwapsMDP(source=SOURCE_QL)
result_ql = run_jpm_rv_backtest(
    signal_table=signal_table,
    regime=regime,
    mdp=mdp_ql,
    config=CONFIG,
    show_progress=True,
)

# ── Report ───────────────────────────────────────────────────────────────
def fmt_metrics(m):
    lines = []
    lines.append(f"  Total P&L (bp):    {m.get('total_pnl', 0):>12,.0f}")
    if "total_pnl_ccy" in m:
        lines.append(f"  Total P&L (CCY):   {m.get('total_pnl_ccy', 0):>12,.0f}")
    lines.append(f"  # Trades:          {m.get('n_trades', 0):>12,d}")
    lines.append(f"  Hit Rate:          {m.get('hit_rate', 0):>12.1%}")
    lines.append(f"  Avg P&L/trade:     {m.get('avg_pnl', 0):>12.1f}")
    lines.append(f"  Sharpe:            {m.get('sharpe', 0):>12.2f}")
    lines.append(f"  Max Drawdown (bp): {m.get('max_drawdown', 0):>12,.0f}")
    lines.append(f"  Avg Holding (d):   {m.get('avg_holding_days', 0):>12.1f}")
    return "\n".join(lines)


def pnl_correlations(label_a, pnl_a, label_b, pnl_b):
    """Print daily and cumulative correlations between two P&L series."""
    a = pnl_a.copy()
    b = pnl_b.copy()
    if not isinstance(a.index, pd.DatetimeIndex):
        a.index = pd.to_datetime(a.index)
    if not isinstance(b.index, pd.DatetimeIndex):
        b.index = pd.to_datetime(b.index)
    common = a.index.intersection(b.index)
    aa = a.loc[common].dropna()
    bb = b.loc[common].dropna()
    common2 = aa.index.intersection(bb.index)
    aa, bb = aa.loc[common2], bb.loc[common2]
    corr = aa.corr(bb) if len(common2) > 10 else float("nan")
    cum_corr = aa.cumsum().corr(bb.cumsum()) if len(common2) > 10 else float("nan")
    print(f"  {label_a} vs {label_b}:")
    print(f"    Days: {len(common2):,d}  Daily corr: {corr:.4f}  Cum corr: {cum_corr:.4f}")


def trade_breakdown(label, result):
    """Print trade breakdown for a full curve result."""
    if len(result.trades) == 0:
        print(f"  {label}: No trades")
        return
    trades = result.trades
    n_total = len(trades)
    if "rv_position_id" in trades.columns:
        grouped = trades.groupby("rv_position_id")["realized_pnl"].sum()
        n_logical = len(grouped)
        hit_grouped = (grouped > 0).mean()
        print(f"  {label}: {n_total} positions, {n_logical} logical trades, hit rate (grouped): {hit_grouped:.1%}")
    else:
        print(f"  {label}: {n_total} positions")


print("\n" + "=" * 70)
print("RESULTS COMPARISON")
print("=" * 70)

print("\n--- APPROXIMATE (vectorized, mdp=None) ---")
print(fmt_metrics(result_approx.metrics))

print(f"\n--- RATESLIB Full Curve ({SOURCE_RL}) ---")
print(fmt_metrics(result_rl.metrics))

print(f"\n--- QUANTLIB Full Curve ({SOURCE_QL}) ---")
print(fmt_metrics(result_ql.metrics))

# ── P&L correlations ────────────────────────────────────────────────────
print("\n--- DAILY P&L CORRELATIONS ---")
pnl_correlations("Approx", result_approx.daily_pnl, "RL", result_rl.daily_pnl)
pnl_correlations("Approx", result_approx.daily_pnl, "QL", result_ql.daily_pnl)
pnl_correlations("RL", result_rl.daily_pnl, "QL", result_ql.daily_pnl)

# ── Trade breakdowns ────────────────────────────────────────────────────
print("\n--- TRADE BREAKDOWNS ---")
trade_breakdown("RL", result_rl)
trade_breakdown("QL", result_ql)

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
