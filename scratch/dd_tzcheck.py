import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
import pandas as pd
from sqlalchemy import create_engine
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE

eng = create_engine(resolve_pg_url())
q = f"""
select data_type from information_schema.columns
 where table_name = '{LEGS_TABLE}'
   and column_name in ('execution_timestamp','event_timestamp','original_execution_timestamp')
"""
print(pd.read_sql(q.replace("data_type","column_name, data_type"), eng).to_string(index=False))
df = pd.read_sql(f"select execution_timestamp, event_timestamp from {LEGS_TABLE} "
                 f"where as_of_date = date '2026-06-10' limit 3", eng)
print(df.dtypes)
print(df.head().to_string(index=False))
