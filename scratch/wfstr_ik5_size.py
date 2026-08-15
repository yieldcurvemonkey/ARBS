import os, sys, time
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
cur.execute("set statement_timeout = '300s'")


def q(sql, params=None, title="", show=200):
    t0 = time.time()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    print(f"--- {title} ({len(rows)} rows, {time.time()-t0:.1f}s) ---")
    print(" | ".join(cols))
    for r in rows[:show]:
        print(" | ".join("" if v is None else str(v) for v in r))
    print(flush=True)
    return rows


q("""select relname, n_live_tup from pg_stat_user_tables
     where relname in ('arbs_dd_unit_v1','arbs_usd_swap_tape_legs_v3','arbs_dd_curve_mid_v1')""",
  None, "row counts (est)")

q("""select indexname, indexdef from pg_indexes
     where tablename in ('arbs_dd_unit_v1','arbs_usd_swap_tape_legs_v3','arbs_dd_curve_mid_v1')
     order by tablename, indexname""", None, "indexes")

conn.close()
