"""Task 2: reproduce PRODUCTION's own raw reader call, exactly.

Production path (per-day tape ingest, run_ingest -> load_usd_swaps(return_raw=True)
-> USD_SwapProduct.build_classification_dataframe):

    start = D 00:00Z ; end = D+1 00:00Z ; unfiltered_end = end + 1 day
    sdr = SDRDataBuilder(cache_path=_resolve_cache_path(None), show_tqdm=True)
    raw = sdr.grab_sdr_trades(start_timestamp=start, end_timestamp=unfiltered_end,
                              agency="CFTC", asset_class="RATES", ignore_cache=False)
"""
import os, sys, hashlib
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pandas as pd
from SDRUtils.data.builder import SDRDataBuilder

pd.set_option("display.width", 240); pd.set_option("display.max_rows", 100)
DI = "Dissemination Identifier"; ODI = "Original Dissemination Identifier"
CACHE = r"C:/Users/chris/clee/ARBS/sdr_cache"          # == _resolve_cache_path(None) target when SDR_CACHE_PATH unset & cwd=ARBS
CDIR = Path(CACHE) / "CFTC" / "RATES" / "2026" / "06"

before = {p.name: (p.stat().st_size, p.stat().st_mtime) for p in CDIR.glob("*.parquet")}
print("cache files before:", len(before))

sdr = SDRDataBuilder(cache_path=CACHE, show_tqdm=False)

frames = []
for day in ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18"]:
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = start + timedelta(days=1)                 # load_usd_swaps window
    unfiltered_end = end + timedelta(days=1)        # build_classification_dataframe raw pass
    df = sdr.grab_sdr_trades(start_timestamp=start, end_timestamp=unfiltered_end,
                             agency="CFTC", asset_class="RATES", ignore_cache=False)
    n_odi = int(df[ODI].notna().sum()) if ODI in df.columns else -1
    at = df["Action type"].value_counts().to_dict() if "Action type" in df.columns else {}
    print(f"{day}: prod-raw rows={len(df):>6}  ODI non-null={n_odi:>5}  {at}")
    df = df.assign(_prod_day=day)
    frames.append(df)

after = {p.name: (p.stat().st_size, p.stat().st_mtime) for p in CDIR.glob("*.parquet")}
print("cache files after :", len(after), " CHANGED:", before != after)

prod = pd.concat(frames, ignore_index=True)
prod_u = prod.drop_duplicates(subset=[DI])
print(f"\nunion over the 4 production windows: rows={len(prod)}  unique DI={len(prod_u)}")
print("Action type (unique DI):")
print(prod_u["Action type"].value_counts())
print("\nODI non-null (unique DI):", int(prod_u[ODI].notna().sum()),
      f"= {100*prod_u[ODI].notna().mean():.2f}%")
print("\nTERM by Event type (unique DI):")
print(prod_u.loc[prod_u["Action type"] == "TERM", "Event type"].value_counts())

# compare against the unfiltered zips
raw = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet")
praw = set(prod_u[DI].astype("string").str.strip().str.replace(r"\.0$", "", regex=True).dropna())
uraw = set(raw[DI].dropna())
print(f"\nproduction-visible DI: {len(praw)}   unfiltered-zip DI: {len(uraw)}")
print(f"in zips but NOT visible to production: {len(uraw - praw)}")
missing = raw[raw[DI].isin(uraw - praw)]
print(missing["Action type"].value_counts())
print("of those missing, TERM by Event type:")
print(missing.loc[missing["Action type"] == "TERM", "Event type"].value_counts())
print("in production but not in the 4 zips (spillover from 06-19/06-22 files):", len(praw - uraw))
