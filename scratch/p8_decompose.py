import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd, numpy as np, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 240); pd.set_option("display.max_rows", 300)
DI = "Dissemination Identifier"; ODI = "Original Dissemination Identifier"
TAPE_START = pd.Timestamp("2024-03-01", tz="UTC")

raw = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet")
raw["_ev"] = pd.to_datetime(raw["_ev"], utc=True); raw["_ex"] = pd.to_datetime(raw["_ex"], utc=True)

conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
cur = conn.cursor(); cur.execute("SET statement_timeout = '300s'")


def resolve(ids):
    out = []
    ids = list(dict.fromkeys([str(x) for x in ids]))
    for i in range(0, len(ids), 4000):
        cur.execute(f"""SELECT trade_id, min(execution_timestamp), min(as_of_date), min(economic_class),
                               min(tenor_years), min(notional_currency)
                        FROM {LEGS_TABLE} WHERE trade_id = ANY(%s) GROUP BY trade_id""", (ids[i:i+4000],))
        out.extend(cur.fetchall())
    return pd.DataFrame(out, columns=["trade_id", "orig_exec_ts", "orig_as_of", "orig_ec", "orig_tenor", "orig_ccy"])


ptr = raw[raw[ODI].notna()].copy()
res = resolve(ptr[ODI].unique())
ptr = ptr.merge(res, left_on=ODI, right_on="trade_id", how="left")
ptr["_resolved"] = ptr["trade_id"].notna()
ptr["orig_exec_ts"] = pd.to_datetime(ptr["orig_exec_ts"], utc=True)

term = ptr[ptr["Action type"] == "TERM"].copy()

# ---------------------------------------------------------------
# VALIDATION: does a lifecycle row's OWN Execution Timestamp equal the
# tape original's execution_timestamp?  If yes, Execution Timestamp on a
# TERM is a usable proxy for "when was the original printed", and we can
# classify unresolved pointers as pre-tape vs in-window without the join.
# ---------------------------------------------------------------
print("=== VALIDATION: TERM row Execution Timestamp vs resolved original execution_timestamp ===")
rt = term[term["_resolved"]].copy()
delta = (rt["_ex"] - rt["orig_exec_ts"]).dt.total_seconds()
print("n resolved TERM:", len(rt))
print("  exact match (|delta| < 1s):", int((delta.abs() < 1).sum()), f"({100*(delta.abs()<1).mean():.1f}%)")
print("  |delta| < 60s            :", int((delta.abs() < 60).sum()), f"({100*(delta.abs()<60).mean():.1f}%)")
print("  |delta| < 1 day          :", int((delta.abs() < 86400).sum()), f"({100*(delta.abs()<86400).mean():.1f}%)")
print("  delta seconds describe:"); print(delta.describe())
print("  same by Event type:")
for et, sub in rt.groupby("Event type"):
    d = (sub["_ex"] - sub["orig_exec_ts"]).dt.total_seconds().abs()
    print(f"    {et:5s} n={len(sub):>4}  <1s {100*(d<1).mean():6.1f}%  <60s {100*(d<60).mean():6.1f}%")

# ---------------------------------------------------------------
# Decompose ALL TERM rows: pre-tape vs in-window (using own Execution Timestamp)
#   and by notional currency
# ---------------------------------------------------------------
print("\n=== TERM rows: own Execution Timestamp vs tape start 2024-03-01 ===")
term["_pre_tape"] = term["_ex"] < TAPE_START
print(pd.crosstab(term["_pre_tape"], term["_resolved"], margins=True))

print("\n=== TERM rows by Notional currency-Leg 1 ===")
ccy = term["Notional currency-Leg 1"].fillna("<NA>")
print(pd.crosstab(ccy, term["_resolved"]).sort_values(True, ascending=False).head(12))

print("\n=== TERM: USD only, Execution Timestamp >= tape start ===")
usd_in = term[(ccy == "USD") & (~term["_pre_tape"])]
print("n =", len(usd_in), " resolved =", int(usd_in["_resolved"].sum()),
      f" ({100*usd_in['_resolved'].mean():.2f}%)")
print(usd_in.groupby("Event type")["_resolved"].agg(["size", "sum", "mean"]).assign(
    pct=lambda d: (100*d["mean"]).round(2)).drop(columns="mean"))

print("\n=== TERM/ETRM only, USD, exec >= tape start, split by whether the row looks like a swap ===")
etrm = usd_in[usd_in["Event type"] == "ETRM"].copy()
print("ETRM USD in-window n =", len(etrm), "resolved", int(etrm["_resolved"].sum()),
      f"({100*etrm['_resolved'].mean():.2f}%)")
print("  UPI present:", int(etrm["Unique Product Identifier"].notna().sum()))
print("  UPI FISN value_counts (top 12):")
print(etrm["UPI FISN"].fillna("<NA>").value_counts().head(12))
print("\n  resolution by UPI FISN (top 10 by size):")
gg = etrm.groupby(etrm["UPI FISN"].fillna("<NA>"))["_resolved"].agg(["size", "sum"])
gg["pct"] = (100*gg["sum"]/gg["size"]).round(1)
print(gg.sort_values("size", ascending=False).head(10))

# unresolved USD in-window ETRM: are they SOFR swaps at all?
un = etrm[~etrm["_resolved"]]
print("\n  UNRESOLVED USD in-window ETRM n =", len(un))
print("  their Underlying asset subtype / UPI Underlier Name (top 10):")
print(un["UPI Underlier Name"].fillna("<NA>").value_counts().head(10))

conn.close()
