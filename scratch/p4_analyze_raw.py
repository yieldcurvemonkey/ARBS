"""Task 3 measurement on the UNFILTERED raw week + diff vs the production cache."""
import sys
from pathlib import Path
import pandas as pd
import numpy as np

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_rows", 200)

RAW = Path(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_zip")
CACHE = Path(r"C:/Users/chris/clee/ARBS/sdr_cache/CFTC/RATES/2026/06")
DAYS = ["2026_06_15", "2026_06_16", "2026_06_17", "2026_06_18"]

DI = "Dissemination Identifier"
ODI = "Original Dissemination Identifier"


def norm(s: pd.Series) -> pd.Series:
    """mirror graph_resolver._normalize_identifier + strip float artefacts"""
    out = s.astype("string")
    out = out.str.strip()
    out = out.replace({"": pd.NA, "None": pd.NA, "NaN": pd.NA, "nan": pd.NA, "<NA>": pd.NA})
    out = out.str.replace(r"\.0$", "", regex=True)
    return out


frames = []
for d in DAYS:
    df = pd.read_parquet(RAW / f"{d}_UNFILTERED.parquet")
    df["_file_date"] = pd.Timestamp(d.replace("_", "-")).date()
    frames.append(df)
raw = pd.concat(frames, ignore_index=True)
print("UNFILTERED raw week rows:", len(raw))

raw[DI] = norm(raw[DI])
raw[ODI] = norm(raw[ODI])
raw["_ex"] = pd.to_datetime(raw["Execution Timestamp"], utc=True, errors="coerce")
raw["_ev"] = pd.to_datetime(raw["Event timestamp"], utc=True, errors="coerce")

print("\n=== 1. row counts: cached (production) vs unfiltered ===")
tot_c = tot_r = 0
for d in DAYS:
    dd = d.replace("_", "-")
    c = pd.read_parquet(CACHE / f"{dd}.parquet")
    r = raw[raw["_file_date"] == pd.Timestamp(dd).date()]
    tot_c += len(c); tot_r += len(r)
    print(f"  {dd}: cached={len(c):>6}  unfiltered={len(r):>6}  dropped={len(r)-len(c):>5} ({100*(len(r)-len(c))/len(r):.1f}%)")
print(f"  WEEK : cached={tot_c}  unfiltered={tot_r}  dropped={tot_r-tot_c} ({100*(tot_r-tot_c)/tot_r:.2f}%)")

print("\n=== 2. what the write-time filter dropped (Action type of rows whose exec-date != file date) ===")
off = raw[raw["_ex"].dt.date != raw["_file_date"]]
print("rows with Execution Timestamp date != file date:", len(off), f"({100*len(off)/len(raw):.2f}%)")
print(off["Action type"].value_counts(dropna=False))
print("\n  of those, ODI non-null:", int(off[ODI].notna().sum()), f"({100*off[ODI].notna().mean():.1f}%)")

print("\n=== 3. ODI non-null overall (unfiltered week) ===")
n = len(raw); nn = int(raw[ODI].notna().sum())
print(f"  {nn}/{n} = {100*nn/n:.2f}% carry a non-null Original Dissemination Identifier")

print("\n=== 4. Action type x ODI ===")
ct = pd.crosstab(raw["Action type"].fillna("<NA>"), raw[ODI].notna(), dropna=False)
ct.columns = ["ODI_null", "ODI_present"] if list(ct.columns) == [False, True] else ct.columns
ct["total"] = ct.sum(axis=1)
ct["pct_with_ODI"] = (100 * ct.get("ODI_present", 0) / ct["total"]).round(2)
print(ct.sort_values("total", ascending=False))

print("\n=== 5. Event type x ODI ===")
ct2 = pd.crosstab(raw["Event type"].fillna("<NA>"), raw[ODI].notna(), dropna=False)
ct2.columns = ["ODI_null", "ODI_present"] if list(ct2.columns) == [False, True] else ct2.columns
ct2["total"] = ct2.sum(axis=1)
ct2["pct_with_ODI"] = (100 * ct2.get("ODI_present", 0) / ct2["total"]).round(2)
print(ct2.sort_values("total", ascending=False))

print("\n=== 6. Action type x Event type (counts) ===")
print(pd.crosstab(raw["Action type"].fillna("<NA>"), raw["Event type"].fillna("<NA>")))

print("\n=== 7. exec-vs-event lag for lifecycle rows (days) ===")
for at in ["NEWT", "TERM", "MODI", "CORR", "EROR", "REVI"]:
    sub = raw[raw["Action type"] == at]
    if sub.empty:
        continue
    lag_d = (sub["_ev"] - sub["_ex"]).dt.total_seconds() / 86400.0
    print(f"  {at:5s} n={len(sub):>6}  exec!=file_date {int((sub['_ex'].dt.date != sub['_file_date']).sum()):>5}"
          f"  event-exec days: p50={lag_d.median():.3f} p90={lag_d.quantile(0.9):.3f} max={lag_d.max():.2f}")

raw.to_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet", index=False)
print("\nwrote scratch/raw_week_unfiltered.parquet")
