"""Profile TradeTape compute() per-layer timing."""
import time, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))

import datetime
import pandas as pd
import _usd_swaps_common as sdr
from SDRUtils.analytics.trade_tape import TradeTape

classified_df, raw_df = sdr.load_usd_swaps(
    datetime.datetime(2026, 3, 2),
    datetime.datetime(2026, 3, 6),
    return_raw=True,
)
print(f"Input: {len(classified_df):,} trades, {len(classified_df.columns)} cols")
print(f"Raw: {len(raw_df):,} rows")

tape = TradeTape(classified_df, raw_df=raw_df)
df = tape._df.copy()

steps = [
    ("Prerequisites", tape._ensure_prerequisites),
    ("Classification", tape._enrich_classification),
    ("UPI reference", tape._enrich_upi_reference),
    ("Off-date detection", tape._detect_off_date),
    ("Lifecycle", tape._enrich_lifecycle),
    ("Cross-day lifecycle", tape._enrich_cross_day_lifecycle),
    ("Event type", tape._enrich_event_type),
    ("Quality flags", tape._enrich_quality),
    ("Packages", tape._enrich_packages),
    ("Market context", tape._enrich_context),
    ("Clustering", tape._enrich_rv),
    ("Tape labels", tape._build_enriched_label),
]

total = 0
for name, fn in steps:
    t0 = time.perf_counter()
    df = fn(df)
    elapsed = time.perf_counter() - t0
    total += elapsed
    print(f"  {name:25s} {elapsed:7.3f}s  ({len(df)} rows, {len(df.columns)} cols)")

print(f"  {'TOTAL':25s} {total:7.3f}s")
