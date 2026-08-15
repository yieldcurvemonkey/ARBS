import pandas as pd
P = 'C:/Users/chris/clee/ARBS-fe/scratch/'
df = pd.read_pickle(P + 'wfstr_ik5_units2_keyed.pkl')
cf = df[df.kind.isin(['CURVE', 'FLY'])]
print("COMBINED CURVE+FLY n=%d" % len(cf))
print("  (a) in_grid            %.1f%% (%d)" % (100*cf.tenors_in_grid.mean(),
                                                cf.tenors_in_grid.sum()))
print("  (b) in_grid & all_spot %.1f%% (%d)" % (100*cf.constructible_loose.mean(),
                                                cf.constructible_loose.sum()))
print("  (c) (b) & no fuzzy     %.1f%% (%d)" % (100*cf.constructible.mean(),
                                                cf.constructible.sum()))
print()
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    cell = s.groupby(['as_of_date', 'key', 'venue_class']).size()
    topk = set(s.key.value_counts().head(15).index)
    c2 = cell[cell.index.get_level_values('key').isin(topk)]
    print(f"{kind}: cells={len(cell)} p50={cell.quantile(.5):.0f} p75={cell.quantile(.75):.0f} "
          f"p90={cell.quantile(.9):.0f} p95={cell.quantile(.95):.0f} "
          f"p99={cell.quantile(.99):.0f} max={cell.max()} mean={cell.mean():.2f} | "
          f"top15: p50={c2.quantile(.5):.0f} p75={c2.quantile(.75):.0f} "
          f"p90={c2.quantile(.9):.0f} max={c2.max()} mean={c2.mean():.2f}")
    print(f"   share of cells >=3: {100*(cell>=3).mean():.0f}%  >=5: {100*(cell>=5).mean():.0f}%"
          f"   | top15 >=3: {100*(c2>=3).mean():.0f}%  >=5: {100*(c2>=5).mean():.0f}%")
    # how many keys clear a 'chartable' bar on a typical day
    for thr in (3, 5, 10):
        per_day_keys = (cell[cell >= thr].groupby(level='as_of_date').size())
        print(f"   keys with >={thr} prints in a (day,venue) cell: median {per_day_keys.median():.0f} per day")
print()
# provenance gain: units whose tape_label is generic PKG-N
gen = cf.tape_label_min.str.contains('PKG-', na=False)
print(f"CURVE/FLY units whose tape_label is a generic PKG-N (no tenors in the label): "
      f"{int(gen.sum())} ({100*gen.mean():.1f}%)")
print(cf[gen].kind.value_counts().to_string())
# tape_label fragmentation overall
frag = cf.groupby('key')['tape_label_min'].nunique()
print(f"\ninstruments (keys) served by >1 distinct tape_label: {int((frag>1).sum())} of {len(frag)}"
      f"; units in them: {int(cf[cf.key.isin(frag[frag>1].index)].shape[0])} "
      f"({100*cf[cf.key.isin(frag[frag>1].index)].shape[0]/len(cf):.1f}%)")
nkeys_per_label = cf.groupby('tape_label_min')['key'].nunique()
print(f"tape_labels covering >1 instrument: {int((nkeys_per_label>1).sum())} of {len(nkeys_per_label)}")
