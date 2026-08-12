"""Orientation probe 2: is the defect in `risk` or in `notional`? And cap granularity."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 260)
pd.set_option("display.max_rows", 400)
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

show("N1. notional magnitude histogram (flow), log10 bucket", q(f"""
SELECT floor(log(notional))::int lg, count(*) n, min(notional) lo, max(notional) hi,
       sum(abs(risk)) dv01
FROM {LEGS_TABLE} WHERE {FLOW} AND notional > 0
GROUP BY 1 ORDER BY 1
"""))

show("N2. rows with notional >= 1e11 (flow): what are they?", q(f"""
SELECT notional, count(*) n, count(distinct as_of_date) days,
       min(as_of_date) lo, max(as_of_date) hi,
       count(*) FILTER (WHERE rate_index_clean='FED_FUNDS') n_ff,
       count(*) FILTER (WHERE rate_index_clean='SOFR') n_sofr,
       sum(abs(risk)) dv01
FROM {LEGS_TABLE} WHERE {FLOW} AND notional >= 1e11
GROUP BY 1 ORDER BY 2 DESC LIMIT 20
"""))

show("N3. does the sentinel exist outside ECONOMIC_FLOW too?", q(f"""
SELECT economic_class, contributes_to_flow, count(*) n
FROM {LEGS_TABLE} WHERE notional >= 1e11 GROUP BY 1,2 ORDER BY 3 DESC
"""))

show("N4. sentinel rows by platform / trade_type / venue", q(f"""
SELECT platform_identifier, venue, trade_type, rate_index_clean, is_off_market,
       count(*) n, min(fixed_rate) lo_r, max(fixed_rate) hi_r
FROM {LEGS_TABLE} WHERE notional >= 1e11
GROUP BY 1,2,3,4,5 ORDER BY 6 DESC LIMIT 30
"""))

show("N5. sentinel rows by as_of_date", q(f"""
SELECT as_of_date, count(*) n, sum(abs(risk)) dv01
FROM {LEGS_TABLE} WHERE notional >= 1e11
GROUP BY 1 ORDER BY 1
"""))

show("N6. fixed_rate = 9.9 sentinel?  fixed_rate distribution extremes (flow)", q(f"""
SELECT fixed_rate, count(*) n, min(notional) lo_n, max(notional) hi_n,
       count(distinct as_of_date) days
FROM {LEGS_TABLE} WHERE {FLOW} AND (fixed_rate > 0.30 OR fixed_rate < -0.10)
GROUP BY 1 ORDER BY 2 DESC LIMIT 30
"""))

show("N7. quality_flags / cap_band_violation / missing_required_fields on sentinel rows", q(f"""
SELECT quality_flags::text qf, cap_band_violation, missing_required_fields::text mrf,
       off_market_reason, count(*) n
FROM {LEGS_TABLE} WHERE notional >= 1e11
GROUP BY 1,2,3,4 ORDER BY 5 DESC LIMIT 20
"""))

# --- cap granularity -------------------------------------------------------
show("C1. distinct cap notional values x tenor range x rate index", q(f"""
SELECT notional cap_value, rate_index_clean, count(*) n,
       min(tenor_years) lo_t, max(tenor_years) hi_t,
       percentile_cont(0.01) WITHIN GROUP (ORDER BY tenor_years) p01_t,
       percentile_cont(0.99) WITHIN GROUP (ORDER BY tenor_years) p99_t
FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND tenor_years IS NOT NULL
GROUP BY 1,2 ORDER BY 2, 4
"""))

show("C2. modal cap by fine tenor bucket (SOFR only)", q(f"""
WITH b AS (
  SELECT CASE
    WHEN tenor_years < 0.126 THEN '01. <46d'
    WHEN tenor_years < 0.22  THEN '02. 46d-3m'
    WHEN tenor_years < 0.47  THEN '03. 3m-6m'
    WHEN tenor_years < 0.97  THEN '04. 6m-1y'
    WHEN tenor_years < 2.02  THEN '05. 1y-2y'
    WHEN tenor_years < 3.02  THEN '06. 2y-3y'
    WHEN tenor_years < 5.02  THEN '07. 3y-5y'
    WHEN tenor_years < 10.02 THEN '08. 5y-10y'
    WHEN tenor_years < 15.02 THEN '09. 10y-15y'
    WHEN tenor_years < 20.02 THEN '10. 15y-20y'
    WHEN tenor_years < 30.02 THEN '11. 20y-30y'
    ELSE '12. >30y' END bucket, notional, rate_index_clean
  FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND tenor_years IS NOT NULL
)
SELECT bucket, rate_index_clean, notional, count(*) n
FROM b GROUP BY 1,2,3 ORDER BY 1,2,4 DESC
"""))

conn.close()
