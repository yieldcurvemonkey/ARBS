import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

print("LEGS_TABLE =", LEGS_TABLE)
q = f"""
select
  count(*)                                                        as legs,
  count(distinct as_of_date)                                      as days,
  count(distinct date_trunc('minute', execution_timestamp))       as distinct_exec_minutes,
  count(distinct (as_of_date, rate_index_clean))                        as day_index_pairs,
  count(*) filter (where effective_date > as_of_date + 3)         as forward_start,
  count(*) filter (where effective_date < as_of_date - 3)         as past_start,
  count(*) filter (where effective_date between as_of_date - 3 and as_of_date + 3) as spot_start,
  count(*) filter (where expiration_date > as_of_date + 3670)     as beyond_10y,
  count(*) filter (where expiration_date > as_of_date + 7300)     as beyond_20y,
  max(expiration_date - as_of_date)                               as max_days
from {LEGS_TABLE}
"""
with psycopg2.connect(resolve_pg_url()) as cn, cn.cursor() as cur:
    cur.execute("set local statement_timeout = '600s'")
    cur.execute(q)
    cols = [d[0] for d in cur.description]
    print(dict(zip(cols, cur.fetchone())))

    cur.execute(f"""
      select rate_index_clean, count(*) from {LEGS_TABLE} group by 1 order by 2 desc limit 12
    """)
    print("rate_index:", cur.fetchall())

    cur.execute(f"""
      select width_bucket((expiration_date - effective_date)/365.25, 0, 51, 17) as b,
             min((expiration_date-effective_date)/365.25) as lo,
             max((expiration_date-effective_date)/365.25) as hi,
             count(*)
      from {LEGS_TABLE} group by 1 order by 1
    """)
    print("tenor histogram (years, 3y bins):")
    for r in cur.fetchall():
        print("   ", r)

    # distinct curve minutes actually needed: one per (rate_index_clean, snap minute)
    cur.execute(f"""
      select count(*) from (
        select distinct rate_index_clean, date_trunc('minute', execution_timestamp)
        from {LEGS_TABLE}
      ) t
    """)
    print("distinct (rate_index_clean, exec-minute) pairs:", cur.fetchone()[0])

    cur.execute(f"""
      select count(*) from (
        select distinct effective_date, expiration_date from {LEGS_TABLE}
      ) t
    """)
    print("distinct (effective_date, expiration_date) schedule pairs:", cur.fetchone()[0])
