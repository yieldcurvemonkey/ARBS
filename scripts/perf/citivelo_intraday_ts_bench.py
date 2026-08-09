r"""Reproduce the three measurements ``citivelo_intraday_ts_warm`` is built on.

Run::

    <env>/python.exe scripts/perf/citivelo_intraday_ts_bench.py [--date 2026-07-29]

Everything is served from the warmed local CurveStore. No Excel, no network.

The warm's shape is not a preference, it is these numbers. Each is printed with
what it decided, so a later reader can see the claim and the evidence together
rather than trusting a docstring:

1. **Acquisition is already solved** - if ``bulk_get_data`` were slow, the answer
   would be a curve-side fix, not a pricing-side one. Measured 1.6 ms/curve.
2. **``omit_unused_fixings`` is worth 8.7x for 1.8e-15 bp** - and the delta is
   printed, because a speedup that changes numbers has to be quoted with the
   change.
3. **Threads do not scale** - the loop is GIL-bound, so the warm parallelises
   over DAYS in processes. Measuring this is what stopped ``n_jobs=8`` being the
   obvious answer; it is 40% SLOWER than one worker.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time
import zoneinfo
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

ET = zoneinfo.ZoneInfo("America/New_York")
CURVE = "USD-SOFR-1D"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--date", default="2026-07-29")
    parser.add_argument("--points", type=int, default=240)
    args = parser.parse_args(argv)

    from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP
    from Query.IRSwaps.IRSwapQuery import IRSwapQuery
    from Query.IRSwaps.IRSwapValue import IRSwapValue
    from Query.IRSwaps.backends.rateslib import RLIRSwapCurve as rl_mod
    from TB.IRSwapsTB import _build_row_for_query

    day = datetime.date.fromisoformat(args.date)
    stamps = [
        datetime.datetime.combine(day, datetime.time(9, 0), tzinfo=ET)
        + datetime.timedelta(minutes=i)
        for i in range(int(args.points))
    ]
    mdp = IRSwapsMDP(source="citivelo_excel_rl")

    # --- 1. acquisition -----------------------------------------------------
    t0 = time.perf_counter()
    curves = mdp.bulk_get_data({"curve_name": CURVE, "timestamps": stamps, "n_jobs": 1})
    acq = time.perf_counter() - t0
    if not curves:
        print(f"no warmed minute curves for {day}; pick a --date the CurveStore holds")
        return 2
    items = sorted(curves.items(), key=lambda kv: kv[0])
    print(f"[1] bulk_get_data      {acq:7.3f}s for {len(items)} curves "
          f"({1000 * acq / len(items):.2f} ms/curve)  -> acquisition is not the bottleneck")

    # --- 2. the fixings shortcut -------------------------------------------
    q10 = IRSwapQuery(curve=CURVE, tenor="10y", value=IRSwapValue.RATE)

    def _run_all(query) -> tuple[float, list[float]]:
        started = time.perf_counter()
        values = [_build_row_for_query(c, query, s, "Date")[2] for s, c in items]
        return time.perf_counter() - started, values

    rl_mod.set_omit_unused_fixings(False)
    off, base = _run_all(q10)
    rl_mod.set_omit_unused_fixings(True)
    on, fast = _run_all(q10)
    worst = max(abs(a - b) for a, b in zip(base, fast))
    print(f"[2] omit_unused_fixings OFF {off:6.3f}s  ON {on:6.3f}s  "
          f"speedup {off / max(on, 1e-9):5.1f}x   max |delta| {worst:.3e} bp")

    # --- 3. per-tenor cost, with the shortcut on ---------------------------
    print("[3] cost per point (omit_unused_fixings ON):")
    for tenor in ("1y", "2y", "5y", "10y", "20y", "30y", "5yx5y", "10yx10y",
                  "5y/10y", "5y/10y/30y"):
        query = IRSwapQuery(curve=CURVE, tenor=tenor, value=IRSwapValue.RATE)
        elapsed, _ = _run_all(query)
        print(f"      {tenor:<14} {1000 * elapsed / len(items):7.2f} ms/pt")

    # --- 4. thread scaling --------------------------------------------------
    tenors = ["1y", "2y", "5y", "10y", "30y", "5yx5y"]
    queries = [IRSwapQuery(curve=CURVE, tenor=t, value=IRSwapValue.RATE) for t in tenors]
    tasks = [(s, q, c) for s, c in items for q in queries]

    def _chunk(chunk):
        return [_build_row_for_query(c, q, s, "Date") for s, q, c in chunk]

    print(f"[4] thread scaling over {len(tasks)} pricings:")
    for workers in (1, 2, 4, 8, 12):
        size = max(1, len(tasks) // (workers * 4))
        chunks = [tasks[i: i + size] for i in range(0, len(tasks), size)]
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_chunk, chunks))
        elapsed = time.perf_counter() - started
        print(f"      workers={workers:<3} {elapsed:7.3f}s  {len(tasks) / elapsed:8.0f} pricings/s")
    print("      -> GIL-bound. Parallelise over DAYS in processes, not queries in threads.")

    rl_mod.set_omit_unused_fixings(None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
