"""Warm the GC fixing cache over EVERY panel date, once, offline.

Why this is the fix rather than a nicety
----------------------------------------
``engine._gc_series`` persists what it has fetched to ``gc_fixings.parquet`` and fetches
only the dates it is missing. It was first warmed over TLT's gated universe -- 2,528
dates in the 20-30y band. The notebook's fund sweep then asks for GOVT, SHY, IEI and IEF,
whose universes span dates TLT's did not, and every one of those becomes a live
``load_us_treasury_gc_fixing_pct`` call with retries, inside a notebook cell, one date at
a time.

The symptom was a kernel that started at 100% CPU and then made ~25 CPU-seconds of
progress per hour with ~100 threads and open sockets -- which reads exactly like a hang
and is really a few hundred serialised network round trips.
"""
import os, sys, time
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-etf")

import pandas as pd
from RVUtils.ETFRebalance import bond_panel as BP, engine as EN

panel = BP.load()
dates = sorted(pd.to_datetime(panel["date"].unique()))
print(f"panel dates: {len(dates):,}  {dates[0].date()} .. {dates[-1].date()}", flush=True)

path = BP.panel_dir() / "gc_fixings.parquet"
if path.exists():
    have = pd.read_parquet(path)
    print(f"cached before: {len(have):,} dates", flush=True)

t0 = time.time()
s = EN._gc_series(dates)
print(f"_gc_series over the full panel: {time.time()-t0:.1f}s", flush=True)
print(f"  n={len(s):,}  nan={int(s.isna().sum())}  "
      f"range {s.min():.4f}..{s.max():.4f}", flush=True)

after = pd.read_parquet(path)
print(f"cached after: {len(after):,} dates -> {path}", flush=True)
