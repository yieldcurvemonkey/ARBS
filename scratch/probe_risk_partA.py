"""Part A: characterise the corrupt `risk` column on the v3 tape.

Finding driving the design (from scratch/probe_risk_orient*.py): the defect is
NOT in `risk`.  `risk` is internally consistent with `notional`; it is
`notional` that carries a 1e20 sentinel.  So the ratio bound suggested in the
brief flags none of them, and the predicate has to test magnitude too.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import pandas as pd
import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

pd.set_option("display.width", 300)
pd.set_option("display.max_rows", 500)
pd.set_option("display.max_columns", 60)
pd.set_option("display.float_format", lambda v: f"{v:,.6g}")

OUT = os.path.dirname(os.path.abspath(__file__))
conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def show(title, df):
    print(f"\n===== {title} =====")
    print(df.to_string())


FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"

# ---------------------------------------------------------------- tie-out
show("A0. headline tie-out: sum(abs(risk)) with / without the 1e20 rows", q(f"""
SELECT rate_index_clean,
       count(*) n,
       sum(abs(risk))                                    dv01_all,
       sum(abs(risk)) FILTER (WHERE notional < 1e11)     dv01_ex_sentinel,
       count(*)       FILTER (WHERE notional >= 1e11)    n_sentinel,
       sum(abs(risk)) FILTER (WHERE notional >= 1e11)    dv01_sentinel
FROM {LEGS_TABLE} WHERE {FLOW}
GROUP BY 1 ORDER BY 3 DESC
"""))

show("A0b. same split by platform_identifier (top 12 by dv01_all)", q(f"""
SELECT platform_identifier,
       count(*) n,
       sum(abs(risk))                                 dv01_all,
       sum(abs(risk)) FILTER (WHERE notional < 1e11)  dv01_ex_sentinel,
       count(*)       FILTER (WHERE notional >= 1e11) n_sentinel
FROM {LEGS_TABLE} WHERE {FLOW}
GROUP BY 1 ORDER BY 3 DESC LIMIT 12
"""))

# ------------------------------------------------- is 1e10..1e11 legitimate?
show("A1. notional between 1e10 and 1e11 (flow): capped? which tenors?", q(f"""
SELECT is_capped, rate_index_clean, count(*) n,
       min(notional) lo_n, max(notional) hi_n,
       min(tenor_years) lo_t, max(tenor_years) hi_t,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY (abs(risk)/notional)/(tenor_years*1e-4)) med_r
FROM {LEGS_TABLE} WHERE {FLOW} AND notional >= 1e10 AND notional < 1e11
GROUP BY 1,2 ORDER BY 3 DESC
"""))

show("A1b. uncapped rows above 1e10: distinct notionals", q(f"""
SELECT notional, count(*) n, min(tenor_years) lo_t, max(tenor_years) hi_t
FROM {LEGS_TABLE} WHERE {FLOW} AND notional >= 1e10 AND notional < 1e11 AND NOT is_capped
GROUP BY 1 ORDER BY 2 DESC LIMIT 20
"""))

# ------------------------------------------------------- the low-ratio tail
show("L1. scaled ratio r bands", q(f"""
WITH x AS (SELECT (abs(risk)/notional)/(tenor_years*1e-4) r, tenor_years, notional
           FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0)
SELECT CASE WHEN r = 0 THEN 'a. r=0'
            WHEN r < 0.25 THEN 'b. 0<r<0.25'
            WHEN r < 0.5  THEN 'c. 0.25-0.5'
            WHEN r < 2.0  THEN 'd. 0.5-2 (sane band)'
            WHEN r < 5.0  THEN 'e. 2-5'
            ELSE 'f. >=5' END band, count(*) n,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY tenor_years) med_tenor,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional
FROM x GROUP BY 1 ORDER BY 1
"""))

show("L2. r<0.5 / r=0 / r>2 by tenor band", q(f"""
WITH x AS (SELECT (abs(risk)/notional)/(tenor_years*1e-4) r, tenor_years
           FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0)
SELECT CASE WHEN tenor_years<0.5 THEN '1. <6m' WHEN tenor_years<1 THEN '2. 6m-1y'
            WHEN tenor_years<5 THEN '3. 1-5y' WHEN tenor_years<15 THEN '4. 5-15y'
            ELSE '5. >15y' END tb,
       count(*) n,
       count(*) FILTER (WHERE r=0) n_zero,
       count(*) FILTER (WHERE r>0 AND r<0.5) n_lo,
       count(*) FILTER (WHERE r>2) n_hi,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r) med_r
