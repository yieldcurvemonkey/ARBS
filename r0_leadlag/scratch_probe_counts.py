"""Probe: in-scope print counts / distinct values for the R0 window. Read-only."""
import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-r0")

import psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

conn = psycopg2.connect(resolve_pg_url())
cur = conn.cursor()

def q(label, sql, args=None):
    print(f"\n=== {label} ===")
    cur.execute(sql, args or ())
    for row in cur.fetchall():
        print("  ", row)

W = "as_of_date BETWEEN '2026-05-01' AND '2026-08-07'"

q("sample trade_id / package_id", f"""
  SELECT trade_id, package_id, leg_order, execution_timestamp, event_timestamp,
         tenor_years, notional, fixed_rate, rate_index_clean, platform_identifier,
         venue, is_block, economic_class, contributes_to_flow, trade_type
  FROM {LEGS_TABLE} WHERE {W} LIMIT 5
""")

q("rate_index_clean distribution (window)", f"""
  SELECT rate_index_clean, count(*) FROM {LEGS_TABLE} WHERE {W}
  GROUP BY 1 ORDER BY 2 DESC LIMIT 25
""")

q("economic_class distribution", f"""
  SELECT economic_class, contributes_to_flow, count(*) FROM {LEGS_TABLE} WHERE {W}
  GROUP BY 1,2 ORDER BY 3 DESC LIMIT 25
""")

q("platform_identifier distribution", f"""
  SELECT platform_identifier, count(*) FROM {LEGS_TABLE} WHERE {W}
  GROUP BY 1 ORDER BY 2 DESC LIMIT 40
""")

q("trade_type distribution (in-scope-ish)", f"""
  SELECT trade_type, count(*) FROM {LEGS_TABLE} WHERE {W}
    AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow
    AND rate_index_clean IN ('SOFR','FED_FUNDS') AND fixed_rate IS NOT NULL
  GROUP BY 1 ORDER BY 2 DESC LIMIT 25
""")

q("IN-SCOPE count + day count", f"""
  SELECT count(*) AS n_legs, count(DISTINCT as_of_date) AS n_days,
         count(DISTINCT trade_id) AS n_trade_ids,
         min(as_of_date), max(as_of_date)
  FROM {LEGS_TABLE} WHERE {W}
    AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow
    AND rate_index_clean IN ('SOFR','FED_FUNDS')
    AND fixed_rate IS NOT NULL AND notional IS NOT NULL
    AND notional < 1e19 AND tenor_years IS NOT NULL AND tenor_years > 0
""")

q("leg_order distribution in scope", f"""
  SELECT leg_order, count(*) FROM {LEGS_TABLE} WHERE {W}
    AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow
    AND rate_index_clean IN ('SOFR','FED_FUNDS') AND fixed_rate IS NOT NULL
  GROUP BY 1 ORDER BY 1
""")

q("notional sentinel check", f"""
  SELECT count(*) FROM {LEGS_TABLE} WHERE {W} AND notional >= 1e19
""")

q("trade_id length/shape sample", f"""
  SELECT length(trade_id), trade_id ~ '^[0-9]+$' AS all_digits, count(*)
  FROM {LEGS_TABLE} WHERE {W} GROUP BY 1,2 ORDER BY 3 DESC LIMIT 10
""")

conn.close()
