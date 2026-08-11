"""Census for the upfront rule: which fee column serves which population.

No pricing. Establishes the row counts every later measurement is sampled from,
and answers two questions the module's design depends on:

  * do TERMINATION rows actually carry ``other_payment_uwin`` (the frozen rule
    reads only ``_ufro``, so if they carry UWIN they currently have nothing to
    compare an NPV against), and
  * how big is the capped-and-upfront intersection that the cap guard would
    exclude.
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)


def q(conn, sql, params=None):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params)


def main() -> None:
    conn = psycopg2.connect(resolve_pg_url())

    print("=== A. fee columns by (economic_class, lifecycle_type) ===")
    print(q(conn, f"""
      SELECT economic_class, lifecycle_type, count(*) n,
             count(*) FILTER (WHERE other_payment_ufro > 0) ufro,
             count(*) FILTER (WHERE other_payment_uwin > 0) uwin,
             count(*) FILTER (WHERE other_payment_pexh > 0) pexh,
             count(*) FILTER (WHERE other_payment_amount > 0) opa
      FROM {LEGS_TABLE}
      GROUP BY 1,2 ORDER BY n DESC""").to_string())

    print("\n=== B. F-10 population: flow legs, not rate outliers, carrying a fee ===")
    print(q(conn, f"""
      SELECT is_off_market, (other_payment_ufro > 0) has_ufro, count(*) n
      FROM {LEGS_TABLE}
      WHERE economic_class='ECONOMIC_FLOW'
      GROUP BY 1,2 ORDER BY 1,2""").to_string())

    print("\n=== C. that population, narrowed to a clean rate-rule universe ===")
    print(q(conn, f"""
      SELECT count(*) n,
             count(*) FILTER (WHERE coalesce(p.n_package_legs,1) <= 1) singletons,
             count(*) FILTER (WHERE coalesce(p.n_package_legs,1) <= 1
                                AND l.trade_type='OUTRIGHT') outrights,
             count(*) FILTER (WHERE coalesce(p.n_package_legs,1) <= 1
                                AND l.trade_type='OUTRIGHT'
                                AND NOT l.is_capped) uncapped_outrights
      FROM {LEGS_TABLE} l LEFT JOIN {PACKAGES_TABLE} p USING (package_id)
      WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
        AND NOT l.is_off_market AND l.other_payment_ufro > 0
        AND l.rate_index_clean IN ('SOFR','FED_FUNDS')
        AND l.fixed_rate IS NOT NULL AND abs(l.fixed_rate) < 1.0
        AND l.notional < 1e11""").to_string())

    print("\n=== D. fee size distribution on that universe (USD) ===")
    print(q(conn, f"""
      SELECT count(*) n,
             percentile_cont(0.05) WITHIN GROUP (ORDER BY other_payment_ufro) p05,
             percentile_cont(0.25) WITHIN GROUP (ORDER BY other_payment_ufro) p25,
             percentile_cont(0.50) WITHIN GROUP (ORDER BY other_payment_ufro) p50,
             percentile_cont(0.75) WITHIN GROUP (ORDER BY other_payment_ufro) p75,
             percentile_cont(0.95) WITHIN GROUP (ORDER BY other_payment_ufro) p95,
             count(*) FILTER (WHERE other_payment_ufro < 500) below_ptp_floor
      FROM {LEGS_TABLE} l
      WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
        AND NOT l.is_off_market AND l.other_payment_ufro > 0
        AND l.trade_type='OUTRIGHT'
        AND l.rate_index_clean IN ('SOFR','FED_FUNDS')""").to_string())

    print("\n=== E. capped and carrying a fee (what the cap guard would exclude) ===")
    print(q(conn, f"""
      SELECT is_off_market, count(*) n, sum(abs(risk)) dv01
      FROM {LEGS_TABLE}
      WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
        AND is_capped AND other_payment_ufro > 0 AND notional < 1e11
      GROUP BY 1""").to_string())

    print("\n=== F. terminations: what is on the row ===")
    print(q(conn, f"""
      SELECT count(*) n,
             count(*) FILTER (WHERE other_payment_uwin > 0) uwin,
             count(*) FILTER (WHERE other_payment_ufro > 0) ufro,
             count(*) FILTER (WHERE fixed_rate IS NOT NULL) has_rate,
             count(*) FILTER (WHERE effective_date < as_of_date) past_effective,
             count(*) FILTER (WHERE event_timestamp IS NOT NULL) has_event_ts,
             count(*) FILTER (WHERE notional < 1e11) sane_notional
      FROM {LEGS_TABLE}
      WHERE lifecycle_type='TERMINATION'""").to_string())

    print("\n=== G. termination seasoning (years since effective) ===")
    print(q(conn, f"""
      SELECT count(*) n,
             percentile_cont(0.25) WITHIN GROUP (ORDER BY yrs) p25,
             percentile_cont(0.50) WITHIN GROUP (ORDER BY yrs) p50,
             percentile_cont(0.75) WITHIN GROUP (ORDER BY yrs) p75,
             percentile_cont(0.95) WITHIN GROUP (ORDER BY yrs) p95
      FROM (SELECT (as_of_date - effective_date)/365.25 AS yrs
            FROM {LEGS_TABLE}
            WHERE lifecycle_type='TERMINATION' AND other_payment_uwin > 0
              AND effective_date IS NOT NULL) t""").to_string())

    conn.close()


if __name__ == "__main__":
    main()
