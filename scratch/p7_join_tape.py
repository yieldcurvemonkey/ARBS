import os, sys, json
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd
import numpy as np
import psycopg2
import psycopg2.extras
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 220); pd.set_option("display.max_rows", 200)

DI = "Dissemination Identifier"
ODI = "Original Dissemination Identifier"
raw = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet")
raw["_ev"] = pd.to_datetime(raw["_ev"], utc=True)
raw["_ex"] = pd.to_datetime(raw["_ex"], utc=True)
print("raw week rows", len(raw))

conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)
cur = conn.cursor()
cur.execute("SET statement_timeout = '300s'")

# ---------- tape bounds ----------
cur.execute(f"SELECT min(as_of_date), max(as_of_date), count(*), count(distinct trade_id) FROM {LEGS_TABLE}")
print("tape bounds (min as_of, max as_of, legs, distinct trade_id):", cur.fetchone())

# ---------- KNOWN-ANSWER VALIDATION of the join plumbing ----------
# every NEWT/TRAD USD SOFR print in the week that the tape ingested must be findable
newt = raw[(raw["Action type"] == "NEWT") & (raw["Event type"] == "TRAD")]
probe = newt[DI].dropna().astype(str).tolist()[:2000]
cur.execute(f"SELECT trade_id FROM {LEGS_TABLE} WHERE trade_id = ANY(%s)", (probe,))
hits = {r[0] for r in cur.fetchall()}
print(f"\n[VALIDATION] 2000 raw NEWT/TRAD Dissemination Identifiers -> {len(hits)} found in tape "
      f"({100*len(hits)/len(probe):.1f}%)  (expect >0 and well below 100% since tape is USD swaps only)")
assert len(hits) > 0, "join plumbing broken: zero NEWT ids resolve"

# sanity: a deliberately bogus id must NOT resolve
cur.execute(f"SELECT count(*) FROM {LEGS_TABLE} WHERE trade_id = ANY(%s)", (["ZZZ_NOT_AN_ID_9999"],))
print("[VALIDATION] bogus id resolves rows:", cur.fetchone()[0], "(expect 0)")


def resolve(ids):
    """return DataFrame trade_id, execution_timestamp, as_of_date, economic_class, tenor_years"""
    out = []
    ids = list(dict.fromkeys([str(x) for x in ids]))
    for i in range(0, len(ids), 4000):
        chunk = ids[i:i + 4000]
        cur.execute(
            f"""SELECT trade_id, min(execution_timestamp) AS ts, min(as_of_date) AS d,
                       min(economic_class) AS ec, min(tenor_years) AS ty, min(tape_label) AS tl
                FROM {LEGS_TABLE} WHERE trade_id = ANY(%s) GROUP BY trade_id""",
            (chunk,))
        out.extend(cur.fetchall())
    return pd.DataFrame(out, columns=["trade_id", "orig_exec_ts", "orig_as_of", "orig_ec", "orig_tenor", "orig_label"])


# ---------- resolve ALL pointers ----------
ptr = raw[raw[ODI].notna()].copy()
print(f"\nrows with a pointer: {len(ptr)} / {len(raw)} = {100*len(ptr)/len(raw):.2f}%")
res = resolve(ptr[ODI].dropna().unique())
print("distinct pointer targets:", ptr[ODI].nunique(), "-> resolved in tape:", len(res),
      f"({100*len(res)/ptr[ODI].nunique():.2f}%)")

ptr = ptr.merge(res, left_on=ODI, right_on="trade_id", how="left")
ptr["_resolved"] = ptr["trade_id"].notna()

print("\n=== pointer resolution by Action type ===")
g = ptr.groupby("Action type")["_resolved"].agg(["size", "sum"])
g["pct"] = (100 * g["sum"] / g["size"]).round(2)
print(g)

print("\n=== pointer resolution for TERM by Event type ===")
t = ptr[ptr["Action type"] == "TERM"]
g2 = t.groupby("Event type")["_resolved"].agg(["size", "sum"])
g2["pct"] = (100 * g2["sum"] / g2["size"]).round(2)
print(g2)

