"""Independent re-measurement of the counts asserted in upfront.py docstrings.

READ ONLY. Checks:
  * "other_payment_uwin > 0 on 15 rows out of 2,326,781 (one a TERMINATION)"
  * "11,583 of 50,752 ECONOMIC_FLOW terminations carry other_payment_ufro"
  * "275,540 flow legs that carry a fee while not being rate outliers"
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 250)


def q(conn, sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


conn = psycopg2.connect(resolve_pg_url())
print("legs table:", LEGS_TABLE)

print("\n[1] total rows / uwin > 0")
print(q(conn, f"""
  SELECT count(*) AS n_rows,
         count(*) FILTER (WHERE other_payment_uwin > 0) AS uwin_pos,
         count(*) FILTER (WHERE other_payment_uwin > 0
                          AND lifecycle_type = 'TERMINATION') AS uwin_termination
  FROM {LEGS_TABLE}""").to_string(index=False))

print("\n[2] terminations by economic_class, and their ufro")
print(q(conn, f"""
  SELECT economic_class, count(*) AS n,
         count(*) FILTER (WHERE other_payment_ufro > 0) AS ufro_pos,
         count(*) FILTER (WHERE other_payment_uwin > 0) AS uwin_pos
  FROM {LEGS_TABLE}
  WHERE lifecycle_type = 'TERMINATION'
  GROUP BY 1 ORDER BY n DESC""").to_string(index=False))

print("\n[3] flow legs with a fee, split by is_off_market")
print(q(conn, f"""
  SELECT is_off_market, count(*) AS n
  FROM {LEGS_TABLE}
  WHERE economic_class = 'ECONOMIC_FLOW' AND other_payment_ufro > 0
  GROUP BY 1 ORDER BY 1""").to_string(index=False))

print("\n[4] how often is other_payment_ufro NULL rather than 0 "
      "(the resolve_upfront NaN path)")
print(q(conn, f"""
  SELECT count(*) AS n,
         count(*) FILTER (WHERE other_payment_ufro IS NULL) AS ufro_null,
         count(*) FILTER (WHERE other_payment_ufro = 0) AS ufro_zero,
         count(*) FILTER (WHERE other_payment_ufro > 0) AS ufro_pos
  FROM {LEGS_TABLE}""").to_string(index=False))

print("\n[5] multi-leg packages where SOME legs have a fee and others are NULL")
print(q(conn, f"""
  WITH p AS (
    SELECT package_id,
           count(*) AS n_legs,
           count(*) FILTER (WHERE other_payment_ufro > 0) AS n_fee,
           count(*) FILTER (WHERE other_payment_ufro IS NULL) AS n_null
    FROM {LEGS_TABLE}
    WHERE package_id IS NOT NULL
    GROUP BY 1)
  SELECT count(*) AS n_packages,
         count(*) FILTER (WHERE n_legs > 1) AS multileg,
         count(*) FILTER (WHERE n_legs > 1 AND n_fee > 0 AND n_null > 0)
           AS multileg_fee_and_null
  FROM p""").to_string(index=False))

print("\n[6] negative other_payment_ufro / uwin anywhere?")
print(q(conn, f"""
  SELECT count(*) FILTER (WHERE other_payment_ufro < 0) AS ufro_neg,
         count(*) FILTER (WHERE other_payment_uwin < 0) AS uwin_neg,
         count(*) FILTER (WHERE other_payment_amount < 0) AS opa_neg
  FROM {LEGS_TABLE}""").to_string(index=False))
conn.close()
