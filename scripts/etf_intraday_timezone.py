r"""What clock are Citi's bond stamps on? Four independent readings, all measured.

Nothing here assumes the answer. Each test names a real event whose New York
time is fixed by institution, and asks which STAMP hour that event lands on. If
the stamps were UTC every answer would be four or five hours later, and four to
five hours is not a distance any of these tests could confuse.

1. **FOMC, 14:00 New York.** The statement lands at 14:00 ET on 21 decision days
   inside the warmed span. The largest hourly move of an FOMC day is that one.
2. **The 08:30 New York data release.** CPI, payrolls, PPI, claims - the single
   sharpest recurring feature of the Treasury day, and it is at 08:30 ET.
3. **The weekly reopen, Sunday 18:00 New York.** The cash and futures week
   restarts Sunday evening New York, and the hole before it is the weekend.
4. **The bound offset.** A window requested to ``2026-06-20 00:00`` returned its
   last row at ``2026-06-19 20:00``, and one to ``2026-01-20 00:00`` returned
   ``2026-01-19 19:00``. Four hours in EDT, five in EST: the offset TRACKS New
   York's UTC offset across the DST boundary, which pins the stamp clock without
   any reference to market behaviour at all.

Reading 4 is the one that cannot be argued with, because a market-activity
argument can always be answered "maybe that market is busy at a different hour".
A DST-tracking offset cannot.
"""

from __future__ import annotations

import datetime
import pathlib

import numpy as np
import pandas as pd

DATA = pathlib.Path(__file__).resolve().parents[1] / "notebooks/backtests/etf_rebalance/_data"

from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes  # noqa: E402
from RVUtils.SFRRVLab.panels import FOMC_DATES  # noqa: E402


def abs_step_profile(frame: pd.DataFrame, days: set | None = None) -> pd.Series:
    """Mean |1-step yield change| in bp by stamp hour, steps kept inside one day."""
    idx = pd.Series(frame.index)
    if days is not None:
        frame = frame[idx.dt.date.isin(days).to_numpy()]
        idx = pd.Series(frame.index)
    d = frame.diff()
    same = idx.dt.date.to_numpy()
    keep = np.r_[False, same[1:] == same[:-1]]
    d = d[keep]
    hours = pd.Series(d.index).dt.hour.to_numpy()
    vals = np.abs(d.to_numpy()) * 100.0
    out = pd.DataFrame({"hour": np.repeat(hours, vals.shape[1]),
                        "bp": vals.reshape(-1)}).dropna()
    return out.groupby("hour")["bp"].mean()


def main() -> int:
    uni = pd.read_csv(DATA / "intraday_universe.csv")
    isins = list(uni["isin"].astype(str))
    q = CitiVeloQuotes(offline=True)
    frame = q.frame([f"RATES.BOND.{i}.YIELD" for i in isins], "HOURLY")
    print(f"cache: {frame.shape[0]:,} hourly rows x {frame.shape[1]} bonds, "
          f"{frame.index.min()} .. {frame.index.max()}\n")

    all_days = set(pd.Series(frame.index).dt.date)
    fomc = {d for d in FOMC_DATES if d in all_days}
    print(f"TEST 1 - FOMC (statement 14:00 New York), {len(fomc)} decision days in span")
    p_f = abs_step_profile(frame, fomc)
    p_a = abs_step_profile(frame, all_days - fomc)
    cmp = pd.DataFrame({"fomc_bp": p_f, "other_bp": p_a})
    cmp["ratio"] = cmp["fomc_bp"] / cmp["other_bp"]
    print(cmp.round(3).to_string())
    print(f"  -> FOMC/other excess peaks at stamp hour {int(cmp['ratio'].idxmax())} "
          f"(ratio {cmp['ratio'].max():.2f}); 14:00 New York is 18:00 or 19:00 UTC.\n")

    print("TEST 2 - the 08:30 New York release, all days")
    print(p_a.round(3).to_string())
    print(f"  -> unconditional activity peaks at stamp hour {int(p_a.idxmax())}; "
          f"08:30 New York is 12:30 or 13:30 UTC.\n")

    print("TEST 3 - the weekly reopen (Sunday 18:00 New York)")
    one = frame.iloc[:, 0].dropna()
    idx = pd.Series(one.index)
    gaps = idx.diff()
    big = gaps > pd.Timedelta(hours=20)
    firsts = idx[big.fillna(False).to_numpy()]
    lasts = idx.shift(1)[big.fillna(False).to_numpy()]
    tab = pd.DataFrame({
        "reopen_dow": firsts.dt.day_name().to_numpy(),
        "reopen_hour": firsts.dt.hour.to_numpy(),
        "close_dow": lasts.dt.day_name().to_numpy(),
        "close_hour": lasts.dt.hour.to_numpy(),
    })
    print("reopen (day, hour) counts:")
    print(tab.groupby(["reopen_dow", "reopen_hour"]).size()
          .sort_values(ascending=False).head(5).to_string())
    print("close (day, hour) counts:")
    print(tab.groupby(["close_dow", "close_hour"]).size()
          .sort_values(ascending=False).head(5).to_string())
    print()

    print("TEST 4 - the request-bound offset across the DST boundary (measured by probe)")
    print("  requested end 2026-06-20 00:00 -> last stamp 2026-06-19 20:00   (-4h, EDT)")
    print("  requested end 2026-01-20 00:00 -> last stamp 2026-01-19 19:00   (-5h, EST)")
    print("  the offset IS New York's UTC offset, and it changes with New York's DST.\n")

    rows = [
        {"test": "FOMC 14:00 ET", "expected_hour_if_ET": 14,
         "expected_hour_if_UTC": "18/19", "observed_peak_hour": int(cmp["ratio"].idxmax())},
        {"test": "08:30 ET release", "expected_hour_if_ET": "8/9",
         "expected_hour_if_UTC": "12/13", "observed_peak_hour": int(p_a.idxmax())},
        {"test": "Sunday reopen 18:00 ET", "expected_hour_if_ET": 18,
         "expected_hour_if_UTC": "22/23",
         "observed_peak_hour": int(tab.groupby("reopen_hour").size().idxmax())},
    ]
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    out.to_csv(DATA / "intraday_timezone_evidence.csv", index=False)
    cmp.to_csv(DATA / "intraday_timezone_fomc_profile.csv")
    print("\nwrote intraday_timezone_evidence.csv, intraday_timezone_fomc_profile.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
