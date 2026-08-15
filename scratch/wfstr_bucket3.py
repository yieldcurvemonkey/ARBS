"""Centroid form of the independent orientation test, split by rule.

Bucket MEMBERSHIP is confounded (a 7.02y swap's KRD sits on the 7Y pillar, which
the TENOR10 edges put in '5-7Y', not '7-10Y'), so use the dv01-mass centroid
instead: where is the positive dv01_if_received mass vs the negative mass.

Prediction, RATE_VS_MID only, base_orientation (-1,+1), index 0 = earliest exp:
    positive mass sits LONGER than negative mass.
Under NPV_VS_UPFRONT the orientation is (+1,+1) -- both legs the same sign -- so
that population is a built-in control that must NOT show the pattern.
"""
import os, warnings
warnings.filterwarnings('ignore')
import pandas as pd, numpy as np
pd.set_option('display.width', 250)
C = r'C:\Users\chris\clee\ARBS-fe\scratch\wfstr_out\_bkt'
b = pd.read_parquet(C + '_b.parquet'); lg = pd.read_parquet(C + '_l.parquet')

lg['_exp'] = pd.to_datetime(lg['expiration_date'])
lg['_eff'] = pd.to_datetime(lg['effective_date'])
lg['leg_order'] = pd.to_numeric(lg['leg_order'], errors='coerce').fillna(0)
lg = lg.sort_values(['package_id', '_exp', '_eff', 'trade_id', 'leg_order'],
                    kind='mergesort')
lg['i'] = lg.groupby('package_id').cumcount()
lg['mat'] = (pd.to_numeric(lg['forward_start_years'], errors='coerce').fillna(0)
             + pd.to_numeric(lg['tenor_years'], errors='coerce'))
w = lg.pivot_table(index='package_id', columns='i', values='mat', aggfunc='first')
w = w[[0, 1]].dropna(); w.columns = ['mat0', 'mat1']
w['fwd'] = (lg.groupby('package_id')['forward_start_years']
            .apply(lambda s: pd.to_numeric(s, errors='coerce').fillna(0).max()) > 0)

YR = {'0-1Y': .5, '1-2Y': 1.5, '2-3Y': 2.5, '3-5Y': 4., '5-7Y': 6., '7-10Y': 8.5,
      '10-15Y': 12.5, '15-20Y': 17.5, '20-30Y': 25., '30Y+': 35.}
b['byrs'] = b['bucket_key'].map(YR)
b['v'] = b['dv01_if_received']

g = b.groupby('package_id')
pos = g.apply(lambda x: np.average(x.byrs[x.v > 0], weights=x.v[x.v > 0])
              if (x.v > 0).any() else np.nan)
neg = g.apply(lambda x: np.average(x.byrs[x.v < 0], weights=-x.v[x.v < 0])
              if (x.v < 0).any() else np.nan)
frac_neg = g.apply(lambda x: float(np.abs(x.v[x.v < 0]).sum()
                                   / np.abs(x.v).sum()) if np.abs(x.v).sum() else np.nan)
meta = g[['rule', 'dealer_sign']].first()

u = pd.DataFrame({'pos': pos, 'neg': neg, 'frac_neg': frac_neg}).join(meta).join(w, how='inner')
u['sep'] = u['mat1'] - u['mat0']

print("A. is there ANY meaningful opposite-signed mass?  (a CURVE under the")
print("   rate rule is one payer + one receiver, so ~half the |dv01| must be")
print("   negative; under the upfront rule both legs share a sign)")
print(u.groupby('rule')['frac_neg'].describe()[['count', 'mean', '25%', '50%', '75%']].to_string())

uu = u.dropna(subset=['pos', 'neg'])
print("\nB. positive mass sits LONGER than negative mass?")
for lab, m in (('all', uu['sep'] > -1e9),
               ('sep >= 1y', uu['sep'] >= 1),
               ('sep >= 3y', uu['sep'] >= 3),
               ('sep >= 5y', uu['sep'] >= 5)):
    s = uu[m]
    r = s.assign(ok=s['pos'] > s['neg']).groupby('rule')['ok'].agg(['size', 'sum', 'mean'])
    print(f"  -- {lab}")
    print(r.to_string())

print("\nC. RATE_VS_MID, sep>=3y, split by dealer_sign "
      "(a rule right on one side only would split here):")
s = uu[(uu['rule'] == 'RATE_VS_MID') & (uu['sep'] >= 3)]
print(s.assign(ok=s['pos'] > s['neg']).groupby('dealer_sign')['ok']
       .agg(['size', 'sum', 'mean']).to_string())

print("\nD. RATE_VS_MID, sep>=3y, forward-starting vs spot "
      "(forward-start units are UNREACHABLE by the par grid):")
print(s.assign(ok=s['pos'] > s['neg']).groupby('fwd')['ok']
       .agg(['size', 'sum', 'mean']).to_string())

bad = s[~(s['pos'] > s['neg'])]
print(f"\nE. {len(bad)} disagreements; their frac_neg / sep:")
if len(bad):
    print(bad[['mat0', 'mat1', 'sep', 'pos', 'neg', 'frac_neg']].describe().to_string())
