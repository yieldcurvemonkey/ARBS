import os, sys, time
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2
import pandas as pd
pd.set_option('display.width', 260); pd.set_option('display.max_colwidth', 70)
pd.set_option('display.max_rows', 300)
conn = psycopg2.connect(resolve_pg_url())
conn.cursor().execute("set statement_timeout = '280s'")
W = "u.as_of_date >= date '2026-05-13'"


def q(sql, title=""):
    t0 = time.time()
    df = pd.read_sql(sql, conn)
    print(f"--- {title} ({len(df)} rows, {time.time()-t0:.1f}s) ---")
    print(df.to_string())
    print(flush=True)
    return df


q(f"""select u.kind, l.trade_type, count(distinct u.package_id) n
      from arbs_dd_unit_v1 u join arbs_usd_swap_tape_legs_v3 l
        on l.package_id=u.package_id and l.as_of_date=u.as_of_date
      where {W} and u.kind in ('CURVE','FLY')
      group by 1,2 order by 1,3 desc""", "trade_type by kind")

q(f"""with a as (
        select u.package_id, count(distinct l.trade_type) nt
        from arbs_dd_unit_v1 u join arbs_usd_swap_tape_legs_v3 l
          on l.package_id=u.package_id and l.as_of_date=u.as_of_date
        where {W} and u.kind in ('CURVE','FLY') group by 1)
      select nt, count(*) n from a group by 1 order by 1""",
  "distinct trade_type per package (1 = homogeneous)")

# the 'SPREADOVER_CURVE' 10Y/30Y question
q(f"""select l.trade_type, count(distinct u.package_id) n
      from arbs_dd_unit_v1 u join arbs_usd_swap_tape_legs_v3 l
        on l.package_id=u.package_id and l.as_of_date=u.as_of_date
      where {W} and u.kind='CURVE' and u.rate_index='SOFR'
        and u.special_tenor_type='STANDARD'
      group by 1 order by 2 desc""", "trade_type within CURVE/SOFR/STANDARD")

# IMM special_tenor_type but spot legs: what does it look like?
q(f"""select u.special_tenor_type, l.forward_label, l.effective_date, l.expiration_date,
        l.tenor_display, u.package_id, l.trade_type, l.tape_label
      from arbs_dd_unit_v1 u join arbs_usd_swap_tape_legs_v3 l
        on l.package_id=u.package_id and l.as_of_date=u.as_of_date
      where u.as_of_date = date '2026-08-06' and u.kind='FLY'
        and u.special_tenor_type='IMM'
      order by u.package_id, l.leg_order limit 24""",
  "FLY special_tenor_type=IMM sample legs")

conn.close()
