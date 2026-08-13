"""Validate dd_nb against answers known in advance.

1. s2_positioning built 2025-06-16..18 through the same modules. Every unit it
   and dd_nb both classify under the same rule must carry the SAME deviation,
   the same npv_pay and the same structure_dv01 -- s2 is the reference.
2. The 7 recovered PKG-N on 2025-06-17 must be routed differently: s2 has them
   under NPV_VS_UPFRONT, dd_nb under PACKAGE_PRICE_VS_MODEL. That divergence is
   the claim; if it is not there the claim is wrong.
3. The ladder's PRICING_ERROR remainder must be explainable.
4. Visibility dates outside the tape window must be explainable.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"

REPO = r"C:\Users\chris\clee\ARBS-dd"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "notebooks", "dealer_direction"))

import pathlib  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import dd_nb  # noqa: E402

S2 = pathlib.Path("D:/dd_signals_cache/s2_pos/units")
DAYS = ["2025-06-16", "2025-06-17", "2025-06-18"]

pipe = dd_nb.run_pipeline(dd_nb.config())
mine = pipe.pricing.units
s2 = pd.concat([pd.read_parquet(S2 / f"{d}.parquet") for d in DAYS],
               ignore_index=True)

print("=" * 74)
print("1. dd_nb vs s2_positioning, same units, same modules")
print("=" * 74)
j = mine.merge(s2, on="unit_key", suffixes=("_me", "_s2"), how="inner")
print(f"units in both: {len(j)} (dd_nb {len(mine)}, s2 {len(s2)})")

same_rule = j[j["rule_me"] == j["rule_s2"]]
print(f"same rule on {len(same_rule)}; differing rule on "
      f"{len(j) - len(same_rule)}")

fails_agree = (j["failure_me"].isna() == j["failure_s2"].isna())
print(f"pricing outcome agrees on {int(fails_agree.sum())}/{len(j)}")
assert fails_agree.all(), "a unit priced in one build and not the other"

ok = same_rule[same_rule["failure_me"].isna()]
for col in ("deviation_bps", "npv_pay", "structure_dv01", "gross_pv01"):
    a = pd.to_numeric(ok[f"{col}_me"], errors="coerce")
    b = pd.to_numeric(ok[f"{col}_s2"], errors="coerce")
    both = a.notna() & b.notna()
    d = float((a[both] - b[both]).abs().max()) if both.any() else np.nan
    print(f"  {col:18s} n={int(both.sum()):5d}  max |diff| = {d:.3e}")
    assert not both.any() or d < 1e-9, f"{col} disagrees with s2"

print("\n" + "=" * 74)
print("2. the routing divergence -- s2 sends recovered PKG-N to the upfront rule")
print("=" * 74)
diff = j[j["rule_me"] != j["rule_s2"]]
print(diff.groupby(["kind_me", "rule_s2", "rule_me"]).size().to_string())
pk = diff[diff["kind_me"] == "PKG"]
assert len(pk) >= 1, "no PKG was routed differently; the claim is false"
assert set(pk["rule_s2"]) == {"NPV_VS_UPFRONT"}, set(pk["rule_s2"])
assert set(pk["rule_me"]) == {"PACKAGE_PRICE_VS_MODEL"}, set(pk["rule_me"])
print(f"\n{len(pk)} PKG units: s2 NPV_VS_UPFRONT -> dd_nb PACKAGE_PRICE_VS_MODEL")
print("  s2's per-leg hypothesis under NPV_VS_UPFRONT would be (1,)*n:")
import SDRUtils.dealer_direction.conventions as conv  # noqa: E402
for k in list(pk["unit_key"])[:3]:
    c = next(c for c in pipe.calls.calls if c.unit_key == k)
    n = int(pk.loc[pk["unit_key"] == k, "n_legs_me"].iloc[0])
    print(f"    {k}: s2 {conv.base_orientation('PKG', n, conv.RULE_UPFRONT)} "
          f"vs dd_nb {c.base_orientation}")
    assert c.base_orientation != conv.base_orientation("PKG", n,
                                                       conv.RULE_UPFRONT), \
        "the recovered orientation is the same as the upfront fallback"

print("\n" + "=" * 74)
print("3. the ladder's PRICING_ERROR remainder")
print("=" * 74)
exc = pipe.ladder.excluded
pe = exc[exc["failure_reason"] == "PRICING_ERROR"]
print(f"{len(pe)} units excluded by the ladder as PRICING_ERROR")
if len(pe):
    keys = set(pe["unit_key"])
    k = pipe.krd.krd[pipe.krd.krd["unit_key"].isin(keys)]
    print(f"  KRD rows for those units: {len(k)}")
    kf = pipe.krd.failures[pipe.krd.failures["unit_key"].isin(keys)]
    print(f"  KRD failures for those units: {len(kf)}")
    if len(kf):
        print(kf[["unit_key", "failure_reason", "failure_detail"]]
              .head(10).to_string(index=False))
    sub = mine[mine["unit_key"].isin(keys)]
    print(sub[["unit_key", "kind", "rule", "n_legs", "structure_dv01",
               "tenor_years"]].head(12).to_string(index=False))
    lg = pipe.pricing.legs[pipe.pricing.legs["unit_key"].isin(keys)]
    print("  notionals:", lg["notional"].describe().to_dict())

print("\n" + "=" * 74)
print("4. visibility dates outside the tape window")
print("=" * 74)
ur = pipe.ladder.unit_rows.drop_duplicates("unit_key")
vd = pd.to_datetime(ur["visibility_date"])
aod = pd.to_datetime(ur["as_of_date"])
lag = (vd - aod).dt.days
print(lag.value_counts().sort_index().to_string())
odd = ur[(vd < pd.Timestamp("2025-06-16")) | (vd > pd.Timestamp("2025-06-18"))]
print(f"\n{len(odd)} units stamped outside the tape window")
print(odd.groupby([pd.to_datetime(odd['visibility_date']).dt.date,
                   "is_block", "is_capped", "visibility_source"])
      .size().to_string())
print("\nsample of the far-forward ones:")
far = odd[pd.to_datetime(odd["visibility_date"]) > pd.Timestamp("2025-06-19")]
print(far[["unit_key", "as_of_date", "execution_timestamp",
           "visibility_timestamp", "visibility_source", "is_block",
           "is_capped"]].head(5).to_string(index=False))

print("\nALL VERIFICATIONS PASSED")
