r"""Reading the warmed Citi intraday UST layer correctly, which is not the obvious way.

The layer
---------
``MDP/CitiVelocityExcel``'s tag cache holds, for the 97-bond TLT 20-31y universe
in ``notebooks/backtests/etf_rebalance/_data/intraday_universe.csv``:

============  =========================  ==========================  ============
frequency     values                     span                        cells
============  =========================  ==========================  ============
``HOURLY``    ``YIELD``, ``PRICE``       2019-11-17 .. now           6,436,709
``HOURLY``    ``ASS_SOFR``               2025-11-22 .. now             464,577
``MI01``      ``YIELD``, ``PRICE``       month-turn blocks, 2021-    (see census)
============  =========================  ==========================  ============

All of it reads offline: ``CitiVeloQuotes(offline=True)`` or ``CitiVelocityMDP(
offline=True)`` serve it with no Excel and no add-in session.

The trap, which is measured and not a guess
--------------------------------------------
**Citi's HOURLY bars are START-STAMPED and carry their own close.** The value at
stamp ``H`` is the mark at ``H:59``, verified against the MI01 minute tape on
3,804 overlapping bond-day-hours: exact equality on **100.0%** of them, median
absolute difference 0.0000 bp, at stamps 10, 13, 14, 15 and 16 alike
(``scripts/etf_stamp_convention2.py``). It is an identity, not a correlation.

So a caller who asks the hourly series for "15:00" and reads it as a 15:00 New
York cash mark is reading the **16:00** mark, and a study of the 15:00-to-16:00
seam built that way measures the 16:00-to-17:00 hour instead. :func:`ny_stamp`
exists so that mistake has to be made deliberately.

Four independent readings put the stamps on **America/New_York**:
FOMC-day excess activity peaks at stamp 14 (statement 14:00 New York, ratio
2.81x); unconditional activity peaks at stamp 8 (the 08:30 release); the weekly
reopen sits at stamp 18 on Sunday (the 18:00 New York restart); and the request
bound is read as UTC, so a window ending ``2026-06-20 00:00`` returns its last
row at ``20:00`` in EDT and ``19:00`` in EST - an offset that tracks New York's
own DST, which no market-behaviour argument is needed to interpret.

Known bad cells
---------------
Nine of 3,218,304 hourly ``YIELD`` cells are impossible (0.00028%), on two dates
(2025-01-14 and 2026-05-12) and entirely in the overnight stamps 01:00-07:00 New
York. **None** is in the New York session and none is at stamp 14 or 15.
``MDP.CitiVelocityExcel.bonds.sanity`` passes all nine - its bands are -5..25%
for a yield, calibrated on the whole Treasury curve - so :func:`drop_impossible`
applies a long-end-specific gate on top.
"""

from __future__ import annotations

import datetime
import pathlib
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

__all__ = [
    "UNIVERSE_CSV",
    "LONG_END_YIELD_BAND",
    "ny_stamp",
    "universe",
    "hourly_frame",
    "ny_marks",
    "drop_impossible",
]

UNIVERSE_CSV = (pathlib.Path(__file__).resolve().parents[2]
                / "notebooks" / "backtests" / "etf_rebalance" / "_data"
                / "intraday_universe.csv")

#: A possibility gate for a 20-31y US Treasury yield in percent. Wider than any
#: real long-end print since 1990 (roughly 0.7% to 9%) and far tighter than
#: ``sanity.US_TREASURY_BANDS``, which has to cover the whole curve and therefore
#: admits the nine corrupt overnight cells this layer actually contains.
LONG_END_YIELD_BAND = (0.20, 12.0)


def ny_stamp(clock_hour: int) -> int:
    """The HOURLY stamp that carries the New York mark at ``clock_hour``:00.

    >>> ny_stamp(16)      # the 16:00 NAV strike lives on the bar stamped 15:00
    15
    >>> ny_stamp(15)      # the 15:00 cash mark lives on the bar stamped 14:00
    14

    Raises
    ------
    ValueError
        For hour 0, whose mark would sit on the previous day's stamp 23. That is
        a real answer but a different day's row, and silently returning 23 is how
        a caller ends up off by one day as well as one hour.
    """
    hour = int(clock_hour)
    if not 1 <= hour <= 23:
        raise ValueError(
            f"clock_hour must be 1..23; {clock_hour} would need the previous day's "
            "stamp 23 and the caller must index that day deliberately."
        )
    return hour - 1


def universe(path: Optional[pathlib.Path] = None) -> pd.DataFrame:
    """The 97-bond universe, with ``maturity_date`` parsed."""
    df = pd.read_csv(path or UNIVERSE_CSV)
    df["maturity_date"] = pd.to_datetime(df["maturity_date"])
    if "issue_date" in df.columns:
        df["issue_date"] = pd.to_datetime(df["issue_date"], errors="coerce")
    return df


def hourly_frame(value: str = "YIELD", isins: Optional[Sequence[str]] = None,
                 start=None, end=None) -> pd.DataFrame:
    """The whole hourly panel for one value, offline, columns named by ISIN."""
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    ids = list(isins) if isins is not None else list(universe()["isin"].astype(str))
    q = CitiVeloQuotes(offline=True)
    frame = q.frame([f"RATES.BOND.{i}.{value}" for i in ids], "HOURLY",
                    start=start, end=end)
    frame.columns = [str(c).split(".")[2] for c in frame.columns]
    return frame


def ny_marks(frame: pd.DataFrame, clock_hour: int) -> pd.DataFrame:
    """One row per calendar date carrying the New York mark at ``clock_hour``:00.

    Uses :func:`ny_stamp`, so the returned 16:00 frame really is the 16:00 mark.
    """
    stamp = ny_stamp(clock_hour)
    idx = pd.Series(frame.index)
    sub = frame[(idx.dt.hour == stamp).to_numpy()]
    out = sub.copy()
    out.index = pd.DatetimeIndex(pd.Series(sub.index).dt.normalize())
    return out[~out.index.duplicated(keep="last")]


def drop_impossible(frame: pd.DataFrame, value: str = "YIELD") -> pd.DataFrame:
    """NaN out cells that cannot be the quantity they are labelled as.

    Only ``YIELD`` has a band here. ``PRICE`` is covered adequately by
    ``sanity.US_TREASURY_BANDS`` (nothing in this layer trips it and nothing in
    it is implausible), and ``ASS_SOFR`` has no calibrated band anywhere in the
    repo - its one bad cell shares a stamp with a bad ``YIELD``, so screening the
    yield and aligning on the surviving index removes it too.
    """
    if str(value).upper() != "YIELD":
        return frame
    lo, hi = LONG_END_YIELD_BAND
    return frame.mask((frame < lo) | (frame > hi))
