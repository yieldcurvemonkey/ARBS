"""IRSwap PCA RV Butterfly — Vectorized Grid Search across all 3 curve modes.

Strategy: pre-compute ALL candidate fly series + OU fits ONCE per scan config,
then sweep threshold/filter parameters as cheap vectorized filtering operations.
This avoids re-fitting OU for every parameter combination.

Output: CSV per mode + combined CSV with Sharpe, P&L, drawdown, trade count
for each (scan_config × threshold_config) combination.

Usage:
    conda activate stir
    cd C:\\Users\\chris\\clee\\ARBS
    python -u notebooks/backtests/irswap_pca_rv_grid_search.py
"""
import sys, os, time, itertools, datetime, warnings, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
warnings.filterwarnings("ignore")
logging.getLogger("BT.signals.irswap_pca_rv_scanner").setLevel(logging.ERROR)

import numpy as np
import pandas as pd
import pytz
from dataclasses import replace

from BT.signals.irswap_pca_rv_scanner import (
    IRSwapPCARVConfig, scan_surface, identify_candidates,
    analyze_candidates, build_rate_queries, reshape_rates_panel,
    _build_fly_series, _fit_ou, compute_fly_weights,
    IRSwapPCASurfaceScan, IRSwapFlyCandidate, IRSwapAnalyzedTrade,
)

tz = pytz.timezone("America/New_York")

# ═══════════════════════════════════════════════════════════════════
# GRID
# ═══════════════════════════════════════════════════════════════════
SCAN_GRID = {
    "pca_window_days": [260, 390, 520],
    "pca_input":       ["levels", "changes"],
}

THRESHOLD_GRID = {
    "zscore_lookback_days": [130, 260],
    "min_zscore_belly":     [1.0, 1.5, 2.0],
    "min_zscore_wing":      [0.0, 0.25, 0.5],
    "max_adf_pvalue":       [0.10, 0.20, 0.50],
    "max_half_life_days":   [60.0, 120.0],
}

STANCHART_FWD = [None, "1Y", "5Y"]
CS_FLIES = [
    ("1Yx1Y", "3Yx1Y", "5Yx1Y"), ("2Yx1Y", "5Yx1Y", "8Yx1Y"),
    ("3Yx1Y", "5Yx1Y", "7Yx1Y"), ("5Yx1Y", "7Yx1Y", "9Yx1Y"),
    ("3Yx1Y", "5Yx1Y", "9Yx1Y"), ("5Yx1Y", "9Yx1Y", "12Yx3Y"),
    ("7Yx1Y", "10Yx2Y", "15Yx5Y"), ("9Yx1Y", "12Yx3Y", "20Yx5Y"),
    ("10Yx2Y", "15Yx5Y", "25Yx5Y"), ("15Yx5Y", "20Yx5Y", "30Yx10Y"),
]

DATA_START = datetime.datetime(2022, 1, 1, 17, tzinfo=tz)
DATA_END   = datetime.datetime(2026, 3, 20, 17, tzinfo=tz)
BT_START   = datetime.datetime(2024, 6, 1, 17, tzinfo=tz)
BT_END     = DATA_END

TRADE_BPV = 100_000.0
COST_BPS  = 0.5
MAX_POS   = 5


# ═══════════════════════════════════════════════════════════════════
# VECTORIZED BACKTEST (no QueryDrivenBacktest overhead)
# ═══════════════════════════════════════════════════════════════════

