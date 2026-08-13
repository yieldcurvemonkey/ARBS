"""Probe: what columns exist on the tape legs/packages tables."""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 400)

conn = psycopg2.connect(resolve_pg_url())
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    for t in (LEGS_TABLE, PACKAGES_TABLE):
        cols = pd.read_sql(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = %(t)s ORDER BY ordinal_position",
            conn, params={"t": t})
        print(f"\n===== {t}  ({len(cols)} cols) =====")
        print(", ".join(f"{r.column_name}:{r.data_type}" for r in cols.itertuples()))
conn.close()
