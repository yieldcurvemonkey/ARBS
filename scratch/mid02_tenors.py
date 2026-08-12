"""MEASUREMENT 1 -- what actually trades, so the grid is the traded set.

All aggregation in SQL: the legs table is 2.3M rows behind a pooler and a raw
read is the statement-timeout trap. Every query is bounded to the window.

`risk` is NEVER summed unfiltered -- the spec's 1e20 "value not available"
sentinel dominates any aggregate that includes it (dd schema docstring).
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
import pathlib
import sys
import warnings

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

warnings.simplefilter("ignore")
pd.set_option("display.max_rows", 300)
pd.set_option("display.width", 200)

S, E = "2026-01-01", "2026-08-07"
conn = psycopg2.connect(resolve_pg_url())
P = {"s": S, "e": E}


def q(sql, **kw):
    return pd.read_sql(sql, conn, params={**P, **kw})


print("=" * 78)
print(f"WINDOW {S} .. {E}   table {LEGS_TABLE}")
print("=" * 78)

print("\n--- A. economic_class x contributes_to_flow x rate_index_clean")
print(q(f"""
SELECT economic_class, contributes_to_flow, rate_index_clean, count(*) n
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s
GROUP BY 1,2,3 ORDER BY n DESC LIMIT 30
""").to_string())

print("\n--- B. risk sentinel census (ECONOMIC_FLOW)")
print(q(f"""
SELECT rate_index_clean,
       count(*) n,
       count(*) FILTER (WHERE risk IS NULL) n_null,
       count(*) FILTER (WHERE abs(risk) >= 1e12) n_sentinel,
       max(abs(risk)) FILTER (WHERE abs(risk) < 1e12) max_sane
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s AND economic_class = 'ECONOMIC_FLOW'
GROUP BY 1 ORDER BY n DESC
""").to_string())

print("\n--- C. special_tenor_type, ECONOMIC_FLOW, by index")
print(q(f"""
SELECT rate_index_clean, special_tenor_type, count(*) n,
       round(sum(abs(risk)) FILTER (WHERE abs(risk) < 1e12)) risk_abs
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s AND economic_class = 'ECONOMIC_FLOW'
GROUP BY 1,2 ORDER BY 1, n DESC
""").to_string())

for idx in ("SOFR", "FED_FUNDS"):
    print(f"\n{'='*78}\n--- D. {idx}: tenor_label, ALL ECONOMIC_FLOW legs")
    print(q(f"""
SELECT tenor_label, count(*) n,
       round(sum(abs(risk)) FILTER (WHERE abs(risk) < 1e12)) risk_abs,
       count(*) FILTER (WHERE special_tenor_type = 'STANDARD') n_std,
       count(*) FILTER (WHERE forward_start_years IS NULL
                           OR abs(forward_start_years) < 0.02) n_spot
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s AND economic_class = 'ECONOMIC_FLOW'
  AND rate_index_clean = %(i)s
GROUP BY 1 ORDER BY n DESC LIMIT 60
""", i=idx).to_string())

    print(f"\n--- E. {idx}: tenor_label, SPOT-START + STANDARD only")
    print(q(f"""
SELECT tenor_label, count(*) n,
       round(sum(abs(risk)) FILTER (WHERE abs(risk) < 1e12)) risk_abs,
       count(DISTINCT as_of_date) n_days
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s AND economic_class = 'ECONOMIC_FLOW'
  AND rate_index_clean = %(i)s
  AND special_tenor_type = 'STANDARD'
  AND (forward_start_years IS NULL OR abs(forward_start_years) < 0.02)
GROUP BY 1 ORDER BY n DESC LIMIT 60
""", i=idx).to_string())

    print(f"\n--- F. {idx}: spot lag  (effective_date - as_of_date), STANDARD spot legs")
    print(q(f"""
SELECT (effective_date - as_of_date) AS cal_days, count(*) n
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s AND economic_class = 'ECONOMIC_FLOW'
  AND rate_index_clean = %(i)s AND special_tenor_type = 'STANDARD'
  AND (forward_start_years IS NULL OR abs(forward_start_years) < 0.02)
  AND effective_date IS NOT NULL
GROUP BY 1 ORDER BY n DESC LIMIT 15
""", i=idx).to_string())

print("\n--- G. SOFR: (expiration - effective) days vs tenor_label, spot STANDARD")
print(q(f"""
SELECT tenor_label,
       count(*) n,
       min(expiration_date - effective_date) d_min,
       round(avg(expiration_date - effective_date)) d_avg,
       max(expiration_date - effective_date) d_max,
       count(DISTINCT (expiration_date - effective_date)) n_distinct
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s AND economic_class = 'ECONOMIC_FLOW'
  AND rate_index_clean = 'SOFR' AND special_tenor_type = 'STANDARD'
  AND (forward_start_years IS NULL OR abs(forward_start_years) < 0.02)
  AND effective_date IS NOT NULL AND expiration_date IS NOT NULL
GROUP BY 1 HAVING count(*) > 200 ORDER BY d_avg
""").to_string())

print("\n--- H. print density by execution_hour_et, ECONOMIC_FLOW spot STANDARD")
print(q(f"""
SELECT execution_hour_et, rate_index_clean, count(*) n
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN %(s)s AND %(e)s AND economic_class = 'ECONOMIC_FLOW'
  AND rate_index_clean IN ('SOFR','FED_FUNDS')
GROUP BY 1,2 ORDER BY 1,2
""").pivot(index="execution_hour_et", columns="rate_index_clean",
           values="n").fillna(0).astype(int).to_string())

conn.close()
