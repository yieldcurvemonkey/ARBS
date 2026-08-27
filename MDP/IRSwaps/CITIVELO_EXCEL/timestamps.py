r"""The timezone contract for the Citi Velocity Excel curve source.

What the wire zone actually is, and how that was established
------------------------------------------------------------
**Citi Velocity timestamps are America/New_York wall clock, and they observe US
daylight saving.** Measured against the live add-in on 2026-08-07; the evidence is
in ``MDP/CitiVelocityExcel/harvest/live_curve_modes/``:

1. ``CVNOW()`` returned ``2026-08-07 10:47:00`` against a wall clock of
   ``10:47:01`` ET and ``14:47:01`` UTC - a -4:00 offset from UTC, which is EDT.
2. The decisive one, because (1) alone cannot separate "New York" from "whatever
   this machine's zone is": **``EUR_EUROSTR``'s trading session is fixed in
   Frankfurt but its stamps move with US DST.** Hourly stamps around the
   2026-03-08 US spring-forward:

   =============  ==================  =====================
   date           stamp hours seen    that window in CET
   =============  ==================  =====================
   2026-03-05/06  02:00 .. 13:59      08:00 .. 19:59
   2026-03-09/11  03:00 .. 14:59      08:00 .. 19:59
   =============  ==================  =====================

   The session is the same 08:00-20:00 CET on both sides; only the ET rendering
   shifts, and it shifts on the **US** transition (2026-03-08), not the European
   one (2026-03-29). A fixed UTC offset cannot produce that, and neither can
   London time.
3. Corroborated on three more currencies whose sessions are unambiguous in their
   own zone. On 2026-08-06/07, reading the stamps as ET gives exactly 08:00-20:00
   local everywhere: ``JPY_TONAR`` 19:00-06:59 ET = 08:00-19:59 JST,
   ``AUD_AONIA`` 18:00-05:59 ET = 08:00-19:59 AEST, ``GBP_SONIA`` 03:00-14:59 ET
   = 08:00-19:59 London.
4. The **request** side is the same zone: a ``CVSNAP`` at ``2026-08-06 10:30``
   returned ``4.23287``, which is exactly the ``MI01`` row stamped 10:30.

**What is still inferred.** This machine is itself in America/New_York, so an
add-in that formats in *machine-local* time is observationally identical to one
that formats in *exchange* time. Evidence (2) rules out UTC and London but not
machine-local. The zone is therefore a named, overridable constant rather than a
hardcode: set ``CITIVELO_EXCEL_WIRE_TZ`` if this is ever run from another zone
and the sessions stop lining up.

The contract at the boundary
----------------------------
* tz-aware datetimes are converted to the wire zone and sent as naive
  ``yyyyMMddHHmm`` - which is the only form ``CVTSHIST`` accepts, and which was
  measured to be honoured (a 10:00-11:00 request returned exactly 61 rows).
* naive datetimes are **localised to the wire zone with a warning**, once per
  process. Rejecting them was the alternative; localising matches what
  ``IRSwapsMDP._load_citivelo_curve_store_point`` and the ERIS live path already
  do for this repo's other intraday sources, so a caller moving between them does
  not silently change meaning. ``strict=True`` (or ``CITIVELO_EXCEL_STRICT_TZ=1``)
  turns the warning into a raise.
* every timestamp handed back is **tz-aware in the wire zone**. A naive stamp is
  what makes a one-hour error look like a real market move, and the repo has that
  failure recorded.
"""

from __future__ import annotations

import datetime
import logging
import os
import warnings
from dataclasses import dataclass
from typing import Any, Literal, Optional, Union

import pandas as pd

try:  # stdlib on 3.9+; the repo also has pytz, but this needs no dependency
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - only on ancient interpreters
    from backports.zoneinfo import ZoneInfo  # type: ignore

__all__ = [
    "DEFAULT_WIRE_TZ",
    "EOD_SNAP_TIME",
    "RequestMode",
    "ResolvedRequest",
    "wire_timezone",
    "to_wire_naive",
    "from_wire_naive",
    "resolve_request",
    "NaiveTimestampError",
]

_logger = logging.getLogger(__name__)

#: The zone Citi Velocity's timestamps are in. See the module docstring for how
#: this was measured and for the one thing that remains inferred.
DEFAULT_WIRE_TZ = "America/New_York"

