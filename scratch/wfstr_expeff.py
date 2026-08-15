"""Discriminate EXPIRATION-first from EFFECTIVE-first in the sort key.

No grid-joinable unit has the two disagreeing (the grid is a SPOT par grid, so
every joinable leg shares one effective date), so the arithmetic test is blind
to that precedence. The units that DO disagree are exp(A) < exp(B) while
eff(A) > eff(B) -- a short forward-start against a longer spot swap. For those,
the two hypotheses predict OPPOSITE per-leg signs, and `dv01_if_received`
(orientation (-1,+1) applied to the sorted legs) reads the answer straight off
the risk profile.
"""
import os, sys, glob, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
warnings.filterwarnings('ignore')
import psycopg2, pandas as pd, numpy as np
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 60)

OUT = r'C:\Users\chris\clee\ARBS-fe\scratch\wfstr_out'
df = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(OUT, '2*.parquet')))],
               ignore_index=True)
df['_exp'] = pd.to_datetime(df['expiration_date'])
df['_eff'] = pd.to_datetime(df['effective_date'])
df['leg_order'] = pd.to_numeric(df['leg_order'], errors='coerce').fillna(0)
df['mat'] = (pd.to_numeric(df['forward_start_years'], errors='coerce').fillna(0)
             + pd.to_numeric(df['tenor_years'], errors='coerce'))

c = df[(df['kind'] == 'CURVE') & (df['rule'] == 'RATE_VS_MID')
       & df['exclusion_reason'].isna()].copy()
a = c.sort_values(['package_id', '_exp', '_eff', 'trade_id', 'leg_order'],
                  kind='mergesort').copy()
a['i_exp'] = a.groupby('package_id').cumcount()
b = c.sort_values(['package_id', '_eff', '_exp', 'trade_id', 'leg_order'],
                  kind='mergesort').copy()
b['i_eff'] = b.groupby('package_id').cumcount()
k = ['package_id', 'trade_id']
m = a.set_index(k)[['i_exp', 'mat', 'as_of_date']].join(b.set_index(k)[['i_eff']])
diff = m.groupby('package_id').apply(lambda g: bool((g.i_exp != g.i_eff).any()))
ids = list(diff[diff].index)
print(f"rate-rule CURVE units where EXP-order and EFF-order disagree: "
      f"{len(ids):,} of {c['package_id'].nunique():,}")

mm = m.loc[m.index.get_level_values(0).isin(ids)].reset_index()
w = mm.pivot_table(index='package_id', columns='i_exp', values='mat', aggfunc='first')
w.columns = ['mat_exp0', 'mat_exp1']
w['sep'] = (w['mat_exp1'] - w['mat_exp0']).abs()
print(f"  their |maturity separation|: median {w['sep'].median():.2f}y  "
      f">=5y on {int((w['sep'] >= 5).sum()):,}  >=8y on {int((w['sep'] >= 8).sum()):,}")

days = sorted({str(d) for d in mm['as_of_date'].unique()})
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
bk = pd.read_sql("""SELECT package_id, bucket_key, dv01_if_received
                    FROM arbs_dd_unit_bucket_v1
                    WHERE bucket_space='TENOR10' AND package_id = ANY(%(p)s::text[])""",
                 conn, params={'p': ids})
conn.close()
print(f"  bucket rows for them: {len(bk):,} over {bk.package_id.nunique():,} units")

YR = {'0-1Y': .5, '1-2Y': 1.5, '2-3Y': 2.5, '3-5Y': 4., '5-7Y': 6., '7-10Y': 8.5,
      '10-15Y': 12.5, '15-20Y': 17.5, '20-30Y': 25., '30Y+': 35.}
bk['byrs'] = bk['bucket_key'].map(YR)
g = bk.groupby('package_id')
pos = g.apply(lambda x: np.average(x.byrs[x.dv01_if_received > 0],
                                   weights=x.dv01_if_received[x.dv01_if_received > 0])
              if (x.dv01_if_received > 0).any() else np.nan)
neg = g.apply(lambda x: np.average(x.byrs[x.dv01_if_received < 0],
                                   weights=-x.dv01_if_received[x.dv01_if_received < 0])
              if (x.dv01_if_received < 0).any() else np.nan)
u = pd.DataFrame({'pos': pos, 'neg': neg}).join(w, how='inner').dropna()
print(f"  units with both signs of mass and 2 maturities: {len(u):,}")

# hypothesis EXP: index0 = earliest EXPIRY -> negative mass at mat_exp0
# hypothesis EFF: index0 = earliest EFFECTIVE = the OTHER leg -> negative mass
#                 at mat_exp1  (these units are exactly where the two swap)
for lab, m_ in (('all', u['sep'] > -1), ('sep>=3y', u['sep'] >= 3),
                ('sep>=5y', u['sep'] >= 5), ('sep>=8y', u['sep'] >= 8)):
    s = u[m_]
    if not len(s):
        continue
    d_exp = (s['neg'] - s['mat_exp0']).abs() < (s['neg'] - s['mat_exp1']).abs()
    print(f"   {lab:8s} n={len(s):4,}   negative KRD mass nearer the EARLIEST-"
          f"EXPIRING leg: {int(d_exp.sum()):4,} ({100*d_exp.mean():5.1f}%)   "
          f"nearer the other leg: {int((~d_exp).sum()):4,}")
