"""Real coverage series for the daily indicator, from the pinned 610-day cache.

Three jobs, in order, and the first two are validation gates:

1. **The bucket map.** ``indicator.bucket_for_years`` must reproduce the skew
   extract's own ``tenor_bucket`` on all 2,326,781 legs. If it does not, every
   retention factor is attached to the wrong bucket and nothing downstream is
   worth reading.
2. **The retention factors and the drift meter.** Recomputing them here must
   reproduce the published table (0.761 at 0-1Y .. 0.495 at 15-20Y) and the
   1-2Y trend (+5.07 pp/yr, t = +3.21). That is a known answer for
   ``indicator.coverage_drift_table``, computed by a different script a
   different way.
3. **The coverage frame** the indicator consumes, per
   (bucket, day, venue, series), written to D: for the properties run.
"""
import glob
import json
import pathlib

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import indicator as ind
from SDRUtils.dealer_direction import ladder

CACHE = pathlib.Path(r"D:\pkgskew_cache")
OUT = pathlib.Path(r"D:\ddind_cache")
OUT.mkdir(exist_ok=True)

COLS = ["as_of_date", "excl_class", "tenor_bucket", "mat_years", "dv01",
        "venue_class", "is_lifecycle"]

frames = [pd.read_parquet(f, columns=COLS) for f in sorted(glob.glob(str(CACHE / "legs_*.parquet")))]
legs = pd.concat(frames, ignore_index=True)
legs["dv01"] = legs["dv01"].abs()
print(f"legs {len(legs):,}  days {legs.as_of_date.nunique()}  "
      f"dv01 {legs.dv01.sum():,.0f}")

# ---------------------------------------------------------------- gate 1
have = legs["tenor_bucket"].astype("string")
mine = pd.Series([ind.bucket_for_years(y) if np.isfinite(y) else None
                  for y in legs["mat_years"].to_numpy()], dtype="string")
both = have.notna() & mine.notna()
agree = (have[both] == mine[both])
print(f"\nGATE 1 bucket map: {agree.sum():,}/{both.sum():,} agree "
      f"({agree.mean():.8%}); {int((~have.notna()).sum())} legs have no "
      f"extract bucket, carrying {legs.loc[~have.notna(), 'dv01'].sum():,.2f} DV01")
if not agree.all():
    bad = legs[both][~agree.to_numpy()]
    print(bad[["mat_years", "tenor_bucket"]].head(20))
    print("  mine:", mine[both][~agree.to_numpy()].head(20).tolist())
assert agree.all(), "the bucket map disagrees with the skew extract"

# ---------------------------------------------------------------- gate 2
legs["kept"] = legs["excl_class"].astype(str).eq("KEPT")
by_b = legs.groupby("tenor_bucket", dropna=True).apply(
    lambda g: pd.Series({"total": g.dv01.sum(),
                         "kept": g.loc[g.kept, "dv01"].sum()}),
    include_groups=False)
by_b["retention"] = by_b["kept"] / by_b["total"]
by_b["excl_pct"] = 100 * (1 - by_b["retention"])
pub = ind.MEASURED_RETENTION_FACTORS
by_b["published"] = [pub[b] for b in by_b.index]
by_b["abs_err"] = (by_b["retention"] - by_b["published"]).abs()
print("\nGATE 2a retention factors vs the published table")
print(by_b[["retention", "published", "abs_err", "excl_pct"]].round(4).to_string())
assert by_b["abs_err"].max() < 0.001, "retention factors do not reproduce"
print(f"  worst |diff| = {by_b['abs_err'].max():.5f}")

# the drift meter, pooled over venue/series exactly as the doc measured it
pooled = legs.groupby(["tenor_bucket", "as_of_date"], dropna=True).apply(
    lambda g: pd.Series({"dv01_total": g.dv01.sum(),
                         "dv01_kept": g.loc[g.kept, "dv01"].sum()}),
    include_groups=False).reset_index()
pooled = pooled.rename(columns={"tenor_bucket": "bucket_key",
                                "as_of_date": "visibility_date"})
pooled["venue_class"] = "POOLED"
pooled["series"] = "POOLED"
post = pooled[(pooled.visibility_date >= pd.Timestamp("2024-07-01").date())
              & (pooled.visibility_date <= pd.Timestamp("2026-07-31").date())]
drift = ind.coverage_drift_table(post)
drift["exclusion_trend_pp_per_yr"] = -drift["coverage_trend_pp_per_yr"]
drift["exclusion_trend_t"] = -drift["coverage_trend_t"]
print("\nGATE 2b exclusion-rate drift, complete months 2024-07..2026-07 "
      "(doc §1: 1-2Y +5.07 pp/yr t=+3.21, 0-1Y -2.87 t=-2.16)")
show = drift.set_index("bucket_key").reindex(list(ind.TENOR_BUCKETS))
print(show[["n_months", "coverage_mean", "exclusion_trend_pp_per_yr",
            "exclusion_trend_t", "coverage_drift_flag"]].round(3).to_string())

# ---------------------------------------------------------------- the frame
legs["series"] = np.where(legs["is_lifecycle"], ladder.SERIES_LIFECYCLE,
                          ladder.SERIES_FLOW)
cov = legs.groupby(["tenor_bucket", "as_of_date", "venue_class", "series"],
                   dropna=True).apply(
    lambda g: pd.Series({"dv01_total": g.dv01.sum(),
                         "dv01_kept": g.loc[g.kept, "dv01"].sum()}),
    include_groups=False).reset_index()
cov = cov.rename(columns={"tenor_bucket": "bucket_key",
                          "as_of_date": "visibility_date"})
cov = cov[cov["dv01_total"] > 0].reset_index(drop=True)
cov.to_parquet(OUT / "coverage_610d.parquet", index=False)
pooled.to_parquet(OUT / "coverage_pooled_610d.parquet", index=False)
print(f"\nwrote {len(cov):,} coverage cells -> {OUT / 'coverage_610d.parquet'}")

# ---------------------------------------------------------------- moves
c = ind.coverage_fraction(cov)
d2c = c[(c.venue_class == "D2C") & (c.series == ladder.SERIES_FLOW)]
rel = (d2c.sort_values(["bucket_key", "visibility_date"])
          .groupby("bucket_key")["coverage_frac"]
          .apply(lambda s: (s.diff().abs() / s.shift()).dropna()))
print("\nday-over-day |relative| coverage move, D2C/FLOW, per bucket")
tbl = rel.groupby(level=0).agg(
    n="size", median="median",
    p90=lambda s: s.quantile(0.90), p99=lambda s: s.quantile(0.99),
    frac_gt_25pct=lambda s: (s > ind.COVERAGE_MOVE_SIGMA).mean())
print(tbl.reindex(list(ind.TENOR_BUCKETS)).round(4).to_string())

json.dump({"legs": int(len(legs)), "days": int(legs.as_of_date.nunique()),
           "worst_retention_err": float(by_b["abs_err"].max())},
          open(OUT / "coverage_meta.json", "w"), indent=1)
print("\nOK")
