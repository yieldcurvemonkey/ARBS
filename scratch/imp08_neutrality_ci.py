"""Read-only. Is the capped-print direction skew real, or a classifier artefact?

imp07 measured OR = 1.34 (p < 1e-4) for is_capped x direction on the frozen
classifier's labels. Before that is reported as a bias in the imputation, three
things have to be separated:

  1. COMPOSITION. Capped prints route to different classification methods, and
     the methods have very different base RECEIVED rates (RATE_VS_MID 21.6%,
     NPV_VS_UPFRONT 30.9%, TICK_RULE 53.1%). A Mantel-Haenszel common odds ratio
     holds method fixed.
  2. THE MID. Two of the three methods reprice against the old Barchart mid,
     measured biased ~0.5bp high with ~7x the dispersion of the Citi minute
     curve -- which is why RATE_VS_MID reads 78% PAID overall. TICK_RULE never
     touches a curve. If the skew is a mid artefact it should live in the curve
     methods and not in TICK_RULE.
  3. POWER. "TICK_RULE shows nothing" is only informative if TICK_RULE could
     have seen something. So: the CI, not the p-value.
"""
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.insert(0, r"C:\Users\chris\clee\ARBS-dd")

import numpy as np
import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._stir_flow_schema_v1 import DIRECTION_TABLE
from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 250)
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


def or_ci(a, b, c, d):
    """Odds ratio with a Woolf 95% interval; +0.5 continuity if any cell is 0."""
    if min(a, b, c, d) == 0:
        a, b, c, d = a + 0.5, b + 0.5, c + 0.5, d + 0.5
    lor = np.log((a * d) / (b * c))
    se = np.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    return np.exp(lor), np.exp(lor - 1.96 * se), np.exp(lor + 1.96 * se)


for flag in ("is_capped", "is_block"):
    print("=" * 96)
    print(f"{flag} x direction: odds of a RECEIVED label, flag vs not")
    print("=" * 96)
    rows = []
    for meth in ["ALL"] + sorted(pair["method"].dropna().unique()):
        g = pair if meth == "ALL" else pair[pair["method"] == meth]
        a, b, c, d = cells(g, flag)
        o, lo, hi = or_ci(a, b, c, d)
        rows.append({"method": meth, "n_flag": int(a + b), "n_other": int(c + d),
                     "recv%_flag": 100 * a / (a + b) if a + b else np.nan,
                     "recv%_other": 100 * c / (c + d) if c + d else np.nan,
                     "OR": o, "lo95": lo, "hi95": hi,
                     "curve_free": meth == "TICK_RULE"})
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    # Mantel-Haenszel common OR, holding classification method fixed
    num = den = 0.0
    for meth, g in pair.groupby("method"):
        a, b, c, d = cells(g, flag)
        n = a + b + c + d
        if n == 0 or min(a + b, c + d) == 0:
            continue
        num += a * d / n
        den += b * c / n
    print(f"\nMantel-Haenszel common OR (method held fixed): {num / den:.3f}")

    # what the composition alone would produce
    mix = (pair.groupby([flag, "method"])["n"].sum()
           / pair.groupby(flag)["n"].sum()).unstack()
    base = (pair[pair["dealer_direction"] == "RECEIVED"].groupby("method")["n"].sum()
            / pair.groupby("method")["n"].sum())
    print("method mix by flag (rows sum to 1) and each method's base RECEIVED rate:")
    print(pd.concat([mix, base.rename("base_recv").to_frame().T]).to_string(
        float_format=lambda v: f"{v:.3f}"))
    predicted = {k: float((mix.loc[k] * base).sum()) for k in (False, True)}
    print(f"RECEIVED share predicted by method mix alone: "
          f"flag={predicted[True]:.4f}  other={predicted[False]:.4f}")
    a, b, c, d = cells(pair, flag)
    print(f"RECEIVED share actually observed            : "
          f"flag={a / (a + b):.4f}  other={c / (c + d):.4f}\n")
