import os, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

print("pandas", pd.__version__)

# production window shape for a per-day run of D=2026-06-15..2026-06-18 (week)
start = datetime(2026, 6, 15, tzinfo=timezone.utc)
end_day = datetime(2026, 6, 18, tzinfo=timezone.utc)
end = end_day + timedelta(days=1)          # what load_usd_swaps gets
unfiltered_end = end + timedelta(days=1)   # what build_classification_dataframe uses for the RAW pass
print("start", start, "end", end, "unfiltered_end", unfiltered_end)

today_utc = datetime.now(timezone.utc).date()
hist_start = start.date()
hist_end = min(unfiltered_end.date(), today_utc - timedelta(days=1))
print("hist_start", hist_start, "hist_end", hist_end, "today_utc", today_utc)

bdays = list(pd.date_range(start=hist_start, end=hist_end,
                           freq=CustomBusinessDay(calendar=USFederalHolidayCalendar())).date)
print("business days in raw window:", bdays)

CACHE = Path(r"C:/Users/chris/clee/ARBS/sdr_cache")
for d in bdays:
    fp = CACHE / "CFTC" / "RATES" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d}.parquet"
    print(" ", d, "cached:", fp.exists())

# ---- direct read of cached day files (NO window filter) ----
print()
print("=== per-cached-file Execution Timestamp date spread ===")
for d in bdays:
    fp = CACHE / "CFTC" / "RATES" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d}.parquet"
    if not fp.exists():
        continue
    df = pd.read_parquet(fp, engine="pyarrow")
    ex = pd.to_datetime(df["Execution Timestamp"], utc=True, errors="coerce").dt.date
    ev = pd.to_datetime(df["Event timestamp"], utc=True, errors="coerce").dt.date
    vc = ex.value_counts().sort_index()
    print(f"file {d}: rows={len(df)} exec-date span {ex.min()}..{ex.max()} ndistinct={ex.nunique()}")
    print("   exec-date top:", dict(list(vc.items())[:6]), "..." if len(vc) > 6 else "")
    print("   event-date span", ev.min(), "..", ev.max(), "ndistinct", ev.nunique())
