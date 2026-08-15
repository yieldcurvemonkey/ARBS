import pickle
import pandas as pd
import numpy as np

pd.set_option('display.width', 300)
pd.set_option('display.max_colwidth', 110)
pd.set_option('display.max_rows', 400)

P = 'C:/Users/chris/clee/ARBS-fe/scratch/'
df = pd.read_pickle(P + 'wfstr_ik5_units2.pkl')
GRID = pickle.load(open(P + 'wfstr_ik5_grid.pkl', 'rb'))
tt = df.trade_type.fillna('')
stt = df.special_tenor_type.fillna('')

fam = np.select(
    [tt.str.startswith('SPREADOVER'),
     tt.str.startswith('MATCHED_MATURITY') | (stt == 'MATCHED_MATURITY'),
     tt.str.startswith('INVOICE') | (stt == 'INVOICE_SWAP'),
     tt.str.startswith('BASIS') | (df.rate_index == 'BASIS'),
     df.is_mac | (stt == 'MAC')],
    ['ASW_SPREADOVER', 'ASW_MATCHED_MATURITY', 'ASW_INVOICE', 'BASIS', 'MAC'],
    default='RATE')
df['family'] = fam

df['key'] = df.kind + '|' + df.rate_index + '|' + df.family + '|' + df.tup_fwd_disp
df['key_lo'] = df.kind + '|' + df.rate_index + '|' + df.family + '|' + df.tup_fwd_disp_lo
df['key_ty'] = df.kind + '|' + df.rate_index + '|' + df.family + '|' + df.tup_fwd_disp_ty
df['key_literal'] = df.kind + '|' + df.rate_index + '|' + df.tup_disp
df['key_v1'] = (df.kind + '|' + df.rate_index + '|' + df.special_tenor_type + '|'
                + df.family + '|' + df.tup_fwd_disp)

print(f"units={len(df)}  {df.as_of_date.min()}..{df.as_of_date.max()} "
      f"days={df.as_of_date.nunique()}  CURVE={int((df.kind=='CURVE').sum())} "
      f"FLY={int((df.kind=='FLY').sum())}")
print("family mix:")
print(pd.crosstab(df.family, df.kind).to_string())
print()

print("=" * 110)
print("A. KEY on hand-checked packages")
print("=" * 110)
pk = ['CURVE_14_4646203141000000701', 'CURVE_18_4647210006000000101',
      'CURVE_15_4646577783000000101', 'CURVE_16_4646806983000000401',
      'CURVE_12_4645295537000000101', 'CURVE_27_4648113837000000201']
print(df[df.package_id.isin(pk)][['package_id', 'trade_type', 'key']].to_string(index=False))
print()

print("=" * 110)
print("B. LITERAL KEY (kind+tenor_display tuple+rate_index) COLLISIONS")
print("=" * 110)
print(f"distinct literal keys={df.key_literal.nunique()}   distinct final keys={df.key.nunique()}")
coll = df.groupby('key_literal')['key'].nunique()
bad = coll[coll > 1]
nu = df[df.key_literal.isin(bad.index)].shape[0]
print(f"literal keys lumping >1 instrument: {len(bad)}/{len(coll)}; "
      f"units affected {nu} ({100*nu/len(df):.1f}%)")
for k in bad.sort_values(ascending=False).index[:6]:
    sub = df[df.key_literal == k]
    print(f"\n  LITERAL {k}  ({len(sub)} units) -> {sub.key.nunique()} instruments; top:")
    for kk, n in sub.key.value_counts().head(5).items():
        print(f"     {n:6d}  {kk}")
print()

print("=" * 110)
print("C. CANONICAL SORT")
print("=" * 110)
print(f"units where leg_order tuple != canonical tuple: "
      f"{int((df.tup_fwd_disp != df.tup_fwd_disp_lo).sum())} "
      f"({100*(df.tup_fwd_disp != df.tup_fwd_disp_lo).mean():.2f}%)")
frag = df.groupby('key')['key_lo'].nunique()
fk = frag[frag > 1]
print(f"instruments that SPLIT into >1 key if leg_order trusted: {len(fk)}/{len(frag)} "
      f"({df[df.key.isin(fk.index)].shape[0]} units)")
print(f"units where ORDER BY tenor_years != ORDER BY (effective,expiration): "
      f"{int((df.tup_fwd_disp != df.tup_fwd_disp_ty).sum())}")
fragty = df.groupby('key')['key_ty'].nunique()
fkty = fragty[fragty > 1]
print(f"instruments that SPLIT if sorted by tenor_years: {len(fkty)}/{len(fragty)} "
      f"({df[df.key.isin(fkty.index)].shape[0]} units)")
print("  examples of tenor_years mis-sort:")
sub = df[(df.tup_fwd_disp != df.tup_fwd_disp_ty)]
print(sub[['package_id', 'special_tenor_type', 'tup_fwd_disp', 'tup_fwd_disp_ty']]
      .head(6).to_string(index=False))
