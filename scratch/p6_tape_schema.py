import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:/Users/chris/clee/ARBS-dd")
import psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE

print("LEGS_TABLE =", LEGS_TABLE, " PACKAGES_TABLE =", PACKAGES_TABLE)
conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
cur.execute("SET LOCAL statement_timeout = '120s'")
cur.execute("""
    SELECT column_name, data_type FROM information_schema.columns
    WHERE table_name = %s ORDER BY ordinal_position
""", (LEGS_TABLE,))
cols = cur.fetchall()
print(f"{len(cols)} columns")
for c, t in cols:
    print(f"  {c:45s} {t}")
conn.close()
