"""Analyse the pulled leg+grid frame. No DB. Pure arithmetic."""
from __future__ import annotations
import os, sys, glob, warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np

pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40)
OUT = r'C:\Users\chris\clee\ARBS-fe\scratch\wfstr_out'

files = sorted(glob.glob(os.path.join(OUT, '2*.parquet')))
print(f"day files: {len(files)}  {os.path.basename(files[0])} .. {os.path.basename(files[-1])}")
df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
print(f"raw leg rows: {len(df):,}   units: {df['package_id'].nunique():,}"
      f"   days: {df['as_of_date'].nunique()}")

# ---- types --------------------------------------------------------------
for c in ('fixed_rate', 'tenor_years', 'forward_start_years'):
    df[c] = pd.to_numeric(df[c], errors='coerce')
df['mid_pct'] = pd.to_numeric(df['mid_pct'], errors='coerce')
df['_exp'] = pd.to_datetime(df['expiration_date'], errors='coerce')
df['_eff'] = pd.to_datetime(df['effective_date'], errors='coerce')
df['leg_order'] = pd.to_numeric(df['leg_order'], errors='coerce').fillna(0)

# ---- 0a. grid join uniqueness ------------------------------------------
dup = df.duplicated(subset=['package_id', 'trade_id'], keep=False)
print(f"\n[0a] legs matching >1 grid row: {int(dup.sum()):,} rows over "
      f"{df.loc[dup,'package_id'].nunique():,} units")
if dup.any():
    print(df.loc[dup, ['package_id','trade_id','tenor_label','grid_tenor',
                       'effective_date','expiration_date','mid_pct']].head(12).to_string())
    # keep one row per leg so the arithmetic is well defined; count it
    df = df.drop_duplicates(subset=['package_id', 'trade_id'], keep='first')

# ---- 0b. leg count vs n_legs -------------------------------------------
cnt = df.groupby('package_id')['trade_id'].transform('size')
bad = cnt != df['n_legs']
print(f"[0b] units whose joined leg count != n_legs: "
      f"{df.loc[bad,'package_id'].nunique():,} of {df['package_id'].nunique():,}")
if bad.any():
    print(df.loc[bad].groupby(['kind', 'n_legs'])['package_id'].nunique().head(20).to_string())
df = df[~bad].copy()

# ---- canonical ordering (replicating universe.annotate_legs) ------------
CAN = ['package_id', '_exp', '_eff', 'trade_id', 'leg_order']
df = df.sort_values(CAN, kind='mergesort').reset_index(drop=True)
df['i_can'] = df.groupby('package_id').cumcount()

# alternative orderings, for the discrimination test
def _idx(frame, keys, name):
    o = frame.sort_values(['package_id'] + keys, kind='mergesort').copy()
    o[name] = o.groupby('package_id').cumcount()
    return o.set_index(['package_id', 'trade_id'])[name]

k = df.set_index(['package_id', 'trade_id']).index
df['i_phys'] = _idx(df, ['phys'], 'i_phys').reindex(k).to_numpy()
df['i_lo'] = _idx(df, ['leg_order'], 'i_lo').reindex(k).to_numpy()
df['i_tid'] = _idx(df, ['trade_id'], 'i_tid').reindex(k).to_numpy()
df['i_ten'] = _idx(df, ['tenor_years'], 'i_ten').reindex(k).to_numpy()
df['i_eff'] = _idx(df, ['_eff', '_exp'], 'i_eff').reindex(k).to_numpy()

Q = {'OUTRIGHT': (1.0,), 'CURVE': (-1.0, 1.0), 'FLY': (-1.0, 2.0, -1.0)}


def price(frame, icol, col, scale):
    """sum_i q_i * x_i * scale, per unit, using ordering `icol`."""
    w = np.empty(len(frame))
    for kind, q in Q.items():
        m = frame['kind'].to_numpy() == kind
        if m.any():
            w[m] = np.take(np.array(q), frame.loc[m, icol].to_numpy())
    s = pd.Series(w * frame[col].to_numpy() * scale, index=frame.index)
    return s.groupby(frame['package_id']).sum()


def n_ok(frame, icol):
    """units where `icol` is a valid 0..n-1 permutation (it always is)."""
    return frame.groupby('package_id')[icol].nunique()


