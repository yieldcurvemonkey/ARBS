import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 240); pd.set_option("display.max_rows", 300)
DI = "Dissemination Identifier"; ODI = "Original Dissemination Identifier"
TAPE_START = pd.Timestamp("2024-03-01", tz="UTC")
WEEK = ("2026-06-15", "2026-06-18")

conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
cur = conn.cursor(); cur.execute("SET statement_timeout = '300s'")


def q(sql, args=None):
    cur.execute(sql, args)
    return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


print("=== tape rows for the week (as_of_date 2026-06-15..18) ===")
print(q(f"""SELECT as_of_date, count(*) legs, count(distinct trade_id) trades
            FROM {LEGS_TABLE} WHERE as_of_date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""", WEEK))

print("\n=== economic_class distribution ===")
print(q(f"""SELECT economic_class, count(*) FROM {LEGS_TABLE}
            WHERE as_of_date BETWEEN %s AND %s GROUP BY 1 ORDER BY 2 DESC""", WEEK))

print("\n=== lifecycle_type distribution ===")
print(q(f"""SELECT lifecycle_type, count(*) FROM {LEGS_TABLE}
            WHERE as_of_date BETWEEN %s AND %s GROUP BY 1 ORDER BY 2 DESC""", WEEK))

print("\n=== headline task-5 counts ===")
print(q(f"""SELECT
   count(*) FILTER (WHERE economic_class='ECONOMIC_UNWIND')       AS econ_unwind,
   count(*) FILTER (WHERE lifecycle_type='TERMINATION')           AS lc_termination,
   count(*) FILTER (WHERE is_unwind)                              AS is_unwind,
   count(*) FILTER (WHERE is_novation)                            AS is_novation,
   count(*) FILTER (WHERE is_novation_terminated)                 AS is_nova_term,
   count(*) FILTER (WHERE is_clearing_termination)                AS is_clrg_term,
   count(*) FILTER (WHERE is_exercise_born)                       AS is_exercise_born,
   count(*) FILTER (WHERE is_compression)                         AS is_compression
   FROM {LEGS_TABLE} WHERE as_of_date BETWEEN %s AND %s""", WEEK).T)

print("\n=== cross: economic_class x lifecycle_type ===")
print(q(f"""SELECT economic_class, lifecycle_type, count(*) FROM {LEGS_TABLE}
            WHERE as_of_date BETWEEN %s AND %s GROUP BY 1,2 ORDER BY 3 DESC LIMIT 25""", WEEK))

# ---- are the tape's unwind rows the TERM messages themselves, or the NEWT they point at? ----
raw = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/raw_week_unfiltered.parquet")
raw["_ex"] = pd.to_datetime(raw["_ex"], utc=True); raw["_ev"] = pd.to_datetime(raw["_ev"], utc=True)
term_ids = raw.loc[raw["Action type"] == "TERM", DI].dropna().astype(str).tolist()
newt_ids = raw.loc[raw["Action type"] == "NEWT", DI].dropna().astype(str).tolist()
modi_ids = raw.loc[raw["Action type"] == "MODI", DI].dropna().astype(str).tolist()


def in_tape(ids, label):
    found = 0
    for i in range(0, len(ids), 4000):
        cur.execute(f"SELECT count(distinct trade_id) FROM {LEGS_TABLE} WHERE trade_id = ANY(%s)",
                    (ids[i:i+4000],))
        found += cur.fetchone()[0]
    print(f"  {label}: {found}/{len(ids)} = {100*found/max(len(ids),1):.2f}% of raw {label} "
          f"Dissemination Identifiers appear as tape trade_id")
    return found


print("\n=== does the tape ingest the TERM messages themselves? ===")
in_tape(term_ids, "TERM")
in_tape(newt_ids, "NEWT")
in_tape(modi_ids, "MODI")

# ---- baseline: what fraction of raw USD OIS NEWT prints reach the tape? ----
print("\n=== BASELINE: raw NEWT ingestion rate into the tape, by UPI FISN ===")
newt = raw[(raw["Action type"] == "NEWT")].copy()
newt["_fisn"] = newt["UPI FISN"].fillna("<NA>")
for fisn in ["NA/Swap OIS USD", "NA/Swap Fxd Flt USD", "NA/Swap Flt Flt OIS USD",
             "NA/Swap Infl Idx USD", "NA/O P Epn OIS USD"]:
    ids = newt.loc[newt["_fisn"] == fisn, DI].dropna().astype(str).tolist()
    if not ids:
        continue
    found = 0
    for i in range(0, len(ids), 4000):
        cur.execute(f"SELECT count(distinct trade_id) FROM {LEGS_TABLE} WHERE trade_id = ANY(%s)",
                    (ids[i:i+4000],))
        found += cur.fetchone()[0]
    print(f"  {fisn:28s} n={len(ids):>6}  in tape {found:>6} = {100*found/len(ids):6.2f}%")

conn.close()
