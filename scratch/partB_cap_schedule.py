"""Part B step 1: reverse-engineer the Part 43 cap schedule actually in force.

Two things the tape shows and the brief did not assume:
  * the cap depends on tenor at a much finer granularity than 2/10/30y;
  * the schedule was RE-SET during the sample (two vintages), so a single
    cap per tenor bucket does not exist over 2024-03..2026-08.

Everything below is derived from the 68,946 capped prints themselves --
their `notional` IS the cap -- rather than asserted from the regulation.
"""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 300)
pd.set_option("display.max_rows", 500)
pd.set_option("display.max_columns", 60)

OUT = os.path.dirname(os.path.abspath(__file__))
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def show(title, df):
    print(f"\n===== {title} =====")
    print(df.to_string())


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"

cap = q(f"""
SELECT trade_id, as_of_date, tenor_years, notional, rate_index_clean
FROM {LEGS_TABLE}
WHERE {FLOW} AND is_capped AND tenor_years > 0 AND notional > 0
""")
cap["as_of_date"] = pd.to_datetime(cap["as_of_date"])
print(f"capped prints pulled: {len(cap):,}")

# ---------------------------------------------------------------- vintage
show("S1. each distinct cap value: date span", (
    cap.groupby("notional")
       .agg(n=("trade_id", "size"), first=("as_of_date", "min"),
            last=("as_of_date", "max"),
            lo_t=("tenor_years", "min"), hi_t=("tenor_years", "max"))
       .sort_values("notional")
))

# The two schedules are disjoint value sets; find the changeover by looking at
# the last day of the old set and the first day of the new set, per bucket.
COARSE = [(0, 0.126, "<46d"), (0.126, 0.30, "46d-3m"), (0.30, 0.55, "3m-6m"),
          (0.55, 1.04, "6m-1y"), (1.04, 2.05, "1y-2y"), (2.05, 5.05, "2y-5y"),
          (5.05, 10.06, "5y-10y"), (10.06, 30.07, "10y-30y"), (30.07, 99, ">30y")]


def coarse(t):
    for lo, hi, lab in COARSE:
        if lo <= t < hi:
            return lab
    return ">30y"


cap["coarse"] = cap["tenor_years"].map(coarse)

sw = []
for lab in [c[2] for c in COARSE]:
    sub = cap[cap["coarse"] == lab]
    if sub.empty:
        continue
    # modal cap in the first and last 60 days of the sample
    early = sub[sub["as_of_date"] < "2024-09-01"]
    late = sub[sub["as_of_date"] > "2025-01-01"]
    if early.empty or late.empty:
        continue
    c_old = early["notional"].mode().iloc[0]
    c_new = late["notional"].mode().iloc[0]
    if c_old == c_new:
        sw.append({"bucket": lab, "cap_old": c_old, "cap_new": c_new,
                   "last_old": None, "first_new": None, "n_old": len(early)})
        continue
    sw.append({
        "bucket": lab, "cap_old": c_old, "cap_new": c_new,
        "last_old": sub.loc[sub["notional"] == c_old, "as_of_date"].max().date(),
        "first_new": sub.loc[sub["notional"] == c_new, "as_of_date"].min().date(),
        "n_old": int((sub["notional"] == c_old).sum()),
        "n_new": int((sub["notional"] == c_new).sum()),
    })
show("S2. changeover per coarse bucket (modal cap early vs late)", pd.DataFrame(sw))

show("S3. capped prints per day around the changeover, by cap value "
     "(5y-10y bucket)", (
    cap[(cap["coarse"] == "5y-10y") & cap["as_of_date"].between("2024-09-15", "2024-10-15")]
    .groupby([cap["as_of_date"].dt.date, "notional"]).size().unstack(fill_value=0)
))

SWITCH = pd.Timestamp("2024-10-07")
cap["vintage"] = np.where(cap["as_of_date"] < SWITCH, "V1", "V2")
show("S4. sanity: cap values by vintage (share of that vintage's capped rows)", (
    cap.groupby(["vintage", "notional"]).size().rename("n").reset_index()
       .assign(share=lambda d: d["n"] / d.groupby("vintage")["n"].transform("sum"))
       .sort_values(["vintage", "n"], ascending=[True, False])
))

# --------------------------------------------------- empirical bucket edges
edges = np.unique(np.concatenate([
    np.arange(0.0, 2.0, 0.02), np.arange(2.0, 12.0, 0.25),
    np.arange(12.0, 52.0, 1.0),
]))
rows = []
for vint, g in cap.groupby("vintage"):
    b = pd.cut(g["tenor_years"], edges, right=False)
    for iv, gg in g.groupby(b, observed=True):
        m = gg["notional"].mode()
        rows.append({"vintage": vint, "lo": iv.left, "hi": iv.right,
                     "n": len(gg), "cap": m.iloc[0],
                     "purity": (gg["notional"] == m.iloc[0]).mean()})
fine = pd.DataFrame(rows).sort_values(["vintage", "lo"])

# merge adjacent fine bins carrying the same modal cap
merged = []
for vint, g in fine.groupby("vintage"):
    cur = None
    for r in g.itertuples():
        if cur is not None and cur["cap"] == r.cap:
            cur["hi"] = r.hi
            cur["n"] += r.n
        else:
            if cur is not None:
                merged.append(cur)
            cur = {"vintage": vint, "lo": r.lo, "hi": r.hi, "cap": r.cap, "n": r.n}
    if cur is not None:
        merged.append(cur)
sched = pd.DataFrame(merged)
sched = sched[sched["n"] >= 25].reset_index(drop=True)   # drop edge noise
show("S5. EMPIRICAL cap schedule (merged fine bins, n>=25)", sched)

# --------------------------------- purity check: how clean is each band?
band_rows = []
for r in sched.itertuples():
    sub = cap[(cap["vintage"] == r.vintage) &
              (cap["tenor_years"] >= r.lo) & (cap["tenor_years"] < r.hi)]
    band_rows.append({
        "vintage": r.vintage, "lo": r.lo, "hi": r.hi, "cap": r.cap, "n": len(sub),
        "pct_at_cap": (sub["notional"] == r.cap).mean(),
        "n_other": int((sub["notional"] != r.cap).sum()),
    })
show("S6. purity of each derived band (fraction of capped prints exactly at the cap)",
     pd.DataFrame(band_rows))

sched.to_csv(os.path.join(OUT, "partB_cap_schedule.csv"), index=False)
with open(os.path.join(OUT, "partB_cap_schedule.json"), "w") as fh:
    json.dump({"switch_date": str(SWITCH.date()),
               "bands": sched.to_dict("records")}, fh, indent=2, default=float)
print(f"\nwrote {os.path.join(OUT, 'partB_cap_schedule.csv')}")

conn.close()
