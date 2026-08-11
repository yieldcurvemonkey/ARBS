"""Part B step 4: the reported tables.

  * notional distribution per tenor band, capped vs sub-cap
  * the per-band imputation at the chosen threshold (u = C/4)
  * what ELSE the cap censors besides `notional`
  * incidental: fixed_rate values that cannot be rates
"""
from __future__ import annotations

import json
import os
import sys
import warnings

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
import psycopg2

OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, OUT)
sys.path.insert(0, os.path.dirname(OUT))

from partB_sensitivity import load_freq, prep, run  # noqa: E402

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE  # noqa: E402
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url  # noqa: E402

pd.set_option("display.width", 330)
pd.set_option("display.max_rows", 600)
pd.set_option("display.max_columns", 60)
pd.set_option("display.float_format", lambda v: f"{v:,.4g}")

conn = psycopg2.connect(resolve_pg_url())


def q(sql):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_sql(sql, conn)


def show(t, d):
    print(f"\n===== {t} =====")
    print(d.to_string(index=False))


with open(os.path.join(OUT, "partB_cap_schedule.json")) as fh:
    sched = json.load(fh)
SWITCH, BANDS = sched["switch_date"], sched["bands"]
whens = []
for b in BANDS:
    vc = (f"as_of_date <  DATE '{SWITCH}'" if b["vintage"] == "V1"
          else f"as_of_date >= DATE '{SWITCH}'")
    whens.append(f"WHEN {vc} AND tenor_years >= {b['lo']} AND tenor_years < {b['hi']} "
                 f"THEN '{b['vintage']} {b['lo']:>5}-{b['hi']:<5} cap={b['cap']/1e6:.0f}mm'")
CELL = "CASE\n  " + "\n  ".join(whens) + "\n  ELSE NULL END"
FLOW = "economic_class='ECONOMIC_FLOW' AND contributes_to_flow"

# --------------------------------------------------------------- distributions
show("P1. notional distribution per band, sub-cap vs capped", q(f"""
SELECT {CELL} AS band, is_capped, count(*) n,
  percentile_cont(0.10) WITHIN GROUP (ORDER BY notional) p10,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY notional) p50,
  percentile_cont(0.90) WITHIN GROUP (ORDER BY notional) p90,
  percentile_cont(0.99) WITHIN GROUP (ORDER BY notional) p99,
  max(notional) mx, avg(notional) mean_n, sum(notional) sum_n
FROM {LEGS_TABLE}
WHERE {FLOW} AND tenor_years>0 AND notional>0 AND notional<1e11
GROUP BY 1,2 ORDER BY 1,2
"""))

show("P2. do any SUB-CAP prints exceed the band cap? (cap enforcement check)", q(f"""
WITH x AS (
  SELECT {CELL} AS band, is_capped, notional,
         CASE {' '.join(
             (f"WHEN as_of_date <  DATE '{SWITCH}' AND tenor_years >= {b['lo']} AND tenor_years < {b['hi']} THEN {b['cap']}"
              if b['vintage']=='V1' else
              f"WHEN as_of_date >= DATE '{SWITCH}' AND tenor_years >= {b['lo']} AND tenor_years < {b['hi']} THEN {b['cap']}")
             for b in BANDS)} END AS cap
  FROM {LEGS_TABLE}
  WHERE {FLOW} AND tenor_years>0 AND notional>0 AND notional<1e11)
SELECT band, count(*) n_all,
       count(*) FILTER (WHERE NOT is_capped AND notional > cap)  n_uncapped_above_cap,
       count(*) FILTER (WHERE is_capped AND notional <> cap)     n_capped_off_cap,
       max(notional) FILTER (WHERE NOT is_capped)                max_uncapped
FROM x WHERE band IS NOT NULL GROUP BY 1 ORDER BY 1
"""))

# ------------------------------------------------- what else does the cap hit?
show("E1. cap vs OTHER fields: is anything besides notional censored?", q(f"""
SELECT is_capped, count(*) n,
  count(*) FILTER (WHERE fixed_rate IS NULL)               n_rate_null,
  count(*) FILTER (WHERE other_payment_amount IS NOT NULL) n_opa,
  count(*) FILTER (WHERE is_block)                         n_block,
  count(*) FILTER (WHERE cap_band_violation)               n_capband,
  count(*) FILTER (WHERE notional_source IS NOT NULL)      n_notsrc,
  count(*) FILTER (WHERE upi_notional_schedule <> 'Constant') n_nonconst_sched,
  count(*) FILTER (WHERE schedule_truncated)               n_sched_trunc,
  count(*) FILTER (WHERE is_off_market)                    n_offmkt,
  count(*) FILTER (WHERE package_transaction_spread IS NOT NULL) n_pkg_spread
FROM {LEGS_TABLE} WHERE {FLOW} GROUP BY 1 ORDER BY 1
"""))

ANN = "((1-exp(-0.04*(coalesce(forward_start_years,0)+tenor_years)))/0.04 " \
      "- (1-exp(-0.04*coalesce(forward_start_years,0)))/0.04)"
