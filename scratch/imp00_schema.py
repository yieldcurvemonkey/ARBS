"""Read-only: what does the direction table look like, and how does it join?"""
import os, sys, warnings
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
import psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import DIRECTION_TABLE
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

conn = psycopg2.connect(resolve_pg_url()); cur = conn.cursor()
def q(sql):
    cur.execute(sql); return cur.fetchall()

print("== direction table columns ==")
for r in q(f"""SELECT column_name, data_type FROM information_schema.columns
               WHERE table_name='{DIRECTION_TABLE}' ORDER BY ordinal_position"""):
    print(r)
print("\n== span ==")
print(q(f"SELECT count(*), min(as_of_date), max(as_of_date) FROM {DIRECTION_TABLE}"))
print("\n== dealer_direction x method ==")
for r in q(f"""SELECT classification_method, dealer_direction, count(*)
               FROM {DIRECTION_TABLE} GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20"""):
    print(r)
print("\n== legs cols matching cap/block/dir ==")
for r in q(f"""SELECT column_name, data_type FROM information_schema.columns
               WHERE table_name='{LEGS_TABLE}'
                 AND (column_name ILIKE '%cap%' OR column_name ILIKE '%block%'
                      OR column_name ILIKE '%direct%' OR column_name ILIKE '%side%'
                      OR column_name ILIKE '%trade_id%' OR column_name ILIKE '%dissemination%')
               ORDER BY 1"""):
    print(r)
conn.close()
