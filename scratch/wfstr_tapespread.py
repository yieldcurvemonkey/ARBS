"""EXTERNAL confirmation: the tape's OWN reported package spread.

`arbs_usd_swap_tape_legs_v3.package_transaction_spread` / `_price` are reported
by the venue, not computed by the direction pipeline. If the claimed
orientation is right then, for a CURVE,

    package_transaction_spread  ==  (fixed_rate[1] - fixed_rate[0]) * 10000

with index 0 = earliest expiration -- and the REVERSED orientation would come
out with the wrong sign on every non-zero print. This tests the sign convention
against a source outside the pipeline entirely.
"""
import os, sys, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
warnings.filterwarnings('ignore')
import psycopg2, pandas as pd, numpy as np
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 60)

DAYS = ['2024-08-15', '2024-11-14', '2025-02-13', '2025-05-15',
        '2025-08-14', '2025-11-13', '2026-02-12', '2026-05-14',
        '2025-03-19', '2025-09-17', '2026-03-18', '2024-09-18']
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
lg = pd.read_sql("""
   SELECT l.package_id, l.trade_id, l.leg_order, l.effective_date,
          l.expiration_date, l.fixed_rate, l.package_transaction_spread,
          l.package_transaction_price, l.tenor_label,
          u.kind, u.n_legs, u.rule, u.deviation_bps, u.dealer_sign
   FROM arbs_usd_swap_tape_legs_v3 l
   JOIN arbs_dd_unit_v1 u ON u.package_id = l.package_id AND u.as_of_date = l.as_of_date
   WHERE l.as_of_date = ANY(%(d)s::date[]) AND u.kind = 'CURVE' AND u.n_legs = 2""",
   conn, params={'d': DAYS})
conn.close()
print(f"CURVE legs: {len(lg):,}  units {lg.package_id.nunique():,}")

for c in ('fixed_rate', 'package_transaction_spread', 'package_transaction_price'):
    lg[c] = pd.to_numeric(lg[c], errors='coerce')
lg['_exp'] = pd.to_datetime(lg['expiration_date'])
lg['_eff'] = pd.to_datetime(lg['effective_date'])
lg['leg_order'] = pd.to_numeric(lg['leg_order'], errors='coerce').fillna(0)
lg = lg.sort_values(['package_id', '_exp', '_eff', 'trade_id', 'leg_order'],
                    kind='mergesort')
lg['i'] = lg.groupby('package_id').cumcount()

print("\nhow often does the tape report a package spread at all?")
print(lg.groupby('i')[['package_transaction_spread', 'package_transaction_price']]
        .agg(['count', 'nunique']).to_string())

r = lg.pivot_table(index='package_id', columns='i', values='fixed_rate', aggfunc='first')
sp = lg.groupby('package_id')['package_transaction_spread'].agg(
    ['first', 'nunique', 'count'])
u = pd.DataFrame({'r0': r[0], 'r1': r[1]}).join(
    sp.rename(columns={'first': 'tape_spread', 'nunique': 'nuniq', 'count': 'ncnt'}))
u = u.join(lg.groupby('package_id')[['rule', 'deviation_bps', 'dealer_sign']].first())
u['traded_bp'] = (u['r1'] - u['r0']) * 1e4
v = u.dropna(subset=['tape_spread'])
v = v[v['tape_spread'].abs() > 1e-9]
print(f"\nunits with a non-null, non-zero tape package_transaction_spread: {len(v):,}")
if len(v):
    for lab, x in (('canonical  (r1 - r0)', v['traded_bp']),
                   ('reversed   (r0 - r1)', -v['traded_bp'])):
        d = (x - v['tape_spread']).abs()
        print(f"  {lab}: median|diff| {d.median():.4f}  "
              f"n within 1e-6 {int((d < 1e-6).sum()):,}/{len(v):,}  "
              f"n within 0.01bp {int((d < 0.01).sum()):,}  "
              f"same SIGN {int((np.sign(x) == np.sign(v['tape_spread'])).sum()):,}")
    print("\n  head:")
    print(v[['r0', 'r1', 'traded_bp', 'tape_spread', 'rule', 'deviation_bps']].head(15).to_string())
