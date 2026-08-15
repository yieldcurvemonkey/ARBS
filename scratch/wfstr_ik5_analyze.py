import pickle
import pandas as pd
import numpy as np

pd.set_option('display.width', 260)
pd.set_option('display.max_colwidth', 100)
pd.set_option('display.max_rows', 300)

P = 'C:/Users/chris/clee/ARBS-fe/scratch/'
df = pd.read_pickle(P + 'wfstr_ik5_units.pkl')
GRID = pickle.load(open(P + 'wfstr_ik5_grid.pkl', 'rb'))

print(f"units={len(df)}  window={df.as_of_date.min()}..{df.as_of_date.max()}  "
      f"days={df.as_of_date.nunique()}")
print(df.kind.value_counts().to_dict())
print("n_joined == n_legs for all:", bool((df.n_joined == df.n_legs).all()))
print()

df['asw'] = np.where(df.is_asw, 'ASW', 'RATE')

# ---------------- key definitions ----------------
# LITERAL (as the task proposed): kind + ordered tenor_display tuple + rate_index
df['key_literal'] = df.kind + '|' + df.rate_index + '|' + df.tup_disp_canon
# FULL (recommended)
df['key_full'] = (df.kind + '|' + df.rate_index + '|' + df.special_tenor_type
                  + '|' + df.asw + '|' + df.tup_full_canon)
# leg_order variant of the full key (uncanonicalised)
df['key_full_legorder'] = (df.kind + '|' + df.rate_index + '|' + df.special_tenor_type
                           + '|' + df.asw + '|' + df.tup_full_legorder)

print("=" * 100)
print("A. KEY VALIDATION on hand-inspected packages (2026-08-07)")
print("=" * 100)
pk = ['CURVE_14_4646203141000000701', 'CURVE_18_4647210006000000101',
      'CURVE_15_4646577783000000101', 'CURVE_16_4646806983000000401',
      'CURVE_12_4645295537000000101', 'CURVE_27_4648113837000000201']
print(df[df.package_id.isin(pk)][
    ['package_id', 'key_literal', 'key_full']].to_string(index=False))
print()

print("=" * 100)
print("B. IS THE LITERAL KEY (kind + tenor_display tuple + rate_index) SUFFICIENT?")
print("=" * 100)
print(f"distinct key_literal (CURVE+FLY) = {df.key_literal.nunique()}")
print(f"distinct key_full    (CURVE+FLY) = {df.key_full.nunique()}")
coll = df.groupby('key_literal')['key_full'].nunique()
bad = coll[coll > 1].sort_values(ascending=False)
n_units_collided = df[df.key_literal.isin(bad.index)].shape[0]
print(f"literal keys that lump >1 real instrument: {len(bad)} / {len(coll)} "
      f"({n_units_collided} units = {100*n_units_collided/len(df):.1f}% of CURVE+FLY)")
print("\nworst literal collisions:")
for k in bad.index[:8]:
    sub = df[df.key_literal == k]
    print(f"  LITERAL {k}   ({len(sub)} units) splits into {sub.key_full.nunique()}:")
    for kf, n in sub.key_full.value_counts().head(6).items():
        print(f"      {n:6d}  {kf}")
print()

print("=" * 100)
print("C. MUST THE TUPLE BE CANONICALLY SORTED?")
print("=" * 100)
mism = df[df.tup_full_canon != df.tup_full_legorder]
print(f"units whose leg_order tuple != canonical tuple: {len(mism)} / {len(df)} "
      f"({100*len(mism)/len(df):.2f}%)")
print(mism.kind.value_counts().to_dict())
# how many keys would be fragmented if we trusted leg_order
frag = df.groupby('key_full')['key_full_legorder'].nunique()
fk = frag[frag > 1]
n_frag_units = df[df.key_full.isin(fk.index)].shape[0]
print(f"instruments that would SPLIT into >1 key if leg_order were trusted: "
      f"{len(fk)} / {len(frag)}  ({n_frag_units} units affected)")
print("examples:")
for k in fk.sort_values(ascending=False).index[:5]:
    sub = df[df.key_full == k]
    print(f"  {k}  ({len(sub)} units) -> {sorted(sub.key_full_legorder.unique())}")
# sorting by tenor_years instead of dates
ty_bad = df[df.tup_disp_tenyrs != df.tup_disp_canon]
print(f"\nunits where ORDER BY tenor_years differs from ORDER BY (effective,expiration): "
      f"{len(ty_bad)}")
print(ty_bad.groupby(['kind', 'special_tenor_type']).size().to_dict())
if len(ty_bad):
    print(ty_bad[['package_id', 'special_tenor_type', 'tup_disp_canon',
                  'tup_disp_tenyrs', 'tup_full_canon']].head(8).to_string(index=False))
