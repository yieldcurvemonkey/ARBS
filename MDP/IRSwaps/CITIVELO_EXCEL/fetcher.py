r"""Fetch one Citi Velocity par grid in EOD, intraday or live mode, and strip it.

Which ``CV*`` function backs each mode, and why
-----------------------------------------------
All three modes go through ``CVTSHIST``. That is a measurement, not a default -
the alternatives were probed live on 2026-08-07 (evidence in
``MDP/CitiVelocityExcel/harvest/live_curve_modes/``):

======================  ===========================================================
primitive               what it actually does
======================  ===========================================================
``CVTSHIST`` ``DAILY``  the EOD grid; 44 tags in one call; explicit ``yyyyMMdd``
                        bounds honoured
``CVTSHIST`` ``MI01``   one-minute history; explicit ``yyyyMMddHHmm`` bounds
                        **measured honoured** (a 10:00-11:00 request returned
                        exactly 61 rows); newest row was 1 minute old at 10:47 ET
``CVLATEST``            serves, but returns a bare column of values with **no
                        timestamp** and only 5 decimal places. Rejected for live:
                        without a stamp, a curve that stopped ticking four hours
                        ago is indistinguishable from one that ticked a second ago
``CVSNAP``              serves the right value at a point - cross-checked to the
                        digit against the ``MI01`` row at the same minute - but
                        also carries **no timestamp**, and it is one call per
                        instant rather than a window you can index into
``CVSTREAM``            a genuinely live RTD-style cell: full double precision
                        (``4.23909408453934`` where ``CVLATEST`` gives
                        ``4.23919``) and the value **changed between two reads 20 s
                        apart**. Right primitive for a polling daemon, wrong one
                        here: it is one scalar per call (44 calls per curve), it
                        carries no stamp, and 44 live RTD regions that must then be
                        torn down is exactly the add-in's second crash trigger
======================  ===========================================================

So ``MI01`` backs both intraday and live, and it is the only primitive that
returns *when* a quote is from - which is what makes staleness detectable instead
of silent. See :class:`~MDP.IRSwaps.CITIVELO_EXCEL.timestamps.ResolvedRequest` for
the timezone contract.

Every tenor Citi serves, per currency
-------------------------------------
The grid is the full ``RATES.OIS.<idx>.PAR.*`` axis for that index, and the curve
is built from **every tenor that actually returned a quote** - not a fixed subset.
Measured 2026-08-07: all twenty currencies serve 44 tenors at EOD and eighteen
serve 44 at one minute. Tenors that did not serve are named on the snapshot rather
than dropped silently, because a curve quietly built from eight points instead of
forty-four still solves and still looks plausible.

What is guarded
---------------
* **Staleness.** Every snapshot carries the lag between what was asked for and
  what was served, and a lag past ``max_staleness`` raises. A backward ``asof``
  search is unbounded by construction: on this repo's other Citi source a request
  365 days past the end of the data still resolved, silently, to the last row.
* **Constituent spread.** Intraday tenors are taken as-of independently, so one
  illiquid tenor can be much older than the rest. The spread is measured and
  raises past ``max_constituent_spread``.
* **Tenor count.** Fewer than ``min_tenors`` usable quotes raises rather than
  producing a curve that solves trivially.
"""

from __future__ import annotations

import datetime
import logging
import threading
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import CurveNameEntry, entry_for_curve_name
from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import (
    ResolvedRequest,
    from_wire_naive,
    resolve_request,
    wire_timezone,
)

__all__ = [
    "CurveSnapshot",
    "CitiVeloExcelCurveFetcher",
    "StaleCurveError",
    "SparseCurveError",
    "DEFAULT_MAX_STALENESS",
]

_logger = logging.getLogger(__name__)

#: How far behind the requested instant a served snapshot may sit. Twelve hours
#: is the same default this repo's other intraday curve sources use, and it
#: comfortably spans the real overnight gaps: measured 2026-08-07, an in-session
#: curve lagged 0.7-1.1 minutes while JPY_TONAR - four hours past its Tokyo close -
#: lagged 232 minutes, which is legitimate and must not raise.
DEFAULT_MAX_STALENESS = datetime.timedelta(hours=12)

