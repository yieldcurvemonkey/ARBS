import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED","0")
import psycopg2
from SDRUtils._swappulse_scripts._tape_tables import PACKAGES_TABLE, LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
c=psycopg2.connect(resolve_pg_url()).cursor()
c.execute(f"""SELECT count(*),
  count(*) FILTER (WHERE ptp_group_id IS NULL) AS gid_null,
  count(*) FILTER (WHERE ptp_group_size IS NULL) AS gsz_null,
  min(ptp_group_size), max(ptp_group_size), count(DISTINCT package_type)
  FROM {PACKAGES_TABLE}
 WHERE opa_sign_confidence='UNRESOLVED' AND dealer_spread_bps=0""")
print("bps=0 UNRESOLVED: n=%s gid_null=%s gsz_null=%s min_sz=%s max_sz=%s n_ptypes=%s"%c.fetchone())
c.execute(f"""SELECT package_type, count(*) FROM {PACKAGES_TABLE}
 WHERE opa_sign_confidence='UNRESOLVED' AND dealer_spread_bps=0
 GROUP BY 1 ORDER BY 2 DESC LIMIT 6""")
print("by package_type:", c.fetchall())
c.execute(f"""SELECT p.package_id, p.ptp_group_id, p.ptp_group_size, p.package_transaction_price,
   count(l.*) AS legs,
   count(l.package_transaction_price) AS legs_with_ptp,
   count(DISTINCT l.package_transaction_price) AS distinct_ptp,
   count(l.other_payment_amount) AS legs_with_opa
 FROM {PACKAGES_TABLE} p JOIN {LEGS_TABLE} l ON l.ptp_group_id = p.ptp_group_id
 WHERE p.opa_sign_confidence='UNRESOLVED' AND p.dealer_spread_bps=0
 GROUP BY 1,2,3,4 LIMIT 5""")
print("samples (pkg, gid, gsz, pkg_ptp, legs, legs_with_ptp, distinct_ptp, legs_with_opa):")
for r in c.fetchall(): print("  ", r)
