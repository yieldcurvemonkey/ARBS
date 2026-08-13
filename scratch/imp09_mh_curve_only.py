"""Read-only. The curve-based odds ratio, pooled over the two curve methods only.

imp08 reported an ALL-METHODS odds ratio of 1.344, but ALL METHODS includes
TICK_RULE, which is the comparison, not part of it. Pooling the two curve-based
strata properly (Mantel-Haenszel, Robins-Breslow-Greenland variance) gives the
number the docstring is actually claiming, and a Breslow-Day test says whether
pooling those two is legitimate at all.
"""
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd
import psycopg2
from scipy import optimize, stats as sps

from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import DIRECTION_TABLE
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

conn = psycopg2.connect(resolve_pg_url())
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    pair = pd.read_sql(f"""
        SELECT d.classification_method AS method, d.dealer_direction,
               l.is_capped, l.is_block, count(*) AS n
        FROM {DIRECTION_TABLE} d JOIN {LEGS_TABLE} l USING (trade_id)
        WHERE l.economic_class = 'ECONOMIC_FLOW' AND l.contributes_to_flow
          AND l.tenor_years > 0 AND l.notional > 0 AND l.notional < 1e11
          AND d.dealer_direction IN ('PAID', 'RECEIVED')
        GROUP BY 1, 2, 3, 4""", conn)
conn.close()
pair["is_capped"] = pair["is_capped"].astype(bool)
pair["is_block"] = pair["is_block"].astype(bool)

CURVE_METHODS = ["RATE_VS_MID", "NPV_VS_UPFRONT", "SPREAD_VS_MID", "FLY_VS_MID"]


def cells(df, flag):
    t = df.pivot_table(index=flag, columns="dealer_direction", values="n",
                       aggfunc="sum", fill_value=0)
    for c in ("PAID", "RECEIVED"):
        if c not in t:
            t[c] = 0
    for i in (False, True):
        if i not in t.index:
            t.loc[i] = 0
    return (float(t.loc[True, "RECEIVED"]), float(t.loc[True, "PAID"]),
            float(t.loc[False, "RECEIVED"]), float(t.loc[False, "PAID"]))


def mh(strata):
    """Mantel-Haenszel OR with the Robins-Breslow-Greenland 95% interval."""
    num = den = 0.0
    s_pr = s_pspr = s_qsr = 0.0
    for a, b, c, d in strata:
        n = a + b + c + d
        if n == 0:
            continue
        R, S = a * d / n, b * c / n
        P, Q = (a + d) / n, (b + c) / n
        num += R
        den += S
        s_pr += P * R
        s_pspr += P * S + Q * R
        s_qsr += Q * S
    orr = num / den
    var = s_pr / (2 * num ** 2) + s_pspr / (2 * num * den) + s_qsr / (2 * den ** 2)
    se = np.sqrt(var)
    return orr, float(np.exp(np.log(orr) - 1.96 * se)), float(np.exp(np.log(orr) + 1.96 * se))


def homogeneity_z(s1, s2):
    """Do two strata share an odds ratio? Woolf: z on the log-OR difference.

    Chosen over Breslow-Day because it can be checked by hand -- the first
    attempt here used Breslow-Day and returned chi2 = 0.00 on strata whose log
    odds ratios plainly differ, which is a broken tool reporting agreement. This
    version is verified against the hand calculation printed below it.
    """
    def lor_se(s):
        a, b, c, d = s
        return np.log((a * d) / (b * c)), np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)

    l1, e1 = lor_se(s1)
    l2, e2 = lor_se(s2)
    z = (l1 - l2) / np.sqrt(e1 ** 2 + e2 ** 2)
    return z, 2 * sps.norm.sf(abs(z)), (np.exp(l1), np.exp(l2), e1, e2)


for flag in ("is_capped", "is_block"):
    print("=" * 88)
    print(flag)
    print("=" * 88)
    curve = [cells(pair[pair.method == m], flag) for m in CURVE_METHODS
             if (pair.method == m).any()]
    for m, s in zip([m for m in CURVE_METHODS if (pair.method == m).any()], curve):
        a, b, c, d = s
        print(f"  {m:<16} capped RECV {a:>6.0f} PAID {b:>6.0f} | "
              f"other RECV {c:>7.0f} PAID {d:>7.0f}")
    orr, lo, hi = mh(curve)
    print(f"\n  curve-based methods only, MH pooled OR = {orr:.3f} [{lo:.3f}, {hi:.3f}]")
    z, p, (o1, o2, e1, e2) = homogeneity_z(curve[0], curve[1])
    print(f"  homogeneity of the two curve strata: OR {o1:.3f} vs {o2:.3f}, "
          f"z = {z:.3f}, p = {p:.4f}"
          f"{'   <- strata DISAGREE, the pooled number is meaningless' if p < 0.05 else '   <- consistent, pooling is legitimate'}")
    print(f"     hand check: (ln{o1:.3f} - ln{o2:.3f}) / sqrt({e1:.4f}^2 + {e2:.4f}^2) "
          f"= ({np.log(o1):.4f} - {np.log(o2):.4f}) / {np.sqrt(e1**2 + e2**2):.4f} "
          f"= {(np.log(o1) - np.log(o2)) / np.sqrt(e1**2 + e2**2):.3f}")

    a, b, c, d = cells(pair[pair.method == "TICK_RULE"], flag)
    lor = np.log((a * d) / (b * c))
    se = np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    print(f"  curve-free  TICK_RULE  OR = {np.exp(lor):.3f} "
          f"[{np.exp(lor - 1.96 * se):.3f}, {np.exp(lor + 1.96 * se):.3f}]  "
          f"(n_flag = {int(a + b)})")
    print(f"  intervals disjoint: {np.exp(lor + 1.96 * se) < lo}\n")