# ---------- decomposition of unresolved ----------
print("\n=== decomposition of UNRESOLVED TERM pointers ===")
cur.execute(f"SELECT min(trade_id::bigint), max(trade_id::bigint) FROM {LEGS_TABLE} WHERE trade_id ~ '^[0-9]+$'")
tmin, tmax = cur.fetchone()
print("tape trade_id numeric range:", tmin, tmax)
unres = t[~t["_resolved"]].copy()
unres["_odi_num"] = pd.to_numeric(unres[ODI], errors="coerce")
pre = (unres["_odi_num"] < tmin).sum()
inr = ((unres["_odi_num"] >= tmin) & (unres["_odi_num"] <= tmax)).sum()
post = (unres["_odi_num"] > tmax).sum()
nonnum = unres["_odi_num"].isna().sum()
print(f"  unresolved TERM pointers: {len(unres)}")
print(f"    target id BELOW tape min id (pre-tape, INFERRED): {pre} ({100*pre/max(len(unres),1):.1f}%)")
print(f"    target id inside tape id range (genuinely missing): {inr} ({100*inr/max(len(unres),1):.1f}%)")
print(f"    target id above tape max id: {post}")
print(f"    non-numeric target id: {nonnum}")

# ---------- reach-back ----------
print("\n=== reach-back: days between unwind Event timestamp and the tape original's execution_timestamp ===")
rt = t[t["_resolved"]].copy()
rt["orig_exec_ts"] = pd.to_datetime(rt["orig_exec_ts"], utc=True)
rt["_reach_d"] = (rt["_ev"] - rt["orig_exec_ts"]).dt.total_seconds() / 86400.0
for et, sub in rt.groupby("Event type"):
    q = sub["_reach_d"].quantile([.5, .75, .9, .95, .99, 1.0])
    print(f"  {et:5s} n={len(sub):>5}  p50={q[.5]:7.2f} p75={q[.75]:8.2f} p90={q[.9]:8.2f} "
          f"p95={q[.95]:8.2f} p99={q[.99]:8.2f} max={q[1.0]:8.2f}")
allq = rt["_reach_d"].quantile([.5, .75, .9, .95, .99, 1.0])
print(f"  ALL   n={len(rt):>5}  p50={allq[.5]:7.2f} p75={allq[.75]:8.2f} p90={allq[.9]:8.2f} "
      f"p95={allq[.95]:8.2f} p99={allq[.99]:8.2f} max={allq[1.0]:8.2f}")
print("\n  reach-back cumulative coverage (of RESOLVED TERM rows):")
for d in [0, 1, 7, 30, 90, 180, 365, 730, 1095]:
    print(f"    <= {d:5d} days : {100*(rt['_reach_d'] <= d).mean():6.2f}%")

# also: same but as a share of ALL TERM rows in the week
print("\n  reach-back cumulative coverage (of ALL 3659 TERM rows in the week):")
n_all_term = len(t)
for d in [0, 1, 7, 30, 90, 180, 365, 730, 1095]:
    print(f"    <= {d:5d} days : {100*(rt['_reach_d'] <= d).sum()/n_all_term:6.2f}%")

print("\n=== what the resolved originals look like (economic_class of the ORIGINAL print) ===")
print(rt["orig_ec"].value_counts(dropna=False).head(15))
print("\n tenor_years of resolved originals for ETRM:")
e = rt[rt["Event type"] == "ETRM"]["orig_tenor"].astype(float)
print(e.describe())

rt_out = rt[[DI, ODI, "Action type", "Event type", "_ev", "_ex", "orig_exec_ts", "orig_as_of",
             "orig_ec", "orig_tenor", "orig_label", "_reach_d"]]
rt_out.to_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/resolved_terms.parquet", index=False)
ptr.drop(columns=[c for c in ptr.columns if ptr[c].dtype == object and c not in
                  [DI, ODI, "Action type", "Event type"]], errors="ignore")
print("\nwrote scratch/resolved_terms.parquet")
conn.close()
