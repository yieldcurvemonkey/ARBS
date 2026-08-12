"""Verify the numbers the FIX newly wrote into universe.py / sanity.py.

Read-only. Every claim here is one the fixer added; if it does not reproduce,
it is a NEW defect introduced by the fix, not an inherited one.
"""
import os
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 60)
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


q("V1 1105-day cutoff as the filter is WRITTEN (fix claims 1,671,827 = 73.0%)",
  f"""SELECT count(*) n_flow,
        count(*) FILTER (WHERE expiration_date > as_of_date + 1105) as_written,
        count(*) FILTER (WHERE tenor_years > 3.02) tenor_proxy
      FROM {T} WHERE {FLOW}""")

q("V2 Term SOFR -- fix claims 33,487 ctf legs removed by the LABEL-alone gate "
  "(review said 33,217)",
  f"""SELECT
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%') label_all_rows,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                         AND contributes_to_flow) label_ctf,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%' AND {FLOW}) label_ef,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                         AND rate_index_clean='SOFR') pair_all_rows,
        count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                         AND rate_index_clean='SOFR' AND {FLOW}) pair_ef
      FROM {T}""")

q("V2b would the ctf label-gate count still net of the other gates? "
  "(the gate reads higher than PRICING_ERROR but lower than NOT_FLOW/EXER)",
  f"""SELECT count(*) n
      FROM {T}
      WHERE leg_tape_label LIKE '%%CME Term%%' AND contributes_to_flow""")

q("V3 economic_class x contributes_to_flow (fix: FLOW 2,289,646 / UNWIND 36,828 "
  "/ ADMIN 307; admits 2,326,474)",
  f"""SELECT economic_class, contributes_to_flow, count(*) n
      FROM {T} GROUP BY 1,2 ORDER BY n DESC""")

q("V4 unwind legs stamped NEW_TRADE (fix: 36,763 of 36,828)",
  f"""SELECT coalesce(lifecycle_type,'(null)') lc, count(*) n
      FROM {T} WHERE economic_class='ECONOMIC_UNWIND'
      GROUP BY 1 ORDER BY n DESC""")

q("V5 PTP sign census (fix: 382,815 below -500, 403,314 above +500). "
  "Review 2.9 called dropping abs() a LATENT no-op.",
  f"""SELECT count(*) FILTER (WHERE package_transaction_price < -500) below_neg500,
             count(*) FILTER (WHERE package_transaction_price > 500) above_pos500,
             count(*) FILTER (WHERE package_transaction_price IS NOT NULL) n_ptp
      FROM {T}""")

q("V6 other_payment_ufro sign (fix: non-negative on EVERY row)",
  f"""SELECT count(*) FILTER (WHERE other_payment_ufro < 0) neg,
             count(*) FILTER (WHERE other_payment_ufro > 0) pos,
             min(other_payment_ufro) mn
      FROM {T}""")

q("V7 venue counts on contributes_to_flow (fix: TREU 25,224 BMTF 20,699 "
  "TWEM 4,785 BTFE 3,026 GSEF 2,659; RTXF/ISWE/BGCO/TRWB unchanged)",
  f"""SELECT platform_identifier,
        count(*) FILTER (WHERE contributes_to_flow) ctf,
        count(*) FILTER (WHERE {FLOW}) ef
      FROM {T}
      WHERE platform_identifier IN
        ('TREU','BMTF','RTXF','ISWE','TWEM','BTFE','GSEF','BGCO','TRWB','CBNL')
      GROUP BY 1 ORDER BY ctf DESC""")

q("V8 trade_type membership (fix: INVOICE 32,073 / INVOICE_SWITCH 4,916 / "
  "INVOICE_CALENDAR 792 / INVOICE_SWAP absent / BASIS_CURVE 1,150 / BASIS_FLY 210)",
  f"""SELECT trade_type, count(*) n FROM {T}
      WHERE trade_type IN ('INVOICE','INVOICE_SWITCH','INVOICE_CALENDAR',
                           'INVOICE_SWAP','BASIS_CURVE','BASIS_FLY')
      GROUP BY 1 ORDER BY n DESC""")

q("V9 non-constant schedules (fix: Custom 11,960 / Accreting 1,507 / "
  "Amortizing 35,470 on ctf; label token 1:1)",
  f"""SELECT coalesce(upi_notional_schedule,'(null)') sched,
        count(*) FILTER (WHERE contributes_to_flow) ctf,
        count(*) FILTER (WHERE contributes_to_flow
                         AND leg_tape_label LIKE '%%Amortizing%%') ctf_and_token
      FROM {T} GROUP BY 1 ORDER BY ctf DESC""")