print()
print("  over-split test: does keeping special_tenor_type in the key fragment instruments?")
f2 = df.groupby('key')['key_v1'].nunique()
f2b = f2[f2 > 1]
print(f"    keys that split when special_tenor_type is added: {len(f2b)} "
      f"({df[df.key.isin(f2b.index)].shape[0]} units)")
for k in f2b.sort_values(ascending=False).index[:4]:
    sub = df[df.key == k]
    print(f"      {k} ({len(sub)}) -> {dict(sub.special_tenor_type.value_counts())}")
print()

print("=" * 110)
print("D. DISTINCT KEYS / CONCENTRATION")
print("=" * 110)
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    vc = s.key.value_counts()
    print(f"{kind}: units={len(s)}  distinct keys={len(vc)}  "
          f"(RATE-family only: {s[s.family=='RATE'].key.nunique()})")
    print("   " + "  ".join(f"top{n}={100*vc.head(n).sum()/len(s):.0f}%"
                            for n in (5, 10, 15, 25, 50, 100)))
    print(f"   keys with >=10 prints: {(vc>=10).sum()}  >=50: {(vc>=50).sum()}  "
          f">=100: {(vc>=100).sum()}  >=300: {(vc>=300).sum()}")
print()


def show_top(kind, n=15, filt=None, label=''):
    s = df[df.kind == kind]
    if filt is not None:
        s = s[filt(s)]
    vc = s.key.value_counts().head(n)
    rows = []
    for k, cnt in vc.items():
        sub = s[s.key == k]
        cell = sub.groupby(['as_of_date', 'venue_class']).size()
        rows.append(dict(key=k, prints=cnt, days=sub.as_of_date.nunique(),
                         per_day=round(cnt / sub.as_of_date.nunique(), 1),
                         med_day_venue=int(cell.median()), max_day_venue=int(cell.max()),
                         priced=int(sub.deviation_bps.notna().sum()),
                         D2C=int((sub.venue_class == 'D2C').sum()),
                         D2D=int((sub.venue_class == 'D2D').sum()),
                         UNK=int((sub.venue_class == 'VENUE_UNKNOWN').sum())))
    out = pd.DataFrame(rows)
    print(f"--- TOP {n} {kind} {label} ---")
    print(out.to_string(index=False))
    print()
    return out


print("=" * 110)
print("E. BUSIEST STRUCTURES (60 published days 2026-05-13..2026-08-07)")
print("=" * 110)
show_top('CURVE', 15)
show_top('FLY', 15)
show_top('CURVE', 10, filt=lambda s: s.family != 'RATE', label='[NON-RATE families]')
show_top('FLY', 6, filt=lambda s: s.family != 'RATE', label='[NON-RATE families]')

print("=" * 110)
print("F. PRINTS PER (as_of_date, key, venue_class)")
print("=" * 110)
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    cell = s.groupby(['as_of_date', 'key', 'venue_class']).size()
    cellp = s[s.deviation_bps.notna()].groupby(['as_of_date', 'key', 'venue_class']).size()
    celldk = s.groupby(['as_of_date', 'key']).size()
    print(f"\n### {kind}: {len(cell)} (day,key,venue) cells / {cell.sum()} prints; "
          f"{len(celldk)} (day,key) cells")
    for nm, c in (('day,key,venue     ', cell), ('day,key,venue PRICED', cellp),
                  ('day,key (venue merged)', celldk)):
        print(f"  {nm}: mean={c.mean():.2f} p50={c.quantile(.5):.0f} "
              f"p75={c.quantile(.75):.0f} p90={c.quantile(.9):.0f} "
              f"p95={c.quantile(.95):.0f} p99={c.quantile(.99):.0f} max={c.max()}")
        print("      " + "  ".join(f">={t}:{100*(c>=t).mean():.0f}%" for t in (2, 3, 5, 10, 20)))
    topk = set(s.key.value_counts().head(15).index)
    c2 = cell[cell.index.get_level_values('key').isin(topk)]
    print(f"  TOP-15 keys only ({len(c2)} cells): mean={c2.mean():.2f} "
          f"p50={c2.quantile(.5):.0f} p75={c2.quantile(.75):.0f} "
          f"p90={c2.quantile(.9):.0f} max={c2.max()}")
    print("      " + "  ".join(f">={t}:{100*(c2>=t).mean():.0f}%" for t in (2, 3, 5, 10, 20)))
    # venue mix of the cells
    print("  cells by venue_class: " +
          str(dict(cell.groupby(level='venue_class').agg(['size', 'mean']).round(2)
                   .apply(lambda r: (int(r['size']), r['mean']), axis=1))))
print()

print("=" * 110)
print("G. GRID COVERAGE")
print("=" * 110)
df['tenors_in_grid'] = df.apply(
    lambda r: bool(GRID.get(r.rate_index)) and all(t in GRID[r.rate_index]
                                                   for t in r.tenor_labels), axis=1)
