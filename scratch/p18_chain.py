import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

DI = "Dissemination Identifier"; ODI = "Original Dissemination Identifier"
TAPE_START = pd.Timestamp("2024-03-01", tz="UTC")
SWAP_FISN = ["NA/Swap OIS USD", "NA/Swap Fxd Flt USD", "NA/Swap Flt Flt OIS USD"]

raw = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet")
raw["_ex"] = pd.to_datetime(raw["_ex"], utc=True)
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
cur = conn.cursor(); cur.execute("SET statement_timeout='300s'")

t = raw[raw["Action type"] == "TERM"].copy()
d = t[(t["Event type"] == "ETRM") & (t["Notional currency-Leg 1"] == "USD") &
      (t["UPI FISN"].isin(SWAP_FISN)) & (t["_ex"] >= TAPE_START)].copy()
ids = d[ODI].astype(str).tolist()
found = set()
for i in range(0, len(ids), 4000):
    cur.execute(f"SELECT distinct trade_id FROM {LEGS_TABLE} WHERE trade_id = ANY(%s)", (ids[i:i+4000],))
    found |= {r[0] for r in cur.fetchall()}
d["_res"] = d[ODI].astype(str).isin(found)
un = d[~d["_res"]]
print("addressable ETRM:", len(d), " unresolved:", len(un))

# does the unresolved pointer name a message that IS in this week's raw (i.e. a CORR/MODI hop)?
week_di = set(raw[DI].dropna().astype(str))
hop = un[ODI].astype(str).isin(week_di)
print("unresolved pointers that name a Dissemination Identifier present in this week's raw:",
      int(hop.sum()), "of", len(un))
if hop.any():
    tgt = raw[raw[DI].astype(str).isin(set(un.loc[hop, ODI].astype(str)))]
    print(tgt["Action type"].value_counts().to_dict())
    # one more hop: do THOSE rows' own ODIs resolve in the tape?
    nxt = tgt[ODI].dropna().astype(str).unique().tolist()
    f2 = set()
    for i in range(0, len(nxt), 4000):
        cur.execute(f"SELECT distinct trade_id FROM {LEGS_TABLE} WHERE trade_id = ANY(%s)", (nxt[i:i+4000],))
        f2 |= {r[0] for r in cur.fetchall()}
    print("  of those next-hop targets, resolve in tape:", len(f2), "of", len(nxt))
print("\nunresolved by FISN:", dict(un["UPI FISN"].value_counts()))
conn.close()
