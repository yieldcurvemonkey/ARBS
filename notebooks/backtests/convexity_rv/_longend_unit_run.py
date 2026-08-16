"""Engine pass ONLY: re-run one long-end structure as a pure flattener.

Split out of ``_strat1_threeway_longend_build.py`` so the (~minutes) engine run
can start before the module extension it verifies is finished. It writes
``strat1_threeway_longend_unit_cohorts_<label>.parquet``; the tie-out itself
lives in that script's ``verify`` command, which reads this cache.

    python notebooks/backtests/convexity_rv/_longend_unit_run.py "5Y/30Y"
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pathlib
import sys
import time

import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV.strat1_listed import LONG_END_STRUCTURES

DATA = _REPO / "notebooks" / "data" / "convexity_rv"


def safe(label: str) -> str:
    return label.replace("/", "-").replace(" ", "_")


def main(label: str) -> None:
    front, back = next((f, b) for (l, f, b) in LONG_END_STRUCTURES if l == label)
    panel = pd.read_parquet(DATA / "strat1_signal_panel.parquet")
    panel["date"] = pd.to_datetime(panel["date"])
    sub = (panel[panel["structure"] == label]
           .drop_duplicates(subset=["date"]).set_index("date").sort_index())

    # Strategy 1's OWN config -- the stored cohorts were built with it, so the
    # cohort grid, horizon, costs and package DV01 must match exactly.
    cfg = s1.Strat1Config(structures=LONG_END_STRUCTURES)
    out = DATA / f"strat1_threeway_longend_unit_cohorts_{safe(label)}.parquet"
    if out.exists():
        print(f"{label}: cache already exists at {out}")
        return

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    unit_signal = pd.Series(1.0, index=sub.index).shift(1).fillna(0.0)
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    bt, cohorts = s1.build_backtest(mdp, cfg, label, front, back, unit_signal, sub.index)
    print(f"{label}: unit-flattener run, {len(cohorts)} cohorts over "
          f"{len(sub)} grid dates", flush=True)
    t0 = time.time()
    bt.run()
    if not getattr(bt, "mtm_history", None):
        raise SystemExit(f"{label}: engine produced no mtm_history -- run() failed")
    print(f"{label}: ran in {time.time() - t0:.0f}s", flush=True)
    table = s1.cohort_table(bt, cohorts, cfg)
    table.to_parquet(out, index=False)
    print(f"{label}: wrote {out} ({len(table)} cohorts, "
          f"{int(table['closed'].sum())} closed)", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "5Y/30Y")