FROM x GROUP BY 1 ORDER BY 1
"""))

show("L3. upi_notional_schedule vs r", q(f"""
WITH x AS (SELECT (abs(risk)/notional)/(tenor_years*1e-4) r, upi_notional_schedule
           FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0)
SELECT upi_notional_schedule, count(*) n,
       percentile_cont(0.05) WITHIN GROUP (ORDER BY r) p05,
       percentile_cont(0.5)  WITHIN GROUP (ORDER BY r) p50,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY r) p95,
       count(*) FILTER (WHERE r < 0.5) n_lo
FROM x GROUP BY 1 ORDER BY 2 DESC LIMIT 15
"""))

show("L3b. forward_start_years vs r (r<0.5 attribution)", q(f"""
WITH x AS (SELECT (abs(risk)/notional)/(tenor_years*1e-4) r,
                  coalesce(forward_start_years,0) fs, is_off_market, is_non_standard_term,
                  schedule_truncated
           FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0)
SELECT (fs > 0.02) is_fwd, is_off_market, is_non_standard_term, count(*) n,
       count(*) FILTER (WHERE r>0 AND r<0.5) n_lo,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY r) med_r
FROM x GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 20
"""))

show("L4. the r>1.6 rows", q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, fixed_rate, risk, platform_identifier,
       trade_type, rate_index_clean, coalesce(forward_start_years,0) fs,
       (abs(risk)/notional)/(tenor_years*1e-4) r
FROM {LEGS_TABLE} WHERE {FLOW} AND notional>0 AND risk IS NOT NULL AND tenor_years>0
  AND (abs(risk)/notional)/(tenor_years*1e-4) > 1.6
ORDER BY 11 DESC LIMIT 25
"""))

# ------------------------------------------------------- the 55 bad rows
bad = q(f"""
SELECT trade_id, as_of_date, notional, tenor_years, fixed_rate, risk,
       platform_identifier, trade_type, rate_index_clean, venue, is_capped, is_block,
       is_off_market, off_market_reason, quality_flags::text quality_flags,
       economic_class, lifecycle_type, execution_timestamp
FROM {LEGS_TABLE} WHERE notional >= 1e11 ORDER BY abs(risk) DESC
""")
show("A2. ALL sentinel rows (notional >= 1e11)", bad)
bad.to_csv(os.path.join(OUT, "risk_sentinel_rows.csv"), index=False)

by_date = q(f"""
SELECT as_of_date, count(*) n, sum(abs(risk)) dv01
FROM {LEGS_TABLE} WHERE notional >= 1e11 GROUP BY 1 ORDER BY 1
""")
show("A3. sentinel rows by as_of_date", by_date)
by_date.to_csv(os.path.join(OUT, "risk_sentinel_by_date.csv"), index=False)

show("A4. daily flow-leg count on those days, for base rate", q(f"""
SELECT as_of_date, count(*) n_flow
FROM {LEGS_TABLE} WHERE {FLOW} AND as_of_date IN (
    SELECT DISTINCT as_of_date FROM {LEGS_TABLE} WHERE notional >= 1e11)
GROUP BY 1 ORDER BY 1
"""))

# BILT baseline: is 1e20 a BILT-wide problem or a handful?
show("A5. BILT FED_FUNDS baseline: notional & fixed_rate distribution", q(f"""
SELECT count(*) n,
       count(*) FILTER (WHERE notional >= 1e11) n_sentinel,
       count(*) FILTER (WHERE fixed_rate = 9.9) n_rate99,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY notional) med_notional,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY fixed_rate) med_rate,
       min(as_of_date) lo, max(as_of_date) hi
FROM {LEGS_TABLE} WHERE {FLOW} AND platform_identifier='BILT' AND rate_index_clean='FED_FUNDS'
"""))

# plot
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    d = by_date.copy()
    d["as_of_date"] = pd.to_datetime(d["as_of_date"])
    fig, ax = plt.subplots(figsize=(11, 3.6))
    ax.bar(d["as_of_date"], d["n"], width=3.0, color="#c0392b")
    ax.set_title("v3 tape: legs with notional = 1e20 sentinel, by as_of_date "
                 f"(n={int(d['n'].sum())} over {len(d)} days)")
    ax.set_ylabel("rows")
    ax.grid(axis="y", alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    p = os.path.join(OUT, "risk_sentinel_by_date.png")
    fig.savefig(p, dpi=130)
    print(f"\n[plot] {p}")
except Exception as e:  # pragma: no cover
    print(f"\n[plot FAILED] {type(e).__name__}: {e}")

conn.close()
