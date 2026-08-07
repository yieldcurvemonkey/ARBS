r"""COM bridge to the Citi Velocity Excel add-in.

This module owns the transport and nothing else: it attaches to a running,
human-authenticated Excel, writes ``CV*`` formulas into a scratch workbook it
created, polls the async cells, reads the blocks back and hands them to
:mod:`MDP.CitiVelocityExcel.block_parser`.

Why COM and not HTTP
--------------------
The add-in is a thin client over documented REST endpoints, but the request
signer lives inside ``Citi.Velocity.Web.dll`` and its signing material sits in
``session\portal``, DPAPI-sealed with secondary entropy (``CryptUnprotectData``
fails with error 13 even as the same user). The add-in's cookies are not in the
WinINet jar either. The add-in is the sanctioned client; we drive it rather than
impersonate it.

Why it attaches and never spawns
--------------------------------
Three isolation routes were tried and all three fail to register the UDFs:
``DispatchEx`` (``/automation -Embedding``), a normal ``EXCEL.EXE <book>`` launch
(Excel is single-instance, so the workbook opens inside the user's process) and
``EXCEL.EXE /x``. Registration is gated on ``CustomRibbon.onLoad`` -> portal
session resume -> entitlements, and the ribbon never loads in an automation
instance.

The write discipline is a correctness requirement
-------------------------------------------------
Because v1 shares the user's process, a bug in this writer can destroy their
unsaved work. Two distinct ``AccessViolation`` triggers were observed, and the
second is the naive fix for the first:

1. writing a block that overlaps a live ``CvFunction_*`` region;
2. clearing or deleting a region while the add-in's queued post-write actions
   (``ExcessClr``, ``Format``, ``AutoFit``) against it are still outstanding.

So: generous spacing, a cursor advanced by the block's **measured** extent, a new
worksheet rather than reuse when the sheet fills, nothing is ever cleared or
deleted, and teardown waits for a drain pause before closing the workbook once.
Every access is serialised behind one process-wide lock, because Excel is a
single shared mutable resource - the user's own session.

Never ``Stop-Process`` a client mid-call: that wedges Excel's OLE server (the
process stays alive and responsive in the UI while every automation bind fails)
and recovery costs a ~13 minute add-in re-login.
"""

from __future__ import annotations

import datetime
import logging
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.block_parser import (
    MetadataRow,
    TshistBlock,
    is_pending,
    coerce_excel_datetime,
    coerce_float,
    excel_error_name,
    normalise_block,
    parse_curve_block,
    parse_metadata_block,
    parse_tshist_block,
)
from MDP.CitiVelocityExcel.errors import (
    AddInNotSignedInError,
    CitiVelocityError,
    AsyncTimeoutError,
    ExcelDiedError,
    ExcelNotRunningError,
)
from MDP.CitiVelocityExcel.excel_constants import (
    BUSY_HRESULTS,
    NAME_ERR,
    VALUE_ERR,
    XL_ERRORS,
)
from MDP.CitiVelocityExcel.frequencies import (
    DateLike,
    format_bound,
    normalise_frequency,
    normalise_period,
    normalise_price_point,
)

__all__ = [
    "CitiVelocityExcelClient",
    "com_retry",
    "EXCEL_LOCK",
    "DEFAULT_FULL_PERIOD",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_GAP",
]

_logger = logging.getLogger(__name__)

#: One lock for every access to Excel, process-wide. Excel is the user's own
#: single shared mutable session; concurrent writers are how regions overlap.
EXCEL_LOCK = threading.RLock()

#: Rows left blank between one block's measured extent and the next anchor.
#: Blocks routinely come back far taller than predicted (a "DAILY 1W" request was
#: observed writing 68 rows), so the gap absorbs the surprise and the cursor is
#: then corrected by the block's real extent.
DEFAULT_GAP = 30

#: Excel's sheet row ceiling, minus headroom.
_MAX_ROW = 900_000

#: Tags per ``CVTSHIST`` call. 44 is proven (it is the add-in's own curve export);
#: the true ceiling is unknown, so the default does not exceed the proven number.
DEFAULT_CHUNK_SIZE = 44

#: Tags per ``CVMETADATA`` call. Smaller, because a poison tag hard-fails the
#: whole batch and forces a bisect.
DEFAULT_METADATA_CHUNK_SIZE = 20

#: The window used when the caller asks for "everything".
#:
#: This was ``"50Y"``, which the add-in **rejects**: ``Period`` is a closed
#: vocabulary (see :data:`MDP.CitiVelocityExcel.frequencies.PERIODS`) and 50Y is
#: not in it. The rejection is silent - no block is written at all - so
#: ``fetch_timeseries`` with neither ``period`` nor ``start`` returned an empty
#: frame for every tag, and looked exactly like a set of tags that do not serve.
#: ``"MAX"`` is the add-in's own token for the tag's whole history.
DEFAULT_FULL_PERIOD = "MAX"

#: Excel's formula length ceiling, with headroom for the fixed arguments.
_MAX_FORMULA_CHARS = 8_000


#: Written into ``A1`` of a scratch workbook's first sheet so this package can
#: recognise its own workbooks and REUSE them.
#:
#: Without it every ``connect()`` called ``Workbooks.Add()`` and a process that
#: did not reach ``close()`` - a streaming daemon by design, a killed run by
#: accident - left the workbook behind. Measured 2026-08-07: **62 open workbooks**,
#: almost all carrying the readiness probe's ``$A$1:$C$71`` footprint.
WORKBOOK_MARKER_PREFIX = "ARBS_CITIVELO_"

#: The tag ordinary request/response clients share, so they all reuse ONE
#: workbook rather than one per process.
DEFAULT_WORKBOOK_TAG = "SCRATCH"


def workbook_marker(tag: str) -> str:
    return f"{WORKBOOK_MARKER_PREFIX}{str(tag).strip().upper()}"


def find_marked_workbook(app: Any, tag: str) -> Optional[Any]:
    """An already-open workbook this package created for ``tag``, or ``None``.

    Identified by a marker string in ``A1`` rather than by file name, because a
    scratch workbook is never saved and Excel names it ``Book47``.
    """
    marker = workbook_marker(tag)
    try:
        count = int(com_retry(lambda: app.Workbooks.Count, attempts=4, delay=0.25))
    except Exception:  # noqa: BLE001
        return None
    for i in range(1, count + 1):
        try:
            workbook = com_retry(lambda: app.Workbooks(i), attempts=2, delay=0.1)
            value = com_retry(
                lambda: workbook.Worksheets(1).Range("A1").Value, attempts=2, delay=0.1
            )
        except Exception:  # noqa: BLE001 - a workbook we cannot read is not ours
            continue
        if isinstance(value, str) and value.strip() == marker:
            return workbook
    return None


