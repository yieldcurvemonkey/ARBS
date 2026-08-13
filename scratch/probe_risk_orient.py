"""Orientation probe: the shape of the corrupt `risk` column and the cap spikes."""
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
pd.set_option("display.max_rows", 300)
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

# --- what units is risk in, on the sane mass? ------------------------------
show("R0. risk column: nulls, zeros, sign", q(f"""
SELECT count(*) n,
       count(risk) n_notnull,
       count(*) FILTER (WHERE risk = 0) n_zero,
       count(*) FILTER (WHERE risk < 0) n_neg,
       count(*) FILTER (WHERE notional IS NULL) n_notional_null,
       count(*) FILTER (WHERE notional = 0) n_notional_zero,
       count(*) FILTER (WHERE tenor_years IS NULL) n_tenor_null
FROM {LEGS_TABLE} WHERE {FLOW}
"""))

show("R1. top 50 by abs(risk)", q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, fixed_rate, risk,
       platform_identifier, trade_type, rate_index_clean, venue, is_capped, is_block,
       economic_class, lifecycle_type
FROM {LEGS_TABLE}
ORDER BY abs(risk) DESC NULLS LAST
LIMIT 50
"""))

show("R2. ratio percentiles over ALL flow legs (notional>0, tenor>0)", q(f"""
SELECT count(*) n,
  percentile_cont(0.001) WITHIN GROUP (ORDER BY abs(risk)/notional) p001,
  percentile_cont(0.01)  WITHIN GROUP (ORDER BY abs(risk)/notional) p01,
  percentile_cont(0.05)  WITHIN GROUP (ORDER BY abs(risk)/notional) p05,
  percentile_cont(0.25)  WITHIN GROUP (ORDER BY abs(risk)/notional) p25,
  percentile_cont(0.50)  WITHIN GROUP (ORDER BY abs(risk)/notional) p50,
  percentile_cont(0.75)  WITHIN GROUP (ORDER BY abs(risk)/notional) p75,
  percentile_cont(0.95)  WITHIN GROUP (ORDER BY abs(risk)/notional) p95,
  percentile_cont(0.99)  WITHIN GROUP (ORDER BY abs(risk)/notional) p99,
  percentile_cont(0.999) WITHIN GROUP (ORDER BY abs(risk)/notional) p999,
  max(abs(risk)/notional) mx
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional > 0 AND risk IS NOT NULL AND tenor_years > 0
"""))

show("R3. scaled ratio r = (abs(risk)/notional) / (tenor_years*1e-4) percentiles", q(f"""
SELECT count(*) n,
  percentile_cont(0.001) WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p001,
  percentile_cont(0.01)  WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p01,
  percentile_cont(0.05)  WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p05,
  percentile_cont(0.25)  WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p25,
  percentile_cont(0.50)  WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p50,
  percentile_cont(0.75)  WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p75,
  percentile_cont(0.95)  WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p95,
  percentile_cont(0.99)  WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p99,
  percentile_cont(0.9999) WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) p9999,
  max((abs(risk)/notional)/(tenor_years*1e-4)) mx
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional > 0 AND risk IS NOT NULL AND tenor_years > 0
"""))

# --- capped: does notional sit exactly on a discrete value? ---------------
show("B0. is_capped vs is_notional_capped cross-tab (flow)", q(f"""
SELECT is_capped, is_notional_capped, notional_source, count(*) n
FROM {LEGS_TABLE} WHERE {FLOW} GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20
"""))

show("B1. notional_source over ALL rows (not just flow)", q(f"""
SELECT notional_source, count(*) n FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC LIMIT 20
"""))

show("B2. capped rows: top notional values", q(f"""
SELECT notional, count(*) n, min(tenor_years) lo_t, max(tenor_years) hi_t
FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped
GROUP BY 1 ORDER BY 2 DESC LIMIT 30
"""))

show("B3. capped rows: notional by Part43 tenor band", q(f"""
SELECT CASE WHEN tenor_years <= 2 THEN '1. <=2y'
            WHEN tenor_years <= 10 THEN '2. 2-10y'
            WHEN tenor_years <= 30 THEN '3. 10-30y'
            ELSE '4. >30y' END band,
       notional, count(*) n
FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND tenor_years IS NOT NULL
GROUP BY 1,2 ORDER BY 1, 3 DESC
"""))

conn.close()
