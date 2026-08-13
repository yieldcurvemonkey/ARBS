"""Part A supplement: risk granularity, annuity-adjusted ratio, above-cap uncapped rows."""
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

show("G1. risk granularity: is risk rounded to 100?", q(f"""
SELECT count(*) n,
  count(*) FILTER (WHERE risk = round(risk::numeric, 0)::float8)            n_int,
  count(*) FILTER (WHERE mod(round(risk::numeric)::bigint, 100) = 0)        n_mult100,
  count(*) FILTER (WHERE mod(round(risk::numeric)::bigint, 1000) = 0)       n_mult1000,
  min(abs(risk)) FILTER (WHERE risk <> 0)                                   min_nonzero
FROM {LEGS_TABLE} WHERE {FLOW} AND risk IS NOT NULL AND abs(risk) < 1e14
"""))

# Annuity-adjusted ratio: DV01/notional ~ A(T)*1e-4 with A(T)=(1-exp(-y*T))/y
ANN = "((1 - exp(-0.04*tenor_years))/0.04)"
RP = f"(abs(risk)/notional)/({ANN}*1e-4)"

show("G2. annuity-adjusted r' percentiles (y=4%)", q(f"""
SELECT count(*) n,
  percentile_cont(0.0001) WITHIN GROUP (ORDER BY {RP}) p0001,
  percentile_cont(0.001) WITHIN GROUP (ORDER BY {RP}) p001,
  percentile_cont(0.01)  WITHIN GROUP (ORDER BY {RP}) p01,
  percentile_cont(0.05)  WITHIN GROUP (ORDER BY {RP}) p05,
  percentile_cont(0.50)  WITHIN GROUP (ORDER BY {RP}) p50,
  percentile_cont(0.95)  WITHIN GROUP (ORDER BY {RP}) p95,
  percentile_cont(0.99)  WITHIN GROUP (ORDER BY {RP}) p99,
  percentile_cont(0.9999) WITHIN GROUP (ORDER BY {RP}) p9999,
  max({RP}) mx
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0 AND risk<>0
"""))

show("G3. r' median by tenor band (does the annuity fix the long end?)", q(f"""
SELECT CASE WHEN tenor_years<0.5 THEN '1. <6m' WHEN tenor_years<1 THEN '2. 6m-1y'
            WHEN tenor_years<5 THEN '3. 1-5y' WHEN tenor_years<15 THEN '4. 5-15y'
            WHEN tenor_years<25 THEN '5. 15-25y' ELSE '6. >25y' END tb,
       count(*) n,
       percentile_cont(0.001) WITHIN GROUP (ORDER BY {RP}) p001,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY {RP}) p50,
       percentile_cont(0.999) WITHIN GROUP (ORDER BY {RP}) p999,
       count(*) FILTER (WHERE {RP} < 0.5) n_lo,
       count(*) FILTER (WHERE {RP} > 2.0) n_hi
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0 AND risk<>0
GROUP BY 1 ORDER BY 1
"""))

show("G4. rows failing the annuity band [0.5,2] -- who are they?", q(f"""
SELECT CASE WHEN {RP} < 0.5 THEN 'lo' ELSE 'hi' END side,
       count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor,
       count(*) FILTER (WHERE abs(risk) <= 200) n_risk_le200,
       count(*) FILTER (WHERE notional < 1e6) n_small_notional
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0 AND risk<>0
  AND ({RP} < 0.5 OR {RP} > 2.0)
GROUP BY 1
"""))

show("G5. sample of annuity-band failures (lo side, large notional)", q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, fixed_rate, risk, platform_identifier,
       trade_type, rate_index_clean, upi_notional_schedule, schedule_truncated, {RP} rp
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>1e7 AND risk IS NOT NULL AND tenor_years>0 AND risk<>0
  AND {RP} < 0.5
ORDER BY notional DESC LIMIT 15
"""))

show("G6. what does the sentinel look like under r'?", q(f"""
SELECT trade_id, notional, tenor_years, risk, {RP} rp
FROM {LEGS_TABLE} WHERE notional >= 1e11 ORDER BY abs(risk) DESC LIMIT 5
"""))

# --- uncapped rows above the applicable cap --------------------------------
show("U1. uncapped SOFR rows with notional > 1e10 and tenor > 0.5y", q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, fixed_rate, risk, platform_identifier,
       trade_type, rate_index_clean, is_capped, is_block, on_p43, venue
FROM {LEGS_TABLE} WHERE {FLOW} AND notional > 1e10 AND tenor_years > 0.5 AND NOT is_capped
ORDER BY notional DESC LIMIT 20
"""))

show("U2. on_p43 vs is_capped (flow)", q(f"""
SELECT on_p43, is_capped, count(*) n, max(notional) max_notional
FROM {LEGS_TABLE} WHERE {FLOW} GROUP BY 1,2 ORDER BY 3 DESC
"""))

conn.close()
