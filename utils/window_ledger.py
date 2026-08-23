# ABOUTME: Inclusive date-interval algebra for resume ledgers that record the
# ABOUTME: windows a warm actually fetched, so a moving end date costs only its tail.
"""What a warm has ALREADY fetched, as a set of date windows.

The problem this exists for
---------------------------
A resume key of the form ``f"{start}|{end}|{values}"`` is correct and expensive.
Correct, because widening the window or asking for a value that was not fetched
last time must not count as done - otherwise a resumed run silently skips work
it never did. Expensive, because a nightly warm passes a window ending at the
last settled session, so ``end`` moves every night, so the key changes every
night, so the whole universe looks un-warmed on every run. Measured on
``scripts/citivelo_ust_universe_warm.py``: 877 bonds re-entering a 30-day window
nightly, part of 2,600-3,500 s a night.

The fix is to separate the WINDOW from the WORK. Record, per unit of work, the
windows actually fetched; a night's work is then the requested window minus what
is banked, and a moving ``end`` costs only the new tail.

Why a ledger of windows and not a coverage interval
---------------------------------------------------
``CitiVeloTagCache.coverage()`` knows only ``first``, ``last`` and ``n_rows`` -
a single interval. It cannot see an INTERIOR hole, and a hole does not raise:
the as-of search serves the previous print and a whole session silently inherits
the day before. So "just ask the cache what it covers" reintroduces a known
data-loss bug. What is recorded here is the set of windows a fetch actually
completed, which is a record of work rather than an inference from data - and an
interval that was never fetched is simply not in it.

Intervals are INCLUSIVE on both ends and merged when they touch: ``[a, b]`` and
``[b + 1 day, c]`` are one window ``[a, c]``, because a day is the unit and
there is no gap between consecutive days.
"""

from __future__ import annotations

import datetime
from typing import Iterable, List, Optional, Sequence, Tuple

Interval = Tuple[datetime.date, datetime.date]
DAY = datetime.timedelta(days=1)


def _as_date(value) -> datetime.date:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


def normalize(intervals: Iterable[Sequence]) -> List[Interval]:
    """Sorted, merged, inclusive. Touching intervals become one."""
    parsed: List[Interval] = []
    for item in intervals or ():
        if item is None:
            continue
        try:
            lo, hi = _as_date(item[0]), _as_date(item[1])
        except (TypeError, ValueError, IndexError, KeyError):
            # A torn or hand-edited ledger entry means "not banked", never a
            # crash: the cost of ignoring it is re-fetching that window.
            continue
        if hi < lo:
            lo, hi = hi, lo
        parsed.append((lo, hi))
    parsed.sort()

    merged: List[Interval] = []
    for lo, hi in parsed:
        if merged and lo <= merged[-1][1] + DAY:
            if hi > merged[-1][1]:
                merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return merged


def add(intervals: Iterable[Sequence], lo, hi) -> List[Interval]:
    """``intervals`` with ``[lo, hi]`` banked as well."""
    return normalize(list(intervals or ()) + [(_as_date(lo), _as_date(hi))])


def subtract(lo, hi, banked: Iterable[Sequence]) -> List[Interval]:
    """The parts of ``[lo, hi]`` that ``banked`` does NOT already cover."""
    lo, hi = _as_date(lo), _as_date(hi)
    if hi < lo:
        return []
    gaps: List[Interval] = []
    cursor = lo
    for b_lo, b_hi in normalize(banked):
        if b_hi < cursor:
            continue
        if b_lo > hi:
            break
        if b_lo > cursor:
            gaps.append((cursor, min(hi, b_lo - DAY)))
        cursor = max(cursor, b_hi + DAY)
        if cursor > hi:
            return gaps
    if cursor <= hi:
        gaps.append((cursor, hi))
    return gaps


def covers(lo, hi, banked: Iterable[Sequence]) -> bool:
    """Whether ``banked`` already holds the whole of ``[lo, hi]``."""
    return not subtract(lo, hi, banked)


def span(intervals: Iterable[Sequence]) -> Optional[Interval]:
    """The single window enclosing ``intervals``, or ``None`` when empty.

    A fetch takes one ``start``/``end`` pair, so a bond needing two separated
    gaps is asked for the range that contains both. That over-fetches the
    covered middle; it never under-fetches, which is the direction that matters.
    """
    merged = normalize(intervals)
    return (merged[0][0], merged[-1][1]) if merged else None


def to_json(intervals: Iterable[Sequence]) -> List[List[str]]:
    """``[["2026-08-01", "2026-08-21"], ...]`` - stable, diffable, sorted."""
    return [[lo.isoformat(), hi.isoformat()] for lo, hi in normalize(intervals)]


def total_days(intervals: Iterable[Sequence]) -> int:
    """How many days are banked. For logging what a run actually saved."""
    return sum((hi - lo).days + 1 for lo, hi in normalize(intervals))
