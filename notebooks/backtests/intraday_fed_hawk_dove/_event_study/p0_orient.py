"""Orientation probe: what the existing artifacts actually contain."""
from __future__ import annotations

import io
import pickle
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd

GCB = Path(r"C:\Users\chris\clee\ARBS-gcb\notebooks\backtests\intraday_fed_hawk_dove\_global_cache")

print("=== events_manual_raw.pkl ===")
with open(GCB / "events_manual_raw.pkl", "rb") as f:
    blob = pickle.load(f)
print("top keys:", list(blob.keys()))
fed = blob["FED"]
print("FED keys:", list(fed.keys()) if isinstance(fed, dict) else type(fed))
evs = fed["events"]
print("n events:", len(evs))
print("first event:", evs[0])
print("last  event:", evs[-1])
dates = sorted(e["speech_ts"].date() for e in evs)
print("range:", dates[0], "->", dates[-1])
srcs = pd.Series([e.get("timestamp_source") for e in evs]).value_counts()
print("timestamp_source:\n", srcs)
buckets = pd.Series([e.get("bucket") for e in evs]).value_counts()
print("bucket:\n", buckets)

print()
print("=== scores csv ===")
for p in [r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\fed_hawk_dove_scores.csv",
          r"C:\Users\chris\clee\project-oasis\private\jpm_research\fed_speak_nlp\global_hawk_dove_scores.csv"]:
    pp = Path(p)
    print(pp.name, "exists:", pp.exists())
    if pp.exists():
        df = pd.read_csv(pp)
        print("  cols:", list(df.columns))
        print("  n:", len(df), " dates:", df["date"].min(), "->", df["date"].max())
        if "central_bank" in df:
            print("  banks:", df["central_bank"].value_counts().to_dict())
        print(df.head(3).to_string())

print()
print("=== cpi/nfp parquet ===")
cn = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis\cpi_nfp_raw.parquet")
print("exists:", cn.exists())
if cn.exists():
    d = pd.read_parquet(cn)
    print("cols:", list(d.columns))
    print("n:", len(d))
    print(d.head(5).to_string())

print()
print("=== fed_calendar_raw.parquet ===")
fc = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_driver_analysis\fed_calendar_raw.parquet")
print("exists:", fc.exists())
if fc.exists():
    d = pd.read_parquet(fc)
    print("cols:", list(d.columns))
    print("n:", len(d))
    print(d.head(5).to_string())
