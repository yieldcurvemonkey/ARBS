import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, '.')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2, pandas as pd

conn = psycopg2.connect(resolve_pg_url())
with conn.cursor() as c:
    c.execute("SET statement_timeout = '600s'")
    c.execute("SHOW statement_timeout"); print("timeout ->", c.fetchone())

def q(sql, **kw):
    return pd.read_sql(sql, conn, params=kw or None)

print("=== grid date range (index-only min/max) ===")
print(q("SELECT min(grid_date) d0, max(grid_date) d1 FROM arbs_dd_curve_mid_v1").to_string())

print("\n=== grid: one day shape ===")
print(q("""SELECT rate_index, count(*) n, count(DISTINCT tenor_label) nt,
                  count(DISTINCT ts) nts, min(ts) t0, max(ts) t1
           FROM arbs_dd_curve_mid_v1 WHERE grid_date = DATE '2026-06-04'
           GROUP BY 1""").to_string())

print("\n=== SOFR CURVE units per as_of_date (top days) ===")
print(q("""SELECT as_of_date, count(*) n
           FROM arbs_dd_unit_v1
           WHERE kind='CURVE' AND rate_index='SOFR' AND rule='RATE_VS_MID'
             AND deviation_bps IS NOT NULL AND curve_timestamp IS NOT NULL
           GROUP BY 1 ORDER BY n DESC LIMIT 12""").to_string())

print("\n=== busiest CURVE tenor pairs (SOFR), sample month ===")
print(q("""
  WITH u AS (
    SELECT package_id, as_of_date FROM arbs_dd_unit_v1
    WHERE kind='CURVE' AND rate_index='SOFR' AND rule='RATE_VS_MID'
      AND deviation_bps IS NOT NULL AND curve_timestamp IS NOT NULL
      AND as_of_date BETWEEN DATE '2026-06-01' AND DATE '2026-06-30'),
  l AS (
    SELECT u.package_id, u.as_of_date,
           string_agg(g.tenor_label, '/' ORDER BY g.expiration_date,
                      g.effective_date, g.trade_id, g.leg_order) AS pair
    FROM u JOIN arbs_usd_swap_tape_legs_v3 g
      ON g.package_id = u.package_id AND g.as_of_date = u.as_of_date
    GROUP BY 1,2)
  SELECT pair, count(*) n FROM l GROUP BY 1 ORDER BY n DESC LIMIT 25""").to_string())

conn.close()
