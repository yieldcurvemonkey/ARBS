"""How much trimming does the moment check need before it stops firing?

The point is NOT to trim until it passes -- it is to find out whether the
leptokurtosis is a fat tail (trimmable) or the body of the distribution
(not trimmable, and therefore a real model-failure diagnostic).
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
df = pd.read_parquet(os.path.join(HERE, "prob01_devs.parquet"))
df["x"] = df["spread_to_mid_bps"].astype(float)


def moments(x, trim):
    lo, hi = np.quantile(x, [trim, 1 - trim])
    xt = x[(x >= lo) & (x <= hi)]
    c = xt - xt.mean()
    m2 = float((c ** 2).mean())
    m4 = float((c ** 4).mean())
    disc = m2 ** 2 - (m4 - m2 ** 2) / 2.0
    if disc < 0:
        return len(xt), m2, m4 / m2 ** 2 - 3, None, None
    s2 = m2 - np.sqrt(disc)
    return len(xt), m2, m4 / m2 ** 2 - 3, np.sqrt(max(s2, 0)), np.sqrt(max(m2 - s2, 0))


for name, sub in [
    ("ALL RATE_VS_MID", df[df.classification_method == "RATE_VS_MID"]),
    ("SOFR 2Y", df[(df.classification_method == "RATE_VS_MID")
                   & (df.rate_index_clean == "SOFR") & (df.tenor_bucket == "2Y")]),
    ("SOFR 1Y", df[(df.classification_method == "RATE_VS_MID")
                   & (df.rate_index_clean == "SOFR") & (df.tenor_bucket == "1Y")]),
    ("SOFR 3M", df[(df.classification_method == "RATE_VS_MID")
                   & (df.rate_index_clean == "SOFR") & (df.tenor_bucket == "3M")]),
    ("FF FOMC_JUL26", df[(df.rate_index_clean == "FED_FUNDS")
                         & (df.tenor_bucket == "FOMC_JUL26")]),
    ("CURVE all", df[df.classification_method == "SPREAD_VS_MID"]),
]:
    x = sub.x.values.astype(float)
    print(f"\n--- {name}  n_raw={len(x):,} ---")
    for trim in (0.0, 0.005, 0.01, 0.025, 0.05, 0.10):
        n, m2, ek, s, h = moments(x, trim) if trim > 0 else moments(x, 1e-9)
        tag = "IMAGINARY" if s is None else f"s={s:.4f} h={h:.4f} tau={s * s / (2 * h):.4f}"
        print(f"  trim={trim:5.3f} n={n:7,d} sd={np.sqrt(m2):9.4f} exkurt={ek:+9.3f}  {tag}")
