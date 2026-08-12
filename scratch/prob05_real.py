"""Known-answer validation on REAL deviations, plus the tick cross-check.

SHAPE EXERCISE, LABELLED. `arbs_stir_direction_v1.spread_to_mid_bps` comes off
the Barchart Q12xM12STIRT curve, which LEDGER F-20 measured as biased ~0.5 bp
high with ~7x the dispersion of the Citi minute curve. These are NOT the
deviations production will see.

They are still worth running for three things that do not depend on the curve
being good:

1. KNOWN ANSWER. F-20 measured the RATE_VS_MID median s2m at -0.4836 bp,
   independently of anything here. If `b0` lands there, the estimator agrees
   with a number it did not produce.
2. THE DIAGNOSTIC ON REAL DATA. Does the leptokurtosis flag fire where F-20
   says the curve is broken (IMM, FOMC) and stay quiet where it is not?
3. THE TICK CROSS-CHECK, on real buckets, against the legacy pipeline's own
   `arbs_stir_tick_size_v1`. A curve LEVEL bias goes into b0 and a curve
   DISPERSION penalty goes into s -- neither goes into h -- so the fitted
   half-spread is comparable to tick/2 even off a bad curve.

Read-only.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SDRUtils._swappulse_scripts.ingest_usdswaps_tape import resolve_pg_url
from SDRUtils.dealer_direction import probability as prob
from SDRUtils.stir_flow.confidence import TickStats

HERE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 220)

df = pd.read_parquet(os.path.join(HERE, "prob01_devs.parquet"))
df["x"] = df["spread_to_mid_bps"].astype(float)

rv = df[df.classification_method == "RATE_VS_MID"]
print("=== 1. KNOWN ANSWER: F-20 measured median s2m = -0.4836 bp ===")
print(f"    raw median                       {rv.x.median():+.4f}")
fit_all = prob.fit_mixture(rv.x.to_numpy(), bucket="RATE_VS_MID")
print(f"    fitted b0                        {fit_all.b0:+.4f}")
print(f"    fitted h / s / tau               {fit_all.h:.4f} / {fit_all.s:.4f} "
      f"/ {fit_all.tau:.4f}")
print(f"    flags                            {','.join(fit_all.flags)}")
print(f"    excess kurtosis (z)              {fit_all.moment.excess_kurtosis:+.2f} "
      f"({fit_all.moment.excess_kurtosis_z:+.1f})")

print("\n=== 2. does the diagnostic fire where F-20 says the curve is broken? ===")
rows = []
for (idx, tb), g in df.groupby(["rate_index_clean", "tenor_bucket"]):
    if len(g) < 300:
        continue
    f = prob.fit_mixture(g.x.to_numpy(), bucket=f"{idx}|{tb}")
    rows.append(dict(rate_index=idx, bucket=tb, n=len(g), b0=f.b0, h=f.h, s=f.s,
                     tau=f.tau, exkurt=f.moment.excess_kurtosis,
                     z=f.moment.excess_kurtosis_z,
                     lepto=prob.FIT_LEPTOKURTIC in f.flags,
                     flags=",".join(x for x in f.flags if x != prob.FIT_OK)))
b = pd.DataFrame(rows).sort_values("n", ascending=False)
print(b.round(3).to_string(index=False))
kind = np.where(b.bucket.str.startswith("IMM_"), "IMM",
                np.where(b.bucket.str.startswith("FOMC_"), "FOMC", "STANDARD"))
print("\nleptokurtosis flag rate by bucket kind (F-20 calls IMM/FOMC broken):")
print(pd.Series(b.lepto.values).groupby(kind).agg(["mean", "count"]).to_string())

print("\n=== 3. tick cross-check against arbs_stir_tick_size_v1 ===")
eng = create_engine(resolve_pg_url(), pool_pre_ping=True)
with eng.connect() as cx:
    ticks = pd.read_sql(text(
        "SELECT tenor_bucket, structure_type, dv01_bucket, "
        "       percentile_cont(0.5) WITHIN GROUP (ORDER BY median_tick_bps) AS tick, "
        "       sum(tick_sample_count) AS n "
        "  FROM arbs_stir_tick_size_v1 WHERE dv01_bucket = 'ALL' "
        "   AND median_tick_bps IS NOT NULL "
        " GROUP BY 1,2,3"), cx)
print(f"tick rows: {len(ticks)}")
tick_map = {(r.tenor_bucket, r.structure_type): float(r.tick)
            for r in ticks.itertuples()}

cc = []
for (idx, tb, st), g in df.groupby(["rate_index_clean", "tenor_bucket", "trade_type"]):
    t = tick_map.get((tb, st))
    if t is None or len(g) < 300:
        continue
    ts = TickStats(median_tick_bps=t, disp_jns=None,
                   futures_tick_bps=0.5 if idx == "FED_FUNDS" else 0.25)
    f = prob.fit_mixture(g.x.to_numpy(), bucket=f"{idx}|{tb}|{st}", tick_stats=ts)
    x = f.crosscheck
    cc.append(dict(bucket=f"{idx}|{tb}|{st}", n=len(g), tick=t,
                   h_mle=f.h_mle, h_used=f.h, h_tick=x.h_independent,
                   ratio=x.ratio_h, comparable=x.comparable, agrees=x.agrees,
                   anchored=prob.FIT_ANCHORED_H in f.flags))
c = pd.DataFrame(cc).sort_values("n", ascending=False)
print(c.round(3).to_string(index=False))
comp = c[c.comparable]
print(f"\ncomparable (the bucket's own MLE stood up): {len(comp)} of {len(c)}")
if len(comp):
    print(f"of those, inside {prob.CROSSCHECK_TOLERANCE}x: {comp.agrees.mean():.1%}; "
          f"median h_mle/h_tick = {comp.ratio.median():.3f}")
print("THE CROSS-CHECK CANNOT BE EXERCISED ON THIS CURVE -- see the note in the "
      "report: the MLE fails on ~every legacy bucket, so there is nothing "
      "independent left to compare. Re-run on Citi deviations.")

print("\n=== 4. b0 against F-20's independently measured tenor gradient ===")
F20 = {"3M": -0.136, "1Y": -0.246, "2Y": -0.524, "3Y": -1.237,
       "IMM_1Y": -5.57, "IMM_2Y": -6.84, "IMM_3Y": -6.83}
for tb, expect in F20.items():
    g = df[(df.rate_index_clean == "SOFR") & (df.tenor_bucket == tb)]
    if g.empty:
        continue
    f = prob.fit_mixture(g.x.to_numpy(), bucket=tb)
    print(f"  {tb:8s} n={len(g):5d}  F-20 median {expect:+7.3f}   "
          f"raw median {g.x.median():+7.3f}   fitted b0 {f.b0:+7.3f}")
