"""AUDIT (refute-probe) 1: locate the claimed negative-notional package and trace it to source."""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import pathlib

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 60)

_REPO = pathlib.Path(__file__).resolve().parents[1]
OUT = _REPO / "notebooks" / "data" / "citivelo_rv"
SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")

pkg = pd.read_parquet(OUT / "f7_packages.parquet")
pkg["file_date"] = pd.to_datetime(pkg["file_date"])
print(f"packages: {len(pkg):,}  cols={list(pkg.columns)}")
print(f"file_date range {pkg['file_date'].min().date()} .. {pkg['file_date'].max().date()}")

tot = pkg["notional_sum"].sum()
neg_sum = pkg[pkg["notional_sum"] < 0]
neg_min = pkg[pkg["notional_min"] < 0]
nan_sum = pkg[~np.isfinite(pkg["notional_sum"])]
zero_sum = pkg[pkg["notional_sum"] == 0]
print(f"\ntotal notional_sum = {tot:,.0f}")
print(f"packages with notional_sum < 0 : {len(neg_sum)}")
print(f"packages with notional_min < 0 : {len(neg_min)}")
print(f"packages with non-finite notional_sum : {len(nan_sum)}")
print(f"packages with notional_sum == 0 : {len(zero_sum)}")

print("\n--- rows with notional_min < 0 ---")
if len(neg_min):
    print(neg_min.to_string(index=False))
print("\n--- rows with notional_sum < 0 ---")
if len(neg_sum):
    print(neg_sum.to_string(index=False))
    print(f"share of summed notional: {neg_sum['notional_sum'].sum() / tot:.6%}")

# ---- trace to the raw file -------------------------------------------------
for _, r in neg_min.iterrows():
    fd = r["file_date"].strftime("%Y-%m-%d")
    hits = sorted(glob.glob(str(SDR_DIR / "*" / "*" / f"{fd}.parquet")))
    print(f"\n=== raw trace for file_date={fd} exec_ts={r['exec_ts']} sig={r['signature']} ===")
    print(f"raw files matching: {hits}")
    if not hits:
        continue
    fp = pathlib.Path(hits[0])
    names = set(pq.read_schema(fp).names)
    want = [c for c in ["Action type", "Event type", "Execution Timestamp", "Effective Date",
                        "Expiration Date", "Fixed rate-Leg 1", "Notional currency-Leg 1",
                        "Notional amount-Leg 1", "Notional amount-Leg 2", "Package indicator",
                        "Block trade election indicator", "Cleared", "Platform identifier",
                        "UPI FISN", "Product name", "Dissemination identifier",
                        "Original dissemination identifier", "Amendment indicator",
                        "Notional quantity-Leg 1", "Total notional quantity-Leg 1"]
            if c in names]
    df = pq.read_table(fp, columns=want).to_pandas()
    ts = pd.to_datetime(df["Execution Timestamp"], errors="coerce", utc=True)
    target = pd.Timestamp(r["exec_ts"])
    if target.tzinfo is None:
        target = target.tz_localize("UTC")
    m = ts.eq(target)
    print(f"rows in raw file at that exec ts: {int(m.sum())}")
    print(df.loc[m].to_string(index=False))
    print("\nrepr of the notional strings:")
    for v in df.loc[m, "Notional amount-Leg 1"]:
        print("   ", repr(v))
