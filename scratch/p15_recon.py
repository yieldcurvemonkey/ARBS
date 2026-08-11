import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import pandas as pd, numpy as np, psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

pd.set_option("display.width", 240); pd.set_option("display.max_rows", 200)
DI = "Dissemination Identifier"; ODI = "Original Dissemination Identifier"
WEEK = ("2026-06-15", "2026-06-18")

# --- A. what does the CACHED parquet actually store in ODI for a NEWT row? ---
c = pd.read_parquet(r"C:/Users/chris/clee/ARBS/sdr_cache/CFTC/RATES/2026/06/2026-06-16.parquet")
n = c[c["Action type"] == "NEWT"]
print("cached parquet ODI dtype:", c[ODI].dtype)
print("NEWT ODI unique values (first 5):", list(pd.unique(n[ODI]))[:5])
print("NEWT ODI isna():", int(n[ODI].isna().sum()), "of", len(n))
print("NEWT ODI == 'nan' string:", int((n[ODI].astype(str) == "nan").sum()))
tv = c[c["Action type"] == "TERM"]
print("TERM ODI isna():", int(tv[ODI].isna().sum()), "of", len(tv))


def norm(s):
    out = s.astype("string").str.strip()
    out = out.replace({"": pd.NA, "None": pd.NA, "NaN": pd.NA, "nan": pd.NA, "<NA>": pd.NA})
    return out.str.replace(r"\.0$", "", regex=True)


print("after normalisation -> NEWT ODI non-null:", int(norm(n[ODI]).notna().sum()),
      " TERM ODI non-null:", int(norm(tv[ODI]).notna().sum()))

# --- B. reconciliation ---
rt = pd.read_parquet(r"C:/Users/chris/clee/ARBS-dd/scratch/resolved_terms.parquet")
rt["orig_as_of"] = pd.to_datetime(rt["orig_as_of"])
print("\n=== resolved TERM pointers (613) by whether the ORIGINAL is in this week ===")
inwk = (rt["orig_as_of"] >= "2026-06-15") & (rt["orig_as_of"] <= "2026-06-18")
print(pd.crosstab(rt["Event type"], inwk, margins=True))

conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
cur = conn.cursor(); cur.execute("SET statement_timeout = '300s'")


def q(sql, args=None):
    cur.execute(sql, args); return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])


tape_term = q(f"""SELECT trade_id, as_of_date, economic_class, lifecycle_type, is_unwind,
                         lc_n_events, lc_status, xd_status, tenor_years, tape_label
                  FROM {LEGS_TABLE}
                  WHERE as_of_date BETWEEN %s AND %s AND lifecycle_type='TERMINATION'""", WEEK)
print("\ntape lifecycle_type='TERMINATION' rows in week:", len(tape_term))
mine = set(rt.loc[inwk, ODI].astype(str))
theirs = set(tape_term["trade_id"].astype(str))
print("  my resolved-in-week TERM targets:", len(mine))
print("  overlap:", len(mine & theirs))
print("  tape flags TERMINATION but I found no TERM pointer:", len(theirs - mine))
print("  I found a TERM pointer but tape does not flag TERMINATION:", len(mine - theirs))

print("\n  which Event types are the ones the tape MISSES (mine - theirs)?")
print(rt[inwk & rt[ODI].astype(str).isin(mine - theirs)]["Event type"].value_counts())

print("\n=== the 4 ECONOMIC_UNWIND rows ===")
print(q(f"""SELECT trade_id, as_of_date, tape_label, tenor_years, notional, economic_class,
                   economic_class_reason, lifecycle_type, is_unwind, other_payment_amount
            FROM {LEGS_TABLE} WHERE as_of_date BETWEEN %s AND %s
              AND economic_class='ECONOMIC_UNWIND'""", WEEK).to_string())

print("\n=== ETRM-only reconciliation (the true economic unwind population) ===")
etrm = rt[rt["Event type"] == "ETRM"]
print("resolved ETRM pointers:", len(etrm),
      " of which original printed in-week:", int(((etrm["orig_as_of"] >= '2026-06-15') & (etrm["orig_as_of"] <= '2026-06-18')).sum()))
print("resolved ETRM originals by as_of month:")
print(etrm["orig_as_of"].dt.to_period("M").value_counts().sort_index())
conn.close()
