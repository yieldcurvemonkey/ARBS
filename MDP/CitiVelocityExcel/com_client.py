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

#: The window used when the caller asks for "everything". The add-in truncates to
#: the tag's own history, so this is a ceiling rather than a promise.
DEFAULT_FULL_PERIOD = "50Y"

#: Excel's formula length ceiling, with headroom for the fixed arguments.
_MAX_FORMULA_CHARS = 8_000


def probe_readiness(
    app: Any, *, timeout: float = 90.0, poll: float = 0.5
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
    workbook = None
    try:
        com_retry(lambda: app.Workbooks.Count, attempts=4, delay=0.25)
        workbook = com_retry(lambda: app.Workbooks.Add())
        sheet = com_retry(lambda: workbook.Worksheets(1))
        com_retry(lambda: setattr(sheet.Range("A1"), "Formula", "=CVTODAY()"))
        deadline = time.time() + max(0.0, timeout)
        while True:
            value = com_retry(lambda: sheet.Range("A1").Value)
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
        return "unusable", workbook


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

        if self._app is not None and self._wb is None:
            self._wb = com_retry(lambda: self._app.Workbooks.Add())
        if self._wb is not None:
            self._ws = com_retry(lambda: self._wb.Worksheets(1))
            self._row = 1 + self._gap  # A1 may hold a readiness probe

    @classmethod
    def connect(cls, *, attempts: int = 6, delay: float = 10.0, **kwargs: Any) -> "CitiVelocityExcelClient":
        """Bind to a running, signed-in Excel and open a scratch workbook.

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
                app, wb = cls._bind_once(readiness_timeout=float(kwargs.get("readiness_timeout", 90.0)))
                return cls(app=app, workbook=wb, **kwargs)
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
    def _bind_once(*, readiness_timeout: float = 90.0) -> Tuple[Any, Any]:
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
            status, wb = probe_readiness(app, timeout=max(1.0, readiness_timeout))
            if status != "unusable":
                saw_excel = True
            if status == "ready":
                return app, wb
            if status == "not_signed_in":
                saw_name_error = True
            if wb is not None:
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
        self._closed = True
        with EXCEL_LOCK:
            time.sleep(self._drain_seconds)
            if self._wb is not None:
                try:
                    self._wb.Close(SaveChanges=False)
                except Exception as exc:  # noqa: BLE001
                    self._logger.warning("CitiVelocityExcelClient: workbook close failed: %s", exc)
            self._wb = None
            self._ws = None

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

    @staticmethod
    def _parse_scalar_grid(
        rows: Sequence[Sequence[Any]],
        tags: Sequence[str],
    ) -> Dict[str, Tuple[Optional[float], Optional[datetime.datetime]]]:
        """Map a ``CVLATEST``/``CVSNAP`` grid onto ``{tag: (value, stamp)}``.

        Both functions answer either as a column-per-tag block with a header row
        (the ``CVTSHIST`` shape) or as one row per tag. Both are handled, and the
        row form is only used when the header form does not apply, so a header
        that happens to be absent never silently shifts the mapping.
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

        body = [r for r in rows if r and any(c is not None for c in r)]
        if len(body) == len(tags):
            for tag, cells in zip(tags, body):
                value = None
                stamp = None
                for cell in cells:
                    if value is None:
                        value = coerce_float(cell)
                    if stamp is None:
                        stamp = coerce_excel_datetime(cell)
                out[tag] = (value, stamp)
            return out

        return {t: (None, None) for t in tags}

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
