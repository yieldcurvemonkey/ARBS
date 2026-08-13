"""Probe: columns of the legs table + a peek at tenor_label / forward_start_years."""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ.setdefault("ARBS_CITIVELO_QUOTES_OFFLINE", "1")
import pathlib
import sys

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

conn = psycopg2.connect(resolve_pg_url())
df = pd.read_sql(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name = %(t)s ORDER BY ordinal_position",
    conn, params={"t": LEGS_TABLE})
pd.set_option("display.max_rows", 400)
print(f"--- {LEGS_TABLE}: {len(df)} columns")
print(df.to_string())

d2 = pd.read_sql(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name = 'arbs_dd_unit_v1' ORDER BY ordinal_position", conn)
print(f"\n--- arbs_dd_unit_v1: {len(d2)} columns")
print(d2.to_string())

d3 = pd.read_sql(
    f"SELECT min(as_of_date) lo, max(as_of_date) hi, count(*) n FROM {LEGS_TABLE}", conn)
print("\n--- legs span"); print(d3.to_string())
d4 = pd.read_sql("SELECT min(as_of_date) lo, max(as_of_date) hi, count(*) n "
                 "FROM arbs_dd_unit_v1", conn)
print("\n--- dd unit span"); print(d4.to_string())
conn.close()
