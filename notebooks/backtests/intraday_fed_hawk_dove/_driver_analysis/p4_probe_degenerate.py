"""Probe 4: localise the flat-curve stretches the monthly sample turned up.

The year-level numbers from stage 2 came back healthy (2019 spread std 63.6 bp,
beta -0.29), which contradicts the monthly probe's reading that 2019 was pinned.
Both can be true if the pathology is EPISODIC. This finds the episodes and sizes
them, so the panel's notes can name the unusable stretches instead of condemning
or clearing whole years.

Two distinct signatures:
  A. FLAT CURVE   -- |IMM_3xIMM_4 - ON| < 2bp and |2y - ON| < 5bp on the same day
  B. FROZEN ON    -- the ON leg repeats a value for a long run
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

sys.stdout.reconfigure(line_buffering=True)

OUT = pathlib.Path(r"C:\Users\chris\clee\ARBS\notebooks\backtests"
                   r"\intraday_fed_hawk_dove\_driver_analysis")
CURVE = "USD-SOFR-1D"
C_IMM, C_ON = f"{CURVE} IMM_3xIMM_4 OUTRIGHT RATE", f"{CURVE} 1d OUTRIGHT RATE"
C_2Y, C_5Y = f"{CURVE} 2y OUTRIGHT RATE", f"{CURVE} 5y OUTRIGHT RATE"


def runs(mask: pd.Series):
    out, start, prev = [], None, False
    for d, v in mask.items():
        if v and not prev:
            start = d
        if prev and not v:
            out.append((start, prev_d))
        prev, prev_d = v, d
    if prev:
        out.append((start, mask.index[-1]))
    return out


def main() -> None:
    r = pd.read_parquet(OUT / "rates_daily.parquet")
    r.index = pd.to_datetime(r.index)
    r = r.sort_index()

    flat = ((r[C_IMM] - r[C_ON]).abs() * 100 < 2.0) & \
           ((r[C_2Y] - r[C_ON]).abs() * 100 < 5.0)
    print(f"FLAT-CURVE days: {int(flat.sum())} of {len(r)} ({flat.mean():.1%})")
    print("by year:")
    print(flat.groupby(r.index.year).agg(["sum", "mean"]).round(3).to_string())
    print("\nruns of >= 3 consecutive flat days:")
    for a, b in runs(flat):
        n = int(flat.loc[a:b].sum())
        if n >= 3:
            print(f"  {a.date()} .. {b.date()}  ({n} days)")

    same = r[C_ON].diff().abs() < 1e-9
    print(f"\nFROZEN-ON days (ON unchanged from prior served day): "
          f"{int(same.sum())} ({same.mean():.1%})")
    print("longest frozen runs (>= 5 days):")
    for a, b in runs(same):
        n = int(same.loc[a:b].sum())
        if n >= 5:
            v = r.loc[a, C_ON]
            print(f"  {a.date()} .. {b.date()}  ({n} days) at ON={v:.4f}")

    print("\n=== the specific stretches the monthly probe flagged ===")
    for a, b in [("2019-01-02", "2019-07-31"), ("2019-09-01", "2019-12-31")]:
        g = r.loc[a:b]
        s = (g[C_IMM] - g[C_ON]) * 100
        print(f"  {a}..{b}: n={len(g)}  spread mean {s.mean():.2f} std {s.std():.2f} bp"
              f"   ON range {g[C_ON].min():.4f}..{g[C_ON].max():.4f}"
              f"   IMM range {g[C_IMM].min():.4f}..{g[C_IMM].max():.4f}")

    print("\n=== IMM_3xIMM_4 own dynamics, the thing the study actually uses ===")
    d = r[C_IMM].diff() * 100
    print(d.groupby(r.index.year).agg(
        ["count", "mean", "std", lambda x: x.abs().mean(),
         lambda x: (x.abs() < 1e-9).mean()]).round(3).to_string(
        header=["n", "mean", "std", "mean_abs", "frac_zero"]))


if __name__ == "__main__":
    main()
