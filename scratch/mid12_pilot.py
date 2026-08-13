"""GAP 2 -- the scaling pilot. Production tenor sets, both indices, real
parquet write, 1 worker vs 2 workers on comparable days.

Constraint: this box already carries a 527-day publish plus two of the user's
own multi-worker jobs, so 2 workers is the ceiling and four days is the whole
pilot. The 8-worker projection is then an extrapolation from a MEASURED
1->2 efficiency, not a guess.

The grid instants are the STORE'S OWN minute stamps for the day, per curve.
A generated date_range would waste strict misses on truncated sessions, get
DST days wrong, and make the completion check ("rows == servable minutes")
impossible to state.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
os.environ["ARBS_RL_OMIT_UNUSED_FIXINGS"] = "1"

import concurrent.futures as cf
import pathlib
import sys
import time
import warnings

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pandas as pd

warnings.simplefilter("ignore")

CACHE = pathlib.Path(os.getenv("MIDGRID_CACHE", r"D:\midgrid_pilot"))

CURVE_MIN = {"SOFR": "USD-SOFR-1D-CITIVELOEXCELMIN",
             "FED_FUNDS": "USD-FEDFUNDS-1D-CITIVELOEXCELMIN"}

TENORS = {
    "SOFR": ["1M", "2M", "3M", "4M", "5M", "6M", "7M", "8M", "9M", "10M",
             "11M", "1Y", "15M", "18M", "21M", "2Y", "3Y", "4Y", "5Y", "6Y",
             "7Y", "8Y", "9Y", "10Y", "11Y", "12Y", "15Y", "20Y", "25Y", "30Y"],
    "FED_FUNDS": ["1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "15M", "18M",
                  "21M", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y"],
}

_ENG = None


def _engines():
    """One pricer + one store per worker process, built on first use."""
    global _ENG
    if _ENG is None:
        from Caching.curve_store import CurveStore
        from SDRUtils.dealer_direction import midprice, snapshot
        _ENG = (midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE),
                CurveStore.default())
    return _ENG


def price_day(day: str) -> dict:
    """Every servable minute of one ET calendar day, both indices."""
    t0 = time.perf_counter()
    try:
        import pytz
        NY = pytz.timezone("America/New_York")
        pricer, store = _engines()
        d = pd.Timestamp(day).date()
        rows = []
        stats = {}
        with pricer.day_scope():
            for index, minname in CURVE_MIN.items():
                curve = pricer.curve_for(index)
                raw = store.read_raw_day(minname, d)
                mins = sorted(pd.to_datetime(raw["timestamp_utc"], utc=True)
                              .dt.floor("min").dt.tz_convert(NY).unique())
                served = miss = 0
                spot = mats = None
                for t in mins:
                    t = pd.Timestamp(t)
                    try:
                        m = pricer.mark_curve(curve, t)
                    except Exception:
                        miss += 1
                        continue
                    if spot is None:
                        ref = m.handle.reference_date()
                        spot = m.handle.calendar_advance(ref, "2b")
                        mats = {tn: m.handle.calendar_advance(spot, tn)
                                for tn in TENORS[index]}
                    served += 1
                    for tn in TENORS[index]:
                        lp = pricer.price_leg(curve, t, spot, mats[tn], 1e6)
                        rows.append((index, tn, t, spot, mats[tn],
                                     lp.mid_pct, lp.pv01,
                                     m.lag_seconds, m.policy))
                stats[index] = {"minutes": len(mins), "served": served,
                                "miss": miss}
        df = pd.DataFrame(rows, columns=[
            "rate_index", "tenor_label", "ts", "effective_date",
            "maturity_date", "mid_pct", "pv01", "snapshot_lag_seconds",
            "snapshot_policy"])
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = CACHE / f"{day}.tmp.parquet"
        df.to_parquet(tmp, index=False)
        os.replace(tmp, CACHE / f"{day}.parquet")
        return {"day": day, "rows": len(df), "seconds": time.perf_counter() - t0,
                "handles_peak": pricer.n_handles, **stats}
    except Exception as exc:
        import traceback
        return {"day": day, "error": f"{type(exc).__name__}: {exc}",
                "tb": traceback.format_exc()[-800:],
                "seconds": time.perf_counter() - t0}


SERIAL = ["2025-10-15", "2026-01-26"]
PARALLEL = ["2025-11-04", "2026-02-12"]

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"

    if mode in ("both", "serial"):
        t = time.perf_counter()
        out = [price_day(d) for d in SERIAL]
        wall1 = time.perf_counter() - t
        print(f"--- SERIAL (1 process), {SERIAL}")
        for r in out:
            print("   ", r)
        print(f"    wall = {wall1:.1f}s")

    if mode in ("both", "parallel"):
        t = time.perf_counter()
        with cf.ProcessPoolExecutor(max_workers=2) as pool:
            out2 = list(pool.map(price_day, PARALLEL))
        wall2 = time.perf_counter() - t
        print(f"\n--- 2 WORKERS, {PARALLEL}")
        for r in out2:
            print("   ", r)
        print(f"    wall = {wall2:.1f}s")

    if mode == "both":
        cpu1 = sum(r["seconds"] for r in out)
        cpu2 = sum(r["seconds"] for r in out2)
        print(f"\n--- SCALING")
        print(f"    serial:   {cpu1:.1f}s CPU / {wall1:.1f}s wall")
        print(f"    2 worker: {cpu2:.1f}s CPU / {wall2:.1f}s wall  "
              f"-> speedup {cpu2/wall2:.2f}x, per-day CPU inflation "
              f"{(cpu2/len(PARALLEL))/(cpu1/len(SERIAL)):.2f}x")
        rows = sum(r.get("rows", 0) for r in out + out2)
        mins = sum(r["SOFR"]["served"] + r["FED_FUNDS"]["served"]
                   for r in out + out2 if "SOFR" in r)
        print(f"    {rows} rows over {mins} served curve-minutes; "
              f"per-day rows ~{rows/4:.0f}")
