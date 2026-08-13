"""How much of a day the slice scan actually covers, and where the seq run ends.

18,943 slice ids against 25,717 rows in the cumulative file is 73.7%. Either
the day has more than 1,333 slices or some rows never appear in one -- and the
answer decides whether the measured publication clock can be the primary
availability source or is always a partial overlay.
"""
from __future__ import annotations

import io
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")

import datetime

import pandas as pd
import requests

from SDRUtils.data.builder import DTCCFetcher
from SDRUtils.dealer_direction import lineage as lin

ROOT = r"C:/Users/chris/clee/ARBS-dd/scratch/dd_lineage_store"
DAY = datetime.date(2026, 6, 16)

pubs = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/slice_pub_0616_full.parquet")
raw = lin.load_raw_days([DAY], root=ROOT)
raw["_di"] = raw[lin.DI].map(lin.normalise_id)
have = set(pubs[lin.DI].map(lin.normalise_id))
print(f"cumulative day rows {len(raw):,}   slice-scanned ids {len(have):,}")
cov = raw["_di"].isin(have)
print(f"covered {int(cov.sum()):,} = {100 * cov.mean():.1f}%")
print("\ncoverage by action type:")
print(raw.assign(cov=cov).groupby("Action type")["cov"].agg(["size", "mean"]).round(3).to_string())

# where does the sequence run end?
f = DTCCFetcher()
sess = requests.Session()
print("\nprobing the tail of the sequence run:")
for seq in (1330, 1333, 1334, 1340, 1360, 1400, 1500):
    url, hdr = f._get_dtcc_url_and_header("CFTC", "RATES", f"2026_06_16_{seq}")
    r = sess.get(url, headers=hdr, timeout=60, stream=True)
    print(f"  seq {seq:>5}: HTTP {r.status_code} len={r.headers.get('content-length')}")
    r.close()

# and the head
print("\nprobing the head:")
for seq in (0, 1, 2):
    url, hdr = f._get_dtcc_url_and_header("CFTC", "RATES", f"2026_06_16_{seq}")
    r = sess.get(url, headers=hdr, timeout=60, stream=True)
    print(f"  seq {seq:>5}: HTTP {r.status_code} len={r.headers.get('content-length')}")
    r.close()

# what do the UNCOVERED rows look like -- are they late-day or a distinct class?
un = raw[~cov]
print(f"\nuncovered rows: {len(un):,}")
ev = pd.to_datetime(un[lin.EVENT_TS], utc=True, errors="coerce")
print("  their event timestamps, ET hour histogram:")
print(ev.dt.tz_convert("America/New_York").dt.hour.value_counts().sort_index().to_string())
