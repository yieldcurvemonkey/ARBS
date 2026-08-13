"""Probe: what does the v3 tape actually carry? Columns, coverage, lineage."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 400)
pd.set_option("display.max_columns", 60)

conn = psycopg2.connect(resolve_pg_url())

for tbl in (LEGS_TABLE, PACKAGES_TABLE):
    cols = pd.read_sql(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = %(t)s ORDER BY ordinal_position",
        conn, params={"t": tbl},
    )
    print(f"\n===== {tbl}: {len(cols)} columns =====")
    print(", ".join(f"{r.column_name}" for r in cols.itertuples()))

print("\n===== legs coverage =====")
print(pd.read_sql(
    f"SELECT min(as_of_date) lo, max(as_of_date) hi, count(*) n, "
    f"count(distinct as_of_date) days FROM {LEGS_TABLE}", conn))

conn.close()
