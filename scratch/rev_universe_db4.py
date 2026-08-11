"""Batch 4: nail the two claims that did not reproduce."""
import os
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 220)
conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)
T = LEGS_TABLE


def q(label, sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_sql(sql, conn)
    print()
    print("### " + label)
    print(df.to_string(index=False))


q("Q40 'Amortizing' label token vs upi_notional_schedule, every population",
  f"""SELECT pop, n_sched_amortizing, n_label_token, n_sched_and_label
      FROM (
        SELECT 'all rows' pop,
          count(*) FILTER (WHERE upi_notional_schedule='Amortizing') n_sched_amortizing,
          count(*) FILTER (WHERE leg_tape_label LIKE '%%Amortizing%%') n_label_token,
          count(*) FILTER (WHERE upi_notional_schedule='Amortizing'
                           AND leg_tape_label LIKE '%%Amortizing%%') n_sched_and_label
        FROM {T}
        UNION ALL
        SELECT 'contributes_to_flow',
          count(*) FILTER (WHERE upi_notional_schedule='Amortizing'),
          count(*) FILTER (WHERE leg_tape_label LIKE '%%Amortizing%%'),
          count(*) FILTER (WHERE upi_notional_schedule='Amortizing'
                           AND leg_tape_label LIKE '%%Amortizing%%')
        FROM {T} WHERE contributes_to_flow
        UNION ALL
        SELECT 'ECONOMIC_FLOW',
          count(*) FILTER (WHERE upi_notional_schedule='Amortizing'),
          count(*) FILTER (WHERE leg_tape_label LIKE '%%Amortizing%%'),
          count(*) FILTER (WHERE upi_notional_schedule='Amortizing'
                           AND leg_tape_label LIKE '%%Amortizing%%')
        FROM {T} WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow
      ) s""")

q("Q41 risk NULL / quantisation on ECONOMIC_FLOW (claim: 2,289,189 non-null, all mult of 100)",
  f"""SELECT count(*) n_flow,
        count(*) FILTER (WHERE risk IS NOT NULL) n_non_null,
        count(*) FILTER (WHERE risk IS NOT NULL AND mod(risk::numeric, 100) <> 0) n_not_mult_100,
        min(abs(risk)) FILTER (WHERE risk <> 0) min_nonzero
      FROM {T} WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow""")

q("Q42 Term SOFR: which population gives 32,842?",
  f"""SELECT
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%') all_rows,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%' AND contributes_to_flow) ctf,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                         AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow) ef,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                         AND rate_index_clean='SOFR') ef_sofr_all,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%' AND rate_index_clean='SOFR'
                         AND economic_class='ECONOMIC_FLOW' AND contributes_to_flow) ef_sofr
      FROM {T}""")

conn.close()
print("\ndone")
