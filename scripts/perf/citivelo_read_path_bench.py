"""Component-timed profile of the Citi Velocity timeseries read path.

Run:
    <env>/python.exe scripts/perf/citivelo_read_path_bench.py [--mode intraday|eod|both]

Everything here is served from the warmed local CurveStore. No Excel, no
network beyond the once-per-process fixings pull.

Why component-timed and not just cProfile: the last 276x on this path was found
by timing components, not by reading a flat total. cProfile is run too (as
``--cprofile``) but the per-stage numbers below are the ones that motivate
changes.
"""

from __future__ import annotations

import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import argparse
import cProfile
import datetime
import io
import pstats
import sys
import time
from pathlib import Path

import pandas as pd
import pytz

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

NYC = pytz.timezone("America/New_York")

DAY = datetime.date(2026, 7, 22)
CURVE = "USD-SOFR-1D"


def _minutes(day: datetime.date, n: int) -> list[datetime.datetime]:
    start = NYC.localize(datetime.datetime.combine(day, datetime.time(3, 0)))
    return [start + datetime.timedelta(minutes=i) for i in range(n)]


def bench_single_point(n: int = 200) -> None:
    """Time N single-point get_data calls, the shape TB's fallback loop uses."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    pts = _minutes(DAY, n)

    # warm every process-wide cache first so we measure the steady state
    mdp.get_data({"curve_name": CURVE, "timestamp": pts[0]})

    t0 = time.perf_counter()
    for t in pts:
        mdp.get_data({"curve_name": CURVE, "timestamp": t})
    dt = time.perf_counter() - t0
    print(f"[single get_data]  {n} pts in {dt:8.3f}s   {1000 * dt / n:7.2f} ms/obs")


def bench_bulk(n: int = 200) -> None:
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    pts = _minutes(DAY, n)
    mdp.get_data({"curve_name": CURVE, "timestamp": pts[0]})

    t0 = time.perf_counter()
    out = mdp.bulk_get_data({"curve_name": CURVE, "timestamps": list(pts)})
    dt = time.perf_counter() - t0
    print(f"[bulk_get_data ]  {n} pts in {dt:8.3f}s   {1000 * dt / n:7.2f} ms/obs   (got {len(out)})")


def bench_components(n: int = 200) -> None:
    """Per-stage cost inside one minute-store point."""
    import zoneinfo

    from Caching.curve_store import CurveStore
    from MDP.IRSwaps.CITIVELO_EXCEL import register
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import (
        citi_index_for_curve_name,
        entry_for_curve_name,
    )
    from MDP.IRSwaps.CITIVELO_EXCEL.fixings import fixings_for
    from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import from_wire_naive, resolve_request
    from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import RLIRSwapCurve

    register()
    store = CurveStore.default()
    asset = f"{CURVE}-CITIVELOEXCELMIN"
    entry = entry_for_curve_name(CURVE)
    citi_index = citi_index_for_curve_name(CURVE)
    pts = _minutes(DAY, n)

    # warm
    fixings_for(CURVE, citi_index, reference_date=DAY)
    store.read_raw_day(asset, DAY)

    acc: dict[str, float] = {}

    def timed(name: str, fn):
        t0 = time.perf_counter()
        r = fn()
        acc[name] = acc.get(name, 0.0) + (time.perf_counter() - t0)
        return r

    for t in pts:
        resolved = timed("resolve_request", lambda: resolve_request(t))
        wanted = timed("from_wire_naive", lambda: from_wire_naive(resolved.wire_instant))
        local_zone = timed("zoneinfo", lambda: zoneinfo.ZoneInfo(entry.local_timezone))
        local_date = wanted.astimezone(local_zone).date()
        timed("register", register)
        frames = []
        for offset in (0, -1, 1):
            day = local_date + datetime.timedelta(days=offset)
            if not timed("has_day", lambda d=day: store.has_day(asset, d)):
                continue
            raw = timed("read_raw_day", lambda d=day: store.read_raw_day(asset, d))
            if raw is not None and not raw.empty:
                frames.append(raw)
        raw = timed("concat", lambda: pd.concat(frames) if len(frames) > 1 else frames[0])
        stamps = timed("to_datetime", lambda: pd.to_datetime(raw["timestamp_utc"], utc=True))
        position = timed(
            "argmin",
            lambda: int((stamps - pd.Timestamp(wanted).tz_convert("UTC")).abs().values.argmin()),
        )
        row = timed("iloc", lambda: raw.iloc[[position]])
        curves = timed(
            "reconstruct", lambda: store.reconstruct_curves_batch(row, cfg=None, max_workers=1)
        )
        handle = next(iter(curves.values()))
        actual = stamps.iloc[position].to_pydatetime()
        ref = actual.astimezone(local_zone).date()
        res = timed("fixings_for", lambda: fixings_for(CURVE, citi_index, reference_date=ref))
        timed("gap_to", lambda: res.gap_to(ref))
        timed(
            "wrap",
            lambda: RLIRSwapCurve(
                rl_curve_id=CURVE,
                rl_curve_handle=handle,
                fixings=res.series,
                meta_data={"timestamp": actual},
            ),
        )

    total = sum(acc.values())
    print(f"\n[components] {n} points, {total:.3f}s total ({1000 * total / n:.2f} ms/obs)")
    for k, v in sorted(acc.items(), key=lambda kv: -kv[1]):
        print(f"    {k:20s} {1000 * v / n:8.3f} ms/obs   {100 * v / total:5.1f}%")


def bench_pricing(n: int = 200) -> None:
    """The Query layer: what it costs to turn a curve into one IRS_RATE."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from TB.IRSwapsTB import _build_row_for_query

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    pts = _minutes(DAY, n)
    curves = [mdp.get_data({"curve_name": CURVE, "timestamp": t}) for t in pts]
    q = IRSwapQuery(curve=CURVE, tenor="10Y", value=IRSwapValue.RATE)

    _build_row_for_query(curves[0], q, pts[0], "Date")
    t0 = time.perf_counter()
    for c, t in zip(curves, pts):
        _build_row_for_query(c, q, t, "Date")
    dt = time.perf_counter() - t0
    print(f"[pricing row   ]  {n} pts in {dt:8.3f}s   {1000 * dt / n:7.2f} ms/obs")


