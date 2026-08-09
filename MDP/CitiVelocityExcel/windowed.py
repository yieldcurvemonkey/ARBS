r"""Fetch a long intraday history at full resolution, by asking for it in pieces.

The granularity ladder
----------------------
``CVTSHIST`` does not serve the frequency you ask for. It serves the frequency it
thinks the *requested span* deserves, and it does so **silently** - the block
comes back looking exactly like a successful minute request, just with fewer
rows. Measured 2026-08-07 on ``RATES.OIS.*.PAR.10Y``, end fixed at 13:00 ET:

===========  ==========  =======================================
requested    span        spacing actually served
===========  ==========  =======================================
``MI01``     2d, 5d      1 minute
``MI01``     6d          1 minute
``MI01``     7d          **10 minutes**
``MI01``     8d - 60d    10 minutes
``MI01``     120d        60 minutes
``MI01``     365d        1440 minutes (daily, stamped midnight)
``HOURLY``   <= 120d     60 minutes
``HOURLY``   365d        1440 minutes
===========  ==========  =======================================

**The cliff is span, not age.** Holding the span at four days and walking the
window back - 3, 10, 18, 25, 40, 60, 90, 180, 365 days ago - returned true
1-minute data every single time. It is only ever hidden by asking for too much of
it at once. The 6d/7d boundary was re-measured on ``EUR_EUROSTR``,
``JPY_TONAR_LCH``, ``GBP_SONIA`` and ``CAD_CORRA``, at both "now" and "a year
ago": identical everywhere, so it is a property of the add-in rather than of any
one curve.

**Retention, bisected 2026-08-09** (``scripts/citivelo_snap_depth_probe.py``,
``--stage floor``), is far deeper than the "at least a year" this file used to
claim, and it is per curve:

==================  ===============  =====
curve               1-minute from    years
==================  ===============  =====
``EUR_EURIBOR``     2016-07-06        10.1
``JPY_TONAR``       2017-12-06         8.7
``EUR_EONIA``       2017-12-06         8.7
``USD_FEDFUND``     2018-09-05         7.9
``USD_SOFR``        2021-09-15         4.9
``EUR_EUROSTR``     2021-09-15         4.9
``JPY_TONAR_LCH``   2024-01-17         2.6
==================  ===============  =====

Below its 1-minute floor a curve may still serve *sparser* intraday data -
``USD_FEDFUND`` returns ~330 rows over four days at ~8-minute spacing back to
2017-12-06. That is real data, and a test which only asks "is the median spacing
one minute?" reports it as absent. ``CVSNAP`` reaches no deeper than any of this:
it reads the same store.

So a full-resolution backfill is not a retention problem, it is a chunking
problem, and this module is the chunker.

.. warning::
   The ladder is **not** monotone in the argument form. ``period="1W"`` served
   true 1-minute data (7,676 rows) while explicit bounds spanning 7.0 days served
   10-minute; ``period="1Y"`` at ``HOURLY`` served 6,252 hourly rows while
   explicit bounds over the same year served 261 daily ones. Do not "simplify"
   this module into a single 7-day-bounds request: that is the shape that
   degrades. Windows here are held strictly **under** the cliff.

Why one worksheet per window
----------------------------
A minute window of a full curve is ~5,300 rows x 45 columns. A few hundred of
them in one sheet is millions of live ``CvFunction_*`` cells and an Excel that
runs out of memory. Each window therefore gets its own sheet, named for its
bounds, which is dropped once the window has been read - the same shape as the
hand-built ``citi_usd_sofr_intraday_curve`` workbooks, which are one file per
Mon-Fri week.

Verification, not trust
-----------------------
Every window's spacing is **measured** against what was asked for. A window that
came back coarser than requested is either retried at half width or raised -
never returned as if it were what the caller wanted. Silently storing 10-minute
data in a minute-resolution series is precisely the failure this module exists
to prevent.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.frequencies import format_bound, normalise_frequency

__all__ = [
    "MAX_SPAN",
    "TARGET_SPACING",
    "DEFAULT_WINDOW",
    "WarmWindow",
    "WindowResult",
    "DownsampledWindowError",
    "window_bounds",
    "iter_windows",
    "fetch_windowed",
    "warm_windows",
]

_logger = logging.getLogger(__name__)

#: The widest span each frequency will still serve at its own resolution.
#: MEASURED, not documented - see the module docstring. The value is the last
#: span that worked, so callers must stay at or below it.
MAX_SPAN: Dict[str, datetime.timedelta] = {
    "MI01": datetime.timedelta(days=6),
    "MI10": datetime.timedelta(days=60),
    "HOURLY": datetime.timedelta(days=120),
}

#: The spacing a frequency is supposed to come back with, used to catch a
#: silently downsampled block.
TARGET_SPACING: Dict[str, datetime.timedelta] = {
    "MI01": datetime.timedelta(minutes=1),
    "MI10": datetime.timedelta(minutes=10),
    "HOURLY": datetime.timedelta(hours=1),
}

#: The window actually used by default. Under every measured cliff, and for
#: ``MI01`` it is a Mon-Fri week - so a window boundary falls in the weekend gap
#: rather than mid-session, which is what the hand-built workbooks do.
DEFAULT_WINDOW: Dict[str, datetime.timedelta] = {
    "MI01": datetime.timedelta(days=5),
    "MI10": datetime.timedelta(days=45),
    "HOURLY": datetime.timedelta(days=90),
}


class DownsampledWindowError(CitiVelocityError):
    """A window came back coarser than the frequency that was requested."""


@dataclass
class WindowResult:
    """One window's outcome, whether or not it produced data."""

    start: datetime.datetime
    end: datetime.datetime
    sheet: str = ""
    n_rows: int = 0
    n_tags: int = 0
    spacing: Optional[datetime.timedelta] = None
    seconds: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and self.n_rows > 0

    def __str__(self) -> str:  # pragma: no cover - operator sugar
        span = f"{self.start:%Y-%m-%d %H:%M} -> {self.end:%Y-%m-%d %H:%M}"
        if self.error:
            return f"{span}  FAILED: {self.error}"
        sp = f"{self.spacing.total_seconds() / 60:.0f}min" if self.spacing else "?"
        return f"{span}  {self.n_rows} rows x {self.n_tags} tags @ {sp}  {self.seconds:.1f}s"


