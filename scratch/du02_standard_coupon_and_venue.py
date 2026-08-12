"""Settle three filter questions with measurement, not argument.

1. Is MAC off-market by construction?  Is IMM?
2. What are XXXX / XOFF -- do they look like the D2C or the D2D population?
3. Are the exercise / novation booleans usable at all?
"""
from __future__ import annotations

import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 240)
pd.set_option("display.max_rows", 300)
pd.set_option("display.max_columns", 40)

conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"


def head(t):
    print()
    print("=" * 92)
    print(t)
    print("=" * 92)


# --- S1. the standard-coupon signature -------------------------------------
# A standard coupon is struck on a coarse grid (MAC = round quarter-percent)
# and therefore essentially ALWAYS needs an upfront. A market-rate trade is
# struck on a free grid and needs one only when it is genuinely seasoned.
head("S1. standard-coupon signature by family (flow legs, sane notional/rate)")
print(q(f"""
WITH b AS (
  SELECT
    CASE
      WHEN is_mac THEN 'MAC (is_mac)'
      WHEN trade_type = 'IMM' THEN 'trade_type=IMM'
      WHEN special_tenor_type = 'IMM' THEN 'stt=IMM (not tt=IMM)'
      WHEN trade_type = 'OUTRIGHT' THEN 'OUTRIGHT (baseline)'
      WHEN trade_type IN ('CURVE','FLY') THEN 'CURVE/FLY (baseline)'
      WHEN trade_type LIKE 'SPREADOVER%' THEN 'SPREADOVER*'
      WHEN trade_type LIKE 'MATCHED%' THEN 'MATCHED_MATURITY*'
      WHEN trade_type LIKE 'INVOICE%' THEN 'INVOICE*'
      ELSE 'other' END fam,
    fixed_rate, other_payment_ufro, other_payment_amount, is_off_market,
    notional, tenor_years
  FROM {LEGS_TABLE}
  WHERE {FLOW} AND fixed_rate IS NOT NULL
    AND abs(fixed_rate) < 1.0 AND notional < 1e11
)
SELECT fam, count(*) n,
  round(100.0*count(*) FILTER (
      WHERE mod((round(fixed_rate*1e8))::bigint, 25000000::bigint) = 0)
    / count(*), 2) pct_on_25bp_grid,
  round(100.0*count(*) FILTER (
      WHERE mod((round(fixed_rate*1e8))::bigint, 1000000::bigint) = 0)
    / count(*), 2) pct_on_1bp_grid,
  round(100.0*count(*) FILTER (WHERE coalesce(other_payment_amount,0) <> 0)
    / count(*), 2) pct_with_upfront,
  round(100.0*count(*) FILTER (WHERE is_off_market) / count(*), 2) pct_off_market,
  round(min(fixed_rate)::numeric, 6) rate_min,
  round(max(fixed_rate)::numeric, 6) rate_max
FROM b GROUP BY 1 ORDER BY 2 DESC
""").to_string(index=False))

head("S1b. the ten most common MAC fixed rates, and the ten most common IMM ones")
for fam, where in (("MAC", "is_mac"), ("IMM", "trade_type='IMM'"),
                   ("OUTRIGHT", "trade_type='OUTRIGHT'")):
    d = q(f"""
        SELECT round(fixed_rate::numeric, 6) rate, count(*) n
        FROM {LEGS_TABLE}
        WHERE {FLOW} AND {where} AND fixed_rate IS NOT NULL AND abs(fixed_rate) < 1.0
        GROUP BY 1 ORDER BY 2 DESC LIMIT 10
    """)
    tot = int(d["n"].sum())
    print(f"  {fam:9s} top-10 modal rates cover {tot:,} legs: "
          + ", ".join(f"{r.rate:.5f}x{r.n}" for r in d.itertuples()))

# --- S2. what XXXX / XOFF look like next to known D2C and known D2D --------
head("S2. platform fingerprint -- known D2C vs known D2D vs the undecided")
print(q(f"""
SELECT
  CASE
    WHEN platform_identifier IN ('TWSF','BBSF','BILT') THEN 'A known-D2C'
    WHEN platform_identifier IN ('BGCD','DWSF','IGDL','ISWV','TPSE','TSEF')
      THEN 'B known-D2D'
    ELSE 'C ' || coalesce(platform_identifier,'(null)') END grp,
  count(*) n,
  round(100.0*count(*) FILTER (WHERE cleared='Y')/count(*), 1) pct_cleared_Y,
  round(100.0*count(*) FILTER (WHERE cleared='I')/count(*), 1) pct_cleared_I,
  round(100.0*count(*) FILTER (WHERE is_capped)/count(*), 2) pct_capped,
  round(100.0*count(*) FILTER (WHERE is_block)/count(*), 2) pct_block,
  round(100.0*count(*) FILTER (WHERE trade_type='OUTRIGHT')/count(*), 1) pct_outright,
  round(100.0*count(*) FILTER (WHERE trade_type LIKE 'SPREADOVER%%'
                                  OR trade_type LIKE 'INVOICE%%'
                                  OR trade_type LIKE 'MATCHED%%')/count(*), 1) pct_asw,
  round(100.0*count(*) FILTER (WHERE trade_type IN ('CURVE','FLY'))/count(*), 1) pct_curve_fly,
  round(100.0*count(*) FILTER (WHERE coalesce(other_payment_amount,0)<>0)/count(*), 1) pct_upfront,
  round(100.0*count(*) FILTER (WHERE rate_index_clean='FED_FUNDS')/count(*), 1) pct_ff,
  round(median(1)::numeric,0) dummy
FROM {LEGS_TABLE} WHERE {FLOW}
GROUP BY 1 HAVING count(*) > 2000 ORDER BY 1, 2 DESC
""".replace("round(median(1)::numeric,0) dummy", "0 dummy")).to_string(index=False))

# --- S3. exercise / novation: are the columns usable? -----------------------
head("S3. exercise / novation flags -- distinct values over the whole tape")
for c in ("is_exercise_born", "is_novation", "is_novation_born",
          "is_novation_terminated", "is_compression", "is_clearing_termination"):
    d = q(f"SELECT coalesce({c}::text,'(null)') v, count(*) n "
          f"FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC")
    print(f"  {c:26s} " + " · ".join(f"{r.v}={r.n:,}" for r in d.itertuples()))

head("S3b. anything else that could name an exercise or a novation?")
print(q(f"""
    SELECT coalesce(lc_status,'(null)') lc_status,
           coalesce(economic_class_reason,'(null)') reason, count(*) n
    FROM {LEGS_TABLE} GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15
""").to_string(index=False))
print()
print(q(f"""
    SELECT coalesce(tape_tags,'(null)') tape_tags, count(*) n
    FROM {LEGS_TABLE} GROUP BY 1 ORDER BY 2 DESC LIMIT 15
""").to_string(index=False))

conn.close()
print("\ndone")
