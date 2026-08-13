"""Part A supplement 2: what is the low-r' class? Implied effective tenor."""
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
ANN = "((1 - exp(-0.04*tenor_years))/0.04)"
RP = f"(abs(risk)/notional)/({ANN}*1e-4)"
# invert A -> effective tenor implied by risk
AIMP = "(abs(risk)/notional/1e-4)"
TEFF = f"(CASE WHEN 0.04*{AIMP} < 0.999 THEN -ln(1 - 0.04*{AIMP})/0.04 ELSE NULL END)"

show("W1. low-r' rows: capped? cap_band_violation? off-market?", q(f"""
SELECT is_capped, cap_band_violation, is_off_market, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY {TEFF}) med_teff
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk<>0 AND risk IS NOT NULL AND tenor_years>0 AND {RP} < 0.5
GROUP BY 1,2,3 ORDER BY 4 DESC
"""))

show("W2. baseline for comparison: all flow rows by is_capped", q(f"""
SELECT is_capped, count(*) n,
       count(*) FILTER (WHERE {RP} < 0.5) n_lo,
       count(*) FILTER (WHERE {RP} > 2.0) n_hi,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY {RP}) med_rp
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk<>0 AND risk IS NOT NULL AND tenor_years>0
GROUP BY 1
"""))

show("W3. low-r' rows: implied effective tenor histogram", q(f"""
SELECT round({TEFF}::numeric, 1) teff, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_stated_tenor
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk<>0 AND risk IS NOT NULL AND tenor_years>0 AND {RP} < 0.5
GROUP BY 1 ORDER BY 2 DESC LIMIT 25
"""))

show("W4. low-r' rows: notional value counts (are they cap values?)", q(f"""
SELECT notional, count(*) n, percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk<>0 AND risk IS NOT NULL AND tenor_years>0 AND {RP} < 0.5
GROUP BY 1 ORDER BY 2 DESC LIMIT 20
"""))

show("W5. low-r' rows by as_of_date quarter and platform", q(f"""
SELECT date_trunc('quarter', as_of_date)::date qtr, count(*) n_lo
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk<>0 AND risk IS NOT NULL AND tenor_years>0 AND {RP} < 0.5
GROUP BY 1 ORDER BY 1
"""))

show("W6. does forward_start explain it? (teff vs tenor - fwd)", q(f"""
SELECT count(*) n,
   count(*) FILTER (WHERE coalesce(forward_start_years,0) > 0.02) n_fwd,
   percentile_cont(0.5) WITHIN GROUP (ORDER BY coalesce(forward_start_years,0)) med_fwd,
   percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor,
   percentile_cont(0.5) WITHIN GROUP (ORDER BY {TEFF}) med_teff,
   count(*) FILTER (WHERE is_mac) n_mac,
   count(*) FILTER (WHERE is_spreadover) n_spr,
   count(*) FILTER (WHERE is_non_standard_term) n_nst,
   count(*) FILTER (WHERE schedule_row_count > 1) n_sched
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk<>0 AND risk IS NOT NULL AND tenor_years>0 AND {RP} < 0.5
"""))

show("W7. tenor_label vs tenor_years for low-r' rows", q(f"""
SELECT tenor_label, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY {TEFF}) med_teff
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND risk<>0 AND risk IS NOT NULL AND tenor_years>0 AND {RP} < 0.5
GROUP BY 1 ORDER BY 2 DESC LIMIT 20
"""))

conn.close()
