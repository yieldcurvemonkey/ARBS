"""Time a FULL-window pull per tenor, writing the per-tenor cache run_d1.py reads.

Run tenor-by-tenor from the command line so the cost is visible and bounded, and so a
kill loses at most one tenor. Skips anything already cached.
"""
import os, sys, time, gc
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
os.environ.setdefault("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pandas as pd
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapValue
from TB.IRSwapsTB import IRSwapsTB
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP

REFDIR = os.path.join(HERE, "cache_d1_ref")
os.makedirs(REFDIR, exist_ok=True)
START = pd.Timestamp("2026-04-30 23:00", tz="UTC")
END = pd.Timestamp("2026-08-07 22:00", tz="UTC")

tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False,
               use_ts_cache=True, use_duckdb=False,
               ts_base_dir=os.path.join(os.path.dirname(HERE), "data", "ts"))

for tn in sys.argv[1:]:
    cp = os.path.join(REFDIR, f"ref_{tn}.parquet")
    if os.path.exists(cp):
        print(f"{tn:5s} cached", flush=True)
        continue
    t = time.time()
    # chunked by month: an unchunked 30y pull reached 6.8 GB resident and thrashed
    edges = pd.date_range(START.floor("D"), END.ceil("D"), freq="MS", tz="UTC")
    edges = pd.DatetimeIndex([START]).append(edges).append(pd.DatetimeIndex([END]))
    edges = edges.sort_values().unique()
    parts = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        ts = tb.get_timeseries(start=pd.Timestamp(a).to_pydatetime(),
                               end=pd.Timestamp(b).to_pydatetime(),
                               queries=[IRSwapQuery(curve="USD-SOFR-1D", tenor=tn,
                                                    value=IRSwapValue.RATE)], freq="1min")
        if ts is None or len(ts) == 0:
            continue
        ss = ts.iloc[:, 0].dropna()
        ix = pd.to_datetime(ss.index)
        ix = ix.tz_localize("UTC") if ix.tz is None else ix.tz_convert("UTC")
        parts.append(pd.DataFrame({"tenor_lc": tn, "ref_min": ix.floor("min"),
                                   "ref_rate": ss.to_numpy(float)}))
        del ts, ss
        gc.collect()
        print(f"  {tn:5s} {a.date()}..{b.date()} {len(parts[-1]):6,}  ({time.time()-t:5.0f}s)", flush=True)
    out = pd.concat(parts, ignore_index=True).drop_duplicates(["tenor_lc", "ref_min"])
    out.to_parquet(cp, index=False)
    print(f"{tn:5s} {len(out):7,} minutes in {time.time()-t:6.1f}s", flush=True)
