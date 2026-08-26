"""Orient on the event/placebo panels before building Chart 1."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove\_event_study")

ev = pd.read_parquet(HERE / "event_paths.parquet")
pl = pd.read_parquet(HERE / "placebo_paths.parquet")

print("EVENT PANEL", ev.shape)
print(ev.dtypes.to_string())
print()
print("PLACEBO PANEL", pl.shape)
print([c for c in pl.columns if c not in ev.columns], "extra cols")
print()

md = pq.read_schema(HERE / "event_paths.parquet").metadata or {}
for k, v in md.items():
    try:
        print(f"META {k.decode()} = {v.decode()[:400]}")
    except Exception:
        pass
print()

r3 = ev[ev["contract_rank"] == 3]
print("rank-3 rows:", len(r3), "events:", r3["event_id"].nunique())
print()
print("stance_sign x is_overlapping (unique events, rank3):")
u = r3.drop_duplicates("event_id")
print(pd.crosstab(u["stance_sign"], u["is_overlapping"]).to_string())
print()
print("bucket dist (unique events):")
print(u["bucket"].value_counts().sort_index().to_string())
print()
print("price coverage by offset, rank3, non-overlapping signed:")
sub = r3[(~r3["is_overlapping"]) & (r3["stance_sign"] != 0)]
cov = sub.groupby("offset_min").agg(
    n=("event_id", "nunique"),
    n_priced=("price", "count"),
    n_signed=("signed_d_bp", "count"),
)
print(cov.to_string())
print()
print("same for ALL events rank3:")
cov2 = r3[r3["stance_sign"] != 0].groupby("offset_min").agg(
    n=("event_id", "nunique"), n_signed=("signed_d_bp", "count"))
print(cov2.to_string())
print()
print("placebo rank3 signed coverage:")
p3 = pl[(pl["contract_rank"] == 3) & (pl["stance_sign"] != 0)]
print(p3.groupby("offset_min").agg(n=("event_id", "nunique"), n_signed=("signed_d_bp", "count")).to_string())
print()
print("placebo has is_overlapping?", pl["is_overlapping"].value_counts().to_dict())
print()
print("sample rows:")
print(r3.head(3).to_string())
