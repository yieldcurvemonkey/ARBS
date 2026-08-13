import sys, os
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

sql = f"""
select
  count(*)                                                        as n_legs,
  count(*) filter (where effective_date is null)                  as null_eff,
  count(*) filter (where expiration_date is null)                 as null_exp,
  count(*) filter (where notional is null)                        as null_notl,
  count(*) filter (where notional < 0)                            as neg_notl,
  count(*) filter (where effective_date < execution_timestamp::date) as past_start_exec
from {LEGS_TABLE}
"""
with psycopg2.connect(resolve_pg_url()) as c, c.cursor() as cur:
    cur.execute("SET LOCAL statement_timeout = '240s'")
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    print(dict(zip(cols, cur.fetchone())))