#: How far apart the newest and oldest tenor in one intraday snapshot may be.
DEFAULT_MAX_CONSTITUENT_SPREAD = datetime.timedelta(hours=6)
_WARN_CONSTITUENT_SPREAD = datetime.timedelta(minutes=30)

#: How far back an EOD request may roll to find a close. Measured in DAYS, and
#: separate from the intraday limit on purpose: a daily row is stamped at
#: midnight, so an end-of-day request is answered by a quote that is up to a day
#: "old" by construction and the 12-hour intraday limit would reject every single
#: one of them. Seven days spans a long weekend plus a national holiday, and still
#: catches the case this guard exists for - EUR_EONIA stopped on 2025-08-15, and a
#: request for it today must fail rather than silently serve a year-old curve.
DEFAULT_MAX_EOD_GAP = datetime.timedelta(days=7)

#: Window fetched behind the target before resolving as-of. Wide enough to cross
#: a weekend and a holiday, narrow enough that a cold cache does not pull years.
_LOOKBACK = {
    "eod": datetime.timedelta(days=21),
    "intraday": datetime.timedelta(days=5),
    "live": datetime.timedelta(days=5),
}

_FREQ = {"eod": "DAILY", "intraday": "MI01", "live": "MI01"}


class StaleCurveError(RuntimeError):
    """The newest quote at or before the requested instant is too old to serve."""


class SparseCurveError(RuntimeError):
    """Too few tenors served to build a meaningful curve."""


@dataclass(frozen=True)
class CurveSnapshot:
    """One Citi par grid at one instant, with everything needed to judge it.

    Attributes
    ----------
    par_rates
        ``{tenor: par_rate_percent}``, every tenor that served. This is what the
        builders consume.
    snapshot_at
        Tz-aware, in the wire zone: the instant the curve represents, i.e. the
        newest constituent quote.
    oldest_constituent_at
        Tz-aware: the oldest constituent quote. Equal to ``snapshot_at`` at EOD,
        and within a minute of it for a liquid intraday grid.
    requested_at
        Tz-aware: what the caller asked for. ``None`` in live mode.
    lag
        ``requested_at`` (or now, in live mode) minus ``snapshot_at``.
    """

    curve_name: str
    citi_index: str
    mode: str
    par_rates: Dict[str, float]
    snapshot_at: datetime.datetime
    oldest_constituent_at: datetime.datetime
    requested_at: Optional[datetime.datetime]
    lag: datetime.timedelta
    freq: str
    tenors_served: Tuple[str, ...] = ()
    tenors_missing: Tuple[str, ...] = ()
    n_rows_fetched: int = 0

    @property
    def reference_date(self) -> datetime.date:
        """The curve's anchor date - the snapshot's own date in the wire zone."""
        return self.snapshot_at.date()

    @property
    def constituent_spread(self) -> datetime.timedelta:
        return self.snapshot_at - self.oldest_constituent_at

    def describe(self) -> str:
        return (
            f"{self.curve_name} ({self.citi_index}) {self.mode} @ "
            f"{self.snapshot_at:%Y-%m-%d %H:%M:%S %Z}: {len(self.par_rates)} tenors, "
            f"lag {self.lag.total_seconds() / 60:.1f} min, spread "
            f"{self.constituent_spread.total_seconds() / 60:.1f} min"
        )

    def to_meta(self) -> Dict[str, Any]:
        """A JSON-ish dict for ``meta_data``, so consumers can see the provenance."""
        return {
            "source": "citivelo_excel",
            "curve_name": self.curve_name,
            "citi_index": self.citi_index,
            "mode": self.mode,
            "freq": self.freq,
            "wire_timezone": wire_timezone().key,
            "snapshot_at": self.snapshot_at.isoformat(),
            "oldest_constituent_at": self.oldest_constituent_at.isoformat(),
            "requested_at": None if self.requested_at is None else self.requested_at.isoformat(),
            "lag_seconds": self.lag.total_seconds(),
            "constituent_spread_seconds": self.constituent_spread.total_seconds(),
            "n_tenors": len(self.par_rates),
            "tenors_missing": list(self.tenors_missing),
        }


