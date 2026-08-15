import os, sys
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, r'C:\Users\chris\clee\ARBS-fe')
import psycopg2, pandas as pd, warnings
warnings.filterwarnings('ignore')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 200)
conn = psycopg2.connect(resolve_pg_url()); conn.set_session(readonly=True)
q = lambda s, p=None: pd.read_sql(s, conn, params=p)

print(q("""SELECT indexname, indexdef FROM pg_indexes
           WHERE tablename IN ('arbs_dd_curve_mid_v1','arbs_dd_unit_v1','arbs_usd_swap_tape_legs_v3')
           ORDER BY tablename, indexname""").to_string())
print()
print(q("""SELECT relname, n_live_tup FROM pg_stat_user_tables
           WHERE relname IN ('arbs_dd_curve_mid_v1','arbs_dd_unit_v1','arbs_usd_swap_tape_legs_v3')"""))
print()
print("grid tenor labels:")
print(q("""SELECT rate_index, tenor_label, count(*) n FROM arbs_dd_curve_mid_v1
           GROUP BY 1,2 ORDER BY 1,2""").to_string())
conn.close()
