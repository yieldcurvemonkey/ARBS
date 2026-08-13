"""Follow-up census: what a TERMINATION row on the v3 tape actually looks like.

uf01 found the premise of the "terminations have no fee to compare against"
gap to be false on this tape: ``other_payment_uwin`` is populated on 15 rows in
2.33M, while 11,583 TERMINATION rows carry ``other_payment_ufro``. So the
question becomes which of those rows is a *seasoned* unwind (where the fee is
P&L) rather than a same-day tear-up (where it is not).
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)

FEE_TERM = """
  lifecycle_type='TERMINATION' AND economic_class='ECONOMIC_FLOW'
  AND other_payment_ufro > 0 AND fixed_rate IS NOT NULL
  AND abs(fixed_rate) < 1.0 AND notional < 1e11
"""


def q(conn, sql, params=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params)


def main() -> None:
    conn = psycopg2.connect(resolve_pg_url())

    print("=== A. seasoning of fee-bearing terminations (years, as_of - effective) ===")
    print(q(conn, f"""
      SELECT count(*) n,
             count(*) FILTER (WHERE effective_date < as_of_date) past_eff,
             percentile_cont(0.05) WITHIN GROUP (ORDER BY yrs) p05,
             percentile_cont(0.50) WITHIN GROUP (ORDER BY yrs) p50,
             percentile_cont(0.95) WITHIN GROUP (ORDER BY yrs) p95,
             max(yrs) mx
      FROM (SELECT as_of_date, effective_date,
                   (as_of_date - effective_date)/365.25::float AS yrs
            FROM {LEGS_TABLE} WHERE {FEE_TERM}) t""").to_string())

    print("\n=== B. how stale is #96 on those rows (days, event - execution) ===")
    print(q(conn, f"""
      SELECT count(*) n,
             count(*) FILTER (WHERE d > 1) older_than_a_day,
             percentile_cont(0.50) WITHIN GROUP (ORDER BY d) p50,
             percentile_cont(0.95) WITHIN GROUP (ORDER BY d) p95, max(d) mx
      FROM (SELECT extract(epoch FROM (event_timestamp - execution_timestamp))/86400.0 d
            FROM {LEGS_TABLE} WHERE {FEE_TERM}) t""").to_string())

    print("\n=== C. trade_type / off-market / capped mix ===")
    print(q(conn, f"""
      SELECT trade_type, is_off_market, count(*) n
      FROM {LEGS_TABLE} WHERE {FEE_TERM}
      GROUP BY 1,2 ORDER BY n DESC LIMIT 12""").to_string())

    print("\n=== D. how many are singleton outrights we can price cleanly ===")
    print(q(conn, f"""
      SELECT count(*) n,
             count(*) FILTER (WHERE package_id IS NULL) no_pkg,
             count(*) FILTER (WHERE trade_type='OUTRIGHT') outright,
             count(*) FILTER (WHERE trade_type='OUTRIGHT' AND NOT is_capped
                                AND expiration_date > as_of_date) priceable
      FROM {LEGS_TABLE} WHERE {FEE_TERM}""").to_string())

    print("\n=== E. and the same for the 36,763 ECONOMIC_UNWIND new trades ===")
    print(q(conn, f"""
      SELECT count(*) n,
             count(*) FILTER (WHERE other_payment_ufro > 0) fee,
             count(*) FILTER (WHERE trade_type='OUTRIGHT') outright,
             percentile_cont(0.50) WITHIN GROUP (
               ORDER BY (as_of_date - effective_date)/365.25::float) seasoning_p50
      FROM {LEGS_TABLE}
      WHERE economic_class='ECONOMIC_UNWIND' AND lifecycle_type='NEW_TRADE'""").to_string())

    conn.close()


if __name__ == "__main__":
    main()
