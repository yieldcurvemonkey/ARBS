import os, sys, datetime
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd
from SDRUtils.dealer_direction import lineage as lin

ROOT = r"C:/Users/chris/clee/ARBS-dd/scratch/dd_lineage_store"
DAYS = [datetime.date(2026, 6, d) for d in (15, 16, 17, 18)]
raw = lin.load_raw_days(DAYS, root=ROOT)
DI, ODI = lin.DI, lin.ODI

ids = raw[DI].map(lin.normalise_id)
ptr = raw[ODI].map(lin.normalise_id)
print("rows", len(raw), " distinct DI", ids.nunique(), " with pointer", int(ptr.notna().sum()))
print("self-pointers (ODI == DI):", int((ids == ptr).sum()))

known = set(ids.dropna())
have_ptr = ptr.notna()
tgt_in_window = ptr[have_ptr].isin(known)
print("pointer targets present in the window:", int(tgt_in_window.sum()), "of", int(have_ptr.sum()))

# of those in-window targets, how many themselves carry a pointer?
parent = {}
for i, di in ids.items():
    p = ptr.get(i)
    if di is not None and p is not None and p != di:
        parent[di] = p
tgt = ptr[have_ptr & tgt_in_window]
two_hop = tgt.isin(set(parent))
print("in-window targets that themselves carry a pointer (=> hop 2 available):", int(two_hop.sum()))

# the TERM->TERM population specifically
act = raw.set_index(ids)["Action type"]
act = act[~act.index.duplicated()]
t = raw[(raw["Action type"] == "TERM") & have_ptr]
tp = ptr[t.index]
tgt_act = tp.map(act.to_dict())
print("\nTERM pointer target action:", tgt_act.value_counts(dropna=False).to_dict())
tt = t[tgt_act == "TERM"]
print("TERM->TERM:", len(tt))
ex = tt.head(5)
for i, r in ex.iterrows():
    di, p = lin.normalise_id(r[DI]), lin.normalise_id(r[ODI])
    print(f"  {di} -> {p}  parent has target: {p in parent}  target's own ptr: {parent.get(p)}")
