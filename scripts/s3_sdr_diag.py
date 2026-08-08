"""Session-3 diagnostic: is the Part 43 FILE DATE the dissemination date?

If prints in file <D>.parquet carry Execution Timestamps from days before D, then
the file date is the DISSEMINATION date and any day-t flow variable must be built
from what appeared in files up to and including t -- aggregating by execution
timestamp would give a live trader prints they could not have seen.

Also measures: Package indicator vocabulary, notional cap markers, and the
(action, event) cell distribution -- all inputs to the F7 registration.

Run: C:/Users/chris/anaconda3/envs/stir/python.exe -X utf8 scripts/s3_sdr_diag.py
"""
import os

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import glob
import pathlib

import pandas as pd

SDR_DIR = pathlib.Path(r"C:\Users\chris\clee\ARBS\sdr_cache\CFTC\RATES")  # READ-ONLY

COLS = [
    "Dissemination Identifier", "Original Dissemination Identifier",
    "Action type", "Event type", "Execution Timestamp", "Event timestamp",
    "Effective Date", "Expiration Date", "Fixed rate-Leg 1",
    "Notional currency-Leg 1", "Notional amount-Leg 1",
    "Package indicator", "Package transaction price", "Package transaction spread",
    "Block trade election indicator", "Platform identifier", "Cleared",
    "UPI FISN", "Product name", "Underlying Asset Name",
]


def load(fp: pathlib.Path) -> pd.DataFrame:
    import pyarrow.parquet as pq

    names = set(pq.read_schema(fp).names)
    want = [c for c in COLS if c in names]
    df = pq.read_table(fp, columns=want).to_pandas()
    df["_file_date"] = pd.Timestamp(fp.stem)
    return df


def main() -> None:
    files = sorted(pathlib.Path(p) for p in glob.glob(str(SDR_DIR / "*" / "*" / "*.parquet")))
    print(f"files: {len(files)}  {files[0].stem} .. {files[-1].stem}")

    # --- sample five files spread across the history -------------------------
    idx = [0, len(files) // 4, len(files) // 2, 3 * len(files) // 4, len(files) - 1]
    for i in idx:
        fp = files[i]
        df = load(fp)
        ts = pd.to_datetime(df["Execution Timestamp"], errors="coerce", utc=True)
        exec_d = ts.dt.tz_convert("America/New_York").dt.date
        fd = pd.Timestamp(fp.stem).date()
        lag_days = pd.Series([(fd - d).days if pd.notna(d) else None for d in exec_d]).dropna()
        print(
            f"\n[{fp.stem}] rows={len(df):,}  exec-date == file-date: "
            f"{(lag_days == 0).mean():.1%}"
        )
        print("  lag(file - exec) day counts:",
              lag_days.value_counts().head(8).to_dict())

    # --- vocabularies on the most recent file --------------------------------
    df = load(files[-1])
    print(f"\n=== vocabularies on {files[-1].stem} ({len(df):,} rows) ===")
    for c in ["Action type", "Event type", "Package indicator",
              "Block trade election indicator", "Cleared"]:
        if c in df.columns:
            print(f"  {c}: {df[c].astype(str).value_counts().head(8).to_dict()}")

    usd = df[df.get("Notional currency-Leg 1").astype(str) == "USD"] if \
        "Notional currency-Leg 1" in df.columns else df
    print(f"\n  USD rows: {len(usd):,}")
    if "Notional amount-Leg 1" in usd.columns:
        na = usd["Notional amount-Leg 1"].astype(str)
        capped = na.str.contains("\\+", na=False)
        print(f"  notional strings containing '+': {capped.sum():,} "
              f"({capped.mean():.2%})  examples: {na[capped].head(3).tolist()}")
        print(f"  notional sample: {na.head(5).tolist()}")

    # --- product vocabulary --------------------------------------------------
    key = "UPI FISN" if "UPI FISN" in usd.columns else "Product name"
    print(f"\n  {key} top 10: {usd[key].astype(str).value_counts().head(10).to_dict()}")

    # --- package linkage probe ----------------------------------------------
    if "Package indicator" in usd.columns:
        pk = usd[usd["Package indicator"].astype(str).str.lower().isin(["true", "y", "yes", "1"])]
        print(f"\n  package-flagged USD rows: {len(pk):,} of {len(usd):,}")
        if len(pk):
            ts = pd.to_datetime(pk["Execution Timestamp"], errors="coerce", utc=True)
            grp = pk.assign(_ts=ts).groupby("_ts").size()
            print(f"  distinct exec timestamps among package rows: {len(grp):,}")
            print(f"  legs-per-timestamp distribution: {grp.value_counts().head(8).to_dict()}")


if __name__ == "__main__":
    main()
