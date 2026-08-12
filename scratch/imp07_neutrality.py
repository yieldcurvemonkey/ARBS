"""Read-only. Three numbers the imputation cannot be reported without.

A. DIRECTION NEUTRALITY. If capped prints are directionally skewed, a ~15% DV01
   imputation is a systematic TILT applied to the ladder, not a variance
   correction -- the difference between a caveat and a bias. The free 2x2s are
   is_capped x direction and is_block x direction against the frozen
   classifier's labels (not truth, but the only labels that exist today; a
   *differential* between capped and uncapped is far more robust to that
   classifier's known 78%-PAID skew than either margin is).
B. THE OVERLAP. Capped legs are ~5x more likely to carry a NULL fixed_rate, so
   the DV01 that needs imputing sits disproportionately on legs that cannot be
   direction-classified at all. Quantified in DV01-proxy terms, not counts.
C. COVERAGE. How many capped legs the shipped notional-keyed lookup imputes,
   against the number the fit was calibrated on.
"""
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd
import psycopg2
from scipy import stats as sps

from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import DIRECTION_TABLE
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import imputation as imp

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 200)
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"


def two_by_two(df, flag):
    """counts, RECEIVED share each way, odds ratio, Fisher p."""
    t = df.pivot_table(index=flag, columns="dealer_direction", values="n",
                       aggfunc="sum", fill_value=0)
    for c in ("PAID", "RECEIVED"):
        if c not in t:
            t[c] = 0
    for i in (False, True):
        if i not in t.index:
            t.loc[i] = 0
    a, b = float(t.loc[True, "RECEIVED"]), float(t.loc[True, "PAID"])
    c, d = float(t.loc[False, "RECEIVED"]), float(t.loc[False, "PAID"])
    orr = (a * d) / (b * c) if b * c else np.nan
    p = sps.fisher_exact([[int(a), int(b)], [int(c), int(d)]])[1] if min(a + b, c + d) else np.nan
    return {"n_flag": int(a + b), "n_other": int(c + d),
            "recv_share_flag": a / (a + b) if a + b else np.nan,
            "recv_share_other": c / (c + d) if c + d else np.nan,
            "odds_ratio": orr, "fisher_p": p}


print("=" * 104)
print("A. DIRECTION NEUTRALITY")
print("=" * 104)
span = q(f"SELECT min(as_of_date) d0, max(as_of_date) d1, count(*) n FROM {DIRECTION_TABLE}")
print(f"frozen-classifier label window: {span.d0[0]} .. {span.d1[0]}  ({span.n[0]:,} units)")
print("NOTE: that window sits entirely inside the V2 cap vintage, and the frozen")
print("      classifier only covers tenors below its 3.02y cutoff. Nothing here")
print("      speaks to V1-era or long-end directional skew.\n")

pair = q(f"""
SELECT d.classification_method AS method, d.dealer_direction,
       l.is_capped, l.is_block, count(*) AS n,
       sum(l.notional * l.tenor_years * 1e-4) AS dv01
FROM {DIRECTION_TABLE} d JOIN {LEGS_TABLE} l USING (trade_id)
WHERE l.economic_class = 'ECONOMIC_FLOW' AND l.contributes_to_flow
  AND l.tenor_years > 0 AND l.notional > 0 AND l.notional < 1e11
  AND d.dealer_direction IN ('PAID', 'RECEIVED')
GROUP BY 1, 2, 3, 4
""")
pair["is_capped"] = pair["is_capped"].astype(bool)
pair["is_block"] = pair["is_block"].astype(bool)
pair["dv01"] = pair["dv01"].astype(float)
print(f"joined leg-direction rows: {int(pair['n'].sum()):,}")

