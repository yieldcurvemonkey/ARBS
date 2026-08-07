r"""A faithful fake of the Excel COM surface the Citi Velocity add-in exposes.

This is test support that ships with the package rather than living under
``tests/``, for two reasons: the equivalence tests, the cache tests and the
notebook all need the same fake, and a fake that lives beside the client it
imitates is the one that gets updated when the client changes.

The fake reproduces the layout the real add-in was observed to produce, not a
convenient simplification of it:

* the formula text lands in the anchor cell as a **string**;
* the header+data block starts **one row down and one column LEFT** of the
  anchor - a resolved call at ``C1`` published
  ``=Sheet1!$C$1:$D$1,Sheet1!$B$2:$D$24``. This is exactly the offset that makes
  index-based header location wrong, so the fake must reproduce it or the
  header-by-content rule is never actually tested;
* data rows are **newest first**;
* the extent is published as a two-area defined name ``CvFunction_<row>_<col>``;
* ``CurrentRegion`` absorbs adjacent cells, so it can be wider than the block;
* the first ``pending_reads`` reads of the anchor return the ``#GETTING_DATA``
  sentinel (``-2146826245``) rather than a blank.

Use :class:`FakeVelocityData` to declare what the add-in should serve, then
:class:`FakeExcelApp` as the ``app=`` argument to
:class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient`.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.excel_constants import (
    EXCEL_EPOCH_ORDINAL,
    GETTING_DATA_ERR,
    NAME_ERR,
    VALUE_ERR,
)

__all__ = [
    "FakeVelocityData",
    "FakeExcelApp",
    "FakeWorkbook",
    "FakeWorksheet",
    "FakeRange",
    "to_excel_serial",
]

_ADDR_RE = re.compile(r"^\$?(?P<col>[A-Z]{1,3})\$?(?P<row>\d+)$", re.IGNORECASE)
_FORMULA_RE = re.compile(r"^=\s*(?P<fn>[A-Za-z_][A-Za-z0-9_]*)\s*\((?P<args>.*)\)\s*$", re.DOTALL)


def _col_to_index(col: str) -> int:
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - 64)
    return n


def _index_to_col(idx: int) -> str:
    out = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def to_excel_serial(when: datetime.datetime) -> float:
    """Convert a naive datetime to the Excel serial the add-in sometimes writes."""
    days = when.date().toordinal() - EXCEL_EPOCH_ORDINAL
    frac = (when.hour * 3600 + when.minute * 60 + when.second) / 86_400.0
    return float(days) + frac


def _split_args(args: str) -> List[str]:
    """Split a formula argument list on commas that are not inside quotes."""
    out: List[str] = []
    depth = 0
    in_quotes = False
    current = ""
    for ch in args:
        if ch == '"':
            in_quotes = not in_quotes
            current += ch
            continue
        if not in_quotes:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                out.append(current)
                current = ""
                continue
        current += ch
    out.append(current)
    return [a.strip().strip('"') for a in out]


# ------------------------------------------------------------------ #
#                         the served data set                        #
# ------------------------------------------------------------------ #


@dataclass
class FakeVelocityData:
    """What the fake add-in serves.

    Parameters
    ----------
    series
        ``{tag: pandas.Series}`` with a ``DatetimeIndex``. The fake slices these
        by the requested window and emits them newest-first, exactly as the
        add-in does.
    bad_tags
        Tags for which the fake writes ``Bad tag: <tag>`` into the column's first
        data cell while every other column in the same call answers normally -
        the per-column degradation that makes a bad tag cost only its own column.
    poison_metadata_tags
        Tags that hard-fail a whole ``CVMETADATA`` batch to ``#VALUE!``, forcing
        the client to bisect. ``RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y`` does this in
        reality even when probed alone.
    metadata
        ``{tag: (description, history_start, history_end)}``.
    curves
        ``{curve_tag: pandas.DataFrame}`` served by ``CVCURVE``/``CVCURVEBOND``.
    date_as_serial
        When True, ``Date`` cells are written as Excel serial floats instead of
        datetimes. Both forms occur in reality depending on the number format the
        add-in applied, and the parser must accept both.
    udf_registered
        When False, every ``CV*`` formula resolves to ``#NAME?`` - the signature
        of an Excel that is running but not signed in to Velocity.
    """

    series: Dict[str, pd.Series] = field(default_factory=dict)
    bad_tags: set[str] = field(default_factory=set)
    poison_metadata_tags: set[str] = field(default_factory=set)
    metadata: Dict[str, Tuple[str, Optional[datetime.datetime], Optional[datetime.datetime]]] = field(
        default_factory=dict
    )
    curves: Dict[str, pd.DataFrame] = field(default_factory=dict)
    date_as_serial: bool = False
    udf_registered: bool = True
    price_point_in_header: bool = True
    #: How much a CVSTREAM cell moves per read, so "it ticks" is assertable.
    stream_tick: float = 1e-5
    stream_reads: Dict[str, int] = field(default_factory=dict)
    #: Model the add-in's silent span-driven downsampling. Measured 2026-08-07:
    #: an ``MI01`` request spanning 6 days serves 1-minute data and one spanning
    #: 7 days serves 10-minute, at any age. The block looks identical either way,
    #: which is what makes it dangerous - so the fake reproduces it, and the
    #: windowed fetcher's spacing guard has something real to catch.
    #: Setting this False is the mutation that proves the guard has teeth.
    downsample_cliff: bool = True

    # -- helpers --------------------------------------------------------

    def _stamp(self, when: pd.Timestamp) -> Any:
        py = when.to_pydatetime()
        return to_excel_serial(py) if self.date_as_serial else py

    #: What the add-in degrades to, per requested frequency, once the span
    #: exceeds the widest window that frequency is served at. From the measured
    #: ladder in ``MDP.CitiVelocityExcel.windowed``.
    _CLIFF: ClassVar[Dict[str, Tuple[datetime.timedelta, str]]] = {
        "MI01": (datetime.timedelta(days=6), "10min"),
        "MI10": (datetime.timedelta(days=60), "60min"),
        "HOURLY": (datetime.timedelta(days=120), "1D"),
    }

    def _apply_cliff(self, s: pd.Series, *, freq: str, start: str, end: str) -> pd.Series:
        """Coarsen ``s`` the way the add-in does when the span is too wide."""
        if not self.downsample_cliff or s.empty:
            return s
        entry = self._CLIFF.get((freq or "").upper())
        if entry is None:
            return s
        cap, coarse = entry
        if start and end:
            span = _parse_bound(end) - _parse_bound(start)
        else:
            span = s.index.max() - s.index.min()
        if span <= cap:
            return s
        return s.resample(coarse).last().dropna()

    def _window(
        self,
        s: pd.Series,
        *,
        period: str,
        start: str,
        end: str,
        freq: str = "",
    ) -> pd.Series:
        out = s
        if start:
            out = out[out.index >= _parse_bound(start)]
        if end:
            out = out[out.index <= _parse_bound(end)]
        if period and not start and period.upper() != "MAX":
            # "MAX" means the tag's whole history, so there is nothing to trim.
            # The rest are <n><D|W|M|Y|H|I> from the add-in's closed vocabulary;
            # the intraday units are minutes/hours.
            unit = period[-1].upper()
            n = int(period[:-1])
            per_unit = {"I": 1 / 1440, "H": 1 / 24, "D": 1, "W": 7, "M": 31, "Y": 366}
            if unit not in per_unit:
                return out
            if not out.empty:
                cutoff = out.index.max() - pd.Timedelta(days=per_unit[unit] * n)
                out = out[out.index >= cutoff]
        return self._apply_cliff(out, freq=freq, start=start, end=end)

    # -- block builders -------------------------------------------------

    def tshist_block(self, args: Sequence[str]) -> Any:
        """Build the block a ``CVTSHIST`` call would produce."""
        if not self.udf_registered:
            return NAME_ERR
        tags = [t.strip() for t in (args[0] if args else "").split(",") if t.strip()]
        freq = args[1] if len(args) > 1 else ""
        period = args[2] if len(args) > 2 else ""
        start = args[3] if len(args) > 3 else ""
        end = args[4] if len(args) > 4 else ""
        point = (args[5] if len(args) > 5 else "CLOSE") or "CLOSE"

        frames: Dict[str, pd.Series] = {}
        for tag in tags:
            if tag in self.bad_tags:
                continue
            s = self.series.get(tag)
            if s is None:
                continue
            frames[tag] = self._window(s, period=period, start=start, end=end, freq=freq)

        index = pd.DatetimeIndex([])
        for s in frames.values():
            index = index.union(s.index)
        index = index.sort_values(ascending=False)  # newest first

        suffix = f" - {point}" if self.price_point_in_header else ""
        header: List[Any] = ["Date"] + [f"{t}{suffix}" for t in tags]
        rows: List[List[Any]] = [header]
        for i, stamp in enumerate(index):
            row: List[Any] = [self._stamp(stamp)]
            for tag in tags:
                if tag in self.bad_tags:
                    row.append(f"Bad tag: {tag}" if i == 0 else None)
                    continue
                s = frames.get(tag)
                if s is None or stamp not in s.index:
                    row.append(None)
                else:
                    row.append(float(s.loc[stamp]))
            rows.append(row)
        if len(rows) == 1:
            # Header only: every requested tag returned no rows in this window.
            rows.append(["" ] + [None] * len(tags))
        return rows

    def metadata_block(self, args: Sequence[str]) -> Any:
        if not self.udf_registered:
            return NAME_ERR
        tags = [t.strip() for t in (args[0] if args else "").split(",") if t.strip()]
        if any(t in self.poison_metadata_tags for t in tags):
            return VALUE_ERR
        rows: List[List[Any]] = [["Description", "Start Date", "End Date"]]
        for tag in tags:
            meta = self.metadata.get(tag)
            if meta is None:
                rows.append([f"Error: Invalid Tag / No data available. Tag = {tag}", None, None])
                continue
            desc, hstart, hend = meta
            rows.append(
                [
                    desc,
                    self._stamp(pd.Timestamp(hstart)) if hstart is not None else None,
                    self._stamp(pd.Timestamp(hend)) if hend is not None else None,
                ]
            )
        return rows

    def latest_block(self, args: Sequence[str]) -> Any:
        if not self.udf_registered:
            return NAME_ERR
        tags = [t.strip() for t in (args[0] if args else "").split(",") if t.strip()]
        rows: List[List[Any]] = []
        for tag in tags:
            s = self.series.get(tag)
            if s is None or s.empty:
                rows.append([None, None])
            else:
                rows.append([float(s.iloc[-1]), self._stamp(s.index[-1])])
        return rows

    def snap_block(self, args: Sequence[str]) -> Any:
        if not self.udf_registered:
            return NAME_ERR
        tags = [t.strip() for t in (args[0] if args else "").split(",") if t.strip()]
        when = _parse_bound(args[1]) if len(args) > 1 and args[1] else None
        rows: List[List[Any]] = []
        for tag in tags:
            s = self.series.get(tag)
            if s is None or s.empty:
                rows.append([None, None])
                continue
            sub = s if when is None else s[s.index <= when]
            if sub.empty:
                rows.append([None, None])
            else:
                rows.append([float(sub.iloc[-1]), self._stamp(sub.index[-1])])
        return rows

    def curve_block(self, args: Sequence[str]) -> Any:
        if not self.udf_registered:
            return NAME_ERR
        tag = args[0] if args else ""
        df = self.curves.get(tag)
        if df is None:
            return VALUE_ERR
        rows: List[List[Any]] = [list(df.columns)]
        for _, r in df.iterrows():
            rows.append(
                [
                    self._stamp(pd.Timestamp(v)) if isinstance(v, (pd.Timestamp, datetime.datetime)) else v
                    for v in r.tolist()
                ]
            )
        return rows

    def today_block(self, args: Sequence[str]) -> Any:
        if not self.udf_registered:
            return NAME_ERR
        return [[self._stamp(pd.Timestamp(datetime.date.today()))]]

    def stream_block(self, args: Sequence[str]) -> Any:
        """A live ``CVSTREAM`` cell: ONE scalar, which moves on every read.

        Both properties are measured, not invented (2026-08-07):

        * ``CVSTREAM("a,b,c")`` returned a single scalar - the FIRST tag's - so
          the comma-separated list is silently truncated to one. The fake does the
          same, which is what lets a test prove the caller writes one cell per tag
          instead of assuming a batch;
        * the same cell read 25 s apart returned ``4.05612604557329`` then
          ``4.05596231843847``. The drift here is deterministic rather than random
          so a test can assert "it moved" without a seed.
        """
        if not self.udf_registered:
            return NAME_ERR
        raw = (args[0] if args else "").split(",")
        tag = raw[0].strip()
        series = self.series.get(tag)
        if series is None or series.empty:
            return VALUE_ERR
        self.stream_reads[tag] = self.stream_reads.get(tag, 0) + 1
        base = float(series.iloc[-1])
        return [[base + self.stream_tick * self.stream_reads[tag]]]

    def dispatch(self, fn: str, args: Sequence[str]) -> Any:
        handler: Optional[Callable[[Sequence[str]], Any]] = {
            "CVTSHIST": self.tshist_block,
            "CVMETADATA": self.metadata_block,
            "CVLATEST": self.latest_block,
            "CVSNAP": self.snap_block,
            "CVSTREAM": self.stream_block,
            "CVCURVE": self.curve_block,
            "CVCURVEBOND": self.curve_block,
            "CVTODAY": self.today_block,
            "CVNOW": self.today_block,
        }.get(fn.upper())
        if handler is None:
            return NAME_ERR
        return handler(args)


def _parse_bound(token: str) -> pd.Timestamp:
    text = str(token).strip()
    if len(text) == 8 and text.isdigit():
        return pd.Timestamp(datetime.datetime.strptime(text, "%Y%m%d"))
    if len(text) == 12 and text.isdigit():
        return pd.Timestamp(datetime.datetime.strptime(text, "%Y%m%d%H%M"))
    return pd.Timestamp(text)


# ------------------------------------------------------------------ #
#                          the COM surface                           #
# ------------------------------------------------------------------ #


class FakeRange:
    """A single cell or rectangular range on a :class:`FakeWorksheet`."""

    def __init__(self, sheet: "FakeWorksheet", row: int, col: int, n_rows: int = 1, n_cols: int = 1):
        self._sheet = sheet
        self.Row = int(row)
        self.Column = int(col)
        self._n_rows = int(n_rows)
        self._n_cols = int(n_cols)

    # -- geometry -------------------------------------------------------

    @property
    def Rows(self) -> Any:
        return _Count(self._n_rows)

    @property
    def Columns(self) -> Any:
        return _Count(self._n_cols)

    @property
    def Areas(self) -> Any:
        return _Areas([self])

    # -- content --------------------------------------------------------

    @property
    def Formula(self) -> Any:
        return self._sheet.cells.get((self.Row, self.Column))

    @Formula.setter
    def Formula(self, value: Any) -> None:
        self._sheet.write_formula(self.Row, self.Column, value)

    @property
    def Value(self) -> Any:
        if self._n_rows == 1 and self._n_cols == 1:
            return self._sheet.read(self.Row, self.Column)
        rows = []
        for r in range(self.Row, self.Row + self._n_rows):
            rows.append(
                tuple(self._sheet.read(r, c) for c in range(self.Column, self.Column + self._n_cols))
            )
        return tuple(rows)

    @Value.setter
    def Value(self, value: Any) -> None:
        """Write a literal (not a formula) into a single cell.

        Used for the workbook reuse marker; a formula would be evaluated, and the
        marker is deliberately inert.
        """
        if self._n_rows == 1 and self._n_cols == 1:
            self._sheet.cells[(self.Row, self.Column)] = value
            return
        raise ValueError("FakeRange.Value: only a single cell can be assigned")

    @property
    def CurrentRegion(self) -> "FakeRange":
        """The contiguous populated rectangle around this cell.

        Deliberately greedy, like the real thing: it absorbs adjacent cells, so a
        parser that trusts it for row offsets reads the wrong row.
        """
        occupied = {(r, c) for (r, c) in self._sheet.cells if self._sheet.cells[(r, c)] is not None}
        if not occupied:
            return FakeRange(self._sheet, self.Row, self.Column, 1, 1)

        seen: set[Tuple[int, int]] = set()
        stack = [(self.Row, self.Column)]
        while stack:
            cell = stack.pop()
            if cell in seen:
                continue
            seen.add(cell)
            r, c = cell
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nxt = (r + dr, c + dc)
                    if nxt in occupied and nxt not in seen:
                        stack.append(nxt)
        seen = {cell for cell in seen if cell in occupied} or {(self.Row, self.Column)}
        rows = [r for r, _ in seen]
        cols = [c for _, c in seen]
        top, bottom = min(rows), max(rows)
        left, right = min(cols), max(cols)
        return FakeRange(self._sheet, top, left, bottom - top + 1, right - left + 1)


class _Count:
    def __init__(self, count: int):
        self.Count = int(count)


class _Areas:
    def __init__(self, areas: Sequence[FakeRange]):
        self._areas = list(areas)
        self.Count = len(self._areas)

    def __call__(self, i: int) -> FakeRange:
        return self._areas[int(i) - 1]


class _MultiAreaName:
    def __init__(self, areas: Sequence[FakeRange]):
        self._areas = list(areas)

    @property
    def RefersToRange(self) -> Any:
        return _MultiAreaRange(self._areas)


class _MultiAreaRange:
    def __init__(self, areas: Sequence[FakeRange]):
        self._areas = list(areas)

    @property
    def Areas(self) -> _Areas:
        return _Areas(self._areas)


class _Names:
    def __init__(self):
        self._names: Dict[str, _MultiAreaName] = {}

    def __call__(self, name: str) -> _MultiAreaName:
        try:
            return self._names[str(name)]
        except KeyError as exc:
            raise AttributeError(f"No defined name {name!r}") from exc

    def define(self, name: str, areas: Sequence[FakeRange]) -> None:
        self._names[str(name)] = _MultiAreaName(areas)


class FakeWorksheet:
    """A sparse cell grid that resolves ``CV*`` formulas through a data set."""

    def __init__(self, book: "FakeWorkbook", name: str):
        self.book = book
        self.Name = name
        self.cells: Dict[Tuple[int, int], Any] = {}
        self._pending: Dict[Tuple[int, int], int] = {}
        #: Cells holding a live CVSTREAM formula, re-evaluated on every read so
        #: the fake actually behaves like RTD. Measured on the real add-in: the
        #: same cell 25 s apart returned 4.05612604557329 then 4.05596231843847.
        self._stream_cells: Dict[Tuple[int, int], Sequence[str]] = {}
        self.Names = _Names()
        #: Set by tests that need to prove a refused delete is survivable rather
        #: than fatal - Excel does refuse, and the backfill must carry on.
        self.refuse_delete = False

    # -- lifecycle ------------------------------------------------------

    def Delete(self) -> None:
        """Drop this sheet from its workbook, as ``Worksheet.Delete`` does."""
        if self.refuse_delete:
            raise RuntimeError("Excel refused to delete the sheet")
        if self in self.book.sheets:
            self.book.sheets.remove(self)
            self.book.sheets_deleted.append(self.Name)

    # -- addressing -----------------------------------------------------

    @property
    def UsedRange(self) -> FakeRange:
        """The rectangle spanning every populated cell on the sheet.

        Unlike ``CurrentRegion`` this is not contiguity-based: it covers
        everything, which is exactly what a client reusing a workbook needs in
        order to start below all of it.
        """
        occupied = [(r, c) for (r, c), v in self.cells.items() if v is not None]
        if not occupied:
            return FakeRange(self, 1, 1, 1, 1)
        rows = [r for r, _ in occupied]
        cols = [c for _, c in occupied]
        top, bottom = min(rows), max(rows)
        left, right = min(cols), max(cols)
        return FakeRange(self, top, left, bottom - top + 1, right - left + 1)

    def Range(self, addr: str) -> FakeRange:
        m = _ADDR_RE.match(str(addr).strip())
        if not m:
            raise ValueError(f"FakeWorksheet.Range: unsupported address {addr!r}")
        return FakeRange(self, int(m.group("row")), _col_to_index(m.group("col")))

    # -- content --------------------------------------------------------

    def read(self, row: int, col: int) -> Any:
        key = (row, col)
        if key in self._stream_cells and not self._pending.get(key, 0):
            # A live RTD cell: its value is whatever the feed says NOW, not what
            # it said when the formula was written.
            fresh = self.book.app.data.dispatch("CVSTREAM", self._stream_cells[key])
            if isinstance(fresh, list):
                self.cells[key] = fresh[0][0]
            else:
                self.cells[key] = fresh
            return self.cells[key]
        remaining = self._pending.get(key, 0)
        if remaining < 0:
            # Never settles - models an add-in that has stopped answering.
            return GETTING_DATA_ERR
        if remaining > 0:
            self._pending[key] = remaining - 1
            return GETTING_DATA_ERR
        return self.cells.get(key)

    def write_formula(self, row: int, col: int, formula: Any) -> None:
        text = str(formula)
        self.book.app.formulas.append((self.Name, f"{_index_to_col(col)}{row}", text))
        m = _FORMULA_RE.match(text.strip())
        if not m:
            self.cells[(row, col)] = formula
            return

        fn = m.group("fn")
        args = _split_args(m.group("args"))
        result = self.book.app.data.dispatch(fn, args)

        # The formula text itself lands in the anchor cell, as a string.
        self.cells[(row, col)] = text
        self._pending[(row, col)] = self.book.app.pending_reads

        if isinstance(result, int):
            # A scalar error replaces the anchor value entirely.
            self.cells[(row, col)] = result
            return

        if fn.upper() == "CVSTREAM":
            self._stream_cells[(row, col)] = args
            # A scalar does not spill: CVSTREAM's value lands in the ANCHOR cell
            # itself (measured - evaluate_formula saw the number as the settled
            # anchor value). Reproducing that here is what makes read_stream's
            # "read the anchor" strategy actually exercised.
            self.cells[(row, col)] = result[0][0]
            self.book.app.blocks.append((self.Name, row, col, 1, 1))
            self.Names.define(f"CvFunction_{row}_{col}", [FakeRange(self, row, col, 1, 1)])
            return

        # The block starts one row down and one column LEFT of the anchor.
        top = row + 1
        left = max(1, col - 1)
        self._check_overlap(top, left, result)
        width = 0
        for r_off, row_vals in enumerate(result):
            width = max(width, len(row_vals))
            for c_off, val in enumerate(row_vals):
                self.cells[(top + r_off, left + c_off)] = val
        height = len(result)
        self.book.app.blocks.append((self.Name, top, left, height, width))
        self.Names.define(
            f"CvFunction_{row}_{col}",
            [
                FakeRange(self, row, col, 1, 2),
                FakeRange(self, top, left, height, width),
            ],
        )

    def _check_overlap(self, top: int, left: int, block: Sequence[Sequence[Any]]) -> None:
        """Raise if this block would land on a live region.

        The real add-in does not raise - it throws
        ``System.AccessViolationException`` from inside ``ExcelRegistration..ctor``
        and takes the whole Excel process down, including the user's open
        workbook. The fake turns that into a loud test failure so the write
        discipline is actually exercised.
        """
        height = len(block)
        width = max((len(r) for r in block), default=0)
        for name, btop, bleft, bheight, bwidth in self.book.app.blocks:
            if name != self.Name:
                continue
            if top + height <= btop or btop + bheight <= top:
                continue
            if left + width <= bleft or bleft + bwidth <= left:
                continue
            raise AssertionError(
                f"AccessViolation: block at row {top}, col {left} ({height}x{width}) overlaps a live "
                f"CvFunction_* region at row {btop}, col {bleft} ({bheight}x{bwidth}). "
                "In the real add-in this kills the Excel process."
            )


class _Worksheets:
    def __init__(self, book: "FakeWorkbook"):
        self.book = book

    def __call__(self, index: int) -> FakeWorksheet:
        return self.book.sheets[int(index) - 1]

    def Add(self) -> FakeWorksheet:
        sheet = FakeWorksheet(self.book, f"Sheet{self.book.sheets_created + 1}")
        self.book.sheets.append(sheet)
        self.book.sheets_created += 1
        return sheet

    @property
    def Count(self) -> int:
        return len(self.book.sheets)


class FakeWorkbook:
    def __init__(self, app: "FakeExcelApp"):
        self.app = app
        self.sheets: List[FakeWorksheet] = [FakeWorksheet(self, "Sheet1")]
        self.closed = False
        self.saved = False
        self.Names = _Names()
        #: Sheets ever added, so a test can tell "created and dropped" from
        #: "never created" - the whole point of the per-window sheet lifecycle.
        self.sheets_created = 1
        self.sheets_deleted: List[str] = []

    @property
    def Worksheets(self) -> _Worksheets:
        return _Worksheets(self)

    def Close(self, SaveChanges: bool = False) -> None:  # noqa: N803 - COM name
        self.closed = True
        self.saved = bool(SaveChanges)
        if self in self.app.workbooks_list:
            self.app.workbooks_list.remove(self)


class _Workbooks:
    def __init__(self, app: "FakeExcelApp"):
        self.app = app

    def __call__(self, index: int) -> FakeWorkbook:
        """1-based indexing, like Excel's own collection.

        Needed so ``find_marked_workbook`` - which walks the collection looking
        for this package's reuse marker - is exercised hermetically.
        """
        return self.app.workbooks_list[int(index) - 1]

    def Add(self) -> FakeWorkbook:
        book = FakeWorkbook(self.app)
        self.app.workbooks_list.append(book)
        self.app.workbooks_created.append(book)
        return book

    @property
    def Count(self) -> int:
        if self.app.dead:
            raise AttributeError("Excel.Application.Workbooks")
        return len(self.app.workbooks_list)


class FakeExcelApp:
    """A fake Excel ``Application`` that records every formula written to it.

    Parameters
    ----------
    data
        What the add-in serves.
    pending_reads
        How many reads of a freshly-written anchor return ``#GETTING_DATA``
        before the value appears. ``0`` disables the sentinel entirely and is
        what the mutation check flips to prove the polling test has teeth.
        A NEGATIVE value never settles, which models an add-in that has stopped
        answering.
    dead
        When True, ``Workbooks.Count`` raises, simulating an Excel that went away
        mid-session.
    """

    def __init__(
        self,
        data: Optional[FakeVelocityData] = None,
        *,
        pending_reads: int = 2,
        dead: bool = False,
    ):
        self.data = data if data is not None else FakeVelocityData()
        self.pending_reads = int(pending_reads)
        self.dead = bool(dead)
        self.formulas: List[Tuple[str, str, str]] = []
        self.blocks: List[Tuple[str, int, int, int, int]] = []
        self.workbooks_list: List[FakeWorkbook] = []
        self.workbooks_created: List[FakeWorkbook] = []
        self.calculate_calls = 0
        #: Excel prompts before deleting a sheet with content; the client turns
        #: this off around the delete and restores it, and a test asserts it did.
        self.DisplayAlerts = True

    @property
    def Workbooks(self) -> _Workbooks:
        if self.dead:
            raise AttributeError("Excel.Application.Workbooks")
        return _Workbooks(self)

    def CalculateUntilAsyncQueriesDone(self) -> None:  # noqa: N802 - COM name
        self.calculate_calls += 1

    # -- assertions the tests use ---------------------------------------

    def formulas_for(self, fn: str) -> List[str]:
        """Every formula written for a given ``CV*`` function, in order."""
        prefix = f"={fn.upper()}("
        return [f for _, _, f in self.formulas if f.upper().startswith(prefix)]

    def anchors(self) -> List[str]:
        return [addr for _, addr, _ in self.formulas]
