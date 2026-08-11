"""Does upi_notional_schedule explain sanity.py's unexplained RISK_VS_NOTIONAL_LOW band?

The LEDGER records 4,878 flow legs with abs(risk) < 0.5*E - 100 and
"mechanism NOT identified". An amortizing swap's `notional` is the INITIAL
notional, so the flat-annuity E over-states its DV01 -- exactly the shape of
that band. The annuity is evaluated in SQL so the whole flow population can be
scanned without pulling 2.3M rows.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 100)

# E = N * (A(f+T) - A(f)) * 1e-4,  A(x) = (1 - exp(-0.04 x)) / 0.04
E = ("notional * ((1 - exp(-0.04*(coalesce(forward_start_years,0)+tenor_years)))/0.04"
     " - (1 - exp(-0.04*coalesce(forward_start_years,0)))/0.04) * 1e-4")
BASE = f"""
  SELECT coalesce(upi_notional_schedule,'(null)') sched,
         coalesce(leg_tape_label,'') LIKE '%%Amortizing%%' lbl_amort,
         is_capped,
         tenor_years,
         abs(risk) < 0.5*({E}) - 100 AS low_band,
         abs(risk) > 2.0*({E}) + 100 AS high_band
  FROM {LEGS_TABLE}
  WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
    AND notional < 1e11 AND notional > 0 AND tenor_years > 0
    AND risk IS NOT NULL AND risk <> 0
    AND ({E}) > 0
"""

conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


print("R1. LOW / HIGH band rate by upi_notional_schedule")
print(q(f"""
    SELECT sched, count(*) n,
           count(*) FILTER (WHERE low_band) n_low,
           round(100.0*count(*) FILTER (WHERE low_band)/count(*), 3) pct_low,
           count(*) FILTER (WHERE high_band) n_high
    FROM ({BASE}) t GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

print()
print("R2. how much of the LOW band is non-Constant notional?")
print(q(f"""
    SELECT count(*) FILTER (WHERE low_band) total_low,
           count(*) FILTER (WHERE low_band AND sched <> 'Constant') low_nonconst,
           count(*) FILTER (WHERE low_band AND lbl_amort) low_lbl_amort,
           count(*) FILTER (WHERE low_band AND is_capped) low_capped,
           count(*) FILTER (WHERE low_band AND sched = 'Constant'
                            AND NOT coalesce(is_capped,false)) low_residual
    FROM ({BASE}) t
""").to_string(index=False))

print()
print("R3. residual LOW (Constant, uncapped) by tenor band")
print(q(f"""
    SELECT CASE WHEN tenor_years < 1 THEN 'a <1y'
                WHEN tenor_years < 2 THEN 'b 1-2y'
                WHEN tenor_years < 5 THEN 'c 2-5y'
                WHEN tenor_years < 10 THEN 'd 5-10y'
                WHEN tenor_years < 30 THEN 'e 10-30y'
                ELSE 'f 30y+' END band,
           count(*) n, count(*) FILTER (WHERE low_band) n_low,
           round(100.0*count(*) FILTER (WHERE low_band)/count(*), 4) pct_low
    FROM ({BASE}) t
    WHERE sched = 'Constant' AND NOT coalesce(is_capped, false)
    GROUP BY 1 ORDER BY 1
""").to_string(index=False))

conn.close()
print("\ndone")
