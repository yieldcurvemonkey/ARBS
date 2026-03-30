"""Forward CS grid search with auto-scan enabled."""
import sys, os, time, itertools, datetime, warnings, logging
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
warnings.filterwarnings("ignore")
logging.getLogger("BT.signals.irswap_pca_rv_scanner").setLevel(logging.ERROR)

import numpy as np, pandas as pd, pytz
from dataclasses import replace
from BT.signals.irswap_pca_rv_scanner import (
    IRSwapPCARVConfig, scan_surface, identify_candidates,
    build_rate_queries, reshape_rates_panel,
    _build_fly_series, _fit_ou,
)

tz = pytz.timezone("America/New_York")
DATA_START = datetime.datetime(2022, 1, 1, 17, tzinfo=tz)
DATA_END = datetime.datetime(2026, 3, 20, 17, tzinfo=tz)
BT_START = datetime.datetime(2024, 6, 1, 17, tzinfo=tz)
BT_END = DATA_END

SCAN_GRID = {
    "pca_window_days": [260, 390, 520],
    "pca_input": ["levels", "changes"],
}
THRESHOLD_GRID = {
    "zscore_lookback_days": [130, 260],
    "min_zscore_belly": [1.0, 1.5, 2.0],
    "min_zscore_wing": [0.0, 0.25, 0.5],
    "max_adf_pvalue": [0.10, 0.20, 0.50],
    "max_half_life_days": [60.0, 120.0],
}


def vectorized_fly_bt(fly_series, ou_mean, ou_hl, direction, cost_bps=0.5, bpv=100000):
    target = ou_mean
    dist = abs(fly_series.iloc[0] - target) if len(fly_series) > 0 else 0
    if dist == 0:
        return {"pnl": 0, "days": 0, "exit": "skip"}
    stop = fly_series.iloc[0] + direction * 0.5 * dist * (-1)
    max_hold = int(ou_hl * 3)
    entry = fly_series.iloc[0]
    cost = cost_bps * 3 * bpv / 10000
    for i in range(1, min(len(fly_series), max_hold + 1)):
        lev = fly_series.iloc[i]
        if direction == 1 and lev <= target:
            return {"pnl": (entry - lev) * bpv * 10000 * direction - cost, "days": i, "exit": "mr"}
        if direction == -1 and lev >= target:
            return {"pnl": (lev - entry) * bpv * 10000 - cost, "days": i, "exit": "mr"}
        if direction == 1 and lev >= stop:
            return {"pnl": (entry - lev) * bpv * 10000 * direction - cost, "days": i, "exit": "sl"}
        if direction == -1 and lev <= stop:
            return {"pnl": (lev - entry) * bpv * 10000 - cost, "days": i, "exit": "sl"}
    if len(fly_series) > 1:
        final = fly_series.iloc[min(max_hold, len(fly_series) - 1)]
        return {"pnl": (final - entry) * bpv * 10000 * direction - cost,
                "days": min(max_hold, len(fly_series) - 1), "exit": "mh"}
    return {"pnl": -cost, "days": 0, "exit": "timeout"}


