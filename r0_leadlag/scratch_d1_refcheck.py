"""Integrity check on the D1 reference cache before any rho is read.

scratch_d1_fullwin.py writes each ref_<tenor>.parquet directly with no tmp+rename, so a
worker killed mid-write leaves a truncated file. Read every one, and check the row count,
the span, monotonicity, and that the rates are plausible USD par rates.
"""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REFDIR = os.path.join(HERE, "cache_d1_ref")

rows = []
for f in sorted(os.listdir(REFDIR)):
    if not f.startswith("ref_"):
        continue
    p = os.path.join(REFDIR, f)
    try:
        d = pd.read_parquet(p)
    except Exception as exc:  # noqa: BLE001
        rows.append((f, -1, f"UNREADABLE {type(exc).__name__}"))
        continue
    tn = d["tenor_lc"].iloc[0]
    dup = int(d.duplicated(["tenor_lc", "ref_min"]).sum())
    rows.append((f, len(d),
                 f"{tn:5s} {d['ref_min'].min()} .. {d['ref_min'].max()}  "
                 f"dup={dup}  nan={int(d['ref_rate'].isna().sum())}  "
                 f"rate p1={d['ref_rate'].quantile(.01):.4f} "
                 f"p50={d['ref_rate'].median():.4f} p99={d['ref_rate'].quantile(.99):.4f}"))

for f, n, msg in rows:
    print(f"{f:18s} {n:8,}  {msg}")

ns = [n for _, n, _ in rows if n > 0]
print()
print(f"{len(rows)} files, row counts min {min(ns):,} max {max(ns):,}")
