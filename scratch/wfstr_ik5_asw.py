import os, sys, time
os.environ.setdefault('ARBS_SUPABASE_ENABLED', '0')
sys.path.insert(0, 'C:/Users/chris/clee/ARBS-fe')
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
import psycopg2
import pandas as pd
pd.set_option('display.width', 260); pd.set_option('display.max_colwidth', 80)
pd.set_option('display.max_rows', 200)
conn = psycopg2.connect(resolve_pg_url())
conn.cursor().execute("set statement_timeout = '280s'")


def q(sql, title=""):
    t0 = time.time()
    df = pd.read_sql(sql, conn)
    print(f"--- {title} ({len(df)} rows, {time.time()-t0:.1f}s) ---")
    print(df.to_string())
    print(flush=True)
    return df


q("""select trade_id, package_id, leg_order, tenor_display, is_spreadover, is_asset_swap,
        basis_type, matched_ust_maturity, ust_cusip, special_tenor_type, tape_label,
        other_payment_amount, package_transaction_spread, trade_type
     from arbs_usd_swap_tape_legs_v3
     where package_id in ('CURVE_16_4646806983000000401','CURVE_12_4645295537000000101')
     order by package_id, leg_order""", "CURVE_16 (SPREADOVER) and CURVE_12 (MMS) leg flags")

q("""select bool_or(l.is_spreadover) sp, bool_or(l.is_asset_swap) asw,
        (l.tape_label like '%SPREADOVER%') lbl_spread,
        (l.tape_label like '%MMS%') lbl_mms,
        count(distinct u.package_id) n
     from arbs_dd_unit_v1 u
     join arbs_usd_swap_tape_legs_v3 l
       on l.package_id=u.package_id and l.as_of_date=u.as_of_date
     where u.as_of_date >= date '2026-05-13' and u.kind in ('CURVE','FLY')
     group by l.tape_label
     """, "raw (will regroup in pandas)")

conn.close()