print()

print("=" * 100)
print("D. HOW MANY DISTINCT STRUCTURE KEYS  (60 published days)")
print("=" * 100)
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    print(f"{kind}: units={len(s)}  distinct key_full={s.key_full.nunique()}  "
          f"distinct key_literal={s.key_literal.nunique()}")
    # concentration
    vc = s.key_full.value_counts()
    for topn in (5, 10, 15, 25, 50, 100):
        print(f"    top{topn:4d} keys cover {100*vc.head(topn).sum()/len(s):5.1f}% of prints")
    print(f"    keys with >=1 print: {len(vc)};  >=10: {(vc>=10).sum()};  "
          f">=50: {(vc>=50).sum()};  >=100: {(vc>=100).sum()}")
print()


def show_top(kind, n=15, only=None, label=''):
    s = df[df.kind == kind]
    if only is not None:
        s = s[only(s)]
    vc = s.key_full.value_counts().head(n)
    rows = []
    for k, cnt in vc.items():
        sub = s[s.key_full == k]
        rows.append(dict(
            key=k, prints=cnt,
            days=sub.as_of_date.nunique(),
            per_day=round(cnt / sub.as_of_date.nunique(), 1),
            priced=int(sub.deviation_bps.notna().sum()),
            D2C=int((sub.venue_class == 'D2C').sum()),
            D2D=int((sub.venue_class == 'D2D').sum()),
            UNK=int((sub.venue_class == 'VENUE_UNKNOWN').sum()),
        ))
    out = pd.DataFrame(rows)
    print(f"--- TOP {n} {kind} {label} (60 published days 2026-05-13..2026-08-07) ---")
    print(out.to_string(index=False))
    print()
    return out


print("=" * 100)
print("E. BUSIEST STRUCTURES")
print("=" * 100)
top_curve = show_top('CURVE', 15)
top_fly = show_top('FLY', 15)
show_top('CURVE', 12, only=lambda s: (s.special_tenor_type == 'STANDARD') & (~s.is_asw),
         label='[STANDARD spot-family, non-ASW]')
show_top('FLY', 12, only=lambda s: (s.special_tenor_type == 'STANDARD') & (~s.is_asw),
         label='[STANDARD spot-family, non-ASW]')

print("=" * 100)
print("F. PRINTS PER (as_of_date, structure key, venue_class)")
print("=" * 100)
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    cell = s.groupby(['as_of_date', 'key_full', 'venue_class']).size()
    cell_p = (s[s.deviation_bps.notna()]
              .groupby(['as_of_date', 'key_full', 'venue_class']).size())
    print(f"\n### {kind}: {len(cell)} non-empty (day,key,venue) cells, {cell.sum()} prints")
    qs = [.5, .75, .9, .95, .99]
    print("  ALL cells      p50/p75/p90/p95/p99/max = "
          + "/".join(f"{cell.quantile(x):.0f}" for x in qs) + f"/{cell.max()}"
          + f"   mean={cell.mean():.2f}")
    print("  priced-only    p50/p75/p90/p95/p99/max = "
          + "/".join(f"{cell_p.quantile(x):.0f}" for x in qs) + f"/{cell_p.max()}"
          + f"   mean={cell_p.mean():.2f}")
    for thr in (2, 3, 5, 10, 20):
        print(f"    cells with >={thr:2d} prints: {100*(cell>=thr).mean():5.1f}%  "
              f"({(cell>=thr).sum():5d} cells, holding "
              f"{100*cell[cell>=thr].sum()/cell.sum():5.1f}% of prints)")
    # restricted to top-15 keys
    topk = set(s.key_full.value_counts().head(15).index)
    c2 = cell[cell.index.get_level_values('key_full').isin(topk)]
    print(f"  -- restricted to the top-15 keys ({len(c2)} cells) --")
    print("     p50/p75/p90/p95/max = "
          + "/".join(f"{c2.quantile(x):.0f}" for x in [.5, .75, .9, .95]) + f"/{c2.max()}"
          + f"   mean={c2.mean():.2f}")
    for thr in (2, 3, 5, 10, 20):
        print(f"     cells with >={thr:2d} prints: {100*(c2>=thr).mean():5.1f}%")
    # ignoring venue split (day,key only)
    cell_dk = s.groupby(['as_of_date', 'key_full']).size()
    print(f"  -- venue merged (day,key): {len(cell_dk)} cells, "
          f"p50/p75/p90/p95/max = "
          + "/".join(f"{cell_dk.quantile(x):.0f}" for x in [.5, .75, .9, .95])
          + f"/{cell_dk.max()}")
    for thr in (2, 3, 5, 10, 20):
        print(f"     cells with >={thr:2d} prints: {100*(cell_dk>=thr).mean():5.1f}%")
