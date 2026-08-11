import os, time, datetime
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
import pandas as pd, numpy as np
from Caching.curve_store import CurveStore
st = CurveStore.default()
NAME = "USD-SOFR-1D-CITIVELOEXCELMIN"
day = datetime.date(2026, 6, 15)
t0 = time.perf_counter()
df = st.read_raw_nodes(NAME, start=day, end=day)
t_read = time.perf_counter() - t0
print("read_raw_nodes %.4fs rows=%d" % (t_read, len(df)))
print("columns:", list(df.columns))
if len(df):
    r = df.iloc[len(df)//2].to_dict()
    print("ts_utc", r.get("timestamp_utc"), "ref", r.get("reference_key"), "interp", r.get("interpolation"))
    nd = r["node_dates"]; dfs = r["discount_factors"]
    print("n_nodes", len(nd), "first", nd[0], "last", nd[-1])
    print("spline_knots", r.get("spline_knots"))
    print("node dates sample:", [str(x) for x in list(nd)[:8]], "...", [str(x) for x in list(nd)[-4:]])
    print("timestamps head:", [str(x) for x in df["timestamp_utc"].head(3)], "tail:", [str(x) for x in df["timestamp_utc"].tail(2)])
