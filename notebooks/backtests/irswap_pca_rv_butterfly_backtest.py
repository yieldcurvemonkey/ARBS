"""IRSwap PCA RV Butterfly Backtest — Test Script

Runs all 3 curve_input_modes sequentially and reports results.
Designed to run in conda env 'stir'.

Usage:
    conda activate stir
    cd C:\\Users\\chris\\clee\\ARBS
    python notebooks/backtests/irswap_pca_rv_butterfly_backtest.py
"""
import sys
sys.path.insert(0, "C:\\Users\\chris\\clee\\ARBS")

import datetime
import warnings
warnings.filterwarnings("ignore")

import pytz
import pandas as pd
import numpy as np

from BT.signals.irswap_pca_rv_scanner import (
    IRSwapPCARVConfig, scan_surface, zscore_snapshot,
    identify_candidates, analyze_candidates, build_signal_table,
    build_rate_queries, build_carry_roll_queries,
    reshape_rates_panel, reshape_carry_roll_panel,
)
from BT.signals.irswap_pca_rv_triggers import (
    IRSwapPCARVTrigger, run_irswap_pca_rv_backtest,
)

tz = pytz.timezone("America/New_York")

# ═══════════════════════════════════════════════════════════════════
# Date range
# ═══════════════════════════════════════════════════════════════════
data_start = datetime.datetime(2022, 1, 1, 17, tzinfo=tz)
data_end = datetime.datetime(2026, 3, 20, 17, tzinfo=tz)
bt_start = datetime.datetime(2024, 6, 1, 17, tzinfo=tz)
bt_end = data_end


