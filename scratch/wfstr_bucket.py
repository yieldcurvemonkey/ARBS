"""INDEPENDENT orientation test: does the KRD profile say index 0 = front leg?

`dv01_if_received` is the profile the dealer would hold IF the dealer received
fixed, i.e. received_signs = +1 * base_orientation = (-1, +1) for a CURVE.
So the SHORTER-expiration leg's bucket must carry NEGATIVE dv01_if_received and
the LONGER-expiration leg's bucket POSITIVE -- for every CURVE unit, whatever
its deviation sign, INCLUDING forward-starting units the par grid cannot reach.
"""
import os, sys, warnings
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
warnings.filterwarnings('ignore')
import psycopg2, pandas as pd, numpy as np
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option('display.width', 250); pd.set_option('display.max_rows', 120)
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
q = lambda s, p=None: pd.read_sql(s, conn, params=p)

DAYS = ['2024-08-15', '2024-11-14', '2025-02-13', '2025-05-15',
        '2025-08-14', '2025-11-13', '2026-02-12', '2026-05-14']

print("bucket spaces / keys:")
print(q("""SELECT bucket_space, bucket_key, count(*) n
           FROM arbs_dd_unit_bucket_v1 WHERE as_of_date = %(d)s
           GROUP BY 1,2 ORDER BY 1,2""", {'d': DAYS[0]}).to_string())

b = q("""SELECT b.package_id, b.bucket_space, b.bucket_key,
                b.dv01_if_received, b.delta_dv01, b.signed_weight,
                u.kind, u.n_legs, u.deviation_bps, u.dealer_sign, u.rule
         FROM arbs_dd_unit_bucket_v1 b
         JOIN arbs_dd_unit_v1 u ON u.package_id = b.package_id
         WHERE b.as_of_date = ANY(%(d)s::date[]) AND u.kind = 'CURVE'""",
      {'d': DAYS})
print(f"\ncurve bucket rows: {len(b):,}  units {b['package_id'].nunique():,}")

lg = q("""SELECT l.package_id, l.trade_id, l.leg_order, l.expiration_date,
                 l.effective_date, l.tenor_label, l.tenor_years,
                 l.forward_start_years, l.fixed_rate
          FROM arbs_usd_swap_tape_legs_v3 l
          WHERE l.as_of_date = ANY(%(d)s::date[])
            AND l.package_id IN (SELECT package_id FROM arbs_dd_unit_v1
                                 WHERE as_of_date = ANY(%(d)s::date[]) AND kind='CURVE')""",
       {'d': DAYS})
print(f"legs: {len(lg):,}")

lg['_exp'] = pd.to_datetime(lg['expiration_date'])
lg['_eff'] = pd.to_datetime(lg['effective_date'])
lg['leg_order'] = pd.to_numeric(lg['leg_order'], errors='coerce').fillna(0)
lg = lg.sort_values(['package_id', '_exp', '_eff', 'trade_id', 'leg_order'],
                    kind='mergesort')
lg['i'] = lg.groupby('package_id').cumcount()
lg['ty'] = pd.to_numeric(lg['tenor_years'], errors='coerce')
lg['fs'] = pd.to_numeric(lg['forward_start_years'], errors='coerce').fillna(0)
lg['mat_yrs'] = lg['fs'] + lg['ty']          # years from spot to maturity

wide = lg.pivot_table(index='package_id', columns='i',
                      values='mat_yrs', aggfunc='first')
wide = wide[[0, 1]].dropna()
wide.columns = ['mat0', 'mat1']
print(f"\ncurve units with 2 legs resolved: {len(wide):,};  "
      f"mat0 < mat1 on {int((wide.mat0 < wide.mat1).sum()):,}, "
      f"equal on {int((wide.mat0 == wide.mat1).sum()):,}, "
      f"mat0 > mat1 on {int((wide.mat0 > wide.mat1).sum()):,}")

# ---- KRD centroid: dv01_if_received-weighted maturity of the +ve and -ve legs
bb = b[b['bucket_space'] == b['bucket_space'].mode()[0]].copy()
print(f"\nusing bucket_space = {bb['bucket_space'].iloc[0]!r}")

# map bucket_key -> a representative maturity in years
def mid_yrs(k):
    k = str(k)
    import re
    nums = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', k)]
    if not nums:
        return np.nan
    return float(np.mean(nums))

bb['byrs'] = bb['bucket_key'].map(mid_yrs)
print(bb.groupby('bucket_key')['byrs'].first().to_string())

pos = (bb[bb.dv01_if_received > 0].assign(w=lambda d: d.dv01_if_received)
         .groupby('package_id').apply(
             lambda g: np.average(g.byrs, weights=g.w)))
neg = (bb[bb.dv01_if_received < 0].assign(w=lambda d: -d.dv01_if_received)
         .groupby('package_id').apply(
             lambda g: np.average(g.byrs, weights=g.w)))
cmp = pd.DataFrame({'pos_yrs': pos, 'neg_yrs': neg}).join(wide, how='inner').dropna()
print(f"\nunits with both a +ve and a -ve KRD mass and 2 legs: {len(cmp):,}")
ok = cmp['pos_yrs'] > cmp['neg_yrs']
print(f"  KRD says LONGER leg carries the POSITIVE dv01_if_received: "
      f"{int(ok.sum()):,} / {len(cmp):,}  ({100*ok.mean():.2f}%)")
print(f"  (that is the (-1,+1) orientation with index 0 = earliest expiration)")
bad = cmp[~ok]
if len(bad):
    print("\n  counterexamples (head):")
    print(bad.head(10).to_string())
    j = bad.join(wide[['mat0', 'mat1']].rename(columns={'mat0': 'm0', 'mat1': 'm1'}))
    print(f"  of those, mat0 == mat1 (a tie, orientation undefined): "
          f"{int((bad.mat0 == bad.mat1).sum())}")

# restrict to well-separated legs so bucket bleed cannot explain it
sep = cmp[(cmp.mat1 - cmp.mat0) >= 3.0]
ok2 = sep['pos_yrs'] > sep['neg_yrs']
print(f"\n  legs >= 3y apart: {int(ok2.sum()):,} / {len(sep):,} "
      f"({100*ok2.mean():.2f}%) agree")

# forward-starting subset -- the population the par grid CANNOT reach
fw = lg.groupby('package_id')['fs'].max()
fwd_ids = fw[fw > 0].index
sf = cmp.loc[cmp.index.intersection(fwd_ids)]
ok3 = sf['pos_yrs'] > sf['neg_yrs']
print(f"  FORWARD-STARTING curve units (grid-unreachable): "
      f"{int(ok3.sum()):,} / {len(sf):,} ({100*ok3.mean() if len(sf) else float('nan'):.2f}%) agree")

conn.close()
