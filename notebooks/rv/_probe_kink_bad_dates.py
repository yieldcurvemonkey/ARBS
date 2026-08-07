"""Probe: is 2025-07-04 a corrupt slot mapping in the SFR fly panel?

2025-07-04 is a US market holiday. If the panel carries a row for it built from
a handful of stale back-month prints, the strip slots on that date are not the
strip -- they are whichever contracts happened to have a settle -- and every
structure keyed on that date is mislabelled.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd

DATA = REPO / "notebooks" / "data" / "sfr_fly_meanrev"
pd.set_option("display.width", 240, "display.max_columns", 40)

c = pd.read_parquet(DATA / "contracts.parquet")
c["as_of"] = pd.to_datetime(c["as_of"])
n_per_date = c.groupby("as_of").size().sort_values()
print("=== contracts per as_of, smallest 8 ===", flush=True)
print(n_per_date.head(8).to_string(), flush=True)

thin = n_per_date[n_per_date < 16]
print(f"\ndates with < 16 contracts: {len(thin)}", flush=True)
for d in thin.index:
    g = c[c["as_of"] == d].sort_values("imm_start")
    print(f"  {d.date()}  n={len(g)}  codes={list(g['code'])}", flush=True)
    print(f"     imm_start {g['imm_start'].min()} -> {g['imm_start'].max()}", flush=True)
    print(f"     OI {list(g['open_interest'])}  vol {list(g['volume'])}", flush=True)

sp = pd.read_parquet(DATA / "slot_panel.parquet")
sp.index = pd.to_datetime(sp.index)
sp.columns = [int(x) for x in sp.columns]
print("\n=== slot_panel around each thin date ===", flush=True)
for d in thin.index:
    lo = sp.index[sp.index < d][-1]
    hi = sp.index[sp.index > d][0] if (sp.index > d).any() else d
    print(sp.loc[[lo, d, hi], [1, 2, 3, 4, 8, 12, 16]].to_string(), flush=True)
    print(f"   front-slot jump into  {d.date()}: "
          f"{100 * (sp.at[d, 1] - sp.at[lo, 1]):+.1f}bp", flush=True)
    print(f"   front-slot jump out of {d.date()}: "
          f"{100 * (sp.at[hi, 1] - sp.at[d, 1]):+.1f}bp", flush=True)

print("\n=== is it a US market holiday? ===", flush=True)
for d in thin.index:
    print(f"  {d.date()}  weekday={d.day_name()}", flush=True)

s3 = pd.read_parquet(DATA / "structures_3m.parquet")
s3["as_of"] = pd.to_datetime(s3["as_of"])
print("\n=== structures_3m on the thin dates ===", flush=True)
for d in thin.index:
    g = s3[s3["as_of"] == d]
    print(g[["key", "cm_label_short", "value", "cm_slot"]].to_string(index=False),
          flush=True)
    prev = s3[(s3["as_of"] < d)]["as_of"].max()
    p = s3[(s3["as_of"] == prev) & (s3["cm_label_short"] == "SFR123")]
    print(f"  SFR123 on {prev.date()}: key={p['key'].iloc[0]} "
          f"value={p['value'].iloc[0]:+.2f}", flush=True)

print("\n=== float-noise values (not on the 0.25bp settlement grid) ===", flush=True)
v = s3["value"].to_numpy()
off = np.abs(v / 0.25 - np.round(v / 0.25)) > 1e-6
print(f"  {off.sum()} of {len(v)} rows off-grid", flush=True)
if off.any():
    print(s3[off][["as_of", "key", "value"]].head(12).to_string(index=False), flush=True)

print("\n=== negative rates (2020 episode) ===", flush=True)
neg = c[c["rate_pct"] < 0]
print(f"  {len(neg)} rows, {neg['as_of'].min()} -> {neg['as_of'].max()}, "
      f"codes={sorted(neg['code'].unique())}", flush=True)
print("DONE", flush=True)
