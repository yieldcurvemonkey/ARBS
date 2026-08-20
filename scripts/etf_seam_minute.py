r"""The 15:00 -> 16:00 seam at MINUTE resolution, on the month-turn days.

The hourly layer answers the seam question over seven years but can only see its
endpoints. This reads the same window off the minute layer, where the endpoints
are real prints rather than bar closes and the path between them is visible.

Three things are measured, all in bp and all against the measured 0.535 bp
butterfly round trip from the daily study:

* the seam's SIZE - mean absolute 15:00->16:00 yield change;
* its CROSS-SECTIONAL dispersion after removing the day's mean, which is what a
  level-neutral structure can actually see;
* the same, restricted to the month-turn days the minute layer was warmed for,
  against the ordinary days inside the same blocks.

An ``asof`` read is used at each clock time, never ``nearest``: a nearest-match
would answer a 15:00 request with a 15:04 print and quietly put four minutes of
the future into a 15:00 mark.
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402

FLY_ROUND_TRIP_BP = 0.535
CLOCKS = ("14:00", "15:00", "15:30", "16:00", "16:15", "17:00")


def asof_panel(cache: CitiVeloTagCache, tags, clock: str,
               tol_min: int = 30) -> pd.DataFrame:
    """``{date -> {tag: last print at or before clock}}``, NaN when nothing is near.

    ``tol_min`` refuses a mark carried forward more than half an hour: a bond that
    last printed at 13:40 does not have a 15:00 mark, and pretending it does puts
    an eighty-minute-stale number into a one-hour measurement.
    """
    hh, mm = (int(x) for x in clock.split(":"))
    cols = {}
    for tag in tags:
        s = cache.read(tag, "MI01", "CLOSE")
        if s is None or s.empty:
            continue
        s = s.dropna()
        idx = pd.DatetimeIndex(s.index)
        target = idx.normalize() + pd.Timedelta(hours=hh, minutes=mm)
        keep = idx <= target
        df = pd.DataFrame({"day": idx.normalize(), "ts": idx, "v": s.to_numpy()})[keep]
        if df.empty:
            continue
        last = df.sort_values("ts").groupby("day").last()
        tgt = last.index + pd.Timedelta(hours=hh, minutes=mm)
        fresh = (tgt - last["ts"]) <= pd.Timedelta(minutes=tol_min)
        cols[tag] = last.loc[fresh, "v"]
    return pd.DataFrame(cols) if cols else pd.DataFrame()


def main() -> int:
    cache = CitiVeloTagCache()
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    tags = [f"RATES.BOND.{i}.YIELD" for i in uni["isin"].astype(str)]
    panels = {c: asof_panel(cache, tags, c) for c in CLOCKS}
    for c, p in panels.items():
        print(f"{c}: {p.shape[0]} dates x {p.shape[1]} bonds"
              + (f"  {p.index.min().date()} .. {p.index.max().date()}" if len(p) else ""))

    rows = []
    for lo, hi in (("15:00", "16:00"), ("14:00", "15:00"), ("16:00", "17:00"),
                   ("15:00", "15:30"), ("15:30", "16:00"), ("16:00", "16:15")):
        a, b = panels[lo], panels[hi]
        if a.empty or b.empty:
            continue
        cols = a.columns.intersection(b.columns)
        idx = a.index.intersection(b.index)
        d = (b.loc[idx, cols] - a.loc[idx, cols]) * 100.0
        wide = d.notna().sum(axis=1) >= 10
        d = d[wide]
        if d.empty:
            continue
        rows.append({
            "window": f"{lo}->{hi}",
            "dates": int(len(d)),
            "bond_dates": int(d.notna().to_numpy().sum()),
            "mean_abs_move_bp": float(np.nanmean(np.abs(d.to_numpy()))),
            "level_move_sd_bp": float(d.mean(axis=1).std()),
            "xsec_sd_bp_median": float(d.std(axis=1).median()),
            "vs_fly_round_trip": float(d.std(axis=1).median() / FLY_ROUND_TRIP_BP),
        })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 200)
    print("\nMINUTE-RESOLUTION SEAM (month-turn days only):")
    print(out.round(4).to_string(index=False))
    out.to_csv(DATA / "intraday_seam_minute.csv", index=False)

    # Month-end proximity, inside the warmed blocks.
    a, b = panels["15:00"], panels["16:00"]
    cols = a.columns.intersection(b.columns)
    idx = a.index.intersection(b.index)
    d = (b.loc[idx, cols] - a.loc[idx, cols]) * 100.0
    d = d[d.notna().sum(axis=1) >= 10]
    if not d.empty:
        me = pd.Series(d.index).dt.to_period("M").dt.to_timestamp("M")
        dte = (me.to_numpy() - d.index.to_numpy()).astype("timedelta64[D]").astype(int)
        bucket = pd.Series(np.where(np.abs(dte) <= 2, "within 2cd of month end",
                                    "rest of the block"), index=d.index)
        xsd = d.std(axis=1)
        tab = pd.DataFrame({
            "dates": xsd.groupby(bucket).size(),
            "xsec_sd_bp_median": xsd.groupby(bucket).median(),
            "mean_abs_move_bp": d.abs().mean(axis=1).groupby(bucket).mean(),
        })
        tab["xsec_sd_vs_cost"] = tab["xsec_sd_bp_median"] / FLY_ROUND_TRIP_BP
        print("\n15:00 -> 16:00 at minute resolution, by month-end proximity:")
        print(tab.round(4).to_string())
        tab.to_csv(DATA / "intraday_seam_minute_by_monthend.csv")
    print("\nwrote intraday_seam_minute.csv, intraday_seam_minute_by_monthend.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
