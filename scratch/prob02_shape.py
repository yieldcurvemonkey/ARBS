"""Shape of the legacy deviations. Biased curve -- SHAPE ONLY (see prob01)."""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
df = pd.read_parquet(os.path.join(HERE, "prob01_devs.parquet"))
df["x"] = df["spread_to_mid_bps"].astype(float)

print("=== overall ===")
print(f"n={len(df):,}  median={df.x.median():+.4f}  mean={df.x.mean():+.4f}")
print(f"IQR=[{df.x.quantile(.25):+.4f},{df.x.quantile(.75):+.4f}]")

for col in ["classification_method", "rate_index_clean", "trade_type", "dv01_bucket"]:
    print(f"\n=== by {col} ===")
    g = df.groupby(col)["x"].agg(["count", "median", "mean", "std"])
    print(g.sort_values("count", ascending=False).head(15).to_string())

print("\n=== excess kurtosis by classification_method (trimmed 1%) ===")
for m, g in df.groupby("classification_method"):
    x = g.x.values
    lo, hi = np.quantile(x, [0.01, 0.99])
    xt = x[(x >= lo) & (x <= hi)]
    xc = xt - xt.mean()
    m2 = (xc ** 2).mean()
    m4 = (xc ** 4).mean()
    print(f"{m:16s} n={len(xt):7,d}  m2={m2:9.4f} m4={m4:12.4f} "
          f"exkurt={m4 / m2 ** 2 - 3:+.3f}")

print("\n=== bucket cardinality: (method, rate_index, tenor_bucket) ===")
key = ["classification_method", "rate_index_clean", "tenor_bucket"]
cnt = df.groupby(key).size().sort_values(ascending=False)
print(f"n buckets={len(cnt)}  >=1000:{(cnt >= 1000).sum()}  >=500:{(cnt >= 500).sum()} "
      f" >=200:{(cnt >= 200).sum()}  >=100:{(cnt >= 100).sum()}  <100:{(cnt < 100).sum()}")
print(cnt.head(12).to_string())
print(f"\nshare of rows in buckets with >=500: "
      f"{cnt[cnt >= 500].sum() / cnt.sum():.1%}")

print("\n=== tenor_bucket vocabulary (top 30) ===")
print(df.tenor_bucket.value_counts().head(30).to_string())

print("\n=== per-month median x (does b0 move?) ===")
df["month"] = pd.to_datetime(df.as_of_date).dt.to_period("M")
mm = df[df.classification_method == "RATE_VS_MID"].groupby("month")["x"].agg(
    ["count", "median", "std"])
print(mm.to_string())