def _vectorized_fly_backtest(
    fly_series: pd.Series,
    ou_mean: float,
    ou_half_life: float,
    zscore_series: pd.Series,
    direction: int,  # +1 = receive belly (expect decrease), -1 = pay belly
    *,
    stop_loss_mult: float = 0.5,
    cost_bps: float = 0.5,
    bpv: float = 100_000.0,
) -> dict:
    """Fast vectorized backtest of a single fly using Z-score entry/exit.

    Entry: when |zscore| > threshold (handled by caller filtering)
    Exit: mean reversion (cross target) or stop-loss or max holding period
    """
    target = ou_mean
    dist = abs(fly_series.iloc[0] - target) if len(fly_series) > 0 else 0
    if dist == 0:
        return {"pnl": 0, "days": 0, "exit": "skip"}

    stop = fly_series.iloc[0] + direction * stop_loss_mult * dist * (-1)
    max_hold = int(ou_half_life * 3)

    entry_level = fly_series.iloc[0]
    entry_cost = cost_bps * 3 * bpv / 10000  # 3 legs

    for i in range(1, min(len(fly_series), max_hold + 1)):
        level = fly_series.iloc[i]

        # Mean reversion exit
        if direction == 1 and level <= target:
            pnl = (entry_level - level) * bpv * 10000 * direction - entry_cost
            return {"pnl": pnl, "days": i, "exit": "mean_reversion"}
        if direction == -1 and level >= target:
            pnl = (level - entry_level) * bpv * 10000 * abs(direction) - entry_cost
            return {"pnl": pnl, "days": i, "exit": "mean_reversion"}

        # Stop loss
        if direction == 1 and level >= stop:
            pnl = (entry_level - level) * bpv * 10000 * direction - entry_cost
            return {"pnl": pnl, "days": i, "exit": "stop_loss"}
        if direction == -1 and level <= stop:
            pnl = (level - entry_level) * bpv * 10000 * abs(direction) - entry_cost
            return {"pnl": pnl, "days": i, "exit": "stop_loss"}

    # Max holding exit
    if len(fly_series) > 1:
        final = fly_series.iloc[min(max_hold, len(fly_series) - 1)]
        pnl = (final - entry_level) * bpv * 10000 * direction - entry_cost
        return {"pnl": pnl, "days": min(max_hold, len(fly_series) - 1), "exit": "max_hold"}

    return {"pnl": -entry_cost, "days": 0, "exit": "timeout"}