def create_marked_workbook(app: Any, tag: str) -> Any:
    """A fresh scratch workbook, stamped so it can be found again."""
    workbook = com_retry(lambda: app.Workbooks.Add())
    sheet = com_retry(lambda: workbook.Worksheets(1))
    com_retry(lambda: setattr(sheet.Range("A1"), "Value", workbook_marker(tag)))
    return workbook


def probe_readiness(
    app: Any, *, timeout: float = 90.0, poll: float = 0.5, workbook: Any = None
) -> Tuple[str, Any]:
    """Classify a candidate Excel by what ``=CVTODAY()`` answers.

    Returns ``(status, workbook)`` where ``status`` is one of:

    ``ready``
        The add-in answered. The scratch workbook is returned for the caller to
        keep - it is the one the readiness probe was written into.
    ``not_signed_in``
        ``#NAME?``. The add-in is loaded but has not registered its UDFs.
    ``unusable``
        No working ``Workbooks`` collection - a Running-Object-Table zombie.
    ``pending``
        Never settled inside ``timeout``.

    Split out of the bind loop because it is the one piece of the connect path
    that is testable without COM, and because the four outcomes need four
    different responses: "no Excel" is fixed by opening Excel, "not signed in" by
    signing in, "unusable" by trying the next ROT entry, and "pending" by
    *waiting* - after a restart the Velocity login takes ~13 minutes and logs
    nothing in between, so an impatient caller concludes it is dead when it is
    merely slow.
    """
    created = workbook is None
    try:
        com_retry(lambda: app.Workbooks.Count, attempts=4, delay=0.25)
        if workbook is None:
            workbook = com_retry(lambda: app.Workbooks.Add())
        sheet = com_retry(lambda: workbook.Worksheets(1))
        # Probe below whatever is already in the sheet. A1 carries the reuse
        # marker, and a reused workbook may already hold live regions - writing
        # the probe on top of one is the AccessViolation trigger.
        probe_cell = f"B{_next_free_row(sheet)}"
        com_retry(lambda: setattr(sheet.Range(probe_cell), "Formula", "=CVTODAY()"))
        deadline = time.time() + max(0.0, timeout)
        while True:
            value = com_retry(lambda: sheet.Range(probe_cell).Value)
            if not is_pending(value):
                break
            if time.time() >= deadline:
                return "pending", workbook
            time.sleep(poll)
            try:
                app.CalculateUntilAsyncQueriesDone()
            except Exception:  # noqa: BLE001 - not all builds expose it
                pass
        if isinstance(value, int) and value == NAME_ERR:
            return "not_signed_in", workbook
        return "ready", workbook
    except Exception:  # noqa: BLE001 - a zombie fails on the very first property
        return "unusable", workbook if created else None


def _next_free_row(sheet: Any, *, gap: int = DEFAULT_GAP) -> int:
    """First row safely below everything already on ``sheet``.

    A reused scratch workbook already holds resolved ``CvFunction_*`` regions (and
    possibly live RTD cells), so a newcomer must start below all of them.
    ``UsedRange`` is the only thing Excel offers that covers the whole sheet;
    where it cannot be read, fall back to a row far enough down to be safe.
    """
    try:
        used = com_retry(lambda: sheet.UsedRange, attempts=2, delay=0.1)
        bottom = int(used.Row) + int(used.Rows.Count) - 1
    except Exception:  # noqa: BLE001
        return 1 + gap
    return max(1, bottom) + gap


def com_retry(fn, *, attempts: int = 40, delay: float = 0.5):
    """Call ``fn()``, retrying while Excel says "call rejected by callee".

    While Excel is busy, ``IDispatch::GetIDsOfNames`` fails and win32com's dynamic
    dispatch reports it as ``AttributeError`` rather than a COM error - e.g.
    ``Excel.Application.Workbooks`` on a perfectly good Application object. That
    is transient, so it is retried alongside the two busy HRESULTs.
    """
    last: Optional[BaseException] = None
    for _ in range(attempts):
        try:
            return fn()
        except AttributeError as exc:
            last = exc
            time.sleep(delay)
        except Exception as exc:  # noqa: BLE001 - re-raised below unless busy
            hresult = getattr(exc, "hresult", None)
            args = getattr(exc, "args", ())
            code = hresult if hresult is not None else (args[0] if args else None)
            if code not in BUSY_HRESULTS:
                raise
            last = exc
            time.sleep(delay)
    raise last if last is not None else RuntimeError("com_retry exhausted with no exception")


