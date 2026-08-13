import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED","0")
import psycopg2
from SDRUtils._swappulse_scripts._tape_tables import PACKAGES_TABLE, LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
c=psycopg2.connect(resolve_pg_url()).cursor()
c.execute(f"""SELECT count(*) AS legs,
   count(*) FILTER (WHERE l.opa_sign = 1) AS plus1,
   count(*) FILTER (WHERE l.opa_sign = -1) AS minus1,
   count(DISTINCT l.ptp_group_id) AS groups
 FROM {LEGS_TABLE} l JOIN {PACKAGES_TABLE} p ON p.ptp_group_id=l.ptp_group_id
 WHERE p.opa_sign_confidence='UNRESOLVED'
   AND l.ptp_group_id LIKE 'PTS/_%%' ESCAPE '/'
   AND l.other_payment_amount IS NOT NULL""")
print("PTS-keyed UNRESOLVED legs WITH an OPA: legs=%s opa_sign=+1:%s -1:%s groups=%s"%c.fetchone())
