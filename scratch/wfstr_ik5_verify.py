import os, sys, time
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2
import pandas as pd
pd.set_option('display.width', 260); pd.set_option('display.max_colwidth', 90)
pd.set_option('display.max_rows', 200)
conn = psycopg2.connect(resolve_pg_url())
conn.cursor().execute("set statement_timeout = '280s'")

# ---- THE DELIVERABLE: one row per unit with its structure_key -------------
STRUCT_KEY_SQL = """
create temp view x as select 1;   -- placeholder never used
"""

KEY_CTE = """
with unit_key as (
  select
      u.package_id,
      u.as_of_date,
      u.kind,
      u.rate_index,
      u.venue_class,
      u.deviation_bps,
      -- ---------- structure family (economics, not provenance) ----------
      case
        when min(l.trade_type) like 'SPREADOVER%%'                     then 'ASW_SPREADOVER'
        when min(l.trade_type) like 'MATCHED_MATURITY%%'
          or u.special_tenor_type = 'MATCHED_MATURITY'                 then 'ASW_MATCHED_MATURITY'
        when min(l.trade_type) like 'INVOICE%%'
          or u.special_tenor_type = 'INVOICE_SWAP'                     then 'ASW_INVOICE'
        when min(l.trade_type) like 'BASIS%%'
          or u.rate_index = 'BASIS'                                    then 'BASIS'
        when bool_or(coalesce(l.is_mac,false))
          or u.special_tenor_type = 'MAC'                              then 'MAC'
        else 'RATE'
      end as family,
      -- ---------- canonical ordered leg tuple ----------
      string_agg(
        upper(coalesce(nullif(l.forward_label,''),'spot')) || ':' || l.tenor_display,
        '/' order by l.effective_date, l.expiration_date, l.trade_id
      ) as leg_tuple,
      -- de-fuzzed labels for the grid join
      array_agg(replace(l.tenor_label,'~','')
        order by l.effective_date, l.expiration_date, l.trade_id) as grid_tenors,
      bool_and(coalesce(l.forward_label,'spot') = 'spot')       as all_spot,
      bool_or(l.tenor_display like '~%%')                       as any_fuzzy
  from arbs_dd_unit_v1 u
  join arbs_usd_swap_tape_legs_v3 l
    on l.package_id = u.package_id and l.as_of_date = u.as_of_date
  where u.kind in ('CURVE','FLY')
    and u.as_of_date = date '2026-08-07'
  group by u.package_id, u.as_of_date, u.kind, u.rate_index, u.venue_class,
           u.deviation_bps, u.special_tenor_type
),
keyed as (
  select *, kind || '|' || rate_index || '|' || family || '|' || leg_tuple as structure_key
  from unit_key
)
"""


def q(sql, title=""):
    t0 = time.time()
    df = pd.read_sql(sql, conn)
    print(f"--- {title} ({len(df)} rows, {time.time()-t0:.1f}s) ---")
    print(df.to_string())
    print(flush=True)
    return df


print("TEST 1 (known answer = 7 D2C prints for the true spot 10s30s SOFR curve):")
q(KEY_CTE + """
  select structure_key, venue_class, count(*) prints,
         count(deviation_bps) priced
  from keyed
  where kind='CURVE' and rate_index='SOFR' and grid_tenors = array['10Y','30Y']
  group by 1,2 order by 3 desc""", "2026-08-07 CURVE SOFR 10Y/30Y by key x venue")

print("TEST 2 (known answer: 528 CURVE+FLY units that day, all keyed, none null):")
q(KEY_CTE + """
  select kind, count(*) n, count(structure_key) n_keyed,
         count(distinct structure_key) n_keys
  from keyed group by 1""", "coverage of the key expression")

print("TEST 3 (mutation check - the key MUST change when family is dropped):")
q(KEY_CTE + """
  select count(distinct structure_key) with_family,
         count(distinct kind||'|'||rate_index||'|'||leg_tuple) without_family,
         count(distinct kind||'|'||rate_index||'|'||
               regexp_replace(leg_tuple,'[A-Z_0-9]+:','','g')) literal_tenor_only
  from keyed""", "key granularity, same day")

print("TEST 4: full-window headline instrument straight from SQL "
      "(known answer: 510 prints / 60 days):")
q("""
with pub as (select as_of_date from arbs_dd_unit_v1 group by 1 order by 1 desc limit 60),
unit_key as (
  select u.package_id, u.as_of_date, u.kind, u.rate_index, u.venue_class, u.deviation_bps,
      case when min(l.trade_type) like 'SPREADOVER%%' then 'ASW_SPREADOVER'
           when min(l.trade_type) like 'MATCHED_MATURITY%%'
             or u.special_tenor_type='MATCHED_MATURITY' then 'ASW_MATCHED_MATURITY'
           when min(l.trade_type) like 'INVOICE%%'
             or u.special_tenor_type='INVOICE_SWAP' then 'ASW_INVOICE'
           when min(l.trade_type) like 'BASIS%%' or u.rate_index='BASIS' then 'BASIS'
           when bool_or(coalesce(l.is_mac,false)) or u.special_tenor_type='MAC' then 'MAC'
           else 'RATE' end as family,
      string_agg(upper(coalesce(nullif(l.forward_label,''),'spot'))||':'||l.tenor_display,
                 '/' order by l.effective_date, l.expiration_date, l.trade_id) as leg_tuple
  from arbs_dd_unit_v1 u
  join arbs_usd_swap_tape_legs_v3 l
    on l.package_id=u.package_id and l.as_of_date=u.as_of_date
  where u.kind in ('CURVE','FLY') and u.as_of_date in (select as_of_date from pub)
  group by u.package_id,u.as_of_date,u.kind,u.rate_index,u.venue_class,
           u.deviation_bps,u.special_tenor_type)
select kind||'|'||rate_index||'|'||family||'|'||leg_tuple as structure_key,
       count(*) prints, count(distinct as_of_date) days, count(deviation_bps) priced
from unit_key
where kind||'|'||rate_index||'|'||family||'|'||leg_tuple
      = 'CURVE|SOFR|RATE|SPOT:10Y/SPOT:30Y'
group by 1""", "headline instrument, 60-day window, pure SQL")

conn.close()
