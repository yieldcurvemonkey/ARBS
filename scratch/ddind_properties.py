"""The published series' own properties, measured on the 610-day cache.

What this CAN measure, exactly and for free, is everything the indicator
publishes except the signed level: the **gross pond** behind each cell, the
**coverage fraction** in front of it, and the **coverage-adjustment factor**
that the second basis multiplies by. The signed level itself needs the
repricing pass (measured today at 115 s/day, plus ~65 s/day for the key-rate
change of basis) and is left unmeasured on purpose rather than approximated.

Every meter used here is the indicator's own, already validated:
``_autocorr``, ``_adf`` (identical to statsmodels to 2.5e-13, empirical size
2.8-5.0% against a nominal 5%), and ``coverage_drift_table`` (reproduces the
skew document's +5.07 pp/yr, t = +3.21 at 1-2Y).
"""
import pathlib

import numpy as np
import pandas as pd

from SDRUtils.dealer_direction import indicator as ind
from SDRUtils.dealer_direction import ladder
from SDRUtils.dealer_direction import types as T

OUT = pathlib.Path(r"D:\ddind_cache")
cov = pd.read_parquet(OUT / "coverage_610d.parquet")
cov = ind.coverage_fraction(cov)
ALL_DAYS = sorted(set(cov["visibility_date"]))
print(f"cells {len(cov):,}  days {len(ALL_DAYS)}  "
      f"{min(ALL_DAYS)} .. {max(ALL_DAYS)}")

FLOOR = pd.Timestamp(ind.SAMPLE_FLOOR).date()
post = cov[cov.visibility_date >= FLOOR]
# the calendar MUST be the post-floor day set. Reindexing post-floor cells onto
# all 610 days prepends 84 zeros, which is a structural break that no ADF can
# see past -- it made every gross series look non-stationary at AC1 = 0.7.
SESSIONS = sorted(set(post["visibility_date"]))
print(f"post sample floor ({FLOOR}): {len(post):,} cells, "
      f"{post.visibility_date.nunique()} days\n")


def _reindexed(block, col, fill):
    s = block.set_index("visibility_date")[col].reindex(SESSIONS)
    return s.fillna(fill).to_numpy(dtype="float64"), s.notna().to_numpy()


def properties(sel, label):
    rows = []
    for bucket in ind.TENOR_BUCKETS:
        b = sel[sel.bucket_key == bucket].sort_values("visibility_date")
        if b.empty:
            continue
        gross, obs = _reindexed(b, "dv01_kept", 0.0)
        cf = b.set_index("visibility_date")["coverage_frac"].reindex(SESSIONS)
        adf_g, stat_g = ind._adf(gross)
        cfv = cf.to_numpy(dtype="float64")
        adf_c, stat_c = ind._adf(cfv[np.isfinite(cfv)])
        rows.append({
            "bucket": bucket, "n_days": int(obs.sum()),
            "frac_days_present": float(obs.mean()),
            "gross_mean_musd_bp": float(np.mean(gross)) / 1e6,
            "gross_ac1": ind._autocorr(gross, 1),
            "gross_ac5": ind._autocorr(gross, 5),
            "gross_ac21": ind._autocorr(gross, 21),
            "gross_adf": adf_g, "gross_stationary": stat_g,
            "cov_mean": float(np.nanmean(cfv)), "cov_sd": float(np.nanstd(cfv, ddof=1)),
            "cov_ac1": ind._autocorr(cfv[np.isfinite(cfv)], 1),
            "cov_adf": adf_c, "cov_stationary": stat_c,
        })
    out = pd.DataFrame(rows)
    print(f"=== {label} ===")
    print(out.round(4).to_string(index=False))
    print()
    return out


