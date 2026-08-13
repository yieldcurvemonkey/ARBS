"""Pick the pilot window: which days carry PKG-4+ with a package price.

Cheap, SQL-only, one aggregate per as_of_date. Read-only.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
os.environ.setdefault("TMPDIR", "D:/ddnb_cache/tmp")

REPO = r"C:\Users\chris\clee\ARBS-dd"
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import warnings  # noqa: E402

import pandas as pd  # noqa: E402

import psycopg2  # noqa: E402

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE  # noqa: E402
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

START, END = sys.argv[1], sys.argv[2]

SQL = f"""
WITH grp AS (
  SELECT as_of_date,
         COALESCE(package_id, trade_id) AS g,
         COUNT(*) AS n_legs,
         MAX(ABS(COALESCE(package_transaction_price, 0))) AS ptp,
         SUM(ABS(COALESCE(other_payment_amount, 0))) AS opa,
         SUM(ABS(COALESCE(other_payment_ufro, 0))
             + ABS(COALESCE(other_payment_uwin, 0))) AS fee,
         BOOL_OR(lifecycle_type IS DISTINCT FROM 'NEW_TRADE') AS lifecycle,
         COUNT(DISTINCT platform_identifier) AS n_plat,
         MIN(platform_identifier) AS plat
  FROM {LEGS_TABLE}
  WHERE as_of_date BETWEEN %(a)s AND %(b)s
  GROUP BY 1, 2
)
SELECT as_of_date,
       COUNT(*) AS n_units,
       SUM(n_legs) AS n_legs,
       COUNT(*) FILTER (WHERE n_legs >= 4) AS pkg4,
       COUNT(*) FILTER (WHERE n_legs >= 4 AND ptp > 0) AS pkg4_with_ptp,
       COUNT(*) FILTER (WHERE n_legs >= 4 AND ptp > 0 AND opa > 0)
           AS pkg4_ptp_opa,
       COUNT(*) FILTER (WHERE n_legs BETWEEN 2 AND 3) AS multileg_2_3,
       COUNT(*) FILTER (WHERE ptp > 0 OR fee > 0) AS upfrontish,
       COUNT(*) FILTER (WHERE lifecycle) AS lifecycle_units,
       COUNT(DISTINCT plat) AS n_platforms
FROM grp
GROUP BY 1
ORDER BY 1
"""

conn = psycopg2.connect(resolve_pg_url())
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    df = pd.read_sql(SQL, conn, params={"a": START, "b": END})
conn.close()

pd.set_option("display.width", 250)
print(df.to_string(index=False))
print()
print("TOTALS:")
print(df.drop(columns=["as_of_date"]).sum().to_string())
