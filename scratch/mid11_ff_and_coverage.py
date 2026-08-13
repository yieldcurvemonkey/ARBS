"""GAP 1+3 -- the FED_FUNDS harness check, and cumulative tenor coverage.

mid03 validated the probe against SOFR only. FED_FUNDS is a different curve
definition served by a different store partition set; a convention fault there
is invisible to a SOFR check, so it gets its own known-answer run.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
os.environ["ARBS_RL_OMIT_UNUSED_FIXINGS"] = "1"

import pathlib
import sys
import warnings

REPO = str(pathlib.Path(__file__).resolve().parents[1])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import numpy as np
import pandas as pd
import psycopg2

from SDRUtils._swappulse_scripts._tape_tables import LEGS_TABLE
from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url

warnings.simplefilter("ignore")
pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)

conn = psycopg2.connect(resolve_pg_url())

# ------------------------------------------------------------- FF harness
SQL = f"""
SELECT u.package_id, u.curve_timestamp, u.deviation_bps, u.curve_name,
       u.snapshot_policy, u.special_tenor_type,
       l.tenor_label, l.effective_date, l.expiration_date, l.notional,
       l.fixed_rate
FROM arbs_dd_unit_v1 u
JOIN {LEGS_TABLE} l ON l.package_id = u.package_id
WHERE u.as_of_date BETWEEN %(a)s AND %(b)s
  AND u.kind='OUTRIGHT' AND u.n_legs=1 AND u.rule='RATE_VS_MID'
  AND u.exclusion_reason IS NULL AND u.deviation_bps IS NOT NULL
  AND u.rate_index='FED_FUNDS'
  AND l.economic_class='ECONOMIC_FLOW' AND l.fixed_rate IS NOT NULL
ORDER BY u.curve_timestamp
"""
ff = pd.read_sql(SQL, conn, params={"a": "2026-03-30", "b": "2026-04-03"})
ff = ff.drop_duplicates("package_id")
print(f"FED_FUNDS OUTRIGHT RATE_VS_MID prints 2026-03-30..04-03: {len(ff)}")
print(ff["special_tenor_type"].value_counts().to_string())

from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY

pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
n = min(40, len(ff))
sample = ff.iloc[np.linspace(0, len(ff) - 1, n).astype(int)]
rows = []
with pricer.day_scope():
    for _, r in sample.iterrows():
        inst = pd.Timestamp(r["curve_timestamp"]).tz_convert(NY)
        implied = float(r["fixed_rate"]) * 100.0 - float(r["deviation_bps"]) / 100.0
        try:
            lp = pricer.price_leg(r["curve_name"], inst, r["effective_date"],
                                  r["expiration_date"], float(r["notional"]))
            d = (lp.mid_pct - implied) * 100.0
            err = None
        except Exception as exc:
            d, err = np.nan, f"{type(exc).__name__}: {str(exc)[:70]}"
        rows.append({"tenor": r["tenor_label"], "stt": r["special_tenor_type"],
                     "instant": inst, "curve": r["curve_name"],
                     "implied": round(implied, 6), "diff_bp": d, "err": err})
out = pd.DataFrame(rows)
print(out.to_string())
ok = out["diff_bp"].dropna()
print(f"\nFED_FUNDS HARNESS: n={len(ok)} errors={out['err'].notna().sum()}  "
      f"max|diff|={ok.abs().max():.3e} bp  median={ok.median():.3e} bp")
print("  " + ("HARNESS OK (float noise)" if ok.abs().max() < 1e-6
              else "*** MISMATCH ***"))

# ------------------------------------------------------- tenor coverage
print("\n" + "=" * 78)
print("CUMULATIVE TENOR COVERAGE  (2026-01-01..2026-08-07, ECONOMIC_FLOW)")
print("=" * 78)
COV = f"""
SELECT tenor_label, count(*) n,
       sum(abs(risk)) FILTER (WHERE abs(risk) < 1e12) risk_abs
FROM {LEGS_TABLE}
WHERE as_of_date BETWEEN '2026-01-01' AND '2026-08-07'
  AND economic_class='ECONOMIC_FLOW' AND rate_index_clean = %(i)s
  {{extra}}
GROUP BY 1
"""
SETS = {
    "SOFR": ["1W", "2W", "1M", "2M", "3M", "4M", "5M", "6M", "7M", "8M", "9M",
             "10M", "11M", "1Y", "15M", "18M", "21M", "2Y", "3Y", "4Y", "5Y",
             "6Y", "7Y", "8Y", "9Y", "10Y", "11Y", "12Y", "15Y", "20Y", "25Y",
             "30Y", "40Y"],
    "FED_FUNDS": ["1W", "2W", "1M", "2M", "3M", "4M", "5M", "6M", "9M", "1Y",
                  "15M", "18M", "21M", "2Y", "3Y", "4Y", "5Y", "7Y", "10Y"],
}
for idx in ("SOFR", "FED_FUNDS"):
    for label, extra in (("all legs", ""),
                         ("spot+STANDARD",
                          "AND special_tenor_type='STANDARD' AND "
                          "(forward_start_years IS NULL OR "
                          "abs(forward_start_years) < 0.02)")):
        df = pd.read_sql(COV.format(extra=extra), conn, params={"i": idx})
        tot_n, tot_r = df["n"].sum(), df["risk_abs"].sum()
        cand = SETS[idx]
        print(f"\n{idx} / {label}: total {tot_n:,} legs, "
              f"|risk| {tot_r:,.0f}")
        for k in range(4, len(cand) + 1, 2):
            sub = df[df["tenor_label"].isin(cand[:k])]
            print(f"   first {k:2d} of the candidate list: "
                  f"{sub['n'].sum()/tot_n*100:5.1f}% of prints, "
                  f"{sub['risk_abs'].sum()/tot_r*100:5.1f}% of |risk|")
        sub = df[df["tenor_label"].isin(cand)]
        print(f"   FULL candidate set ({len(cand)}): "
              f"{sub['n'].sum()/tot_n*100:5.1f}% of prints, "
              f"{sub['risk_abs'].sum()/tot_r*100:5.1f}% of |risk|")
        # what is left out, biggest first
        left = df[~df["tenor_label"].isin(cand)].nlargest(8, "n")
        print(f"   biggest excluded labels: "
              f"{', '.join(f'{r.tenor_label}({r.n})' for r in left.itertuples())}")
conn.close()
