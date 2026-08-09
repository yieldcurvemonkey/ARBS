"""Run the instrument / parameter grid search.

    python global_hawk_dove_grid_run.py --stage panel     # gather prices (slow, network)
    python global_hawk_dove_grid_run.py --stage grid      # score everything (fast)

The panel stage is separated because it is the only part that touches the
network; once it exists, thousands of configurations are pure arithmetic.
"""

from __future__ import annotations

import argparse
import datetime
import itertools
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
    MAX_STALENESS_MIN, BANKS, make_bucketer_factory, _p,
)

MAX_RANK = 6
ENTRY_MIN = [-120, -60, -45, -15]
EXIT_MIN = [60, 120, 180, 240]
#: Labelling schemes that a desk could actually have run at the time.
CAUSAL_MODES = ["peer", "percentile", "absolute"]

#: NOT point-in-time. The researched committee-standing table was written in 2026
#: from sources that postdate the trades it labels, and its period BOUNDARIES are
#: the largest free parameter in it - an adversarial audit showed an oracle table
#: at one period per speaker reaches t=5.8, and at speaker x year t=10.5, while
#: making the same table's estimation window causal collapses it to t=0.9. These
#: are computed and reported as an UPPER BOUND on what perfect knowledge of who
#: was a hawk would have been worth. They are never pooled into the deflation
#: with causal modes, because ranking a fitted label against honest ones and
#: deflating the lot as one experiment understates the search.
NONCAUSAL_MODES = ["researched", "blended"]

BUCKET_MODES = CAUSAL_MODES + NONCAUSAL_MODES


def _meta_frame(events) -> pd.DataFrame:
    """Per-event direction and timing, keyed by tag.

    ``side_rate`` is +1 for a hawk: the structures are defined in RATE space, so
    a hawk is long the structure. It is the negation of the futures-side used by
    the engine, where a hawk SELLS.
    """
    return pd.DataFrame([{
        "tag": e["tag"],
        "side_rate": -float(e["side"]),
        "size": 1.0,
        "opened_at": pd.Timestamp(e["entry_ts"]),
        "timestamp_source": e.get("timestamp_source", "forexfactory"),
        "bank": e["bank"], "speaker": e["speaker"], "bucket": e["bucket"],
    } for e in events]).set_index("tag")


def stage_panel(bucket_modes, legs) -> None:
    """Prices for every contract rank at every event of every labelling scheme."""
    scores = G.load_global_scores(SCORES_CSV, SCORE_METRIC)
    barchart = STIRFutureMDP(source="BARCHART_STIRF-RL")
    G.load_bar_cache(CACHE / "bars.pkl")

    store = {}
    for mode in bucket_modes:
        factory = make_bucketer_factory(scores, mode)
        panels, metas = {}, {}
        for bank in legs:
            cfg = G.CB_CONFIGS[bank]
            events, _funnel = G.build_leg_events(
                cfg, scores, start=BT_START, end=BT_END,
                entry_offset=datetime.timedelta(minutes=-45),
                exit_offset=datetime.timedelta(minutes=180),
                base_bpv=BASE_BPV, contract_rank=3,
                bucketer_factory=factory, blackout_bd=BLACKOUT_BD,
            )
            events, _ = G.drop_overlaps(events)
            if not events:
                continue
            _p(f"  [{mode}] {bank}: {len(events)} events -> panel over ranks 1..{MAX_RANK}")
            panel = GRID.build_price_panel(
                events, cfg, barchart, range(1, MAX_RANK + 1),
                max_staleness_min=MAX_STALENESS_MIN, show_progress=True)
            if panel.empty:
                continue
            panels[bank] = panel
            metas[bank] = _meta_frame(events)
        store[mode] = {"panels": panels, "metas": metas}
        G.save_bar_cache(CACHE / "bars.pkl")

    with open(CACHE / "grid_panel.pkl", "wb") as f:
        pickle.dump(store, f)
    _p(f"wrote {CACHE / 'grid_panel.pkl'}")