def bench_timeseries(n: int = 841) -> None:
    """End-to-end, the way the notebook does it."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.Unified.UnifiedQuery import UnifiedQuery
    from Query.Unified.registry import UnifiedValue
    from TB.IRSwapsTB import IRSwapsTB
    from TB.TimeseriesBuilder import TimeseriesBuilder

    import shutil
    import uuid
    from pathlib import Path as _Path

    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    # A throwaway mapping-cache stem. Without it the second run of this bench
    # serves 841 cached rows in 0.13 s and measures nothing.
    tb = IRSwapsTB(
        mdp, show_tqdm=False, use_ts_cache=False,
        cache_stem=f"perfbench_{uuid.uuid4().hex[:12]}",
    )
    ts = TimeseriesBuilder()
    pts = _minutes(DAY, n)

    try:
        t0 = time.perf_counter()
        df = ts.get_timeseries(
            start=pts[0],
            end=pts[-1],
            queries=[UnifiedQuery(curve=CURVE, tenor="10Y", value=UnifiedValue.IRS_RATE)],
            freq="1min",
            routers={"IRS": tb},
            ignore_cache_miss=True,
        )
        dt = time.perf_counter() - t0
        print(f"[get_timeseries]  {len(df)} rows in {dt:8.3f}s   {1000 * dt / max(1, len(df)):7.2f} ms/obs")
    finally:
        path = _Path(getattr(tb, "_cache_path", ""))
        tb.close()
        if str(path):
            shutil.rmtree(path, ignore_errors=True)


def _eod_days(n: int) -> list[datetime.date]:
    from Caching.curve_store import CurveStore
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import asset_for

    days = sorted(CurveStore.default().available_dates(asset_for(CURVE)))
    return days[-(n + 1) : -1]


def bench_eod(n: int = 200) -> None:
    """EOD history: per-point vs the batch branch."""
    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

    days = _eod_days(n)
    mdp = IRSwapsMDP(source="citivelo_excel_rl")
    mdp.get_data({"curve_name": CURVE, "timestamp": days[0]})

    t0 = time.perf_counter()
    for d in days:
        mdp.get_data({"curve_name": CURVE, "timestamp": d})
    dt = time.perf_counter() - t0
    print(f"[eod single    ]  {len(days)} days in {dt:8.3f}s   {1000 * dt / len(days):7.2f} ms/obs")

    t0 = time.perf_counter()
    out = mdp.bulk_get_data({"curve_name": CURVE, "timestamps": list(days)})
    dt = time.perf_counter() - t0
    print(f"[eod bulk      ]  {len(days)} days in {dt:8.3f}s   {1000 * dt / len(days):7.2f} ms/obs"
          f"   (got {len(out)})")


def bench_read_strategy(n: int = 60) -> None:
    """N single-day PyArrow reads vs one DuckDB range scan, for an EOD asset.

    Measured because the EOD batch could use either, and the repo's own comment
    on ``read_raw_nodes`` ("~5ms vs ~200ms for DuckDB Hive scan on a single
    partition") is about ONE day, which says nothing about a range.
    """
    from Caching.curve_store import CurveStore
    from MDP.IRSwaps.CITIVELO_EXCEL.warm import asset_for

    store = CurveStore.default()
    asset = asset_for(CURVE)
    days = _eod_days(n)

    t0 = time.perf_counter()
    rows = 0
    for d in days:
        rows += len(store.read_raw_day(asset, d))
    per_day = time.perf_counter() - t0
    print(f"[read_raw_day  ]  {len(days)} days in {per_day:8.3f}s "
          f"  {1000 * per_day / len(days):7.2f} ms/day  ({rows} rows)")

    t0 = time.perf_counter()
    df = store.read_raw_nodes(asset, start=days[0], end=days[-1])
    ranged = time.perf_counter() - t0
    print(f"[read_raw_nodes]  {len(days)} days in {ranged:8.3f}s "
          f"  {1000 * ranged / len(days):7.2f} ms/day  ({len(df)} rows)")


def bench_swaptions(n: int = 40) -> None:
    """The store-backed Citi swaption cube read (PR #400), never yet timed."""
    from Caching.swaption_cube_store import SwaptionCubeStore
    from MDP.IRSwaptions.CITIVELO.cube_store import (
        clear_stored_cube_cache,
        load_stored_cubes,
        store_asset,
        stored_coverage,
    )

    cov = stored_coverage("USD")
    print(f"[swaptions] coverage: {cov}")
    store = SwaptionCubeStore.default()
    asset = store_asset("USD")
    days = sorted(store.available_dates(asset))[-n:]
    if not days:
        print("[swaptions] nothing warmed; skipping")
        return

    clear_stored_cube_cache()
    t0 = time.perf_counter()
    got = load_stored_cubes("USD", days)
    cold = time.perf_counter() - t0
    print(f"[swaptions cold]  {len(got)}/{len(days)} days in {cold:8.3f}s "
          f"  {1000 * cold / len(days):7.2f} ms/day")

    t0 = time.perf_counter()
    load_stored_cubes("USD", days)
    warm = time.perf_counter() - t0
    print(f"[swaptions warm]  {len(days)} days in {warm:8.3f}s "
          f"  {1000 * warm / len(days):7.2f} ms/day")

    clear_stored_cube_cache()
    t0 = time.perf_counter()
    for d in days:
        store.read_day(asset, d)
    reads = time.perf_counter() - t0
    print(f"[swaptions read_day only]  {1000 * reads / len(days):7.2f} ms/day")


BENCHES = {
    "single": bench_single_point,
    "bulk": bench_bulk,
    "components": bench_components,
    "pricing": bench_pricing,
    "timeseries": bench_timeseries,
    "eod": bench_eod,
    "read_strategy": bench_read_strategy,
    "swaptions": bench_swaptions,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", default="components", choices=sorted(BENCHES) + ["all"])
    ap.add_argument("-n", type=int, default=200)
    ap.add_argument("--cprofile", action="store_true")
    args = ap.parse_args()

    names = sorted(BENCHES) if args.bench == "all" else [args.bench]

    for name in names:
        fn = BENCHES[name]
        if args.cprofile:
            pr = cProfile.Profile()
            pr.enable()
            fn(args.n)
            pr.disable()
            s = io.StringIO()
            pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(45)
            print(s.getvalue())
        else:
            fn(args.n)


if __name__ == "__main__":
    main()
