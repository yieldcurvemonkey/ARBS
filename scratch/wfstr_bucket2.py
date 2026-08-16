"""Sharper INDEPENDENT orientation test.

For each CURVE unit map each leg's maturity to its own TENOR10 bucket. Where the
two legs land in DIFFERENT buckets the netting ambiguity is gone, and the
prediction is exact:

    dv01_if_received[bucket of the EARLIER-expiring leg]  < 0
    dv01_if_received[bucket of the LATER-expiring leg]    > 0

because received_signs = +1 * base_orientation(CURVE) = (-1, +1) with index 0 =
earliest expiration. Nothing here touches the par grid, so forward-starting and
broken-date curves -- which the grid cannot reach at all -- are covered.
"""
import os, sys, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
warnings.filterwarnings('ignore')
import psycopg2, pandas as pd, numpy as np
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 120)

CACHE = r'C:\Users\chris\clee\ARBS-fe\scratch\wfstr_out\_bkt'
DAYS = ['2024-08-15', '2024-11-14', '2025-02-13', '2025-05-15',
        '2025-08-14', '2025-11-13', '2026-02-12', '2026-05-14']

if os.path.exists(CACHE + '_b.parquet'):
    b = pd.read_parquet(CACHE + '_b.parquet'); lg = pd.read_parquet(CACHE + '_l.parquet')
else:
    conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
    q = lambda s, p=None: pd.read_sql(s, conn, params=p)
    b = q("""SELECT b.package_id, b.bucket_key, b.dv01_if_received, b.delta_dv01,
                    u.kind, u.deviation_bps, u.dealer_sign, u.rule, u.signed_weight
             FROM arbs_dd_unit_bucket_v1 b
             JOIN arbs_dd_unit_v1 u ON u.package_id = b.package_id
             WHERE b.as_of_date = ANY(%(d)s::date[]) AND u.kind='CURVE'
               AND b.bucket_space='TENOR10'""", {'d': DAYS})
    lg = q("""SELECT l.package_id, l.trade_id, l.leg_order, l.expiration_date,
                     l.effective_date, l.tenor_years, l.forward_start_years
              FROM arbs_usd_swap_tape_legs_v3 l
              WHERE l.as_of_date = ANY(%(d)s::date[])
                AND l.package_id IN (SELECT package_id FROM arbs_dd_unit_v1
                                     WHERE as_of_date = ANY(%(d)s::date[]) AND kind='CURVE')""",
           {'d': DAYS})
    b.to_parquet(CACHE + '_b.parquet'); lg.to_parquet(CACHE + '_l.parquet')
    conn.close()

print(f"bucket rows {len(b):,}  units {b.package_id.nunique():,}   legs {len(lg):,}")

lg['_exp'] = pd.to_datetime(lg['expiration_date'])
lg['_eff'] = pd.to_datetime(lg['effective_date'])
lg['leg_order'] = pd.to_numeric(lg['leg_order'], errors='coerce').fillna(0)
lg = lg.sort_values(['package_id', '_exp', '_eff', 'trade_id', 'leg_order'],
                    kind='mergesort')
lg['i'] = lg.groupby('package_id').cumcount()
lg['ty'] = pd.to_numeric(lg['tenor_years'], errors='coerce')
lg['fs'] = pd.to_numeric(lg['forward_start_years'], errors='coerce').fillna(0)
lg['mat'] = lg['fs'] + lg['ty']

EDGES = [0, 1, 2, 3, 5, 7, 10, 15, 20, 30, 1e9]
NAMES = ['0-1Y', '1-2Y', '2-3Y', '3-5Y', '5-7Y', '7-10Y', '10-15Y',
         '15-20Y', '20-30Y', '30Y+']
lg['bkt'] = pd.cut(lg['mat'], bins=EDGES, labels=NAMES, right=True,
                   include_lowest=True).astype(str)

w = lg.pivot_table(index='package_id', columns='i', values='mat', aggfunc='first')
wb = lg.pivot_table(index='package_id', columns='i', values='bkt',
                    aggfunc='first')
w = w[[0, 1]].dropna(); w.columns = ['mat0', 'mat1']
wb = wb[[0, 1]].dropna(); wb.columns = ['b0', 'b1']
u = w.join(wb, how='inner')
u['fwd'] = lg.groupby('package_id')['fs'].max().reindex(u.index) > 0

piv = b.pivot_table(index='package_id', columns='bucket_key',
                    values='dv01_if_received', aggfunc='first')
u = u.join(piv, how='inner')
meta = b.groupby('package_id')[['rule', 'dealer_sign', 'deviation_bps']].first()
u = u.join(meta)

sel = u[u['b0'] != u['b1']].copy()
sel['d0'] = [r[r['b0']] for _, r in sel.iterrows()]
sel['d1'] = [r[r['b1']] for _, r in sel.iterrows()]
sel = sel.dropna(subset=['d0', 'd1'])
print(f"\nunits whose two legs land in DIFFERENT TENOR10 buckets: {len(sel):,}")
ok = (sel['d0'] < 0) & (sel['d1'] > 0)
print(f"  front bucket NEGATIVE and back bucket POSITIVE: "
      f"{int(ok.sum()):,} / {len(sel):,}  ({100*ok.mean():.3f}%)")
print(f"  the exact opposite (front +, back -):           "
      f"{int(((sel.d0>0)&(sel.d1<0)).sum()):,}")
print("\n  by whether the print is forward-starting (grid-unreachable):")
print(sel.assign(ok=ok).groupby('fwd')['ok'].agg(['size', 'sum', 'mean']).to_string())
print("\n  by rule:")
print(sel.assign(ok=ok).groupby('rule')['ok'].agg(['size', 'sum', 'mean']).to_string())
print("\n  by dealer_sign (a formula right for one side and inverted for the")
print("  other would split here):")
print(sel.assign(ok=ok).groupby('dealer_sign')['ok'].agg(['size', 'sum', 'mean']).to_string())
bad = sel[~ok]
if len(bad):
    print(f"\n  {len(bad)} disagreements, head:")
    print(bad[['mat0', 'mat1', 'b0', 'b1', 'd0', 'd1', 'rule',
               'dealer_sign']].head(15).to_string())
    print("\n  their |mat1-mat0| distribution:")
    print((bad['mat1'] - bad['mat0']).describe().to_string())
