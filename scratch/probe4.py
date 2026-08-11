import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED","0")
import psycopg2
from SDRUtils._swappulse_scripts._tape_tables import PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
c=psycopg2.connect(resolve_pg_url()).cursor()
c.execute(f"""SELECT opa_sign_confidence,
   CASE WHEN ptp_group_id LIKE 'PTS/_%%' ESCAPE '/' THEN 'PTS(spread-keyed)'
        WHEN ptp_group_id LIKE 'PTP/_%%' ESCAPE '/' THEN 'PTP(price-keyed)'
        ELSE 'other' END AS keying,
   count(*), count(dealer_spread_bps),
   count(*) FILTER (WHERE dealer_spread_bps=0) AS bps_zero
 FROM {PACKAGES_TABLE} WHERE opa_sign_confidence IS NOT NULL
 GROUP BY 1,2 ORDER BY 1,2""")
print(f"{'tier':<12}{'keying':<20}{'n':>9}{'n_bps':>9}{'bps=0':>9}")
for r in c.fetchall(): print(f"{r[0]:<12}{r[1]:<20}{r[2]:>9}{r[3]:>9}{r[4]:>9}")
c.execute(f"""SELECT opa_sign_confidence, count(*),
   percentile_cont(0.50) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8 AS p50,
   percentile_cont(0.90) WITHIN GROUP (ORDER BY dealer_spread_bps)::float8 AS p90
 FROM {PACKAGES_TABLE}
 WHERE opa_sign_confidence IN ('EXACT','TIGHT') AND dealer_spread_bps > 0
 GROUP BY 1 ORDER BY 1""")
print("\nEXACT/TIGHT restricted to bps>0:")
for r in c.fetchall(): print(f"  {r[0]:<7} n={r[1]:<7} p50={r[2]:.6g} p90={r[3]:.6g}")
