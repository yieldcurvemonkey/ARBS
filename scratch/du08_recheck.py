from __future__ import annotations
import os, sys, warnings
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import pandas as pd, psycopg2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import universe as un
pd.set_option("display.width", 200)
conn = psycopg2.connect(resolve_pg_url())
def q(s):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore"); return pd.read_sql(s, conn)

print("R1. the 15 UWIN legs under the CURRENT rule")
uw = q(f"SELECT DISTINCT as_of_date FROM {LEGS_TABLE} WHERE coalesce(other_payment_uwin,0)<>0 ORDER BY 1")
ids = set(q(f"SELECT trade_id FROM {LEGS_TABLE} WHERE coalesce(other_payment_uwin,0)<>0")["trade_id"])
rows = []
for d in uw["as_of_date"]:
    legs = un.load_legs(conn, d, d)
    ann = un.annotate_legs(legs); u = un.unit_frame(legs)
    for _, lg in ann[ann["trade_id"].isin(ids)].iterrows():
        r = u.loc[lg["_unit_group"]]
        rows.append({"date": d, "trade_id": lg["trade_id"],
                     "lifecycle": lg["lifecycle_type"],
                     "uwin": lg["other_payment_uwin"],
                     "upfront": r["upfront"], "source": r["upfront_source"],
                     "exclusion": r["exclusion"], "detail": r["exclusion_detail"]})
d = pd.DataFrame(rows)
print(d.to_string(index=False))
print(f"  sourced UWIN and KEPT: {int(((d['source']=='UWIN_SUM') & d['exclusion'].isna()).sum())}")

print()
print("R2. MAC units by exclusion -- explains 14,856 vs the SQL 14,877")
macdays = q(f"SELECT DISTINCT as_of_date FROM {LEGS_TABLE} WHERE is_mac ORDER BY 1")["as_of_date"]
tot = {}
for dd in macdays:
    legs = un.load_legs(conn, dd, dd)
    u = un.unit_frame(legs)
    m = u[u["is_mac"]]
    for k, v in m["exclusion"].fillna("(kept)").value_counts().items():
        tot[k] = tot.get(k, 0) + int(v)
print("  ", tot, "  total", sum(tot.values()))
conn.close()