def run_vectorized_grid(mode: str) -> pd.DataFrame:
    """Run vectorized grid search for one mode.

    Strategy:
    1. Load data once
    2. For each scan config (pca_window, pca_input):
       a. Run PCA scan -> Z-scores + residuals
       b. For every candidate fly found across ALL dates, fit OU once
       c. Store (fly_key, date, fly_series_from_date, ou_params, zscores)
    3. For each threshold config:
       a. Filter candidates by thresholds (cheap)
       b. Simulate trades vectorized
       c. Record metrics
    """
    from TB.TimeseriesBuilder import TimeseriesBuilder
    from TB.IRSwapsTB import IRSwapsTB
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    print(f"\n{'='*70}", flush=True)
    print(f"  GRID SEARCH: mode={mode}", flush=True)
    print(f"{'='*70}", flush=True)

    base_config = IRSwapPCARVConfig(curve_input_mode=mode, include_carry_roll=False)
    if mode == "forward_stanchart":
        base_config.forward_starts = list(STANCHART_FWD)
    if mode == "forward_cs":
        # Use auto-scan to find ALL butterfly patterns across CS forwards.
        # The old manual 10-fly universe was far too narrow — auto-scan
        # finds 50-80+ candidates per date across the 16 forward tenors.
        base_config.auto_scan_fly = True

    mdp = IRSwapsMDP(source=base_config.source)
    ts = TimeseriesBuilder()
    queries = build_rate_queries(base_config)
    router = {"IRS": IRSwapsTB(mdp, show_tqdm=True)}
    print(f"  Loading {len(queries)} queries...", flush=True)
    rates_df = ts.get_timeseries(start=DATA_START, end=DATA_END, queries=queries, n_jobs=12, routers=router)
    panels = reshape_rates_panel(rates_df, base_config)
    any_panel = next(iter(panels.values()))

    scan_keys = list(SCAN_GRID.keys())
    scan_combos = list(itertools.product(*SCAN_GRID.values()))
    thresh_keys = list(THRESHOLD_GRID.keys())
    thresh_combos = list(itertools.product(*THRESHOLD_GRID.values()))

    all_results = []
    t0 = time.perf_counter()

    for scan_combo in scan_combos:
        scan_p = dict(zip(scan_keys, scan_combo))
        pca_win = scan_p["pca_window_days"]
        pca_inp = scan_p["pca_input"]

        # === PHASE 1: PCA scan (once per scan config) ===
        scan_cfg = replace(base_config, pca_window_days=pca_win, pca_input=pca_inp)
        print(f"\n  --- Scan: pca={pca_win} inp={pca_inp} ---", flush=True)
        t1 = time.perf_counter()
        scan_result = scan_surface(panels, scan_cfg)
        print(f"  PCA scan: {time.perf_counter()-t1:.1f}s", flush=True)

        # === PHASE 2: Enumerate ALL candidate flies across all dates ===
        # For each zscore_lookback, we need a separate scan (Z-scores differ)
        for zs_lb in THRESHOLD_GRID["zscore_lookback_days"]:
            if zs_lb >= pca_win:
                continue

            zs_cfg = replace(scan_cfg, zscore_lookback_days=zs_lb)
            if zs_lb != scan_cfg.zscore_lookback_days:
                zs_scan = scan_surface(panels, zs_cfg)
            else:
                zs_scan = scan_result

            # Collect all unique fly candidates + OU fits
            warmup = pca_win + zs_lb
            bt_start_ts = pd.Timestamp(BT_START).tz_localize(None)
            bt_end_ts = pd.Timestamp(BT_END).tz_localize(None)

            dates = any_panel.index
            dates = dates[pd.Index([pd.Timestamp(d) for d in dates]) >= bt_start_ts]
            dates = dates[pd.Index([pd.Timestamp(d) for d in dates]) <= bt_end_ts]

            # Use relaxed thresholds to find ALL possible candidates
            relaxed_cfg = replace(zs_cfg,
                min_zscore_belly=0.5, min_zscore_wing=0.0,
                max_adf_pvalue=1.0, max_half_life_days=999,
            )

            print(f"  Building candidate pool (zs_lb={zs_lb})...", flush=True)
            t2 = time.perf_counter()

            # Collect candidate signals per date
            date_signals = []  # list of (date, candidate, ou_params, fly_from_date)
            ou_cache = {}  # fly_key -> ou_params

            for dt in dates:
                idx = any_panel.index.get_loc(dt)
                if idx < warmup:
                    continue

                cands = identify_candidates(zs_scan, panels, relaxed_cfg, date=dt)
                if not cands:
                    continue

                panels_to = {fwd: p.iloc[:idx+1] for fwd, p in panels.items()}

                for c in cands:
                    rp = panels_to.get(c.forward_start)
                    if rp is None:
                        continue

                    fly_key = (c.forward_start, c.tenors)
                    fly = _build_fly_series(c, rp)

                    # Cache OU fit per fly_key
                    if fly_key not in ou_cache:
                        try:
                            ou = _fit_ou(fly.iloc[-min(520, len(fly)):], relaxed_cfg)
                            ou_cache[fly_key] = ou
                        except Exception:
                            ou_cache[fly_key] = None

                    ou_params = ou_cache[fly_key]
                    if ou_params is None:
                        continue

                    # Get fly series from this date forward (for vectorized backtest)
                    full_rp = panels.get(c.forward_start)
                    if full_rp is None:
                        continue
                    fly_full = _build_fly_series(c, full_rp)
                    fly_forward = fly_full.iloc[idx:]

                    date_signals.append({
                        "date": dt,
                        "candidate": c,
                        "ou": ou_params,
                        "fly_forward": fly_forward,
                    })

            elapsed_build = time.perf_counter() - t2
            print(f"  {len(date_signals)} date-signals, {len(ou_cache)} unique flies "
                  f"({elapsed_build:.1f}s)", flush=True)

            # === PHASE 3: Sweep thresholds (vectorized, fast) ===
            for thresh_combo in thresh_combos:
                tp = dict(zip(thresh_keys, thresh_combo))
                if tp["zscore_lookback_days"] != zs_lb:
                    continue  # Already handled above

                belly_thresh = tp["min_zscore_belly"]
                wing_thresh = tp["min_zscore_wing"]
                max_adf = tp["max_adf_pvalue"]
                max_hl = tp["max_half_life_days"]

                # Filter signals
                trades = []
                active_count = 0
                last_exit_date = {}

                for sig in date_signals:
                    c = sig["candidate"]
                    ou = sig["ou"]

                    # Apply thresholds
                    if abs(c.zscore_belly) < belly_thresh:
                        continue
                    if abs(c.zscore_left) < wing_thresh or abs(c.zscore_right) < wing_thresh:
                        continue
                    if ou["adf_pvalue"] > max_adf:
                        continue
                    if ou["half_life"] > max_hl or ou["half_life"] < 3.0:
                        continue

                    # Max concurrent
                    if active_count >= MAX_POS:
                        continue

                    fly_key = (c.forward_start, c.tenors)
                    # No re-entry within holding period
                    if fly_key in last_exit_date:
                        if sig["date"] <= last_exit_date[fly_key]:
                            continue

                    direction = 1 if c.direction == "receive_belly" else -1
                    result = _vectorized_fly_backtest(
                        sig["fly_forward"],
                        ou["theta"], ou["half_life"],
                        pd.Series(),  # zscore not used in vectorized
                        direction,
                        cost_bps=COST_BPS, bpv=TRADE_BPV,
                    )

                    trades.append(result)
                    if result["days"] > 0:
                        exit_idx = any_panel.index.get_loc(sig["date"]) + result["days"]
                        if exit_idx < len(any_panel.index):
                            last_exit_date[fly_key] = any_panel.index[exit_idx]

                # Compute metrics
                row = {"mode": mode, **scan_p, **tp}
                if trades:
                    pnls = [t["pnl"] for t in trades]
                    days = [t["days"] for t in trades]
                    row["n_trades"] = len(trades)
                    row["total_pnl"] = sum(pnls)
                    row["avg_pnl"] = np.mean(pnls)
                    row["median_pnl"] = np.median(pnls)
                    row["win_rate"] = np.mean([1 if p > 0 else 0 for p in pnls])
                    row["avg_days"] = np.mean(days)
                    # Approximate Sharpe from trade P&Ls
                    if np.std(pnls) > 0:
                        row["sharpe"] = np.mean(pnls) / np.std(pnls) * np.sqrt(252 / max(np.mean(days), 1))
                    else:
                        row["sharpe"] = 0
                    row["max_loss"] = min(pnls)
                    exits = [t["exit"] for t in trades]
                    row["mr_exits"] = exits.count("mean_reversion")
                    row["sl_exits"] = exits.count("stop_loss")
                    row["mh_exits"] = exits.count("max_hold")
                else:
                    row.update(n_trades=0, total_pnl=0, avg_pnl=np.nan,
                               median_pnl=np.nan, win_rate=np.nan, avg_days=np.nan,
                               sharpe=np.nan, max_loss=0, mr_exits=0, sl_exits=0, mh_exits=0)

                all_results.append(row)

            elapsed = time.perf_counter() - t0
            n_done = len(all_results)
            print(f"  {n_done} combos done ({elapsed:.0f}s)", flush=True)

    return pd.DataFrame(all_results)


