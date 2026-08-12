"""HARNESS CHECK -- before any of the other probes are trusted.

Reprice a set of already-classified OUTRIGHT prints through
``SessionBranchPricer.price_leg`` using the leg's OWN effective/expiration
dates at the unit's OWN ``curve_timestamp``, and compare against

    implied_mid_pct = fixed_rate * 100 - deviation_bps / 100

which is what ``backfill_dealer_direction.py:524-530`` wrote:
``deviation_bps = structure_price(traded) - structure_price(mid)`` and for an
OUTRIGHT ``structure_price(x) = x_pct * 100``.

If THIS does not reproduce to float noise, the probe harness is wrong (tz,
`_as_request`, midnight) and nothing measured afterwards means anything.

Then, on the SAME instants, reprice with a STANDARDISED spot start
(T+2 business) and the exact tenor maturity, which isolates the *convention*
delta with zero grid-interpolation error.
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
import pathlib
import sys
import time
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
pd.set_option("display.width", 220)
pd.set_option("display.max_rows", 200)

DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-04-01"
TENORS = ("10Y", "5Y", "2Y", "30Y")
NPER = int(os.getenv("MID03_N", "8"))

SQL = f"""
SELECT u.package_id, u.unit_key, u.curve_timestamp, u.pricing_timestamp,
       u.deviation_bps, u.snapshot_policy, u.snapshot_lag_seconds,
       u.curve_name, u.rate_index, u.special_tenor_type,
       l.trade_id, l.tenor_label, l.tenor_years, l.effective_date,
       l.expiration_date, l.notional, l.fixed_rate, l.forward_start_years
FROM arbs_dd_unit_v1 u
JOIN {LEGS_TABLE} l ON l.package_id = u.package_id
WHERE u.as_of_date = %(d)s
  AND u.kind = 'OUTRIGHT' AND u.n_legs = 1
  AND u.rule = 'RATE_VS_MID'
  AND u.exclusion_reason IS NULL
  AND u.deviation_bps IS NOT NULL
  AND u.rate_index = 'SOFR'
  AND u.special_tenor_type = 'STANDARD'
  AND u.snapshot_policy = 'STRICT_1MIN_IN_SESSION'
  AND l.economic_class = 'ECONOMIC_FLOW'
  AND l.tenor_label = ANY(%(t)s)
  AND l.fixed_rate IS NOT NULL
  AND (l.forward_start_years IS NULL OR abs(l.forward_start_years) < 0.02)
ORDER BY l.tenor_label, u.curve_timestamp
"""

conn = psycopg2.connect(resolve_pg_url())
df = pd.read_sql(SQL, conn, params={"d": DAY, "t": list(TENORS)})
conn.close()
print(f"candidates on {DAY}: {len(df)}")
if df.empty:
    raise SystemExit("no candidates -- that is a failed read, not a quiet day")

# one leg per package for an OUTRIGHT; guard rather than assume
dups = df["package_id"].duplicated().sum()
print(f"packages with >1 joined leg: {dups}")
df = df.drop_duplicates("package_id")

# spread the sample across the session rather than taking the head
sample = (df.groupby("tenor_label", group_keys=False)
            .apply(lambda g: g.iloc[np.linspace(0, len(g) - 1, min(NPER, len(g)))
                                    .astype(int)]))
print(f"sample: {len(sample)}")

from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY

pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
print(f"pricer source={pricer.source} governed={pricer.snapshot_governed} "
      f"curve_for(SOFR)={pricer.curve_for('SOFR')}")

rows = []
t0 = time.perf_counter()
with pricer.day_scope():
    for _, r in sample.iterrows():
        inst = pd.Timestamp(r["curve_timestamp"]).tz_convert(NY)
        traded_pct = float(r["fixed_rate"]) * 100.0
        implied_mid = traded_pct - float(r["deviation_bps"]) / 100.0
        try:
            lp = pricer.price_leg(r["curve_name"], inst,
                                  r["effective_date"], r["expiration_date"],
                                  float(r["notional"]), fixed_rate=None)
            mid = lp.mid_pct
            pv01 = lp.pv01
            err = None
        except Exception as exc:
            mid = pv01 = np.nan
            err = f"{type(exc).__name__}: {str(exc)[:90]}"
        rows.append({
            "tenor": r["tenor_label"], "instant": inst,
            "eff": r["effective_date"], "mat": r["expiration_date"],
            "traded_pct": traded_pct, "implied_mid": implied_mid,
            "repriced": mid, "pv01": pv01,
            "diff_bp": (mid - implied_mid) * 100.0 if mid == mid else np.nan,
            "err": err,
        })
    n_handles = pricer.n_handles
el = time.perf_counter() - t0

out = pd.DataFrame(rows)
print(f"\nrepriced {len(out)} legs in {el:.1f}s, {n_handles} curve handles built")
print(out[["tenor", "instant", "eff", "mat", "traded_pct", "implied_mid",
           "repriced", "diff_bp", "err"]].to_string())

ok = out["diff_bp"].dropna()
print("\n=== HARNESS: |repriced - implied_mid| in bp")
print(f"  n={len(ok)}  errors={out['err'].notna().sum()}")
if len(ok):
    print(f"  max|diff| = {ok.abs().max():.3e} bp    median = {ok.median():.3e} bp")
    print(f"  p99|diff| = {ok.abs().quantile(0.99):.3e} bp")
    if ok.abs().max() > 1e-6:
        print("  *** HARNESS MISMATCH -- do not trust anything downstream ***")
    else:
        print("  HARNESS OK (float noise)")
