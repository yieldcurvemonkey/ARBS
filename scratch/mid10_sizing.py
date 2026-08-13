"""MEASUREMENT 4/5 -- day set, servable minutes per day, row counts, and the
bp cost of the spot-rule choice.

The backfill floor is not a matter of taste: a strict-policy request before the
minute store's first partition misses on EVERY minute, which snapshot.py's own
docstring says is indistinguishable from a cold store. So the day set is
(tape days) INTERSECT (store partitions), measured, not assumed.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
os.environ["ARBS_RL_OMIT_UNUSED_FIXINGS"] = "1"

import datetime
import pathlib
import sys
import warnings

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import numpy as np
import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

warnings.simplefilter("ignore")
pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 300)

conn = psycopg2.connect(resolve_pg_url())
tape = pd.read_sql(
    f"SELECT DISTINCT as_of_date FROM {LEGS_TABLE} ORDER BY 1", conn)
tape_days = [pd.Timestamp(d).date() for d in tape["as_of_date"]]
print(f"tape: {len(tape_days)} as_of days  {tape_days[0]} .. {tape_days[-1]}")
for lo in (datetime.date(2024, 3, 1), datetime.date(2024, 7, 1)):
    sub = [d for d in tape_days if d >= lo]
    print(f"  from {lo}: {len(sub)} days")

from Caching.curve_store import CurveStore
store = CurveStore.default()
parts = {}
for cname in ("USD-SOFR-1D-CITIVELOEXCELMIN", "USD-FEDFUNDS-1D-CITIVELOEXCELMIN"):
    ds = set(store.available_dates(cname))
    parts[cname] = ds
    print(f"\n{cname}: {len(ds)} partitions")
    for lo in (datetime.date(2024, 3, 1), datetime.date(2024, 7, 1)):
        sub = [d for d in tape_days if d >= lo]
        have = [d for d in sub if d in ds]
        missing = [d for d in sub if d not in ds]
        print(f"  tape days from {lo}: {len(sub)}, store has {len(have)}, "
              f"MISSING {len(missing)}")
        if missing:
            print(f"    first 20 missing: {[str(x) for x in missing[:20]]}")

both = parts["USD-SOFR-1D-CITIVELOEXCELMIN"] & parts["USD-FEDFUNDS-1D-CITIVELOEXCELMIN"]
for lo in (datetime.date(2024, 3, 1), datetime.date(2024, 7, 1)):
    sub = [d for d in tape_days if d >= lo and d in both]
    print(f"\nBOTH curves + tape, from {lo}: {len(sub)} days")

# ---- servable minutes per day, sampled across the whole span
target = [d for d in tape_days if d >= datetime.date(2024, 7, 1) and d in both]
idx = np.linspace(0, len(target) - 1, 40).astype(int)
rows = []
for i in sorted(set(idx)):
    d = target[i]
    n = {}
    for cname in parts:
        try:
            df = store.read_raw_day(cname, d)
            n[cname] = int(pd.to_datetime(df["timestamp_utc"], utc=True)
                           .dt.floor("min").nunique())
        except Exception as exc:
            n[cname] = -1
    rows.append({"day": d, "dow": d.strftime("%a"),
                 "sofr_min": n["USD-SOFR-1D-CITIVELOEXCELMIN"],
                 "ff_min": n["USD-FEDFUNDS-1D-CITIVELOEXCELMIN"]})
mm = pd.DataFrame(rows)
print(f"\nservable distinct minutes per day, {len(mm)} sampled days:")
print(mm.to_string())
print(f"\n  SOFR minutes/day: mean={mm['sofr_min'].mean():.0f} "
      f"median={mm['sofr_min'].median():.0f} min={mm['sofr_min'].min()} "
      f"max={mm['sofr_min'].max()}")
print(f"  FF   minutes/day: mean={mm['ff_min'].mean():.0f} "
      f"median={mm['ff_min'].median():.0f} min={mm['ff_min'].min()} "
      f"max={mm['ff_min'].max()}")

# ---- the spot-rule cost, in bp, everything else held fixed
print("\n" + "=" * 78)
print("SPOT-RULE COST: rule A (curve ref +2b, nyc) vs rule T (tape modal spot)")
print("=" * 78)
from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY

pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
CURVE = pricer.curve_for("SOFR")
TEN = ["1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "30Y"]
for DAY, spot_T_s in (("2026-04-01", "2026-04-03"),   # nyc calls 04-03 a holiday
                      ("2026-04-02", "2026-04-06"),
                      ("2026-03-30", "2026-04-01"),   # ordinary Monday, A==T
                      ("2025-04-16", "2025-04-21")):  # Good Friday 2025: A==T
    out = []
    for h in (3, 9, 14, 20):
        t = pd.Timestamp(f"{DAY} {h:02d}:30:00", tz=NY)
        try:
            m = pricer.mark_curve(CURVE, t)
        except Exception as exc:
            out.append({"h": h, "err": type(exc).__name__})
            continue
        ref = m.handle.reference_date()
        sA = m.handle.calendar_advance(ref, "2b")
        sT = pd.Timestamp(spot_T_s).to_pydatetime()
        r = {"h": h, "ref": ref.date(), "spotA": sA.date(), "spotT": sT.date()}
        for tn in TEN:
            a = pricer.price_leg(CURVE, t, sA, m.handle.calendar_advance(sA, tn),
                                 1e6).mid_pct
            b = pricer.price_leg(CURVE, t, sT, m.handle.calendar_advance(sT, tn),
                                 1e6).mid_pct
            r[tn] = round((a - b) * 100.0, 4)
        out.append(r)
    pricer.clear()
    print(f"\n{DAY}: (grid_A - grid_T) in bp")
    print(pd.DataFrame(out).to_string())

conn.close()