#: The wall-clock instant, in the wire zone, that Citi's ``DAILY`` series is struck
#: at. A daily row is *stamped at midnight* by the add-in, so this cannot be read
#: off the wire and had to be measured against Citi's own minute series.
#:
#: **Measured 2026-08-26, two independent ways, both pointing at 15:00 New York:**
#:
#: * quote level - pooled ``RMSE(DAILY - MI01(t))`` over minutes of day for the
#:   2Y/5Y/10Y/30Y ``USD_SOFR`` par tags, 18 days: 0.146 bp at 15:00 against 0.163
#:   at 14:59, 0.170 at 15:01, 0.624 at 14:00, 0.701 at 16:00, 0.818 at 17:00;
#: * curve level - the warmed EOD curve against the warmed 10-minute curves in
#:   zero-rate bp, 40 EST days 2023-01-03..2026-01-02 and 40 EDT days
#:   2023-03-13..2026-06-22: median RMSE minimises in the **14:40-15:20 ET** band in
#:   BOTH regimes (EST 0.591 at 14:50 / 0.614 at 15:00 vs 1.041 at 17:00; EDT 0.444
#:   / 0.464 vs 0.821). The band does **not** move with US DST, so the snap runs on
#:   a New York clock rather than a fixed UTC offset, and it is stable back to 2023.
#:
#: This matters because it is one leg of a difference: the SR3 convexity adjustment
#: marks a futures settle (CME strikes it 13:59:30-14:00:00 CT = 15:00 ET) against
#: this curve, and the whole quantity is 1.3-6.8 bp. Before this constant existed
#: the EOD curve was stamped 17:00 - not used for pricing, but two hours of drift
#: (~0.7 bp of zero rate) away from what the number actually was.
EOD_SNAP_TIME = datetime.time(15, 0)

RequestMode = Literal["live", "intraday", "eod"]

TimestampLike = Union[datetime.date, datetime.datetime, pd.Timestamp, str]

_WARNED_NAIVE = False


class NaiveTimestampError(ValueError):
    """Raised for a naive datetime when strict timezone handling is on."""


def wire_timezone() -> ZoneInfo:
    """The wire zone, overridable with ``CITIVELO_EXCEL_WIRE_TZ``."""
    return ZoneInfo(os.environ.get("CITIVELO_EXCEL_WIRE_TZ", DEFAULT_WIRE_TZ))


def _strict_default() -> bool:
    return str(os.environ.get("CITIVELO_EXCEL_STRICT_TZ", "")).strip().lower() in {"1", "true", "yes"}


def _warn_naive(value: Any) -> None:
    """One warning per process: a per-call warning in a bulk build is noise."""
    global _WARNED_NAIVE
    if _WARNED_NAIVE:
        return
    _WARNED_NAIVE = True
    warnings.warn(
        f"citivelo_excel: naive timestamp {value!r} was localised to "
        f"{wire_timezone().key}, which is the zone Citi Velocity's own stamps are in "
        "(measured 2026-08-07). Pass a tz-aware datetime to say so explicitly, or set "
        "CITIVELO_EXCEL_STRICT_TZ=1 to make this an error. Further naive timestamps "
        "this process will not be warned about.",
        stacklevel=3,
    )


def to_wire_naive(
    timestamp: TimestampLike, *, strict: Optional[bool] = None
) -> datetime.datetime:
    """A tz-aware (or naive) instant as the naive wall clock the add-in expects.

    Parameters
    ----------
    timestamp
        A ``datetime``, ``pandas.Timestamp`` or ISO string. Aware values are
        converted into the wire zone; naive values are assumed already to be in
        it.
    strict
        Raise :class:`NaiveTimestampError` on a naive input instead of warning.
        Defaults to ``CITIVELO_EXCEL_STRICT_TZ``.

    Notes
    -----
    Converting an aware instant into the wire zone can land inside a DST gap
    (02:00-03:00 on a US spring-forward date), where the resulting wall clock
    never existed and Citi has no rows. That is a genuine empty result, not an
    error, and the caller sees it as such.
    """
    strict = _strict_default() if strict is None else bool(strict)
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is None:
        if strict:
            raise NaiveTimestampError(
                f"citivelo_excel: refusing a naive timestamp {timestamp!r} under strict timezone "
                f"handling. Citi Velocity's stamps are {wire_timezone().key} wall clock; pass "
                "e.g. datetime(2026, 8, 6, 10, 30, tzinfo=ZoneInfo('America/New_York'))."
            )
        _warn_naive(timestamp)
        return ts.to_pydatetime()
    return ts.tz_convert(wire_timezone()).tz_localize(None).to_pydatetime()


