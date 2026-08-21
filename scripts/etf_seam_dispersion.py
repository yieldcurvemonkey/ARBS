r"""How much of the 15:00 -> 16:00 move is CROSS-SECTIONAL, over the whole warmed history.

The structural hypothesis is that the seam between a 15:00 New York cash mark and
a 16:00 NAV strike is where a rebalancing fund's economics and the bonds' marks
diverge. A butterfly is level-neutral, so what a butterfly can harvest from that
seam is not the size of the 15->16 move - it is the part of that move which
differs ACROSS bonds. A one-basis-point parallel drift between 15:00 and 16:00 is
worth exactly nothing to a fly.

So this measures both, side by side, from the cache and offline:

* the pooled mean absolute 15->16 yield change, which is the seam's total size;
* the CROSS-SECTIONAL standard deviation of that change on each date, after
  removing the day's mean, which bounds what a level-neutral structure can see.

The daily study's wall was a 0.434 bp cross-sectional richness dispersion against
a 0.535 bp butterfly round trip. The comparable number here is the one to put
next to it.
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402

MEASURED_FLY_ROUND_TRIP_BP = 0.535   # RESULTS.md, measured FedInvest bid/offer


def mark_at(frame: pd.DataFrame, clock_hour: int) -> pd.DataFrame:
    """The New York mark at ``clock_hour``:00, read off the correctly-stamped bar.

    Citi's HOURLY bars are START-STAMPED and carry their own close. Measured
    against the minute tape on 3,804 bond-day-hours (``etf_stamp_convention2.py``):
    the value at stamp ``H`` equals the MI01 print at ``H:59`` on **100.0%** of
    them, median difference 0.0000 bp - not a correlation, an identity.

    So the mark at 16:00 lives at stamp 15:00, and a naive read of the series
    labelled "15:00" as a 15:00 mark is off by one hour. That mislabelling would
    have renamed the 16:00->17:00 hour as the seam and reported it as such.
    """
    stamp = clock_hour - 1
    idx = pd.Series(frame.index)
    sub = frame[(idx.dt.hour == stamp).to_numpy()]
    out = sub.copy()
    out.index = pd.DatetimeIndex(pd.Series(sub.index).dt.normalize())
    return out[~out.index.duplicated(keep="last")]


def main() -> int:
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    isins = list(uni["isin"].astype(str))
    q = CitiVeloQuotes(offline=True)
    tags = [f"RATES.BOND.{i}.YIELD" for i in isins]
    frame = q.frame(tags, "HOURLY")
    print(f"cache: {frame.shape[0]:,} hourly rows x {frame.shape[1]} bonds, "
          f"{frame.index.min()} .. {frame.index.max()}")

    rows = []
    for lo, hi, name in ((15, 16, "1500->1600  THE SEAM"),
                         (14, 15, "1400->1500  control"),
                         (13, 14, "1300->1400  control"),
                         (16, 17, "1600->1700  control (post cash close)"),
                         (10, 16, "1000->1600  control (whole session)")):
        a, b = mark_at(frame, lo), mark_at(frame, hi)
        common = a.index.intersection(b.index)
        common = common[common.to_series().dt.weekday < 5]
        d = (b.loc[common] - a.loc[common]) * 100.0        # bp
        d = d.dropna(axis=1, how="all")
        # Level-neutral part: remove each date's cross-sectional mean.
        demeaned = d.sub(d.mean(axis=1), axis=0)
        n_obs = int(d.notna().to_numpy().sum())
        wide = d.notna().sum(axis=1) >= 10
        rows.append({
            "window": name,
            "dates": int(wide.sum()),
            "bond_dates": n_obs,
            "mean_abs_move_bp": float(np.nanmean(np.abs(d.to_numpy()))),
            "level_move_sd_bp": float(d.mean(axis=1)[wide].std()),
            "xsec_sd_bp_median": float(d[wide].std(axis=1).median()),
            "xsec_sd_bp_mean": float(d[wide].std(axis=1).mean()),
            "residual_sd_bp_pooled": float(np.nanstd(demeaned[wide].to_numpy())),
            "vs_fly_round_trip": float(d[wide].std(axis=1).median()
                                       / MEASURED_FLY_ROUND_TRIP_BP),
        })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    print("\n" + out.to_string(index=False))
    out.to_csv(DATA / "intraday_seam_dispersion.csv", index=False)

    # Per year, for the seam window only, so a single regime cannot carry it.
    a, b = mark_at(frame, 15), mark_at(frame, 16)
    common = a.index.intersection(b.index)
    common = common[common.to_series().dt.weekday < 5]
    d = ((b.loc[common] - a.loc[common]) * 100.0).dropna(axis=1, how="all")
    wide = d.notna().sum(axis=1) >= 10
    d = d[wide]
    per_year = pd.DataFrame({
        "dates": d.groupby(d.index.year).size(),
        "mean_level_move_bp": d.mean(axis=1).groupby(d.index.year).mean(),
        "xsec_sd_bp_median": d.std(axis=1).groupby(d.index.year).median(),
        "mean_abs_move_bp": d.abs().mean(axis=1).groupby(d.index.year).mean(),
    })
    per_year["xsec_sd_vs_cost"] = per_year["xsec_sd_bp_median"] / MEASURED_FLY_ROUND_TRIP_BP
    print("\nPER YEAR, 15:00 -> 16:00:")
    print(per_year.round(4).to_string())
    per_year.to_csv(DATA / "intraday_seam_dispersion_by_year.csv")

    # Is the seam WIDER at the reconstitution? That is the whole hypothesis, and
    # it is a two-line question once the frame exists.
    me = pd.Series(d.index).dt.to_period("M").dt.to_timestamp("M")
    dte = (me.to_numpy() - d.index.to_numpy()).astype("timedelta64[D]").astype(int)
    buckets = pd.cut(pd.Series(dte, index=d.index), [-1, 2, 5, 10, 400],
                     labels=["last 3 cal days", "3-5", "6-10", "rest of month"])
    xsd = d.std(axis=1)
    by_bucket = pd.DataFrame({
        "dates": xsd.groupby(buckets, observed=False).size(),
        "xsec_sd_bp_median": xsd.groupby(buckets, observed=False).median(),
        "mean_abs_move_bp": d.abs().mean(axis=1).groupby(buckets, observed=False).mean(),
    })
    by_bucket["xsec_sd_vs_cost"] = by_bucket["xsec_sd_bp_median"] / MEASURED_FLY_ROUND_TRIP_BP
    print("\n15:00 -> 16:00 SEAM by distance to month end (the reconstitution):")
    print(by_bucket.round(4).to_string())
    by_bucket.to_csv(DATA / "intraday_seam_dispersion_by_monthend.csv")
    print("\nwrote intraday_seam_dispersion*.csv (3 files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