unit = (df.sort_values(['package_id', 'i_can'])
          .groupby('package_id')
          .agg(kind=('kind', 'first'), rule=('rule', 'first'),
               n_legs=('n_legs', 'first'), as_of_date=('as_of_date', 'first'),
               dev=('deviation_bps', 'first'), rate_index=('rate_index', 'first'),
               dsign=('dealer_sign', 'first'), ddir=('dealer_direction', 'first'),
               bias=('mid_bias_bps', 'first'), p=('p', 'first'),
               sw=('signed_weight', 'first'), dz=('in_dead_zone', 'first'),
               excl=('exclusion_reason', 'first'), stt=('special_tenor_type', 'first'),
               vintage=('code_vintage', 'first'),
               nmid=('mid_pct', 'count'), offmkt=('is_off_market', 'max'),
               mac=('is_mac', 'max'), fwd=('forward_start_years', 'max'),
               nexp=('_exp', 'nunique'), neff=('_eff', 'nunique'),
               tenors=('tenor_label', lambda s: '/'.join(map(str, s))),
               ))
unit['grid_clean'] = unit['nmid'] == unit['n_legs']

for ic in ('i_can', 'i_phys', 'i_lo', 'i_tid', 'i_ten', 'i_eff'):
    unit['traded_' + ic] = price(df, ic, 'fixed_rate', 100.0 * 100.0)
    unit['mid_' + ic] = price(df, ic, 'mid_pct', 100.0)
    unit['err_' + ic] = (unit['traded_' + ic] - unit['mid_' + ic]) - unit['dev']

unit['dev_bps_rule'] = unit['rule']
unit.to_parquet(os.path.join(os.path.dirname(OUT), 'wfstr_unit_frame.parquet'))
print(f"\nunit frame: {len(unit):,} units")

# =========================================================================
print("\n" + "=" * 78)
print("[1] POPULATION AND GRID COVERAGE, by kind x rule")
print("=" * 78)
piv = unit.groupby(['kind', 'rule']).agg(
    n=('dev', 'size'), n_grid_clean=('grid_clean', 'sum'),
    n_excl_null=('excl', lambda s: int(s.isna().sum())))
piv['pct_clean'] = (100 * piv['n_grid_clean'] / piv['n']).round(1)
print(piv.to_string())

RATE = unit['rule'] == 'RATE_VS_MID'
CLEAN = unit['grid_clean'] & unit['excl'].isna()

# =========================================================================
print("\n" + "=" * 78)
print("[2] KNOWN-ANSWER: OUTRIGHT, rate rule, grid-clean")
print("=" * 78)
o = unit[RATE & CLEAN & (unit['kind'] == 'OUTRIGHT')]
e = o['err_i_can'].abs()
print(f"n={len(o):,}  median|err|={e.median():.3e}  max|err|={e.max():.3e} bp  "
      f"n<1e-9={int((e<1e-9).sum()):,}  n>=1e-6={int((e>=1e-6).sum()):,}")

# =========================================================================
print("\n" + "=" * 78)
print("[3] CLAIM UNDER TEST: CURVE / FLY, rate rule, grid-clean (join success only)")
print("=" * 78)
for kind in ('CURVE', 'FLY'):
    s = unit[RATE & CLEAN & (unit['kind'] == kind)]
    e = s['err_i_can'].abs()
    print(f"{kind:8s} n={len(s):6,}  median|err|={e.median():.3e}  "
          f"max|err|={e.max():.3e}  n<1e-9={int((e<1e-9).sum()):6,}  "
          f"n>=1e-6={int((e>=1e-6).sum()):,}")
    # the reversed / alternative orderings
    for ic in ('i_phys', 'i_lo', 'i_tid', 'i_ten', 'i_eff'):
        ee = s['err_' + ic].abs()
        print(f"           {ic:8s} median|err|={ee.median():.3e}  "
              f"max={ee.max():.3e}  n_exact={int((ee<1e-9).sum()):6,}")
    # reversed traded side only (the other agent's one-sided test)
    if kind == 'CURVE':
        rev = (-s['traded_i_can'] - s['mid_i_can']) - s['dev']
        print(f"           reversed-traded-only: median|err|={rev.abs().median():.4f} "
              f" max={rev.abs().max():.4f}  n_exact={int((rev.abs()<1e-9).sum())}")

