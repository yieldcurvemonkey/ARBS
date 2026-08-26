"""Probe 1: what does fomc_decision_dates() actually return -- decision dates or
effective dates? The Fed decides on a Wednesday and the new target range is
effective the following day, so a day-of-week histogram settles it.

Everything downstream (is_fomc_day, is_blackout, the |d_rate_bp| known-answer
check) is off by one business day if this is wrong.
"""
from __future__ import annotations

import collections
import datetime as dt
import os
import sys

os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")
sys.path.append(r"C:\Users\chris\clee\ARBS")
sys.path.append(r"C:\Users\chris\clee\ARBS\notebooks\backtests\intraday_fed_hawk_dove")

import pandas as pd  # noqa: E402

sys.stdout.reconfigure(line_buffering=True)

from fomc_extras import fomc_decision_dates  # noqa: E402

DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def main() -> None:
    ds = fomc_decision_dates()
    print(f"n dates = {len(ds)}   {ds[0]} .. {ds[-1]}")

    hist = collections.Counter(DOW[d.weekday()] for d in ds)
    print("\nday-of-week histogram of the RAW dates:")
    for k in DOW:
        print(f"  {k}: {hist.get(k, 0)}")

    # Known answers. The 10 Dec 2025 cut is named in FED_SPEAKER_QUARTERLY_LABELS.md
    # and is a WEDNESDAY. The 29 Jul 2026 hold with three hawkish dissents is also
    # named there and is a WEDNESDAY. If the raw dates land on the Thursday after
    # each, the map is serving EFFECTIVE dates.
    known_decisions = [dt.date(2025, 12, 10), dt.date(2026, 7, 29),
                       dt.date(2026, 4, 29), dt.date(2026, 3, 18),
                       dt.date(2024, 9, 18), dt.date(2022, 3, 16)]
    print("\nknown DECISION dates vs the served dates around them:")
    for kd in known_decisions:
        near = [d for d in ds if abs((d - kd).days) <= 4]
        print(f"  {kd} ({DOW[kd.weekday()]}): served nearby = "
              f"{[(str(d), DOW[d.weekday()], (d - kd).days) for d in near]}")

    print("\nlast 14 served dates:")
    for d in ds[-14:]:
        print(f"  {d}  {DOW[d.weekday()]}")

    print("\nfirst 6 served dates:")
    for d in ds[:6]:
        print(f"  {d}  {DOW[d.weekday()]}")

    # Gap structure: FOMC meets 8x/year, so consecutive gaps should be ~40-60 days
    g = pd.Series([(b - a).days for a, b in zip(ds[:-1], ds[1:])])
    print(f"\ngap between consecutive dates: median {g.median():.0f}d  "
          f"min {g.min()}d  max {g.max()}d   n<20d = {(g < 20).sum()}")


if __name__ == "__main__":
    main()
