"""Orientation probe: schema + population counts. READ ONLY."""
import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
import psycopg2
import pandas as pd
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option('display.width', 250)
pd.set_option('display.max_columns', 60)
pd.set_option('display.max_rows', 300)

conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)


def q(sql, params=None):
    return pd.read_sql(sql, conn, params=params)


print("=== unit_v1 columns ===")
print(q("""SELECT column_name, data_type FROM information_schema.columns
           WHERE table_name='arbs_dd_unit_v1' ORDER BY ordinal_position""").to_string())

print("\n=== legs_v3 columns ===")
print(q("""SELECT column_name, data_type FROM information_schema.columns
           WHERE table_name='arbs_usd_swap_tape_legs_v3' ORDER BY ordinal_position""").to_string())

print("\n=== unit population by kind / rule ===")
print(q("""SELECT kind, rule, n_legs,
                  count(*) n,
                  count(deviation_bps) n_dev,
                  count(*) FILTER (WHERE exclusion_reason IS NULL) n_ok,
                  count(*) FILTER (WHERE curve_timestamp IS NOT NULL) n_ct
           FROM arbs_dd_unit_v1
           GROUP BY 1,2,3 ORDER BY 1,2,3""").to_string())

print("\n=== date span ===")
print(q("""SELECT min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) FROM arbs_dd_unit_v1""").to_string())

print("\n=== curve grid ===")
print(q("""SELECT rate_index, count(*) n, count(DISTINCT tenor_label) n_tenor,
                  min(ts) mn, max(ts) mx
           FROM arbs_dd_curve_mid_v1 GROUP BY 1""").to_string())

conn.close()
