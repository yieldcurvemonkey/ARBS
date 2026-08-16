"""Artifact builder for strategy 1-listed (curve gamma vs EXCHANGE-LISTED vol).

The notebook loads parquet artifacts if they exist and rebuilds them if not.
Building the whole thing in one process is ~25 minutes -- one curve build plus 21
repricings x 2 legs x 5 structures per day over 525 dates, then five engine runs
with ~50 concurrent 1-year cohorts each -- which is past nbconvert's default
timeout. So this script does the work and writes the files; the notebook reads.

Usage (from the repo root, conda env ``stir``)::

    python notebooks/backtests/convexity_rv/_strat1_listed_build.py vol
    python notebooks/backtests/convexity_rv/_strat1_listed_build.py panel [chunk nchunks]
    python notebooks/backtests/convexity_rv/_strat1_listed_build.py merge
    python notebooks/backtests/convexity_rv/_strat1_listed_build.py bt <structure-label>
    python notebooks/backtests/convexity_rv/_strat1_listed_build.py all

Chunks are disjoint contiguous date ranges, so the day-partitioned curve store is
never written twice at the same key.

NETWORK: nothing here touches a listed-option MDP. The listed leg is read from
``notebooks/data/sfr_rv_lab/*.parquet`` and the OTC leg from the local swaption
cube store. There is no code path in this file that can reach a vendor.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime
import json
import pathlib
import sys
import time

import numpy as np
import pandas as pd

_REPO = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
from RVUtils.ConvexityRV import listed_vol as lv
from RVUtils.ConvexityRV import strat1_listed as sl
from RVUtils.ConvexityRV.swaption_cube import atmf_vol_series, load_vol_panel

DATA = _REPO / "notebooks" / "data" / "convexity_rv"
DATA.mkdir(parents=True, exist_ok=True)

CFG = sl.Strat1ListedConfig()

OTC_CACHE = DATA / f"vol_{CFG.otc_expiry}x{CFG.otc_tenor}.parquet"
LISTED_ATM = DATA / "strat1_listed_atm_panel.parquet"
LISTED_SERIES = DATA / "strat1_listed_atm_matched.parquet"
PANEL = DATA / "strat1_listed_signal_panel.parquet"


def safe(label: str) -> str:
    return label.replace("/", "-").replace(" ", "_")


# ------------------------------------------------------------------ vol inputs


def listed_artifacts(rebuild: bool = False):
    """(quote panel, per-contract ATM panel, horizon-matched series)."""
    panel = lv.load_sfr_panel(start=CFG.start, end=CFG.end)
    if LISTED_ATM.exists() and not rebuild:
        atm = pd.read_parquet(LISTED_ATM)
        atm["as_of"] = pd.to_datetime(atm["as_of"])
    else:
        atm = lv.sfr_atm_vol_panel(panel, business_days_per_year=CFG.business_days_per_year)
        atm.to_parquet(LISTED_ATM, index=False)
    series = lv.listed_atm_series(
        atm, CFG.horizon_years,
        max_gap_days=CFG.listed_max_gap_days,
        min_tte_years=CFG.listed_min_tte_years,
    )
    series.reset_index().to_parquet(LISTED_SERIES, index=False)
    return panel, atm, series


def otc_artifacts():
    """(swaption smile panel, sector-matched ATMF series in bp/yr)."""
    panel = load_vol_panel(
        [(CFG.otc_expiry, CFG.otc_tenor)], CFG.start, CFG.end, cache_path=OTC_CACHE,
    )
    return panel, atmf_vol_series(panel, CFG.otc_expiry, CFG.otc_tenor)


def build_vol() -> None:
    lp, atm, series = listed_artifacts(rebuild=True)
    op, otc = otc_artifacts()
    print(f"listed quotes {len(lp)} rows / {lp['as_of'].nunique()} dates", flush=True)
    print(f"listed ATM panel {len(atm)} (date, contract) rows", flush=True)
    print(f"horizon-matched listed series {len(series)} dates "
          f"{series.index.min().date()}..{series.index.max().date()}", flush=True)
    print(f"OTC {CFG.otc_expiry}x{CFG.otc_tenor} smile {len(op)} rows, "
          f"ATMF {len(otc)} dates", flush=True)


# ----------------------------------------------------------------- signal panel


def build_panel(chunk: int = 0, nchunks: int = 1) -> None:
    lp, atm, series = listed_artifacts()
    op, otc = otc_artifacts()

    # The grid is the listed panel's own dates -- the swap curve covers
    # 2019-2026, so the listed side is what binds.
    days = pd.DatetimeIndex(sorted(pd.unique(lp["as_of"])))
    parts = np.array_split(np.arange(len(days)), nchunks)
    mine = days[parts[chunk]]
    out = DATA / f"strat1_listed_panel_chunk{chunk:02d}.parquet"
    print(f"chunk {chunk}/{nchunks}: {len(mine)} days "
          f"{mine[0].date()}..{mine[-1].date()}", flush=True)

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    t0 = time.time()
    df = sl.build_listed_signal_panel(
        mdp, CFG, mine,
        listed_series=series, listed_panel=lp, otc_atmf=otc, otc_panel=op,
        progress_every=50, log=lambda *a, **k: print(*a, flush=True),
    )
    df.reset_index().to_parquet(out, index=False)
    print(f"chunk {chunk}: wrote {out.name} rows={len(df)} in {time.time() - t0:.0f}s",
          flush=True)


def merge_panel() -> None:
    parts = sorted(DATA.glob("strat1_listed_panel_chunk*.parquet"))
    if not parts:
        raise SystemExit("no panel chunks found")
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["date", "structure"]).sort_values(["date", "structure"])
    df.to_parquet(PANEL, index=False)
    print(f"merged {len(parts)} chunks -> {len(df)} rows, {df['date'].nunique()} days "
          f"{df['date'].min().date()}..{df['date'].max().date()}")


# -------------------------------------------------------------------- backtest


def build_bt(label: str) -> None:
    if not PANEL.exists():
        raise SystemExit("signal panel missing -- run `panel` then `merge` first")
    panel = pd.read_parquet(PANEL)
    panel["date"] = pd.to_datetime(panel["date"])

    front, back = next((f, b) for (l, f, b) in CFG.structures if l == label)
    sub = panel[panel["structure"] == label].set_index("date").sort_index()
    if sub.empty:
        raise SystemExit(f"no panel rows for {label!r}")

    col = ("signal_listed" if CFG.benchmark == "listed" else "signal_otc")
    if CFG.signal_mode != "breakeven_vol":
        col = ("signal_ep_listed" if CFG.benchmark == "listed" else "signal_ep_otc")
    # LAG 1: the signal is computed off day t's close, the cohort fills at t+1.
    signal = sub[col].shift(1).fillna(0.0)
    grid = sub.index

    mdp = IRSwapsMDP(source="CITIVELO_EXCEL")
    bt, cohorts = sl.build_backtest(mdp, CFG.curve_config(), label, front, back, signal, grid)
    print(f"{label}: {len(cohorts)} cohorts, {len(grid)} grid days", flush=True)
    t0 = time.time()
    bt.run()
    # QueryDrivenBacktest.run() SWALLOWS exceptions -- assert on the output.
    if not getattr(bt, "mtm_history", None):
        raise SystemExit(f"{label}: engine produced no mtm_history -- run() failed silently")
    eq = pd.Series(bt.mtm_history)
    eq.index = pd.to_datetime(eq.index)
    print(f"{label}: {len(eq)} marks in {time.time() - t0:.0f}s", flush=True)

    tbl = sl.cohort_table(bt, cohorts, CFG.curve_config())
    eq.to_frame("equity_usd").to_parquet(DATA / f"strat1_listed_equity_{safe(label)}.parquet")
    tbl.to_parquet(DATA / f"strat1_listed_cohorts_{safe(label)}.parquet", index=False)
    closed = tbl[tbl["closed"]]
    if len(closed):
        print(f"{label}: closed {len(closed)}/{len(tbl)}  "
              f"gross {closed['gross_pnl_bp'].sum():+.1f}bp  "
              f"avg {closed['gross_pnl_bp'].mean():+.2f}bp  "
              f"hit {float((closed['gross_pnl_bp'] > 0).mean()):.1%}", flush=True)
    else:
        print(f"{label}: 0 of {len(tbl)} cohorts closed inside the sample", flush=True)


def build_all() -> None:
    build_vol()
    build_panel(0, 1)
    merge_panel()
    for label, _f, _b in CFG.structures:
        build_bt(label)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "vol":
        build_vol()
    elif cmd == "panel":
        if len(sys.argv) > 3:
            build_panel(int(sys.argv[2]), int(sys.argv[3]))
        else:
            build_panel(0, 1)
    elif cmd == "merge":
        merge_panel()
    elif cmd == "bt":
        build_bt(sys.argv[2])
    elif cmd == "all":
        build_all()
    else:
        raise SystemExit(f"unknown command {cmd!r}")