def stage_grid(cost_bp: float) -> pd.DataFrame:
    with open(CACHE / "grid_panel.pkl", "rb") as f:
        store = pickle.load(f)

    structures = GRID.build_structures(MAX_RANK)
    _p(f"{len(structures)} structures x {len(store)} labelling schemes "
       f"x {len(ENTRY_MIN) * len(EXIT_MIN)} timings")

    frames = []
    for mode, blob in store.items():
        g = GRID.run_grid(blob["panels"], blob["metas"], structures, cost_bp=cost_bp)
        if g.empty:
            continue
        g["bucket_mode"] = mode
        g["causal"] = mode in CAUSAL_MODES
        frames.append(g)
    if not frames:
        raise SystemExit("empty grid")
    allg = pd.concat(frames, ignore_index=True)

    # Deflate the CAUSAL search on its own. The timing dimension multiplies the
    # trial count even though the panel is built at one timing, so it is counted:
    # understating the trials would understate the hurdle.
    grid = allg[allg["causal"]].reset_index(drop=True)
    n_trials = len(grid) * len(ENTRY_MIN) * len(EXIT_MIN)
    grid = GRID.add_deflated(grid, n_trials=n_trials)

    noncausal = allg[~allg["causal"]].reset_index(drop=True)
    if len(noncausal):
        nc = GRID.add_deflated(noncausal, n_trials=len(noncausal) * len(ENTRY_MIN) * len(EXIT_MIN))
        _p("\n=== NON-CAUSAL UPPER BOUND (researched / blended labels) ===")
        _p("These use a stance table written in 2026 about trades from 2021-2026. They are")
        _p("NOT tradeable and are shown only to bound what perfect knowledge of who was a")
        _p("hawk would have been worth.")
        _p(nc.sort_values("sharpe_ann", ascending=False)[
            ["structure", "bucket_mode", "trades", "avg_bp", "sharpe_ann", "t_stat"]
        ].head(10).round(4).to_string(index=False))

    out = grid.drop(columns=["_returns"])
    out.to_csv(CACHE / "grid_results.csv", index=False)
    _p(f"\nwrote {CACHE / 'grid_results.csv'}  ({len(out)} configs, n_trials={n_trials})")

    cols = ["structure", "kind", "bucket_mode", "trades", "total_bp", "avg_bp",
            "hit", "sharpe_ann", "t_stat", "dsr", "sr_star"]
    _p("\n=== TOP 25 BY SHARPE ===")
    _p(out[cols].head(25).round(4).to_string(index=False))
    _p("\n=== TOP 10 BY DEFLATED SHARPE ===")
    _p(out.sort_values("dsr", ascending=False)[cols].head(10).round(4).to_string(index=False))
    _p("\n=== by structure kind (median annualised Sharpe) ===")
    _p(out.groupby("kind")["sharpe_ann"].agg(["count", "median", "max"]).round(3).to_string())
    _p("\n=== by labelling scheme ===")
    _p(out.groupby("bucket_mode")[["sharpe_ann", "avg_bp", "trades"]]
       .agg({"sharpe_ann": ["median", "max"], "avg_bp": "median", "trades": "median"})
       .round(4).to_string())

    alive = out[(out["dsr"] > 0.95) & (out["trades"] >= 50)]
    _p(f"\nconfigs with DSR > 0.95 and >=50 trades: {len(alive)}")
    if len(alive):
        _p(alive[cols].head(15).round(4).to_string(index=False))
    else:
        _p("  NONE — every configuration's Sharpe is inside what this many trials\n"
           "  would produce from noise alone.")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="grid", choices=["panel", "grid"])
    ap.add_argument("--cost-bp", type=float, default=0.0)
    ap.add_argument("--modes", default=",".join(BUCKET_MODES))
    ap.add_argument("--legs", default=",".join(BANKS))
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    legs = [x.strip().upper() for x in args.legs.split(",") if x.strip()]

    if args.stage == "panel":
        stage_panel(modes, legs)
    else:
        stage_grid(args.cost_bp)


if __name__ == "__main__":
    main()