d2c = post[(post.venue_class == T.VENUE_D2C) & (post.series == ladder.SERIES_FLOW)]
d2d = post[(post.venue_class == T.VENUE_D2D) & (post.series == ladder.SERIES_FLOW)]
unk = post[(post.venue_class == T.VENUE_UNKNOWN) & (post.series == ladder.SERIES_FLOW)]
p_d2c = properties(d2c, "D2C / FLOW  (kept gross DV01 and coverage, per bucket-day)")
p_d2d = properties(d2d, "D2D / FLOW")
p_unk = properties(unk, "VENUE_UNKNOWN / FLOW")

# ------------------------------------------------------------------ moves
print("=== coverage moves: does the size of the day change the answer? ===")
rows = []
for bucket in ind.TENOR_BUCKETS:
    b = d2c[d2c.bucket_key == bucket].sort_values("visibility_date")
    c = b["coverage_frac"].to_numpy(dtype="float64")
    g = b["dv01_total"].to_numpy(dtype="float64")
    ok = np.isfinite(c[:-1]) & (c[:-1] > 0)
    rel = np.where(ok, np.abs(np.diff(c)) / np.where(ok, c[:-1], 1.0), np.nan)
    keep = np.isfinite(rel)
    big = (g[:-1] >= np.median(g)) & keep
    rel_all = rel[keep]
    rows.append({
        "bucket": bucket, "n": int(keep.sum()),
        "median_rel_move": float(np.median(rel_all)),
        "frac_gt_25pct_all": float((rel_all > 0.25).mean()),
        "frac_gt_25pct_big_days": float((rel[big] > 0.25).mean()),
        "median_rel_move_big_days": float(np.median(rel[big])),
    })
moves = pd.DataFrame(rows)
print(moves.round(4).to_string(index=False))
print("  ('big days' = the day's gross tape DV01 in that bucket is at or above "
      "the bucket's own median)\n")

# ---------------------------------------------- the effect of the basis choice
print("=== effect of the level-basis choice, measured on the factor itself ===")
print("adjusted = raw * f,  f = mean(coverage) / rolling_mean(coverage, "
      f"{ind.COVERAGE_SMOOTH_OBS}). f is a pure function of coverage, so its")
print("path bounds the raw-vs-adjusted divergence for ANY level path.\n")
rows = []
for bucket in ind.TENOR_BUCKETS:
    b = d2c[d2c.bucket_key == bucket].sort_values("visibility_date")
    cf = pd.Series(b["coverage_frac"].to_numpy(dtype="float64"))
    smooth = cf.rolling(ind.COVERAGE_SMOOTH_OBS,
                        min_periods=ind.COVERAGE_SMOOTH_OBS).mean()
    f = (cf.mean() / smooth).dropna()
    yrs = np.array([(d - b.visibility_date.iloc[0]).days / 365.25
                    for d in b.visibility_date])[-len(f):]
    slope = np.polyfit(yrs, f.to_numpy(), 1)[0] if len(f) > 10 else np.nan
    rows.append({
        "bucket": bucket, "n_f": len(f),
        "f_mean": float(f.mean()), "f_sd": float(f.std(ddof=1)),
        "f_p5": float(f.quantile(0.05)), "f_p95": float(f.quantile(0.95)),
        "f_first": float(f.iloc[0]), "f_last": float(f.iloc[-1]),
        "f_last_over_first": float(f.iloc[-1] / f.iloc[0]),
        "f_trend_per_yr": float(slope),
        "sd_log_f_pct": float(np.std(np.log(f.to_numpy()), ddof=1) * 100),
    })
basis = pd.DataFrame(rows)
print(basis.round(4).to_string(index=False))
print("\n  f_sd / sd_log_f is the whole difference between the two bases: at "
      "f_sd = 0 they are the same series.")
print("  A bucket whose f drifts is a bucket whose RAW level carries a "
      "measurement trend the adjusted one removes.\n")

for name, df in (("props_d2c", p_d2c), ("props_d2d", p_d2d),
                 ("props_unknown", p_unk), ("moves", moves), ("basis", basis)):
    df.to_csv(OUT / f"ddind_{name}.csv", index=False)
print(f"wrote 5 tables -> {OUT}")
