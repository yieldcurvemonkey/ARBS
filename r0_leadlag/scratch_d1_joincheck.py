"""R10's known-answer check on the D1 join, run BEFORE any rho is read.

Prints ONLY the join diagnostics the deviations file declares must pass first:
match rate, per-day median dev_curve, and the correlation of dev_curve with the rate
level (a tz/units error would drive that toward +-1). Deliberately prints no rho and no
sign-agreement rate.
"""
import os, sys
os.environ["ARBS_SUPABASE_ENABLED"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import numpy as np, pandas as pd

REFDIR = os.path.join(HERE, "cache_d1_ref")
legs = pd.read_parquet(os.path.join(HERE, "cache", "tape_legs_signed.parquet"))
have = sorted({f[4:-8] for f in os.listdir(REFDIR) if f.startswith("ref_")})
print("reference tenors available:", have)

legs["tenor_lc"] = legs["tenor_label"].astype(str).str.lower()
et = legs["execution_timestamp"].dt.tz_convert("America/New_York").dt.hour
sel = ((legs["fwd_key"] == "spot") & (~legs["is_mac"]) & legs["tenor_lc"].isin(have)
       & legs["dev_median"].notna() & et.between(1, 22)
       & (legs["execution_timestamp"] >= pd.Timestamp("2026-05-01", tz="UTC"))
       & (legs["execution_timestamp"] < pd.Timestamp("2026-08-08", tz="UTC")))
d = legs[sel].copy()
d["exec_min"] = d["execution_timestamp"].dt.floor("min")
print(f"prints in the join test: {len(d):,}")

ref = pd.concat([pd.read_parquet(os.path.join(REFDIR, f"ref_{t}.parquet")) for t in have],
                ignore_index=True).drop_duplicates(["tenor_lc", "ref_min"])
parts = []
for tn, g in d.groupby("tenor_lc"):
    r = ref[ref["tenor_lc"] == tn][["ref_min", "ref_rate"]].sort_values("ref_min")
    parts.append(pd.merge_asof(g.sort_values("exec_min"), r, left_on="exec_min",
                               right_on="ref_min", direction="backward",
                               tolerance=pd.Timedelta("2min")))
j = pd.concat(parts, ignore_index=True)
print(f"match rate: {j['ref_rate'].notna().mean():.1%}  "
      f"({int(j['ref_rate'].notna().sum()):,}/{len(j):,})")
print("per-tenor match rate:")
for tn, g in j.groupby("tenor_lc"):
    print(f"   {tn:5s} {g['ref_rate'].notna().mean():6.1%}  (n={len(g):,})")

j = j[j["ref_rate"].notna()].copy()
scale = float(np.nanmedian(j["ref_rate"] / j["fixed_rate"]))
print(f"\nreference/tape rate scale (median ratio) = {scale:.3f}")
j["ref_dec"] = j["ref_rate"] / (100.0 if scale > 50 else 1.0)
j["dev_curve"] = j["fixed_rate"] - j["ref_dec"]

print("\nKNOWN-ANSWER CHECK — per-day median dev_curve must sit near zero (bp):")
dm = j.assign(day=j["exec_min"].dt.date).groupby("day")["dev_curve"].median() * 1e4
print(f"  n_days {len(dm)}  p5 {dm.quantile(.05):+.2f}  p50 {dm.median():+.2f}  "
      f"p95 {dm.quantile(.95):+.2f}  min {dm.min():+.2f}  max {dm.max():+.2f}")
print(f"  overall median dev_curve  = {j['dev_curve'].median()*1e4:+.2f} bp, "
      f"IQR {(j['dev_curve'].quantile(.75)-j['dev_curve'].quantile(.25))*1e4:.2f} bp")
print(f"  overall median dev_median = {j['dev_median'].median()*1e4:+.2f} bp, "
      f"IQR {(j['dev_median'].quantile(.75)-j['dev_median'].quantile(.25))*1e4:.2f} bp")
print(f"  corr(dev_curve, rate level) = "
      f"{np.corrcoef(j['dev_curve'], j['ref_dec'])[0,1]:+.3f}  "
      f"(a tz/units error drives this toward +-1)")
print("\nper-tenor median dev_curve (bp):")
for tn, g in j.groupby("tenor_lc"):
    print(f"   {tn:5s} {g['dev_curve'].median()*1e4:+8.2f}   n={len(g):,}")
print("\n(no rho, no sign-agreement rate printed by design)")