# =========================================================================
print("\n" + "=" * 78)
print("[4] NEGATIVE CONTROL: same formula on NPV_VS_UPFRONT units")
print("=" * 78)
for kind in ('OUTRIGHT', 'CURVE', 'FLY'):
    s = unit[(unit['rule'] == 'NPV_VS_UPFRONT') & CLEAN & (unit['kind'] == kind)]
    if not len(s):
        continue
    e = s['err_i_can'].abs()
    print(f"{kind:8s} n={len(s):6,}  median|err|={e.median():.4f}  "
          f"p95={e.quantile(.95):.4f}  max={e.max():.4f}  "
          f"n_exact(<1e-9)={int((e<1e-9).sum()):,}")

# =========================================================================
print("\n" + "=" * 78)
print("[5] LEG-ORDER DISCRIMINATION")
print("=" * 78)
multi = df[df['kind'].isin(['CURVE', 'FLY'])]
for ic, lab in (('i_phys', 'physical(ctid)'), ('i_lo', 'leg_order'),
                ('i_tid', 'trade_id'), ('i_ten', 'tenor_years'),
                ('i_eff', 'effective_date')):
    diff = multi.groupby('package_id').apply(
        lambda g, c=ic: bool((g['i_can'].to_numpy() != g[c].to_numpy()).any()))
    ids = diff[diff].index
    sub = unit.loc[unit.index.intersection(ids)]
    subc = sub[RATE.reindex(sub.index) & CLEAN.reindex(sub.index)]
    print(f"{lab:16s} differs from canonical on {len(ids):6,} of "
          f"{len(diff):6,} multi-leg units;  grid-clean rate-rule subset: {len(subc):5,}")
    if len(subc):
        print(f"                 on THOSE units: canonical max|err|="
              f"{subc['err_i_can'].abs().max():.3e}   {lab} max|err|="
              f"{subc['err_' + ic].abs().max():.4f}  "
              f"{lab} n_exact={int((subc['err_' + ic].abs() < 1e-9).sum())}")

# =========================================================================
print("\n" + "=" * 78)
print("[6] TIES: CURVE units whose two legs share an expiration date")
print("=" * 78)
c = unit[unit['kind'] == 'CURVE']
tie_exp = c[c['nexp'] == 1]
tie_both = c[(c['nexp'] == 1) & (c['neff'] == 1)]
print(f"CURVE units total {len(c):,}; same expiration_date on both legs "
      f"{len(tie_exp):,}; same expiration AND effective {len(tie_both):,}")
if len(tie_exp):
    t = tie_exp[RATE.reindex(tie_exp.index).fillna(False)]
    print(t.groupby(['rule', 'grid_clean']).size().to_string())
    tc = t[t['grid_clean']]
    if len(tc):
        print(f"  grid-clean tie units n={len(tc)}  max|err|={tc['err_i_can'].abs().max():.3e}"
              f"  mid_bp range {tc['mid_i_can'].min():.4f}..{tc['mid_i_can'].max():.4f}")
    print(tie_exp[['kind', 'rule', 'tenors', 'grid_clean', 'dev']].head(10).to_string())

# =========================================================================
print("\n" + "=" * 78)
print("[7] TAILS: largest |err| rows among rate-rule grid-clean CURVE/FLY")
print("=" * 78)
s = unit[RATE & CLEAN & unit['kind'].isin(['CURVE', 'FLY'])]
t = s.reindex(s['err_i_can'].abs().sort_values(ascending=False).index).head(12)
print(t[['kind', 'as_of_date', 'rate_index', 'tenors', 'dev', 'traded_i_can',
         'mid_i_can', 'err_i_can', 'stt', 'offmkt', 'vintage']].to_string())

print("\n[7b] err by code_vintage (rate-rule grid-clean CURVE+FLY)")
print(s.groupby('vintage')['err_i_can'].agg(
    n='size', med=lambda x: x.abs().median(), mx=lambda x: x.abs().max()).to_string())
print("\n[7c] err by month")
s2 = s.copy(); s2['m'] = pd.to_datetime(s2['as_of_date']).dt.to_period('M').astype(str)
print(s2.groupby('m')['err_i_can'].agg(
    n='size', mx=lambda x: x.abs().max()).to_string())
