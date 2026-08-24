"""Build strip data + run the linear peak-fade backtests.

Task 4 (gate) of the strip-peak-fade system. See
.superpowers/sdd/2026-08-24-strip-peak-fade/task-4-brief.md.

Window note: anchored at 2026-01-02 per the task-4 ruling (all 8 front quarterly
SR3 contracts are live at the anchor date). ``build_daily_strip`` returns the
*intersection* of dates where all n_front contracts have a settle -- a contract
that expires mid-window truncates the strip via an inner dropna(), so the
printed date range below may be shorter than [START, END]. That's expected;
report the achieved range, don't assume the nominal one.
"""
import datetime
import sys
sys.path.insert(0, ".")

import os
os.environ["ARBS_SUPABASE_ENABLED"] = "0"

import pandas as pd
import numpy as np

from RVUtils.StripPeak.strip_builder import build_daily_strip
from RVUtils.StripPeak.peak_tracker import identify_peak, migration_events
from RVUtils.StripPeak.linear_backtest import backtest_spread, backtest_butterfly, summary_stats

START = datetime.date(2026, 1, 2)
END = datetime.date(2026, 8, 22)
N_FRONT = 8
HOLD_DAYS_GRID = [5, 10, 21, 42, 63]
COST_GRID_SPREAD = [0.0, 1.0, 2.0]      # 2 legs
COST_GRID_FLY = [0.0, 2.0, 4.0]          # 4 legs

print("=== Building daily strip ===")
strip = build_daily_strip(START, END, N_FRONT, cache=True)
print(f"Strip: {strip.shape[0]} dates x {strip.shape[1]} contracts")
print(f"Columns: {list(strip.columns)}")
if strip.shape[0] > 0:
    print(f"Date range: {strip.index[0]} to {strip.index[-1]}  (nominal request: {START} to {END})")
else:
    print("Date range: EMPTY STRIP")

assert strip.shape[1] == N_FRONT, (
    f"Expected {N_FRONT} contract columns, got {strip.shape[1]} "
    f"({list(strip.columns)}) -- build_daily_strip silently drops a contract "
    f"column on fetch error (see task-1-report.md); refusing to run the gate "
    f"on a narrower-than-requested strip since peak_idx semantics shift."
)
assert strip.shape[0] > 0, "Strip is empty -- nothing to backtest."

print("\n=== Identifying peaks ===")
peak = identify_peak(strip)
interior = peak[peak["is_interior"]]
print(f"Total dates: {len(peak)}, interior peaks: {len(interior)}")
print(f"Peak contracts (value counts):")
print(peak["peak_contract"].value_counts().to_string())

events = migration_events(peak)
print(f"\nMigration events: {len(events)}")
if len(events) > 0:
    print("Last 10 migration events:")
    print(events.tail(10).to_string())

print("\n=== Spread backtest grid ===")
spread_results = []
for hd in HOLD_DAYS_GRID:
    for cost in COST_GRID_SPREAD:
        bt = backtest_spread(strip, peak, hold_days=hd, cost_bp=cost)
        stats = summary_stats(bt)
        stats["hold_days"] = hd
        stats["cost_bp"] = cost
        stats["variant"] = "spread"
        spread_results.append(stats)
        print(f"  hold={hd:3d}d  cost={cost:.1f}bp  n={stats['n_trades']:4d}  "
              f"hit={stats['hit_rate']:.1%}  avg={stats['avg_pnl_bp']:+.2f}bp  "
              f"sharpe={stats['sharpe']:.2f}")

print("\n=== Butterfly backtest grid ===")
fly_results = []
for hd in HOLD_DAYS_GRID:
    for cost in COST_GRID_FLY:
        bt = backtest_butterfly(strip, peak, hold_days=hd, cost_bp=cost)
        stats = summary_stats(bt)
        stats["hold_days"] = hd
        stats["cost_bp"] = cost
        stats["variant"] = "butterfly"
        fly_results.append(stats)
        print(f"  hold={hd:3d}d  cost={cost:.1f}bp  n={stats['n_trades']:4d}  "
              f"hit={stats['hit_rate']:.1%}  avg={stats['avg_pnl_bp']:+.2f}bp  "
              f"sharpe={stats['sharpe']:.2f}")

all_results = pd.DataFrame(spread_results + fly_results)
out_dir = "analysis_outputs/strip_peak"
os.makedirs(out_dir, exist_ok=True)
all_results.to_csv(f"{out_dir}/linear_grid.csv", index=False)
print(f"\nResults saved to {out_dir}/linear_grid.csv")

print("\n=== Gate check: gross-of-cost (cost=0.0) avg_pnl_bp by hold_days ===")
gross = all_results[all_results["cost_bp"] == 0.0][
    ["variant", "hold_days", "n_trades", "hit_rate", "avg_pnl_bp", "sharpe"]
].sort_values(["variant", "hold_days"])
print(gross.to_string(index=False))
any_gross_edge = (gross["avg_pnl_bp"] > 0).any()
print(f"\nAny gross-of-cost avg_pnl_bp > 0 across all variants/hold_days: {any_gross_edge}")
