"""MEASUREMENT 6 -- the known-answer check that decides whether this works.

`arbs_dd_unit_v1.deviation_bps` already carries, per print, the traded structure
price minus the model mid, against THIS curve store, from THIS pricer. For a
single-leg OUTRIGHT under RULE_RATE:

    implied_mid_pct = fixed_rate*100 - deviation_bps/100

So a candidate grid can be scored against every such print on the day. The
error decomposes three ways and they must be reported separately or a
convention fault hides inside a spacing number:

  HARNESS   same instant, same dates          -> must be ~1e-13 bp (mid03)
  CONVENTION same instant, GRID dates vs print's own dates
  SPACING   grid dates AND grid instant, vs the print's instant

Two spot rules are priced side by side:
  A  spot = curve.calendar_advance(curve.reference_date(), "2b")  -- the rule
     `RLIRSwapCurve.build_irswap(fwd="0D")` already uses in this repo
  T  spot = the tape's own modal effective_date for the day
"""
import os
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
os.environ["ARBS_CITIVELO_QUOTES_OFFLINE"] = "1"
os.environ["ARBS_RL_OMIT_UNUSED_FIXINGS"] = "1"

import datetime
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
pd.set_option("display.width", 260)
pd.set_option("display.max_rows", 400)

from SDRUtils.dealer_direction import midprice, snapshot
from SDRUtils.stir_flow.pricing import NY

TENORS = ["3M", "1Y", "2Y", "5Y", "10Y", "30Y"]
DAYS = sys.argv[1:] or ["2026-04-01", "2025-10-15", "2026-06-05"]
SPACINGS = [1, 5, 15, 30, 60]

PRINTS_SQL = f"""
SELECT u.package_id, u.curve_timestamp, u.deviation_bps,
       u.snapshot_policy, u.curve_name,
       l.tenor_label, l.effective_date, l.expiration_date,
       l.notional, l.fixed_rate
FROM arbs_dd_unit_v1 u
JOIN {LEGS_TABLE} l ON l.package_id = u.package_id
WHERE u.as_of_date = %(d)s
  AND u.kind = 'OUTRIGHT' AND u.n_legs = 1 AND u.rule = 'RATE_VS_MID'
  AND u.exclusion_reason IS NULL AND u.deviation_bps IS NOT NULL
  AND u.rate_index = 'SOFR' AND u.special_tenor_type = 'STANDARD'
  AND l.economic_class = 'ECONOMIC_FLOW'
  AND l.tenor_label = ANY(%(t)s)
  AND l.fixed_rate IS NOT NULL
  AND l.effective_date >= (l.execution_timestamp AT TIME ZONE 'America/New_York')::date
  AND (l.forward_start_years IS NULL OR abs(l.forward_start_years) < 0.02)
"""

MODAL_SQL = f"""
SELECT effective_date, count(*) n FROM {LEGS_TABLE}
WHERE as_of_date = %(d)s AND economic_class='ECONOMIC_FLOW'
  AND rate_index_clean='SOFR' AND special_tenor_type='STANDARD'
  AND tenor_label IN ('2Y','5Y','10Y','30Y')
  AND (forward_start_years IS NULL OR abs(forward_start_years) < 0.02)
  AND effective_date >= (execution_timestamp AT TIME ZONE 'America/New_York')::date
GROUP BY 1 ORDER BY n DESC LIMIT 1
"""

pricer = midprice.SessionBranchPricer(source=snapshot.CURVE_SOURCE)
CURVE = pricer.curve_for("SOFR")
conn = psycopg2.connect(resolve_pg_url())

