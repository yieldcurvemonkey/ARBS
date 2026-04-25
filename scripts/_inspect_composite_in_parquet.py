"""Check whether composite package types exist in the classification parquets."""
import pandas as pd
from pathlib import Path

for day in ["2026-04-23", "2026-04-10", "2026-04-17"]:
    root = Path(
        f"C:/Users/chris/clee/ARBS/sdr_cache/classification_cache/"
        f"usd_swaps/ERIS_EOD_LIVE-RL_BASIC/"
        f"curve1_fly1_mms1_invoice1_mac1_spreadover1/"
        f"2026/04/{day}"
    )
    files = list(root.glob("*.parquet"))
    if not files:
        print(f"{day}: no parquet")
        continue
    df = pd.read_parquet(files[0])
    print(f"\n=== {day} ===  rows={len(df)}")
    counts = df["package_type"].value_counts(dropna=False)
    for pt, n in counts.items():
        print(f"  {pt!s:<30} {n}")
    composites = df[df["package_type"].astype(str).str.contains("_", na=False) & df["package_type"].astype(str).str.contains("CURVE|FLY", na=False)]
    print(f"  composites: {len(composites)}")