def from_wire_naive(timestamp: TimestampLike) -> datetime.datetime:
    """A naive wire stamp as a tz-aware datetime in the wire zone.

    Every timestamp this source hands back goes through here, so the two DST
    edge cases have to be decided rather than left to raise. A bare
    ``Timestamp.tz_localize`` does **not** quietly pick a fold - it raises
    ``AmbiguousTimeError`` on the repeated hour and ``NonExistentTimeError`` on
    the skipped one - which would turn one snapshot a year into an unhandled
    crash inside a curve build.

    ``ambiguous=True``
        The repeated 01:00-01:59 ET hour on a US fall-back resolves to the FIRST
        occurrence (still on daylight time). The add-in publishes no fold
        information, so no better answer exists; the two readings are an hour
        apart on a Sunday when none of the twenty curves trades.
    ``nonexistent="shift_forward"``
        02:00-02:59 ET on a US spring-forward never happened, so no stamp can
        carry it - but a *request* converted from another zone can land there, and
        shifting to 03:00 asks for the first instant that does exist.
    """
    ts = pd.Timestamp(timestamp)
    if ts.tzinfo is not None:
        return ts.tz_convert(wire_timezone()).to_pydatetime()
    return ts.tz_localize(
        wire_timezone(), ambiguous=True, nonexistent="shift_forward"
    ).to_pydatetime()


@dataclass(frozen=True)
class ResolvedRequest:
    """What a caller's ``timestamp`` argument means, decided once and explicitly.

    Attributes
    ----------
    mode
        ``live``, ``intraday`` or ``eod``.
    requested
        The caller's original argument, untouched, for error messages.
    wire_instant
        For ``intraday``: the naive wire-zone wall clock to ask the add-in for.
        ``None`` in the other two modes.
    eod_date
        For ``eod``: the calendar date whose close is wanted. ``None`` otherwise.
    """

    mode: RequestMode
    requested: Any
    wire_instant: Optional[datetime.datetime] = None
    eod_date: Optional[datetime.date] = None

    def describe(self) -> str:
        if self.mode == "live":
            return "live"
        if self.mode == "eod":
            return f"eod {self.eod_date}"
        return f"intraday {self.wire_instant:%Y-%m-%d %H:%M} {wire_timezone().key}"


def resolve_request(
    timestamp: Union[TimestampLike, Literal["live"], None],
    *,
    strict: Optional[bool] = None,
) -> ResolvedRequest:
    """Classify a ``timestamp`` argument into one of the three modes.

    The dispatch, in order, and why each rule is where it is:

    1. ``"live"`` (or ``None``) -> **live**.
    2. a bare ``datetime.date`` -> **eod** for that date. Checked by excluding
       ``datetime.datetime`` explicitly, because ``datetime`` subclasses ``date``
       and a plain ``isinstance(x, date)`` test would swallow every intraday
       request.
    3. anything else datetime-like at **exactly midnight** -> **eod**. This
       includes ``pandas.Timestamp("2026-08-06")``, which is the common accidental
       spelling of "that day" - and note ``pandas.Timestamp`` is itself a
       ``datetime`` subclass, so an ``isinstance(x, datetime)`` branch placed
       first would make this rule unreachable. Midnight-as-EOD is also the answer
       that round-trips: the add-in stamps its own ``DAILY`` rows at midnight.
    4. anything else datetime-like -> **intraday** at that instant.

    To request an intraday curve at exactly midnight - which is a real instant, if
    an illiquid one - use the fetcher directly, or ask for ``00:00:01``. The
    ambiguity is inherent in overloading one argument across three modes; this
    resolves it toward the reading that is almost always meant and says so.
    """
    if timestamp is None or (isinstance(timestamp, str) and timestamp.strip().lower() == "live"):
        return ResolvedRequest(mode="live", requested=timestamp)

    if isinstance(timestamp, datetime.date) and not isinstance(timestamp, datetime.datetime):
        return ResolvedRequest(mode="eod", requested=timestamp, eod_date=timestamp)

    ts = pd.Timestamp(timestamp)
    if (ts.hour, ts.minute, ts.second, ts.microsecond) == (0, 0, 0, 0):
        return ResolvedRequest(mode="eod", requested=timestamp, eod_date=ts.date())

    return ResolvedRequest(
        mode="intraday",
        requested=timestamp,
        wire_instant=to_wire_naive(ts, strict=strict),
    )