class CitiVeloExcelCurveFetcher:
    """Serve a Citi Velocity par grid in any of the three time modes.

    >>> f = CitiVeloExcelCurveFetcher()                              # doctest: +SKIP
    >>> snap = f.snapshot("GBP-SONIA-1D", "live")                    # doctest: +SKIP
    >>> snap.describe()                                              # doctest: +SKIP
    'GBP-SONIA-1D (GBP_SONIA) live @ 2026-08-07 10:50:00 EDT: 44 tenors, ...'

    Parameters
    ----------
    quotes
        A :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes`. Built lazily when
        omitted, which means a fully-cached request never opens a workbook and
        never needs a signed-in Excel.
    offline
        Serve only from the tag cache. Anything not cached is simply absent, and
        the resulting snapshot raises :class:`SparseCurveError` rather than
        pretending.
    """

    def __init__(
        self,
        *,
        quotes: Optional[CitiVeloQuotes] = None,
        offline: bool = False,
        method: str = "asof",
        max_staleness: Optional[datetime.timedelta] = DEFAULT_MAX_STALENESS,
        max_eod_gap: Optional[datetime.timedelta] = DEFAULT_MAX_EOD_GAP,
        max_constituent_spread: Optional[datetime.timedelta] = DEFAULT_MAX_CONSTITUENT_SPREAD,
        min_tenors: int = 4,
        client_kwargs: Optional[Mapping[str, Any]] = None,
    ):
        self._quotes = quotes
        self._owns_quotes = quotes is None
        self._offline = bool(offline)
        self._method = str(method)
        self._max_staleness = max_staleness
        self._max_eod_gap = max_eod_gap
        self._max_spread = max_constituent_spread
        self._min_tenors = int(min_tenors)
        self._client_kwargs = dict(client_kwargs or {})
        self._lock = threading.RLock()

    # -- lifecycle ------------------------------------------------------

    def quotes(self) -> CitiVeloQuotes:
        with self._lock:
            if self._quotes is None:
                self._quotes = CitiVeloQuotes(
                    offline=self._offline, client_kwargs=self._client_kwargs
                )
            return self._quotes

    def close(self) -> None:
        with self._lock:
            if self._quotes is not None and self._owns_quotes:
                self._quotes.close()
            self._quotes = None

    def __enter__(self) -> "CitiVeloExcelCurveFetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- the grid -------------------------------------------------------

    @staticmethod
    def par_grid_tags(citi_index: str) -> List[str]:
        """Every ``PAR`` tag Citi publishes for this curve, in tenor order.

        The whole axis, deliberately. A curve stripped from a hand-picked subset
        interpolates through the tenors it dropped, and the dropped ones are
        exactly where an off-node tie-out would have caught a convention error.
        """
        return T.ois_par_grid(citi_index)

    def snapshot(
        self,
        curve_name: str,
        timestamp: Union[str, datetime.date, datetime.datetime, pd.Timestamp, None] = "live",
        *,
        strict_tz: Optional[bool] = None,
        force_refresh: bool = False,
        min_tenors: Optional[int] = None,
        max_staleness: Optional[datetime.timedelta] = ...,  # type: ignore[assignment]
    ) -> CurveSnapshot:
        """The par grid for ``curve_name`` at ``timestamp``.

        Raises
        ------
        StaleCurveError
            The newest quote at or before the request is older than
            ``max_staleness``, or the tenors disagree by more than
            ``max_constituent_spread``.
        SparseCurveError
            Fewer than ``min_tenors`` tenors served.
        """
        entry = entry_for_curve_name(curve_name)
        request = resolve_request(timestamp, strict=strict_tz)
        default_limit = self._max_eod_gap if request.mode == "eod" else self._max_staleness
        limit = default_limit if max_staleness is ... else max_staleness

        frame = self._fetch_window(entry, request, force_refresh=force_refresh)
        return self._resolve(
            entry,
            request,
            frame,
            min_tenors=self._min_tenors if min_tenors is None else int(min_tenors),
            max_staleness=limit,
        )

    # -- internals ------------------------------------------------------

    def _fetch_window(
        self, entry: CurveNameEntry, request: ResolvedRequest, *, force_refresh: bool
    ) -> pd.DataFrame:
        freq = _FREQ[request.mode]
        lookback = _LOOKBACK[request.mode]
        if request.mode == "eod":
            end = datetime.datetime.combine(request.eod_date, datetime.time(23, 59, 59))
        elif request.mode == "intraday":
            end = request.wire_instant
        else:
            # Live: bounded ABOVE by now in the wire zone rather than left open, so
            # a clock skew on the add-in side cannot hand back a future stamp and
            # have it read as a negative lag.
            end = datetime.datetime.now(wire_timezone()).replace(tzinfo=None)
        start = end - lookback

        return self.quotes().frame(
            self.par_grid_tags(entry.citi_index),
            freq,
            start=start,
            end=end,
            force_refresh=force_refresh,
        )

    def _resolve(
        self,
        entry: CurveNameEntry,
        request: ResolvedRequest,
        frame: pd.DataFrame,
        *,
        min_tenors: int,
        max_staleness: Optional[datetime.timedelta],
    ) -> CurveSnapshot:
        freq = _FREQ[request.mode]
        all_tenors = [t.rsplit(".", 1)[-1] for t in self.par_grid_tags(entry.citi_index)]

        if request.mode == "eod" and request.eod_date >= datetime.datetime.now(wire_timezone()).date():
            # Measured 2026-08-07: the DAILY series already carried a row stamped
            # 2026-08-07 00:00 at 10:47 ET, i.e. mid-session. It is the running
            # value, not a close, and calling it "EOD" without saying so is the
            # stale-data-served-as-final failure in its other direction.
            warnings.warn(
                f"citivelo_excel: {entry.curve_name} EOD for {request.eod_date} is TODAY. Citi's "
                "daily series carries a row for the current, incomplete session, so this is the "
                "running level rather than a settled close. Use timestamp='live' if that is what "
                "you meant, or ask for the previous business day.",
                stacklevel=3,
            )

        if frame is None or frame.empty:
            raise SparseCurveError(
                f"citivelo_excel: no {freq} quotes for {entry.curve_name} ({entry.citi_index}) "
                f"in the window ending {request.describe()}. "
                + _coverage_hint(entry, request.mode)
            )

        # The EOD search runs to the END of the requested day (a daily row could in
        # principle be stamped at any time of it), but the lag is measured against
        # its START - the add-in stamps daily rows at midnight, so measuring
        # against 23:59:59 would make every single EOD snapshot look 24 h stale.
        target: Optional[pd.Timestamp]
        lag_from: Optional[pd.Timestamp]
        if request.mode == "live":
            target = lag_from = None
        elif request.mode == "intraday":
            target = lag_from = pd.Timestamp(request.wire_instant)
        else:
            target = pd.Timestamp(
                datetime.datetime.combine(request.eod_date, datetime.time(23, 59, 59))
            )
            lag_from = pd.Timestamp(datetime.datetime.combine(request.eod_date, datetime.time()))

        # Per-tenor as-of: each tenor's newest print at or before the target. A
        # single wide row would be all-or-nothing on one minute; this is what lets
        # a 44-tenor grid survive one illiquid tenor skipping a print.
        par_rates: Dict[str, float] = {}
        stamps: List[pd.Timestamp] = []
        for column in frame.columns:
            series = frame[column].dropna()
            if target is not None:
                series = series[series.index <= target]
            if series.empty:
                continue
            tenor = str(column).rsplit(".", 1)[-1]
            par_rates[tenor] = float(series.iloc[-1])
            stamps.append(series.index[-1])

        if len(par_rates) < min_tenors:
            raise SparseCurveError(
                f"citivelo_excel: only {len(par_rates)} tenor(s) served for {entry.curve_name} "
                f"at {request.describe()} (need {min_tenors}); a curve built from that many "
                "points solves trivially and means nothing. "
                + _coverage_hint(entry, request.mode)
            )

        snapshot_at = from_wire_naive(max(stamps))
        oldest_at = from_wire_naive(min(stamps))
        requested_at = None if target is None else from_wire_naive(target)
        now = datetime.datetime.now(wire_timezone())
        lag = (from_wire_naive(lag_from) if lag_from is not None else now) - snapshot_at

        if max_staleness is not None and lag > max_staleness:
            unit, size = ("d", lag.total_seconds() / 86_400) if request.mode == "eod" else (
                "h", lag.total_seconds() / 3600
            )
            limit_size = (
                max_staleness.total_seconds() / 86_400
                if request.mode == "eod"
                else max_staleness.total_seconds() / 3600
            )
            raise StaleCurveError(
                f"citivelo_excel: the newest {entry.curve_name} quote at or before "
                f"{request.describe()} is {snapshot_at:%Y-%m-%d %H:%M:%S %Z}, which is "
                f"{size:.1f} {unit} stale against a limit of {limit_size:.1f} {unit}. An as-of "
                "search is backward and unbounded, so serving this would have looked like a "
                "current curve. " + _coverage_hint(entry, request.mode)
            )

        spread = snapshot_at - oldest_at
        if self._max_spread is not None and spread > self._max_spread:
            raise StaleCurveError(
                f"citivelo_excel: {entry.curve_name} tenors at {request.describe()} span "
                f"{spread.total_seconds() / 3600:.1f} h between the oldest and newest quote "
                f"({oldest_at:%H:%M:%S} .. {snapshot_at:%H:%M:%S}), past the "
                f"{self._max_spread.total_seconds() / 3600:.1f} h limit. Mixing quotes that far "
                "apart builds a curve that existed at no instant."
            )
        if spread > _WARN_CONSTITUENT_SPREAD:
            warnings.warn(
                f"citivelo_excel: {entry.curve_name} at {request.describe()} mixes quotes "
                f"{spread.total_seconds() / 60:.0f} minutes apart "
                f"({oldest_at:%H:%M} .. {snapshot_at:%H:%M}).",
                stacklevel=3,
            )

        return CurveSnapshot(
            curve_name=entry.curve_name,
            citi_index=entry.citi_index,
            mode=request.mode,
            par_rates=par_rates,
            snapshot_at=snapshot_at,
            oldest_constituent_at=oldest_at,
            requested_at=requested_at,
            lag=lag,
            freq=freq,
            tenors_served=tuple(t for t in all_tenors if t in par_rates),
            tenors_missing=tuple(t for t in all_tenors if t not in par_rates),
            n_rows_fetched=int(len(frame)),
        )

    # -- builders -------------------------------------------------------

    def build_rl(self, snapshot: CurveSnapshot, **build_kwargs: Any) -> Any:
        """The rateslib curve for a snapshot, with the reprice guard intact.

        ``build_rl_ois_curve`` re-prices its own calibration swaps and raises if it
        cannot. That guard is not optional under rateslib 2.7.1, where a bad grid
        returns ``status='SUCCESS'`` from a curve that misprices its own inputs by
        4.9e+05 bp; nothing here relaxes it.
        """
        from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve

        return build_rl_ois_curve(
            par_rates=snapshot.par_rates,
            ref_date=snapshot.reference_date,
            citi_index=snapshot.citi_index,
            timestamp=snapshot.snapshot_at,
            **build_kwargs,
        )

    def build_ql(self, snapshot: CurveSnapshot, **build_kwargs: Any) -> Any:
        """The QuantLib curve for a snapshot."""
        from MDP.CitiVelocityExcel.curves.ql_builder import build_ql_ois_curve

        return build_ql_ois_curve(
            par_rates=snapshot.par_rates,
            ref_date=snapshot.reference_date,
            citi_index=snapshot.citi_index,
            **build_kwargs,
        )


def _coverage_hint(entry: CurveNameEntry, mode: str) -> str:
    """Say what the live harvest already knows about this curve and mode.

    An empty frame has two very different causes - the curve does not serve this
    mode at all, or it simply is not trading right now - and the fix differs.
    """
    if not entry.supports(mode):
        return (
            f"Measured 2026-08-07, {entry.citi_index} does not serve {mode} data: "
            f"it supports {', '.join(entry.modes) or 'nothing'}. {entry.note}".strip()
        )
    return (
        f"{entry.citi_index} does serve {mode} data, so this is most likely outside its "
        "trading session or outside its history. Sessions are 08:00-20:00 LOCAL to the "
        "currency, expressed in America/New_York stamps - e.g. JPY_TONAR ticks 19:00-06:59 ET."
    )
