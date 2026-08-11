"""READ-ONLY measurements for the universe-module review fixes.

Everything here is a SELECT. Nothing writes.
"""
import os
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import sanity

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 40)
pd.set_option("display.max_rows", 200)

conn = psycopg2.connect(resolve_pg_url())


def q(sql, **params):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params or None)


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"

print("=" * 78)
print("A. FLAT_YIELD anchors: measured annuity |risk|/notional*1e4 by exact tenor")
print("=" * 78)
rows = []
for label, lo, hi in [("1y", 0.98, 1.02), ("2y", 1.98, 2.02), ("3y", 2.98, 3.02),
                      ("5y", 4.98, 5.02), ("7y", 6.98, 7.02), ("10y", 9.98, 10.02),
                      ("15y", 14.98, 15.02), ("20y", 19.98, 20.02),
                      ("30y", 29.98, 30.02), ("40y", 39.9, 40.1)]:
    d = q(f"""
        SELECT tenor_years, notional, abs(risk) ar
        FROM {LEGS_TABLE}
        WHERE {FLOW} AND notional > 0 AND notional < 1e11
          AND risk IS NOT NULL AND risk <> 0
          AND coalesce(forward_start_years,0) < 0.02
          AND tenor_years >= %(lo)s AND tenor_years <= %(hi)s
    """, lo=lo, hi=hi)
    if d.empty:
        rows.append((label, 0, np.nan, np.nan, np.nan, np.nan))
        continue
    a_meas = (d["ar"].astype(float) / d["notional"].astype(float)) * 1e4
    t_med = float(d["tenor_years"].astype(float).median())
    rows.append((label, len(d), t_med, float(a_meas.median()),
                 float(a_meas.quantile(0.25)), float(a_meas.quantile(0.75))))
anch = pd.DataFrame(rows, columns=["tenor", "n", "t_med", "A_meas_median",
                                   "A_p25", "A_p75"])
anch["A_model_004"] = [float(sanity.annuity(t)) if t == t else np.nan
                       for t in anch["t_med"]]
anch["A_model_002"] = [float(sanity.annuity(t, flat_yield=0.02)) if t == t else np.nan
                       for t in anch["t_med"]]
anch["ratio_004"] = anch["A_meas_median"] / anch["A_model_004"]
anch["ratio_002"] = anch["A_meas_median"] / anch["A_model_002"]
print(anch.to_string(index=False))

print()
print("=" * 78)
print("B. the docstring's own tenor-band ratio table (|risk| / expected_dv01)")
print("=" * 78)
bands = [("<6m", 0.0, 0.5), ("6m-2y", 0.5, 2.0), ("2-5y", 2.0, 5.0),
         ("5-10y", 5.0, 10.0), ("10-25y", 10.0, 25.0), (">25y", 25.0, 1e9)]
out = []
for label, lo, hi in bands:
    d = q(f"""
        SELECT tenor_years, notional, forward_start_years, risk
        FROM {LEGS_TABLE}
        WHERE {FLOW} AND notional > 0 AND notional < 1e11
          AND risk IS NOT NULL AND risk <> 0
          AND tenor_years > %(lo)s AND tenor_years <= %(hi)s
        ORDER BY md5(trade_id || leg_order::text) LIMIT 60000
    """, lo=lo, hi=hi)
    exp = sanity.expected_dv01(d["notional"].astype(float),
                               d["tenor_years"].astype(float),
                               d["forward_start_years"].astype(float))
    r = np.abs(d["risk"].astype(float).to_numpy()) / exp
    out.append((label, len(d), float(np.nanmedian(r))))
print(pd.DataFrame(out, columns=["band", "n", "median_ratio"]).to_string(index=False))

print()
print("=" * 78)
print("C. RISK_ZERO_MATERIAL: exp_dv01 distribution of risk=0 and risk=100 legs")
print("=" * 78)
z = q(f"""
    SELECT notional, tenor_years, forward_start_years
    FROM {LEGS_TABLE}
    WHERE {FLOW} AND risk = 0 AND notional > 0 AND notional < 1e11
      AND tenor_years > 0
""")
zexp = sanity.expected_dv01(z["notional"].astype(float),
                            z["tenor_years"].astype(float),
                            z["forward_start_years"].astype(float))
print(f"  risk=0 flow legs (testable inputs): {len(z):,}")
for p in (0.5, 0.75, 0.9, 0.95, 0.99, 1.0):
    print(f"    exp_dv01 p{p:<5} {np.nanquantile(zexp, p):>14,.1f}")
for thr in (50, 100, 150, 200, 300, 500, 1000, 3000, 30000):
    print(f"    flagged at exp > {thr:>6}: {int((zexp > thr).sum()):>7,}"
          f"  ({(zexp > thr).mean():.2%})   admitted: {int((zexp <= thr).sum()):>7,}")

h = q(f"""
    SELECT notional, tenor_years, forward_start_years
    FROM {LEGS_TABLE}
    WHERE {FLOW} AND risk = 100 AND notional > 0 AND notional < 1e11
      AND tenor_years > 0
    ORDER BY md5(trade_id || leg_order::text) LIMIT 60000
""")
hexp = sanity.expected_dv01(h["notional"].astype(float),
                            h["tenor_years"].astype(float),
                            h["forward_start_years"].astype(float))
print(f"  risk=100 flow legs sampled: {len(h):,}")
for p in (0.01, 0.05, 0.5, 0.95, 0.99):
    print(f"    exp_dv01 p{p:<5} {np.nanquantile(hexp, p):>14,.1f}")

