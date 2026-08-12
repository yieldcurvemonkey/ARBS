"""Does the new ET-date filter in `_day_minutes` drop any real minute?

A guard that silently removes data is worse than the hazard it closes, so it is
measured before it is trusted: for each sampled partition, how many distinct
minutes it holds and how many of those fall on a DIFFERENT ET calendar date.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
import datetime, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pandas as pd
import pytz
from Caching.curve_store import CurveStore

NY = pytz.timezone("America/New_York")
store = CurveStore.default()

DAYS = ["2024-06-30", "2024-07-01", "2024-07-04", "2024-08-07", "2025-04-06",
        "2025-04-07", "2025-10-14", "2025-10-15", "2026-03-31", "2026-04-01",
        "2026-06-16", "2026-06-17", "2026-08-07"]

total_held = total_out = 0
for ds in DAYS:
    d = datetime.date.fromisoformat(ds)
    for curve in ("USD-SOFR-1D", "USD-FEDFUNDS-1D"):
        raw = store.read_raw_day(f"{curve}-CITIVELOEXCELMIN", d)
        if raw is None or len(raw) == 0:
            print(f"{ds} {curve:<16} EMPTY")
            continue
        ts = (pd.to_datetime(raw["timestamp_utc"], utc=True)
              .dt.floor("min").dt.tz_convert(NY))
        uniq = pd.Series(sorted(set(ts)))
        out = uniq[uniq.dt.date != d]
        total_held += len(uniq)
        total_out += len(out)
        flag = "  <-- DROPPED" if len(out) else ""
        print(f"{ds} {curve:<16} {len(uniq):>5} minutes, "
              f"{len(out):>3} off-date{flag}  "
              f"[{uniq.iloc[0]:%H:%M} .. {uniq.iloc[-1]:%H:%M} ET]")
        for t in out[:5]:
            print(f"      off-date stamp: {t}")

print(f"\nTOTAL: {total_held:,} distinct minutes across the sample, "
      f"{total_out} of them off-date "
      f"({100.0 * total_out / max(total_held, 1):.4f}%)")
print("The filter is a no-op on real data." if total_out == 0
      else "THE FILTER DROPS REAL MINUTES -- do not ship it as written.")
