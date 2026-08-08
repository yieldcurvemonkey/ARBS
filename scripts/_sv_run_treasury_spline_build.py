"""One-off driver: build the full Treasury-spline cache for Task 16's H2
regression window (2021-01-04..2026-08-03, the UMEP-usable window
established in Task 15). Long-running (multi-hour) -- run in the background
and poll; progress checkpoints to notebooks/data/strikeless_vol/ust_splines.pkl
every 50 dates so a killed run loses at most 50 dates of work.
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import datetime as dt
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.sv_treasury_splines import spline_map

START = dt.date(2021, 1, 4)
END = dt.date(2026, 8, 3)

if __name__ == "__main__":
    dates = pd.bdate_range(START, END).date.tolist()
    print(f"Building Treasury splines for {START}..{END} ({len(dates)} business days requested)", flush=True)
    t0 = time.time()
    smap = spline_map(dates, show_progress=True, checkpoint_every=50)
    elapsed = time.time() - t0
    n_ok = sum(1 for s in smap.values() if s is not None)
    n_none = sum(1 for s in smap.values() if s is None)
    print(f"DONE in {elapsed:.1f}s ({elapsed/60:.1f} min). {n_ok} built, {n_none} None (holidays/gaps).", flush=True)
