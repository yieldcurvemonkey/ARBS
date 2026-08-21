r"""Is the value at hourly stamp 15:00 a 15:00 mark, or the CLOSE of the 15:00-16:00 bar?

This is not pedantry. The whole intraday study is about the 15:00 New York cash
mark against the 16:00 NAV strike, and if Citi's hourly bars are start-stamped
closes then the series labelled ``15:00`` is a 16:00 print and every statement
about the seam is off by one hour - including the dispersion headline.

It is settled by comparing the two layers on the same bond-day. The MI01 series
carries an actual print at each minute; the HOURLY series carries one number per
hour. Whichever minute the hourly number EQUALS is the convention, and equality
here is exact to the tick, not a correlation.

Three candidate conventions are tested against the minute tape:

* ``point 15:00``  - the hourly value equals the last minute print at or before 15:00
* ``bar close 16:00`` (start-stamped) - it equals the last print at or before 16:00
* ``bar close 15:00`` (end-stamped)   - identical to the first; the discriminator
  between them is only whether 15:00's number ever uses information after 15:00
"""

from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.cache import CitiVeloTagCache  # noqa: E402


def main() -> int:
    cache = CitiVeloTagCache()
    stems = sorted((cache.base_dir / "MI01" / "CLOSE").glob("RATES.BOND.*.YIELD.parquet"))
    rows = []
    for p in stems[:120]:
        tag = p.stem
        mi = cache.read(tag, "MI01", "CLOSE")
        hr = cache.read(tag, "HOURLY", "CLOSE")
        if mi is None or hr is None or mi.empty or hr.empty:
            continue
        mi, hr = mi.dropna(), hr.dropna()
        days = sorted(set(pd.Series(mi.index).dt.date) & set(pd.Series(hr.index).dt.date))
        for day in days:
            m = mi[pd.Series(mi.index).dt.date.to_numpy() == day]
            h = hr[pd.Series(hr.index).dt.date.to_numpy() == day]
            for hour in (10, 13, 15, 16):
                ts = pd.Timestamp(day) + pd.Timedelta(hours=hour)
                if ts not in h.index:
                    continue
                target = float(h.loc[ts])
                for label, bound in (
                    ("asof_H", ts),
                    ("asof_H+1h", ts + pd.Timedelta(hours=1)),
                    ("asof_H-1h", ts - pd.Timedelta(hours=1)),
                ):
                    prior = m.index[m.index <= bound]
                    if len(prior) == 0:
                        continue
                    v = float(m.loc[prior.max()])
                    rows.append({"tag": tag, "day": day, "hour": hour, "candidate": label,
                                 "hourly": target, "minute": v,
                                 "exact": bool(abs(v - target) < 1e-9),
                                 "abs_diff_bp": abs(v - target) * 100.0,
                                 "minute_stamp": prior.max()})
    df = pd.DataFrame(rows)
    if df.empty:
        print("No overlapping MI01/HOURLY bond-days yet.")
        return 1
    pd.set_option("display.width", 200)
    g = df.groupby(["hour", "candidate"]).agg(
        n=("exact", "size"), exact_frac=("exact", "mean"),
        median_abs_diff_bp=("abs_diff_bp", "median")).reset_index()
    print(f"{df['tag'].nunique()} bonds x {df['day'].nunique()} overlapping days\n")
    print(g.round(4).to_string(index=False))

    best = g.loc[g.groupby("hour")["exact_frac"].idxmax()]
    print("\nBEST MATCH PER HOUR:")
    print(best.round(4).to_string(index=False))
    win = best["candidate"].mode().iat[0]
    print(f"\nVERDICT: the hourly value at stamp H matches the minute tape "
          f"'{win}'. "
          + ("The stamp is a POINT-IN-TIME mark at H: a value labelled 15:00 is a "
             "15:00 New York mark and the 15:00->16:00 seam is exactly that."
             if win == "asof_H" else
             "The stamp is NOT a point-in-time mark at H - the seam labels must be "
             "shifted accordingly."))
    df.to_csv(DATA / "intraday_stamp_convention_detail.csv", index=False)
    g.to_csv(DATA / "intraday_stamp_convention.csv", index=False)
    print("\nwrote intraday_stamp_convention.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
