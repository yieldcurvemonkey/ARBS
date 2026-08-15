"""Artifact builder for strategy 1 (JPM curve-as-gamma).

The notebook loads parquet artifacts if they exist and rebuilds them if not.
Rebuilding the whole thing in one process is ~2h -- one curve build plus 13
repricings x 2 legs x 4 structures per day, then four 1900-day engine runs with
~50 concurrent 1-year cohorts each -- which is past nbconvert's timeout. So this
script does the same work in disjoint parallel chunks and writes the same files.

Usage (from the repo root, conda env ``stir``)::

    python notebooks/backtests/convexity_rv/_strat1_build.py panel <chunk> <nchunks>
    python notebooks/backtests/convexity_rv/_strat1_build.py bt <structure-label>
    python notebooks/backtests/convexity_rv/_strat1_build.py merge

Chunks are disjoint contiguous date ranges, so the day-partitioned curve store
is never written twice at the same key.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from RVUtils.ConvexityRV import strat1_curve_gamma as s1
from RVUtils.ConvexityRV.swaption_cube import atmf_vol_series, load_vol_panel

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)

CFG = s1.Strat1Config()


def safe(label: str) -> str:
    return label.replace("/", "-").replace(" ", "_")


def vol_artifacts():
    panel = load_vol_panel(
        [(CFG.swaption_expiry, CFG.swaption_tenor)], CFG.start, CFG.end,
        cache_path=DATA / "vol_1Yx30Y.parquet",
    )
    return panel, atmf_vol_series(panel, CFG.swaption_expiry, CFG.swaption_tenor)


def candidate_days() -> pd.DatetimeIndex:
    """Business days in the window, US federal holidays removed."""
    from pandas.tseries.holiday import USFederalHolidayCalendar
    from pandas.tseries.offsets import CustomBusinessDay

    cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    return pd.DatetimeIndex(pd.date_range(CFG.start, CFG.end, freq=cbd))


def build_panel(chunk: int, nchunks: int) -> None:
    days = candidate_days()
    parts = np.array_split(np.arange(len(days)), nchunks)
    mine = days[parts[chunk]]
    out = DATA / f"strat1_panel_chunk{chunk:02d}.parquet"
    print(f"chunk {chunk}/{nchunks}: {len(mine)} days {mine[0].date()}..{mine[-1].date()}", flush=True)

    panel, atmf = vol_artifacts()
    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    t0 = time.time()
    df = s1.build_signal_panel(
        mdp, CFG, mine, atmf_vol=atmf, vol_panel=panel,
        progress_every=50,
        log=lambda *a, **k: print(*a, flush=True),
    )
    df.reset_index().to_parquet(out, index=False)
    print(f"chunk {chunk}: wrote {out.name} rows={len(df)} in {time.time() - t0:.0f}s", flush=True)


def merge_panel() -> None:
    parts = sorted(DATA.glob("strat1_panel_chunk*.parquet"))
    if not parts:
        raise SystemExit("no panel chunks found")
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["date", "structure"]).sort_values(["date", "structure"])
    df.to_parquet(DATA / "strat1_signal_panel.parquet", index=False)
    n_days = df["date"].nunique()
    print(f"merged {len(parts)} chunks -> {len(df)} rows, {n_days} days "
          f"{df['date'].min().date()}..{df['date'].max().date()}")


def build_bt(label: str) -> None:
    ppath = DATA / "strat1_signal_panel.parquet"
    if not ppath.exists():
        raise SystemExit("signal panel missing -- run `panel` chunks then `merge` first")
    panel = pd.read_parquet(ppath)
    panel["date"] = pd.to_datetime(panel["date"])

    front, back = next((f, b) for (l, f, b) in CFG.structures if l == label)
    sub = panel[panel["structure"] == label].set_index("date").sort_index()
    if sub.empty:
        raise SystemExit(f"no panel rows for {label!r}")

    col = "signal_breakeven" if CFG.signal_mode == "breakeven_vol" else "signal_expected_payoff"
    # LAG 1: the signal is computed off day t's close, the cohort fills at t+1.
    signal = sub[col].shift(1).fillna(0.0)
    grid = sub.index

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    bt, cohorts = s1.build_backtest(mdp, CFG, label, front, back, signal, grid)
    print(f"{label}: {len(cohorts)} cohorts, {len(grid)} grid days", flush=True)
    t0 = time.time()
    bt.run()
    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    print(f"{label}: {len(eq)} marks in {time.time() - t0:.0f}s", flush=True)

    tbl = s1.cohort_table(bt, cohorts, CFG)
    eq.to_frame("equity_usd").to_parquet(DATA / f"strat1_equity_{safe(label)}.parquet")
    tbl.to_parquet(DATA / f"strat1_cohorts_{safe(label)}.parquet", index=False)
    closed = tbl[tbl["closed"]]
    print(f"{label}: closed {len(closed)}/{len(tbl)}  "
          f"gross {closed['gross_pnl_bp'].sum():+.1f}bp  "
          f"avg {closed['gross_pnl_bp'].mean():+.2f}bp  "
          f"hit {float((closed['gross_pnl_bp'] > 0).mean()):.1%}", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "panel":
        build_panel(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "merge":
        merge_panel()
    elif cmd == "bt":
        build_bt(sys.argv[2])
    else:
        raise SystemExit(f"unknown command {cmd!r}")
