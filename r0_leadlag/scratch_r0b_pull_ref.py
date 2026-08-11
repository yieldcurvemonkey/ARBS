"""R0b — pull the Citi minute-curve par-rate reference, one tenor per argument.

Same machinery as D1's scratch_d1_fullwin.py (chunked by month, one tenor at a time so a
kill loses at most one tenor, skips anything already cached). Two changes, both forced by
the environment and both recorded in r0b_deviations.md R0b-4 / R0b-10:

  * writes to D:\\r0b_cache\\ref  (C: was at 1 MB an hour before R0b started)
  * ts_base_dir is D:\\r0b_cache\\ts for the same reason

The twelve tenors D1 already pulled are read from D:\\r0_cache_moved\\cache_d1_ref and are
not re-pulled.

    python scratch_r0b_pull_ref.py 4y 15y 9y
"""
import gc
import os
import sys
import time

os.environ["ARBS_SUPABASE_ENABLED"] = "0"
os.environ.setdefault("ARBS_RL_OMIT_UNUSED_FIXINGS", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import pandas as pd  # noqa: E402
from Query.IRSwaps.IRSwapQuery import IRSwapQuery, IRSwapValue  # noqa: E402
from TB.IRSwapsTB import IRSwapsTB  # noqa: E402
from MDP.IRSwaps.IRSwapsMDP import IRSwapsMDP  # noqa: E402

REFDIR = r"D:\r0b_cache\ref"
D1DIR = r"D:\r0_cache_moved\cache_d1_ref"
TSDIR = r"D:\r0b_cache\ts"
PARTDIR = r"D:\r0b_cache\ref_parts"
os.makedirs(REFDIR, exist_ok=True)
os.makedirs(TSDIR, exist_ok=True)
os.makedirs(PARTDIR, exist_ok=True)

START = pd.Timestamp("2026-04-30 23:00", tz="UTC")
END = pd.Timestamp("2026-08-07 22:00", tz="UTC")

tb = IRSwapsTB(IRSwapsMDP(source="citivelo_excel_rl"), show_tqdm=False,
               use_ts_cache=True, use_duckdb=False, ts_base_dir=TSDIR)

for tn in sys.argv[1:]:
    cp = os.path.join(REFDIR, f"ref_{tn}.parquet")
    if os.path.exists(cp) or os.path.exists(os.path.join(D1DIR, f"ref_{tn}.parquet")):
        print(f"{tn:5s} cached", flush=True)
        continue
    t = time.time()
    edges = pd.date_range(START.floor("D"), END.ceil("D"), freq="MS", tz="UTC")
    edges = pd.DatetimeIndex([START]).append(edges).append(pd.DatetimeIndex([END]))
    edges = edges.sort_values().unique()
    parts = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        # chunk-level resume: a 10-minute foreground cap kills the slowest tenors
        # mid-pull, so each month is banked as its own part file.
        part = os.path.join(PARTDIR, f"ref_{tn}__{a.date()}_{b.date()}.parquet")
        if os.path.exists(part):
            parts.append(pd.read_parquet(part))
            print(f"  {tn:5s} {a.date()}..{b.date()} {len(parts[-1]):6,}  (part cached)",
                  flush=True)
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
        p = pd.DataFrame({"tenor_lc": tn, "ref_min": ix.floor("min"),
                          "ref_rate": ss.to_numpy(float)})
        p.to_parquet(part, index=False)
        parts.append(p)
        del ts, ss
        gc.collect()
        print(f"  {tn:5s} {a.date()}..{b.date()} {len(parts[-1]):6,}  "
              f"({time.time()-t:5.0f}s)", flush=True)
    if not parts:
        print(f"{tn:5s} NO DATA — excluded from the reference set (R0b-4)", flush=True)
        continue
    out = pd.concat(parts, ignore_index=True).drop_duplicates(["tenor_lc", "ref_min"])
    out.to_parquet(cp, index=False)
    print(f"{tn:5s} {len(out):7,} minutes in {time.time()-t:6.1f}s -> {cp}", flush=True)
print("PULL_BLOCK_DONE", flush=True)
