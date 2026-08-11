"""READ-ONLY: negative package_transaction_price, and mixed economic_class packages."""
import os
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 240)
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


print("package_transaction_price sign census")
print(q(f"""
    SELECT count(*) FILTER (WHERE package_transaction_price < 0) neg,
           count(*) FILTER (WHERE package_transaction_price < -500) neg_over_floor,
           count(*) FILTER (WHERE package_transaction_price > 500) pos_over_floor,
           min(package_transaction_price) lo, max(package_transaction_price) hi
    FROM {LEGS_TABLE}
""").to_string(index=False))

print()
print("other_payment_ufro sign census")
print(q(f"""
    SELECT count(*) FILTER (WHERE other_payment_ufro < 0) neg,
           count(*) FILTER (WHERE other_payment_ufro > 0) pos,
           min(other_payment_ufro) lo
    FROM {LEGS_TABLE}
""").to_string(index=False))

print()
print("packages mixing economic_class / platform_identifier")
print(q(f"""
    WITH p AS (SELECT package_id, count(*) n,
                      count(DISTINCT economic_class) nc,
                      count(DISTINCT platform_identifier) np,
                      count(DISTINCT lifecycle_type) nl
               FROM {LEGS_TABLE} GROUP BY 1 HAVING count(*) > 1)
    SELECT count(*) multileg,
           count(*) FILTER (WHERE nc > 1) mixed_class,
           count(*) FILTER (WHERE np > 1) mixed_platform,
           count(*) FILTER (WHERE nl > 1) mixed_lifecycle
    FROM p
""").to_string(index=False))

conn.close()
print("DONE")
