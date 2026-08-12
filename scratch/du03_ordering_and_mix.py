"""Is (expiration_date, effective_date, trade_id) actually a TOTAL order?
Plus: mixed-index packages, and whether packages ever span as_of_date.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 200)
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def head(t):
    print()
    print("=" * 88)
    print(t)
    print("=" * 88)


head("O1. leg_order distribution -- is one row one trade, or one row one leg?")
print(q(f"SELECT leg_order, count(*) n FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 1"
        ).to_string(index=False))

head("O2. is (package_id, expiration, effective, trade_id) unique?")
print(q(f"""
    SELECT count(*) n_dup_groups, coalesce(sum(c),0) n_rows_in_dups
    FROM (
      SELECT package_id, expiration_date, effective_date, trade_id, count(*) c
      FROM {LEGS_TABLE} WHERE package_id IS NOT NULL
      GROUP BY 1,2,3,4 HAVING count(*) > 1
    ) t
""").to_string(index=False))

head("O2b. and with leg_order added?")
print(q(f"""
    SELECT count(*) n_dup_groups
    FROM (
      SELECT package_id, expiration_date, effective_date, trade_id, leg_order,
             count(*) c
      FROM {LEGS_TABLE} WHERE package_id IS NOT NULL
      GROUP BY 1,2,3,4,5 HAVING count(*) > 1
    ) t
""").to_string(index=False))

head("O2c. singleton trades: is trade_id unique when package_id IS NULL?")
print(q(f"""
    SELECT count(*) n_dup_trade_ids
    FROM (SELECT trade_id, count(*) c FROM {LEGS_TABLE}
          WHERE package_id IS NULL GROUP BY 1 HAVING count(*) > 1) t
""").to_string(index=False))

head("O3. do packages span more than one as_of_date?")
print(q(f"""
    SELECT count(*) n_pkgs_spanning
    FROM (SELECT package_id, count(DISTINCT as_of_date) d FROM {LEGS_TABLE}
          WHERE package_id IS NOT NULL GROUP BY 1 HAVING count(DISTINCT as_of_date) > 1) t
""").to_string(index=False))

head("O4. packages with more than one rate_index_clean")
print(q(f"""
    SELECT n_idx, count(*) n_packages, sum(n_legs) n_legs
    FROM (
      SELECT package_id, count(DISTINCT rate_index_clean) n_idx, count(*) n_legs
      FROM {LEGS_TABLE}
      WHERE package_id IS NOT NULL AND contributes_to_flow
      GROUP BY 1
    ) t GROUP BY 1 ORDER BY 1
""").to_string(index=False))

head("O4b. which index pairs, for the mixed ones")
print(q(f"""
    SELECT idxs, count(*) n_packages FROM (
      SELECT package_id, string_agg(DISTINCT rate_index_clean, '+' ORDER BY rate_index_clean) idxs
      FROM {LEGS_TABLE} WHERE package_id IS NOT NULL AND contributes_to_flow
      GROUP BY 1
    ) t WHERE idxs LIKE '%%+%%' GROUP BY 1 ORDER BY 2 DESC LIMIT 20
""").to_string(index=False))

head("O5. does legs.package_transaction_price agree within a package?")
print(q(f"""
    SELECT count(*) n_pkgs, count(*) FILTER (WHERE d > 1) n_disagree
    FROM (SELECT package_id, count(DISTINCT package_transaction_price) d
          FROM {LEGS_TABLE} WHERE package_id IS NOT NULL GROUP BY 1) t
""").to_string(index=False))

head("O6. does legs count match packages.n_package_legs?")
print(q(f"""
    SELECT count(*) n_pkgs,
           count(*) FILTER (WHERE actual <> declared) n_mismatch,
           count(*) FILTER (WHERE declared IS NULL) n_no_pkg_row
    FROM (
      SELECT l.package_id, count(*) actual, max(p.n_package_legs) declared
      FROM {LEGS_TABLE} l LEFT JOIN {PACKAGES_TABLE} p USING (package_id)
      WHERE l.package_id IS NOT NULL GROUP BY 1
    ) t
""").to_string(index=False))

head("O7. rate_index_clean over ALL rows (the UNSUPPORTED_INDEX population)")
print(q(f"""
    SELECT coalesce(rate_index_clean,'(null)') idx, count(*) n,
           count(*) FILTER (WHERE contributes_to_flow) n_flow
    FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

head("O8. leg counts per as_of_date -- min / median / max, for the day loop")
print(q(f"""
    SELECT min(n) min_legs, percentile_cont(0.5) WITHIN GROUP (ORDER BY n) med_legs,
           max(n) max_legs, count(*) n_days
    FROM (SELECT as_of_date, count(*) n FROM {LEGS_TABLE} GROUP BY 1) t
""").to_string(index=False))

conn.close()
print("\ndone")
