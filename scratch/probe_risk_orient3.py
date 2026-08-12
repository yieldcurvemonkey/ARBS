"""Orientation probe 3: cap-schedule vintage, and the low-ratio tail."""
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
BUCKET = """CASE
    WHEN tenor_years < 0.126 THEN '01. <46d'
    WHEN tenor_years < 0.30  THEN '02. 46d-3m'
    WHEN tenor_years < 0.55  THEN '03. 3m-6m'
    WHEN tenor_years < 1.04  THEN '04. 6m-1y'
    WHEN tenor_years < 2.05  THEN '05. 1y-2y'
    WHEN tenor_years < 3.03  THEN '06. 2y-3y'
    WHEN tenor_years < 5.05  THEN '07. 3y-5y'
    WHEN tenor_years < 10.06 THEN '08. 5y-10y'
    WHEN tenor_years < 15.02 THEN '09. 10y-15y'
    WHEN tenor_years < 20.02 THEN '10. 15y-20y'
    WHEN tenor_years < 30.07 THEN '11. 20y-30y'
    ELSE '12. >30y' END"""

show("V1. cap value x quarter, 5y-10y bucket", q(f"""
SELECT date_trunc('quarter', as_of_date)::date qtr, notional, count(*) n
FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND {BUCKET} = '08. 5y-10y'
GROUP BY 1,2 ORDER BY 1,3 DESC
"""))

show("V2. cap value x quarter, 2y-3y bucket", q(f"""
SELECT date_trunc('quarter', as_of_date)::date qtr, notional, count(*) n
FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND {BUCKET} = '06. 2y-3y'
GROUP BY 1,2 ORDER BY 1,3 DESC
"""))

show("V3. modal cap per (bucket, quarter) -- top-2 per cell", q(f"""
WITH c AS (
  SELECT {BUCKET} bucket, date_trunc('quarter', as_of_date)::date qtr, notional, count(*) n,
         row_number() OVER (PARTITION BY {BUCKET}, date_trunc('quarter', as_of_date)
                            ORDER BY count(*) DESC) rk
  FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND tenor_years IS NOT NULL
  GROUP BY 1,2,3
)
SELECT bucket, qtr, notional, n, rk FROM c WHERE rk <= 2 ORDER BY bucket, qtr, rk
"""))

# --- low scaled-ratio rows -------------------------------------------------
show("L1. scaled ratio r bands (flow, notional>0, tenor>0)", q(f"""
WITH x AS (SELECT (abs(risk)/notional)/(tenor_years*1e-4) r, tenor_years, notional, trade_type,
                  is_off_market, upi_notional_schedule, forward_start_years
           FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0)
SELECT CASE WHEN r = 0 THEN 'a. r=0'
            WHEN r < 0.25 THEN 'b. 0<r<0.25'
            WHEN r < 0.5  THEN 'c. 0.25-0.5'
            WHEN r < 2.0  THEN 'd. 0.5-2 (sane)'
            WHEN r < 5.0  THEN 'e. 2-5'
            ELSE 'f. >=5' END band, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional
FROM x GROUP BY 1 ORDER BY 1
"""))

show("L2. r<0.5 rows: what are they? (tenor bands)", q(f"""
WITH x AS (SELECT (abs(risk)/notional)/(tenor_years*1e-4) r, tenor_years, trade_type,
                  upi_notional_schedule, is_off_market, forward_start_years, is_non_standard_term
           FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0)
SELECT CASE WHEN tenor_years<1 THEN '<1y' WHEN tenor_years<5 THEN '1-5y'
            WHEN tenor_years<15 THEN '5-15y' ELSE '>15y' END tb,
       count(*) n, count(*) FILTER (WHERE r<0.5) n_lo,
       count(*) FILTER (WHERE r=0) n_zero,
       count(*) FILTER (WHERE r>2) n_hi
FROM x GROUP BY 1 ORDER BY 1
"""))

show("L3. upi_notional_schedule vs r", q(f"""
WITH x AS (SELECT (abs(risk)/notional)/(tenor_years*1e-4) r, upi_notional_schedule
           FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0)
SELECT upi_notional_schedule, count(*) n,
       percentile_cont(0.05) WITHIN GROUP (ORDER BY r) p05,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r) p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY r) p95,
       count(*) FILTER (WHERE r < 0.5) n_lo
FROM x GROUP BY 1 ORDER BY 2 DESC LIMIT 15
"""))

show("L4. sample r>2 rows", q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, fixed_rate, risk, platform_identifier,
       trade_type, rate_index_clean, (abs(risk)/notional)/(tenor_years*1e-4) r
FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0
  AND (abs(risk)/notional)/(tenor_years*1e-4) > 1.6
ORDER BY (abs(risk)/notional)/(tenor_years*1e-4) DESC LIMIT 25
"""))

conn.close()
