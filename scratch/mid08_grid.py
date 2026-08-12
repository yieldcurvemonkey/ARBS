"""MEASUREMENT 4/5 -- per-tenor cost, and the session window from the STORE.

Two things the aggregate 22-tenor number hides:

* per-tenor cost is not flat. An OIS float leg compounds daily, so a 40Y leg
  carries ~40x the daily rates of a 1Y one. If the long end dominates, the
  tenor set is a cost decision, not a taste one.
* the session window must come from what the store can actually SERVE under
  the strict policy, not from Citi's advertised hours. A minute with no
  snapshot is a hole in the chart either way.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
os.environ["ARBS_RL_OMIT_UNUSED_FIXINGS"] = "1"

import datetime
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
pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 300)

from Query.IRSwaps.backends.rateslib.RLIRSwapCurve import omit_unused_fixings
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY

print(f"omit_unused_fixings={omit_unused_fixings()}")

TENORS = ["1W", "2W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y", "18M",
          "2Y", "3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y",
          "20Y", "25Y", "30Y", "40Y"]
DAY = "2026-04-01"

pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
CURVE = pricer.curve_for("SOFR")
t0 = pd.Timestamp(f"{DAY} 09:00:00", tz=NY)
m = pricer.mark_curve(CURVE, t0)
spot = m.handle.calendar_advance(m.handle.reference_date(), "2b")
mats = {tn: m.handle.calendar_advance(spot, tn) for tn in TENORS}

print(f"\n--- per-tenor price_leg cost, warm curve, n=15 each  "
      f"(ref={m.handle.reference_date().date()} spot={spot.date()})")
rows = []
for tn in TENORS:
    ts = []
    for _ in range(15):
        t = time.perf_counter()
        lp = pricer.price_leg(CURVE, t0, spot, mats[tn], 1_000_000.0)
        ts.append((time.perf_counter() - t) * 1000.0)
    rows.append({"tenor": tn, "mat": mats[tn].date(),
                 "ms": round(statistics.median(ts), 2),
                 "rate_pct": round(lp.mid_pct, 6)})
per = pd.DataFrame(rows)
per["cum_ms"] = per["ms"].cumsum()
print(per.to_string())
print(f"\nTOTAL all {len(TENORS)} tenors = {per['ms'].sum():.1f} ms")
for cut in ("30Y", "20Y", "15Y"):
    sub = per[per.index <= per.index[per["tenor"] == cut][0]]
    print(f"  set truncated at {cut:>3} ({len(sub):2d} tenors) = "
          f"{sub['ms'].sum():6.1f} ms")

# ------------------------------------------------------------------ session
print("\n" + "=" * 78)
print("SESSION WINDOW -- minutes the STORE can serve, from its own partitions")
from Caching.curve_store import CurveStore

store = CurveStore.default()
print("store base_dir:", store.base_dir)
for cname in ("USD-SOFR-1D-CITIVELOEXCELMIN", "USD-FEDFUNDS-1D-CITIVELOEXCELMIN"):
    dates = store.available_dates(cname)
    print(f"\n{cname}: {len(dates)} partitions "
          f"{min(dates)} .. {max(dates)}")
    frames = []
    sample = [datetime.date(2026, 4, 1), datetime.date(2026, 4, 2),
              datetime.date(2025, 10, 15), datetime.date(2024, 12, 4),
              datetime.date(2026, 3, 30), datetime.date(2026, 6, 5)]
    for d in sample:
        if d not in dates:
            print(f"  {d}: MISSING partition")
            continue
        df = store.read_raw_day(cname, d)
        ts = pd.to_datetime(df["timestamp_utc"], utc=True).dt.tz_convert(NY)
        h = ts.dt.hour.value_counts().sort_index()
        frames.append(h.rename(str(d)))
        print(f"  {d} ({d.strftime('%a')}): {len(df)} rows, "
              f"{ts.dt.floor('min').nunique()} distinct minutes, "
              f"{ts.min()} .. {ts.max()}")
    if frames:
        print("\n  minutes per ET hour:")
        print(pd.concat(frames, axis=1).fillna(0).astype(int).to_string())
