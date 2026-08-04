import datetime
import sys

sys.path.insert(0, r"C:\Users\chris\clee\ARBS-xm")
from BT.serff.futures_data import backfill_settles

syms = [f"SR3{c}{y % 100:02d}" for y in range(2026, 2029) for c in "HMUZ"]
out = backfill_settles(datetime.date(2024, 1, 1), datetime.date(2026, 8, 1),
                       symbols=syms, show_progress=True)
for s in syms:
    df = out.get(s)
    print(s, "MISSING" if df is None or df.empty else
          f"{len(df)} rows to {df.index.max().date()}", flush=True)
