"""Measurements the universe filters have to be built on. Read-only, prod."""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE, PACKAGES_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 200)
pd.set_option("display.max_columns", 40)

conn = psycopg2.connect(resolve_pg_url())


def q(sql, **params):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn, params=params or None)


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"


def head(t):
    print()
    print("=" * 78)
    print(t)
    print("=" * 78)


# --- M1. are the lifecycle/novation/exercise booleans populated at all? -----
head("M1. is_* lifecycle booleans -- TRUE / FALSE / NULL counts, ALL rows")
cols = [
    "is_new_risk", "is_unwind", "is_compression", "is_compression_spec",
    "is_reset_optimization", "is_novation", "is_novation_born",
    "is_novation_terminated", "is_exercise_born", "is_clearing_termination",
    "is_mac", "is_spreadover", "is_asset_swap", "is_non_standard_term",
    "is_off_market", "is_off_date",
]
sel = ", ".join(
    f"count(*) FILTER (WHERE {c}) AS {c}_t, "
    f"count(*) FILTER (WHERE {c} IS NULL) AS {c}_n"
    for c in cols
)
r = q(f"SELECT count(*) AS total, {sel} FROM {LEGS_TABLE}").iloc[0]
print(f"  total rows: {int(r['total']):,}")
for c in cols:
    print(f"  {c:26s} TRUE {int(r[c + '_t']):>9,}   NULL {int(r[c + '_n']):>9,}")

# --- M2. trade_type x contributes_to_flow -----------------------------------
head("M2. trade_type over ECONOMIC_FLOW legs (+ MAC/IMM/special_tenor_type)")
print(q(f"""
    SELECT trade_type, count(*) n,
           count(*) FILTER (WHERE is_mac) n_mac,
           count(*) FILTER (WHERE fixed_rate IS NULL) n_no_rate,
           count(*) FILTER (WHERE coalesce(other_payment_ufro,0)<>0) n_ufro,
           round(sum(abs(risk)) FILTER (WHERE abs(notional) < 1e11)) risk_sane
    FROM {LEGS_TABLE} WHERE {FLOW}
    GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

head("M2b. special_tenor_type over flow legs")
print(q(f"""
    SELECT coalesce(special_tenor_type,'(null)') stt, count(*) n
    FROM {LEGS_TABLE} WHERE {FLOW} GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

# --- M3. platform mix, with venue column + cleared, for XXXX / XOFF ---------
head("M3. platform_identifier over flow legs, with the tape's own venue col")
print(q(f"""
    SELECT coalesce(platform_identifier,'(null)') pid,
           count(*) n,
           count(DISTINCT venue) n_venue,
           string_agg(DISTINCT venue, '/') venues,
           string_agg(DISTINCT cleared, '/') cleared,
           round(100.0*count(*) FILTER (WHERE is_block)/count(*), 2) pct_block,
           round(avg(notional) FILTER (WHERE abs(notional)<1e11)) avg_notional
    FROM {LEGS_TABLE} WHERE {FLOW}
    GROUP BY 1 HAVING count(*) > 300 ORDER BY 2 DESC
""").to_string(index=False))

# --- M4. other payment components -------------------------------------------
head("M4. other-payment components: populated counts by lifecycle_type")
print(q(f"""
    SELECT lifecycle_type, economic_class, count(*) n,
      count(*) FILTER (WHERE coalesce(other_payment_ufro,0)<>0) ufro,
      count(*) FILTER (WHERE coalesce(other_payment_uwin,0)<>0) uwin,
      count(*) FILTER (WHERE coalesce(other_payment_pexh,0)<>0) pexh,
      count(*) FILTER (WHERE coalesce(other_payment_amount,0)<>0) amt,
      count(*) FILTER (WHERE
          coalesce(other_payment_ufro,0)<>0 AND coalesce(other_payment_uwin,0)<>0) both_uf_uw
    FROM {LEGS_TABLE} WHERE contributes_to_flow
    GROUP BY 1,2 ORDER BY 3 DESC
""").to_string(index=False))

head("M4b. does ufro+uwin+pexh reconcile to other_payment_amount?")
print(q(f"""
    SELECT count(*) n_amt_nonzero,
      count(*) FILTER (WHERE abs(coalesce(other_payment_ufro,0)
                              + coalesce(other_payment_uwin,0)
                              + coalesce(other_payment_pexh,0)
                              - other_payment_amount) < 0.01) n_reconciles
    FROM {LEGS_TABLE}
    WHERE contributes_to_flow AND coalesce(other_payment_amount,0) <> 0
""").to_string(index=False))

# --- M5. maturity spread now the cutoff is gone -----------------------------
head("M5. flow legs by tenor band, and the 1105d cutoff")
print(q(f"""
    SELECT CASE
      WHEN tenor_years < 1 THEN 'a <1y'
      WHEN tenor_years < 2 THEN 'b 1-2y'
      WHEN tenor_years < 5 THEN 'c 2-5y'
      WHEN tenor_years < 10 THEN 'd 5-10y'
      WHEN tenor_years < 30 THEN 'e 10-30y'
      ELSE 'f 30y+' END band,
      count(*) n,
      count(*) FILTER (WHERE expiration_date > as_of_date + 1105) beyond_cutoff
    FROM {LEGS_TABLE} WHERE {FLOW} GROUP BY 1 ORDER BY 1
""").to_string(index=False))

# --- M6. package structure / leg-count mix ----------------------------------
head("M6. n_package_legs distribution over flow legs")
print(q(f"""
    SELECT coalesce(p.n_package_legs, 1) n_legs, count(*) n_legs_rows,
           count(DISTINCT coalesce(l.package_id, l.trade_id)) n_units
    FROM {LEGS_TABLE} l LEFT JOIN {PACKAGES_TABLE} p USING (package_id)
    WHERE l.economic_class='ECONOMIC_FLOW' AND l.contributes_to_flow
    GROUP BY 1 ORDER BY 1
""").to_string(index=False))

conn.close()
print("\ndone")
