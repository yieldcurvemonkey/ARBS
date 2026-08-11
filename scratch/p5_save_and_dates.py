import sys
from pathlib import Path
import pandas as pd

RAW = Path(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_zip")
DAYS = ["2026_06_15", "2026_06_16", "2026_06_17", "2026_06_18"]
DI = "Dissemination Identifier"
ODI = "Original Dissemination Identifier"

KEEP = [DI, ODI, "Action type", "Event type", "Event timestamp", "Execution Timestamp",
        "Effective Date", "Expiration Date", "Cleared", "Product name",
        "Unique Product Identifier", "UPI FISN", "UPI Underlier Name",
        "Notional amount-Leg 1", "Notional amount-Leg 2",
        "Notional currency-Leg 1", "Notional currency-Leg 2",
        "Fixed rate-Leg 1", "Fixed rate-Leg 2", "Other payment amount",
        "Block trade election indicator", "Package indicator",
        "Underlier ID-Leg 1", "Underlier ID-Leg 2",
        "Underlying asset subtype or underlying contract subtype-Leg 1",
        "Amendment indicator", "Asset Class"]


def norm(s):
    out = s.astype("string").str.strip()
    out = out.replace({"": pd.NA, "None": pd.NA, "NaN": pd.NA, "nan": pd.NA, "<NA>": pd.NA})
    return out.str.replace(r"\.0$", "", regex=True)


frames = []
for d in DAYS:
    df = pd.read_parquet(RAW / f"{d}_UNFILTERED.parquet")
    df = df[[c for c in KEEP if c in df.columns]].copy()
    df["_file_date"] = pd.Timestamp(d.replace("_", "-")).date()
    frames.append(df)
raw = pd.concat(frames, ignore_index=True)
raw[DI] = norm(raw[DI])
raw[ODI] = norm(raw[ODI])
raw["_ex"] = pd.to_datetime(raw["Execution Timestamp"], utc=True, errors="coerce")
raw["_ev"] = pd.to_datetime(raw["Event timestamp"], utc=True, errors="coerce")

print("rows", len(raw))
print("\n=== Event timestamp date vs file date ===")
same_ev = (raw["_ev"].dt.date == raw["_file_date"])
print("event-date == file-date:", int(same_ev.sum()), f"({100*same_ev.mean():.2f}%)")
print("event-date != file-date by Action type:")
print(raw.loc[~same_ev, "Action type"].value_counts(dropna=False))
print("\nevent-date offset (days, event - file) distribution for the mismatches:")
offd = (pd.to_datetime(raw.loc[~same_ev, "_ev"]).dt.tz_localize(None).dt.normalize()
        - pd.to_datetime(raw.loc[~same_ev, "_file_date"])).dt.days
print(offd.value_counts().sort_index().head(20))

print("\n=== TERM subset detail ===")
term = raw[raw["Action type"] == "TERM"]
print("TERM total", len(term))
print(term["Event type"].value_counts())
print("\nTERM: exec-date == file-date?", int((term["_ex"].dt.date == term["_file_date"]).sum()),
      "of", len(term))
print("TERM: event-date == file-date?", int((term["_ev"].dt.date == term["_file_date"]).sum()),
      "of", len(term))
print("\nTERM by Event type: n, dropped_by_cache(exec!=file), reachback_days(event-exec) p50/p90/max")
for et, sub in term.groupby("Event type"):
    rb = (sub["_ev"] - sub["_ex"]).dt.total_seconds() / 86400.0
    print(f"  {et:5s} n={len(sub):>5} dropped={int((sub['_ex'].dt.date != sub['_file_date']).sum()):>5}"
          f"  p50={rb.median():8.3f} p90={rb.quantile(.9):9.2f} max={rb.max():9.2f}")

# duplicated DI across days?
print("\n=== duplicate Dissemination Identifier across the 4 files ===")
print("unique DI:", raw[DI].nunique(), "rows:", len(raw), "dupes:", int(raw[DI].duplicated().sum()))

for c in raw.columns:
    if raw[c].dtype == object:
        raw[c] = raw[c].astype("string")
raw.to_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet", index=False)
print("\nwrote scratch/raw_week_unfiltered.parquet", raw.shape)
