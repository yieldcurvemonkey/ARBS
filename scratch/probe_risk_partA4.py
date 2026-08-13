"""Part A supplement 3: forward-start-aware expected DV01, and the residual failures."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 300)
pd.set_option("display.max_rows", 500)
pd.set_option("display.max_columns", 60)
pd.set_option("display.float_format", lambda v: f"{v:,.6g}")

conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def show(title, df):
    print(f"\n===== {title} =====")
    print(df.to_string())


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"
F = "coalesce(forward_start_years, 0)"
# expected DV01 per unit notional, forward-start aware, flat y = 4%
EXP = f"(notional * ((1-exp(-0.04*({F}+tenor_years)))/0.04 - (1-exp(-0.04*{F}))/0.04) * 1e-4)"
RR = f"(abs(risk) / {EXP})"

BASE = (f"{FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0 "
        f"AND {EXP} > 0")

show("X1. forward-start-aware r'' percentiles (all flow, incl. risk=0)", q(f"""
SELECT count(*) n,
  percentile_cont(0.0001) WITHIN GROUP (ORDER BY {RR}) p0001,
  percentile_cont(0.001) WITHIN GROUP (ORDER BY {RR}) p001,
  percentile_cont(0.01)  WITHIN GROUP (ORDER BY {RR}) p01,
  percentile_cont(0.05)  WITHIN GROUP (ORDER BY {RR}) p05,
  percentile_cont(0.50)  WITHIN GROUP (ORDER BY {RR}) p50,
  percentile_cont(0.95)  WITHIN GROUP (ORDER BY {RR}) p95,
  percentile_cont(0.99)  WITHIN GROUP (ORDER BY {RR}) p99,
  percentile_cont(0.999) WITHIN GROUP (ORDER BY {RR}) p999,
  percentile_cont(0.9999) WITHIN GROUP (ORDER BY {RR}) p9999,
  max({RR}) mx
FROM {LEGS_TABLE} WHERE {BASE} AND risk <> 0
"""))

show("X2. r'' median by tenor band and forward-start", q(f"""
SELECT CASE WHEN tenor_years<0.5 THEN '1. <6m' WHEN tenor_years<1 THEN '2. 6m-1y'
            WHEN tenor_years<5 THEN '3. 1-5y' WHEN tenor_years<15 THEN '4. 5-15y'
            WHEN tenor_years<25 THEN '5. 15-25y' ELSE '6. >25y' END tb,
       ({F} > 0.02) is_fwd, count(*) n,
       percentile_cont(0.001) WITHIN GROUP (ORDER BY {RR}) p001,
       percentile_cont(0.5)   WITHIN GROUP (ORDER BY {RR}) p50,
       percentile_cont(0.999) WITHIN GROUP (ORDER BY {RR}) p999
FROM {LEGS_TABLE} WHERE {BASE} AND risk <> 0
GROUP BY 1,2 ORDER BY 1,2
"""))

show("X3. residual failures of the band, with the $100 quantisation allowance", q(f"""
SELECT count(*) n_total,
  count(*) FILTER (WHERE abs(risk) > 2.0*{EXP} + 100)                     n_hi_raw,
  count(*) FILTER (WHERE abs(risk) < 0.5*{EXP} - 100)                     n_lo_raw,
  count(*) FILTER (WHERE risk = 0 AND {EXP} > 300)                        n_zero_material,
  count(*) FILTER (WHERE risk = 0)                                        n_zero
FROM {LEGS_TABLE} WHERE {BASE}
"""))

show("X4. the remaining hi failures", q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, {F} fwd, fixed_rate, risk,
       platform_identifier, rate_index_clean, is_capped, {EXP} exp_dv01, {RR} rr
FROM {LEGS_TABLE} WHERE {BASE} AND abs(risk) > 2.0*{EXP} + 100
ORDER BY {RR} DESC LIMIT 20
"""))

show("X5. the remaining lo failures (largest expected dv01)", q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, {F} fwd, fixed_rate, risk,
       platform_identifier, rate_index_clean, is_capped, cap_band_violation,
       {EXP} exp_dv01, {RR} rr
FROM {LEGS_TABLE} WHERE {BASE} AND abs(risk) < 0.5*{EXP} - 100
ORDER BY {EXP} DESC LIMIT 20
"""))

show("X6. lo failures: characterise", q(f"""
SELECT is_capped, cap_band_violation, ({F}>0.02) is_fwd, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY {RR}) med_rr
FROM {LEGS_TABLE} WHERE {BASE} AND abs(risk) < 0.5*{EXP} - 100
GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 15
"""))

show("X7. risk=0 rows: material or immaterial?", q(f"""
SELECT CASE WHEN {EXP} < 100 THEN 'a. exp<100 (below quantisation)'
            WHEN {EXP} < 300 THEN 'b. 100-300'
            WHEN {EXP} < 1000 THEN 'c. 300-1000'
            ELSE 'd. >1000' END band, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor
FROM {LEGS_TABLE} WHERE {BASE} AND risk = 0 GROUP BY 1 ORDER BY 1
"""))

show("X8. sentinel rows under r''", q(f"""
SELECT trade_id, notional, tenor_years, {F} fwd, risk, {EXP} exp_dv01, {RR} rr
FROM {LEGS_TABLE} WHERE notional >= 1e11 ORDER BY abs(risk) DESC LIMIT 4
"""))

show("X9. cap_band_violation overall (flow)", q(f"""
SELECT cap_band_violation, is_capped, count(*) n FROM {LEGS_TABLE} WHERE {FLOW}
GROUP BY 1,2 ORDER BY 3 DESC
"""))

conn.close()
