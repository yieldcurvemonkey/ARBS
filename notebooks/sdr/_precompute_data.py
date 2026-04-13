"""
Pre-compute classified SDR trades and save to parquet.
This avoids each notebook re-loading the full year of data.
Usage: conda run -n stir python _precompute_data.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import nest_asyncio
nest_asyncio.apply()

import datetime
import _usd_swaps_common as sdr

START = datetime.datetime(2026, 1, 10, tzinfo=datetime.timezone.utc)
END = datetime.datetime(2026, 4, 10, 23, 59, 59, tzinfo=datetime.timezone.utc)
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_precomputed_trades.parquet")

print(f"Loading classified trades: {START.date()} to {END.date()}")
df = sdr.load_usd_swaps(START, END)

if df.empty:
    print("ERROR: No data loaded. Check date range and cache.")
    sys.exit(1)

n_days = df['execution_date'].nunique() if 'execution_date' in df.columns else 0
print(f"Loaded {len(df):,} trades from {n_days} trading days")
print(f"Total DV01: {sdr.format_dv01(df['dv01'].sum())}")
print(f"Columns: {list(df.columns)}")
print(f"Memory usage: {df.memory_usage(deep=True).sum() / 1e6:.1f} MB")

# Drop any remaining list-typed columns before parquet serialization
for col in df.columns:
    try:
        sample = df[col].dropna().iloc[0] if len(df[col].dropna()) > 0 else None
        if isinstance(sample, (list, dict)):
            print(f"  Dropping unhashable column: {col}")
            df = df.drop(columns=[col])
    except Exception:
        pass

# Save to parquet
df.to_parquet(OUTPUT, index=False, engine="pyarrow")
print(f"Saved to: {OUTPUT}")
print(f"File size: {os.path.getsize(OUTPUT) / 1e6:.1f} MB")
