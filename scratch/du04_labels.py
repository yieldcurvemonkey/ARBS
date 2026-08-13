from __future__ import annotations
import os, sys, warnings
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import pandas as pd, psycopg2
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option("display.width", 240); pd.set_option("display.max_rows", 100)
conn = psycopg2.connect(resolve_pg_url())
def q(s):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore"); return pd.read_sql(s, conn)
print("L1. EXCLUDED_LABEL_TOKENS population, and what index they carry")
print(q(f"""
 SELECT CASE WHEN leg_tape_label LIKE '%%CME Term%%' THEN 'CME Term'
             WHEN leg_tape_label LIKE '%%Amortizing%%' THEN 'Amortizing'
             ELSE 'other' END tok,
        rate_index_clean, count(*) n,
        count(*) FILTER (WHERE fixed_rate IS NULL) n_no_rate,
        count(*) FILTER (WHERE contributes_to_flow) n_flow
 FROM {LEGS_TABLE}
 WHERE leg_tape_label LIKE '%%CME Term%%' OR leg_tape_label LIKE '%%Amortizing%%'
 GROUP BY 1,2 ORDER BY 3 DESC""").to_string(index=False))
print("\nL2. upi_notional_schedule values")
print(q(f"""SELECT coalesce(upi_notional_schedule,'(null)') v, count(*) n,
   count(*) FILTER (WHERE contributes_to_flow) n_flow FROM {LEGS_TABLE}
   GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").to_string(index=False))
print("\nL3. schedule_truncated / schedule_row_count")
print(q(f"""SELECT coalesce(schedule_truncated::text,'(null)') st,
   count(*) n, max(schedule_row_count) max_rows FROM {LEGS_TABLE}
   GROUP BY 1 ORDER BY 2 DESC""").to_string(index=False))
print("\nL4. economic_class x contributes_to_flow (the NOT_FLOW population)")
print(q(f"""SELECT economic_class, contributes_to_flow, count(*) n
   FROM {LEGS_TABLE} GROUP BY 1,2 ORDER BY 3 DESC""").to_string(index=False))
print("\nL5. MAC units: how many have NO upfront at all (unit level)")
print(q(f"""SELECT has_up, count(*) n_units, sum(n_legs) n_legs FROM (
     SELECT package_id, bool_or(coalesce(other_payment_amount,0)<>0
            OR abs(coalesce(package_transaction_price,0))>500) has_up, count(*) n_legs
     FROM {LEGS_TABLE} WHERE contributes_to_flow AND package_id IN (
        SELECT DISTINCT package_id FROM {LEGS_TABLE} WHERE is_mac AND contributes_to_flow)
     GROUP BY 1) t GROUP BY 1""").to_string(index=False))
conn.close(); print("\ndone")
