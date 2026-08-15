import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
for t in ('arbs_dd_unit_v1', 'arbs_usd_swap_tape_legs_v3', 'arbs_dd_curve_mid_v1'):
    cur.execute("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_name = %s ORDER BY ordinal_position
    """, (t,))
    rows = cur.fetchall()
    print('=' * 70)
    print(t, len(rows), 'cols')
    print('; '.join(f'{c}:{d}' for c, d in rows))
conn.close()
