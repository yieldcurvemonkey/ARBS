"""Batch 3: try to reproduce the headline numbers quoted in the docstrings."""
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
FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"


def q(label, sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_sql(sql, conn)
    print()
    print("### " + label)
    print(df.to_string(index=False))
    return df


q("Q30 1105-day cutoff: every plausible reading of 'discards 69.7% (1,595,321)'",
  f"""SELECT count(*) n_flow,
        count(*) FILTER (WHERE expiration_date - as_of_date > 1105) exp_minus_asof_gt,
        count(*) FILTER (WHERE expiration_date - as_of_date >= 1105) exp_minus_asof_ge,
        count(*) FILTER (WHERE expiration_date - effective_date > 1105) exp_minus_eff_gt,
        count(*) FILTER (WHERE tenor_years > 1105/365.25) tenor_gt,
        count(*) FILTER (WHERE tenor_years > 3.02) tenor_gt_302
      FROM {T} WHERE {FLOW}""")

q("Q31 Term SOFR flow legs (docstring: 32,842)",
  f"""SELECT count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%') n_all_rows_flow
      FROM {T} WHERE {FLOW}""")

q("Q32 venue flow counts on ECONOMIC_FLOW (docstring table)",
  f"""SELECT platform_identifier pid, count(*) n
      FROM {T} WHERE {FLOW}
        AND platform_identifier IN ('TREU','BMTF','RTXF','ISWE','TWEM','BTFE','GSEF','TRWB','BGCO')
      GROUP BY 1 ORDER BY n DESC""")

q("Q33 MAC: 98.85% of flow legs carry an other payment?",
  f"""SELECT count(*) n_mac_flow,
        count(*) FILTER (WHERE coalesce(other_payment_amount,0) <> 0) n_with_other_payment,
        round(100.0*count(*) FILTER (WHERE coalesce(other_payment_amount,0) <> 0)/count(*),2) pct,
        count(*) FILTER (WHERE coalesce(other_payment_ufro,0) <> 0) n_with_ufro
      FROM {T} WHERE {FLOW} AND is_mac""")

q("Q34 the 'Amortizing' label token caught 15,527 of 35,470?",
  f"""SELECT count(*) n_amortizing_schedule,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%Amortizing%%') n_label_token
      FROM {T} WHERE {FLOW} AND upi_notional_schedule='Amortizing'""")

q("Q35 upfront presence by venue class (the fingerprint table)",
  f"""SELECT platform_identifier pid, count(*) n,
        round(100.0*count(*) FILTER (WHERE coalesce(other_payment_ufro,0)<>0)/count(*),1) pct_upfront,
        round(100.0*count(*) FILTER (WHERE trade_type='OUTRIGHT')/count(*),1) pct_outright
      FROM {T} WHERE {FLOW} AND platform_identifier IN
        ('TREU','TWEM','BMTF','BTFE','ISWE','GSEF','RTXF','XOFF','XXXX')
      GROUP BY 1 ORDER BY n DESC""")

q("Q36 the 55 sentinel legs: are they excluded on other grounds anyway?",
  f"""SELECT count(*) n, count(*) FILTER (WHERE contributes_to_flow) n_flow,
        count(DISTINCT platform_identifier) n_pid,
        string_agg(DISTINCT platform_identifier, ',') pids
      FROM {T} WHERE notional >= 1e11""")

conn.close()
print("\ndone")
