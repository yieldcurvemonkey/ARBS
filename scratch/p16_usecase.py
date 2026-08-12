import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd, numpy as np, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 240); pd.set_option("display.max_rows", 200)
DI = "Dissemination Identifier"; ODI = "Original Dissemination Identifier"
TAPE_START = pd.Timestamp("2024-03-01", tz="UTC")
SWAP_FISN = ["NA/Swap OIS USD", "NA/Swap Fxd Flt USD", "NA/Swap Flt Flt OIS USD"]

raw = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet")
raw["_ex"] = pd.to_datetime(raw["_ex"], utc=True); raw["_ev"] = pd.to_datetime(raw["_ev"], utc=True)

conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
cur = conn.cursor(); cur.execute("SET statement_timeout = '300s'")


def resolve(ids):
    out = []
    ids = list(dict.fromkeys([str(x) for x in ids]))
    for i in range(0, len(ids), 4000):
        cur.execute(f"""SELECT trade_id, min(execution_timestamp), min(as_of_date), min(tenor_years),
                               min(notional), min(tape_label), min(economic_class)
                        FROM {LEGS_TABLE} WHERE trade_id = ANY(%s) GROUP BY trade_id""", (ids[i:i+4000],))
        out.extend(cur.fetchall())
    return pd.DataFrame(out, columns=["trade_id", "o_ts", "o_asof", "o_tenor", "o_notional",
                                      "o_label", "o_ec"])


t = raw[(raw["Action type"] == "TERM")].copy()
t["_ccy"] = t["Notional currency-Leg 1"].fillna("<NA>")
t["_fisn"] = t["UPI FISN"].fillna("<NA>")
res = resolve(t[ODI].unique())
t = t.merge(res, left_on=ODI, right_on="trade_id", how="left")
t["_res"] = t["trade_id"].notna()
t["o_ts"] = pd.to_datetime(t["o_ts"], utc=True)

print("=== FUNNEL: raw TERM -> flippable unwind, week 2026-06-15..18 ===")
step = []
step.append(("all TERM messages in raw zips", len(t), int(t["_res"].sum())))
a = t[t["Event type"] == "ETRM"];            step.append(("  Event type == ETRM", len(a), int(a["_res"].sum())))
b = a[a["_ccy"] == "USD"];                   step.append(("  + notional ccy USD", len(b), int(b["_res"].sum())))
c = b[b["_fisn"].isin(SWAP_FISN)];           step.append(("  + UPI FISN is a USD swap", len(c), int(c["_res"].sum())))
d = c[c["_ex"] >= TAPE_START];               step.append(("  + own exec ts >= tape start", len(d), int(d["_res"].sum())))
for lbl, n, r in step:
    print(f"  {lbl:38s} n={n:>5}  pointer resolves in tape: {r:>5}  ({100*r/max(n,1):5.1f}%)")

print("\n=== the addressable population (ETRM / USD / swap FISN / in-window) ===")
print("n =", len(d), " resolved =", int(d['_res'].sum()), f" = {100*d['_res'].mean():.2f}%")
print("by FISN:")
g = d.groupby("_fisn")["_res"].agg(["size", "sum"]); g["pct"] = (100*g["sum"]/g["size"]).round(1)
print(g)
print("\nunresolved in that population, by FISN:", dict(d[~d["_res"]]["_fisn"].value_counts()))
print("their own exec-ts month:", dict(d[~d['_res']]['_ex'].dt.to_period('M').value_counts().sort_index().tail(8)))

r_ = d[d["_res"]].copy()
r_["_reach_d"] = (r_["_ev"] - r_["o_ts"]).dt.total_seconds() / 86400
print("\nreach-back (days) for the addressable resolved set, n =", len(r_))
print(r_["_reach_d"].describe(percentiles=[.25, .5, .75, .9, .95, .99]).round(2).to_string())
for dd in [0, 1, 2, 5, 10, 21, 63, 126, 252, 504, 830]:
    print(f"   <= {dd:4d} d : {100*(r_['_reach_d']<=dd).mean():6.2f}%")

print("\n=== is the unwind cash present on the TERM message? ===")
opa = pd.to_numeric(r_["Other payment amount"], errors="coerce")
print("  Other payment amount non-null:", int(opa.notna().sum()), f"({100*opa.notna().mean():.1f}%)")
print("  Fixed rate-Leg 1 non-null   :", int(pd.to_numeric(r_['Fixed rate-Leg 1'], errors='coerce').notna().sum()),
      f"({100*pd.to_numeric(r_['Fixed rate-Leg 1'], errors='coerce').notna().mean():.1f}%)")
n1 = pd.to_numeric(r_["Notional amount-Leg 1"], errors="coerce")
print("  Notional amount-Leg 1 non-null:", int(n1.notna().sum()), f"({100*n1.notna().mean():.1f}%)")
ratio = n1 / pd.to_numeric(r_["o_notional"], errors="coerce")
print("  TERM notional / original notional: ==1 :", int((ratio.round(6) == 1).sum()),
      " <1 (partial):", int((ratio < 0.999999).sum()), " >1:", int((ratio > 1.000001).sum()),
      " n/a:", int(ratio.isna().sum()))

print("\n=== daily scale ===")
print("addressable resolved ETRM per business day:", round(len(r_)/4, 1))
cur.execute(f"""SELECT count(*)/4.0 FROM {LEGS_TABLE} WHERE as_of_date BETWEEN '2026-06-15' AND '2026-06-18'""")
print("tape legs per business day in the same week:", float(cur.fetchone()[0]))
conn.close()
