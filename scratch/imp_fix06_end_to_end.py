"""Read-only. The corrected calibration through the PUBLIC api, on the real tape.

Same shape as imp10_end_to_end.py, re-run because the calibration changed: the
leg-by-leg headline (68,945 capped legs keyed on notional, against the 67,619
the fit was calibrated on) is a docstring number and it moves with the fit.
Also re-checks the renamed reporting-only column and that no capped leg is
silently skipped.
"""
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

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
        SELECT as_of_date, tenor_years, notional, is_capped
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
assert "notional_expected" not in out.columns, "the unmarked column is back"
print("notional passed through bit-identical, no unmarked expected column: OK")

reasons = out["notional_impute_reason"].value_counts()
print("\ndecisions on the capped population:")
print(reasons.to_string())
assert reasons.sum() == len(out), "a leg got no decision"
assert imp.REASON_NOT_CAPPED not in reasons.index
assert out.loc[out["notional_imputed"], "notional_impute_factor"].gt(1.0).all()
assert out.loc[~out["notional_imputed"], "notional_impute_factor"].isna().all()

out["dv01"] = out["notional"] * out["tenor_years"] * 1e-4
out["excess"] = ((out["notional_expected_reporting_only"].fillna(out["notional"])
                  - out["notional"]) * out["tenor_years"] * 1e-4)
obs = denom["dv01"].sum() + out["dv01"].sum()
exc = out["excess"].sum()
print(f"\nobserved DV01 proxy (all flow legs) {obs:,.5g}")
print(f"imputed excess DV01                 {exc:,.5g}")
print(f"imputed share of the total          {exc / (obs + exc):.4%}")
print(f"capped-at-print DV01 share          {out['dv01'].sum() / obs:.4%}")
print(f"DV01-weighted effective multiplier  {1 + exc / out['dv01'].sum():.4f}")

deg = {(b.vintage, b.cap) for b in imp.CAP_BANDS if b.ln_degenerate}
v = out["as_of_date"].map(imp.vintage_for)
is_deg = [(vi, n) in deg for vi, n in zip(v, out["notional"])]
print(f"share of the imputed excess from bound-determined cells: "
      f"{out.loc[is_deg, 'excess'].sum() / exc:.4f}")


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
