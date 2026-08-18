import os, sys, time
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2
import pandas as pd

conn = psycopg2.connect(resolve_pg_url())
conn.cursor().execute("set statement_timeout = '280s'")

SQL = """
with pub as (
  select as_of_date from arbs_dd_unit_v1 group by 1 order by 1 desc limit 60
),
u as (
  select * from arbs_dd_unit_v1
  where as_of_date in (select as_of_date from pub) and kind in ('CURVE','FLY')
)
select
  u.package_id, u.as_of_date, u.kind, u.rate_index, u.venue_class,
  u.special_tenor_type, u.exclusion_reason, u.rule, u.deviation_bps,
  u.execution_timestamp, u.n_legs, u.dealer_direction,
  count(*)                                              as n_joined,
  min(l.trade_type)                                     as trade_type,
  bool_or(coalesce(l.is_mac,false))                     as is_mac,
  bool_or(coalesce(l.matched_ust_maturity,false))       as mm_ust,
  bool_or(l.tenor_display like '~%%')                   as any_fuzzy,
  bool_and(coalesce(l.forward_label,'spot') = 'spot')   as all_spot,
  -- canonical, tilde PRESERVED, forward prefix
  string_agg(upper(coalesce(nullif(l.forward_label,''),'spot')) || ':' || l.tenor_display,
             '/' order by l.effective_date, l.expiration_date, l.trade_id) as tup_fwd_disp,
  -- canonical, tenor_display only (the literal proposal)
  string_agg(l.tenor_display, '/'
             order by l.effective_date, l.expiration_date, l.trade_id)     as tup_disp,
  -- leg_order variant of the same
  string_agg(upper(coalesce(nullif(l.forward_label,''),'spot')) || ':' || l.tenor_display,
             '/' order by l.leg_order)                                     as tup_fwd_disp_lo,
  -- sorted by tenor_years
  string_agg(upper(coalesce(nullif(l.forward_label,''),'spot')) || ':' || l.tenor_display,
             '/' order by l.tenor_years, l.effective_date, l.trade_id)     as tup_fwd_disp_ty,
  array_agg(replace(l.tenor_label,'~','')
             order by l.effective_date, l.expiration_date, l.trade_id)     as tenor_labels,
  min(l.tape_label)                                     as tape_label_min,
  count(distinct l.tape_label)                          as n_tape_labels
from u
join arbs_usd_swap_tape_legs_v3 l
  on l.package_id = u.package_id and l.as_of_date = u.as_of_date
group by u.package_id, u.as_of_date, u.kind, u.rate_index, u.venue_class,
         u.special_tenor_type, u.exclusion_reason, u.rule, u.deviation_bps,
         u.execution_timestamp, u.n_legs, u.dealer_direction
"""
t0 = time.time()
df = pd.read_sql(SQL, conn)
print(f"pulled {len(df)} units in {time.time()-t0:.1f}s")
df.to_pickle('C:/Users/chris/clee/ARBS-fe/scratch/wfstr_ik5_units2.pkl')

# does special_tenor_type=MATCHED_MATURITY always show up as fuzzy tenor_display?
print(pd.crosstab(df.special_tenor_type, [df.any_fuzzy, df.trade_type.str.contains('MATCHED')]).to_string())
print()
print(pd.crosstab(df.trade_type, df.special_tenor_type).to_string())
conn.close()
