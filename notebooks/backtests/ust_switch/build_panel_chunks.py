"""Resumable per-(tenor, year) panel builder.

Why this exists instead of just calling ``get_timeseries`` once
---------------------------------------------------------------
``FixedRateBondsTB.get_timeseries`` DEADLOCKS on large requests. Measured twice:

* one 2010-2026 call for all seven tenors -- 0.00 CPU seconds per 20s of wall clock, 150
  threads in ``Wait``, no external sockets, nothing written for 55 minutes;
* year-chunked with ``n_jobs=4`` -- survived ~110 of 112 chunks and then stalled with the
  identical signature on the last one, after 5,309 CPU-seconds of real work.

So chunking alone is not the fix; it only moved the stall. Two changes make it robust:

1. **``n_jobs=1``.** No ``ThreadPoolExecutor``, so no contention with the ZODB-backed
   ``LayeredCacheMixin`` that the thread pool appears to deadlock against. This costs
   nothing: a chunk already in ``data/ts`` returns in **0.2 seconds** single-threaded, and
   ~95% of the range is cached by the runs that got that far.
2. **Persist every chunk immediately.** A stall then costs one chunk, not the run. Re-run
   and it resumes.

Diagnosing this needs CPU-time delta, not the log: a deadlocked process and a slow one look
identical in the output file, and stdout through a pipe is block-buffered anyway.

    <env>/python.exe notebooks/backtests/ust_switch/build_panel_chunks.py            # resume
    <env>/python.exe notebooks/backtests/ust_switch/build_panel_chunks.py --assemble  # combine
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import sys
import time

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from notebooks.backtests.ust_switch.build_bond_panel import (  # noqa: E402
    MAX_RANK,
    TENORS,
    alias_for,
)

HERE = pathlib.Path(__file__).resolve().parent
DATA = HERE / "_data"
CHUNKS = DATA / "chunks"
PANEL_PATH = DATA / "bond_panel.parquet"
MAP_PATH = DATA / "alias_cusip_map.parquet"


def chunk_path(tenor: int, year: int) -> pathlib.Path:
    return CHUNKS / f"t{tenor}_y{year}.parquet"


def fetch_chunk(tb, tenor: int, c_start, c_end):
    from Query.FixedRateBonds.FixedRateBondQuery import FixedRateBondQuery
    from Query.FixedRateBonds.FixedRateBondValue import FixedRateBondValue

    values = [
        FixedRateBondValue.YTM,
        FixedRateBondValue.DV01,
        FixedRateBondValue.CLEAN_PRICE,
        FixedRateBondValue.DIRTY_PRICE,
        FixedRateBondValue.MOD_DURATION,
    ]
    qs = [
        FixedRateBondQuery(cusip=alias_for(r, tenor), value=v,
                           structure_kwargs={"notional": 1_000_000})
        for r in range(MAX_RANK + 1)
        for v in values
    ]
    df = tb.get_timeseries(start=c_start, end=c_end, queries=qs, n_jobs=1)
    if df is None or df.empty:
        return None
    df.columns = [str(c) for c in df.columns]
    long = df.stack().rename("value").reset_index()
    long.columns = ["date", "col", "value"]
    parts = long["col"].str.split(" ", expand=True)
    long["alias"] = parts[0]
    long["value_id"] = parts[2]
    long["tenor"] = tenor
    long["date"] = pd.to_datetime(long["date"])
    return long[["date", "tenor", "alias", "value_id", "value"]]


def build(amap: pd.DataFrame, start: datetime.date, end: datetime.date, *, force: bool = False) -> None:
    from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
    from TB.FixedRateBondsTB import FixedRateBondsTB

    CHUNKS.mkdir(parents=True, exist_ok=True)
    mdp = FixedRateBondsMDP(source="USTS_FEDINVEST_WSJ_LIVE-QL")
    tb = FixedRateBondsTB(mdp, show_tqdm=False)

    todo = []
    for tenor in TENORS:
        sub = amap[(amap["tenor"] == tenor) & (amap["rank"] == 0)]
        if sub.empty:
            continue
        t_start = max(start, sub["date"].min().date())
        t_end = min(end, sub["date"].max().date())
        for yr in range(t_start.year, t_end.year + 1):
            cs = max(t_start, datetime.date(yr, 1, 1))
            ce = min(t_end, datetime.date(yr, 12, 31))
            if cs <= ce:
                todo.append((tenor, yr, cs, ce))

    done = sum(1 for t, y, _, _ in todo if chunk_path(t, y).exists())
    print(f"{len(todo)} chunks, {done} already on disk, {len(todo) - done} to fetch", flush=True)

    for i, (tenor, yr, cs, ce) in enumerate(todo, 1):
        p = chunk_path(tenor, yr)
        if p.exists() and not force:
            continue
        t0 = time.time()
        try:
            part = fetch_chunk(tb, tenor, cs, ce)
        except Exception as exc:
            print(f"  [{i}/{len(todo)}] {tenor}Y {yr}: FAILED {type(exc).__name__}: {exc}", flush=True)
            continue
        if part is None:
            print(f"  [{i}/{len(todo)}] {tenor}Y {yr}: EMPTY", flush=True)
            continue
        part.to_parquet(p, index=False)
        print(f"  [{i}/{len(todo)}] {tenor}Y {yr}: {len(part):6d} rows ({time.time() - t0:5.1f}s)", flush=True)


def assemble(amap: pd.DataFrame) -> pd.DataFrame:
    files = sorted(CHUNKS.glob("t*_y*.parquet"))
    if not files:
        raise FileNotFoundError(f"no chunks under {CHUNKS}")
    long = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    long["date"] = pd.to_datetime(long["date"])
    wide = long.pivot_table(
        index=["date", "tenor", "alias"], columns="value_id", values="value", aggfunc="first"
    ).reset_index()
    wide.columns.name = None
    keys = amap[["date", "tenor", "alias", "rank", "cusip", "cpn", "issue_date", "maturity_date"]]
    out = wide.merge(keys, on=["date", "tenor", "alias"], how="inner")
    return out.sort_values(["tenor", "date", "rank"]).reset_index(drop=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2010-01-01")
    ap.add_argument("--end", default="2026-08-17")
    ap.add_argument("--assemble", action="store_true", help="skip fetching, just combine")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)

    amap = pd.read_parquet(MAP_PATH)
    amap["date"] = pd.to_datetime(amap["date"])

    if not a.assemble:
        build(amap, datetime.date.fromisoformat(a.start), datetime.date.fromisoformat(a.end),
              force=a.force)

    panel = assemble(amap)
    panel.to_parquet(PANEL_PATH, index=False)
    print(f"\npanel {panel.shape} -> {PANEL_PATH}")
    print(f"  {panel['date'].min().date()} .. {panel['date'].max().date()}  "
          f"{panel['date'].nunique()} days  {panel['cusip'].nunique()} cusips")
    print(panel.groupby(["tenor", "rank"])["YTM"].agg(["count", "mean"]).round(3).to_string())
    print(f"\nYTM missing: {panel['YTM'].isna().mean():.4%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