def print_top(df, mode, n=10):
    valid = df.dropna(subset=["sharpe"])
    valid = valid[valid["n_trades"] > 2]
    if valid.empty:
        print(f"\n  No valid results for {mode}", flush=True)
        return
    top = valid.sort_values("sharpe", ascending=False).head(n)
    print(f"\n{'='*70}", flush=True)
    print(f"  TOP {min(n, len(top))} — {mode.upper()}", flush=True)
    print(f"{'='*70}", flush=True)
    cols = ["pca_window_days", "pca_input", "zscore_lookback_days",
            "min_zscore_belly", "min_zscore_wing", "max_adf_pvalue", "max_half_life_days",
            "n_trades", "total_pnl", "sharpe", "win_rate", "avg_days",
            "mr_exits", "sl_exits", "mh_exits"]
    cols = [c for c in cols if c in top.columns]
    print(top[cols].to_string(index=False, float_format="%.2f"), flush=True)


if __name__ == "__main__":
    print("=" * 70, flush=True)
    print("  IRSwap PCA RV — Vectorized Grid Search", flush=True)
    print(f"  BT: {BT_START.date()} to {BT_END.date()}", flush=True)
    print("=" * 70, flush=True)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    all_dfs = []

    for mode in ["spot", "forward_stanchart", "forward_cs"]:
        try:
            df = run_vectorized_grid(mode)
            path = os.path.join(out_dir, f"irswap_pca_rv_grid_{mode}.csv")
            df.to_csv(path, index=False)
            print(f"\n  Saved {len(df)} rows -> {path}", flush=True)
            print_top(df, mode)
            all_dfs.append(df)
        except Exception as e:
            print(f"\n  FATAL: {mode}: {e}", flush=True)
            import traceback; traceback.print_exc()

    if all_dfs:
        combined = pd.concat(all_dfs, ignore_index=True)
        cpath = os.path.join(out_dir, "irswap_pca_rv_grid_combined.csv")
        combined.to_csv(cpath, index=False)
        print(f"\n{'='*70}", flush=True)
        print(f"  COMBINED: {len(combined)} rows -> {cpath}", flush=True)
        for mode in ["spot", "forward_stanchart", "forward_cs"]:
            sub = combined[(combined["mode"]==mode) & (combined["n_trades"]>2)]
            sub = sub.dropna(subset=["sharpe"])
            if sub.empty:
                print(f"  {mode}: no results", flush=True)
                continue
            b = sub.sort_values("sharpe", ascending=False).iloc[0]
            print(f"  {mode}: Sharpe={b['sharpe']:.2f} trades={b['n_trades']:.0f} "
                  f"P&L=${b['total_pnl']:,.0f} win={b['win_rate']:.0%} "
                  f"| pca={b['pca_window_days']:.0f} inp={b['pca_input']} "
                  f"zs={b['zscore_lookback_days']:.0f} belly={b['min_zscore_belly']:.1f} "
                  f"wing={b['min_zscore_wing']:.2f} adf={b['max_adf_pvalue']:.2f} "
                  f"hl={b['max_half_life_days']:.0f}", flush=True)

    print("\nDone.", flush=True)
