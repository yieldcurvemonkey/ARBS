import os, sys
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-r0")
import psycopg2
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

conn = psycopg2.connect(resolve_pg_url()); cur = conn.cursor()
W = ("as_of_date BETWEEN '2026-05-01' AND '2026-08-07' AND economic_class='ECONOMIC_FLOW' "
     "AND contributes_to_flow AND rate_index_clean IN ('SOFR','FED_FUNDS') "
     "AND fixed_rate IS NOT NULL AND notional IS NOT NULL AND notional < 1e19 "
     "AND tenor_years IS NOT NULL AND tenor_years > 0")

def q(lbl, sql):
    print(f"\n=== {lbl} ===")
    cur.execute(sql)
    for r in cur.fetchall(): print("  ", r)

q("venue x platform_identifier", f"SELECT venue, platform_identifier, count(*) FROM {LEGS_TABLE} WHERE {W} GROUP BY 1,2 ORDER BY 3 DESC LIMIT 40")
q("venue totals", f"SELECT venue, count(*) FROM {LEGS_TABLE} WHERE {W} GROUP BY 1 ORDER BY 2 DESC")
q("is_block", f"SELECT is_block, count(*) FROM {LEGS_TABLE} WHERE {W} GROUP BY 1")
q("bucket counts", f"""
 SELECT CASE WHEN tenor_years<=1.5 THEN 'SFR_FF' WHEN tenor_years<=3 THEN 'TU'
             WHEN tenor_years<=7 THEN 'FV' WHEN tenor_years<=12 THEN 'TY_UXY'
             ELSE 'US' END AS bucket, count(*), round(sum(notional*tenor_years*1e-4)/1e6,1) AS dv01_mm
 FROM {LEGS_TABLE} WHERE {W} GROUP BY 1 ORDER BY 2 DESC""")
q("fwd start distribution", f"""
 SELECT CASE WHEN forward_start_years IS NULL THEN 'null' WHEN forward_start_years<=0.02 THEN 'spot'
             WHEN forward_start_years<=1 THEN '<=1y' ELSE '>1y' END, count(*)
 FROM {LEGS_TABLE} WHERE {W} GROUP BY 1 ORDER BY 2 DESC""")
q("tenor_label top", f"SELECT tenor_label, count(*) FROM {LEGS_TABLE} WHERE {W} GROUP BY 1 ORDER BY 2 DESC LIMIT 20")
q("distinct tenor_label count", f"SELECT count(DISTINCT tenor_label) FROM {LEGS_TABLE} WHERE {W}")
q("prints per (day,tenor_label) percentiles", f"""
 SELECT percentile_disc(0.1) WITHIN GROUP (ORDER BY n), percentile_disc(0.5) WITHIN GROUP (ORDER BY n),
        percentile_disc(0.9) WITHIN GROUP (ORDER BY n)
 FROM (SELECT as_of_date, tenor_label, count(*) n FROM {LEGS_TABLE} WHERE {W} GROUP BY 1,2) s""")
q("exec ts null / range", f"SELECT count(*) FILTER (WHERE execution_timestamp IS NULL), min(execution_timestamp), max(execution_timestamp) FROM {LEGS_TABLE} WHERE {W}")
conn.close()
