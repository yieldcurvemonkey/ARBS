"""Measure arbs_stir_direction_v1 in prod. READ ONLY."""
import os, sys, json
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import DIRECTION_TABLE, TICK_TABLE

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()

def q(sql, params=None):
    cur.execute(sql, params or {})
    return cur.fetchall()

print("== table existence ==")
for t in (DIRECTION_TABLE, TICK_TABLE):
    r = q("SELECT to_regclass(%s)", (t,))
    print(f"{t}: {r[0][0]}")

print("\n== row count / date span ==")
print(q(f"SELECT count(*), min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) FROM {DIRECTION_TABLE}"))

print("\n== code_vintage distribution ==")
for r in q(f"""SELECT coalesce(code_vintage,'<NULL>') v, count(*) n,
                      min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) d,
                      min(classified_at), max(classified_at)
               FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY n DESC"""):
    print(r)

print("\n== dealer_direction distribution ==")
for r in q(f"""SELECT dealer_direction, count(*) n,
               round(100.0*count(*)/sum(count(*)) OVER (), 2) pct
               FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY n DESC"""):
    print(r)

print("\n== direction_confidence distribution ==")
for r in q(f"""SELECT coalesce(direction_confidence,'<NULL>') c, count(*) n,
               round(100.0*count(*)/sum(count(*)) OVER (), 2) pct
               FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY n DESC"""):
    print(r)

print("\n== classification_method distribution ==")
for r in q(f"""SELECT coalesce(classification_method,'<EMPTY>') m, count(*) n
               FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY n DESC"""):
    print(r)

print("\n== trade_type / rate_index / off_market ==")
for r in q(f"SELECT trade_type, count(*) FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY 2 DESC"):
    print(r)
for r in q(f"SELECT rate_index_clean, count(*) FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY 2 DESC"):
    print(r)
for r in q(f"SELECT is_off_market, count(*) FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY 2 DESC"):
    print(r)

print("\n== curve_suspect_trade ==")
for r in q(f"SELECT curve_suspect_trade, count(*) FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY 2 DESC"):
    print(r)

print("\n== quality_flags top ==")
for r in q(f"""SELECT f, count(*) FROM {DIRECTION_TABLE}, unnest(coalesce(quality_flags,'{{}}'::text[])) f
               GROUP BY 1 ORDER BY 2 DESC LIMIT 15"""):
    print((str(r[0])[:110], r[1]))
print("empty/no flags:", q(f"SELECT count(*) FROM {DIRECTION_TABLE} WHERE quality_flags IS NULL OR cardinality(quality_flags)=0"))

print("\n== per-day rows (first 15 / last 15) ==")
days = q(f"""SELECT as_of_date, count(*) n,
             count(*) FILTER (WHERE dealer_direction='UNKNOWN') unk,
             count(DISTINCT code_vintage) nv
             FROM {DIRECTION_TABLE} GROUP BY 1 ORDER BY 1""")
print("n_days =", len(days))
for r in days[:15]:
    print(r)
print("...")
for r in days[-15:]:
    print(r)

print("\n== tick table ==")
print(q(f"SELECT count(*), min(as_of_date), max(as_of_date) FROM {TICK_TABLE}"))

conn.close()
