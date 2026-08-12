"""List the tape leg columns this repricing probe will need."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()
cur.execute(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_name = %s ORDER BY ordinal_position",
    (LEGS_TABLE,),
)
rows = cur.fetchall()
print(f"{LEGS_TABLE}: {len(rows)} columns")
for name, dtype in rows:
    print(f"  {name:45s} {dtype}")
conn.close()
