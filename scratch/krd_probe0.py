import os, time, datetime
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
t0=time.perf_counter()
from Caching.curve_store import CurveStore
print("import CurveStore", time.perf_counter()-t0)
st = CurveStore.default()
print("base_dir", st.base_dir)
for name in ("USD-SOFR-1D-CITIVELOEXCELMIN","USD-FEDFUNDS-1D-CITIVELOEXCELMIN"):
    t0=time.perf_counter()
    ds = st.available_dates(name)
    print(name, "ndates", len(ds), "first", ds[0] if ds else None, "last", ds[-1] if ds else None, "%.3fs"%(time.perf_counter()-t0))
    jun = [d for d in ds if d.year==2026 and d.month==6]
    print("  2026-06 dates:", jun[:8], "...", len(jun))