show("E2. is `risk` computed FROM the capped notional (=> also right-censored)?", q(f"""
SELECT is_capped, count(*) n,
  percentile_cont(0.05) WITHIN GROUP (ORDER BY abs(risk)/(notional*{ANN}*1e-4)) p05,
  percentile_cont(0.50) WITHIN GROUP (ORDER BY abs(risk)/(notional*{ANN}*1e-4)) p50,
  percentile_cont(0.95) WITHIN GROUP (ORDER BY abs(risk)/(notional*{ANN}*1e-4)) p95,
  sum(abs(risk)) sum_risk
FROM {LEGS_TABLE}
WHERE {FLOW} AND notional>0 AND notional<1e11 AND risk IS NOT NULL AND risk<>0
  AND tenor_years>0 GROUP BY 1
"""))

show("E3. block vs cap: are capped prints also blocks?", q(f"""
SELECT is_capped, is_block, count(*) n FROM {LEGS_TABLE} WHERE {FLOW}
GROUP BY 1,2 ORDER BY 3 DESC
"""))

show("E4. capped share by execution session / venue (is censoring selective?)", q(f"""
SELECT venue, count(*) n, count(*) FILTER (WHERE is_capped) n_cap,
       (count(*) FILTER (WHERE is_capped))::float/count(*) share
FROM {LEGS_TABLE} WHERE {FLOW} GROUP BY 1 ORDER BY 2 DESC LIMIT 10
"""))

# ------------------------------------------------------ incidental: fixed_rate
show("Z1. INCIDENTAL: fixed_rate values that cannot be rates (|rate| >= 1.0 = 100%)", q(f"""
SELECT count(*) n_flow,
  count(*) FILTER (WHERE abs(fixed_rate) >= 1.0)  n_ge_100pct,
  count(*) FILTER (WHERE abs(fixed_rate) >= 0.30) n_ge_30pct,
  count(*) FILTER (WHERE fixed_rate IS NULL)      n_null,
  count(*) FILTER (WHERE fixed_rate < 0)          n_neg
FROM {LEGS_TABLE} WHERE {FLOW}
"""))

show("Z2. INCIDENTAL: those rows' platforms and whether the tape already flags them", q(f"""
SELECT platform_identifier, is_off_market, off_market_reason, count(*) n,
       min(fixed_rate) lo, max(fixed_rate) hi, count(distinct as_of_date) days
FROM {LEGS_TABLE} WHERE {FLOW} AND abs(fixed_rate) >= 1.0
GROUP BY 1,2,3 ORDER BY 4 DESC LIMIT 15
"""))

conn.close()

# ---------------------------------------------- final imputation at u = C/4
print("\n\n" + "=" * 118)
print("FINAL IMPUTATION TABLE  (lognormal, censored MLE, u = C/4)")
print("=" * 118)
freq = prep(load_freq())
d = run(freq, ("div", 4.0))
d["imp_share_notional"] = d["exc_notional_ln"] / (d["tot_notional"] + d["exc_notional_ln"])
d["imp_share_dv01"] = d["exc_dv01_ln"] / (d["tot_dv01"] + d["exc_dv01_ln"])
d["cap_share"] = d["n_cap"] / d.groupby(level=0)["n_cap"].transform("sum") * 0  # placeholder
cols = ["vintage", "lo", "hi", "cap", "u", "n_sub", "n_cap", "par_alpha_cens",
        "ln_mu_cens", "ln_sigma_cens", "ln_mult", "E_above_ln_cens",
        "ncap_err_ln", "ks_lognorm", "tot_notional", "exc_notional_ln",
        "imp_share_notional", "tot_dv01", "exc_dv01_ln", "imp_share_dv01"]
print(d[cols].to_string(index=False))
tn, te = d["tot_notional"].sum(), d["exc_notional_ln"].sum()
td, ted = d["tot_dv01"].sum(), d["exc_dv01_ln"].sum()
print(f"\nOVERALL notional : observed {tn:,.5g}  imputed excess {te:,.5g}  "
      f"=> {te/(tn+te):.3%} imputed")
print(f"OVERALL dv01proxy: observed {td:,.5g}  imputed excess {ted:,.5g}  "
      f"=> {ted/(td+ted):.3%} imputed")

# collapse to the four coarse Part-43 tenor buckets the brief asked for
def coarse(lo):
    if lo < 2.0:
        return "1. <=2y"
    if lo < 10.0:
        return "2. 2-10y"
    if lo < 30.0:
        return "3. 10-30y"
    return "4. >30y"


d["coarse"] = d["lo"].map(coarse)
agg = d.groupby("coarse").agg(
    n_cap=("n_cap", "sum"), tot_notional=("tot_notional", "sum"),
    exc_notional=("exc_notional_ln", "sum"), tot_dv01=("tot_dv01", "sum"),
    exc_dv01=("exc_dv01_ln", "sum"), caps=("cap", lambda s: sorted(set(s))))
agg["imp_share_notional"] = agg["exc_notional"] / (agg["tot_notional"] + agg["exc_notional"])
agg["imp_share_dv01"] = agg["exc_dv01"] / (agg["tot_dv01"] + agg["exc_dv01"])
print("\n----- collapsed to the four coarse Part 43 tenor buckets -----")
print(agg.to_string())
d.to_csv(os.path.join(OUT, "partB_final_imputation_Cdiv4.csv"), index=False)
print(f"\nwrote {os.path.join(OUT, 'partB_final_imputation_Cdiv4.csv')}")
