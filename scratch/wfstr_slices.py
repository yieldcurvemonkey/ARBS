"""Slice the confirmed population, and check code_vintage uniformity in prod."""
import os, sys, glob, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
warnings.filterwarnings('ignore')
import psycopg2, pandas as pd, numpy as np
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 80)

u = pd.read_parquet(r'C:\Users\chris\clee\ARBS-fe\scratch\wfstr_unit_frame.parquet')
s = u[(u['rule'] == 'RATE_VS_MID') & u['grid_clean'] & u['excl'].isna()
      & u['kind'].isin(['CURVE', 'FLY'])]
print(f"confirmed population: {len(s):,} units, {s['as_of_date'].nunique()} days, "
      f"{pd.to_datetime(s['as_of_date']).min().date()} .. "
      f"{pd.to_datetime(s['as_of_date']).max().date()}")
print("\nby kind x rate_index:")
print(s.groupby(['kind', 'rate_index'])['err_i_can'].agg(
    n='size', med=lambda x: x.abs().median(), mx=lambda x: x.abs().max()).to_string())
print("\nby special_tenor_type:")
print(s.groupby(['kind', 'stt'])['err_i_can'].agg(
    n='size', mx=lambda x: x.abs().max()).to_string())
print("\nby dealer_sign (both directions must be exact, not just on net):")
print(s.groupby(['kind', 'dsign'])['err_i_can'].agg(
    n='size', mx=lambda x: x.abs().max()).to_string())
print("\nby |deviation| decile -- a unit error would blow up in the tails:")
s2 = s.copy(); s2['q'] = pd.qcut(s2['dev'].abs(), 10, duplicates='drop', labels=False)
print(s2.groupby('q').agg(n=('dev', 'size'), dev_lo=('dev', lambda x: x.abs().min()),
                          dev_hi=('dev', lambda x: x.abs().max()),
                          mx=('err_i_can', lambda x: x.abs().max())).to_string())
print("\ntraded_bp magnitude reached (the scale the formula is tested over):")
print(s.groupby('kind')['traded_i_can'].describe(
    percentiles=[.01, .5, .99]).to_string())

conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
print("\ncode_vintage over the WHOLE unit table:")
print(pd.read_sql("SELECT code_vintage, count(*) n, min(as_of_date) mn, max(as_of_date) mx "
                  "FROM arbs_dd_unit_v1 GROUP BY 1 ORDER BY 2 DESC", conn).to_string())
print("\nrate-rule CURVE/FLY units with a NULL curve_timestamp or a stale snapshot:")
print(pd.read_sql("""SELECT kind, snapshot_policy, count(*) n
                     FROM arbs_dd_unit_v1
                     WHERE rule='RATE_VS_MID' AND kind IN ('CURVE','FLY')
                       AND exclusion_reason IS NULL
                     GROUP BY 1,2 ORDER BY 1,2""", conn).to_string())
conn.close()
