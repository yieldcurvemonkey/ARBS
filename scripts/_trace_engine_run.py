"""Run a 2-day backtest with a single SFRU26 PAY signal and dump every step."""
from __future__ import annotations
import datetime, sys
from pathlib import Path
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from RVUtils.SFRConvexScreener import (
    JointMethod, Leg, SFRConvexScreenerConfig, SFRScreenerBacktestConfig,
    StructureDef, StructureType,
)
from RVUtils.SFRConvexScreener._backtest_signals import BacktestSignal
from RVUtils.SFRConvexScreener._backtest_triggers import (
    build_entry_trigger, build_exit_trigger,
)
from BT.data_handler import TimeGrid
from BT.query_engine import QueryDrivenBacktest
from BT.query_strategy import QueryStrategy
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP


NYC = pytz.timezone("America/New_York")

# Use the actual cached signals
import pickle
from pathlib import Path
with Path("data/screener_results/sfr_convex_screener_backtest_cache/2026-03-30_60855039beb3.pkl").open("rb") as fh:
    snap_330 = pickle.load(fh)
with Path("data/screener_results/sfr_convex_screener_backtest_cache/2026-03-31_60855039beb3.pkl").open("rb") as fh:
    snap_331 = pickle.load(fh)
from RVUtils.SFRConvexScreener._backtest_signals import build_signal_table_from_snapshots
table = build_signal_table_from_snapshots([snap_330, snap_331])

# bt_cfg: daily rebal, no DOW, low TP/SL so the position stays open across both days
bt_cfg = SFRScreenerBacktestConfig(
    bpv_per_trade=100_000.0,
    entry_min_asymmetry=1.5, entry_min_composite_score=0,
    skip_stale=True,
    structure_types=("outright", "calendar", "butterfly"),
    max_concurrent=5, rebalance_dow=None,
    exit_asymmetry_threshold=1.10,
    exit_take_profit_bp=10.0, exit_stop_loss_bp=-15.0,
    exit_max_holding_days=22,
)

entry_trigger = build_entry_trigger(table, bt_cfg)
exit_trigger = build_exit_trigger(table, bt_cfg)

mdp = IRSwapsMDP(source="BARCHART_STIRF-RL")
strategy = QueryStrategy(
    name="trace", triggers=[entry_trigger, exit_trigger], default_mdp=mdp,
)

bt_dts = [
    NYC.localize(datetime.datetime(2026, 3, 30, 17, 0)),
    NYC.localize(datetime.datetime(2026, 3, 31, 17, 0)),
]
bt = QueryDrivenBacktest(
    time_grid=TimeGrid(bt_dts), strategy=strategy, mdp=mdp, show_progress=False,
)
bt.run()

print(f"\n--- backtest finished ---")
print(f"realized_pnl: {bt.realized_pnl:,.2f}")
print(f"closed positions: {len(bt.portfolio.closed_positions_log)}")
for c in bt.portfolio.closed_positions_log:
    print(f"  realized={c['realized_pnl']:,.2f} gross={c['gross_realized_pnl']:,.2f}")
print(f"open positions: {len(bt.portfolio.positions)}")
print(f"mtm_history:")
for d, v in bt.mtm_history.items():
    print(f"  {d}: {v:,.2f}")
print(f"\n--- portfolio.positions[0] (if any) ---")
if bt.portfolio.positions:
    p = bt.portfolio.positions[0]
    print(f"  package: {p.package}")
    print(f"  weights: {p.weights}")
    print(f"  source_query.fixed_rate: {p.package[0].fixed_rate}")
    print(f"  source_query.notional.real: {getattr(p.package[0].kwargs.get('notional'), 'real', p.package[0].kwargs.get('notional'))}")
