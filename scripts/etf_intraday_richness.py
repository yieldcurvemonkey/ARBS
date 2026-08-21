r"""The seam, measured on the SAME richness definition the daily study's wall was.

The daily result this whole effort is trying to get past is a number:
cross-sectional richness dispersion of **0.434 bp** against a **0.535 bp**
butterfly round trip - 0.81x, and no edge. That number is a residual to
``RVUtils.ETFRebalance.curve.fit_residuals``: a local, robust, coupon-adjusted
cubic in maturity, not a raw yield and not a global polynomial.

Comparing an intraday raw-yield dispersion to it would be comparing two different
statistics and calling the difference a finding, so this runs the repo's own
fitter on the intraday marks instead, at the two clock times that matter:

* **15:00 New York** - where the cash desks mark, which is the hourly bar stamped
  ``14:00`` (start-stamped bars, tied out to the minute tape at H:59 on 100.0% of
  3,804 bond-day-hours);
* **16:00 New York** - where the NAV is struck and the shares stop trading, which
  is the bar stamped ``15:00``.

Two quantities come out, and only the second is tradeable:

``resid_sd``
    the cross-section of richness at an instant. Directly comparable to 0.434 bp.
``dresid_sd``
    the cross-section of the CHANGE in richness between 15:00 and 16:00. This is
    what a level- and curve-neutral structure put on at 15:00 and taken off at
    16:00 could capture at most, before any question of whether it is predictable.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402
from RVUtils.ETFRebalance.curve import fit_residuals  # noqa: E402

DAILY_RICHNESS_SD_BP = 0.434
FLY_ROUND_TRIP_BP = 0.535


def panel_at(frame: pd.DataFrame, stamp_hour: int, meta: pd.DataFrame) -> pd.DataFrame:
    idx = pd.Series(frame.index)
    sub = frame[(idx.dt.hour == stamp_hour).to_numpy()]
    sub = sub[~pd.Series(sub.index).dt.normalize().duplicated(keep="last").to_numpy()]
    long = sub.stack().rename("ytm").reset_index()
    long.columns = ["stamp", "tag", "ytm"]
    long["isin"] = long["tag"].str.split(".").str[2]
    long = long.merge(meta, on="isin", how="left")
    long["date"] = pd.to_datetime(long["stamp"]).dt.normalize()
    long["ttm"] = (long["maturity_date"] - long["stamp"]).dt.days / 365.25
    long = long[(long["ttm"] > 0) & long["ytm"].notna() & long["cpn"].notna()]
    return long[["date", "stamp", "cusip", "isin", "ytm", "ttm", "cpn"]]


def main() -> int:
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    uni["maturity_date"] = pd.to_datetime(uni["maturity_date"])
    meta = uni.rename(columns={"coupon": "cpn"})[["isin", "cusip", "maturity_date", "cpn"]]

    q = CitiVeloQuotes(offline=True)
    frame = q.frame([f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)], "HOURLY")
    frame = frame[frame.index >= "2021-01-01"]
    print(f"panel {frame.shape[0]:,} stamps x {frame.shape[1]} bonds")

    out_rows = []
    fitted = {}
    for clock, stamp in (("15:00 NY", 14), ("16:00 NY", 15)):
        p = panel_at(frame, stamp, meta)
        p = p[p.groupby("date")["cusip"].transform("size") >= 20]
        r = fit_residuals(p, deg=3, x_axis="ttm", include_coupon=True, robust=True,
                          y_col="ytm")
        fitted[clock] = r
        sd = r.groupby("date")["resid_bp"].std()
        rmse = r.groupby("date")["fit_rmse_bp"].first()
        out_rows.append({
            "clock": clock, "stamp_hour": stamp, "dates": int(sd.notna().sum()),
            "bonds_median": int(r.groupby("date").size().median()),
            "resid_sd_bp_median": float(sd.median()),
            "fit_rmse_bp_median": float(rmse.median()),
            "vs_daily_study_0434": float(sd.median() / DAILY_RICHNESS_SD_BP),
            "vs_fly_round_trip": float(sd.median() / FLY_ROUND_TRIP_BP),
        })
    inst = pd.DataFrame(out_rows)
    pd.set_option("display.width", 220)
    print("\nRICHNESS AT AN INSTANT (repo's own local robust coupon-adjusted fit):")
    print(inst.round(4).to_string(index=False))

    # ---- the tradeable object: the CHANGE in richness across the seam ------
    a = fitted["15:00 NY"].pivot_table(index="date", columns="cusip", values="resid_bp")
    b = fitted["16:00 NY"].pivot_table(index="date", columns="cusip", values="resid_bp")
    cols = a.columns.intersection(b.columns)
    idx = a.index.intersection(b.index)
    dr = b.loc[idx, cols] - a.loc[idx, cols]
    dr = dr[dr.notna().sum(axis=1) >= 20]
    sd_d = dr.std(axis=1)
    print(f"\nCHANGE IN RICHNESS, 15:00 -> 16:00 New York, {len(dr)} dates x "
          f"{len(cols)} bonds")
    print(f"  cross-sectional SD of the richness CHANGE: median {sd_d.median():.4f} bp")
    print(f"  as a fraction of the 0.535 bp butterfly round trip: "
          f"{sd_d.median() / FLY_ROUND_TRIP_BP:.3f}x")
    print(f"  the daily study's wall was {DAILY_RICHNESS_SD_BP:.3f} bp = "
          f"{DAILY_RICHNESS_SD_BP / FLY_ROUND_TRIP_BP:.2f}x")
    print(f"  mean |richness change| per bond-day: {dr.abs().stack().mean():.4f} bp")

    me = pd.Series(dr.index).dt.to_period("M").dt.to_timestamp("M")
    dte = (me.to_numpy() - dr.index.to_numpy()).astype("timedelta64[D]").astype(int)
    bucket = pd.Series(np.where(dte <= 2, "last 3 cal days of month", "rest of month"),
                       index=dr.index)
    tab = pd.DataFrame({
        "dates": sd_d.groupby(bucket).size(),
        "dresid_sd_bp_median": sd_d.groupby(bucket).median(),
        "mean_abs_dresid_bp": dr.abs().mean(axis=1).groupby(bucket).mean(),
    })
    tab["vs_fly_round_trip"] = tab["dresid_sd_bp_median"] / FLY_ROUND_TRIP_BP
    print("\nby distance to the reconstitution:")
    print(tab.round(4).to_string())

    per_year = pd.DataFrame({
        "dates": sd_d.groupby(sd_d.index.year).size(),
        "dresid_sd_bp_median": sd_d.groupby(sd_d.index.year).median(),
    })
    per_year["vs_fly_round_trip"] = per_year["dresid_sd_bp_median"] / FLY_ROUND_TRIP_BP
    print("\nper year:")
    print(per_year.round(4).to_string())

    # ---- what a BUTTERFLY sees, measured rather than assumed ---------------
    # Assuming independent residuals would give the fly a spread of sqrt(6)*sd.
    # Adjacent-maturity residuals are correlated, so that overstates it. Build the
    # actual adjacent triplets and measure.
    mat = dict(zip(uni["cusip"].astype(str), uni["maturity_date"]))
    fly_rows = []
    for date, row in dr.iterrows():
        v = row.dropna()
        if len(v) < 5:
            continue
        order = sorted(v.index, key=lambda c: mat.get(c, pd.Timestamp.max))
        vals = v[order].to_numpy()
        # 2*belly - front - back on every adjacent triplet
        f = 2.0 * vals[1:-1] - vals[:-2] - vals[2:]
        fly_rows.append({"date": date, "n_flies": len(f),
                         "fly_sd_bp": float(np.std(f)),
                         "fly_mean_abs_bp": float(np.mean(np.abs(f)))})
    fly = pd.DataFrame(fly_rows).set_index("date")
    perfect = float(fly["fly_mean_abs_bp"].median())
    print(f"\nWHAT A BUTTERFLY SEES, 15:00 -> 16:00 New York")
    print(f"  adjacent-maturity triplets per date: median {int(fly['n_flies'].median())}")
    print(f"  SD of the fly's richness change:        {fly['fly_sd_bp'].median():.4f} bp")
    print(f"  mean |fly richness change|:             {perfect:.4f} bp")
    print(f"  a PERFECT forecaster of the sign earns that {perfect:.4f} bp gross, "
          f"against a MEASURED {FLY_ROUND_TRIP_BP:.3f} bp round trip "
          f"= {perfect / FLY_ROUND_TRIP_BP:.3f}x")
    fly_me = fly[(pd.Series(fly.index).dt.to_period("M").dt.to_timestamp("M").to_numpy()
                  - fly.index.to_numpy()).astype("timedelta64[D]").astype(int) <= 2]
    print(f"  on the last 3 calendar days of the month ({len(fly_me)} dates): "
          f"{fly_me['fly_mean_abs_bp'].median():.4f} bp = "
          f"{fly_me['fly_mean_abs_bp'].median() / FLY_ROUND_TRIP_BP:.3f}x")
    fly.to_csv(DATA / "intraday_richness_fly_by_date.csv")

    inst.to_csv(DATA / "intraday_richness_instant.csv", index=False)
    tab.to_csv(DATA / "intraday_richness_change_by_monthend.csv")
    per_year.to_csv(DATA / "intraday_richness_change_by_year.csv")
    sd_d.rename("dresid_sd_bp").to_csv(DATA / "intraday_richness_change_by_date.csv")
    print("\nwrote intraday_richness_instant.csv, intraday_richness_change_by_*.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
