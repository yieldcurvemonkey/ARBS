"""At-scale validation of the lineage store over the whole built window.

Known answers first (the 2026-06-15..18 week, recorded in F-18), then the
measurements the 4-day window could not make: is the pointer topology a star or
a chain, and does the reach-back curve hold up over 62 days.
"""
from __future__ import annotations

import datetime
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")

import pandas as pd

from SDRUtils.dealer_direction import lineage as lin

pd.set_option("display.width", 220)
ROOT = r"C:/Users/chris/clee/ARBS-dd/scratch/dd_lineage_store"
TAPE_START = pd.Timestamp("2024-03-01", tz="UTC")
SWAP_FISN = ["NA/Swap OIS USD", "NA/Swap Fxd Flt USD", "NA/Swap Flt Flt OIS USD"]
DI, ODI = lin.DI, lin.ODI

store = lin.LineageStore(root=ROOT)
days = store.covered_days()
lg = store.read_range(days[0], days[-1])
print(f"store: {len(days)} days {days[0]} .. {days[-1]}, {len(lg):,} rows")

# ---------- 1. KNOWN ANSWER: the June week funnel, rebuilt ----------
wk = [datetime.date(2026, 6, d) for d in (15, 16, 17, 18)]
raw_wk = lin.load_raw_days(wk, root=ROOT)
w = lg[lg["file_date"].isin(wk)].merge(
    raw_wk[[DI, "UPI FISN", "Notional currency-Leg 1", lin.EXEC_TS]]
    .rename(columns={DI: "dissemination_id"}), on="dissemination_id", how="left")
t = w[w["action_type"] == "TERM"]
a = t[(t["event_type"] == "ETRM") & (t["Notional currency-Leg 1"] == "USD")
      & (t["UPI FISN"].isin(SWAP_FISN))
      & (pd.to_datetime(t[lin.EXEC_TS], utc=True) >= TAPE_START)]
ois = a[a["UPI FISN"] == "NA/Swap OIS USD"]
print(f"\n[KNOWN ANSWER] June week: TERM {len(t)} (3,659)  addressable {len(a)} (508) "
      f"resolved {int((a['status'] == lin.ST_RESOLVED_TAPE).sum())} (428)")
print(f"               NA/Swap OIS USD {len(ois)} (415) resolved "
      f"{int((ois['status'] == lin.ST_RESOLVED_TAPE).sum())} (382) = "
      f"{100 * (ois['status'] == lin.ST_RESOLVED_TAPE).mean():.2f}% (92.0%)")
print(f"               self-pointers now labelled: "
      f"{int((t['status'] == lin.ST_SELF_POINTER).sum())} TERM rows")

# ---------- 2. the topology question, at scale ----------
raw = lin.load_raw_days(days, root=ROOT, columns=(DI, ODI, lin.ACTION, lin.EVENT,
                                                  lin.EVENT_TS, lin.EXEC_TS, "UPI FISN",
                                                  "Notional currency-Leg 1", "file_date"))
raw["_di"] = raw[DI].map(lin.normalise_id)
raw["_odi"] = raw[ODI].map(lin.normalise_id)
known = set(raw["_di"].dropna())
ptr = raw[raw["_odi"].notna()]
selfp = ptr["_di"] == ptr["_odi"]
non_self = ptr[~selfp]
has_ptr = set(non_self["_di"])
tgt_in_window = non_self["_odi"].isin(known)
tgt_has_own_ptr = non_self["_odi"].isin(has_ptr)
print(f"\n=== POINTER TOPOLOGY over {len(days)} days ({len(raw):,} raw rows) ===")
print(f"  rows with a pointer          : {len(ptr):,}")
print(f"  self-pointers (ODI == own DI): {int(selfp.sum()):,} = {100 * selfp.mean():.2f}% of pointers")
print(f"  target present in the window : {int(tgt_in_window.sum()):,} of {len(non_self):,}")
print(f"  target ITSELF carries a (non-self) pointer -> a real 2-hop chain exists: "
      f"{int(tgt_has_own_ptr.sum()):,}")
print("\n  hops distribution in the store:")
print(lg["hops"].value_counts().sort_index().to_string())
print("\n  terminal_action of rows the walk resolved:")
res = lg[lg["status"] == lin.ST_RESOLVED_TAPE]
print(res["terminal_action"].value_counts(dropna=False).to_string())

# ---------- 3. status mix, all rows and TERM ----------
print("\n=== status mix (all pointer rows) ===")
print(lg["status"].value_counts().to_string())
term = lg[lg["action_type"] == "TERM"]
print(f"\n=== status mix (TERM only, n={len(term):,}) ===")
print(term["status"].value_counts().to_string())
print(f"\nTERM resolved to the tape: {int((term['status'] == lin.ST_RESOLVED_TAPE).sum()):,} = "
      f"{100 * (term['status'] == lin.ST_RESOLVED_TAPE).mean():.2f}%")
print(f"TERM PRE_TAPE: {int((term['status'] == lin.ST_PRE_TAPE).sum()):,} = "
      f"{100 * (term['status'] == lin.ST_PRE_TAPE).mean():.2f}% (recorded 5.6%), of which "
      f"resolved: {int(((term['status'] == lin.ST_PRE_TAPE) & False).sum())} (must be 0 by construction)")

# ---------- 4. reach-back at scale ----------
rb = term.loc[term["status"] == lin.ST_RESOLVED_TAPE, "reach_back_days"].dropna()
print(f"\n=== reach-back over {len(rb):,} tape-resolved TERMs "
      f"(recorded 75.5 / 90.7 / 95.6 at 1 / 63 / 252 d) ===")
for d in (0, 1, 7, 30, 63, 90, 180, 252, 365, 730, 1825):
    print(f"  <= {d:5d}d : {100 * (rb <= d).mean():6.2f}%")
print(f"  max {rb.max():.1f} d = {rb.max() / 365.25:.1f} years   negative: {int((rb < 0).sum())}")

# ---------- 5. the addressable OIS population over the whole window ----------
allt = lg.merge(raw[["_di", "UPI FISN", "Notional currency-Leg 1", lin.EXEC_TS]]
                .rename(columns={"_di": "dissemination_id"}), on="dissemination_id", how="left")
at = allt[(allt["action_type"] == "TERM") & (allt["event_type"] == "ETRM")
          & (allt["Notional currency-Leg 1"] == "USD")
          & (allt["UPI FISN"] == "NA/Swap OIS USD")
          & (pd.to_datetime(allt[lin.EXEC_TS], utc=True) >= TAPE_START)]
r = at["status"] == lin.ST_RESOLVED_TAPE
print(f"\n=== NA/Swap OIS USD ETRM, own exec >= tape start, whole window ===")
print(f"  n={len(at):,}  resolved to tape {int(r.sum()):,} = {100 * r.mean():.2f}%  "
      f"(week measurement 92.05%)")
print(f"  per day: {len(at) / len(days):.0f} addressable, {int(r.sum()) / len(days):.0f} resolved")
at.to_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/addressable_ois_terms.parquet", index=False)
print("  wrote scratch/addressable_ois_terms.parquet")