for flag in ("is_capped", "is_block"):
    print(f"\n--- {flag} x direction (count-weighted) ---")
    rows = [{"method": "ALL METHODS", **two_by_two(pair, flag)}]
    for meth, g in pair.groupby("method"):
        rows.append({"method": meth, **two_by_two(g, flag)})
    print(pd.DataFrame(rows).to_string(index=False,
                                       float_format=lambda v: f"{v:.4f}"))

print("\n--- the same 2x2s weighted by DV01 proxy rather than by count ---")
for flag in ("is_capped", "is_block"):
    t = pair.pivot_table(index=flag, columns="dealer_direction", values="dv01",
                         aggfunc="sum", fill_value=0.0)
    t["recv_share"] = t["RECEIVED"] / (t["RECEIVED"] + t["PAID"])
    print(f"\n{flag}:")
    print(t.to_string(float_format=lambda v: f"{v:,.5g}"))

print("\n" + "=" * 104)
print("B. THE OVERLAP: imputed DV01 that cannot be direction-classified")
print("=" * 104)
ov = q(f"""
SELECT is_capped, (fixed_rate IS NULL) AS rate_null, count(*) n,
       sum(notional * tenor_years * 1e-4) dv01_proxy
FROM {LEGS_TABLE}
WHERE {FLOW} AND tenor_years > 0 AND notional > 0 AND notional < 1e11
GROUP BY 1, 2 ORDER BY 1, 2
""")
ov["dv01_proxy"] = ov["dv01_proxy"].astype(float)
print(ov.to_string(index=False))
tot_n, tot_d = ov["n"].sum(), ov["dv01_proxy"].sum()
cap = ov[ov.is_capped]
unc = ov[~ov.is_capped]
print(f"\nP(rate NULL | capped)   = {cap.loc[cap.rate_null, 'n'].sum() / cap['n'].sum():.4%}")
print(f"P(rate NULL | uncapped) = {unc.loc[unc.rate_null, 'n'].sum() / unc['n'].sum():.4%}")
print(f"capped share of legs                  = {cap['n'].sum() / tot_n:.4%}")
print(f"capped share of DV01 proxy AT THE CAP = {cap['dv01_proxy'].sum() / tot_d:.4%}")

print("\n== the same, with the shipped multiplier applied to the capped legs ==")
mult = q(f"""
SELECT CASE WHEN as_of_date < DATE '2024-10-07' THEN 'V1' ELSE 'V2' END vintage,
       notional, (fixed_rate IS NULL) AS rate_null, count(*) n,
       sum(notional * tenor_years * 1e-4) dv01_proxy
FROM {LEGS_TABLE}
WHERE {FLOW} AND is_capped AND tenor_years > 0 AND notional > 0 AND notional < 1e11
GROUP BY 1, 2, 3
""")
mult["dv01_proxy"] = mult["dv01_proxy"].astype(float)
mult["factor"] = [imp._BY_CAP[(v, float(n))].multiplier
                  if (v, float(n)) in imp._BY_CAP else np.nan
                  for v, n in zip(mult["vintage"], mult["notional"])]
mult["dv01_imputed"] = mult["dv01_proxy"] * mult["factor"]
matched = mult["factor"].notna()
print(f"capped legs matched to a cap value: {int(mult.loc[matched, 'n'].sum()):,} "
      f"of {int(mult['n'].sum()):,}")
excess = float((mult.loc[matched, "dv01_imputed"] - mult.loc[matched, "dv01_proxy"]).sum())
print(f"total DV01 proxy observed              = {tot_d:,.5g}")
print(f"total DV01 proxy after imputation      = {tot_d + excess:,.5g}")
print(f"imputed (unobserved) share of the total= {excess / (tot_d + excess):.4%}")

