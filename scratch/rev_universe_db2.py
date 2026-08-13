"""Batch 2: size the any()/all() blind spots and spot-check docstring claims."""
import os
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 100)

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
    return df


q("Q20 multi-leg packages where SOME BUT NOT ALL legs trip a gate",
  f"""SELECT
        count(*) FILTER (WHERE n>1 AND nf>0 AND nf<n)      AS mixed_not_flow,
        count(*) FILTER (WHERE n>1 AND nc>0 AND nc<n)      AS mixed_nonconstant,
        count(*) FILTER (WHERE n>1 AND nr>0 AND nr<n)      AS mixed_no_fixed_rate,
        count(*) FILTER (WHERE n>1 AND ts>0 AND ts<n)      AS mixed_term_sofr,
        count(*) FILTER (WHERE n>1 AND xt>0 AND xt<n)      AS mixed_excluded_type,
        count(*) FILTER (WHERE n>1 AND sen>0 AND sen<n)    AS mixed_notional_sentinel,
        count(*) FILTER (WHERE n>1 AND rn>0 AND rn<n)      AS mixed_risk_null,
        count(*) FILTER (WHERE n>1)                        AS multileg_pkgs
      FROM (
        SELECT package_id, count(*) n,
          count(*) FILTER (WHERE NOT contributes_to_flow) nf,
          count(*) FILTER (WHERE upi_notional_schedule IN ('Amortizing','Custom','Accreting')) nc,
          count(*) FILTER (WHERE fixed_rate IS NULL) nr,
          count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%') ts,
          count(*) FILTER (WHERE trade_type IN ('SPREADOVER','SPREADOVER_CURVE',
              'SPREADOVER_FLY','MATCHED_MATURITY','MATCHED_MATURITY_CURVE',
              'MATCHED_MATURITY_FLY','INVOICE','INVOICE_SWAP','INVOICE_CALENDAR',
              'INVOICE_SWITCH')) xt,
          count(*) FILTER (WHERE notional >= 1e11) sen,
          count(*) FILTER (WHERE risk IS NULL) rn
        FROM {T} GROUP BY package_id
      ) s""")

q("Q21 is_mac population (report claims 15,026 units)",
  f"""SELECT count(*) FILTER (WHERE is_mac) n_is_mac,
             count(*) FILTER (WHERE is_mac AND trade_type='MAC') n_both,
             count(*) FILTER (WHERE is_mac AND trade_type<>'MAC') n_mac_flag_other_type,
             count(DISTINCT package_id) FILTER (WHERE is_mac) n_mac_pkgs
      FROM {T}""")

q("Q22 BASIS_CURVE / BASIS_FLY -- caught by rate_index_clean?",
  f"""SELECT trade_type, coalesce(rate_index_clean,'(null)') idx, count(*) n
      FROM {T} WHERE trade_type IN ('BASIS_CURVE','BASIS_FLY','FOMC')
      GROUP BY 1,2 ORDER BY n DESC""")

q("Q23 rate_index_clean distribution (docstring: SOFR 2,234,429 / FF 70,709 / BASIS 15,259 / OTHER 6,384)",
  f"""SELECT coalesce(rate_index_clean,'(null)') idx, count(*) n
      FROM {T} GROUP BY 1 ORDER BY n DESC""")

q("Q24 the 1,415 |rate|>=1 rows with normal notional -- what are they",
  f"""SELECT width_bucket(abs(fixed_rate), 1, 20, 4) b,
             count(*) n, min(abs(fixed_rate)) lo, max(abs(fixed_rate)) hi,
             count(*) FILTER (WHERE trade_type='MAC') n_mac
      FROM {T} WHERE abs(fixed_rate) >= 1.0 AND notional < 1e11
      GROUP BY 1 ORDER BY 1""")

q("Q25 fixed_rate scale sanity (is it a fraction?)",
  f"""SELECT count(*) n, min(fixed_rate) lo,
             percentile_disc(0.5) WITHIN GROUP (ORDER BY fixed_rate) med,
             max(fixed_rate) hi
      FROM {T} WHERE contributes_to_flow AND fixed_rate IS NOT NULL""")

q("Q26 the 1105-day cutoff claim (69.7% of 2,289,646 flow legs)",
  f"""SELECT count(*) n_flow,
             count(*) FILTER (WHERE expiration_date - as_of_date > 1105) n_beyond,
             round(100.0*count(*) FILTER (WHERE expiration_date - as_of_date > 1105)
                   / count(*), 1) pct
      FROM {T} WHERE economic_class='ECONOMIC_FLOW' AND contributes_to_flow""")

q("Q27 packages with exactly one leg (unit loses its package_id)",
  f"""SELECT count(*) FILTER (WHERE n=1) one_leg_pkgs, count(*) all_pkgs
      FROM (SELECT package_id, count(*) n FROM {T} GROUP BY package_id) s""")

q("Q28 ECONOMIC_UNWIND legs admitted by contributes_to_flow, by lifecycle",
  f"""SELECT economic_class, coalesce(lifecycle_type,'(null)') lc, count(*) n
      FROM {T} WHERE economic_class <> 'ECONOMIC_FLOW'
      GROUP BY 1,2 ORDER BY n DESC""")

q("Q29 risk NULL / zero among admitted legs",
  f"""SELECT count(*) FILTER (WHERE risk IS NULL) n_null,
             count(*) FILTER (WHERE risk = 0) n_zero,
             count(*) n
      FROM {T} WHERE contributes_to_flow""")

conn.close()
print("\ndone")
