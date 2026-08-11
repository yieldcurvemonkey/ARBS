"""Probe 2: seasoning flags, the 2024-07 regime break, termination economics."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)
pd.set_option("display.max_colwidth", 90)

conn = psycopg2.connect(resolve_pg_url())


def q(sql, **p):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=p or None)


def show(t, df):
    print(f"\n===== {t} =====")
    print(df.to_string())


show("V1. seasoning flags populated?", q(
    f"SELECT count(*) n, "
    f"count(*) FILTER (WHERE lc_has_past_effective) n_pasteff, "
    f"count(*) FILTER (WHERE lc_is_off_market_seasoned) n_seasoned, "
    f"count(*) FILTER (WHERE lc_days_seasoned IS NOT NULL) n_daysnn, "
    f"count(*) FILTER (WHERE lc_days_seasoned > 0) n_dayspos, "
    f"count(*) FILTER (WHERE is_new_risk) n_newrisk, "
    f"count(*) FILTER (WHERE lc_was_amended) n_amended, "
    f"count(*) FILTER (WHERE lc_was_null_filled) n_nullfill, "
    f"count(*) FILTER (WHERE lc_has_economics_change) n_econchg "
    f"FROM {LEGS_TABLE}"))

show("V2. effective_date in the past (real seasoning, computed)", q(
    f"SELECT (effective_date < as_of_date - 5) past_eff, lifecycle_type, "
    f"economic_class, count(*) n "
    f"FROM {LEGS_TABLE} GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20"))

show("V3. the 2024-07/08 regime break: lifecycle_type by month", q(
    f"SELECT to_char(as_of_date,'YYYY-MM') ym, lifecycle_type, count(*) n "
    f"FROM {LEGS_TABLE} WHERE as_of_date BETWEEN '2024-05-01' AND '2024-10-31' "
    f"GROUP BY 1,2 ORDER BY 1,3 DESC"))

show("V4. platform XOFF by month (unwind carrier?)", q(
    f"SELECT to_char(as_of_date,'YYYY-MM') ym, "
    f"count(*) FILTER (WHERE platform_identifier='XOFF') n_xoff, "
    f"count(*) FILTER (WHERE platform_identifier='XXXX') n_xxxx, "
    f"count(*) n_all FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 1"))

show("V5. TERMINATION rows: economics", q(
    f"SELECT count(*) n, "
    f"count(*) FILTER (WHERE fixed_rate IS NOT NULL) n_rate, "
    f"count(*) FILTER (WHERE other_payment_ufro <> 0) n_ufro, "
    f"count(*) FILTER (WHERE is_off_market) n_offmkt, "
    f"count(*) FILTER (WHERE effective_date < as_of_date - 5) n_pasteff, "
    f"avg(notional) avg_notional, "
    f"percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional "
    f"FROM {LEGS_TABLE} WHERE lifecycle_type='TERMINATION'"))

show("V6. NEW_TRADE flow rows: same economics for comparison", q(
    f"SELECT count(*) n, "
    f"count(*) FILTER (WHERE other_payment_ufro <> 0) n_ufro, "
    f"count(*) FILTER (WHERE is_off_market) n_offmkt, "
    f"count(*) FILTER (WHERE effective_date < as_of_date - 5) n_pasteff, "
    f"percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional "
    f"FROM {LEGS_TABLE} WHERE lifecycle_type='NEW_TRADE' AND economic_class='ECONOMIC_FLOW'"))

show("V7. TERMINATION sample", q(
    f"SELECT trade_id, as_of_date, tenor_label, effective_date, expiration_date, "
    f"notional, fixed_rate, other_payment_ufro, is_off_market, off_market_reason, "
    f"platform_identifier, venue, trade_type "
    f"FROM {LEGS_TABLE} WHERE lifecycle_type='TERMINATION' AND as_of_date > '2026-06-01' "
    f"ORDER BY as_of_date DESC LIMIT 12"))

show("V8. off_market_reason vocabulary", q(
    f"SELECT off_market_reason, count(*) n FROM {LEGS_TABLE} "
    f"WHERE off_market_reason IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 20"))

show("V9. is_off_market vs upfront presence (flow)", q(
    f"SELECT is_off_market, (other_payment_ufro <> 0) has_ufro, count(*) n "
    f"FROM {LEGS_TABLE} WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"GROUP BY 1,2 ORDER BY 3 DESC"))

conn.close()