null_rows = matched & mult["rate_null"]
null_excess = float((mult.loc[null_rows, "dv01_imputed"] - mult.loc[null_rows, "dv01_proxy"]).sum())
null_imp_total = float(mult.loc[null_rows, "dv01_imputed"].sum())
all_imp_total = float(mult.loc[matched, "dv01_imputed"].sum())
null_all = float(ov.loc[ov.rate_null, "dv01_proxy"].sum())
print(f"\nof the IMPUTED excess DV01, the share on NULL-fixed_rate legs = {null_excess / excess:.4%}")
print(f"of all capped DV01 post-imputation, the NULL-rate share       = {null_imp_total / all_imp_total:.4%}")
print(f"of ALL tape DV01 post-imputation, the unclassifiable share    = "
      f"{(null_all + null_excess) / (tot_d + excess):.4%}")
print(f"  (capped+NULL legs: {int(mult.loc[null_rows, 'n'].sum()):,};  "
      f"their DV01 at the cap {float(mult.loc[null_rows, 'dv01_proxy'].sum()):,.5g}, "
      f"imputed {null_imp_total:,.5g})")

print("\n-- per coarse tenor bucket: imputed DV01 and how much of it is unclassifiable --")
bucket = q(f"""
SELECT CASE WHEN as_of_date < DATE '2024-10-07' THEN 'V1' ELSE 'V2' END vintage,
       CASE WHEN tenor_years < 2 THEN '1. <=2y'
            WHEN tenor_years < 10 THEN '2. 2-10y'
            WHEN tenor_years < 30 THEN '3. 10-30y'
            ELSE '4. >30y' END bucket,
       notional, (fixed_rate IS NULL) AS rate_null, count(*) n,
       sum(notional * tenor_years * 1e-4) dv01_proxy
FROM {LEGS_TABLE}
WHERE {FLOW} AND is_capped AND tenor_years > 0 AND notional > 0 AND notional < 1e11
GROUP BY 1, 2, 3, 4
""")
bucket["dv01_proxy"] = bucket["dv01_proxy"].astype(float)
bucket["factor"] = [imp._BY_CAP[(v, float(n))].multiplier
                    if (v, float(n)) in imp._BY_CAP else 1.0
                    for v, n in zip(bucket["vintage"], bucket["notional"])]
bucket["excess"] = bucket["dv01_proxy"] * (bucket["factor"] - 1.0)
b1 = bucket.groupby("bucket").agg(n_cap=("n", "sum"), excess=("excess", "sum"))
b2 = bucket[bucket.rate_null].groupby("bucket").agg(n_null=("n", "sum"),
                                                    excess_null=("excess", "sum"))
B = b1.join(b2, how="left").fillna(0.0)
B["null_share_of_imputed"] = B["excess_null"] / B["excess"]
print(B.to_string(float_format=lambda v: f"{v:,.5g}"))

print("\n" + "=" * 104)
print("C. COVERAGE: legs the shipped lookup imputes vs legs the fit was built on")
print("=" * 104)
by_cap = (mult[matched].groupby(["vintage", "notional"])["n"].sum().reset_index()
          .rename(columns={"notional": "cap", "n": "n_tape"}))
frozen = pd.DataFrame([{"vintage": b.vintage, "cap": b.cap, "label": b.label,
                        "n_fit": b.n_capped} for b in imp.CAP_BANDS])
m = frozen.merge(by_cap, on=["vintage", "cap"], how="outer").fillna(0)
m["delta"] = m["n_tape"] - m["n_fit"]
print(m.to_string(index=False))
print(f"\ncapped legs imputed by the shipped lookup: {int(m['n_tape'].sum()):,}")
print(f"capped legs the fit was calibrated on    : {int(m['n_fit'].sum()):,}")
print(f"widening: {m['n_tape'].sum() / m['n_fit'].sum() - 1:+.2%} "
      "(tenor-band gaps and edge fuzz that the fit's tenor keying dropped)")

agree = q(f"""
SELECT count(*) n FROM {LEGS_TABLE}
WHERE {FLOW} AND is_capped AND tenor_years > 0 AND notional > 0 AND notional < 1e11
""")
print(f"\ncapped flow legs with a usable tenor and notional: {int(agree.n[0]):,}")
conn.close()
