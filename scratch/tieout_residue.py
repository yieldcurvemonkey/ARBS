"""The residue, individually; the curve effect by tenor; and the persisted-table
cross-check the tie-out design calls for.

Reads only the parquet the sweep wrote plus a READ-ONLY query against the prod
tape DB for the cross-check. Writes nothing to the database.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd  # noqa: E402

ROOT = r"D:\tieout_cache"
AN = os.path.join(ROOT, "analysis")
pd.set_option("display.width", 200)

m = pd.read_parquet(os.path.join(AN, "joined_bar.parquet"))

print("=" * 78)
print("THE 49 NEW_REFUSED ROWS, INDIVIDUALLY")
print("=" * 78)
ref = m[m["stratum"] == "NEW_REFUSED"]
cols = ["unit_key", "as_of_date", "failure", "trade_type", "kind", "n_legs",
        "dealer_direction", "classification_method", "quality_flags"]
for reason, g in ref.groupby(ref["failure"].fillna(ref["exclusion"])):
    print(f"\n--- {reason}  n={len(g)} ---")
    gg = g[[c for c in cols if c in g.columns]].copy()
    gg["quality_flags"] = gg["quality_flags"].astype(str).str.slice(0, 80)
    print(gg.to_string(index=False))
    if "failure_detail" in g:
        print("  details:", g["failure_detail"].astype(str).str.slice(0, 150)
              .value_counts().head(6).to_dict())

print("\n" + "=" * 78)
print("OLD 'UNKNOWN' ROWS OVERALL (whatever stratum they landed in)")
print("=" * 78)
unk = m[m["dealer_direction"].isin(["UNKNOWN"]) | m["dealer_direction"].isna()]
print(f"n={len(unk)}   stratum: {unk['stratum'].value_counts().to_dict()}")
print(f"new side on them: {unk['side_new'].value_counts(dropna=False).to_dict()}")
print("old quality_flags:")
print(unk["quality_flags"].astype(str).str.slice(0, 90).value_counts().head(8).to_string())

print("\n" + "=" * 78)
print("NEW_EXACT_TIE -- the T-4 zero-branch class, at scale")
print("=" * 78)
tie = m[m["stratum"] == "NEW_EXACT_TIE"]
print(f"n={len(tie)}  old side {tie['dealer_direction'].value_counts().to_dict()}")
print(f"  method {tie['classification_method'].value_counts().to_dict()}")
print(f"  confidence {tie['direction_confidence'].value_counts(dropna=False).to_dict()}")
print(f"  rate_index {tie['rate_index'].value_counts(dropna=False).to_dict()}")
print(f"  days affected: {tie['as_of_date'].nunique()} of {m['as_of_date'].nunique()}")

print("\n" + "=" * 78)
print("CURVE EFFECT BY TENOR BAND  (F-20's monotone gradient, re-measured)")
print("=" * 78)
ce = pd.read_parquet(os.path.join(AN, "curve_effect.parquet"))
ce = ce[ce["side_new_bar"].notna() & ce["side_new_citi"].notna()]
rows = []
for band, g in ce.groupby("tenor_band"):
    rows.append({
        "tenor_band": band, "n": len(g),
        "median_dev_bar": g["deviation_bps_bar"].median(),
        "median_dev_citi": g["deviation_bps_citi"].median(),
        "pctPAID_bar": 100.0 * (g["side_new_bar"] == "PAID").mean(),
        "pctPAID_citi": 100.0 * (g["side_new_citi"] == "PAID").mean(),
        "shift_pct": 100.0 * (g["side_new_bar"] != g["side_new_citi"]).mean(),
        "IQR_dev_bar": g["deviation_bps_bar"].quantile(0.75) - g["deviation_bps_bar"].quantile(0.25),
        "IQR_dev_citi": g["deviation_bps_citi"].quantile(0.75) - g["deviation_bps_citi"].quantile(0.25),
    })
t = pd.DataFrame(rows)
order = ["0-1M", "1M-3M", "3M-6M", "6M-1Y", "1Y-2Y", "2Y-3Y", "3Y-5Y"]
t["o"] = t["tenor_band"].apply(lambda b: order.index(b) if b in order else 99)
print(t.sort_values("o").drop(columns="o").to_string(index=False, float_format="%.4f"))

print("\n" + "=" * 78)
print("CROSS-CHECK: the FRESH reference run vs the PERSISTED arbs_stir_direction_v1")
print("=" * 78)
import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

days = sorted(m["as_of_date"].astype(str).unique())
probe = [days[0], days[len(days) // 3], days[2 * len(days) // 3], days[-1]]
conn = psycopg2.connect(resolve_pg_url(None))
conn.set_session(readonly=True)
for d in probe:
    fresh = m[m["as_of_date"].astype(str) == d][
        ["unit_key", "dealer_direction", "classification_method",
         "direction_confidence", "spread_to_mid_bps"]]
    pers = pd.read_sql(
        "SELECT unit_key, dealer_direction, classification_method, "
        "direction_confidence, spread_to_mid_bps, code_vintage "
        "FROM arbs_stir_direction_v1 WHERE as_of_date = %(d)s", conn, params={"d": d})
    j = fresh.merge(pers, on="unit_key", how="outer", indicator=True,
                    suffixes=("_fresh", "_pers"))
    both = j[j["_merge"] == "both"]
    same = (both["dealer_direction_fresh"] == both["dealer_direction_pers"])
    print(f"\n{d}: fresh {len(fresh)} units, persisted {len(pers)}, "
          f"overlap {len(both)} "
          f"(fresh-only {int((j['_merge'] == 'left_only').sum())}, "
          f"persisted-only {int((j['_merge'] == 'right_only').sum())})")
    print(f"   direction agreement {100.0 * same.mean():.4f}%  "
          f"({int((~same).sum())} differ)")
    if (~same).any():
        dif = both[~same]
        print(dif[["unit_key", "dealer_direction_fresh", "dealer_direction_pers",
                   "classification_method_fresh", "classification_method_pers",
                   "spread_to_mid_bps_fresh", "spread_to_mid_bps_pers"]]
              .head(15).to_string(index=False))
    num = both[both["spread_to_mid_bps_fresh"].notna()
               & both["spread_to_mid_bps_pers"].notna()]
    if len(num):
        dd = (num["spread_to_mid_bps_fresh"] - num["spread_to_mid_bps_pers"]).abs()
        print(f"   max |s2m fresh - s2m persisted| = {dd.max():.3e} bp "
              f"(n={len(num)})   > 0.01 bp on {int((dd > 0.01).sum())}"
              f"   > 1 bp on {int((dd > 1.0).sum())}"
              f"   median {dd.median():.3e}")
        print(f"   persisted code_vintage: "
              f"{pers['code_vintage'].value_counts(dropna=False).to_dict()}")
conn.close()