def window_bounds(freq: str, window: Optional[datetime.timedelta] = None) -> datetime.timedelta:
    """The window width to use for ``freq``, validated against the measured cliff."""
    token = normalise_frequency(freq)
    default = DEFAULT_WINDOW.get(token)
    if default is None:
        raise CitiVelocityError(
            f"{token} is not an intraday frequency; windowing is for "
            f"{sorted(DEFAULT_WINDOW)} only."
        )
    if window is None:
        return default
    if window <= datetime.timedelta(0):
        raise CitiVelocityError(f"window must be positive, got {window}.")
    cap = MAX_SPAN[token]
    if window > cap:
        raise CitiVelocityError(
            f"A {window} window at {token} exceeds the measured {cap} cliff: the add-in "
            f"would silently serve coarser data. Use <= {cap}."
        )
    return window


def iter_windows(
    start: datetime.datetime,
    end: datetime.datetime,
    freq: str,
    window: Optional[datetime.timedelta] = None,
) -> Iterator[Tuple[datetime.datetime, datetime.datetime]]:
    """Split ``[start, end)`` into half-open windows no wider than the cliff.

    Half-open on purpose: adjacent windows sharing an endpoint would each return
    that minute and the concatenation would carry duplicates. One minute is
    subtracted from each window's upper bound because ``CVTSHIST``'s ``EndDate``
    is inclusive.
    """
    if end <= start:
        return
    width = window_bounds(freq, window)
    cursor = start
    while cursor < end:
        stop = min(cursor + width, end)
        yield cursor, stop
        cursor = stop


@dataclass(frozen=True)
class WarmWindow:
    """One request :func:`warm_windows` made, and what came back for it."""

    start: Any
    end: Any
    tags: Tuple[str, ...] = ()
    n_rows: int = 0

    @property
    def span(self) -> datetime.timedelta:
        return pd.Timestamp(self.end).to_pydatetime() - pd.Timestamp(self.start).to_pydatetime()

    def __str__(self) -> str:  # pragma: no cover - operator sugar
        return (
            f"{pd.Timestamp(self.start):%Y-%m-%d %H:%M} -> {pd.Timestamp(self.end):%Y-%m-%d %H:%M}  "
            f"{self.n_rows} rows x {len(self.tags)} tags"
        )