df['constructible'] = df.tenors_in_grid & df.all_spot & (~df.any_fuzzy)
df['constructible_loose'] = df.tenors_in_grid & df.all_spot
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    print(f"\n### {kind} n={len(s)}")
    print(f"  (a) every de-fuzzed leg tenor_label in the grid  : "
          f"{100*s.tenors_in_grid.mean():5.1f}%  ({int(s.tenors_in_grid.sum())})")
    print(f"  (b) (a) AND every leg spot-starting              : "
          f"{100*s.constructible_loose.mean():5.1f}%  ({int(s.constructible_loose.sum())})")
    print(f"  (c) (b) AND no fuzzy (~) leg                     : "
          f"{100*s.constructible.mean():5.1f}%  ({int(s.constructible.sum())})")
    print(f"      all legs spot alone: {100*s.all_spot.mean():.1f}%   "
          f"any fuzzy leg: {100*s.any_fuzzy.mean():.1f}%")
    b = s.groupby('family').agg(n=('package_id', 'size'),
                                in_grid=('tenors_in_grid', 'mean'),
                                all_spot=('all_spot', 'mean'),
                                constructible=('constructible', 'mean'))
    b[['in_grid', 'all_spot', 'constructible']] *= 100
    print(b.round(1).to_string())
    b2 = s.groupby('special_tenor_type').agg(n=('package_id', 'size'),
                                             in_grid=('tenors_in_grid', 'mean'),
                                             all_spot=('all_spot', 'mean'),
                                             constructible=('constructible', 'mean'))
    b2[['in_grid', 'all_spot', 'constructible']] *= 100
    print(b2.round(1).to_string())
    topk = set(s.key.value_counts().head(15).index)
    t = s[s.key.isin(topk)]
    print(f"  top-15 keys: in_grid={100*t.tenors_in_grid.mean():.1f}% "
          f"constructible={100*t.constructible.mean():.1f}% of {len(t)} units")
print()
print("rate_index breakdown (CURVE+FLY):")
ri = df.groupby('rate_index').agg(n=('package_id', 'size'),
                                  in_grid=('tenors_in_grid', 'mean'),
                                  constructible=('constructible', 'mean'))
ri[['in_grid', 'constructible']] *= 100
print(ri.round(1).to_string())
print()

print("=" * 110)
print("H. 2026-08-07  CURVE 10Y/30Y SOFR")
print("=" * 110)
d = df[df.as_of_date.astype(str) == '2026-08-07']
print(f"units on 2026-08-07: {len(d)} (CURVE {int((d.kind=='CURVE').sum())}, "
      f"FLY {int((d.kind=='FLY').sum())})")
c = d[(d.kind == 'CURVE') & (d.rate_index == 'SOFR')]
c1030 = c[c.tenor_labels.map(lambda a: list(a) == ['10Y', '30Y'])]
print(f"CURVE/SOFR units: {len(c)};  de-fuzzed tenor tuple == 10Y/30Y: {len(c1030)}")
t = c1030.groupby(['key', 'venue_class']).size().unstack(fill_value=0)
t['TOTAL'] = t.sum(1)
print(t.sort_values('TOTAL', ascending=False).to_string())
HK = 'CURVE|SOFR|RATE|SPOT:10Y/SPOT:30Y'
h = c1030[c1030.key == HK]
print(f"\nHEADLINE key {HK}")
print(f"  prints={len(h)}  priced={int(h.deviation_bps.notna().sum())}")
print("  by venue_class : " + str(dict(h.venue_class.value_counts())))
print("  priced by venue: " + str(dict(h[h.deviation_bps.notna()].venue_class.value_counts())))
print("  tape_labels present in this one instrument on this one day:")
print(h.tape_label_min.value_counts().to_string())
print("\n  what a tape_label-keyed UI would show for "
      "'USD-SOFR-COMPOUND 1D Constant Spot 10Y/30Y CURVE PHYS':")
print(f"    {int((h.tape_label_min == 'USD-SOFR-COMPOUND 1D Constant Spot 10Y/30Y CURVE PHYS').sum())} of {len(h)} prints")
print("\n  same-day 10Y/30Y in OTHER families (excluded by the key):")
print(c1030[c1030.family != 'RATE'].groupby(['family', 'key']).size().to_string())

print("\n60-day per-day history of the headline instrument:")
hh = df[df.key == HK]
pv = hh.groupby(['as_of_date', 'venue_class']).size().unstack(fill_value=0)
pv['TOTAL'] = pv.sum(1)
print(f"  prints={len(hh)} over {hh.as_of_date.nunique()} days; per-day "
      f"p50={pv.TOTAL.median():.0f} mean={pv.TOTAL.mean():.1f} "
      f"min={pv.TOTAL.min()} max={pv.TOTAL.max()}")
print(f"  days with >=2: {100*(pv.TOTAL>=2).mean():.0f}%  >=5: "
      f"{100*(pv.TOTAL>=5).mean():.0f}%  >=10: {100*(pv.TOTAL>=10).mean():.0f}%")
print("\n  tape_label fragmentation of this instrument over 60 days:")
print(hh.tape_label_min.value_counts().to_string())

df.to_pickle(P + 'wfstr_ik5_units2_keyed.pkl')
print("\nDONE")
