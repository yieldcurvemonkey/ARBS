r"""Build the intraday (date x New York clock hour x bond) panel this study grids over.

Three things are joined and one is fitted.

* **Yields** come from the warmed Citi ``HOURLY`` layer, read through
  :mod:`RVUtils.ETFRebalance.intraday` so the START-STAMPED bar convention is applied
  once, here, rather than by every caller. ``ny_marks(frame, 16)`` really is the 16:00
  New York mark.
* **ttm / cpn / mod_dur / spread_price_bp** come from the daily FedInvest panel
  (``ust_panel.parquet``). Duration and the quoted spread do not move materially inside a
  session, and there is no intraday source for either, so the daily value is carried
  across the day and that is stated rather than hidden.
* **resid_bp** is fitted PER (date, hour) with the daily study's own
  ``curve.fit_residuals`` -- local robust coupon-adjusted cubic. Refitting at each hour is
  the whole point: a residual carried from the daily close cannot answer a question about
  time of day.
* **stale** flags a bond-hour whose yield is EXACTLY the previous hour's. That is the H4
  covariate. A bond that does not print between 15:00 and 16:00 contributes a mechanical
  zero to the seam move, which biases the seam's dispersion down and its per-bond
  structure toward whatever is liquid.

Early closes are flagged, not dropped, from the SIFMA recommended-close rules (July 3 or
the weekday before July 4, the Friday after Thanksgiving, Christmas Eve, New Year's Eve,
Good Friday) plus an empirical staleness check, because a 14:00 close makes the 15:00 and
16:00 marks the same number by construction and month-end can land on one.
"""
from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from RVUtils.ETFRebalance import curve, intraday as itd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "notebooks" / "backtests" / "etf_rebalance" / "_data"

#: New York clock hours the grid ranges over. 09:00 is the first hour with a full
#: cross-section (stamp 8 carries 1,811 rows against 1,845 for stamps 9-17) and 17:00 is
#: the last hour before the tape thins into the overnight session.
CLOCK_HOURS = list(range(9, 18))


def _easter(year: int) -> pd.Timestamp:
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return pd.Timestamp(year=year, month=month, day=day + 1)


def early_close_dates(years) -> set:
    """SIFMA recommended 14:00 (or earlier) US bond-market closes."""
    out = set()
    for y in years:
        # July 3, or the weekday before July 4 when the 3rd is a weekend
        j4 = pd.Timestamp(y, 7, 4)
        cand = j4 - pd.Timedelta(days=1)
        while cand.weekday() >= 5:
            cand -= pd.Timedelta(days=1)
        out.add(cand.normalize())
        # Friday after Thanksgiving (4th Thursday of November)
        nov = pd.date_range(f"{y}-11-01", f"{y}-11-30", freq="D")
        thurs = [d for d in nov if d.weekday() == 3]
        out.add((thurs[3] + pd.Timedelta(days=1)).normalize())
        # Christmas Eve and New Year's Eve, rolled back off a weekend
        for mo, da in ((12, 24), (12, 31)):
            c = pd.Timestamp(y, mo, da)
            while c.weekday() >= 5:
                c -= pd.Timedelta(days=1)
            out.add(c.normalize())
        # Maundy Thursday (early close before Good Friday's full close)
        out.add((_easter(y) - pd.Timedelta(days=3)).normalize())
    return out


