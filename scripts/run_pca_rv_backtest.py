"""Run the PCA RV butterfly backtest as a script.

Usage: python scripts/run_pca_rv_backtest.py
"""
import datetime
import warnings
import sys
import os

warnings.filterwarnings("ignore")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import pytz
import pandas as pd
import numpy as np

from BT.signals.pca_rv_scanner import (
    PCARVScannerConfig, scan_forward_surface, zscore_snapshot,
    identify_candidates, analyze_candidates, build_signal_table,
    build_rate_queries, reshape_rates_panel,
)
from BT.signals.pca_rv_triggers import PCARVEntryTrigger, PCARVExitTrigger

tz = pytz.timezone("America/New_York")

# Use spot-only to avoid rateslib forward-start pricing issues.
# Reduce zscore_lookback to 260d so warm-up (520+260=780) fits in available data (~998 dates).
config = PCARVScannerConfig(
    forward_starts=[None],  # spot only — forward starts hit leg2_fixings bug
    zscore_lookback_days=260,
)

data_start = datetime.datetime(2022, 1, 1, 17, tzinfo=tz)
data_end = datetime.datetime(2025, 12, 31, 17, tzinfo=tz)

print(f"Config: {config.curve} / {config.source}")
print(f"Tenors: {config.tenors}")
print(f"Forward starts: {config.forward_starts}")
print(f"PCA window: {config.pca_window_days}d, Z-score window: {config.zscore_lookback_days}d")
print(f"Min Z-score entry: {config.min_zscore_entry}, Max ADF p-value: {config.max_adf_pvalue}")
print(f"Fly categories: {list(config.fly_tenor_categories.keys())}")

# ── 1. Load rates ────────────────────────────────────────────────
print("\n[1/5] Loading rates...")
from TB.TimeseriesBuilder import TimeseriesBuilder
from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

curve_mdp = IRSwapsMDP(source=config.source)
ts_builder = TimeseriesBuilder()
queries = build_rate_queries(config)
router = {"IRS": IRSwapsTB(curve_mdp, show_tqdm=True)}

rates_df = ts_builder.get_timeseries(
    start=data_start, end=data_end, queries=queries, n_jobs=12, routers=router,
)
panels = reshape_rates_panel(rates_df, config)
# Convert date index to pd.Timestamp for consistent comparisons
for fwd in panels:
    panels[fwd].index = pd.to_datetime(panels[fwd].index)
print(f"  Loaded {len(panels)} panel(s)")
for fwd, df in panels.items():
    label = "Spot" if fwd is None else fwd
    non_null = df.dropna(how="all")
    first = non_null.index[0]
    last = non_null.index[-1]
    first_str = first.date() if hasattr(first, "date") else first
    last_str = last.date() if hasattr(last, "date") else last
    print(f"  {label}: {non_null.shape[0]} dates x {non_null.shape[1]} tenors, "
          f"range={first_str} to {last_str}")

# ── 2. Stage 1: Surface scan ────────────────────────────────────
print("\n[2/5] Running Stage 1: Full-curve PCA surface scan...")
result = scan_forward_surface(panels, config)
snap = zscore_snapshot(result)
print(f"  Z-score snapshot ({snap.shape[0]} tenors x {snap.shape[1]} fwd starts):")
print(snap.to_string(float_format="{:.2f}".format))

if None in result.variance_explained:
    ve = result.variance_explained[None].dropna()
    if not ve.empty:
        print(f"\n  Avg variance explained by 3 PCs: {ve.sum(axis=1).mean():.1%}")

# ── 3. Stage 2: Candidates at latest date ────────────────────────
print("\n[3/5] Identifying candidates at latest date...")
candidates = identify_candidates(result, panels, config)
print(f"  Found {len(candidates)} candidates")
for c in candidates:
    print(f"    {c.forward_start or 'Spot'} {c.tenors[0]}/{c.tenors[1]}/{c.tenors[2]} "
          f"w=[{c.weights[0]:.2f}/1.00/{c.weights[2]:.2f}] "
          f"dir={c.direction} Z(belly)={c.zscore_belly:.2f}")

# ── 4. Build signal table ────────────────────────────────────────
bt_start = datetime.datetime(2024, 1, 1, 17, tzinfo=tz)
bt_end = data_end
print(f"\n[4/5] Building signal table {bt_start.date()} to {bt_end.date()}...")
signal_table = build_signal_table(
    panels, config,
    start_date=pd.Timestamp(bt_start).tz_localize(None),
    end_date=pd.Timestamp(bt_end).tz_localize(None),
)
total_signals = sum(len(v) for v in signal_table.values())
passing_signals = sum(sum(1 for t in v if t.passes_filter) for v in signal_table.values())
print(f"  {len(signal_table)} dates with signals, {total_signals} total, {passing_signals} passing filters")

# ── 5. Run backtest ──────────────────────────────────────────────
print(f"\n[5/5] Running backtest...")
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from BT.data_handler import TimeGrid

entry = PCARVEntryTrigger(signal_table, config, bpv=100_000)
exit_ = PCARVExitTrigger(signal_table, config)
strategy = QueryStrategy("pca_rv_fly", triggers=[entry, exit_], default_mdp=curve_mdp)

bt_dates = pd.bdate_range(bt_start, bt_end, tz=tz)
bt_datetimes = [d.to_pydatetime() for d in bt_dates]

bt = QueryDrivenBacktest(
    time_grid=TimeGrid(bt_datetimes),
    strategy=strategy,
    mdp=curve_mdp,
)
bt.run()

# ── Results ──────────────────────────────────────────────────────
mtm = pd.Series(bt.mtm_history).sort_index()
n_trades = len(bt.portfolio.trades_log)
realized = bt.realized_pnl
final_mtm = mtm.iloc[-1] if len(mtm) > 0 else 0

daily_pnl = mtm.diff().dropna()
sharpe = (daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)) if daily_pnl.std() > 0 else 0
peak = mtm.cummax()
dd = mtm - peak
max_dd = dd.min()
hit_rate = (daily_pnl > 0).mean() if len(daily_pnl) > 0 else 0

print(f"\n{'='*55}")
print(f"  PCA RV BUTTERFLY BACKTEST RESULTS")
print(f"{'='*55}")
print(f"  Period:            {bt_start.date()} to {bt_end.date()}")
print(f"  Total trades:      {n_trades}")
print(f"  Final MTM P&L:     ${final_mtm:,.0f}")
print(f"  Realized P&L:      ${realized:,.0f}")
print(f"  Sharpe ratio:      {sharpe:.2f}")
print(f"  Max drawdown:      ${max_dd:,.0f}")
print(f"  Daily hit rate:    {hit_rate:.1%}")
print(f"  Open positions:    {len(bt.portfolio.positions)}")
print(f"{'='*55}")

# Trade log
if bt.portfolio.trades_log:
    print(f"\nTrade log ({n_trades} entries):")
    for o in bt.portfolio.trades_log[:20]:
        ts = str(getattr(o, "timestamp", ""))[:10]
        q = str(getattr(o, "query", ""))[:80]
        print(f"  {ts}: {q}")
    if n_trades > 20:
        print(f"  ... and {n_trades - 20} more")
else:
    print("\nNo trades executed during backtest period")

print("\nDone.")