def warm_windows(
    quotes: Any,
    tags: Sequence[str],
    freq: str,
    start: Any,
    end: Any,
    *,
    window: Optional[datetime.timedelta] = None,
    price_point: str = "CLOSE",
    force_refresh: bool = False,
    newest_first: bool = True,
    failures: Optional[Dict[str, str]] = None,
) -> List[WarmWindow]:
    r"""Warm the TAG CACHE over ``[start, end]``, in requests held under the cliff.

    This is deliberately NOT :func:`fetch_windowed`. That one takes a connected
    ``client`` and pushes a worksheet per window, which is the right transport for
    a one-off read and the wrong one for anything that wants to be read twice: it
    **writes nothing to the tag cache**. Measured on the first run of
    ``scripts/citivelo_ust_universe_warm.py``, 349 bonds and 698 tags "succeeded"
    in 134 s and left *zero* ``MI01`` parquets on disk. ``CitiVeloQuotes.frame``
    goes through the cache, so this drives that instead - and on the same
    measurement it was 48 s and +170 MB against 134 s and +971 MB, 5.7x cheaper as
    well as actually cached.

    Driving ``frame`` means taking on the cliff obligation that ``fetch_windowed``
    would otherwise carry: ``CVTSHIST`` silently downsamples by requested SPAN,
    and the ``MI01`` threshold is measured at exactly 6 days - a 7-day request
    returns 10-minute rows in a block that looks identical. Every request here is
    therefore bounded by :data:`MAX_SPAN`, which is where that measurement lives.

    Parameters
    ----------
    quotes
        Anything with ``CitiVeloQuotes.frame``'s signature. A LIVE-capable reader:
        an offline one cannot warm anything, since a cache miss is what the warm
        exists to fill.
    window
        Request width. ``None`` takes :data:`MAX_SPAN` for the frequency - the
        widest span measured to still serve at full resolution, so the fewest
        round trips that are safe. Validated by :func:`window_bounds` either way,
        which refuses anything over the cliff.
    newest_first
        Walk back from ``end``. A warm that stops - at a memory ceiling, on a COM
        error, because someone closed Excel - then has the RECENT data, which is
        what a reader asks for first.
    failures
        Optional mapping the per-tag transport reasons are merged into, across
        every window. This is how a caller tells "the fetch did not happen" from
        "the market held nothing", which is the difference between retrying and
        widening.

    Returns
    -------
    list[WarmWindow]
        One entry per request actually issued, in the order issued, carrying the
        tags that served and the row count. A caller can assert on the bounds -
        which is the point of returning them rather than an ``int``.

    Notes
    -----
    A frequency with no measured cliff (``DAILY`` and coarser) is fetched in ONE
    request. Chunking it would spend round trips against a threshold that does
    not exist.
    """
    token = normalise_frequency(freq)
    wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
    if not wanted:
        return []

    cap = MAX_SPAN.get(token)
    if cap is None:
        spans: List[Tuple[Any, Any]] = [(start, end)]
    else:
        width = window_bounds(token, cap if window is None else window)
        lo = pd.Timestamp(start).to_pydatetime()
        hi = pd.Timestamp(end).to_pydatetime()
        spans = []
        cursor = hi
        while cursor > lo:
            w_start = max(lo, cursor - width)
            spans.append((w_start, cursor))
            if w_start <= lo:
                break
            cursor = w_start
        if not spans:
            # A degenerate range (end <= start) is still one request rather than
            # none: returning nothing here would report a warm that never ran as
            # a warm that found nothing.
            spans = [(lo, hi)]
        if not newest_first:
            spans.reverse()

    out: List[WarmWindow] = []
    for w_start, w_end in spans:
        reported: Dict[str, str] = {}
        frame = quotes.frame(
            list(wanted),
            token,
            start=w_start,
            end=w_end,
            price_point=price_point,
            force_refresh=force_refresh,
            failures=reported,
        )
        if failures is not None:
            failures.update(reported)
        served = tuple(str(c) for c in getattr(frame, "columns", ()))
        out.append(
            WarmWindow(start=w_start, end=w_end, tags=served, n_rows=int(len(frame)))
        )
    return out


def _spacing_of(index: pd.Index) -> Optional[datetime.timedelta]:
    if len(index) < 3:
        return None
    deltas = pd.Series(index).diff().dropna()
    if deltas.empty:
        return None
    return deltas.median().to_pytimedelta()


def _sheet_name(start: datetime.datetime, end: datetime.datetime) -> str:
    return f"{start:%Y%m%d%H%M}-{end:%Y%m%d%H%M}"


