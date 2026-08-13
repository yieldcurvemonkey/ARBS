"""Is the recorded '43 TERM->TERM pointers = chained partial terminations'
actually 43 TERM rows that point at THEMSELVES?"""
import os, sys, datetime
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd
from SDRUtils.dealer_direction import lineage as lin

ROOT = r"C:/Users/chris/clee/ARBS-dd/scratch/dd_lineage_store"
DAYS = [datetime.date(2026, 6, d) for d in (15, 16, 17, 18)]
TAPE_START = pd.Timestamp("2024-03-01", tz="UTC")
SWAP_FISN = ["NA/Swap OIS USD", "NA/Swap Fxd Flt USD", "NA/Swap Flt Flt OIS USD"]
DI, ODI = lin.DI, lin.ODI

raw = lin.load_raw_days(DAYS, root=ROOT)
raw["_di"] = raw[DI].map(lin.normalise_id)
raw["_odi"] = raw[ODI].map(lin.normalise_id)
raw["_ex"] = pd.to_datetime(raw[lin.EXEC_TS], utc=True, errors="coerce")

store = lin.LineageStore(root=ROOT)
lg = store.read_range(DAYS[0], DAYS[-1])
st = dict(zip(lg["dissemination_id"], lg["status"]))

# p18's addressable set, verbatim
a = raw[(raw["Action type"] == "TERM") & (raw["Event type"] == "ETRM")
        & (raw["Notional currency-Leg 1"] == "USD") & (raw["UPI FISN"].isin(SWAP_FISN))
        & (raw["_ex"] >= TAPE_START)]
a = a.assign(status=a["_di"].map(st))
un = a[a["status"] != lin.ST_RESOLVED_TAPE]
print(f"addressable {len(a)}   unresolved {len(un)}   (recorded 508 / 80)")
self_ptr = (un["_di"] == un["_odi"])
print(f"  of the unresolved, SELF-POINTERS (ODI == own DI): {int(self_ptr.sum())} "
      f"(recorded '43 point at another TERM')")
in_week = un["_odi"].isin(set(raw["_di"])) & ~self_ptr
print(f"  point at a DIFFERENT id present in the week: {int(in_week.sum())}")
if int(in_week.sum()):
    tgt = raw[raw["_di"].isin(set(un.loc[in_week, "_odi"]))]
    print("   those targets by action:", tgt["Action type"].value_counts().to_dict())
    print("   and do THOSE carry a pointer?", int(tgt["_odi"].notna().sum()), "of", len(tgt))
print(f"  point outside the week entirely: {int((~un['_odi'].isin(set(raw['_di']))).sum())}")

print("\nall 361 self-pointers in the week, by action/event:")
sp = raw[raw["_di"] == raw["_odi"]]
print(sp.groupby(["Action type", "Event type"]).size().to_string())
print("\nself-pointer TERM rows: do they resolve to the tape as themselves?")
spt = sp[sp["Action type"] == "TERM"]
print(spt["_di"].map(st).value_counts(dropna=False).to_string())