def build() -> pd.DataFrame:
    t0 = time.time()
    uni = itd.universe()
    isin2cusip = dict(zip(uni["isin"].astype(str), uni["cusip"].astype(str)))

    fr = itd.drop_impossible(itd.hourly_frame("YIELD"), "YIELD")
    fr = fr.rename(columns=isin2cusip)
    print(f"[panel] hourly yields {fr.shape} in {time.time()-t0:.1f}s", flush=True)

    # ---- stack to (date, hour, cusip) over the clock hours we grid on -----------------
    stamps = {h: itd.ny_stamp(h) for h in CLOCK_HOURS}
    idx_hour = pd.Series(fr.index).dt.hour.to_numpy()
    pieces = []
    for h, st in stamps.items():
        sub = fr[idx_hour == st]
        d = pd.DatetimeIndex(pd.Series(sub.index).dt.normalize())
        sub = sub.copy()
        sub.index = d
        sub = sub[~sub.index.duplicated(keep="last")]
        s = sub.stack(future_stack=True).rename("ytm_h")
        s.index.names = ["date", "cusip"]
        p = s.reset_index()
        p["hour"] = h
        pieces.append(p.dropna(subset=["ytm_h"]))
    px = pd.concat(pieces, ignore_index=True)
    print(f"[panel] stacked {len(px):,} bond-hours over {px['date'].nunique()} dates",
          flush=True)

    # ---- staleness: exactly the previous CLOCK hour's yield, same bond, same day ------
    px = px.sort_values(["cusip", "date", "hour"])
    prev = px.groupby(["cusip", "date"])["ytm_h"].shift(1)
    px["stale"] = (px["ytm_h"] == prev)
    px.loc[prev.isna(), "stale"] = False   # first hour of the day: unknown, not stale

    # ---- daily join: ttm / cpn / mod_dur / spread ------------------------------------
    daily = pd.read_parquet(DATA / "ust_panel.parquet",
                            columns=["date", "cusip", "ttm", "cpn", "mod_dur",
                                     "spread_price_bp", "ytm", "issue_date",
                                     "maturity_date", "rank"])
    daily = daily[daily["cusip"].isin(set(uni["cusip"].astype(str)))]
    px = px.merge(daily, on=["date", "cusip"], how="left", suffixes=("", "_eod"))
    have = px["ttm"].notna()
    print(f"[panel] daily join covers {have.mean():.4f} of bond-hours", flush=True)
    px = px[have].copy()

    # ---- residual, refitted at every hour --------------------------------------------
    outs = []
    for h, g in px.groupby("hour", sort=True):
        r = curve.fit_residuals(g, deg=3, x_axis="ttm", include_coupon=True,
                                robust=True, min_bonds=12, y_col="ytm_h")
        outs.append(r)
        print(f"[panel]   hour {h:02d}: {len(r):,} rows, "
              f"resid sd {r['resid_bp'].std():.3f}bp, {time.time()-t0:.0f}s", flush=True)
    px = pd.concat(outs, ignore_index=True)

    ec = early_close_dates(range(int(px["date"].dt.year.min()),
                                 int(px["date"].dt.year.max()) + 1))
    px["early_close"] = px["date"].isin(ec)
    px["is_last_bd"] = px["date"] == px["date"].groupby(
        px["date"].dt.to_period("M")).transform("max")

    px = px.sort_values(["date", "hour", "ttm"]).reset_index(drop=True)
    out = DATA / "tsgrid_intraday_panel.parquet"
    px.to_parquet(out, index=False)
    print(f"[panel] wrote {out} {px.shape} in {time.time()-t0:.0f}s", flush=True)
    return px


if __name__ == "__main__":
    p = build()
    # QC that must be looked at before anything is traded on this
    qc = []
    for h, g in p.groupby("hour"):
        qc.append({
            "clock_hour": h, "stamp": itd.ny_stamp(h),
            "rows": len(g), "dates": g["date"].nunique(),
            "bonds_per_date_med": float(g.groupby("date")["cusip"].size().median()),
            "resid_sd_bp": float(g["resid_bp"].std()),
            "resid_xsec_sd_bp_med": float(g.groupby("date")["resid_bp"].std().median()),
            "fit_rmse_bp_med": float(g.groupby("date")["fit_rmse_bp"].first().median()),
            "stale_frac": float(g["stale"].mean()),
        })
    qc = pd.DataFrame(qc)
    qc.to_csv(DATA / "tsgrid_panel_qc.csv", index=False)
    print(qc.to_string(index=False))