def fetch_windowed(
    client: Any,
    tags: Sequence[str],
    freq: str,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    window: Optional[datetime.timedelta] = None,
    price_point: str = "CLOSE",
    timeout: Optional[float] = None,
    on_window: Optional[Any] = None,
    strict_spacing: bool = True,
    keep_sheets: bool = False,
) -> Tuple[Dict[str, pd.Series], List[WindowResult]]:
    """Fetch ``[start, end)`` at ``freq`` in windows, and concatenate.

    Parameters
    ----------
    client
        A connected :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient`.
    on_window
        Called with each :class:`WindowResult` as it completes. This is the seam
        a resumable backfill writes through: a caller that persists per window
        loses at most one window when Excel goes away mid-run.
    strict_spacing
        Raise :class:`DownsampledWindowError` when a window comes back coarser
        than ``freq`` even after being retried at half width. Turning this off
        makes silently-coarse data reachable, so it defaults on.
    keep_sheets
        Leave each window's worksheet in place instead of dropping it. For
        debugging a single window; ruinous over a backfill.

    Returns
    -------
    (series, windows)
        ``series`` maps tag -> one ascending, de-duplicated float series across
        every window. ``windows`` is the per-window log, including failures.
    """
    token = normalise_frequency(freq)
    target = TARGET_SPACING.get(token)
    wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
    if not wanted:
        return {}, []

    collected: Dict[str, List[pd.Series]] = {t: [] for t in wanted}
    results: List[WindowResult] = []

    for w_start, w_stop in iter_windows(start, end, token, window):
        result = _fetch_one_window(
            client,
            wanted,
            token,
            w_start,
            w_stop,
            price_point=price_point,
            timeout=timeout,
            target=target,
            strict_spacing=strict_spacing,
            keep_sheets=keep_sheets,
            collected=collected,
        )
        results.append(result)
        if on_window is not None:
            on_window(result)

    out: Dict[str, pd.Series] = {}
    for tag, parts in collected.items():
        parts = [p for p in parts if p is not None and not p.empty]
        if not parts:
            continue
        merged = pd.concat(parts).sort_index()
        out[tag] = merged[~merged.index.duplicated(keep="last")]
    return out, results


def _fetch_one_window(
    client: Any,
    tags: List[str],
    token: str,
    w_start: datetime.datetime,
    w_stop: datetime.datetime,
    *,
    price_point: str,
    timeout: Optional[float],
    target: Optional[datetime.timedelta],
    strict_spacing: bool,
    keep_sheets: bool,
    collected: Dict[str, List[pd.Series]],
) -> WindowResult:
    """One window, on its own sheet, verified and then torn down."""
    import time as _time

    result = WindowResult(start=w_start, end=w_stop)
    # EndDate is inclusive; step back a minute so windows stay half-open.
    inclusive_end = w_stop - datetime.timedelta(minutes=1)
    started = _time.time()
    sheet_pushed = False
    try:
        result.sheet = client.push_window_sheet(_sheet_name(w_start, w_stop))
        sheet_pushed = True
        got = client.fetch_timeseries(
            tags,
            freq=token,
            start=format_bound(w_start, freq=token),
            end=format_bound(inclusive_end, freq=token),
            price_point=price_point,
            timeout=timeout,
        )
        if not got:
            result.error = "no data"
            return result

        sample = max(got.values(), key=len)
        spacing = _spacing_of(sample.index)
        result.spacing = spacing
        result.n_rows = len(sample)
        result.n_tags = len(got)

        if target is not None and spacing is not None and spacing > target:
            # Coarser than asked for. Retry once at half width before giving up:
            # the cliff is a span threshold, so a narrower window may clear it.
            half = (w_stop - w_start) / 2
            if half >= datetime.timedelta(hours=6):
                _logger.warning(
                    "%s..%s came back at %s spacing (wanted %s); retrying at half width.",
                    w_start, w_stop, spacing, target,
                )
                if sheet_pushed and not keep_sheets:
                    client.drop_window_sheet()
                    sheet_pushed = False
                sub_parts: Dict[str, List[pd.Series]] = {t: [] for t in tags}
                sub_ok = True
                for s2, e2 in ((w_start, w_start + half), (w_start + half, w_stop)):
                    sub = _fetch_one_window(
                        client, tags, token, s2, e2,
                        price_point=price_point, timeout=timeout, target=target,
                        strict_spacing=False, keep_sheets=keep_sheets, collected=sub_parts,
                    )
                    sub_ok = sub_ok and sub.ok and (
                        sub.spacing is None or sub.spacing <= target
                    )
                if sub_ok:
                    for tag, parts in sub_parts.items():
                        collected[tag].extend(parts)
                    result.spacing = target
                    result.n_rows = sum(len(p) for p in sub_parts.get(tags[0], []))
                    return result
            msg = (
                f"{w_start:%Y-%m-%d %H:%M}..{w_stop:%Y-%m-%d %H:%M} requested {token} "
                f"but was served {spacing} spacing. The add-in downsamples by span; "
                f"narrow the window."
            )
            if strict_spacing:
                raise DownsampledWindowError(msg)
            result.error = msg
            return result

        for tag, series in got.items():
            collected.setdefault(tag, []).append(series)
        return result
    except DownsampledWindowError:
        raise
    except Exception as exc:  # noqa: BLE001 - one bad window must not end a backfill
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    finally:
        result.seconds = _time.time() - started
        if sheet_pushed and not keep_sheets:
            try:
                client.drop_window_sheet()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("dropping window sheet failed: %s", exc)
