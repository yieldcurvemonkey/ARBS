"""Read-only: close the gaps in the empirically-derived cap schedule.

The merged bands in partB_cap_schedule.json have holes (V1 10.5-10.75) and
open right ends (V1 >41y, V2 >45y) because the merge dropped bins with n<25.
A production lookup has to be TOTAL over tenor, so measure what cap actually
applies in the holes instead of guessing an edge.
"""
import os, sys, warnings
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300)
conn = psycopg2.connect(resolve_pg_url())
def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)

FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"
SW = "DATE '2024-10-07'"

print("== G1. capped prints in the V1 10.5-10.75 hole ==")
print(q(f"""SELECT notional, count(*) n, min(tenor_years) lo_t, max(tenor_years) hi_t
  FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND as_of_date < {SW}
    AND tenor_years >= 10.4 AND tenor_years < 11.2 GROUP BY 1 ORDER BY 2 DESC""").to_string(index=False))

print("\n== G2. capped prints at the long end, per vintage ==")
print(q(f"""SELECT CASE WHEN as_of_date < {SW} THEN 'V1' ELSE 'V2' END v, notional,
  count(*) n, min(tenor_years) lo_t, max(tenor_years) hi_t
  FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped AND tenor_years >= 30.5
  GROUP BY 1,2 ORDER BY 1, 3 DESC""").to_string(index=False))

print("\n== G3. max tenor on the flow tape, capped and not ==")
print(q(f"""SELECT is_capped, count(*) n, max(tenor_years) max_t,
  count(*) FILTER (WHERE tenor_years >= 41) n_ge41, count(*) FILTER (WHERE tenor_years >= 45) n_ge45
  FROM {LEGS_TABLE} WHERE {FLOW} AND tenor_years > 0 GROUP BY 1""").to_string(index=False))

print("\n== G4. does every capped print's notional match one of its vintage's 9 caps? ==")
V1 = "(6400000000,2100000000,1200000000,1100000000,460000000,240000000,170000000,120000000,75000000)"
V2 = "(17000000000,7500000000,2000000000,1700000000,1100000000,650000000,470000000,250000000,160000000)"
print(q(f"""SELECT CASE WHEN as_of_date < {SW} THEN 'V1' ELSE 'V2' END v, count(*) n,
  count(*) FILTER (WHERE (as_of_date <  {SW} AND notional IN {V1})
                      OR (as_of_date >= {SW} AND notional IN {V2})) n_match
  FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped GROUP BY 1""").to_string(index=False))

print("\n== G5. the capped prints that match NO schedule value ==")
print(q(f"""SELECT CASE WHEN as_of_date < {SW} THEN 'V1' ELSE 'V2' END v, notional, count(*) n,
  min(tenor_years) lo_t, max(tenor_years) hi_t, min(as_of_date) d0, max(as_of_date) d1
  FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped
   AND NOT ((as_of_date <  {SW} AND notional IN {V1}) OR (as_of_date >= {SW} AND notional IN {V2}))
  GROUP BY 1,2 ORDER BY 3 DESC LIMIT 25""").to_string(index=False))

print("\n== G6. for matched prints, does the notional-implied band agree with the tenor band? ==")
print(q(f"""SELECT CASE WHEN as_of_date < {SW} THEN 'V1' ELSE 'V2' END v,
  count(*) n, count(*) FILTER (WHERE tenor_years IS NULL OR tenor_years<=0) n_no_tenor
  FROM {LEGS_TABLE} WHERE {FLOW} AND is_capped GROUP BY 1""").to_string(index=False))
conn.close()