all_rows = []
for DAY in DAYS:
    prints = pd.read_sql(PRINTS_SQL, conn, params={"d": DAY, "t": TENORS})
    modal = pd.read_sql(MODAL_SQL, conn, params={"d": DAY})
    if prints.empty:
        print(f"{DAY}: no prints -- a business day with no prints is a FAILED "
              f"READ, not a quiet market")
        continue
    prints = prints.drop_duplicates("package_id")
    spot_T = pd.Timestamp(modal.iloc[0]["effective_date"]).to_pydatetime()

    # the grid's own day: 01:00..22:59 ET is the store's partition window
    d0 = pd.Timestamp(DAY)
    minutes = pd.date_range(f"{DAY} 01:00", f"{DAY} 22:59", freq="1min",
                            tz=NY)

    pricer.clear()
    # anchor curve for the day's dates
    anchor = None
    for t in minutes:
        try:
            anchor = pricer.mark_curve(CURVE, t)
            break
        except Exception:
            continue
    if anchor is None:
        print(f"{DAY}: no servable minute at all -- failed read")
        continue
    ref = anchor.handle.reference_date()
    spot_A = anchor.handle.calendar_advance(ref, "2b")
    mats_A = {tn: anchor.handle.calendar_advance(spot_A, tn) for tn in TENORS}
    mats_T = {tn: anchor.handle.calendar_advance(spot_T, tn) for tn in TENORS}
    print(f"\n{'='*78}\n{DAY}  ref={ref.date()}  spotA={spot_A.date()}  "
          f"spotT={spot_T.date()} (modal, n={int(modal.iloc[0]['n'])})  "
          f"prints={len(prints)}")

    # ---- build the 1-minute grid
    t0 = time.perf_counter()
    grid = {}
    miss = 0
    for t in minutes:
        try:
            pricer.mark_curve(CURVE, t)
        except Exception:
            miss += 1
            continue
        row = {}
        for tn in TENORS:
            row[("A", tn)] = pricer.price_leg(CURVE, t, spot_A, mats_A[tn],
                                              1_000_000.0).mid_pct
            row[("T", tn)] = pricer.price_leg(CURVE, t, spot_T, mats_T[tn],
                                              1_000_000.0).mid_pct
        grid[t] = row
    el = time.perf_counter() - t0
    gts = pd.DatetimeIndex(sorted(grid))
    print(f"  grid: {len(gts)}/{len(minutes)} minutes served "
          f"({miss} strict misses) in {el:.1f}s  "
          f"= {1000*el/max(len(gts),1):.1f} ms/minute for "
          f"{2*len(TENORS)} legs")
    pricer.clear()

    for _, r in prints.iterrows():
        inst = pd.Timestamp(r["curve_timestamp"]).tz_convert(NY)
        implied = float(r["fixed_rate"]) * 100.0 - float(r["deviation_bps"]) / 100.0
        tn = r["tenor_label"]
        exact_A = (pd.Timestamp(r["effective_date"]) == pd.Timestamp(spot_A)
                   and pd.Timestamp(r["expiration_date"]) == pd.Timestamp(mats_A[tn]))
        exact_T = (pd.Timestamp(r["effective_date"]) == pd.Timestamp(spot_T)
                   and pd.Timestamp(r["expiration_date"]) == pd.Timestamp(mats_T[tn]))
        base = {"day": DAY, "tenor": tn, "instant": inst, "implied": implied,
                "exact_A": exact_A, "exact_T": exact_T}
        for sp in SPACINGS:
            sub = gts[(gts.minute % sp == 0)] if sp > 1 else gts
            if len(sub) == 0:
                continue
            i = int(np.abs((sub - inst).total_seconds().to_numpy()).argmin())
            g = sub[i]
            dt = abs((g - inst).total_seconds())
            base[f"dt_{sp}"] = dt
            base[f"A_{sp}"] = (grid[g][("A", tn)] - implied) * 100.0
            base[f"T_{sp}"] = (grid[g][("T", tn)] - implied) * 100.0
        all_rows.append(base)

conn.close()
df = pd.DataFrame(all_rows)
out = pathlib.Path(REPO) / "scratch" / "_mid09_rows.parquet"
df.to_parquet(out, index=False)
print(f"\nwrote {out}  ({len(df)} print comparisons)")


def dist(s, label):
    s = s.dropna()
    if not len(s):
        return f"  {label:<34} n=0"
    return (f"  {label:<34} n={len(s):>5}  "
            f"med={s.median():+7.3f}  mean={s.mean():+7.3f}  "
            f"sd={s.std():6.3f}  "
            f"p05={s.quantile(.05):+7.3f}  p95={s.quantile(.95):+7.3f}  "
            f"|p50|={s.abs().median():6.3f}  |p95|={s.abs().quantile(.95):6.3f}")


print("\n" + "=" * 78)
print("(grid_mid - implied_mid) in bp   -- SPOT RULE A (curve ref +2b, nyc)")
print("=" * 78)
for tn in TENORS:
    d = df[df["tenor"] == tn]
    print(f"\n{tn}:")
    print(dist(d["A_1"], "1-min grid, ALL prints"))
    print(dist(d.loc[d["exact_A"], "A_1"], "1-min grid, EXACT-DATE prints"))
    print(dist(d.loc[~d["exact_A"], "A_1"], "1-min grid, other-date prints"))

print("\n" + "=" * 78)
print("(grid_mid - implied_mid) in bp   -- SPOT RULE T (tape modal spot)")
print("=" * 78)
for tn in TENORS:
    d = df[df["tenor"] == tn]
    print(f"\n{tn}:")
    print(dist(d["T_1"], "1-min grid, ALL prints"))
    print(dist(d.loc[d["exact_T"], "T_1"], "1-min grid, EXACT-DATE prints"))
    print(dist(d.loc[~d["exact_T"], "T_1"], "1-min grid, other-date prints"))

print("\n" + "=" * 78)
print("SPACING: EXACT-DATE prints only (rule T), by grid spacing")
print("=" * 78)
for tn in TENORS:
    d = df[(df["tenor"] == tn) & df["exact_T"]]
    print(f"\n{tn}:  (n={len(d)})")
    for sp in SPACINGS:
        print(dist(d[f"T_{sp}"], f"{sp:>2}-min grid"))

print("\n" + "=" * 78)
print("SPACING vs |dt| to nearest grid point, EXACT-DATE prints, rule T, "
      "pooled over tenors")
print("=" * 78)
rows = []
for sp in SPACINGS:
    d = df[df["exact_T"]].copy()
    d = d[[f"T_{sp}", f"dt_{sp}", "tenor"]].dropna()
    d.columns = ["err", "dt", "tenor"]
    d["bucket"] = pd.cut(d["dt"], [-1, 30, 60, 120, 300, 600, 1800, 1e9],
                         labels=["<=30s", "30-60s", "1-2m", "2-5m", "5-10m",
                                 "10-30m", ">30m"])
    g = d.groupby("bucket", observed=True)["err"].agg(
        n="size", med="median", absmed=lambda x: x.abs().median(),
        abs95=lambda x: x.abs().quantile(0.95))
    g["spacing"] = sp
    rows.append(g.reset_index())
print(pd.concat(rows).set_index(["spacing", "bucket"]).to_string())
