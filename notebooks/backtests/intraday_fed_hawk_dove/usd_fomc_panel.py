"""Build a FED-only price panel across the SOFR strip, ranks 1..8.

The pooled study caps the strip at 6 because the ESTR / SONIA / CORRA / SARON
contracts thin out beyond that. SR3 does not - the SOFR strip is liquid well past
two years - so a USD-only search can look further out, which matters because the
contract that best expresses a policy-expectations signal need not be the front one.

    python usd_fomc_panel.py --stage panel
    python usd_fomc_panel.py --stage grid
"""

from __future__ import annotations

import argparse
import datetime
import pickle
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-gcb")
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd

from MDP.STIRFutures.STIRFutureMDP import STIRFutureMDP

import global_hawk_dove_common as G
import global_hawk_dove_grid as GRID
from global_hawk_dove_run import (
    CACHE, SCORES_CSV, SCORE_METRIC, BT_START, BT_END, BASE_BPV, BLACKOUT_BD,
    MAX_STALENESS_MIN, make_bucketer_factory, _p,
)
from global_hawk_dove_grid_run import _meta_frame, CAUSAL_MODES, NONCAUSAL_MODES

MAX_RANK = 8
ENTRY_MIN = [-120, -60, -45, -15]
EXIT_MIN = [60, 120, 180, 240]
PANEL = CACHE / "usd_panel.pkl"
RESULTS = CACHE / "usd_grid_results.csv"


def stage_panel(modes) -> None:
    scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)
    barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
    G.load_bar_cache(CACHE / "bars.pkl")
    cfg = G.CB_CONFIGS["FED"]

    store = {}
    for mode in modes:
        factory = make_bucketer_factory(scores, mode)
        events, _f = G.build_leg_events(
            cfg, scores, start=BT_START, end=BT_END,
            entry_offset=datetime.timedelta(minutes=-45),
            exit_offset=datetime.timedelta(minutes=180),
            base_bpv=BASE_BPV, contract_rank=3,
            bucketer_factory=factory, blackout_bd=BLACKOUT_BD,
        )
        events, _ = G.drop_overlaps(events)
        _p(f"  [{mode}] FED: {len(events)} events -> ranks 1..{MAX_RANK}")
        panel = GRID.build_price_panel(
            events, cfg, barchart, range(1, MAX_RANK + 1),
            max_staleness_min=MAX_STALENESS_MIN, show_progress=True)
        if panel.empty:
            continue
        store[mode] = {"panels": {"FED": panel}, "metas": {"FED": _meta_frame(events)}}
        G.save_bar_cache(CACHE / "bars.pkl")

    with open(PANEL, "wb") as f:
        pickle.dump(store, f)
    _p(f"wrote {PANEL}")
    if G.FETCH_FAILURES:
        _p(f"  WARNING: {len(G.FETCH_FAILURES)} fetches FAILED")


def stage_grid(cost_bp: float = 0.0) -> pd.DataFrame:
    with open(PANEL, "rb") as f:
        store = pickle.load(f)
    structures = GRID.build_structures(MAX_RANK)
    _p(f"{len(structures)} structures x {len(store)} schemes x "
       f"{len(ENTRY_MIN) * len(EXIT_MIN)} timings")

    frames = []
    for mode, blob in store.items():
        g = GRID.run_grid(blob["panels"], blob["metas"], structures, cost_bp=cost_bp)
        if g.empty:
            continue
        g["bucket_mode"] = mode
        g["causal"] = mode in CAUSAL_MODES
        frames.append(g)
    allg = pd.concat(frames, ignore_index=True)

    grid = allg[allg["causal"]].reset_index(drop=True)
    n_trials = len(grid) * len(ENTRY_MIN) * len(EXIT_MIN)
    grid = GRID.add_deflated(grid, n_trials=n_trials)

    out = grid.drop(columns=["_returns"])
    out.to_csv(RESULTS, index=False)
    _p(f"\nwrote {RESULTS}  ({len(out)} causal configs, n_trials={n_trials})")

    cols = ["structure", "kind", "bucket_mode", "trades", "total_bp", "avg_bp",
            "hit", "sharpe_ann", "t_stat", "dsr", "sr_star"]
    _p("\n=== TOP 20 BY SHARPE ===")
    _p(out[cols].head(20).round(4).to_string(index=False))
    _p("\n=== by structure family ===")
    _p(out.groupby("kind")["sharpe_ann"].agg(["count", "median", "max"]).round(3).to_string())
    _p("\n=== outright Sharpe by contract rank ===")
    o = out[out.kind == "outright"].copy()
    o["rank"] = o["structure"].str.split("_").str[1].astype(int)
    _p(o.pivot_table(index="rank", columns="bucket_mode",
                     values="sharpe_ann").round(3).to_string())

    alive = out[(out["dsr"] > 0.95) & (out["trades"] >= 50)]
    _p(f"\nconfigs with DSR > 0.95 and >=50 trades: {len(alive)} of {len(out)}")
    if len(alive):
        _p(alive[cols].head(15).round(4).to_string(index=False))

    nc = allg[~allg["causal"]]
    if len(nc):
        nc = GRID.add_deflated(nc.reset_index(drop=True),
                               n_trials=len(nc) * len(ENTRY_MIN) * len(EXIT_MIN))
        _p("\n=== NON-CAUSAL upper bound (researched / blended) ===")
        _p(nc.sort_values("sharpe_ann", ascending=False)[
            ["structure", "bucket_mode", "trades", "avg_bp", "sharpe_ann", "t_stat"]
        ].head(8).round(4).to_string(index=False))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="grid", choices=["panel", "grid"])
    ap.add_argument("--modes", default=",".join(CAUSAL_MODES + NONCAUSAL_MODES))
    ap.add_argument("--cost-bp", type=float, default=0.0)
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if args.stage == "panel":
        stage_panel(modes)
    else:
        stage_grid(args.cost_bp)


if __name__ == "__main__":
    main()
