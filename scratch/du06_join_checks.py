"""Two joins-or-not questions, and the platform-disagreement rate."""
from __future__ import annotations

import os
import sys
import time
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 240)
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


print("J1. legs.package_transaction_price vs packages.package_transaction_price")
print(q(f"""
    SELECT count(*) n_legs,
      count(*) FILTER (WHERE l.package_transaction_price IS DISTINCT FROM
                             p.package_transaction_price) n_differ,
      count(*) FILTER (WHERE l.package_transaction_price IS NOT NULL) n_leg_ptp,
      count(*) FILTER (WHERE p.package_transaction_price IS NOT NULL) n_pkg_ptp
    FROM {LEGS_TABLE} l JOIN {PACKAGES_TABLE} p USING (package_id)
""").to_string(index=False))

print()
print("J2. do packages ever mix platform_identifier / venue / lifecycle_type?")
print(q(f"""
    SELECT count(*) n_pkgs,
      count(*) FILTER (WHERE np > 1) mixed_platform,
      count(*) FILTER (WHERE nv > 1) mixed_venue,
      count(*) FILTER (WHERE nl > 1) mixed_lifecycle,
      count(*) FILTER (WHERE nc > 1) mixed_cleared,
      count(*) FILTER (WHERE ne > 1) mixed_econclass
    FROM (
      SELECT package_id,
             count(DISTINCT platform_identifier) np,
             count(DISTINCT venue) nv,
             count(DISTINCT lifecycle_type) nl,
             count(DISTINCT cleared) nc,
             count(DISTINCT economic_class) ne
      FROM {LEGS_TABLE} GROUP BY 1
    ) t
""").to_string(index=False))

print()
print("J3. cleared distinct values")
print(q(f"SELECT coalesce(cleared,'(null)') v, count(*) n FROM {LEGS_TABLE} "
        "GROUP BY 1 ORDER BY 2 DESC").to_string(index=False))

print()
t0 = time.time()
d = q(f"""
    SELECT l.trade_id, l.package_id, l.as_of_date, l.notional, l.risk
    FROM {LEGS_TABLE} l
    WHERE l.as_of_date BETWEEN '2026-06-01' AND '2026-06-30'
    ORDER BY l.package_id, l.expiration_date, l.effective_date, l.trade_id
""")
print(f"J4. one month, 5 cols, ordered: {len(d):,} rows in {time.time()-t0:.1f}s")

conn.close()
print("\ndone")
