"""FINAL -- the join rule's coverage.

The grid is exact only where the consumer looks it up at
`snapshot.snap_instant(pricing_ts)` -- floor-to-minute-minus-one, ET -- which
is precisely what `arbs_dd_unit_v1.curve_timestamp` already stores. So the
front end joins prints to the grid by EQUALITY on that column, and the
question is what fraction of prints land inside the store's 01:00-22:59 ET
publication window.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
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
pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 60)
conn = psycopg2.connect(resolve_pg_url())

print("--- arbs_dd_unit_v1.curve_timestamp by ET hour (whole table)")
df = pd.read_sql("""
SELECT rate_index,
       extract(hour FROM curve_timestamp AT TIME ZONE 'America/New_York')::int h,
       count(*) n
FROM arbs_dd_unit_v1
WHERE curve_timestamp IS NOT NULL
GROUP BY 1,2 ORDER BY 1,2""", conn)
p = df.pivot(index="h", columns="rate_index", values="n").fillna(0).astype(int)
print(p.to_string())
tot = p.sum()
inside = p.loc[[h for h in p.index if 1 <= h <= 22]].sum()
print("\n  total units with a curve_timestamp:")
print(tot.to_string())
print("  inside the store window 01:00-22:59 ET:")
print((inside / tot * 100).round(2).to_string())

print("\n--- and by second-of-minute: is curve_timestamp always a whole minute?")
print(pd.read_sql("""
SELECT extract(second FROM curve_timestamp)::int s, count(*) n
FROM arbs_dd_unit_v1 WHERE curve_timestamp IS NOT NULL
GROUP BY 1 ORDER BY n DESC LIMIT 5""", conn).to_string())

print("\n--- tape legs (all ECONOMIC_FLOW) by ET execution hour, share outside")
df2 = pd.read_sql(f"""
SELECT rate_index_clean rate_index,
       count(*) n,
       count(*) FILTER (WHERE extract(hour FROM execution_timestamp
             AT TIME ZONE 'America/New_York')::int BETWEEN 1 AND 22) n_in
FROM {LEGS_TABLE}
WHERE economic_class='ECONOMIC_FLOW'
  AND rate_index_clean IN ('SOFR','FED_FUNDS')
GROUP BY 1""", conn)
df2["pct_in"] = (df2["n_in"] / df2["n"] * 100).round(2)
print(df2.to_string())
conn.close()
