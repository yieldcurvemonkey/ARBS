r"""A live curve daemon driven by ``CVSTREAM``, for as many curves as you like.

Why ``CVSTREAM`` and not the request/response path
--------------------------------------------------
``MDP/IRSwaps/CITIVELO_EXCEL/fetcher.py`` deliberately does **not** use
``CVSTREAM``: it is one scalar per call with no timestamp, so a request/response
source cannot tell a live quote from one that stopped four hours ago. A daemon is
the other case entirely - it supplies its own clock, it polls on a cadence it
controls, and it can afford to write its cells once and keep them forever. Those
are exactly the conditions ``CVSTREAM`` is good under.

What was measured about it (2026-08-07)
---------------------------------------
* **One tag per cell.** ``=CVSTREAM("a,b,c")`` returned a single scalar - the
  first tag's - silently dropping the other two. A 44-tenor curve is therefore 44
  cells, not one.
* **It really is RTD.** The same cell read 25 s apart gave
  ``4.05612604557329`` then ``4.05596231843847``.
* **Full double precision**, against ``CVLATEST``'s 5 decimal places
  (``4.23909408453934`` vs ``4.23919``).
* **The value lands in the anchor cell**, because a scalar does not spill.

The shape that follows
----------------------
Writing is the dangerous operation and it happens **once**, at
:meth:`CitiVeloStreamDaemon.open`. Every poll after that is
:meth:`CitiVelocityExcelClient.read_stream`, which performs no writes at all -
so a daemon that runs for eight hours writes to the user's Excel for the first
few seconds and then only reads. Its workbook is **never closed**: an RTD cell
always has queued add-in actions against it, and tearing one down is the
documented ``AccessViolation`` trigger. ``client.close()`` knows this and
declines.

The timestamp is ours, and that is a real limitation
-----------------------------------------------------
``CVSTREAM`` publishes no timestamp, so a snapshot is stamped with **the instant
the daemon read the cell**, not the instant Citi produced the quote. For a
one-minute cadence inside a liquid session that is a sub-second distinction; for a
curve whose market has closed it is not, and the daemon must not keep writing the
same frozen numbers under fresh timestamps. So a poll only persists when at least
one tenor has **moved** since the last one, and a run of unchanged polls is
counted and reported. That is the honest substitute for a vendor stamp, and it is
why ``MI01`` remains the primitive for anything that needs to know *when*.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd  # noqa: F401 - used in _existing_day

from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import CurveNameEntry, entry_for_curve_name
from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import wire_timezone

__all__ = [
    "StreamCurve",
    "PollResult",
    "CitiVeloStreamDaemon",
    "DEFAULT_ASSET_SUFFIX",
    "DEFAULT_POLL_SECONDS",
]

_logger = logging.getLogger(__name__)

#: CurveStore asset suffix. Deliberately distinct from the request/response
#: source's and from the older workbook source's ``-CITIVELO``: three different
#: constructions of "the Citi curve" must not share a key, or which one you get
#: depends on cache state.
DEFAULT_ASSET_SUFFIX = "CITIVELOSTREAM"

DEFAULT_POLL_SECONDS = 60.0

#: How many consecutive unchanged polls before saying so. Not an error - an
#: illiquid curve legitimately sits still - but a run of them is the signature of
#: a feed that has stopped, and silence about it is how a frozen curve gets
#: persisted all afternoon.
_STALL_WARN_POLLS = 10

#: What ``push_l2`` may be. See :class:`CitiVeloStreamDaemon`.
_L2_MODES = ("off", "rows", "day")


def _normalise_l2_mode(value: Any) -> str:
    """``push_l2`` accepts a bool for compatibility and a string for precision.

    ``True`` maps to ``"rows"``, not to the old whole-day-blob-per-poll
    behaviour: that is a change of meaning, and a deliberate one. The old
    behaviour is still reachable as ``"day"`` and is documented as a footgun.
    """
    if value is None or value is False:
        return "off"
    if value is True:
        return "rows"
    token = str(value).strip().lower()
    if token in _L2_MODES:
        return token
    raise ValueError(
        f"push_l2={value!r} is not a recognised mode. Use one of {_L2_MODES}, "
        "or a bool (False -> 'off', True -> 'rows')."
    )


@dataclass
class StreamCurve:
    """One curve's live cells, and the state needed to gate a write."""

    curve_name: str
    citi_index: str
    entry: CurveNameEntry
    tags: Dict[str, str]  # tenor -> tag
    cells: Dict[str, str] = field(default_factory=dict)  # tag -> cell address
    currency: str = ""  # which workbook this curve's cells live in
    last_values: Dict[str, float] = field(default_factory=dict)
    unchanged_polls: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0
    day_snapshots: Dict[datetime.date, List[Any]] = field(default_factory=dict)

    @property
    def asset(self) -> str:
        return f"{self.curve_name}-{DEFAULT_ASSET_SUFFIX}"


