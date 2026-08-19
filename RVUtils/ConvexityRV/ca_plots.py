"""Gap-honest plotting helpers for the convexity-adjustment series.

WHY THIS MODULE EXISTS
======================
A rendered-trace audit on 2026-08-19 found **152 traces across 11 executed
notebooks drawing a straight line across a gap longer than 15 days**, the worst
of them a **553-day** bridge. The CA charts specifically drew a 502-day line from
2025-03-12 to 2026-07-27, and one notebook *printed*, above the chart:

    "The series is NOT interpolated across the 2023+ gap; every chart below
     uses connectgaps=False so the hole is visible."

That statement was false, and the reason it was false is the point of this
module: **``connectgaps=False`` only breaks a line where ``y`` is null.** The
frames handed to plotly were built by an inner join on observed dates, so they
carried **zero** NaN rows for the flag to act on. The flag was correct, present,
and completely inert. Grepping for it -- which an earlier pass did -- therefore
cannot answer the question either.

The fix is one line per series, and it is upstream of plotly:

    fig.add_trace(go.Scatter(**line(bday_reindex(s), name="Blues CA (bp)")))

:func:`bday_reindex` puts the series back on a business-day grid so the holes
become NaN rows, and :func:`line` sets ``connectgaps=False`` so plotly then has
something to break on. Neither works without the other.

WHAT AN HONEST GAP LOOKS LIKE
=============================
Three things, all cheap:

1. **The hole is a hole.** No segment is drawn across it.
2. **The reader is told how sparse the series is.** :func:`coverage_note`
   returns "503 obs / 1,451 business days (34.7%)" for a subtitle, because a
   dotted line and a solid line look identical at a glance and only the count
   distinguishes 100% coverage from a third.
3. **The gaps are enumerated.** :func:`gap_table` lists every hole longer than a
   threshold with its span, so a reader can check whether the thing they are
   about to regress on is a series or three series in a trench coat.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional, Sequence, Union

import numpy as np
import pandas as pd

__all__ = [
    "bday_reindex",
    "gap_table",
    "coverage_note",
    "line",
    "GAP_DAYS",
]

#: A gap longer than this many calendar days is a hole worth drawing as one.
#: Fifteen days clears Christmas-New Year and any single holiday week, and is the
#: same threshold ``trim_to_contiguous_run`` uses, so the two agree about what a
#: break is.
GAP_DAYS = 15


def bday_reindex(
    obj: Union[pd.Series, pd.DataFrame],
    *,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
    freq: str = "B",
) -> Union[pd.Series, pd.DataFrame]:
    """Put a date-indexed series/frame back on a business-day grid, NaN in the holes.

    This is the half of the fix that ``connectgaps=False`` cannot do for itself.
    An observed-dates-only frame has no null rows, so the flag has nothing to
    break the line on and plotly joins across the hole -- correctly, by its own
    rules, and wrongly by ours.

    Measured on the Blues CA series: 503 observations over 1,451 business days.
    Reindexing produces **948 NaN rows**, which is exactly the material the flag
    needs. Reindexing is not resampling and never invents a value: every original
    observation keeps its own date and value, and every unobserved business day
    becomes ``NaN``.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(obj.index)).sort_values()
    if not len(idx):
        return obj
    lo = pd.Timestamp(start) if start is not None else idx.min()
    hi = pd.Timestamp(end) if end is not None else idx.max()
    grid = pd.bdate_range(lo, hi, freq=freq)
    out = obj.copy()
    out.index = idx if isinstance(obj.index, pd.DatetimeIndex) else pd.to_datetime(obj.index)
    return out.sort_index().reindex(grid)


def gap_table(index: Sequence, *, max_gap_days: int = GAP_DAYS) -> pd.DataFrame:
    """Every hole longer than *max_gap_days*, with the dates that bracket it.

    Report this next to any regression or correlation run on a sparse series. A
    126-day rolling correlation whose window sits either side of a 502-day hole
    is not a 126-day correlation, and no amount of ``connectgaps`` reveals that.
    """
    idx = pd.DatetimeIndex(pd.to_datetime(pd.Index(index))).dropna().sort_values()
    if len(idx) < 2:
        return pd.DataFrame(columns=["from", "to", "gap_days"])
    d = idx.to_series().diff().dt.days
    hit = d[d > max_gap_days]
    return pd.DataFrame({
        "from": [idx[idx.get_loc(t) - 1].date() for t in hit.index],
        "to": [t.date() for t in hit.index],
        "gap_days": hit.astype(int).to_numpy(),
    }).sort_values("gap_days", ascending=False).reset_index(drop=True)


def coverage_note(obj: Union[pd.Series, pd.DataFrame], *,
                  start: Optional[datetime.date] = None,
                  end: Optional[datetime.date] = None) -> str:
    """``"503 obs / 1,451 business days (34.7%)"`` -- for a chart subtitle.

    A sparse line and a dense line look identical once drawn. The observation
    count is the only thing on the chart that distinguishes them, so it belongs
    on every chart of a series that is not complete.
    """
    s = obj if isinstance(obj, pd.Series) else obj.iloc[:, 0]
    idx = pd.DatetimeIndex(pd.to_datetime(s.dropna().index))
    if not len(idx):
        return "no observations"
    lo = pd.Timestamp(start) if start is not None else idx.min()
    hi = pd.Timestamp(end) if end is not None else idx.max()
    grid = pd.bdate_range(lo, hi)
    n, m = int(s.notna().sum()), max(1, len(grid))
    return f"{n:,} obs / {m:,} business days ({100.0 * n / m:.1f}%)"


def line(series: pd.Series, *, name: str, **kwargs: Any) -> Dict[str, Any]:
    """``go.Scatter`` kwargs for a gap-honest line.

    ``connectgaps=False`` is set here so no call site can forget it, and
    ``mode="lines"`` so a hole reads as absence rather than as a flat run of
    markers. Pass the series through :func:`bday_reindex` first or the flag has
    nothing to act on -- that is the whole lesson of this module.
    """
    s = series.dropna() if series.index.has_duplicates else series
    out: Dict[str, Any] = {
        "x": list(s.index), "y": list(np.asarray(s.to_numpy(), dtype=float)),
        "name": name, "mode": "lines", "connectgaps": False,
    }
    out.update(kwargs)
    return out
