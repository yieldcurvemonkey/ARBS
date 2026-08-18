import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2, pandas as pd
conn = psycopg2.connect(resolve_pg_url())
print(pd.read_sql("""
with pub as (select as_of_date from arbs_dd_unit_v1 group by 1 order by 1 desc limit 60)
select count(*) legs,
       count(*) filter (where l.tenor_display is null) null_display,
       count(*) filter (where l.effective_date is null) null_eff,
       count(*) filter (where l.expiration_date is null) null_exp,
       count(*) filter (where l.trade_type is null) null_tt
from arbs_dd_unit_v1 u
join arbs_usd_swap_tape_legs_v3 l
  on l.package_id=u.package_id and l.as_of_date=u.as_of_date
where u.kind in ('CURVE','FLY') and u.as_of_date in (select as_of_date from pub)
""", conn).to_string())
conn.close()
