"""Discriminate the QUOTE WEIGHTS, not just the leg order.

A global sign flip of the weight vector leaves |traded - mid| unchanged and only
moves the residual by 2*deviation, so it is the weakest thing to pin. Test it
head on, together with the FLY belly permutations.
"""
import os, glob, warnings
warnings.filterwarnings('ignore')
import pandas as pd, numpy as np
pd.set_option('display.width', 250)
OUT = r'C:\Users\chris\clee\ARBS-fe\scratch\wfstr_out'

df = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(OUT, '2*.parquet')))],
               ignore_index=True)
df['fixed_rate'] = pd.to_numeric(df['fixed_rate'], errors='coerce')
df['mid_pct'] = pd.to_numeric(df['mid_pct'], errors='coerce')
df['_exp'] = pd.to_datetime(df['expiration_date'])
df['_eff'] = pd.to_datetime(df['effective_date'])
df['leg_order'] = pd.to_numeric(df['leg_order'], errors='coerce').fillna(0)
df = df.sort_values(['package_id', '_exp', '_eff', 'trade_id', 'leg_order'],
                    kind='mergesort').reset_index(drop=True)
df['i'] = df.groupby('package_id').cumcount()

df = df[(df['rule'] == 'RATE_VS_MID') & df['exclusion_reason'].isna()]
ok = df.groupby('package_id')['mid_pct'].transform('count') == df['n_legs']
df = df[ok]

CAND = {
    'CURVE': {'(-1,+1)  CLAIMED': (-1., 1.),
              '(+1,-1)  global flip': (1., -1.)},
    'FLY': {'(-1,+2,-1)  CLAIMED': (-1., 2., -1.),
            '(+1,-2,+1)  global flip': (1., -2., 1.),
            '(+2,-1,-1)  belly=index0': (2., -1., -1.),
            '(-1,-1,+2)  belly=index2': (-1., -1., 2.),
            '(-1,+1, 0)  front curve': (-1., 1., 0.),
            '(-0.5,+1,-0.5) half wings': (-.5, 1., -.5)},
}

for kind, cands in CAND.items():
    s = df[df['kind'] == kind]
    n = s['package_id'].nunique()
    dev = s.groupby('package_id')['deviation_bps'].first()
    print(f"\n{kind}: {n:,} rate-rule grid-clean units "
          f" median|deviation| = {dev.abs().median():.4f} bp")
    for lab, q in cands.items():
        w = np.take(np.array(q), s['i'].to_numpy())
        t = pd.Series(w * s['fixed_rate'].to_numpy() * 1e4,
                      index=s.index).groupby(s['package_id']).sum()
        m = pd.Series(w * s['mid_pct'].to_numpy() * 1e2,
                      index=s.index).groupby(s['package_id']).sum()
        e = (t - m - dev).abs()
        print(f"   {lab:28s} median|err| {e.median():.4e}  max {e.max():.4e}  "
              f"n_exact {int((e < 1e-9).sum()):6,}/{len(e):,}")

# unit-scale traps: fraction vs percent vs bp on the traded side
s = df[df['kind'] == 'CURVE']
dev = s.groupby('package_id')['deviation_bps'].first()
q = np.array([-1., 1.])
w = np.take(q, s['i'].to_numpy())
m = pd.Series(w * s['mid_pct'].to_numpy() * 1e2, index=s.index).groupby(s['package_id']).sum()
print("\nCURVE unit-scale variants on the TRADED side (mid held canonical):")
for lab, sc in (('fixed_rate * 1e4   CLAIMED', 1e4),
                ('fixed_rate * 1e2   (treat as percent)', 1e2),
                ('fixed_rate * 1e6   (treat as bp)', 1e6)):
    t = pd.Series(w * s['fixed_rate'].to_numpy() * sc,
                  index=s.index).groupby(s['package_id']).sum()
    e = (t - m - dev).abs()
    print(f"   {lab:40s} median|err| {e.median():.4e}  n_exact {int((e<1e-9).sum()):,}")
print("\nCURVE unit-scale variants on the MID side (traded held canonical):")
t = pd.Series(w * s['fixed_rate'].to_numpy() * 1e4, index=s.index).groupby(s['package_id']).sum()
for lab, sc in (('mid_pct * 1e2   CLAIMED', 1e2),
                ('mid_pct * 1e4   (treat as fraction)', 1e4),
                ('mid_pct * 1.0   (treat as bp)', 1.0)):
    m2 = pd.Series(w * s['mid_pct'].to_numpy() * sc,
                   index=s.index).groupby(s['package_id']).sum()
    e = (t - m2 - dev).abs()
    print(f"   {lab:40s} median|err| {e.median():.4e}  n_exact {int((e<1e-9).sum()):,}")
