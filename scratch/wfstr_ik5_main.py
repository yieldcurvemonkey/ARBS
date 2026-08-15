import os, sys, time
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2
import pandas as pd

pd.set_option('display.width', 250)
pd.set_option('display.max_colwidth', 90)
pd.set_option('display.max_rows', 200)

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
cur.execute("set statement_timeout = '280s'")


def q(sql, params=None, title=""):
    t0 = time.time()
    df = pd.read_sql(sql, conn, params=params)
    print(f"--- {title} ({len(df)} rows, {time.time()-t0:.1f}s) ---")
    print(df.to_string())
    print(flush=True)
    return df


# ------------------------------------------------------------------ sanity 1
q("""select forward_label, count(*) n,
        min(forward_start_years) mn, max(forward_start_years) mx
     from arbs_usd_swap_tape_legs_v3
     where as_of_date >= date '2026-07-01' and forward_label = 'spot'
     group by 1""", None, "SANITY: forward_label='spot' => forward_start_years range")

# ------------------------------------------------------------------ pub days
pub = q("""select as_of_date from arbs_dd_unit_v1
           group by 1 order by 1 desc limit 60""", None, "last 60 published days (head)")
D_LAST = pub['as_of_date'].max()
D_FIRST = pub['as_of_date'].min()
print(f"WINDOW: {D_FIRST} .. {D_LAST}  ({len(pub)} published days)\n", flush=True)

# ------------------------------------------------------------------ main pull
KEYSQL = """
with pub as (
  select as_of_date from arbs_dd_unit_v1 group by 1 order by 1 desc limit 60
),
u as (
  select * from arbs_dd_unit_v1
  where as_of_date in (select as_of_date from pub) and kind in ('CURVE','FLY')
),
agg as (
  select
    u.package_id, u.as_of_date, u.kind, u.rate_index, u.venue_class,
    u.special_tenor_type, u.exclusion_reason, u.rule, u.deviation_bps,
    u.execution_timestamp, u.n_legs,
    count(*) as n_joined,
    bool_or(coalesce(l.is_spreadover,false) or coalesce(l.is_asset_swap,false)) as is_asw,
    bool_and(coalesce(l.forward_label,'spot') = 'spot')                        as all_spot,
    -- canonical (near leg first)
    string_agg(replace(l.tenor_display,'~','') , '/'
       order by l.effective_date, l.expiration_date, l.trade_id) as tup_disp_canon,
    string_agg(replace(l.tenor_label,'~','')   , '/'
       order by l.effective_date, l.expiration_date, l.trade_id) as tup_lbl_canon,
    string_agg(upper(coalesce(nullif(l.forward_label,''),'spot')) || ':' ||
               replace(l.tenor_label,'~',''), '/'
       order by l.effective_date, l.expiration_date, l.trade_id) as tup_full_canon,
    -- as-stored (leg_order)
    string_agg(replace(l.tenor_display,'~','') , '/' order by l.leg_order) as tup_disp_legorder,
    string_agg(upper(coalesce(nullif(l.forward_label,''),'spot')) || ':' ||
               replace(l.tenor_label,'~',''), '/' order by l.leg_order) as tup_full_legorder,
    -- sorted by tenor_years (the literal proposal)
    string_agg(replace(l.tenor_display,'~','') , '/'
       order by l.tenor_years, l.effective_date, l.trade_id) as tup_disp_tenyrs,
    array_agg(replace(l.tenor_label,'~','')
       order by l.effective_date, l.expiration_date, l.trade_id) as tenor_labels
  from u
  join arbs_usd_swap_tape_legs_v3 l
    on l.package_id = u.package_id and l.as_of_date = u.as_of_date
  group by u.package_id, u.as_of_date, u.kind, u.rate_index, u.venue_class,
           u.special_tenor_type, u.exclusion_reason, u.rule, u.deviation_bps,
           u.execution_timestamp, u.n_legs
)
select * from agg
"""
t0 = time.time()
df = pd.read_sql(KEYSQL, conn)
print(f"MAIN PULL: {len(df)} units in {time.time()-t0:.1f}s\n", flush=True)
df.to_pickle('C:/Users/chris/clee/ARBS-fe/scratch/wfstr_ik5_units.pkl')

# ------------------------------------------------------------------ grid tenors
g = q("""select grid_date, rate_index, tenor_label
         from arbs_dd_curve_mid_v1
         where grid_date in (date '2026-08-07', date '2026-05-15', date '2025-11-14',
                             date '2024-09-16')
         group by 1,2,3""", None, "grid tenor sets sample (raw)")
gt = (g.groupby(['grid_date', 'rate_index'])['tenor_label']
        .agg(lambda s: tuple(sorted(s))).reset_index())
gt['n'] = gt['tenor_label'].map(len)
print(gt[['grid_date', 'rate_index', 'n']].to_string())
print("distinct tenor sets per rate_index:")
for ri, sub in gt.groupby('rate_index'):
    sets = set(sub['tenor_label'])
    print(f"  {ri}: {len(sets)} distinct set(s) across {len(sub)} sampled days")
    for s in sets:
        print(f"    n={len(s)} {sorted(s)}")
import pickle
with open('C:/Users/chris/clee/ARBS-fe/scratch/wfstr_ik5_grid.pkl', 'wb') as f:
    pickle.dump({ri: set(sub.iloc[0]['tenor_label']) for ri, sub in gt.groupby('rate_index')}, f)

conn.close()
print("DONE", flush=True)
