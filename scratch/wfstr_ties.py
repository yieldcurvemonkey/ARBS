"""Tie-break and degenerate-input checks.

1. CURVE units whose two legs share expiration (and effective) date: 'long minus
   short' has no date to decide it, so the order falls through to trade_id --
   and the pipeline resolves trade_id in PANDAS (python codepoint order), while
   a reader writing SQL `ORDER BY trade_id` gets the DATABASE COLLATION. Do the
   two ever disagree, and does the sign of the answer depend on it?
2. NULL / non-finite fixed_rate on a rate-rule leg.
3. off-market / MAC / IMM legs inside rate-rule CURVE units.
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
print(f"{df['as_of_date'].nunique()} days, {len(df):,} leg rows")

c = df[df['kind'] == 'CURVE']
g = c.groupby('package_id')
tie = g.agg(nexp=('_exp', 'nunique'), neff=('_eff', 'nunique'),
            rule=('rule', 'first'), dev=('deviation_bps', 'first'),
            nrate=('fixed_rate', 'nunique'), nmid=('mid_pct', 'count'),
            n_legs=('n_legs', 'first'), tids=('trade_id', list),
            rates=('fixed_rate', list), excl=('exclusion_reason', 'first'))
tie['clean'] = tie['nmid'] == tie['n_legs']
t = tie[tie['nexp'] == 1]
print(f"\n[1] CURVE units, both legs SAME expiration_date: {len(t):,} of {len(tie):,}")
print(t.groupby(['rule', tie['neff'] == 1])[['dev']].agg(
    n=('dev', 'size'), n_dev_nonzero=('dev', lambda s: int((s.abs() > 1e-9).sum()))).to_string())
tr = t[(t['rule'] == 'RATE_VS_MID')]
print(f"\n  rate-rule same-expiration CURVE units: {len(tr):,}; "
      f"grid-clean {int(tr['clean'].sum()):,}; "
      f"|deviation| > 1e-9 on {int((tr['dev'].abs() > 1e-9).sum()):,}; "
      f"the two legs carry DIFFERENT fixed_rate on {int((tr['nrate'] > 1).sum()):,}")
amb = tr[(tr['nrate'] > 1) & (tr['neff'] == 1)]
print(f"  -> units where the tie-break actually decides the SIGN "
      f"(same exp, same eff, different rates): {len(amb):,}")
if len(amb):
    print(amb[['dev', 'clean', 'tids', 'rates']].head(10).to_string())

# --- does python order == postgres collation order on those trade_ids? -----
ids = sorted({x for v in tr['tids'] for x in v})
print(f"\n[1b] collation check on {len(ids):,} trade_ids from tie units")
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
cur = conn.cursor()
cur.execute("SELECT current_setting('lc_collate'), version()")
print("   lc_collate =", cur.fetchone()[0])
cur.execute("SELECT t FROM unnest(%s::text[]) t ORDER BY t", (ids,))
pg = [r[0] for r in cur.fetchall()]
py = sorted(ids)
print(f"   postgres order == python order: {pg == py}")
if pg != py:
    d = [i for i, (a, b) in enumerate(zip(pg, py)) if a != b][:5]
    print("   first divergences:", [(pg[i], py[i]) for i in d])
print("   sample trade_ids:", ids[:4])
conn.close()

# --- 2. degenerate inputs -------------------------------------------------
r = df[(df['rule'] == 'RATE_VS_MID') & df['kind'].isin(['CURVE', 'FLY'])]
print(f"\n[2] rate-rule CURVE/FLY legs: {len(r):,}")
print(f"    NULL fixed_rate: {int(r['fixed_rate'].isna().sum())}")
print(f"    non-finite     : {int((~np.isfinite(r['fixed_rate'].fillna(np.nan))).sum())}")
print(f"    |fixed_rate| > 1 (i.e. looks like PERCENT not a fraction): "
      f"{int((r['fixed_rate'].abs() > 1).sum())}")
print(f"    fixed_rate range: {r['fixed_rate'].min():.6f} .. {r['fixed_rate'].max():.6f}")
print(f"    mid_pct range   : {pd.to_numeric(r['mid_pct'], errors='coerce').min():.4f} .. "
      f"{pd.to_numeric(r['mid_pct'], errors='coerce').max():.4f}")
print(f"    is_off_market legs: {int(r['is_off_market'].fillna(False).sum())}, "
      f"is_mac: {int(r['is_mac'].fillna(False).sum())}")
print("\n[3] special_tenor_type on rate-rule CURVE/FLY units:")
print(r.groupby(['kind', 'special_tenor_type'])['package_id'].nunique().to_string())
