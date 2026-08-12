"""READ-ONLY: the RATE_SENTINEL population (review 3.7) and the notional headroom."""
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


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"

print("RATE_SENTINEL population (|fixed_rate| >= 1.0)")
print(q(f"""
    SELECT count(*) all_rows,
           count(*) FILTER (WHERE {FLOW}) flow,
           count(*) FILTER (WHERE notional < 1e11) ordinary_notional,
           count(*) FILTER (WHERE notional >= 1e11) sentinel_notional,
           count(*) FILTER (WHERE abs(fixed_rate) >= 9.89 AND abs(fixed_rate) <= 9.91) near_99,
           min(abs(fixed_rate)) lo, max(abs(fixed_rate)) hi
    FROM {LEGS_TABLE} WHERE abs(fixed_rate) >= 1.0
""").to_string(index=False))

print()
print("bucketed")
print(q(f"""
    SELECT width_bucket(abs(fixed_rate), 1.0, 11.0, 10) b,
           count(*) n, min(abs(fixed_rate)) lo, max(abs(fixed_rate)) hi
    FROM {LEGS_TABLE} WHERE abs(fixed_rate) >= 1.0 AND notional < 1e11
    GROUP BY 1 ORDER BY 1
""").to_string(index=False))

print()
print("notional headroom: anything between the measured legit max and 1e11?")
print(q(f"""
    SELECT count(*) FILTER (WHERE notional > 2.86e10 AND notional < 1e11) in_gap,
           count(*) FILTER (WHERE notional >= 1e11) sentinels,
           max(notional) FILTER (WHERE notional < 1e11) max_legit
    FROM {LEGS_TABLE}
""").to_string(index=False))

conn.close()
print("DONE")
