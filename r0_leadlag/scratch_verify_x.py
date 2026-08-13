"""Independent verification of data/x_signed_dv01.parquet.

Reads the WRITTEN FILE (not the in-memory build) and re-derives every aggregate from
the cached tape legs by a separate route -- scalar bucket/forward functions rather
than the vectorised ones the build used, so a drift between the two shows up.
"The build printed a report" is not evidence the rows exist or are right.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_x_tape as B

FAIL = []


def check(name, cond, detail=""):
    cond = bool(cond)
    print(("  ok   " if cond else "  FAIL ") + name + (f"   {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


x = pd.read_parquet(B.OUT_PARQUET)
print(f"=== file: {B.OUT_PARQUET}  rows={len(x)} ===")
print(x.dtypes.to_string())
print(x.head(4).to_string())
print()

want = ["bucket", "minute_utc", "clock", "signed_dv01", "gross_dv01",
        "n_prints", "is_block", "venue_class"]
check("columns exactly as specified", list(x.columns) == want, str(list(x.columns)))
check("no NaNs anywhere", not x.isna().any().any(), str(x.isna().sum().to_dict()))
check("clock values", set(x["clock"]) == {"diss", "exec"})
check("bucket values", set(x["bucket"]) == set(B.BUCKETS))
check("venue_class values", set(x["venue_class"]) == {"D2C", "IDB"})
check("is_block is bool", x["is_block"].dtype == bool, str(x["is_block"].dtype))
check("minute_utc tz-aware UTC", str(x["minute_utc"].dt.tz) == "UTC")
check("minute_utc minute-floored", bool((x["minute_utc"].dt.second == 0).all()))
check("grain unique", not x.duplicated(["bucket", "minute_utc", "clock", "is_block", "venue_class"]).any())
check("window respected",
      (x["minute_utc"].min() >= B.EMIT_START) and (x["minute_utc"].max() < B.EMIT_END),
      f"{x['minute_utc'].min()} .. {x['minute_utc'].max()}")
check("gross_dv01 > 0 everywhere", bool((x["gross_dv01"] > 0).all()))
check("|signed| <= gross", bool((x["signed_dv01"].abs() <= x["gross_dv01"] + 1e-6).all()))
check("n_prints >= 1", bool((x["n_prints"] >= 1).all()))

# ---- re-derive from the tape cache by an independent route ---------------------
t = pd.read_parquet(B.TAPE_CACHE)
t["execution_timestamp"] = pd.to_datetime(t["execution_timestamp"], utc=True)
for c in ("tenor_years", "forward_start_years", "notional", "fixed_rate"):
    t[c] = pd.to_numeric(t[c], errors="coerce").astype(float)
t["bucket2"] = [B.bucket_for_tenor(v) for v in t["tenor_years"]]          # scalar path
t["fwd_key"] = [B.forward_start_key(v) for v in t["forward_start_years"]]  # scalar path
t["dv01_2"] = t["notional"] * t["tenor_years"] * 1e-4
t["is_block"] = t["is_block"].fillna(False).astype(bool)
t["venue_class"] = np.where(t["platform_identifier"].isin(B.IDB_MICS), "IDB", "D2C")
check("scalar bucket == vectorised bucket on 310k real rows",
      bool((t["bucket2"] == B._bucket_series(t["tenor_years"])).all()))
check("scalar fwd_key == vectorised fwd_key on 310k real rows",
      bool((t["fwd_key"] == B._forward_key_series(t["forward_start_years"])).all()))
t = B.attach_mid_sign(t)

win = (t["execution_timestamp"] >= B.EMIT_START) & (t["execution_timestamp"] < B.EMIT_END)
e = t[win]
xe, xd = x[x["clock"] == "exec"], x[x["clock"] == "diss"]
check("exec n_prints total == tape", int(xe["n_prints"].sum()) == len(e),
      f"file={int(xe['n_prints'].sum())} tape={len(e)}")
check("exec gross_dv01 total == tape", abs(xe["gross_dv01"].sum() - e["dv01_2"].sum()) < 1.0,
      f"file={xe['gross_dv01'].sum():.2f} tape={e['dv01_2'].sum():.2f}")
check("exec signed_dv01 total == tape",
      abs(xe["signed_dv01"].sum() - (e["customer_sign"] * e["dv01_2"]).sum()) < 1.0,
      f"file={xe['signed_dv01'].sum():.2f} tape={(e['customer_sign']*e['dv01_2']).sum():.2f}")

lhs = xe.groupby(["bucket", "is_block", "venue_class"])["gross_dv01"].sum().sort_index()
rhs = e.groupby(["bucket2", "is_block", "venue_class"])["dv01_2"].sum().sort_index()
rhs.index.names = lhs.index.names
check("exec gross_dv01 matches per (bucket,is_block,venue)",
      np.allclose(lhs.values, rhs.reindex(lhs.index).values, atol=1.0),
      f"max abs diff {np.max(np.abs(lhs.values - rhs.reindex(lhs.index).values)):.4f}")

print(f"\n  exec prints={int(xe['n_prints'].sum())}  diss prints={int(xd['n_prints'].sum())}"
      f"  (difference = window-edge truncation; dissemination pushes late prints past EMIT_END)")
check("diss prints within 0.5% of exec",
      abs(int(xd["n_prints"].sum()) - int(xe["n_prints"].sum())) / int(xe["n_prints"].sum()) < 0.005)
check("diss gross_dv01 within 1% of exec",
      abs(xd["gross_dv01"].sum() - xe["gross_dv01"].sum()) / xe["gross_dv01"].sum() < 0.01,
      f"exec={xe['gross_dv01'].sum():.0f} diss={xd['gross_dv01'].sum():.0f}")
check("predicted_futures_sign(+1) == -1 (positive X predicts NEGATIVE Y)",
      B.predicted_futures_sign(+1) == -1)

sg = e["customer_sign"]
paid = (sg == 1).sum() / (sg != 0).sum()
print(f"\n  direction split: {paid*100:.2f}% paid / {(1-paid)*100:.2f}% received "
      f"of {int((sg != 0).sum())} signed prints ({(sg == 0).mean()*100:.1f}% unsigned)")
check("direction split within 45-55%", 0.45 <= paid <= 0.55, f"{paid*100:.2f}% paid")

print("\n  per-clock / per-bucket coverage:")
print(x.groupby(["clock", "bucket"]).agg(
    cells=("n_prints", "size"), prints=("n_prints", "sum"),
    minutes=("minute_utc", "nunique"),
    signed_dv01=("signed_dv01", "sum"), gross_dv01=("gross_dv01", "sum")).to_string())
print(f"\n  N_days exec={xe['minute_utc'].dt.date.nunique()}  diss={xd['minute_utc'].dt.date.nunique()}")
print(f"  N_bins exec={len(xe)} cells / {xe['minute_utc'].nunique()} minutes;"
      f"  diss={len(xd)} cells / {xd['minute_utc'].nunique()} minutes")

print("\n" + ("ALL VERIFICATION CHECKS PASSED" if not FAIL else f"FAILURES: {FAIL}"))
sys.exit(1 if FAIL else 0)