def run_mode(mode: str) -> dict:
    """Run the full pipeline for a given curve_input_mode."""
    print(f"\n{'='*70}")
    print(f"  RUNNING MODE: {mode}")
    print(f"{'='*70}")

    config = IRSwapPCARVConfig(
        curve_input_mode=mode,
        # Relax filters slightly for more signals during testing
        min_zscore_belly=1.25,
        min_zscore_wing=0.3,
        max_adf_pvalue=0.15,
        auto_scan_fly=(mode != "forward_cs"),  # Use manual universe for CS forwards
        include_carry_roll=True,
    )

    # For stanchart mode, limit forward starts for speed
    if mode == "forward_stanchart":
        config.forward_starts = [None, "1Y", "5Y"]  # Reduced set for testing

    # For CS forwards mode, we need a custom fly universe since tenors are different
    if mode == "forward_cs":
        config.fly_universe = [
            ("1Yx1Y", "3Yx1Y", "5Yx1Y"),
            ("2Yx1Y", "5Yx1Y", "8Yx1Y"),
            ("3Yx1Y", "5Yx1Y", "7Yx1Y"),
            ("5Yx1Y", "7Yx1Y", "9Yx1Y"),
            ("3Yx1Y", "5Yx1Y", "9Yx1Y"),
            ("5Yx1Y", "9Yx1Y", "12Yx3Y"),
            ("7Yx1Y", "10Yx2Y", "15Yx5Y"),
            ("9Yx1Y", "12Yx3Y", "20Yx5Y"),
            ("10Yx2Y", "15Yx5Y", "25Yx5Y"),
            ("15Yx5Y", "20Yx5Y", "30Yx10Y"),
        ]
        config.auto_scan_fly = False

    print(f"Config: {config.curve} / {config.source}")
    print(f"Mode: {config.curve_input_mode}")
    print(f"PCA window: {config.pca_window_days}d, Z-score window: {config.zscore_lookback_days}d")
    print(f"Min Z-score belly: {config.min_zscore_belly}, wing: {config.min_zscore_wing}")
    print(f"Max ADF p-value: {config.max_adf_pvalue}")

    # ── Data Loading ─────────────────────────────────────────────
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from TB.IRSwapsTB import IRSwapsTB
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    curve_mdp = IRSwapsMDP(source=config.source)
    ts_builder = TimeseriesBuilder()
    queries = build_rate_queries(config)
    router = {"IRS": IRSwapsTB(curve_mdp, show_tqdm=True)}

    print(f"\nFetching {len(queries)} rate queries...")
    try:
        rates_df = ts_builder.get_timeseries(
            start=data_start, end=data_end, queries=queries, n_jobs=12, routers=router,
        )
    except Exception as e:
        print(f"ERROR: Data loading failed: {e}")
        return {"mode": mode, "error": str(e)}

    panels = reshape_rates_panel(rates_df, config)
    print(f"Loaded panels for {len(panels)} forward starts")

    if not panels:
        print("ERROR: No panels loaded")
        return {"mode": mode, "error": "No panels loaded"}

    any_panel = next(iter(panels.values()))
    print(f"Date range: {any_panel.index[0]} to {any_panel.index[-1]}")
    print(f"Panel shape: {any_panel.shape}")

    # ── Carry/Roll-down (optional) ───────────────────────────────
    carry_roll_panels = None
    if config.include_carry_roll:
        try:
            cr_queries = build_carry_roll_queries(config)
            print(f"Fetching {len(cr_queries)} carry/roll queries...")
            cr_df = ts_builder.get_timeseries(
                start=data_start, end=data_end, queries=cr_queries, n_jobs=12, routers=router,
            )
            carry_roll_panels = reshape_carry_roll_panel(cr_df, config)
            print(f"Loaded carry/roll panels for {len(carry_roll_panels)} forward starts")
        except Exception as e:
            print(f"WARNING: Carry/roll loading failed (continuing without): {e}")

    # ── Stage 1: Surface Scan ────────────────────────────────────
    print("\nRunning Stage 1: Full-curve PCA surface scan...")
    scan_result = scan_surface(panels, config)

    # Z-score snapshot
    snap = zscore_snapshot(scan_result)
    if not snap.empty:
        print(f"\nZ-Score Snapshot (latest):")
        print(snap.to_string(float_format="%.2f"))
    else:
        print("WARNING: Z-score snapshot is empty")

    # Variance explained
    for fwd, ve_df in scan_result.variance_explained.items():
        valid_ve = ve_df.dropna()
        if not valid_ve.empty:
            latest_ve = valid_ve.iloc[-1]
            fwd_label = "Spot" if fwd is None else fwd
            print(f"\nVariance explained ({fwd_label}): {latest_ve.to_dict()}")
            cum = latest_ve.sum()
            print(f"  Cumulative: {cum:.1%}")

    # ── Stage 2: Candidates at latest date ───────────────────────
    candidates = identify_candidates(scan_result, panels, config)
    print(f"\nStage 2: Found {len(candidates)} candidates at latest date")

    if candidates:
        for c in candidates[:5]:
            print(f"  {c.tenors[0]}/{c.tenors[1]}/{c.tenors[2]} "
                  f"[fwd={c.forward_start or 'spot'}] "
                  f"dir={c.direction} "
                  f"Z(belly)={c.zscore_belly:.2f} "
                  f"weights=({c.weights[0]:.2f}, 1.00, {c.weights[2]:.2f})")

    # ── Stage 3: OU Analytics ────────────────────────────────────
    if candidates:
        trades = analyze_candidates(candidates, panels, config, carry_roll_panels)
        print(f"\nStage 3: Analyzed {len(trades)} trades")
        passing = [t for t in trades if t.passes_filter]
        print(f"  Passing filter: {len(passing)}")
        for t in trades[:5]:
            status = "PASS" if t.passes_filter else f"FAIL ({'; '.join(t.filter_reasons)})"
            print(f"  {t.candidate.tenors} HL={t.half_life_days:.1f}d "
                  f"ADF={t.adf_pvalue:.3f} P/C={t.profit_cost_ratio:.1f} "
                  f"[{status}]")

    # ── Stage 4: Signal Table ────────────────────────────────────
    print(f"\nBuilding rolling signal table ({bt_start.date()} to {bt_end.date()})...")
    signal_table = build_signal_table(
        panels, config, carry_roll_panels,
        start_date=pd.Timestamp(bt_start),
        end_date=pd.Timestamp(bt_end),
    )
    total_signals = sum(len(v) for v in signal_table.values())
    passing_signals = sum(sum(1 for t in v if t.passes_filter) for v in signal_table.values())
    print(f"Signal table: {len(signal_table)} dates with signals")
    print(f"Total signals: {total_signals}, passing filters: {passing_signals}")

    # ── Backtest ─────────────────────────────────────────────────
    if passing_signals == 0:
        print("WARNING: No passing signals — backtest would be empty")
        return {
            "mode": mode,
            "signal_dates": len(signal_table),
            "total_signals": total_signals,
            "passing_signals": passing_signals,
            "n_trades": 0,
            "sharpe": np.nan,
            "error": None,
        }

    bt_dates = pd.bdate_range(bt_start, bt_end, tz=tz)
    bt_datetimes = [d.to_pydatetime() for d in bt_dates]

    print(f"\nRunning backtest: {bt_start.date()} to {bt_end.date()} ({len(bt_datetimes)} steps)")
    try:
        bt = run_irswap_pca_rv_backtest(
            signal_table=signal_table,
            config=config,
            mdp=curve_mdp,
            bt_dates=bt_datetimes,
        )
    except Exception as e:
        print(f"ERROR: Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return {
            "mode": mode,
            "signal_dates": len(signal_table),
            "total_signals": total_signals,
            "passing_signals": passing_signals,
            "error": str(e),
        }

    # ── Results ──────────────────────────────────────────────────
    mtm = pd.Series(bt.mtm_history).sort_index()
    n_trades = len(bt.portfolio.trades_log)
    n_closed = len(bt.portfolio.closed_positions_log)
    n_open = len(bt.portfolio.positions)
    realized = bt.realized_pnl
    final_mtm = mtm.iloc[-1] if len(mtm) > 0 else 0

    daily_pnl = mtm.diff().dropna()
    sharpe = (daily_pnl.mean() / daily_pnl.std() * np.sqrt(252)) if daily_pnl.std() > 0 else 0
    max_dd = (mtm - mtm.cummax()).min()
    hit_rate = (daily_pnl > 0).mean() if len(daily_pnl) > 0 else 0

    print(f"\n{'='*50}")
    print(f"BACKTEST RESULTS — {mode.upper()}")
    print(f"{'='*50}")
    print(f"Period:            {bt_start.date()} to {bt_end.date()}")
    print(f"Total entries:     {n_trades}")
    print(f"Closed trades:     {n_closed}")
    print(f"Open positions:    {n_open}")
    print(f"Final MTM P&L:     ${final_mtm:,.0f}")
    print(f"Realized P&L:      ${realized:,.0f}")
    print(f"Sharpe ratio:      {sharpe:.2f}")
    print(f"Max drawdown:      ${max_dd:,.0f}")
    print(f"Daily hit rate:    {hit_rate:.1%}")
    print(f"{'='*50}")

    # Trade log
    if bt.portfolio.closed_positions_log:
        print(f"\nClosed trade log ({len(bt.portfolio.closed_positions_log)} trades):")
        for entry in bt.portfolio.closed_positions_log[:10]:
            print(f"  Opened: {entry['opened_at']}, Closed: {entry['closed_at']}, "
                  f"P&L: ${entry['realized_pnl']:,.0f}, "
                  f"Days: {entry['holding_period_days']:.0f}, "
                  f"Reason: {entry.get('exit_meta', {}).get('reason', 'unknown')}")

    return {
        "mode": mode,
        "signal_dates": len(signal_table),
        "total_signals": total_signals,
        "passing_signals": passing_signals,
        "n_trades": n_trades,
        "n_closed": n_closed,
        "n_open": n_open,
        "final_mtm": final_mtm,
        "realized_pnl": realized,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "hit_rate": hit_rate,
        "error": None,
    }


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  IRSwap PCA RV Butterfly Backtest — All 3 Modes")
    print("=" * 70)

    results = []
    # Run all modes sequentially. To test a single mode, comment out the others.
    for mode in ["spot", "forward_stanchart", "forward_cs"]:
        try:
            r = run_mode(mode)
            results.append(r)
        except Exception as e:
            print(f"\nFATAL ERROR in mode {mode}: {e}")
            import traceback
            traceback.print_exc()
            results.append({"mode": mode, "error": str(e)})

    # ── Summary ──────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("  SUMMARY ACROSS ALL MODES")
    print(f"{'='*70}")
    summary_df = pd.DataFrame(results)
    print(summary_df.to_string(index=False))
    print(f"\nDone.")
