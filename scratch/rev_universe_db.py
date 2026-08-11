"""Read-only prod measurements sizing the universe-module review findings."""
import os
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 200)
pd.set_option("display.max_rows", 200)

conn = psycopg2.connect(resolve_pg_url())
conn.set_session(readonly=True)


def q(label, sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_sql(sql, conn)
    print()
    print("### " + label)
    print(df.to_string(index=False))
    return df


T = LEGS_TABLE
print("table:", T)

q("Q0 row/trade cardinality",
  f"""SELECT count(*) n_rows, count(DISTINCT trade_id) n_trade_ids,
             count(*) FILTER (WHERE package_id IS NULL) n_no_pkg
      FROM {T}""")

q("Q1 multi-row trade_ids with NULL package_id (would become CURVE/FLY units)",
  f"""SELECT n_rows_per_trade, count(*) n_trades FROM (
        SELECT trade_id, count(*) n_rows_per_trade
        FROM {T} WHERE package_id IS NULL GROUP BY trade_id
      ) s WHERE n_rows_per_trade > 1
      GROUP BY 1 ORDER BY 1""")

q("Q1b multi-row trade_ids overall",
  f"""SELECT n, count(*) n_trades FROM (
        SELECT trade_id, count(*) n FROM {T} GROUP BY trade_id
      ) s WHERE n > 1 GROUP BY 1 ORDER BY 1 LIMIT 20""")

q("Q2 total-order claim: duplicate (unit_group, exp, eff, trade_id) groups",
  f"""SELECT count(*) n_dup_groups, coalesce(sum(c),0) n_rows_in_dups FROM (
        SELECT coalesce(package_id, trade_id) g, expiration_date, effective_date,
               trade_id, count(*) c
        FROM {T}
        GROUP BY 1,2,3,4 HAVING count(*) > 1
      ) s""")

q("Q3 flow definition: contributes_to_flow vs economic_class",
  f"""SELECT economic_class, contributes_to_flow, count(*) n
      FROM {T} GROUP BY 1,2 ORDER BY n DESC LIMIT 20""")

q("Q4 lifecycle_type distribution (incl NULL)",
  f"""SELECT coalesce(lifecycle_type,'(null)') lifecycle_type, count(*) n
      FROM {T} GROUP BY 1 ORDER BY n DESC LIMIT 20""")

q("Q5 non-NEW_TRADE rows with NULL event_timestamp (build_universe raises)",
  f"""SELECT coalesce(lifecycle_type,'(null)') lifecycle_type,
             count(*) n,
             count(*) FILTER (WHERE contributes_to_flow) n_flow
      FROM {T}
      WHERE coalesce(lifecycle_type,'x') <> 'NEW_TRADE' AND event_timestamp IS NULL
      GROUP BY 1 ORDER BY n DESC LIMIT 20""")

q("Q5b any row at all with NULL event_timestamp",
  f"""SELECT count(*) n_null_event,
             count(*) FILTER (WHERE lifecycle_type='NEW_TRADE') n_newt
      FROM {T} WHERE event_timestamp IS NULL""")

q("Q6 NEW_TRADE where original_execution_timestamp <> execution_timestamp",
  f"""SELECT count(*) n_newt,
             count(*) FILTER (WHERE original_execution_timestamp IS NOT NULL
                              AND original_execution_timestamp <> execution_timestamp) n_diff,
             max(abs(extract(epoch FROM (execution_timestamp - original_execution_timestamp)))) max_abs_sec
      FROM {T} WHERE lifecycle_type = 'NEW_TRADE'""")

q("Q6b same, flow only, with the biggest gaps",
  f"""SELECT count(*) n_diff_flow,
             round(max(abs(extract(epoch FROM (execution_timestamp - original_execution_timestamp))))/86400.0, 1) max_days
      FROM {T}
      WHERE lifecycle_type='NEW_TRADE' AND contributes_to_flow
        AND original_execution_timestamp IS NOT NULL
        AND original_execution_timestamp <> execution_timestamp""")

q("Q7 event_timestamp_granularity distribution",
  f"""SELECT coalesce(event_timestamp_granularity,'(null)') g, count(*) n,
             count(*) FILTER (WHERE contributes_to_flow) n_flow
      FROM {T} GROUP BY 1 ORDER BY n DESC LIMIT 20""")

q("Q7b rows whose event_timestamp is exactly 00:00:00 UTC (EOD-fallback path)",
  f"""SELECT count(*) n_midnight_utc,
             count(*) FILTER (WHERE contributes_to_flow) n_flow,
             count(*) FILTER (WHERE coalesce(lifecycle_type,'x') <> 'NEW_TRADE') n_non_newt
      FROM {T}
      WHERE event_timestamp IS NOT NULL
        AND (event_timestamp AT TIME ZONE 'UTC')::time = '00:00:00'""")

q("Q8 trade_type values vs EXCLUDED_TRADE_TYPES",
  f"""SELECT coalesce(trade_type,'(null)') trade_type, count(*) n,
             count(*) FILTER (WHERE contributes_to_flow) n_flow
      FROM {T} GROUP BY 1 ORDER BY n DESC LIMIT 60""")

q("Q9 CME Term label case variants",
  f"""SELECT count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%') exact_token,
             count(*) FILTER (WHERE leg_tape_label ILIKE '%%cme term%%') any_case,
             count(*) FILTER (WHERE leg_tape_label ILIKE '%%term sofr%%') term_sofr_any_case,
             count(*) FILTER (WHERE leg_tape_label ILIKE '%%term sofr%%'
                              AND leg_tape_label NOT LIKE '%%CME Term%%') missed
      FROM {T}""")

q("Q10 negative other_payment_ufro / uwin",
  f"""SELECT count(*) FILTER (WHERE other_payment_ufro < 0) neg_ufro,
             count(*) FILTER (WHERE other_payment_ufro > 0) pos_ufro,
             count(*) FILTER (WHERE other_payment_uwin <> 0) any_uwin,
             count(*) FILTER (WHERE other_payment_pexh <> 0) any_pexh
      FROM {T}""")

q("Q10b packages carrying UFRO of BOTH signs (sum-then-abs cancels)",
  f"""SELECT count(*) n_pkgs FROM (
        SELECT package_id FROM {T} WHERE package_id IS NOT NULL
        GROUP BY package_id
        HAVING count(*) FILTER (WHERE other_payment_ufro > 0) > 0
           AND count(*) FILTER (WHERE other_payment_ufro < 0) > 0
      ) s""")

q("Q11 upi_notional_schedule distribution",
  f"""SELECT coalesce(upi_notional_schedule,'(null)') s, count(*) n,
             count(*) FILTER (WHERE contributes_to_flow) n_flow
      FROM {T} GROUP BY 1 ORDER BY n DESC LIMIT 20""")

q("Q12 packages spanning as_of_date / mixing platform / mixing index",
  f"""SELECT count(*) FILTER (WHERE n_dates > 1) span_dates,
             count(*) FILTER (WHERE n_plat > 1) mix_platform,
             count(*) FILTER (WHERE n_idx > 1) mix_index,
             count(*) n_pkgs
      FROM (
        SELECT package_id, count(DISTINCT as_of_date) n_dates,
               count(DISTINCT platform_identifier) n_plat,
               count(DISTINCT rate_index_clean) n_idx
        FROM {T} WHERE package_id IS NOT NULL GROUP BY package_id
      ) s""")

q("Q13 notional sentinel count and rate sentinel population",
  f"""SELECT count(*) FILTER (WHERE notional >= 1e11) n_notional_sentinel,
             count(*) FILTER (WHERE abs(fixed_rate) >= 1.0) n_rate_ge_1,
             count(*) FILTER (WHERE abs(fixed_rate) >= 1.0 AND notional < 1e11) n_rate_ge_1_normal_notional,
             count(*) FILTER (WHERE abs(fixed_rate) >= 1.0 AND contributes_to_flow) n_rate_ge_1_flow
      FROM {T}""")

q("Q14 platform codes present but unclassified",
  f"""SELECT coalesce(platform_identifier,'(null)') pid, count(*) n,
             count(*) FILTER (WHERE contributes_to_flow) n_flow
      FROM {T} GROUP BY 1 ORDER BY n DESC LIMIT 40""")

q("Q15 exercise/novation flags: any TRUE anywhere?",
  f"""SELECT count(*) FILTER (WHERE is_exercise_born) a,
             count(*) FILTER (WHERE is_novation) b,
             count(*) FILTER (WHERE is_novation_born) c,
             count(*) FILTER (WHERE is_novation_terminated) d
      FROM {T}""")

conn.close()
print("\ndone")