print()

print("=" * 100)
print("G. GRID COVERAGE: can a continuous mid be drawn?")
print("=" * 100)


def cover(row):
    g = GRID.get(row.rate_index)
    if g is None:
        return False
    return all(t in g for t in row.tenor_labels)


df['tenors_in_grid'] = df.apply(cover, axis=1)
df['constructible'] = df.tenors_in_grid & df.all_spot
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    print(f"\n### {kind}  (n={len(s)})")
    print(f"  (a) LITERAL  - every leg tenor_label in the {kind}'s rate_index grid: "
          f"{100*s.tenors_in_grid.mean():.1f}%  ({s.tenors_in_grid.sum()})")
    print(f"  (b) CONSTRUCTIBLE - (a) AND every leg spot-starting:                 "
          f"{100*s.constructible.mean():.1f}%  ({s.constructible.sum()})")
    print(f"      all legs spot-starting alone:                                    "
          f"{100*s.all_spot.mean():.1f}%")
    br = s.groupby('special_tenor_type').agg(
        n=('package_id', 'size'),
        tenors_in_grid=('tenors_in_grid', 'mean'),
        all_spot=('all_spot', 'mean'),
        constructible=('constructible', 'mean'))
    br[['tenors_in_grid', 'all_spot', 'constructible']] *= 100
    print(br.round(1).to_string())
    ri = s.groupby('rate_index').agg(
        n=('package_id', 'size'),
        tenors_in_grid=('tenors_in_grid', 'mean'),
        constructible=('constructible', 'mean'))
    ri[['tenors_in_grid', 'constructible']] *= 100
    print(ri.round(1).to_string())

# which tenors are the misses
miss = []
for _, r in df[~df.tenors_in_grid].iterrows():
    g = GRID.get(r.rate_index, set())
    for t in r.tenor_labels:
        if t not in g:
            miss.append((r.rate_index, t))
mv = pd.Series([f"{a}:{b}" for a, b in miss]).value_counts()
print("\ntop missing (rate_index:tenor_label) among units failing the grid test:")
print(mv.head(25).to_string())
print()

# constructible restricted to the top-15 keys
for kind in ('CURVE', 'FLY'):
    s = df[df.kind == kind]
    topk = set(s.key_full.value_counts().head(15).index)
    t = s[s.key_full.isin(topk)]
    print(f"{kind} top-15 keys: constructible = {100*t.constructible.mean():.1f}% "
          f"of {len(t)} units")
print()

print("=" * 100)
print("H. 2026-08-07  'CURVE 10Y/30Y SOFR'  by venue_class")
print("=" * 100)
d = df[(df.as_of_date == pd.Timestamp('2026-08-07').date()) |
       (df.as_of_date.astype(str) == '2026-08-07')]
c = d[(d.kind == 'CURVE') & (d.rate_index == 'SOFR')]
c1030 = c[c.tup_lbl_canon == '10Y/30Y']
print(f"all CURVE SOFR units 2026-08-07: {len(c)};  with de-fuzzed tenor tuple 10Y/30Y: "
      f"{len(c1030)}")
print("\nby FULL key:")
print(c1030.groupby(['key_full', 'venue_class']).size().unstack(fill_value=0)
      .assign(TOTAL=lambda x: x.sum(1)).sort_values('TOTAL', ascending=False).to_string())
print("\nheadline - the instrument the user means "
      "(CURVE|SOFR|STANDARD|RATE|SPOT:10Y/SPOT:30Y):")
hk = 'CURVE|SOFR|STANDARD|RATE|SPOT:10Y/SPOT:30Y'
h = c1030[c1030.key_full == hk]
print(f"  total prints                 : {len(h)}")
print(h.venue_class.value_counts().to_string())
print(f"  priced (deviation_bps not null): {int(h.deviation_bps.notna().sum())}")
print(h[h.deviation_bps.notna()].venue_class.value_counts().to_string())
print("\n  what a tape_label key would have shown instead:")
print()

print("=" * 100)
print("I. per-day counts for the headline instrument over the window")
print("=" * 100)
hh = df[df.key_full == hk]
pv = hh.groupby(['as_of_date', 'venue_class']).size().unstack(fill_value=0)
pv['TOTAL'] = pv.sum(1)
print(pv.tail(20).to_string())
print(f"\nper-day TOTAL: p50={pv.TOTAL.median():.0f} mean={pv.TOTAL.mean():.1f} "
      f"max={pv.TOTAL.max()} min={pv.TOTAL.min()} days={len(pv)}")

df.to_pickle(P + 'wfstr_ik5_units_keyed.pkl')
print("\nDONE")