print()
print("=" * 78)
print("D. review 3.1 -- the 1105-day cutoff vs the tenor_years > 3.02 proxy")
print("=" * 78)
print(q(f"""
    SELECT count(*) n_flow,
           count(*) FILTER (WHERE expiration_date > as_of_date + interval '1105 days')
               AS beyond_1105,
           count(*) FILTER (WHERE tenor_years > 3.02) AS tenor_gt_302
    FROM {LEGS_TABLE} WHERE {FLOW}
""").to_string(index=False))

print()
print("=" * 78)
print("E. review 3.2 -- Amortizing label token vs upi_notional_schedule")
print("=" * 78)
for pop, where in (("all rows", "TRUE"),
                   ("contributes_to_flow", "contributes_to_flow"),
                   ("ECONOMIC_FLOW+ctf", FLOW)):
    print(pop, q(f"""
        SELECT count(*) FILTER (WHERE leg_tape_label LIKE '%%Amortizing%%') tok,
               count(*) FILTER (WHERE upi_notional_schedule = 'Amortizing') sched,
               count(*) FILTER (WHERE leg_tape_label LIKE '%%Amortizing%%'
                                  AND upi_notional_schedule = 'Amortizing') both
        FROM {LEGS_TABLE} WHERE {where}
    """).to_dict("records"))
print("  schedule mix (contributes_to_flow):")
print(q(f"""
    SELECT coalesce(upi_notional_schedule,'(null)') s, count(*) n
    FROM {LEGS_TABLE} WHERE contributes_to_flow GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

print()
print("=" * 78)
print("F. review 3.3 -- the FX/NDF codes said not to appear on this tape")
print("=" * 78)
print(q(f"""
    SELECT platform_identifier, count(*) n
    FROM {LEGS_TABLE}
    WHERE platform_identifier IN ('CBNL','JPCB','EBSS','XEBS','THRE','BHSF')
    GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

print()
print("=" * 78)
print("G. review 3.4 -- CME Term label populations")
print("=" * 78)
print(q(f"""
    SELECT count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                              AND rate_index_clean='SOFR') all_rows_pair,
           count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                              AND rate_index_clean='SOFR' AND {FLOW}) flow_pair,
           count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%'
                              AND contributes_to_flow) ctf_label,
           count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%') all_label
    FROM {LEGS_TABLE}
""").to_string(index=False))

print()
print("=" * 78)
print("H. review 4.1 -- contributes_to_flow by economic_class / lifecycle_type")
print("=" * 78)
print(q(f"""
    SELECT economic_class, contributes_to_flow, count(*) n
    FROM {LEGS_TABLE} GROUP BY 1,2 ORDER BY 1,2
""").to_string(index=False))
print(q(f"""
    SELECT economic_class, lifecycle_type, count(*) n
    FROM {LEGS_TABLE}
    WHERE contributes_to_flow AND economic_class <> 'ECONOMIC_FLOW'
    GROUP BY 1,2 ORDER BY 3 DESC
""").to_string(index=False))

print()
print("=" * 78)
print("I. the any->all live reachability: some-but-not-all legs bad in a package")
print("=" * 78)
print(q(f"""
    WITH p AS (
      SELECT package_id, count(*) n,
             count(*) FILTER (WHERE fixed_rate IS NULL) n_norate,
             count(*) FILTER (WHERE risk IS NULL) n_norisk,
             count(*) FILTER (WHERE NOT contributes_to_flow) n_notflow,
             count(*) FILTER (WHERE upi_notional_schedule IS DISTINCT FROM 'Constant'
                                AND upi_notional_schedule IS NOT NULL) n_nonconst,
             count(*) FILTER (WHERE leg_tape_label LIKE '%%CME Term%%') n_term,
             count(DISTINCT rate_index_clean) n_idx,
             count(*) FILTER (WHERE rate_index_clean IS NULL) n_nullidx
      FROM {LEGS_TABLE} GROUP BY package_id HAVING count(*) > 1)
    SELECT count(*) FILTER (WHERE n_norate  BETWEEN 1 AND n-1) mixed_norate,
           count(*) FILTER (WHERE n_norisk  BETWEEN 1 AND n-1) mixed_norisk,
           count(*) FILTER (WHERE n_notflow BETWEEN 1 AND n-1) mixed_notflow,
           count(*) FILTER (WHERE n_nonconst BETWEEN 1 AND n-1) mixed_nonconst,
           count(*) FILTER (WHERE n_term    BETWEEN 1 AND n-1) mixed_term,
           count(*) FILTER (WHERE n_idx > 1) mixed_index,
           count(*) FILTER (WHERE n_nullidx > 0) any_null_index
    FROM p
""").to_string(index=False))

print()
print("=" * 78)
print("J. review 3.5 -- venue counts under the two populations")
print("=" * 78)
print(q(f"""
    SELECT platform_identifier,
           count(*) FILTER (WHERE {FLOW}) flow_ctf,
           count(*) FILTER (WHERE contributes_to_flow) ctf,
           count(*) all_rows
    FROM {LEGS_TABLE}
    WHERE platform_identifier IN
      ('TREU','BMTF','RTXF','ISWE','TWEM','BTFE','GSEF','BGCO','TRWB',
       'BILT','XXXX','XOFF')
    GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

print()
print("=" * 78)
print("K. INVOICE_SWAP / trade_type census (review 3.8)")
print("=" * 78)
print(q(f"""
    SELECT trade_type, count(*) n FROM {LEGS_TABLE}
    WHERE trade_type LIKE 'INVOICE%%' OR trade_type LIKE 'BASIS%%'
    GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

conn.close()
print("\nDONE")
