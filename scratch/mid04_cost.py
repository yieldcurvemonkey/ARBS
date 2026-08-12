"""MEASUREMENT 2+3 -- what one grid point costs, and how a par rate is got.

Single process, no pool: the box already carries a 527-day publish plus two of
the user's jobs, so a parallel probe would measure contention, not cost.

Run TWICE, as two separate invocations:
    python scratch/mid04_cost.py            # fixings shortcut OFF (default)
    MID04_OMIT=1 python scratch/mid04_cost.py
`omit_unused_fixings()` caches the env read on first call, so the flag has to
be set before the first curve is built -- which a second process guarantees and
a second function call inside one process does not.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
if os.getenv("MID04_OMIT") == "1":
    os.environ["ARBS_RL_OMIT_UNUSED_FIXINGS"] = "1"
else:
    os.environ.pop("ARBS_RL_OMIT_UNUSED_FIXINGS", None)

import pathlib
import statistics
import sys
import time
import warnings

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pandas as pd

warnings.simplefilter("ignore")

DAY = os.getenv("MID04_DAY", "2026-04-01")
N_COLD = int(os.getenv("MID04_NCOLD", "20"))

SOFR_TENORS = ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "4Y",
               "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y",
               "25Y", "30Y", "40Y"]
FF_TENORS = ["1M", "2M", "3M", "6M", "9M", "1Y", "18M", "2Y", "3Y", "5Y", "10Y"]

t_imp0 = time.perf_counter()
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY
from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import omit_unused_fixings
t_imp = time.perf_counter() - t_imp0

print("=" * 78)
print(f"day={DAY}  omit_unused_fixings={omit_unused_fixings()}  "
      f"import={t_imp:.2f}s")
print("=" * 78)

pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
CURVES = {k: pricer.curve_for(k) for k in ("SOFR", "FED_FUNDS")}
print(f"curves: {CURVES}")


def inst(hh, mm):
    return pd.Timestamp(f"{DAY} {hh:02d}:{mm:02d}:00", tz=NY)


def bench(fn, n):
    ts = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        ts.append((time.perf_counter() - t) * 1000.0)
    return ts


def show(label, ts):
    if not ts:
        print(f"  {label:<44} n=0")
        return
    print(f"  {label:<44} n={len(ts):>3}  "
          f"median={statistics.median(ts):8.1f} ms  "
          f"mean={statistics.mean(ts):8.1f}  "
          f"min={min(ts):8.1f}  max={max(ts):8.1f}")


results = {}

for index, curve in CURVES.items():
    tenors = SOFR_TENORS if index == "SOFR" else FF_TENORS
    print(f"\n---------------- {index}  ({curve}) ----------------")
    pricer.clear()

    # (a) first curve build in this process -- carries lazy imports + store open
    t = time.perf_counter()
    m0 = pricer.mark_curve(curve, inst(9, 0))
    first_ms = (time.perf_counter() - t) * 1000.0
    print(f"  first build (incl. lazy import/store open) = {first_ms:.1f} ms   "
          f"policy={m0.policy} lag={m0.lag_seconds}s")

    ref = m0.handle.reference_date()
    spot = m0.handle.calendar_advance(ref, "2b")
    print(f"  reference_date={ref.date()}  spot(2b)={spot.date()}  "
          f"instant ET date={inst(9,0).date()}")

    # (a2) steady-state COLD minutes -- a fresh minute each time
    cold = bench(lambda i: pricer.mark_curve(curve, inst(9, 1 + i)), N_COLD)
    show("(a) mark_curve, cold minute", cold)

    # (b) already-cached minute
    warm = bench(lambda i: pricer.mark_curve(curve, inst(9, 1 + (i % N_COLD))),
                 3 * N_COLD)
    show("(b) mark_curve, cached minute", warm)

    # (c)/(d) price_leg off an ALREADY MARKED curve
    mats = {tn: m0.handle.calendar_advance(spot, tn) for tn in tenors}
    one = bench(lambda i: pricer.price_leg(curve, inst(9, 0), spot,
                                           mats["10Y"], 1_000_000.0), 30)
    show("(c) price_leg, ONE tenor (10Y), warm curve", one)

    def all_tenors(_):
        for tn in tenors:
            pricer.price_leg(curve, inst(9, 0), spot, mats[tn], 1_000_000.0)

    many = bench(all_tenors, 5)
    show(f"(d) price_leg x{len(tenors)} tenors, warm curve", many)
    per = [x / len(tenors) for x in many]
    show("    -> per tenor", per)

    # the rates themselves, so the numbers are visible not just the timings
    print(f"\n  par rates at {inst(9,0)}  (spot {spot.date()}):")
    for tn in tenors:
        lp = pricer.price_leg(curve, inst(9, 0), spot, mats[tn], 1_000_000.0)
        print(f"    {tn:>4}  mat={mats[tn].date()}  rate={lp.mid_pct:9.6f} %  "
              f"pv01={lp.pv01:12.2f}")

    results[index] = {
        "first_ms": first_ms,
        "cold_med": statistics.median(cold),
        "warm_med": statistics.median(warm),
        "one_med": statistics.median(one),
        "many_med": statistics.median(many),
        "per_tenor": statistics.median(per),
        "n_tenors": len(tenors),
    }

print("\n" + "=" * 78)
print("SUMMARY (ms)")
for k, v in results.items():
    print(f"  {k:<10} cold_build={v['cold_med']:7.1f}  cached={v['warm_med']:7.3f}  "
          f"1 tenor={v['one_med']:6.1f}  {v['n_tenors']} tenors={v['many_med']:7.1f}"
          f"  per-tenor={v['per_tenor']:5.1f}")
    tot = v["cold_med"] + v["many_med"]
    print(f"             one grid point (build + {v['n_tenors']} tenors) "
          f"= {tot:7.1f} ms   build share = {100*v['cold_med']/tot:4.1f}%")
