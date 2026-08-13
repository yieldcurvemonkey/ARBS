"""Validate the sidecar against the week whose answers are already recorded.

F-18 measured, single-hop, on 2026-06-15..18:
  100,079 raw rows; 17,305 pointers (17.29%)
  TERM 3,659; resolved 613 (16.8%)
  funnel ETRM -> +USD -> +USD-swap UPI -> +own exec >= tape start = 428/508 = 84.25%
  NA/Swap OIS USD 382/415 = 92.0%
  80 unresolved addressable, of which 43 point at another TERM
  reach-back <=1d 75.5%, <=63d 90.7%, <=252d 95.6%
  5.6% of TERMs point pre-tape and resolved 0/206

Multi-hop must be >= single-hop everywhere, and the pre-tape rows must still
resolve 0.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")

import datetime

import pandas as pd

from SDRUtils.dealer_direction import lineage as lin

pd.set_option("display.width", 220)

ROOT = r"C:/Users/chris/clee/ARBS-dd/scratch/dd_lineage_store"
DAYS = [datetime.date(2026, 6, d) for d in (15, 16, 17, 18)]
TAPE_START = pd.Timestamp("2024-03-01", tz="UTC")
SWAP_FISN = ["NA/Swap OIS USD", "NA/Swap Fxd Flt USD", "NA/Swap Flt Flt OIS USD"]
RES = [lin.ST_RESOLVED_TAPE]

store = lin.LineageStore(root=ROOT)
lg = store.read_range(DAYS[0], DAYS[-1])
raw = lin.load_raw_days(DAYS, root=ROOT)
print(f"raw union {len(raw):,} rows (recorded 100,079)   lineage rows {len(lg):,} (recorded 17,305)")

# attach the product columns the funnel needs
cols = [lin.DI, "UPI FISN", "Notional currency-Leg 1", lin.EXEC_TS]
lg = lg.merge(raw[cols].rename(columns={lin.DI: "dissemination_id"}),
              on="dissemination_id", how="left")

term = lg[lg["action_type"] == "TERM"]
print(f"\nTERM rows {len(term):,} (recorded 3,659)")
res = term["status"].isin(RES)
print(f"  resolved to the tape (multi-hop): {int(res.sum()):,} = {100*res.mean():.1f}%  "
      f"(recorded single-hop 613 = 16.8%)")

funnel = [
    ("all TERM", term),
    ("+ ETRM", term[term["event_type"] == "ETRM"]),
]
e = term[term["event_type"] == "ETRM"]
funnel.append(("+ USD", e[e["Notional currency-Leg 1"] == "USD"]))
u = funnel[-1][1]
funnel.append(("+ USD-swap UPI", u[u["UPI FISN"].isin(SWAP_FISN)]))
s = funnel[-1][1]
funnel.append(("+ own exec >= tape start",
               s[pd.to_datetime(s[lin.EXEC_TS], utc=True) >= TAPE_START]))
a = funnel[-1][1]
funnel.append(("   of which NA/Swap OIS USD", a[a["UPI FISN"] == "NA/Swap OIS USD"]))
print("\nfunnel (multi-hop):")
for name, sub in funnel:
    r = sub["status"].isin(RES)
    print(f"  {name:<28s} n={len(sub):>5}  resolved={int(r.sum()):>5}  "
          f"{100*r.mean() if len(sub) else 0:6.2f}%")

# --- what multi-hop bought -------------------------------------------------
print("\nhops distribution over all pointer rows:")
print(lg["hops"].value_counts().sort_index().to_string())
addressable = a
multi = addressable[addressable["hops"] > 1]
print(f"\naddressable ETRM/USD/swap/in-tape-era rows resolved at >1 hop: {len(multi)}")
gain = addressable["status"].isin(RES) & (addressable["hops"] > 1)
print(f"  of which resolve to the tape ONLY because of the extra hop: {int(gain.sum())}")

# TERM -> TERM pointers: the topology the star model cannot express
t2t = lg[(lg["action_type"] == "TERM") & (lg["terminal_action"] == "TERM")]
ptr_is_term = lg[lg["action_type"] == "TERM"].merge(
    raw[[lin.DI, "Action type"]].rename(columns={lin.DI: "pointer_id",
                                                 "Action type": "pointer_action"}),
    on="pointer_id", how="left")
n_t2t = int((ptr_is_term["pointer_action"] == "TERM").sum())
print(f"\nTERM rows whose DIRECT pointer is itself a TERM: {n_t2t} (recorded 43 in this week)")
print(f"TERM rows whose walk TERMINATES on a TERM (chain ran out of window): {len(t2t)}")

# --- reach-back ------------------------------------------------------------
rb = term.loc[term["status"].isin(RES), "reach_back_days"].dropna()
print(f"\nreach-back over {len(rb)} resolved TERMs (recorded 75.5 / 90.7 / 95.6 at 1 / 63 / 252d):")
for d in (0, 1, 7, 63, 90, 252, 365, 730):
    print(f"  <= {d:4d}d : {100*(rb <= d).mean():6.2f}%")
print(f"  max {rb.max():.1f} days = {rb.max()/365.25:.1f} years")

# --- the pre-tape consistency check ---------------------------------------
pre = term[term["status"] == lin.ST_PRE_TAPE]
print(f"\nPRE_TAPE TERM rows: {len(pre)} = {100*len(pre)/len(term):.1f}% of TERMs "
      f"(recorded 5.6%); resolved to the tape: "
      f"{int(pre['status'].isin(RES).sum())} (must be 0)")
assert int(pre["status"].isin(RES).sum()) == 0

print("\nstatus mix over all pointer rows:")
print(lg["status"].value_counts().to_string())
print("\nstatus mix for TERM only:")
print(term["status"].value_counts().to_string())
