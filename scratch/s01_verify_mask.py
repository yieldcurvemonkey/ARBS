"""GATE: confirm the Execution-Timestamp mask really loses 40.7% of terminations,
on a FRESH day, including the ignore_cache=True half that was code-verified only.

Known-answer first: re-fetch 2026_06_16 through the direct path and tie the row
count out against the parquet the earlier probe saved. A fetcher that is itself
wrong would report a plausible loss rate and hide the thing it is measuring.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")

import httpx
import pandas as pd

from SDRUtils.data.builder import DTCCFetcher, SDRDataBuilder

pd.set_option("display.width", 220)

DI = "Dissemination Identifier"
ODI = "Original Dissemination Identifier"
SCRATCH_CACHE = r"C:/Users/chris/clee/ARBS-dd/scratch/_verify_cache"   # NOT the prod sdr_cache
FRESH = sys.argv[1] if len(sys.argv) > 1 else "2026-08-06"


def direct(date_string: str) -> pd.DataFrame:
    """The unfiltered zip, straight from DTCC (p3's path)."""
    async def run():
        f = DTCCFetcher(error_verbose=True)
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
        async with httpx.AsyncClient(limits=limits, timeout=180, verify=False, http2=True) as client:
            buf = await f._fetch_dtcc_sdr_data_helper(
                client=client, date_string=date_string, agency="CFTC",
                asset_class="RATES", max_retries=3, backoff_factor=2,
            )
            if buf is None:
                return pd.DataFrame()
            dfs = f._extract_dataframes_from_zip(buf, convert_key_into_dt=False,
                                                 parallelize=False, use_pyarrow=True)
            return next(iter(dfs.values())) if dfs else pd.DataFrame()
    return asyncio.run(run())


# ---------- known answer ----------
print("=== KNOWN ANSWER: direct fetch of 2026_06_16 vs the saved unfiltered parquet ===")
saved = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_zip/2026_06_16_UNFILTERED.parquet")
again = direct("2026_06_16")
print(f"  saved rows {len(saved)}   refetched rows {len(again)}   match={len(saved) == len(again)}")
print(f"  saved TERM {int((saved['Action type'] == 'TERM').sum())}   "
      f"refetched TERM {int((again['Action type'] == 'TERM').sum())}")
assert len(again) > 0, "direct fetcher returned nothing - measurement tool is broken"

# ---------- fresh day, unfiltered ----------
ds = FRESH.replace("-", "_")
print(f"\n=== FRESH DAY {FRESH}: unfiltered zip ===")
raw = direct(ds)
raw["_ex"] = pd.to_datetime(raw["Execution Timestamp"], utc=True, errors="coerce")
print("  rows", len(raw))
print(raw["Action type"].value_counts().to_string())

# ---------- what fetch_historical_reports keeps, start == end == D ----------
print(f"\n=== fetch_historical_reports(start=end={FRESH}) - the daily service's own call ===")
d = date.fromisoformat(FRESH)
f = DTCCFetcher()
kept = f.fetch_historical_reports(start_date=d, end_date=d, agency="CFTC", asset_class="RATES",
                                  use_pyarrow=True, one_df=True, show_tqdm=False)
print("  rows", len(kept))
print(kept["Action type"].value_counts().to_string())

lost = len(raw) - len(kept)
print(f"\n  rows lost: {lost} of {len(raw)} = {100 * lost / len(raw):.2f}%")
for act in ["TERM", "MODI", "CORR", "NEWT", "EROR", "REVI"]:
    n_raw = int((raw["Action type"] == act).sum())
    n_kept = int((kept["Action type"] == act).sum())
    if n_raw:
        print(f"    {act}: raw {n_raw:>6}  kept {n_kept:>6}  lost {n_raw - n_kept:>6} "
              f"= {100 * (n_raw - n_kept) / n_raw:5.1f}%")
# exercises
if "Event type" in raw.columns:
    for ev in ["ETRM", "PTNG", "EXER", "NOVA", "COMP"]:
        n_raw = int(((raw["Action type"] == "TERM") & (raw["Event type"] == ev)).sum())
        n_kept = int(((kept["Action type"] == "TERM") & (kept["Event type"] == ev)).sum())
        if n_raw:
            print(f"    TERM/{ev}: raw {n_raw:>6}  kept {n_kept:>6}  "
                  f"lost {100 * (n_raw - n_kept) / n_raw:5.1f}%")
    n_raw = int((raw["Event type"] == "EXER").sum())
    n_kept = int((kept["Event type"] == "EXER").sum())
    if n_raw:
        print(f"    any/EXER: raw {n_raw}  kept {n_kept}  lost {100 * (n_raw - n_kept) / n_raw:.1f}%")

# ---------- ignore_cache=True: the half that was code-verified, not measured ----------
print(f"\n=== grab_sdr_trades(ignore_cache=True), production window shape, scratch cache ===")
Path(SCRATCH_CACHE).mkdir(parents=True, exist_ok=True)
sdr = SDRDataBuilder(cache_path=SCRATCH_CACHE, show_tqdm=False)
start = datetime.combine(d, datetime.min.time(), tzinfo=timezone.utc)
prod = sdr.grab_sdr_trades(start_timestamp=start, end_timestamp=start + timedelta(days=2),
                           agency="CFTC", asset_class="RATES", ignore_cache=True)
print("  rows visible to production:", len(prod))
raw_ids = set(raw[DI].dropna().astype(str))
prod_ids = set(prod[DI].dropna().astype(str).str.replace(r"\.0$", "", regex=True))
miss = raw_ids - prod_ids
print(f"  ids in the day's zip that production never sees: {len(miss)} of {len(raw_ids)} "
      f"= {100 * len(miss) / len(raw_ids):.2f}%")
m = raw[raw[DI].astype(str).isin(miss)]
print("  missing by action type:")
print(m["Action type"].value_counts().to_string())
n_term = int((raw["Action type"] == "TERM").sum())
n_term_miss = int((m["Action type"] == "TERM").sum())
print(f"  TERM lost under ignore_cache=True: {n_term_miss} of {n_term} = "
      f"{100 * n_term_miss / max(n_term, 1):.1f}%")

# ---------- why: what execution dates do the lost TERMs carry ----------
print("\n=== the mechanism: execution date of the lost TERM rows ===")
lt = m[m["Action type"] == "TERM"].copy()
lt["_ex"] = pd.to_datetime(lt["Execution Timestamp"], utc=True, errors="coerce")
print("  exec date == file date:", int((lt["_ex"].dt.date == d).sum()))
print("  exec date <  file date:", int((lt["_ex"].dt.date < d).sum()))
print("  exec date quantiles (days before the file date):")
age = (pd.Timestamp(d, tz="UTC") - lt["_ex"]).dt.total_seconds() / 86400.0
print(age.quantile([.5, .9, .99, 1.0]).round(1).to_string())
raw.to_parquet(rf"C:/Users/chris/clee/ARBS-dd/scratch/_verify_{ds}_UNFILTERED.parquet", index=False)
print("\nwrote scratch/_verify_%s_UNFILTERED.parquet" % ds)
