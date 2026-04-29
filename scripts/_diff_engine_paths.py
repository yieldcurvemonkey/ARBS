"""Run the engine via run_backtest (the cached_only path) AND via my manual setup.
Capture and compare per-trade realized values to isolate the 2x outright magnitude bug."""
from __future__ import annotations
import datetime, sys
from pathlib import Path
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from RVUtils.SFRConvexScreener import (
    JointMethod, SFRConvexScreenerConfig, SFRScreenerBacktestConfig,
)
from RVUtils.SFRConvexScreener.backtest import run_backtest, _config_summary_for_cache
from RVUtils.SFRConvexScreener._backtest_cache import snapshot_cache_key

import datetime as dt
NYC = pytz.timezone("America/New_York")
sc = SFRConvexScreenerConfig(universe_size=12, include_outrights=True, jpm_method=True,
    primary_joint_method=JointMethod.HISTORICAL_GAUSSIAN_COPULA,
    correlation_window=60, n_simulations=50_000)
print(f"key for 3/30: {snapshot_cache_key(dt.date(2026,3,30), _config_summary_for_cache(sc))}")

bc = SFRScreenerBacktestConfig(
    bpv_per_trade=100_000.0, entry_min_asymmetry=1.5, max_concurrent=5,
    structure_types=("outright", "calendar", "butterfly"),
    rebalance_dow=None, exit_asymmetry_threshold=1.10,
    exit_take_profit_bp=10.0, exit_stop_loss_bp=-15.0,
    exit_max_holding_days=22,
)

from scripts.run_screener_backtest_cached_only import _bt_datetimes
bt_dts_my = [
    NYC.localize(dt.datetime(2026, 3, 30, 17, 0)),
    NYC.localize(dt.datetime(2026, 3, 31, 17, 0)),
]
bt_dts_co = _bt_datetimes(dt.date(2026, 3, 30), dt.date(2026, 3, 31))
print(f"my  bt_dts: {bt_dts_my}")
print(f"co  bt_dts: {bt_dts_co}")
print(f"equal: {bt_dts_my == bt_dts_co}")
bt_dts = bt_dts_co  # Use cached_only's exact datetimes

def _run(label, snap_dates):
    bt = run_backtest(
        bt_datetimes=bt_dts, screener_config=sc, backtest_config=bc,
        cache_root="data/screener_results/sfr_convex_screener_backtest_cache",
        snapshot_dates=snap_dates,
        show_progress=False,
    )

    print(f"\n=== {label} ===")
    print(f"realized_pnl: {bt.realized_pnl:,.2f}")
    print(f"closed positions: {len(bt.portfolio.closed_positions_log)}")
    for c in bt.portfolio.closed_positions_log:
        pmeta = c.get("position_meta", {}) or {}
        print(f"  {pmeta.get('structure_id')} type={pmeta.get('structure_type')} realized={c['realized_pnl']:,.2f} entry_npv={pmeta.get('entry_npv')}")


# Run cached_only's main directly via subprocess-like import call
import sys as _sys
_sys.argv = [
    "run_screener_backtest_cached_only.py",
    "--start", "2026-03-30", "--end", "2026-03-31", "--only", "f_daily_rebalance",
]
from scripts.run_screener_backtest_cached_only import main as cached_only_main
print("\n=== invoking cached_only.main() in this process ===")
cached_only_main()
