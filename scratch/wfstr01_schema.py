import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()

for tbl in ('arbs_dd_unit_v1', 'arbs_usd_swap_tape_legs_v3', 'arbs_dd_curve_mid_v1'):
    cur.execute("""
        SELECT ordinal_position, column_name, data_type
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
    """, (tbl,))
    rows = cur.fetchall()
    print(f"\n=== {tbl} ({len(rows)} cols) ===")
    for r in rows:
        print(f"  {r[0]:3d}  {r[1]:<38s} {r[2]}")

conn.close()