if __name__ == "__main__":
    print("=" * 70, flush=True)
    print("  Forward CS Grid Search (auto_scan_fly=True)", flush=True)
    print("=" * 70, flush=True)

    mode = "forward_cs"
    base_config = IRSwapPCARVConfig(
        curve_input_mode=mode,
        include_carry_roll=False,
        auto_scan_fly=True,  # KEY FIX: enable auto-scan
    )

    from TB.TimeseriesBuilder import TimeseriesBuilder
    from TB.IRSwapsTB import IRSwapsTB
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source=base_config.source)
    ts_b = TimeseriesBuilder()
    queries = build_rate_queries(base_config)
    router = {"IRS": IRSwapsTB(mdp, show_tqdm=True)}
    print(f"Loading {len(queries)} queries...", flush=True)
    rates_df = ts_b.get_timeseries(start=DATA_START, end=DATA_END, queries=queries, n_jobs=12, routers=router)
    panels = reshape_rates_panel(rates_df, base_config)
    any_panel = next(iter(panels.values()))
    print(f"Panel: {any_panel.shape}", flush=True)

    scan_keys = list(SCAN_GRID.keys())
    scan_combos = list(itertools.product(*SCAN_GRID.values()))
    thresh_keys = list(THRESHOLD_GRID.keys())
    thresh_combos = list(itertools.product(*THRESHOLD_GRID.values()))

    results = []
    t0 = time.perf_counter()

    for scan_combo in scan_combos:
        scan_p = dict(zip(scan_keys, scan_combo))
        pca_win = scan_p["pca_window_days"]
        pca_inp = scan_p["pca_input"]

        scan_cfg = replace(base_config, pca_window_days=pca_win, pca_input=pca_inp)
        print(f"\n--- Scan: pca={pca_win} inp={pca_inp} ---", flush=True)
        scan_result = scan_surface(panels, scan_cfg)

        for zs_lb in THRESHOLD_GRID["zscore_lookback_days"]:
            if zs_lb >= pca_win:
                continue
            zs_cfg = replace(scan_cfg, zscore_lookback_days=zs_lb)
            if zs_lb != scan_cfg.zscore_lookback_days:
                zs_scan = scan_surface(panels, zs_cfg)
            else:
                zs_scan = scan_result

            warmup = pca_win + zs_lb
            bt_s = pd.Timestamp(BT_START).tz_localize(None)
            bt_e = pd.Timestamp(BT_END).tz_localize(None)
            dates = any_panel.index
            dates = dates[pd.Index([pd.Timestamp(d) for d in dates]) >= bt_s]
            dates = dates[pd.Index([pd.Timestamp(d) for d in dates]) <= bt_e]

            relaxed = replace(zs_cfg,
                min_zscore_belly=0.5, min_zscore_wing=0.0,
                max_adf_pvalue=1.0, max_half_life_days=999,
                auto_scan_fly=True,
            )

            t2 = time.perf_counter()
            date_signals = []
            ou_cache = {}

            for dt in dates:
                idx = any_panel.index.get_loc(dt)
                if idx < warmup:
                    continue
                cands = identify_candidates(zs_scan, panels, relaxed, date=dt)
                if not cands:
                    continue
                panels_to = {fwd: p.iloc[:idx + 1] for fwd, p in panels.items()}
                for c in cands:
                    rp = panels_to.get(c.forward_start)
                    if rp is None:
                        continue
                    fly_key = (c.forward_start, c.tenors)
                    fly = _build_fly_series(c, rp)
                    if fly_key not in ou_cache:
                        try:
                            ou_cache[fly_key] = _fit_ou(fly.iloc[-min(520, len(fly)):], relaxed)
                        except Exception:
                            ou_cache[fly_key] = None
                    ou_params = ou_cache[fly_key]
                    if ou_params is None:
                        continue
                    full_rp = panels.get(c.forward_start)
                    if full_rp is None:
                        continue
                    fly_full = _build_fly_series(c, full_rp)
                    fly_fwd = fly_full.iloc[idx:]
                    date_signals.append({
                        "date": dt, "candidate": c, "ou": ou_params, "fly_forward": fly_fwd,
                    })

            print(f"  zs_lb={zs_lb}: {len(date_signals)} signals, "
                  f"{len(ou_cache)} flies ({time.perf_counter() - t2:.1f}s)", flush=True)

            for thresh_combo in thresh_combos:
                tp = dict(zip(thresh_keys, thresh_combo))
                if tp["zscore_lookback_days"] != zs_lb:
                    continue

                belly_t = tp["min_zscore_belly"]
                wing_t = tp["min_zscore_wing"]
                max_adf = tp["max_adf_pvalue"]
                max_hl = tp["max_half_life_days"]

                trades = []
                last_exit = {}
                for sig in date_signals:
                    c = sig["candidate"]
                    ou = sig["ou"]
                    if abs(c.zscore_belly) < belly_t:
                        continue
                    if abs(c.zscore_left) < wing_t or abs(c.zscore_right) < wing_t:
                        continue
                    if ou["adf_pvalue"] > max_adf:
                        continue
                    if ou["half_life"] > max_hl or ou["half_life"] < 3.0:
                        continue
                    fly_key = (c.forward_start, c.tenors)
                    if fly_key in last_exit and sig["date"] <= last_exit[fly_key]:
                        continue
                    d = 1 if c.direction == "receive_belly" else -1
                    r = vectorized_fly_bt(sig["fly_forward"], ou["theta"], ou["half_life"], d)
                    trades.append(r)
                    if r["days"] > 0:
                        eidx = any_panel.index.get_loc(sig["date"]) + r["days"]
                        if eidx < len(any_panel.index):
                            last_exit[fly_key] = any_panel.index[eidx]

                row = {"mode": mode, **scan_p, **tp}
                if trades:
                    pnls = [t["pnl"] for t in trades]
                    days_list = [t["days"] for t in trades]
                    row["n_trades"] = len(trades)
                    row["total_pnl"] = sum(pnls)
                    row["avg_pnl"] = np.mean(pnls)
                    row["win_rate"] = np.mean([1 if p > 0 else 0 for p in pnls])
                    row["avg_days"] = np.mean(days_list)
                    row["sharpe"] = (np.mean(pnls) / np.std(pnls) * np.sqrt(252 / max(np.mean(days_list), 1))
                                     if np.std(pnls) > 0 else 0)
                    row["max_loss"] = min(pnls)
                    exits = [t["exit"] for t in trades]
                    row["mr_exits"] = exits.count("mr")
                    row["sl_exits"] = exits.count("sl")
                    row["mh_exits"] = exits.count("mh")
                else:
                    row.update(n_trades=0, total_pnl=0, avg_pnl=np.nan, win_rate=np.nan,
                               avg_days=np.nan, sharpe=np.nan, max_loss=0,
                               mr_exits=0, sl_exits=0, mh_exits=0)
                results.append(row)

            print(f"  {len(results)} combos done ({time.perf_counter() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(results)
    out_path = os.path.join(os.path.dirname(__file__), "irswap_pca_rv_grid_forward_cs.csv")
    df.to_csv(out_path, index=False)
    print(f"\nSaved {len(df)} rows to {out_path}", flush=True)

    valid = df.dropna(subset=["sharpe"])
    valid = valid[valid["n_trades"] > 2]
    print(f"Valid combos (>2 trades): {len(valid)}", flush=True)

    if not valid.empty:
        top = valid.sort_values("sharpe", ascending=False).head(15)
        cols = ["pca_window_days", "pca_input", "zscore_lookback_days",
                "min_zscore_belly", "min_zscore_wing", "max_adf_pvalue", "max_half_life_days",
                "n_trades", "total_pnl", "sharpe", "win_rate", "avg_days",
                "mr_exits", "sl_exits", "mh_exits"]
        print(f"\n{'='*80}", flush=True)
        print(f"  TOP 15 FORWARD_CS RESULTS", flush=True)
        print(f"{'='*80}", flush=True)
        print(top[cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"), flush=True)

        best = valid.sort_values("sharpe", ascending=False).iloc[0]
        print(f"\nBEST: Sharpe={best['sharpe']:.2f} trades={best['n_trades']:.0f} "
              f"P&L=${best['total_pnl']:,.0f} win={best['win_rate']:.0%}", flush=True)
        print(f"  pca={best['pca_window_days']:.0f} inp={best['pca_input']} "
              f"zs={best['zscore_lookback_days']:.0f}", flush=True)
        print(f"  belly={best['min_zscore_belly']:.1f} wing={best['min_zscore_wing']:.2f} "
              f"adf={best['max_adf_pvalue']:.2f} hl={best['max_half_life_days']:.0f}", flush=True)

        valid10 = valid[valid["n_trades"] >= 10]
        if not valid10.empty:
            b10 = valid10.sort_values("sharpe", ascending=False).iloc[0]
            print(f"\nBEST (>=10 trades): Sharpe={b10['sharpe']:.2f} trades={b10['n_trades']:.0f} "
                  f"P&L=${b10['total_pnl']:,.0f} win={b10['win_rate']:.0%}", flush=True)
            print(f"  pca={b10['pca_window_days']:.0f} inp={b10['pca_input']} "
                  f"zs={b10['zscore_lookback_days']:.0f}", flush=True)
            print(f"  belly={b10['min_zscore_belly']:.1f} wing={b10['min_zscore_wing']:.2f} "
                  f"adf={b10['max_adf_pvalue']:.2f} hl={b10['max_half_life_days']:.0f}", flush=True)
    else:
        print("No valid results with >2 trades", flush=True)

    print(f"\nTotal time: {time.perf_counter() - t0:.0f}s", flush=True)
    print("Done.", flush=True)
