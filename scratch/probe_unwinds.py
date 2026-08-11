"""Probe: what ARE the unwind rows, and can their size be recovered?"""
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
pd.set_option("display.max_colwidth", 120)

conn = psycopg2.connect(resolve_pg_url())


def q(sql, **p):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=p or None)


def show(t, df):
    print(f"\n===== {t} =====")
    print(df.to_string())


show("U1. lifecycle_type x economic_class", q(
    f"SELECT lifecycle_type, economic_class, count(*) n, "
    f"count(*) FILTER (WHERE contributes_to_flow) n_flow, "
    f"count(*) FILTER (WHERE on_p43) n_p43 "
    f"FROM {LEGS_TABLE} GROUP BY 1,2 ORDER BY 3 DESC"))

show("U2. economic_class_reason for ECONOMIC_UNWIND", q(
    f"SELECT economic_class_reason, count(*) n FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_UNWIND' GROUP BY 1 ORDER BY 2 DESC LIMIT 20"))

show("U3. economic_class_reason for TERMINATION lifecycle", q(
    f"SELECT lifecycle_type, economic_class, economic_class_reason, count(*) n "
    f"FROM {LEGS_TABLE} WHERE lifecycle_type='TERMINATION' "
    f"GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20"))

show("U4. unwind rows: do they carry rate / fee / notional?", q(
    f"SELECT count(*) n, "
    f"count(*) FILTER (WHERE fixed_rate IS NOT NULL) n_rate, "
    f"count(*) FILTER (WHERE notional IS NOT NULL AND notional > 0) n_notional, "
    f"count(*) FILTER (WHERE other_payment_amount IS NOT NULL) n_opa, "
    f"count(*) FILTER (WHERE other_payment_ufro IS NOT NULL AND other_payment_ufro <> 0) n_ufro, "
    f"count(*) FILTER (WHERE other_payment_uwin IS NOT NULL AND other_payment_uwin <> 0) n_uwin, "
    f"count(*) FILTER (WHERE other_payment_pexh IS NOT NULL AND other_payment_pexh <> 0) n_pexh, "
    f"count(*) FILTER (WHERE is_off_market) n_offmkt, "
    f"count(*) FILTER (WHERE risk IS NOT NULL) n_risk "
    f"FROM {LEGS_TABLE} WHERE economic_class='ECONOMIC_UNWIND'"))

show("U5. unwind sample", q(
    f"SELECT trade_id, as_of_date, lifecycle_type, tenor_label, effective_date, "
    f"expiration_date, notional, fixed_rate, other_payment_amount, other_payment_ufro, "
    f"other_payment_uwin, is_off_market, venue, platform_identifier, trade_type "
    f"FROM {LEGS_TABLE} WHERE economic_class='ECONOMIC_UNWIND' "
    f"AND as_of_date > '2026-05-01' ORDER BY as_of_date DESC LIMIT 12"))

show("U6. unwinds by month", q(
    f"SELECT to_char(as_of_date,'YYYY-MM') ym, count(*) n_unwind, "
    f"count(*) FILTER (WHERE lifecycle_type='TERMINATION') n_term "
    f"FROM {LEGS_TABLE} WHERE economic_class='ECONOMIC_UNWIND' GROUP BY 1 ORDER BY 1"))

show("U7. TERMINATION rows by month vs total", q(
    f"SELECT to_char(as_of_date,'YYYY-MM') ym, "
    f"count(*) FILTER (WHERE lifecycle_type='TERMINATION') n_term, "
    f"count(*) FILTER (WHERE lifecycle_type='OTHER') n_other, "
    f"count(*) n_all FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 1"))

show("U8. original_execution_source + alpha lag", q(
    f"SELECT original_execution_source, count(*) n, "
    f"count(*) FILTER (WHERE alpha_lag_seconds > 0) n_alpha_pos, "
    f"count(*) FILTER (WHERE d2_missing IS NULL) n_d2_null, "
    f"count(*) FILTER (WHERE d2_missing = true) n_d2_true "
    f"FROM {LEGS_TABLE} GROUP BY 1"))

show("U9. canonical_underlier_key -- can it group a trade with its unwind?", q(
    f"SELECT count(*) n, count(distinct canonical_underlier_key) n_keys, "
    f"count(*) FILTER (WHERE canonical_underlier_key IS NULL) n_null "
    f"FROM {LEGS_TABLE}"))

show("U10. do unwind rows share a canonical_underlier_key with an earlier NEW_TRADE?", q(
    f"""
    WITH u AS (
      SELECT canonical_underlier_key k, notional, as_of_date, trade_id
      FROM {LEGS_TABLE}
      WHERE economic_class='ECONOMIC_UNWIND' AND canonical_underlier_key IS NOT NULL
      LIMIT 2000
    )
    SELECT count(*) n_unwind_sampled,
           count(*) FILTER (WHERE m.n_prior > 0) n_with_prior,
           avg(m.n_prior) avg_prior
    FROM u
    LEFT JOIN LATERAL (
      SELECT count(*) n_prior FROM {LEGS_TABLE} l
      WHERE l.canonical_underlier_key = u.k
        AND l.lifecycle_type = 'NEW_TRADE'
        AND l.as_of_date <= u.as_of_date
    ) m ON true
    """))

conn.close()
