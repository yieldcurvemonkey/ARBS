"""Read-only. End-to-end through the PUBLIC api, on the real tape.

Everything so far went through internals (imp._BY_CAP) or a cached frequency
table. This runs the whole capped population through impute_frame() -- the
function a caller would actually use -- and checks that:

  * every capped leg gets a decision and none is silently skipped;
  * `notional` comes back bit-identical;
  * the aggregate imputed DV01 share matches the number measured by the other
    code path (15.65%), which is the point of running it a second way;
  * the tenor key and the notional key agree, and where they do not, how often.

The uncapped population enters only as the denominator, so it is aggregated in
SQL rather than pulled: a 2.29M-row select over the pooler dies mid-read.
"""
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import imputation as imp

pd.set_option("display.width", 220)
SANE = ("economic_class = 'ECONOMIC_FLOW' AND contributes_to_flow "
        "AND tenor_years > 0 AND notional > 0 AND notional < 1e11")
BUCKET = ("CASE WHEN tenor_years < 2 THEN '1. <=2y' "
          "WHEN tenor_years < 10 THEN '2. 2-10y' "
          "WHEN tenor_years < 30 THEN '3. 10-30y' ELSE '4. >30y' END")

conn = psycopg2.connect(resolve_pg_url())
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    legs = pd.read_sql(f"""
        SELECT as_of_date, tenor_years, notional, is_capped,
               (fixed_rate IS NULL) AS rate_null
        FROM {LEGS_TABLE} WHERE {SANE} AND is_capped""", conn)
    denom = pd.read_sql(f"""
        SELECT {BUCKET} AS bucket, count(*) n,
               sum(notional * tenor_years * 1e-4) dv01
        FROM {LEGS_TABLE} WHERE {SANE} AND NOT is_capped GROUP BY 1""", conn)
conn.close()
legs["notional"] = legs["notional"].astype(float)
legs["tenor_years"] = legs["tenor_years"].astype(float)
legs["is_capped"] = legs["is_capped"].astype(bool)
denom["dv01"] = denom["dv01"].astype(float)
print(f"capped flow legs: {len(legs):,}   uncapped DV01 proxy: {denom.dv01.sum():,.5g}")

before = legs["notional"].copy()
out = imp.impute_frame(legs)
assert out["notional"].equals(before), "impute_frame edited notional"
print("notional passed through bit-identical: OK")

reasons = out["notional_impute_reason"].value_counts()
print("\ndecisions on the capped population:")
print(reasons.to_string())
assert reasons.sum() == len(out), "a leg got no decision"
assert imp.REASON_NOT_CAPPED not in reasons.index
assert out.loc[out["notional_imputed"], "notional_impute_factor"].gt(1.0).all()
assert out.loc[~out["notional_imputed"], "notional_impute_factor"].isna().all()
print("every capped leg decided, every factor > 1, every non-imputed factor NaN: OK")

out["dv01"] = out["notional"] * out["tenor_years"] * 1e-4
out["excess"] = ((out["notional_expected"].fillna(out["notional"]) - out["notional"])
                 * out["tenor_years"] * 1e-4)
obs = denom["dv01"].sum() + out["dv01"].sum()
exc = out["excess"].sum()
print(f"\nobserved DV01 proxy (all flow legs) {obs:,.5g}")
print(f"imputed excess DV01                 {exc:,.5g}")
print(f"imputed share of the total          {exc / (obs + exc):.4%}")


def coarse(t):
    return ("1. <=2y" if t < 2 else "2. 2-10y" if t < 10
            else "3. 10-30y" if t < 30 else "4. >30y")


out["bucket"] = out["tenor_years"].map(coarse)
B = out.groupby("bucket").agg(n_cap=("dv01", "size"),
                              cap_dv01=("dv01", "sum"), excess=("excess", "sum"))
B = B.join(denom.set_index("bucket")[["dv01"]].rename(columns={"dv01": "uncapped_dv01"}))
B["observed"] = B["cap_dv01"] + B["uncapped_dv01"]
B["imputed_share"] = B["excess"] / (B["observed"] + B["excess"])
print("\nper coarse tenor bucket (bucketed on the leg's own tenor):")
print(B[["n_cap", "observed", "excess", "imputed_share"]].to_string(
    float_format=lambda v: f"{v:,.5g}"))

cap = out[out["notional_imputed"]]
agree = pd.Series([imp.tenor_band_agrees(n, t, d)
                   for n, t, d in zip(cap["notional"], cap["tenor_years"],
                                      cap["as_of_date"])])
print(f"\ncapped legs where the tenor band and the notional band agree: "
      f"{int(agree.sum()):,} of {len(agree):,} ({agree.mean():.4%})")
dis = cap[~agree.to_numpy()]
if len(dis):
    print("the disagreements, by cap value:")
    print(dis.groupby("notional").agg(n=("tenor_years", "size"),
                                      lo_t=("tenor_years", "min"),
                                      hi_t=("tenor_years", "max")).to_string())
