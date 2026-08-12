"""Probe: the facts that decide the dealer-direction design.

A. lineage — can an unwind be linked back to its original print?
B. tenor distribution — how much of the tape is beyond the current 3y cutoff?
C. on/off market split, MAC share, package structures
D. platform -> D2C/D2D
E. capped share, report lag by block
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 200)
pd.set_option("display.max_columns", 60)

conn = psycopg2.connect(resolve_pg_url())


def q(sql, **params):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params or None)


def show(title, df):
    print(f"\n===== {title} =====")
    print(df.to_string())


# --- A. lineage -----------------------------------------------------------
show("A1. trade_id shape (10 samples)", q(
    f"SELECT trade_id, package_id, lifecycle_type, economic_class, lc_n_events, "
    f"lc_status, xd_status, is_unwind, manual_link_id "
    f"FROM {LEGS_TABLE} WHERE as_of_date = '2026-06-02' LIMIT 10"))

show("A2. economic_class distribution (all history)", q(
    f"SELECT economic_class, count(*) n, "
    f"count(*) FILTER (WHERE contributes_to_flow) n_flow "
    f"FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC"))

show("A3. lifecycle_type distribution", q(
    f"SELECT lifecycle_type, count(*) n FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC LIMIT 25"))

show("A4. unwind flags", q(
    f"SELECT is_unwind, is_novation, is_novation_terminated, is_clearing_termination, "
    f"count(*) n FROM {LEGS_TABLE} GROUP BY 1,2,3,4 ORDER BY 5 DESC LIMIT 20"))

show("A5. xd_ family populated?", q(
    f"SELECT xd_status, count(*) n, avg(xd_n_events) avg_ev, "
    f"avg(xd_notional_pct_remaining) avg_pct, "
    f"count(*) FILTER (WHERE xd_is_terminated) n_term "
    f"FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC LIMIT 20"))

show("A6. lc_ unwind family", q(
    f"SELECT count(*) n, "
    f"count(*) FILTER (WHERE lc_was_partially_terminated) n_partterm, "
    f"count(*) FILTER (WHERE lc_has_partial_unwind) n_partunw, "
    f"count(*) FILTER (WHERE lc_inception_notional IS NOT NULL) n_incep, "
    f"count(*) FILTER (WHERE lc_current_notional IS NOT NULL) n_curr, "
    f"count(*) FILTER (WHERE lc_current_notional < lc_inception_notional) n_cut, "
    f"count(*) FILTER (WHERE d2_missing) n_d2miss, "
    f"count(*) FILTER (WHERE rc_timeline_json IS NOT NULL) n_rc "
    f"FROM {LEGS_TABLE}"))

show("A7. rc_timeline_json sample", q(
    f"SELECT trade_id, lifecycle_type, lc_n_events, left(rc_timeline_json::text, 400) rc "
    f"FROM {LEGS_TABLE} WHERE rc_timeline_json IS NOT NULL AND lc_n_events > 1 "
    f"AND as_of_date > '2026-05-01' LIMIT 5"))

show("A8. ECONOMIC_UNWIND rows recent", q(
    f"SELECT as_of_date, count(*) n FROM {LEGS_TABLE} "
    f"WHERE economic_class = 'ECONOMIC_UNWIND' AND as_of_date > '2026-06-01' "
    f"GROUP BY 1 ORDER BY 1 DESC LIMIT 15"))

# --- B. tenor -------------------------------------------------------------
show("B1. tenor_years distribution among ECONOMIC_FLOW", q(
    f"SELECT width_bucket(tenor_years, 0, 40, 40) b, min(tenor_years) lo, max(tenor_years) hi, "
    f"count(*) n, sum(abs(risk)) dv01 FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow AND tenor_years IS NOT NULL "
    f"GROUP BY 1 ORDER BY 1"))

show("B2. share beyond 3y", q(
    f"SELECT (tenor_years > 3.02) beyond3y, count(*) n, sum(abs(risk)) dv01 "
    f"FROM {LEGS_TABLE} WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"GROUP BY 1"))

show("B3. rate_index_clean", q(
    f"SELECT rate_index_clean, count(*) n, sum(abs(risk)) dv01 FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow GROUP BY 1 ORDER BY 2 DESC"))

# --- C. market / structures ----------------------------------------------
show("C1. on/off market + MAC", q(
    f"SELECT is_off_market, is_mac, is_spreadover, count(*) n FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20"))

show("C2. trade_type distribution (flow)", q(
    f"SELECT trade_type, count(*) n, sum(abs(risk)) dv01 FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"GROUP BY 1 ORDER BY 2 DESC LIMIT 40"))

show("C3. package_structure distribution", q(
    f"SELECT package_structure, count(*) n, avg(n_package_legs) avg_legs "
    f"FROM {PACKAGES_TABLE} GROUP BY 1 ORDER BY 2 DESC LIMIT 30"))

show("C4. n_package_legs histogram", q(
    f"SELECT n_package_legs, count(*) n FROM {PACKAGES_TABLE} GROUP BY 1 ORDER BY 1 LIMIT 30"))

show("C5. ptp_group coverage", q(
    f"SELECT count(*) n, count(*) FILTER (WHERE ptp_group_id IS NOT NULL) n_ptp "
    f"FROM {LEGS_TABLE} WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow"))

# --- D. platform ----------------------------------------------------------
show("D1. platform_identifier (flow)", q(
    f"SELECT platform_identifier, venue, count(*) n, sum(abs(risk)) dv01 FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"GROUP BY 1,2 ORDER BY 3 DESC LIMIT 40"))

# --- E. caps and lag ------------------------------------------------------
show("E1. capped share", q(
    f"SELECT is_capped, is_notional_capped, is_block, notional_source, count(*) n, "
    f"sum(abs(risk)) dv01 FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"GROUP BY 1,2,3,4 ORDER BY 5 DESC LIMIT 25"))

show("E2. report lag by block (seconds)", q(
    f"SELECT is_block, count(*) n, "
    f"percentile_cont(0.5) WITHIN GROUP (ORDER BY report_lag_seconds) p50, "
    f"percentile_cont(0.9) WITHIN GROUP (ORDER BY report_lag_seconds) p90, "
    f"percentile_cont(0.99) WITHIN GROUP (ORDER BY report_lag_seconds) p99, "
    f"max(report_lag_seconds) mx "
    f"FROM {LEGS_TABLE} WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"AND report_lag_seconds IS NOT NULL GROUP BY 1"))

show("E3. execution hour ET distribution (flow)", q(
    f"SELECT execution_hour_et, count(*) n FROM {LEGS_TABLE} "
    f"WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow "
    f"GROUP BY 1 ORDER BY 1"))

# --- F. opa solver --------------------------------------------------------
show("F1. opa_sign family (packages)", q(
    f"SELECT opa_sign_confidence, count(*) n, avg(abs(opa_signed_net)) avg_net, "
    f"avg(abs(opa_ptp_residual)) avg_resid, avg(dealer_spread_bps) avg_dsb "
    f"FROM {PACKAGES_TABLE} WHERE opa_signed_net IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 20"))

show("F2. dealer_spread_est populated?", q(
    f"SELECT count(*) n, count(*) FILTER (WHERE dealer_spread_est IS NOT NULL) n_est, "
    f"count(*) FILTER (WHERE dealer_spread_bps IS NOT NULL) n_bps, "
    f"count(*) FILTER (WHERE opa_sign_confidence IS NOT NULL) n_conf "
    f"FROM {PACKAGES_TABLE}"))

show("F3. legs opa_sign", q(
    f"SELECT opa_sign, count(*) n FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC LIMIT 10"))

conn.close()