q("V10 RATE_SENTINEL census (sanity fix: 1,469 rows, 54 on a sentinel notional, "
  "1,415 ordinary; 412 in [3,4), 415 in [6,7))",
  f"""SELECT count(*) n_ge1,
        count(*) FILTER (WHERE abs(notional) >= 1e11) on_sentinel_notional,
        count(*) FILTER (WHERE abs(notional) < 1e11 OR notional IS NULL) ordinary,
        count(*) FILTER (WHERE abs(fixed_rate) >= 3 AND abs(fixed_rate) < 4) in_3_4,
        count(*) FILTER (WHERE abs(fixed_rate) >= 6 AND abs(fixed_rate) < 7) in_6_7
      FROM {T} WHERE abs(fixed_rate) >= 1.0""")

q("V11 largest legitimate notional (sanity fix: NOTIONAL_LEGIT_MAX = 2.86e10) "
  "and the headroom gap the new validator tripwire watches",
  f"""SELECT count(*) FILTER (WHERE notional > 2.86e10 AND notional < 1e11) in_gap,
             count(*) FILTER (WHERE notional >= 1e11) at_or_above_bound,
             max(notional) FILTER (WHERE notional < 1e11) max_legit
      FROM {T}""")

q("V12 multi-leg packages with some-but-not-all NULL fixed_rate / risk "
  "(test docstrings: 136 and 107) and mixed economic_class (2,323)",
  f"""SELECT
        count(*) FILTER (WHERE n_legs > 1 AND n_null_rate > 0
                         AND n_null_rate < n_legs) mixed_null_rate,
        count(*) FILTER (WHERE n_legs > 1 AND n_null_risk > 0
                         AND n_null_risk < n_legs) mixed_null_risk,
        count(*) FILTER (WHERE n_legs > 1 AND n_class > 1) mixed_class
      FROM (
        SELECT package_id, count(*) n_legs,
               count(*) FILTER (WHERE fixed_rate IS NULL) n_null_rate,
               count(*) FILTER (WHERE risk IS NULL) n_null_risk,
               count(DISTINCT economic_class) n_class
        FROM {T} WHERE package_id IS NOT NULL GROUP BY package_id) s""")

# --- the FLAT_YIELD calibration table the new test pins ---------------------
# Computed from `risk` and `notional` ALONE, so it is independent of
# sanity.expected_dv01 -- the point of the test.
ann = q("V13 the tape's OWN implied annuity by tenor (sanity docstring table + "
        "the 10 rows _MEASURED_ANNUITY pins)",
        f"""SELECT round(tenor_years::numeric, 6) tenor, count(*) n_legs,
               percentile_cont(0.5) WITHIN GROUP (
                 ORDER BY abs(risk) / notional * 1e4) a_measured
        FROM {T}
        WHERE {FLOW} AND forward_start_years < 0.02
          AND risk IS NOT NULL AND risk <> 0
          AND notional > 0 AND notional < 1e11
        GROUP BY 1 HAVING count(*) > 1000 ORDER BY 1""")

import numpy as np  # noqa: E402
from SDRUtils.dealer_direction import sanity  # noqa: E402

print()
print("### V13b measured vs annuity(t) at FLAT_YIELD = 0.04 and 0.02")
rows = []
for t, n, a in ann.itertuples(index=False):
    t = float(t)
    a = float(a)
    a04 = float(sanity.annuity(t))
    a02 = (1.0 - np.exp(-0.02 * t)) / 0.02
    rows.append((t, int(n), a, a04, 100 * (a04 / a - 1), a02,
                 100 * (a02 / a - 1)))
print(pd.DataFrame(rows, columns=[
    "tenor", "n_legs", "a_measured", "a@0.04", "err%@0.04", "a@0.02",
    "err%@0.02"]).to_string(index=False))

q("V14 the RISK_ZERO_SLACK justification: risk=0 p95 and risk=100 p1 of "
  "expected DV01, and how many risk=0 legs the 3.0 vs 0.5 slack flags "
  "(sanity fix: p95 47.4, p1 49.9, 16,605 testable, 0 flagged, max 260, "
  "0.5 would flag 269 = 1.62%)",
  f"""WITH e AS (
        SELECT risk, notional * ((1 - exp(-0.04 * tenor_years)) / 0.04)
                     * exp(-0.04 * forward_start_years) * 1e-4 AS exp_dv01
        FROM {T}
        WHERE {FLOW} AND risk IS NOT NULL
          AND notional IS NOT NULL AND notional > 0 AND notional < 1e11
          AND tenor_years IS NOT NULL AND forward_start_years IS NOT NULL
          AND abs(fixed_rate) < 1.0)
      SELECT
        count(*) FILTER (WHERE risk = 0) n_zero_testable,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY exp_dv01)
          FILTER (WHERE risk = 0) p95_zero,
        max(exp_dv01) FILTER (WHERE risk = 0) max_zero,
        percentile_cont(0.01) WITHIN GROUP (ORDER BY exp_dv01)
          FILTER (WHERE risk = 100) p1_hundred,
        count(*) FILTER (WHERE risk = 0 AND exp_dv01 > 300) flagged_at_3,
        count(*) FILTER (WHERE risk = 0 AND exp_dv01 > 50) flagged_at_half
      FROM e""")

conn.close()
print("\ndone")