class CitiVelocityExcelClient:
    """Request/response client over a running, signed-in Citi Velocity add-in.

    >>> client = CitiVelocityExcelClient.connect()             # doctest: +SKIP
    >>> series = client.fetch_timeseries(                      # doctest: +SKIP
    ...     ["RATES.OIS.USD_SOFR.PAR.10Y"], freq="DAILY", period="1M"
    ... )
    >>> client.close()                                         # doctest: +SKIP

    Or as a context manager, which closes the scratch workbook after the drain
    pause::

        with CitiVelocityExcelClient.connect() as client:      # doctest: +SKIP
            ...

    Parameters
    ----------
    app
        An Excel ``Application`` COM object. Injected by the hermetic tests; when
        ``None`` (the normal path) the client binds to a running instance itself.
        It never spawns Excel.
    """

    # -- construction ---------------------------------------------------

    def __init__(
        self,
        *,
        app: Any = None,
        workbook: Any = None,
        gap: int = DEFAULT_GAP,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        metadata_chunk_size: int = DEFAULT_METADATA_CHUNK_SIZE,
        poll_timeout: float = 240.0,
        poll_interval: float = 0.25,
        drain_seconds: float = 2.0,
        readiness_timeout: float = 90.0,
        stream_write_pause: float = 0.15,
        shared_workbook: bool = False,
        logger: Optional[logging.Logger] = None,
    ):
        self._app = app
        self._wb = workbook
        self._ws: Any = None
        self._row = 1
        self._gap = int(gap)
        self._chunk_size = int(chunk_size)
        self._metadata_chunk_size = int(metadata_chunk_size)
        self._poll_timeout = float(poll_timeout)
        self._poll_interval = float(poll_interval)
        self._drain_seconds = float(drain_seconds)
        self._readiness_timeout = float(readiness_timeout)
        self._logger = logger or _logger
        self._closed = False
        self.calls = 0
        #: ``{tag: cell}`` for every live CVSTREAM cell this client has written.
        #: Non-empty makes close() a no-op - see open_stream().
        self._streaming: Dict[str, str] = {}
        self._stream_write_pause = float(stream_write_pause)
        # True only when this client ATTACHED to a tagged workbook that outlives
        # it. A client that created its own workbook (the hermetic tests, and any
        # direct `app=` construction) still owns it and still closes it.
        self._shared_workbook = bool(shared_workbook)

        if self._app is not None and self._wb is None:
            self._wb = com_retry(lambda: self._app.Workbooks.Add())
        if self._wb is not None:
            self._ws = com_retry(lambda: self._wb.Worksheets(1))
            # Start below EVERYTHING already on the sheet, not below a presumed
            # readiness probe: a reused scratch workbook carries every previous
            # run's regions, and writing on top of one kills Excel.
            self._row = _next_free_row(self._ws, gap=self._gap)

    @classmethod
    def connect(
        cls,
        *,
        attempts: int = 6,
        delay: float = 10.0,
        workbook_tag: str = DEFAULT_WORKBOOK_TAG,
        **kwargs: Any,
    ) -> "CitiVelocityExcelClient":
        """Bind to a running, signed-in Excel and REUSE this tag's scratch workbook.

        ``workbook_tag`` groups clients onto one workbook. Every ordinary
        request/response client shares ``SCRATCH``; the streaming daemon uses one
        tag per currency, so its never-closable RTD workbooks are a handful rather
        than one per curve per restart. Before tags existed each ``connect()``
        added a workbook and any process that did not reach ``close()`` left it
        behind - 62 of them had accumulated by 2026-08-07.

        Retries the bind: Excel can be busy for minutes during a long recalc, and
        a single pass over the candidates then wrongly reports "no usable Excel".

        Raises
        ------
        ExcelNotRunningError
            No reachable Excel instance at all.
        AddInNotSignedInError
            Excel is reachable but ``=CVTODAY()`` returns ``#NAME?``.
        """
        last: Optional[BaseException] = None
        for i in range(max(1, int(attempts))):
            try:
                app, wb = cls._bind_once(
                    readiness_timeout=float(kwargs.get("readiness_timeout", 90.0)),
                    workbook_tag=workbook_tag,
                )
                return cls(app=app, workbook=wb, shared_workbook=True, **kwargs)
            except AddInNotSignedInError:
                raise
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised
                last = exc
                if i < attempts - 1:
                    time.sleep(delay)
        if isinstance(last, ExcelNotRunningError):
            raise last
        raise ExcelNotRunningError(str(last) if last else "")

    @staticmethod
    def _bind_once(
        *, readiness_timeout: float = 90.0, workbook_tag: str = DEFAULT_WORKBOOK_TAG
    ) -> Tuple[Any, Any]:
        """Bind to a USABLE Excel: one whose Workbooks work and whose UDFs answer.

        ``GetActiveObject`` returns whatever registered in the Running Object
        Table first, which can be a zombie embedded instance with no ``Workbooks``
        collection, so every ROT entry is enumerated and probed. Do NOT filter on
        file extension: an unsaved workbook registers as e.g. ``Book2``, and the
        zombie instance owns the first slot.
        """
        try:
            import pythoncom  # type: ignore
            import win32com.client as win32  # type: ignore
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise ExcelNotRunningError(f"pywin32 is not installed ({exc}).") from exc

        pythoncom.CoInitialize()

        candidates: List[Any] = []
        try:
            candidates.append(com_retry(lambda: win32.GetActiveObject("Excel.Application")))
        except Exception:  # noqa: BLE001 - absence is the normal "no Excel" path
            pass
        try:
            rot = pythoncom.GetRunningObjectTable()
            ctx = pythoncom.CreateBindCtx(0)
            for moniker in rot.EnumRunning():
                try:
                    name = moniker.GetDisplayName(ctx, None)
                except Exception:  # noqa: BLE001
                    continue
                try:
                    obj = win32.GetObject(name)
                except Exception:  # noqa: BLE001
                    continue
                for cand in (getattr(obj, "Application", None), obj):
                    if cand is not None:
                        candidates.append(cand)
        except Exception:  # noqa: BLE001
            pass

        if not candidates:
            raise ExcelNotRunningError()

        saw_excel = False
        saw_name_error = False
        for app in candidates:
            existing = find_marked_workbook(app, workbook_tag)
            status, wb = probe_readiness(
                app, timeout=max(1.0, readiness_timeout), workbook=existing
            )
            if status != "unusable":
                saw_excel = True
            if status == "ready":
                if existing is None and wb is not None:
                    # The probe created it; stamp it so the next process finds it
                    # instead of adding another.
                    try:
                        com_retry(
                            lambda: setattr(
                                wb.Worksheets(1).Range("A1"), "Value",
                                workbook_marker(workbook_tag),
                            )
                        )
                    except Exception as exc:  # noqa: BLE001 - reuse is best-effort
                        _logger.debug("could not stamp the scratch workbook: %s", exc)
                return app, wb
            if status == "not_signed_in":
                saw_name_error = True
            if wb is not None and existing is None:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:  # noqa: BLE001
                    pass

        if saw_name_error:
            raise AddInNotSignedInError()
        if saw_excel:
            raise ExcelNotRunningError(
                "Found a running Excel, but =CVTODAY() never settled. "
                "If Excel was just restarted the Velocity login takes ~13 minutes and logs "
                "nothing in between - wait 15 minutes before concluding it is dead."
            )
        raise ExcelNotRunningError()

    # -- context manager ------------------------------------------------

    def __enter__(self) -> "CitiVelocityExcelClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the scratch workbook after letting queued add-in actions drain.

        Nothing is cleared or deleted at any point: tearing a region down while
        the add-in's ``ExcessClr``/``Format``/``AutoFit`` actions against it are
        outstanding is itself an ``AccessViolation`` trigger that takes the whole
        Excel process with it.
        """
        if self._closed:
            return
        if self._streaming:
            # An RTD cell always has queued add-in actions against it, so closing
            # the workbook that holds one is the documented AccessViolation
            # trigger. A streaming client's workbook is abandoned in place, on
            # purpose: an orphaned scratch workbook costs the user a tab, and the
            # alternative costs them the process.
            self._logger.info(
                "CitiVelocityExcelClient.close(): %d live CVSTREAM cell(s) open; leaving the "
                "workbook in place rather than tearing down live RTD regions.",
                len(self._streaming),
            )
            self._closed = True
            return
        self._closed = True
        if self._shared_workbook:
            # A tagged workbook outlives the process that happened to create it;
            # closing it would make the next run add another.
            self._wb = None
            self._ws = None
            return
        with EXCEL_LOCK:
            time.sleep(self._drain_seconds)
            if self._wb is not None:
                try:
                    self._wb.Close(SaveChanges=False)
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("CitiVelocityExcelClient: workbook close failed: %s", exc)
            self._wb = None
            self._ws = None

    # -- window sheets ---------------------------------------------------

    def push_window_sheet(self, name: str) -> str:
        """Start writing into a fresh worksheet named ``name``, and return it.

        A long backfill is the one workload that cannot share the running sheet:
        a minute-resolution window is ~5,300 rows x 45 columns, so a few hundred
        windows would fill the sheet, roll onto another, and leave Excel holding
        millions of live ``CvFunction_*`` cells.

        Giving each window its own sheet - the shape the hand-built workbooks in
        ``citi_usd_sofr_intraday_curve`` use, one per Mon-Fri week - makes the
        window a unit that can be dropped whole once it has been read. See
        :meth:`drop_window_sheet`.

        Sheet 1 is never touched: it holds the reuse marker that lets the next
        run find this workbook instead of adding another.
        """
        self._check_alive()
        with EXCEL_LOCK:
            sheet = com_retry(lambda: self._wb.Worksheets.Add())
            # Excel sheet names cap at 31 chars and reject : \ / ? * [ ].
            safe = re.sub(r"[:\\/?*\[\]]", "_", str(name))[:31]
            try:
                com_retry(lambda: setattr(sheet, "Name", safe))
            except Exception:  # noqa: BLE001 - a duplicate name is not worth failing over
                safe = str(com_retry(lambda: sheet.Name))
            self._ws = sheet
            self._row = 1
        return safe

    def drop_window_sheet(self) -> bool:
        """Delete the current window sheet after letting the add-in drain.

        Returns ``True`` if the sheet went away. A refusal is reported, not
        raised: the caller's data is already read, and the cost of a surviving
        sheet is memory, whereas the cost of fighting Excel here is the process.

        The drain is not optional. The add-in queues ``ExcessClr``/``Format``/
        ``AutoFit`` against cells it has written, and deleting a sheet out from
        under those queued actions is the documented ``AccessViolation`` trigger.
        By the time this is called the block has already settled (it was polled
        to a non-pending value and read), so the queue is short - but it is not
        guaranteed empty until Excel says so.
        """
        self._check_alive()
        with EXCEL_LOCK:
            sheet, self._ws = self._ws, None
            if sheet is None:
                return False
            try:
                self._app.CalculateUntilAsyncQueriesDone()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(self._drain_seconds)
            alerts = None
            try:
                alerts = self._app.DisplayAlerts
                self._app.DisplayAlerts = False
            except Exception:  # noqa: BLE001
                pass
            try:
                com_retry(lambda: sheet.Delete())
                dropped = True
            except Exception as exc:  # noqa: BLE001
                self._logger.warning(
                    "CitiVelocityExcelClient.drop_window_sheet: Excel refused the delete "
                    "(%s). Leaving the sheet in place - the window's data is already read.",
                    exc,
                )
                dropped = False
            finally:
                if alerts is not None:
                    try:
                        self._app.DisplayAlerts = alerts
                    except Exception:  # noqa: BLE001
                        pass
            # Fall back to the marker sheet so the client stays usable either way.
            self._ws = com_retry(lambda: self._wb.Worksheets(1))
            self._row = 1
            return dropped

    def sheet_count(self) -> int:
        """How many worksheets the scratch workbook is currently carrying."""
        try:
            return int(com_retry(lambda: self._wb.Worksheets.Count))
        except Exception:  # noqa: BLE001
            return -1

    # -- sheet plumbing -------------------------------------------------

    def _check_alive(self) -> None:
        if self._closed:
            raise ExcelDiedError("CitiVelocityExcelClient is closed.")
        try:
            com_retry(lambda: self._app.Workbooks.Count, attempts=4, delay=0.25)
        except Exception as exc:  # noqa: BLE001
            raise ExcelDiedError(
                f"Excel is no longer reachable ({exc}). Not retrying: retrying into a dying "
                "OLE server is what wedges it, and recovery costs a full add-in re-login."
            ) from exc

    def _anchor(self, rows_needed: int) -> str:
        """Reserve an anchor below every live region, with a wide margin.

        ``rows_needed`` is only a provisional reservation - the cursor is
        corrected by :meth:`_advance_past` once the real extent is known, because
        under-reserving would put the next anchor inside a live ``CvFunction_*``
        region, which is a crash trigger.
        """
        if self._row + rows_needed + self._gap > _MAX_ROW:
            # Add a sheet rather than reuse rows. Never delete the old one.
            self._ws = com_retry(lambda: self._wb.Worksheets.Add())
            self._row = 1
        # Column B, not A: the add-in writes its block one column to the LEFT of
        # the anchor and one row below it (a resolved call at C1 published
        # `=Sheet1!$C$1:$D$1,Sheet1!$B$2:$D$24`). Anchoring in column A would put
        # the Date column off-sheet.
        cell = f"B{self._row}"
        self._row += int(rows_needed) + self._gap
        return cell

    def _advance_past(self, region: Any) -> None:
        """Push the cursor below the block that was actually written."""
        try:
            bottom = int(region.Row) + int(region.Rows.Count) - 1
        except Exception:  # noqa: BLE001 - the provisional reservation stands
            return
        self._row = max(self._row, bottom + 1 + self._gap)

    def _settle(self, cell: str, *, timeout: Optional[float] = None) -> Tuple[Any, float]:
        """Poll ``cell`` until it stops being a pending sentinel.

        Returns ``(value, elapsed)``. A timeout returns the last pending value so
        the caller can decide whether to raise with the tag list attached.
        """
        limit = self._poll_timeout if timeout is None else float(timeout)
        started = time.time()
        value: Any = None
        while True:
            elapsed = time.time() - started
            value = com_retry(lambda: self._ws.Range(cell).Value)
            if not is_pending(value):
                return value, elapsed
            if elapsed >= limit:
                return value, elapsed
            time.sleep(self._poll_interval)
            try:
                self._app.CalculateUntilAsyncQueriesDone()
            except Exception:  # noqa: BLE001 - not all builds expose it
                pass

    def _extent(self, anchor: str) -> Any:
        """Resolve the region the add-in wrote for the formula at ``anchor``.

        The add-in publishes the exact extent as a defined name
        ``CvFunction_<row>_<col>``, e.g.
        ``=Sheet1!$C$1:$D$1,Sheet1!$B$2:$D$24`` - the header+data block is the
        larger area. That is the reliable extractor and the most stable contract
        the add-in offers (it survives layout changes that would break fixed
        offsets). ``CurrentRegion`` is the fallback, and it is only a fallback
        because it absorbs adjacent cells.
        """
        try:
            rng = com_retry(lambda: self._ws.Range(anchor))
            row = int(rng.Row)
            col = int(rng.Column)
        except Exception:  # noqa: BLE001
            return com_retry(lambda: self._ws.Range(anchor).CurrentRegion)

        name = f"CvFunction_{row}_{col}"
        for holder in (self._ws, self._wb):
            if holder is None:
                continue
            try:
                named = com_retry(lambda: holder.Names(name).RefersToRange, attempts=2, delay=0.1)
            except Exception:  # noqa: BLE001 - name absent on this holder
                continue
            if named is None:
                continue
            best = None
            best_cells = -1
            try:
                areas = named.Areas
                count = int(areas.Count)
                for i in range(1, count + 1):
                    area = areas(i)
                    cells = int(area.Rows.Count) * int(area.Columns.Count)
                    if cells > best_cells:
                        best, best_cells = area, cells
            except Exception:  # noqa: BLE001 - single-area name
                best = named
            if best is not None:
                return best

        return com_retry(lambda: self._ws.Range(anchor).CurrentRegion)

    def _write_and_read(
        self,
        formula: str,
        *,
        rows_needed: int,
        timeout: Optional[float] = None,
    ) -> Tuple[List[List[Any]], Any, float]:
        """Write one formula, poll it, and read back its measured extent.

        Returns ``(rows, settled_value, elapsed)``. ``rows`` is empty when the
        formula resolved to a scalar error.
        """
        self._check_alive()
        anchor = self._anchor(rows_needed)
        com_retry(lambda: setattr(self._ws.Range(anchor), "Formula", formula))
        try:
            self._app.CalculateUntilAsyncQueriesDone()
        except Exception:  # noqa: BLE001
            pass
        value, elapsed = self._settle(anchor, timeout=timeout)
        self.calls += 1

        if is_pending(value):
            return [], value, elapsed
        if isinstance(value, int) and excel_error_name(value) is not None:
            return [], value, elapsed

        region = self._extent(anchor)
        self._advance_past(region)
        rows = normalise_block(com_retry(lambda: region.Value))
        return rows, value, elapsed

    # -- CVTSHIST -------------------------------------------------------

    @staticmethod
    def _tshist_formula(
        tags: Sequence[str],
        *,
        freq: str,
        period: str,
        start: str,
        end: str,
        price_point: str,
    ) -> str:
        joined = ",".join(tags)
        return (
            f'=CVTSHIST("{joined}","{freq}","{period}","{start}","{end}","{price_point}")'
        )

    def _chunks(self, tags: Sequence[str], size: int, *, overhead: int) -> List[List[str]]:
        """Chunk tags, tightening the chunk when the formula would be too long."""
        out: List[List[str]] = []
        current: List[str] = []
        current_chars = 0
        for tag in tags:
            projected = current_chars + len(tag) + 1
            if current and (len(current) >= size or projected + overhead > _MAX_FORMULA_CHARS):
                out.append(current)
                current, current_chars = [], 0
                projected = len(tag) + 1
            current.append(tag)
            current_chars = projected
        if current:
            out.append(current)
        return out

    def fetch_timeseries(
        self,
        tags: Sequence[str],
        freq: str = "DAILY",
        *,
        period: Optional[str] = None,
        start: Optional[DateLike] = None,
        end: Optional[DateLike] = None,
        price_point: str = "CLOSE",
        strict: bool = False,
        timeout: Optional[float] = None,
    ) -> Dict[str, pd.Series]:
        """Fetch full history for ``tags`` in as few ``CVTSHIST`` calls as possible.

        Parameters
        ----------
        tags
            Velocity tags. Duplicates are collapsed; order is preserved.
        freq
            One of ``MI01 MI10 HOURLY DAILY WEEKLY MONTHLY``.
        period
            A relative window such as ``'1W'``/``'6M'``/``'5Y'``. When neither
            ``period`` nor ``start`` is given, :data:`DEFAULT_FULL_PERIOD` is used
            - the add-in truncates it to the tag's own history.
        start, end
            Explicit bounds. Dates or datetimes; formatted per
            :func:`~MDP.CitiVelocityExcel.frequencies.format_bound`.
        strict
            Raise on any per-tag failure instead of omitting that tag.

        Returns
        -------
        dict[str, pandas.Series]
            One ascending, de-duplicated float series per tag that returned data.
            Tags that failed are ABSENT from the mapping and their reasons are
            available through :meth:`last_failures`; a bad tag costs its own
            column and nothing else, because ``CVTSHIST`` degrades per column.
        """
        freq_token = normalise_frequency(freq)
        point_token = normalise_price_point(price_point)
        period_token = normalise_period(period)
        start_token = format_bound(start, freq=freq_token)
        end_token = format_bound(end, freq=freq_token)
        if not period_token and not start_token:
            period_token = DEFAULT_FULL_PERIOD

        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        out: Dict[str, pd.Series] = {}
        failures: Dict[str, str] = {}
        if not wanted:
            self._last_failures = failures
            return out

        overhead = len('=CVTSHIST("","","","","","")') + len(freq_token) + len(period_token) + len(
            start_token
        ) + len(end_token) + len(point_token)

        with EXCEL_LOCK:
            for chunk in self._chunks(wanted, self._chunk_size, overhead=overhead):
                formula = self._tshist_formula(
                    chunk,
                    freq=freq_token,
                    period=period_token,
                    start=start_token,
                    end=end_token,
                    price_point=point_token,
                )
                rows, value, elapsed = self._write_and_read(
                    formula, rows_needed=8, timeout=timeout
                )
                if is_pending(value):
                    raise AsyncTimeoutError(chunk, elapsed, formula)
                if not rows:
                    err = excel_error_name(value) or "no block"
                    for tag in chunk:
                        failures[tag] = err
                    continue

                block: TshistBlock = parse_tshist_block(rows, chunk, price_point=point_token)
                out.update(block.series)
                failures.update(block.failures)

        self._last_failures = failures
        if strict and failures:
            raise CitiVelocityError(
                f"CVTSHIST failed for {len(failures)} tag(s): "
                + ", ".join(f"{k} ({v})" for k, v in list(failures.items())[:10])
            )
        return out

    def last_failures(self) -> Dict[str, str]:
        """Per-tag failure reasons from the most recent :meth:`fetch_timeseries`."""
        return dict(getattr(self, "_last_failures", {}))

    def fetch_frame(
        self,
        tags: Sequence[str],
        freq: str = "DAILY",
        **kwargs: Any,
    ) -> pd.DataFrame:
        """:meth:`fetch_timeseries` as one wide, time-indexed frame."""
        series = self.fetch_timeseries(tags, freq, **kwargs)
        if not series:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
        frame = pd.concat(series, axis=1)
        frame.index.name = "Date"
        return frame.sort_index()

    # -- CVMETADATA -----------------------------------------------------

    def metadata(self, tags: Sequence[str], *, timeout: Optional[float] = None) -> Dict[str, MetadataRow]:
        """Description and history bounds per tag, bisecting on ``#VALUE!``.

        ``CVMETADATA`` usually degrades per row, but some tags hard-fail the
        entire batch to ``#VALUE!`` - ``RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y`` does
        this even alone. A batch returning ``#VALUE!`` is therefore bisected to
        isolate the poison tag rather than discarded.

        This is NOT a validator. It reports zero valid tenors for the entire
        ``SWAP_SPREAD`` family while ``CVTSHIST`` serves all eleven; use
        :meth:`validate` for validity.
        """
        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        out: Dict[str, MetadataRow] = {}
        if not wanted:
            return out
        with EXCEL_LOCK:
            for chunk in self._chunks(wanted, self._metadata_chunk_size, overhead=32):
                self._metadata_chunk(chunk, out, timeout=timeout)
        return out

    def _metadata_chunk(
        self,
        chunk: Sequence[str],
        out: Dict[str, MetadataRow],
        *,
        timeout: Optional[float] = None,
    ) -> None:
        formula = '=CVMETADATA("{}",TRUE)'.format(",".join(chunk))
        rows, value, elapsed = self._write_and_read(
            formula, rows_needed=len(chunk) + 1, timeout=timeout
        )
        if is_pending(value):
            raise AsyncTimeoutError(chunk, elapsed, formula)

        hard_fail = isinstance(value, int) and value in (VALUE_ERR, NAME_ERR)
        if hard_fail or not rows:
            if len(chunk) == 1:
                out[chunk[0]] = MetadataRow(chunk[0], XL_ERRORS.get(value, "error"), None, None, ok=False)
                return
            mid = len(chunk) // 2
            self._metadata_chunk(chunk[:mid], out, timeout=timeout)
            self._metadata_chunk(chunk[mid:], out, timeout=timeout)
            return

        parsed = parse_metadata_block(rows, chunk)
        unresolved = [t for t in chunk if not parsed[t].ok and parsed[t].description is None]
        if unresolved and len(unresolved) == len(chunk) and len(chunk) > 1:
            # A whole-batch mismatch: fall back per tag so nothing is misattributed.
            for tag in chunk:
                self._metadata_chunk([tag], out, timeout=timeout)
            return
        out.update(parsed)

    # -- CVLATEST / CVSNAP ----------------------------------------------

    def latest(self, tags: Sequence[str], *, timeout: Optional[float] = None) -> Dict[str, Tuple[Optional[float], Optional[datetime.datetime]]]:
        """Live tick and its timestamp per tag, via ``CVLATEST``."""
        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        out: Dict[str, Tuple[Optional[float], Optional[datetime.datetime]]] = {}
        if not wanted:
            return out
        with EXCEL_LOCK:
            for chunk in self._chunks(wanted, self._chunk_size, overhead=32):
                formula = '=CVLATEST("{}")'.format(",".join(chunk))
                rows, value, elapsed = self._write_and_read(
                    formula, rows_needed=len(chunk) + 2, timeout=timeout
                )
                if is_pending(value):
                    raise AsyncTimeoutError(chunk, elapsed, formula)
                out.update(self._parse_scalar_grid(rows, chunk))
        return out

    def snapshot(
        self,
        tags: Sequence[str],
        when: DateLike,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Tuple[Optional[float], Optional[datetime.datetime]]]:
        """Point-in-time value per tag, via ``CVSNAP`` at ``when``."""
        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        out: Dict[str, Tuple[Optional[float], Optional[datetime.datetime]]] = {}
        if not wanted:
            return out
        stamp = format_bound(when, freq="MI01")
        with EXCEL_LOCK:
            for chunk in self._chunks(wanted, self._chunk_size, overhead=32):
                formula = '=CVSNAP("{}","{}")'.format(",".join(chunk), stamp)
                rows, value, elapsed = self._write_and_read(
                    formula, rows_needed=len(chunk) + 2, timeout=timeout
                )
                if is_pending(value):
                    raise AsyncTimeoutError(chunk, elapsed, formula)
                out.update(self._parse_scalar_grid(rows, chunk))
        return out

    #: Excel serial floor below which a numeric cell is a PRICE, not a date.
    #: 32874 is 1990-01-01; no Citi series starts earlier, and a par rate is a
    #: single-digit float. Without this floor ``coerce_excel_datetime(4.23919)``
    #: happily returns ``1900-01-03 05:44:26`` and a rate is reported as a
    #: timestamp - measured on a live ``CVSNAP`` on 2026-08-07.
    _MIN_STAMP_SERIAL = 32_874.0

    @classmethod
    def _parse_scalar_grid(
        cls,
        rows: Sequence[Sequence[Any]],
        tags: Sequence[str],
    ) -> Dict[str, Tuple[Optional[float], Optional[datetime.datetime]]]:
        """Map a ``CVLATEST``/``CVSNAP`` grid onto ``{tag: (value, stamp)}``.

        Both functions answer either as a column-per-tag block with a header row
        (the ``CVTSHIST`` shape) or as one row per tag. Both are handled, and the
        row form is only used when the header form does not apply, so a header
        that happens to be absent never silently shifts the mapping.

        Measured live on 2026-08-07, and both facts cost a wrong answer before
        they were known:

        **The row form is POSITIONAL and can contain empty rows.** ``CVLATEST``
        over six tags where one is a discontinued curve (``EUR_EONIA``) returns
        six rows, one of them blank. Compacting the blanks away before checking
        ``len(body) == len(tags)`` made the count disagree and returned
        ``(None, None)`` for **all six** - one dead curve silently blanked five
        live ones. Rows are therefore aligned by position, not by compaction.

        **A single-column row has no timestamp.** ``CVLATEST`` and ``CVSNAP`` both
        answer with bare values; neither publishes a stamp. Reading the same cell
        as both value and date turned the 10Y rate ``4.23287`` into the timestamp
        ``1900-01-03 05:35:20``. A stamp is now only taken from a cell that is
        genuinely a datetime, or from a *different* cell whose serial is past
        :attr:`_MIN_STAMP_SERIAL`.
        """
        out: Dict[str, Tuple[Optional[float], Optional[datetime.datetime]]] = {}
        if not rows:
            return {t: (None, None) for t in tags}

        block = parse_tshist_block(rows, tags)
        if block.series:
            for tag in tags:
                s = block.series.get(tag)
                if s is None or s.empty:
                    out[tag] = (None, None)
                else:
                    out[tag] = (float(s.iloc[-1]), s.index[-1].to_pydatetime())
            return out

        body = cls._align_scalar_rows(rows, len(tags))
        if body is None:
            return {t: (None, None) for t in tags}
        for tag, cells in zip(tags, body):
            out[tag] = cls._scalar_row(cells)
        return out

    @staticmethod
    def _align_scalar_rows(
        rows: Sequence[Sequence[Any]], n_tags: int
    ) -> Optional[List[Sequence[Any]]]:
        """Line a scalar grid up with the tag list without reordering it.

        Blank rows in the middle are DATA (a tag that served nothing) and are kept
        where they are. Blank rows at the edges, and a leading header row, are
        padding and are trimmed - but only when trimming makes the count match, so
        an unrecognised shape is reported as such rather than silently shifted.
        """
        candidate = [list(r) for r in rows]
        if len(candidate) == n_tags:
            return candidate

        def _blank(row: Sequence[Any]) -> bool:
            return not row or all(c is None or (isinstance(c, str) and not c.strip()) for c in row)

        trimmed = list(candidate)
        while trimmed and _blank(trimmed[0]):
            trimmed.pop(0)
        while trimmed and _blank(trimmed[-1]):
            trimmed.pop()
        if len(trimmed) == n_tags:
            return trimmed
        # A header row carries no numbers at all.
        if len(trimmed) == n_tags + 1 and all(coerce_float(c) is None for c in trimmed[0]):
            return trimmed[1:]
        return None

    @classmethod
    def _scalar_row(cls, cells: Sequence[Any]) -> Tuple[Optional[float], Optional[datetime.datetime]]:
        """One row of a scalar grid as ``(value, stamp)``; stamp is usually ``None``."""
        value: Optional[float] = None
        value_at: Optional[int] = None
        for i, cell in enumerate(cells):
            v = coerce_float(cell)
            if v is not None:
                value, value_at = v, i
                break
        stamp: Optional[datetime.datetime] = None
        for i, cell in enumerate(cells):
            if i == value_at:
                continue
            if isinstance(cell, datetime.datetime) or isinstance(cell, datetime.date):
                stamp = coerce_excel_datetime(cell)
                break
            if isinstance(cell, (int, float)) and not isinstance(cell, bool):
                if float(cell) >= cls._MIN_STAMP_SERIAL:
                    stamp = coerce_excel_datetime(cell)
                    break
        return value, stamp

    # -- arbitrary CV* formulas -----------------------------------------

    def evaluate_formula(
        self,
        formula: str,
        *,
        rows_needed: int = 4,
        timeout: Optional[float] = None,
    ) -> Tuple[Any, List[List[Any]]]:
        """Write one arbitrary formula, settle it, and return ``(value, rows)``.

        The escape hatch for the ``CV*`` functions that have no typed wrapper -
        ``CVNOW``, ``CVTODAY``, ``CVSTREAM``, ``CVTICK`` - and for probing a new
        one before deciding what its wrapper should look like. It goes through the
        SAME disciplined write path as every other call (anchor below every live
        region, cursor advanced by the block's measured extent, nothing ever
        cleared), which is the whole point of it living here rather than in a
        probe script: a second write path that does not honour the spacing rules
        is an ``AccessViolation`` waiting to happen.

        Returns
        -------
        tuple
            ``value`` is the settled anchor cell - the answer itself for a scalar
            function, or the formula text for one that spills a block. ``rows`` is
            the normalised block at the measured extent, empty when the formula
            resolved to a scalar error.

        Notes
        -----
        ``rows_needed`` is only a provisional reservation; pass a generous number
        for a function whose block size is unknown. It does not need to be right,
        because the cursor is corrected from the real extent afterwards - but
        under-reserving costs nothing only because the default gap is 30 rows.
        """
        with EXCEL_LOCK:
            rows, value, elapsed = self._write_and_read(
                str(formula), rows_needed=int(rows_needed), timeout=timeout
            )
        if is_pending(value):
            raise AsyncTimeoutError([str(formula)], elapsed, str(formula))
        return value, rows

    # -- CVSTREAM -------------------------------------------------------

    def open_stream(
        self,
        tags: Sequence[str],
        *,
        timeout: Optional[float] = None,
        settle: bool = True,
    ) -> Dict[str, str]:
        """Write one live ``CVSTREAM`` cell per tag and return ``{tag: address}``.

        ``CVSTREAM`` is **one tag per cell** - measured 2026-08-07, a
        comma-separated list of three tags returned a single scalar (the first
        tag's), silently dropping the rest. So a 44-tenor curve is 44 cells.

        The cells are real RTD: the same cell read 25 s apart returned
        ``4.05612604557329`` then ``4.05596231843847``. Two consequences shape
        this API:

        * **The value lands in the anchor cell itself**, unlike ``CVTSHIST``,
          which puts its formula text there and spills its block one column left.
          A scalar does not spill, so polling is just reading the anchor.
        * **The workbook holding these cells must never be closed.** An RTD cell
          always has queued add-in actions against it, and tearing one down is the
          documented ``AccessViolation`` trigger. :meth:`close` is therefore a
          no-op once a stream is open; see :attr:`has_open_stream`.

        Writing happens once, here, through the same spacing discipline as every
        other call. :meth:`read_stream` afterwards performs **no writes at all**,
        which is what makes a long-running poller safe.
        """
        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        cells: Dict[str, str] = {}
        if not wanted:
            return cells
        with EXCEL_LOCK:
            for tag in wanted:
                self._check_alive()
                anchor = self._anchor(2)
                formula = f'=CVSTREAM("{tag}")'
                self._write_stream_formula(anchor, formula, tag)
                self.calls += 1
                cells[tag] = anchor
                # Establishing an RTD subscription is real work for Excel, and a
                # burst of them makes it reject the next write outright. Measured
                # 2026-08-07: 44 cells opened cleanly, then the 45th (the first of
                # the next curve) raised com_error(-2147352567, 'Exception
                # occurred'). Pacing removes it; see _write_stream_formula for the
                # retry that covers the rest.
                if self._stream_write_pause:
                    time.sleep(self._stream_write_pause)
            self._streaming.update(cells)
            if settle:
                # One settle pass over the whole set rather than per cell: they
                # resolve concurrently, so waiting on each in turn would serialise
                # what the add-in already parallelises.
                for tag, anchor in cells.items():
                    value, elapsed = self._settle(anchor, timeout=timeout)
                    if is_pending(value):
                        self._logger.warning(
                            "CitiVelocityExcelClient.open_stream: %s still pending after %.1fs "
                            "(cell %s). Leaving it live; read_stream will report it as absent "
                            "until it resolves.",
                            tag,
                            elapsed,
                            anchor,
                        )
        return cells

    def _write_stream_formula(
        self, anchor: str, formula: str, tag: str, *, attempts: int = 5
    ) -> None:
        """Set one ``CVSTREAM`` formula, retrying Excel's transient refusals.

        ``com_retry`` covers the two documented busy HRESULTs and win32com's
        AttributeError, but a burst of RTD subscriptions produces a *different*
        rejection: ``com_error(-2147352567, 'Exception occurred.', (0, None, None,
        None, 0, -2146777998))`` - measured on the 45th consecutive stream write.
        It is transient and clears in under a second, so it is retried with
        backoff rather than allowed to abort a daemon that has already placed 44
        live cells.

        The retry is bounded and re-raises with the tag named, because the same
        error shape would also be produced by a genuinely bad formula, and a
        daemon that retried that forever would look like a hang.
        """
        last: Optional[BaseException] = None
        for attempt in range(max(1, attempts)):
            try:
                com_retry(lambda: setattr(self._ws.Range(anchor), "Formula", formula))
                return
            except Exception as exc:  # noqa: BLE001 - re-raised below if persistent
                last = exc
                self._logger.debug(
                    "open_stream: %s at %s rejected (attempt %d/%d): %s",
                    tag, anchor, attempt + 1, attempts, exc,
                )
                time.sleep(0.5 * (attempt + 1))
        raise CitiVelocityError(
            f"CVSTREAM formula for {tag!r} at {anchor} was refused {attempts} times "
            f"({last}). Excel may be saturated with RTD subscriptions - reduce the number of "
            "streamed curves, or raise stream_write_pause."
        ) from last

    @property
    def has_open_stream(self) -> bool:
        """True once :meth:`open_stream` has written a live RTD cell."""
        return bool(self._streaming)

    def read_stream(
        self, cells: Optional[Mapping[str, str]] = None
    ) -> Dict[str, Optional[float]]:
        """Current value of each streaming cell. **Reads only - never writes.**

        A tag whose cell is still pending, or has resolved to an Excel error,
        comes back as ``None`` rather than as a number. That distinction is the
        whole point: an RTD cell that has stopped updating still holds its last
        value, so the caller needs the timestamp discipline of the layer above to
        decide whether a number is current.
        """
        target = dict(cells) if cells is not None else dict(self._streaming)
        out: Dict[str, Optional[float]] = {}
        with EXCEL_LOCK:
            for tag, anchor in target.items():
                try:
                    value = com_retry(lambda: self._ws.Range(anchor).Value)
                except Exception as exc:  # noqa: BLE001 - one bad cell is not the batch
                    self._logger.debug("read_stream: %s (%s) failed: %s", tag, anchor, exc)
                    out[tag] = None
                    continue
                if is_pending(value) or (isinstance(value, int) and excel_error_name(value)):
                    out[tag] = None
                    continue
                out[tag] = coerce_float(value)
        return out

    # -- CVCURVE / CVCURVEBOND ------------------------------------------

    def curve(self, curve_tag: str, *, timeout: Optional[float] = None) -> pd.DataFrame:
        """Fetch a ``CVCURVE`` grid.

        The block layout of ``CVCURVE``/``CVCURVEBOND`` is entitled but was not
        exercised during design (the run that would have verified it crashed
        Excel first), so the parser locates the header by content and does not
        assume the ``CVTSHIST`` shape.
        """
        return self._curve_call("CVCURVE", curve_tag, timeout=timeout)

    def curve_bond(self, curve_tag: str, *, timeout: Optional[float] = None) -> pd.DataFrame:
        """Fetch a ``CVCURVEBOND`` grid: ``Date | ISIN | Description | <measure>``."""
        return self._curve_call("CVCURVEBOND", curve_tag, timeout=timeout)

    def _curve_call(self, fn: str, curve_tag: str, *, timeout: Optional[float] = None) -> pd.DataFrame:
        formula = f'={fn}("{curve_tag}")'
        with EXCEL_LOCK:
            rows, value, elapsed = self._write_and_read(formula, rows_needed=64, timeout=timeout)
        if is_pending(value):
            raise AsyncTimeoutError([curve_tag], elapsed, formula)
        if not rows:
            err = excel_error_name(value)
            if err:
                raise CitiVelocityError(f"{fn}({curve_tag!r}) returned {err}")
            return pd.DataFrame()
        return parse_curve_block(rows)

    # -- validation -----------------------------------------------------

    def validate(
        self,
        tags: Sequence[str],
        *,
        freq: str = "DAILY",
        period: str = "1W",
        chunk_size: Optional[int] = None,
    ) -> Dict[str, str]:
        """Classify each tag ``valid`` | ``empty`` | ``<failure reason>``.

        Validation goes through ``CVTSHIST``, never ``CVMETADATA``: it is the path
        we actually fetch through, it degrades per column rather than poisoning a
        batch, and it validates many tags per call. ``CVMETADATA`` reported ZERO
        valid tenors for ``RATES.OIS.USD_SOFR.SWAP_SPREAD`` while ``CVTSHIST``
        serves all eleven - trusting it would silently drop a whole family.

        ``empty`` means the tag is well-formed and recognised but returned no rows
        in this window; some families (notably bond ``OAS``) need a window longer
        than ``1W`` to show data, so ``empty`` is not evidence of an invalid tag.
        """
        wanted = list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))
        out: Dict[str, str] = {}
        if not wanted:
            return out
        size = int(chunk_size or min(self._chunk_size, 15))
        prev_chunk = self._chunk_size
        self._chunk_size = size
        try:
            served = self.fetch_timeseries(wanted, freq, period=period)
        finally:
            self._chunk_size = prev_chunk
        failures = self.last_failures()
        for tag in wanted:
            if tag in served:
                out[tag] = "valid"
            else:
                out[tag] = failures.get(tag, "unknown")
        return out

    def validate_with_controls(
        self,
        tags: Sequence[str],
        *,
        controls: Sequence[str] = (
            "RATES.OIS.USD_SOFR.PAR.10Y",
            "RATES.VOL.USD.ATM_RFR.NORMAL.ANNUAL.1Y.10Y",
        ),
        freq: str = "DAILY",
        period: str = "1W",
    ) -> Dict[str, str]:
        """:meth:`validate`, but refuse to report unless known-good controls pass.

        Two validators in the design session produced confident wrong numbers
        (``0/1673`` valid, and "13% fetchable") and controls are what caught them.
        A validator that is itself broken reports failure everywhere and looks
        exactly like a genuine negative result.
        """
        control_result = self.validate(list(controls), freq=freq, period=period)
        bad = {t: v for t, v in control_result.items() if v != "valid"}
        if bad:
            raise CitiVelocityError(
                "Control tags failed, so this validation run cannot be trusted and is "
                f"refusing to report: {bad}"
            )
        return self.validate(tags, freq=freq, period=period)