@dataclass
class PollResult:
    """What one poll of one curve did, and why."""

    curve_name: str
    at: datetime.datetime
    persisted: bool
    reason: str
    n_tenors: int = 0
    n_moved: int = 0
    reference_date: Optional[datetime.date] = None
    rate_10y: Optional[float] = None
    error: Optional[str] = None

    def describe(self) -> str:
        head = f"{self.at:%H:%M:%S} {self.curve_name:<20}"
        if self.error:
            return f"{head} ERROR {self.error}"
        mark = "wrote" if self.persisted else "skip "
        tail = f"10Y={self.rate_10y:.5f}" if self.rate_10y is not None else ""
        return f"{head} {mark} {self.n_tenors:>2} tenors, {self.n_moved:>2} moved  {self.reason:<28}{tail}"


class CitiVeloStreamDaemon:
    """Poll live ``CVSTREAM`` cells and persist a curve per tick.

    >>> daemon = CitiVeloStreamDaemon(["USD-SOFR-1D", "GBP-SONIA-1D"])   # doctest: +SKIP
    >>> daemon.open()                                                     # doctest: +SKIP
    >>> for r in daemon.poll_once():                                      # doctest: +SKIP
    ...     print(r.describe())

    Parameters
    ----------
    curve_names
        Which curves to stream. Each costs one RTD cell per tenor (44), written
        once.
    client
        A connected :class:`CitiVelocityExcelClient`. Built on :meth:`open` when
        omitted.
    store
        A ``Caching.curve_store.CurveStore``. Built on first write when omitted.
    push_l2
        What, if anything, to publish to Supabase. **Off by default.**

        ``False`` / ``"off"``
            local parquet only.
        ``True`` / ``"rows"``
            upsert ONE row per poll into ``arbs_curve_snapshots_v1`` via
            ``SupabaseCurveSync.upsert_snapshot_row``, and push the day blob once
            at :meth:`flush_l2` (shutdown or day rollover). This is the pattern
            ``scripts/eris_live_curve_service.py`` already uses for a per-minute
            feed, and it is what ``True`` now means.
        ``"day"``
            the OLD meaning: a whole-day blob per poll. Kept only so an existing
            caller is not silently re-pointed, and it is a footgun.
            ``CurveStore.write_day`` re-INSERTs the entire day's BYTEA on every
            call, so the traffic grows quadratically through the session - the
            ERIS design doc measures ~88 MB re-pushed per minute by end of day at
            18k nodes. At 44 nodes it is smaller, but it is still the same shape
            of mistake: the row tier answers the same question for one row.
    """

    def __init__(
        self,
        curve_names: Sequence[str],
        *,
        client: Any = None,
        store: Any = None,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        min_tenors: int = 8,
        push_l2: bool = False,
        persist: bool = True,
        on_result: Optional[Callable[[PollResult], None]] = None,
        build_kwargs: Optional[Mapping[str, Any]] = None,
    ):
        self._names = [str(n).strip().upper() for n in curve_names]
        self._client = client
        self._owns_client = client is None
        self._store = store
        self._poll_seconds = float(poll_seconds)
        self._min_tenors = int(min_tenors)
        self._l2_mode = _normalise_l2_mode(push_l2)
        #: kept for the old attribute name; True for either publishing mode.
        self._push_l2 = self._l2_mode != "off"
        self._sync: Any = None
        self._l2_rows = 0
        self._l2_row_failures = 0
        self._persist = bool(persist)
        self._on_result = on_result
        self._build_kwargs = dict(build_kwargs or {})
        self.curves: Dict[str, StreamCurve] = {}
        #: One client (hence one workbook) per currency.
        self._clients: Dict[str, Any] = {}
        self._lock = threading.RLock()
        self._opened = False

    # -- setup ----------------------------------------------------------

    def client(self, currency: str = "SHARED") -> Any:
        """The client for one CURRENCY's workbook.

        Grouped by currency on purpose. A streaming workbook can never be closed
        (its RTD cells always have queued add-in actions against it), so one
        workbook per *curve* per *restart* accumulates without limit - 62 had
        piled up before this was fixed. One per currency keeps the count to the
        number of currencies streamed, and a restart REUSES each rather than
        adding another, because the workbook carries a marker this package
        recognises.

        An injected client (the hermetic tests) is shared by every currency: the
        fake has no workbook-per-currency notion and nothing under test needs one.
        """
        if self._client is not None:
            return self._client
        from MDP.CitiVelocityExcel.com_client import CitiVelocityExcelClient

        key = str(currency).upper()
        with self._lock:
            existing = self._clients.get(key)
            if existing is None:
                existing = CitiVelocityExcelClient.connect(
                    attempts=1,
                    readiness_timeout=180.0,
                    poll_timeout=300.0,
                    workbook_tag=f"STREAM_{key}",
                )
                self._clients[key] = existing
            return existing

    def store(self) -> Any:
        if self._store is None:
            from Caching.curve_store import CurveStore

            self._store = CurveStore.default()
        return self._store

    def open(self) -> Dict[str, int]:
        """Write every curve's RTD cells. **The only writing this daemon does.**

        Returns ``{curve_name: n_cells}``. Idempotent: calling it twice does not
        write a second set of cells, because a second set would double the live
        regions for no benefit.
        """
        from MDP.CitiVelocityExcel import tags as T
        from MDP.IRSwaps.CITIVELO_EXCEL import register

        with self._lock:
            if self._opened:
                return {name: len(c.cells) for name, c in self.curves.items()}
            register()
            out: Dict[str, int] = {}
            for name in self._names:
                entry = entry_for_curve_name(name)
                grid = T.ois_par_grid(entry.citi_index)
                tags = {tag.rsplit(".", 1)[-1]: tag for tag in grid}
                client = self.client(entry.currency)
                _logger.info(
                    "citivelo_excel stream: opening %d live cells for %s (%s) in the %s workbook",
                    len(grid), name, entry.citi_index, entry.currency,
                )
                cells = client.open_stream(grid)
                self.curves[name] = StreamCurve(
                    curve_name=name, citi_index=entry.citi_index, entry=entry,
                    tags=tags, cells=cells, currency=entry.currency,
                )
                out[name] = len(cells)
            self._opened = True
            return out

    def close(self) -> None:
        """Release the client. The WORKBOOK is deliberately left in place.

        See the module docstring: an RTD cell always has queued add-in actions
        against it. ``CitiVelocityExcelClient.close`` declines to close a workbook
        holding one; this just drops the reference.
        """
        with self._lock:
            if self._client is not None and self._owns_client:
                self._client.close()
            self._client = None
            for client in self._clients.values():
                try:
                    client.close()
                except Exception as exc:  # noqa: BLE001 - teardown must not raise
                    _logger.debug("stream client close: %s", exc)
            self._clients.clear()

    # -- polling --------------------------------------------------------

    def poll_once(self) -> List[PollResult]:
        """Read every curve's cells once, build, and persist what moved."""
        if not self._opened:
            self.open()
        now = datetime.datetime.now(wire_timezone())
        results: List[PollResult] = []
        for name, curve in self.curves.items():
            try:
                results.append(self._poll_curve(curve, now))
            except Exception as exc:  # noqa: BLE001 - one curve must not stop the loop
                curve.failed += 1
                result = PollResult(
                    curve_name=name, at=now, persisted=False, reason="error",
                    error=f"{type(exc).__name__}: {exc}",
                )
                results.append(result)
                _logger.warning("citivelo_excel stream: %s poll failed: %s", name, exc)
        for result in results:
            if self._on_result is not None:
                self._on_result(result)
        return results

    def _poll_curve(self, curve: StreamCurve, now: datetime.datetime) -> PollResult:
        raw = self.client(curve.currency or curve.entry.currency).read_stream(curve.cells)
        values = {
            tenor: float(raw[tag])
            for tenor, tag in curve.tags.items()
            if raw.get(tag) is not None
        }
        if len(values) < self._min_tenors:
            curve.skipped += 1
            return PollResult(
                curve_name=curve.curve_name, at=now, persisted=False,
                reason=f"only {len(values)} tenors live", n_tenors=len(values),
            )

        moved = [t for t, v in values.items() if curve.last_values.get(t) != v]
        if curve.last_values and not moved:
            curve.unchanged_polls += 1
            curve.skipped += 1
            reason = "unchanged"
            if curve.unchanged_polls == _STALL_WARN_POLLS:
                _logger.warning(
                    "citivelo_excel stream: %s has not moved for %d consecutive polls - the feed "
                    "may have stopped, or its market is closed. Nothing is being written, which is "
                    "the correct outcome either way.",
                    curve.curve_name, curve.unchanged_polls,
                )
                reason = f"unchanged x{curve.unchanged_polls}"
            return PollResult(
                curve_name=curve.curve_name, at=now, persisted=False, reason=reason,
                n_tenors=len(values), n_moved=0, rate_10y=values.get("10Y"),
            )

        curve.unchanged_polls = 0
        reference_date = now.astimezone(_zone(curve.entry.local_timezone)).date()
        rlc = self._build(curve, values, reference_date, now)
        if self._persist:
            self._persist_snapshot(curve, rlc, now, reference_date)
        curve.last_values = values
        curve.written += 1
        return PollResult(
            curve_name=curve.curve_name, at=now, persisted=self._persist,
            reason="ok" if self._persist else "built (persist off)",
            n_tenors=len(values), n_moved=len(moved),
            reference_date=reference_date, rate_10y=values.get("10Y"),
        )

    def _build(
        self,
        curve: StreamCurve,
        values: Mapping[str, float],
        reference_date: datetime.date,
        now: datetime.datetime,
    ) -> Any:
        """Strip the curve, keeping the reprice guard. Raises if it will not solve."""
        from MDP.CitiVelocityExcel.curves.rl_builder import build_rl_ois_curve

        return build_rl_ois_curve(
            par_rates=dict(values),
            ref_date=reference_date,
            citi_index=curve.citi_index,
            timestamp=now,
            min_tenors=self._min_tenors,
            **self._build_kwargs,
        )

    def _persist_snapshot(
        self,
        curve: StreamCurve,
        rlc: Any,
        now: datetime.datetime,
        reference_date: datetime.date,
    ) -> None:
        from Caching.curve_store import CurveSnapshot, _to_date

        import pytz

        handle = rlc.rl_pricing_curve
        raw_nodes = handle.nodes._nodes if hasattr(handle.nodes, "_nodes") else dict(handle.nodes)
        ordered = sorted(raw_nodes.keys())
        ts_utc = now.astimezone(datetime.timezone.utc).replace(microsecond=0)
        et = ts_utc.astimezone(wire_timezone())

        snapshot = CurveSnapshot(
            timestamp_utc=ts_utc,
            timestamp_local=ts_utc.astimezone(pytz.timezone("America/Chicago")),
            trading_date=reference_date,
            session_minute=int(et.hour * 60 + et.minute),
            curve_name=curve.asset,
            cfg_hash="",
            reference_key=curve.curve_name,
            interpolation="log_linear",
            source_variant="CITIVELO_STREAM",
            node_dates=[_to_date(d) for d in ordered],
            discount_factors=[float(raw_nodes[d]) for d in ordered],
        )
        # Accumulate and rewrite the day. write_day is atomic and
        # content-addressed, so a rewrite that changes nothing costs nothing; and
        # keeping the day in memory means a restart re-reads rather than
        # truncating what is already on disk.
        bucket = curve.day_snapshots.setdefault(reference_date, [])
        if not bucket:
            bucket.extend(self._existing_day(curve, reference_date))
        bucket.append(snapshot)
        # The blob goes to L2 per poll ONLY under the legacy "day" mode. In
        # "rows" mode write_day stays local and the tick is published as one
        # indexed row; the day blob is pushed once by flush_l2().
        self.store().write_day(
            curve.asset,
            reference_date,
            bucket,
            overwrite=True,
            push_l2=(self._l2_mode == "day"),
        )
        if self._l2_mode == "rows":
            self._upsert_row(curve, snapshot)

    def _curve_sync(self) -> Any:
        """The L2 sync, built once. ``None`` when unavailable, never raising."""
        if self._sync is None:
            try:
                from Caching.supabase_curve_sync import SupabaseCurveSync

                self._sync = SupabaseCurveSync.from_defaults()
            except Exception as exc:  # noqa: BLE001 - a daemon must not die on this
                _logger.warning(
                    "citivelo_excel stream: no Supabase sync (%s); ticks stay local.", exc
                )
                self._sync = False
        return self._sync or None

    def _upsert_row(self, curve: StreamCurve, snapshot: Any) -> None:
        """One indexed row per tick — the pattern eris_live_curve_service uses.

        A failure here is logged and dropped: the local parquet already has the
        tick, and a daemon that dies because a pooler blinked is worse than one
        that skips a row.
        """
        sync = self._curve_sync()
        if sync is None:
            return
        try:
            if sync.upsert_snapshot_row(snapshot, curve.asset):
                self._l2_rows += 1
            else:
                self._l2_row_failures += 1
        except Exception as exc:  # noqa: BLE001
            self._l2_row_failures += 1
            if self._l2_row_failures in (1, 10, 100):
                _logger.warning(
                    "citivelo_excel stream: L2 row upsert failed for %s (%s). "
                    "%d failure(s) so far; the local parquet is unaffected.",
                    curve.asset, exc, self._l2_row_failures,
                )

    def flush_l2(self) -> Dict[str, int]:
        """Push each accumulated day's blob to L2 once. Safe to call repeatedly.

        This is the whole-day push that "rows" mode defers, so a restart or a
        reader that wants the day as one parquet gets it - without paying for it
        on every one of the day's several hundred polls.
        """
        if self._l2_mode != "rows":
            return {"days": 0, "rows": self._l2_rows}
        sync = self._curve_sync()
        if sync is None:
            return {"days": 0, "rows": self._l2_rows}
        pushed = 0
        for curve in self.curves.values():
            for day in list(curve.day_snapshots):
                try:
                    if sync.push_day(curve.asset, day):
                        pushed += 1
                except Exception as exc:  # noqa: BLE001
                    _logger.warning(
                        "citivelo_excel stream: L2 day push failed for %s %s (%s)",
                        curve.asset, day, exc,
                    )
        _logger.info(
            "citivelo_excel stream: flushed %d day blob(s) to L2 (%d row(s) upserted, "
            "%d row failure(s))", pushed, self._l2_rows, self._l2_row_failures,
        )
        return {"days": pushed, "rows": self._l2_rows, "row_failures": self._l2_row_failures}

    def _existing_day(self, curve: StreamCurve, day: datetime.date) -> List[Any]:
        """Snapshots already on disk for this day, so a restart appends."""
        from Caching.curve_store import CurveSnapshot, _to_date

        try:
            store = self.store()
            if not store.has_day(curve.asset, day):
                return []
            frame = store.read_raw_day(curve.asset, day)
        except Exception as exc:  # noqa: BLE001 - a restart must not fail on this
            _logger.warning(
                "citivelo_excel stream: could not read the existing %s day for %s (%s); "
                "this run will rewrite it from its own snapshots only.",
                curve.asset, day, exc,
            )
            return []
        if frame is None or getattr(frame, "empty", True):
            return []
        import pytz

        out: List[Any] = []
        for row in frame.to_dict("records"):
            ts_utc = pd.Timestamp(row["timestamp_utc"])
            if ts_utc.tzinfo is None:
                ts_utc = ts_utc.tz_localize("UTC")
            out.append(
                CurveSnapshot(
                    timestamp_utc=ts_utc.to_pydatetime(),
                    timestamp_local=ts_utc.tz_convert(pytz.timezone("America/Chicago")).to_pydatetime(),
                    trading_date=day,
                    session_minute=int(row.get("session_minute") or 0),
                    curve_name=curve.asset,
                    cfg_hash=str(row.get("cfg_hash") or ""),
                    reference_key=str(row.get("reference_key") or curve.curve_name),
                    interpolation=str(row.get("interpolation") or "log_linear"),
                    source_variant=str(row.get("source_variant") or "CITIVELO_STREAM"),
                    node_dates=[_to_date(d) for d in row["node_dates"]],
                    discount_factors=[float(x) for x in row["discount_factors"]],
                )
            )
        return out

    # -- the loop -------------------------------------------------------

    def run(
        self,
        *,
        once: bool = False,
        max_polls: Optional[int] = None,
        stop_at: Optional[datetime.time] = None,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """Poll on a drift-free cadence until ``stop_at`` or ``max_polls``."""
        self.open()
        started = datetime.datetime.now(wire_timezone())
        polls = 0
        try:
            while True:
                cycle = time.monotonic()
                for result in self.poll_once():
                    if verbose:
                        print(result.describe(), flush=True)
                polls += 1
                if once or (max_polls is not None and polls >= max_polls):
                    break
                now = datetime.datetime.now(wire_timezone())
                if stop_at is not None and now.time() >= stop_at:
                    break
                # Drift-free: sleep the remainder of the interval, not the whole
                # interval after the work.
                time.sleep(max(0.0, self._poll_seconds - (time.monotonic() - cycle)))
        except KeyboardInterrupt:
            _logger.info("citivelo_excel stream: interrupted; the workbook is left in place.")
        finally:
            # Deferred day blobs land here, including after Ctrl-C. Without the
            # finally, "rows" mode would leave the day blob unpublished on the
            # one exit path that actually happens.
            try:
                self.flush_l2()
            except Exception as exc:  # noqa: BLE001 - teardown must not raise
                _logger.warning("citivelo_excel stream: L2 flush failed (%s)", exc)
        return {
            "started": started.isoformat(),
            "polls": polls,
            "curves": {
                name: {
                    "asset": c.asset, "written": c.written, "skipped": c.skipped,
                    "failed": c.failed, "cells": len(c.cells),
                }
                for name, c in self.curves.items()
            },
        }


def _zone(name: str) -> Any:
    try:
        from zoneinfo import ZoneInfo
    except ImportError:  # pragma: no cover
        from backports.zoneinfo import ZoneInfo  # type: ignore
    return ZoneInfo(name)
