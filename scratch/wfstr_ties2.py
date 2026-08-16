"""The same-expiration CURVE units are a GRID-FREE test of the whole formula.

Both legs carry the same effective_date and the same expiration_date, so the two
model mids are the same number and mid_bp = mid[1]-mid[0] = 0 EXACTLY. Then

    deviation_bps  ==  (fixed_rate[1] - fixed_rate[0]) * 10000

with index 0/1 decided purely by the trade_id tie-break. No par grid is
involved, so this reaches units the grid cannot price, and it is a ONE-SIDED
test: flipping the order flips the sign of a quantity that is often tens of bp.
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
df['fixed_rate'] = pd.to_numeric(df['fixed_rate'], errors='coerce')
df['leg_order'] = pd.to_numeric(df['leg_order'], errors='coerce').fillna(0)
df = df.sort_values(['package_id', '_exp', '_eff', 'trade_id', 'leg_order'],
                    kind='mergesort')
df['i'] = df.groupby('package_id').cumcount()
print(f"{df['as_of_date'].nunique()} days, {len(df):,} leg rows")

c = df[(df['kind'] == 'CURVE') & (df['rule'] == 'RATE_VS_MID')].copy()
g = c.groupby('package_id')
info = g.agg(nexp=('_exp', 'nunique'), neff=('_eff', 'nunique'),
             nleg=('trade_id', 'size'), n_legs=('n_legs', 'first'),
             dev=('deviation_bps', 'first'), excl=('exclusion_reason', 'first'),
             nmid=('mid_pct', 'count'))
tie = info[(info.nexp == 1) & (info.neff == 1) & (info.nleg == 2)
           & (info.n_legs == 2)]
sub = c[c['package_id'].isin(tie.index)]
r = sub.pivot_table(index='package_id', columns='i', values='fixed_rate',
                    aggfunc='first')
tie = tie.join(r.rename(columns={0: 'r0', 1: 'r1'}))
tie['traded_bp'] = (tie['r1'] - tie['r0']) * 1e4
tie['err'] = tie['traded_bp'] - tie['dev']
tie['err_rev'] = (-tie['traded_bp']) - tie['dev']
tie['grid_clean'] = tie['nmid'] == 2

live = tie[tie['traded_bp'].abs() > 1e-9]
print(f"\nsame-exp+same-eff rate-rule CURVE units: {len(tie):,}   "
      f"(grid-clean {int(tie.grid_clean.sum()):,}, "
      f"grid-UNREACHABLE {int((~tie.grid_clean).sum()):,})")
print(f"of which the two legs traded at DIFFERENT rates (the tie-break decides "
      f"the sign): {len(live):,}")
print(f"\n  canonical order  : median|err| {live['err'].abs().median():.3e}  "
      f"max {live['err'].abs().max():.3e} bp   n_exact(<1e-9) "
      f"{int((live['err'].abs()<1e-9).sum()):,}/{len(live):,}")
print(f"  REVERSED order   : median|err| {live['err_rev'].abs().median():.4f}  "
      f"max {live['err_rev'].abs().max():.4f} bp   n_exact(<1e-9) "
      f"{int((live['err_rev'].abs()<1e-9).sum()):,}/{len(live):,}")
print(f"  |traded_bp| on those units: median {live['traded_bp'].abs().median():.3f} "
      f"p95 {live['traded_bp'].abs().quantile(.95):.3f} max {live['traded_bp'].abs().max():.3f} bp")
print(f"  and on the GRID-UNREACHABLE ones only: n="
      f"{int((~live.grid_clean).sum()):,}  max|err| "
      f"{live.loc[~live.grid_clean,'err'].abs().max():.3e}")
bad = live[live['err'].abs() > 1e-9]
if len(bad):
    print("\n  FAILURES:")
    print(bad.head(20).to_string())

# --- collation -----------------------------------------------------------
ids = sorted(set(sub['trade_id']))
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
cur = conn.cursor()
cur.execute("SELECT datcollate, datctype FROM pg_database WHERE datname = current_database()")
print("\ncollation:", cur.fetchone())
cur.execute("SELECT t FROM unnest(%s::text[]) t ORDER BY t", (ids,))
pg = [x[0] for x in cur.fetchall()]
print(f"postgres ORDER BY == python sorted() on {len(ids):,} tie-unit trade_ids: "
      f"{pg == sorted(ids)}")
cur.execute("SELECT count(*) FROM arbs_usd_swap_tape_legs_v3 WHERE trade_id !~ '^[0-9]+$'")
print("trade_ids that are not pure digits, whole table:", cur.fetchone()[0])
conn.close()
