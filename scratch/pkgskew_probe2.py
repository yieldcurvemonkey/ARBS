"""Probe 2: semantics of execution_hour_et, PTP/PTS fill rates, packages join size."""
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

pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 300)

conn = psycopg2.connect(resolve_pg_url())
q = lambda s, **kw: pd.read_sql(s, conn, params=kw or None)

with warnings.catch_warnings():
    warnings.simplefilter("ignore")

    print("--- row counts ---")
    print(q(f"SELECT (SELECT count(*) FROM {LEGS_TABLE}) legs, "
            f"(SELECT count(*) FROM {PACKAGES_TABLE}) pkgs, "
            f"(SELECT count(DISTINCT package_id) FROM {LEGS_TABLE}) leg_pkg_ids, "
            f"(SELECT count(*) FROM {LEGS_TABLE} WHERE package_id IS NULL) leg_no_pkg"))

    print("\n--- execution_hour_et vs execution_timestamp at ET, one day ---")
    print(q(f"""
        SELECT execution_hour_et,
               min(execution_timestamp AT TIME ZONE 'America/New_York') lo,
               max(execution_timestamp AT TIME ZONE 'America/New_York') hi,
               count(*) n
        FROM {LEGS_TABLE} WHERE as_of_date = DATE '2025-06-11'
        GROUP BY 1 ORDER BY 1
    """))

    print("\n--- execution_hour_et nulls overall ---")
    print(q(f"SELECT count(*) n, count(execution_hour_et) n_hour, "
            f"count(execution_timestamp) n_exec, count(event_timestamp) n_evt, "
            f"count(execution_session) n_sess FROM {LEGS_TABLE}"))

    print("\n--- PTP / PTS / ptp_group / opa_sign fill, by trade_type family ---")
    print(q(f"""
        SELECT trade_type,
               count(*) n,
               count(package_transaction_price) n_ptp,
               count(package_transaction_spread) n_pts,
               count(ptp_group_id) n_grp,
               count(opa_sign) FILTER (WHERE opa_sign <> 0) n_opa
        FROM {LEGS_TABLE}
        GROUP BY 1 ORDER BY n DESC LIMIT 40
    """))

    print("\n--- packages: opa_sign_confidence / package_structure ---")
    print(q(f"SELECT opa_sign_confidence, count(*) n FROM {PACKAGES_TABLE} GROUP BY 1 ORDER BY n DESC"))
    print(q(f"SELECT package_structure, count(*) n FROM {PACKAGES_TABLE} GROUP BY 1 ORDER BY n DESC LIMIT 25"))

conn.close()
