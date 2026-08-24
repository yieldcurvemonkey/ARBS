r"""Pure parsers for the blocks the Citi Velocity add-in writes into Excel.

Nothing here touches COM. Every function takes the raw ``Range.Value`` payload -
a tuple of tuples of Python scalars - and returns tidy pandas objects, so the
whole parsing contract is testable without Excel.

Layout of a resolved ``CVTSHIST`` at anchor ``X1`` (verified live)::

    X1        the formula text, as a string
    X2:Z2     header row:  'Date' | '<tag> - CLOSE' | ...
    X3:Z...   data rows, NEWEST FIRST

Four gotchas are encoded here, each of which silently corrupts results if you
get it wrong:

1. **Pending cells are COM ints, not blanks.** ``#GETTING_DATA`` is
   ``-2146826245`` and ``#N/A`` is ``-2146826246``. Treating "non-empty" as
   "done" reads the sentinel as data.
2. **Locate the header row by CONTENT, never by index.** ``CurrentRegion``
   absorbs adjacent cells (the ``A1`` readiness probe did exactly this), which
   shifts every row; a hardcoded ``rows[1]`` then reads the formula row and every
   tag is misreported as "no column".
3. **Dates arrive as Excel serials OR as ``pywintypes.datetime``**, depending on
   the number format the add-in happened to apply. Both must be accepted.
4. **``CVTSHIST`` degrades per column.** A bad tag yields the literal string
   ``Bad tag: <tag>`` in that column's first data cell while every other tag in
   the same call returns normally, so a failure is per-tag and must not discard
   the batch.
"""

from __future__ import annotations

import datetime
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.excel_constants import (
    BAD_TAG_PREFIX,
    EXCEL_EPOCH_ORDINAL,
    PENDING_SENTINELS,
    XL_ERRORS,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "TshistBlock",
    "MetadataRow",
    "is_pending",
    "excel_error_name",
    "coerce_excel_datetime",
    "coerce_float",
    "normalise_block",
    "find_header_row",
    "split_header",
    "parse_tshist_block",
    "parse_metadata_block",
    "parse_curve_block",
]

# "RATES.OIS.USD_SOFR.PAR.10Y - CLOSE" -> ("RATES.OIS.USD_SOFR.PAR.10Y", "CLOSE")
_HEADER_SPLIT_RE = re.compile(r"^(?P<tag>.+?)\s+-\s+(?P<point>[A-Za-z_]+)\s*$")

#: How far down a block we look for the header row. A block whose header is not
#: in the first this-many rows is malformed, not merely offset.
_HEADER_SCAN_ROWS = 24


# ------------------------------------------------------------------ #
#                          scalar coercion                           #
# ------------------------------------------------------------------ #


def is_pending(value: Any) -> bool:
    """True when ``value`` means "the add-in has not answered yet".

    This is the single most important predicate in the package. The naive
    alternative - ``value is not None`` means done - reads ``#GETTING_DATA``
    (``-2146826245``) as a data point.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    if isinstance(value, int) and value in PENDING_SENTINELS:
        return True
    if isinstance(value, str):
        stripped = value.strip()
        # The add-in briefly writes its own progress text before the async value
        # lands ("Requesting data...", "!..."), which is not an answer either.
        if stripped.startswith("Requesting") or stripped.startswith("!"):
            return True
    return False


def excel_error_name(value: Any) -> Optional[str]:
    """Return ``'#VALUE!'``-style text when ``value`` is an Excel error int."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return XL_ERRORS.get(value)
    return None


def coerce_excel_datetime(value: Any) -> Optional[datetime.datetime]:
    """Coerce a Citi ``Date`` cell to a naive :class:`datetime.datetime`.

    Accepts, in this order:

    * ``datetime``/``date`` (this covers ``pywintypes.datetime``, which subclasses
      ``datetime.datetime``) - tz-aware values are converted to naive local wall
      clock, because the add-in reports the feed's own wall clock and mixing tz
      and naive stamps in one index breaks every downstream ``asof``;
    * a numeric Excel serial (``46238.0`` etc.);
    * an ISO-ish string.

    Returns ``None`` for anything that is not a date, including error sentinels.
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime(value.year, value.month, value.day)

    if isinstance(value, (int, float)):
        if excel_error_name(value) is not None:
            return None
        serial = float(value)
        if not math.isfinite(serial) or serial <= 0 or serial > 2_958_465:  # 9999-12-31
            return None
        days = int(serial)
        frac = serial - days
        try:
            base = datetime.date.fromordinal(EXCEL_EPOCH_ORDINAL + days)
        except (ValueError, OverflowError):
            return None
        # Round to the second: Excel serials carry float noise that otherwise
        # turns 09:31:00 into 09:30:59.999998 and breaks exact-minute alignment.
        seconds = int(round(frac * 86_400.0))
        return datetime.datetime.combine(base, datetime.time()) + datetime.timedelta(seconds=seconds)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            ts = pd.to_datetime(text, errors="raise")
        except Exception:
            return None
        if ts is pd.NaT:
            return None
        ts = pd.Timestamp(ts)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        return ts.to_pydatetime()

    return None


def coerce_float(value: Any) -> Optional[float]:
    """Coerce a data cell to ``float``; ``None`` for blanks, errors and text."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if excel_error_name(value) is not None:
            return None
        out = float(value)
        return out if math.isfinite(out) else None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text or text.startswith(BAD_TAG_PREFIX) or text.startswith("Error"):
            return None
        try:
            out = float(text)
        except ValueError:
            return None
        return out if math.isfinite(out) else None
    return None


# ------------------------------------------------------------------ #
#                           block plumbing                           #
# ------------------------------------------------------------------ #


def normalise_block(raw: Any) -> List[List[Any]]:
    """Normalise a ``Range.Value`` payload to a list of row lists.

    A multi-cell range comes back as a tuple of tuples; a single-row range as a
    tuple of scalars; a 1x1 range as a bare scalar. All three shapes occur.
    """
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        rows: List[List[Any]] = []
        for row in raw:
            if isinstance(row, (list, tuple)):
                rows.append(list(row))
            else:
                rows.append([row])
        return rows
    return [[raw]]


def find_header_row(
    rows: Sequence[Sequence[Any]],
    *,
    first_cell: str = "Date",
    max_scan: int = _HEADER_SCAN_ROWS,
) -> Optional[int]:
    """Index of the header row, located by CONTENT.

    Never locate it by index: ``CurrentRegion`` absorbs adjacent cells, which
    shifts every row down and makes a hardcoded offset read the formula row.
    """
    wanted = str(first_cell).strip().lower()
    for i, row in enumerate(rows[:max_scan]):
        if not row:
            continue
        head = row[0]
        if isinstance(head, str) and head.strip().lower() == wanted:
            return i
    return None


def split_header(header: Any) -> Tuple[Optional[str], Optional[str]]:
    """Split ``'<tag> - CLOSE'`` into ``(tag, price_point)``.

    Returns ``(None, None)`` for the ``Date`` column and anything unparseable.
    """
    if not isinstance(header, str):
        return (None, None)
    text = header.strip()
    if not text:
        return (None, None)
    m = _HEADER_SPLIT_RE.match(text)
    if m is None:
        return (None, None)
    return (m.group("tag").strip(), m.group("point").strip().upper())


def _column_for_tag(headers: Sequence[Any], tag: str) -> Optional[int]:
    """Locate ``tag``'s column by header text, not by request position.

    Exact match on the parsed tag first; a prefix match is the fallback for
    header spellings that do not carry a ``" - <PRICEPOINT>"`` suffix. The
    prefix form is safe because Velocity tags are dot-separated, so one tag can
    only prefix another across a ``'.'``, never across the ``' '`` we require.
    """
    for j, h in enumerate(headers):
        parsed, _ = split_header(h)
        if parsed is not None and parsed == tag:
            return j
    for j, h in enumerate(headers):
        if isinstance(h, str) and h.strip() == tag:
            return j
    for j, h in enumerate(headers):
        if isinstance(h, str) and h.strip().startswith(tag + " "):
            return j
    return None


# ------------------------------------------------------------------ #
#                              CVTSHIST                              #
# ------------------------------------------------------------------ #


@dataclass
class TshistBlock:
    """Parsed result of one ``CVTSHIST`` call.

    ``series`` holds one ascending, de-duplicated :class:`pandas.Series` per tag
    that returned data. ``failures`` holds a short reason per tag that did not,
    so a bad tag costs its own column and nothing else.
    """

    series: Dict[str, pd.Series] = field(default_factory=dict)
    failures: Dict[str, str] = field(default_factory=dict)
    headers: List[str] = field(default_factory=list)
    n_rows: int = 0
    #: Body rows that belonged to a DIFFERENT block in the same region and were
    #: discarded. Non-zero means the region held more than one block, which is a
    #: defect in the caller's sheet cursor, not in the data - see
    #: :func:`_one_block_only`. Reported rather than silently swallowed, because
    #: truncating quietly is how the caller stops finding out.
    foreign_rows: int = 0

    @property
    def ok(self) -> bool:
        return not self.failures

    def frame(self) -> pd.DataFrame:
        """The populated tags as one wide, time-indexed frame."""
        if not self.series:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"))
        out = pd.concat(self.series, axis=1)
        out.index.name = "Date"
        return out.sort_index()


def _one_block_only(
    body: Sequence[Sequence[Any]],
    *,
    first_cell: str = "Date",
) -> Tuple[List[Sequence[Any]], int]:
    """Cut ``body`` at the first row that belongs to a DIFFERENT block.

    Why this is needed
    ------------------
    ``find_header_row`` already defends the HEADER against a region that holds
    more than one block ("``CurrentRegion`` absorbs adjacent cells"). Nothing
    defended the BODY. So when the sheet cursor was left inside a live spill and
    the next ``CVTSHIST`` landed inside it, the region came back holding two
    blocks, the FIRST header won, and every row of the SECOND block was read as
    data for the first block's columns - by position.

    That is not a hypothetical. It put swaption normal vol under 36 of the 44
    ``RATES.OIS.USD_SOFR.PAR.*`` tags back to 2015-10-08, and under CAD_CORRA and
    JPY_TONAR_LCH as well, because ``DEFAULT_CHUNK_SIZE`` is 44 and so is a par
    grid: column j of one block is column j of the other, one for one.

    Three independent markers, because a region can be cut so that any one of
    them is absent:

    ``a second header row``
        A ``Date`` first cell cannot recur inside one block.
    ``a formula row``
        A first cell beginning ``=`` is the next call's own formula text.
    ``the dates stop being monotone``
        A ``CVTSHIST`` body runs one way (newest-first from the add-in) and a
        second block restarts at its own newest row. The direction is MEASURED
        from the first two dated rows rather than assumed, so an oldest-first
        block is not truncated at row two; a repeated stamp is not a reversal,
        because the parser's own contract allows one across a chunk seam.

    Returns ``(body_up_to_the_seam, n_rows_discarded)``.
    """
    wanted = str(first_cell).strip().lower()
    direction = 0  # +1 ascending, -1 descending, 0 not yet known
    last: Optional[datetime.datetime] = None

    for i, row in enumerate(body):
        head = row[0] if row else None

        if isinstance(head, str):
            text = head.strip()
            if text.lower() == wanted or text.startswith("="):
                return list(body[:i]), len(body) - i

        stamp = coerce_excel_datetime(head) if row else None
        if stamp is None:
            # A blank or unparseable first cell is not by itself a seam - the
            # add-in pads blocks - but it carries no ordering evidence either.
            continue
        if last is not None:
            if stamp > last:
                step = 1
            elif stamp < last:
                step = -1
            else:
                step = 0  # a repeated stamp across a chunk seam; not a reversal
            if step != 0:
                if direction == 0:
                    direction = step
                elif step != direction:
                    return list(body[:i]), len(body) - i
        last = stamp

    return list(body), 0


def parse_tshist_block(
    raw: Any,
    tags: Sequence[str],
    *,
    price_point: str = "CLOSE",
) -> TshistBlock:
    """Parse a ``CVTSHIST`` block into one series per requested tag.

    Parameters
    ----------
    raw
        The ``Range.Value`` payload of the block (or an already-normalised list
        of row lists).
    tags
        The tags that were requested, in request order. Columns are matched by
        HEADER TEXT rather than position, so a partially-served call still maps
        correctly.
    price_point
        Recorded on the result for provenance; column matching does not depend
        on it, because the add-in has been observed to echo the price point in
        the header for some families and omit it for others.

    Returns
    -------
    TshistBlock
        ``series`` for tags that returned data, ``failures`` for the rest. A tag
        whose column is present but whose first data cell reads ``Bad tag: ...``
        is a failure; a tag whose column is present and empty is recorded as
        ``"empty"`` - the add-in distinguishes "no such tag" from "no rows in
        this window" and so must we.
    """
    _ = price_point
    rows = raw if isinstance(raw, list) and (not raw or isinstance(raw[0], list)) else normalise_block(raw)
    out = TshistBlock(n_rows=0)

    tag_list = list(dict.fromkeys(tags))
    if len(rows) < 2:
        for t in tag_list:
            out.failures[t] = "no block"
        return out

    hdr_i = find_header_row(rows)
    if hdr_i is None:
        for t in tag_list:
            out.failures[t] = "no header row"
        return out

    headers = [c if isinstance(c, str) else ("" if c is None else str(c)) for c in rows[hdr_i]]
    out.headers = headers
    # ONE block only. A region that holds two blocks is a caller defect, and
    # reading the second one's rows by column position is how swaption vol got
    # banked under the OIS par tags - see :func:`_one_block_only`.
    body, foreign = _one_block_only(rows[hdr_i + 1 :])
    out.foreign_rows = foreign
    if foreign:
        _logger.warning(
            "parse_tshist_block: the region held %d row(s) belonging to another "
            "block below this one; they were discarded. The sheet cursor was left "
            "inside a live spill - the first requested tag was %s.",
            foreign,
            next(iter(dict.fromkeys(tags)), "(none)"),
        )
    out.n_rows = len(body)

    stamps: List[Optional[datetime.datetime]] = [
        coerce_excel_datetime(r[0]) if r else None for r in body
    ]

    for tag in tag_list:
        col = _column_for_tag(headers, tag)
        if col is None:
            out.failures[tag] = "no column"
            continue

        first_cell = body[0][col] if body and col < len(body[0]) else None
        if isinstance(first_cell, str) and first_cell.strip().startswith(BAD_TAG_PREFIX):
            out.failures[tag] = "bad tag"
            continue
        err = excel_error_name(first_cell)
        if err is not None and first_cell not in PENDING_SENTINELS:
            out.failures[tag] = err
            continue

        idx: List[datetime.datetime] = []
        vals: List[float] = []
        for r, stamp in zip(body, stamps):
            if stamp is None:
                continue
            cell = r[col] if col < len(r) else None
            v = coerce_float(cell)
            if v is None:
                continue
            idx.append(stamp)
            vals.append(v)

        if not idx:
            out.failures[tag] = "empty"
            continue

        s = pd.Series(vals, index=pd.DatetimeIndex(idx, name="Date"), name=tag, dtype="float64")
        # The block is newest-first and can repeat a stamp across chunk seams.
        s = s[~s.index.duplicated(keep="first")].sort_index()
        out.series[tag] = s

    return out


# ------------------------------------------------------------------ #
#                             CVMETADATA                             #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class MetadataRow:
    """One ``CVMETADATA`` row: description plus the tag's history bounds."""

    tag: str
    description: Optional[str]
    history_start: Optional[datetime.datetime]
    history_end: Optional[datetime.datetime]
    ok: bool

    @property
    def failed(self) -> bool:
        return not self.ok


def parse_metadata_block(raw: Any, tags: Sequence[str]) -> Dict[str, MetadataRow]:
    """Parse a ``CVMETADATA`` block.

    The layout depends on whether ANY tag in the call resolved: with at least one
    valid tag, row 0 is a header starting ``Description``; with none, there is no
    header at all and the error text sits at the anchor. Both are handled.

    ``CVMETADATA`` is NOT a sound validator - it hard-fails to ``#VALUE!`` for
    tags that exist and serve data but carry no metadata (the whole
    ``SWAP_SPREAD`` family does this). Validate through ``CVTSHIST`` instead; use
    this only for description and history bounds.
    """
    rows = normalise_block(raw)
    tag_list = list(dict.fromkeys(tags))
    out: Dict[str, MetadataRow] = {}

    if rows:
        head = str(rows[0][0]).strip().lower() if rows[0] else ""
        if head.startswith("description"):
            rows = rows[1:]

    if len(rows) != len(tag_list):
        # Row count mismatch: refuse to guess which row belongs to which tag.
        for t in tag_list:
            out[t] = MetadataRow(t, None, None, None, ok=False)
        return out

    for tag, cells in zip(tag_list, rows):
        desc = cells[0] if cells else None
        desc_text = None if desc is None else str(desc).strip()
        failed = bool(desc_text) and desc_text.startswith("Error")
        out[tag] = MetadataRow(
            tag=tag,
            description=None if failed else desc_text,
            history_start=coerce_excel_datetime(cells[1]) if len(cells) > 1 else None,
            history_end=coerce_excel_datetime(cells[2]) if len(cells) > 2 else None,
            ok=not failed and bool(desc_text),
        )
    return out


# ------------------------------------------------------------------ #
#                       CVCURVE / CVCURVEBOND                        #
# ------------------------------------------------------------------ #


def parse_curve_block(raw: Any, *, header_first_cell: str = "Date") -> pd.DataFrame:
    """Parse a ``CVCURVE`` / ``CVCURVEBOND`` grid into a DataFrame.

    ``CVCURVEBOND`` returns ``Date | ISIN | Description | <measure>``; ``CVCURVE``
    returns a comparable grid whose first column is a date. The header row is
    located by content exactly as for ``CVTSHIST``; if no ``Date`` header is
    found the first row is taken as the header, because the block layout of these
    two functions was entitled-but-unexercised at design time and must not be
    assumed to match ``CVTSHIST``.
    """
    rows = normalise_block(raw)
    if not rows:
        return pd.DataFrame()

    hdr_i = find_header_row(rows, first_cell=header_first_cell)
    if hdr_i is None:
        # Fall back to the first row that is entirely strings - the formula row
        # is a single string in column 0 with blanks after it.
        hdr_i = 0
        for i, row in enumerate(rows[: _HEADER_SCAN_ROWS]):
            non_null = [c for c in row if c is not None and str(c).strip() != ""]
            if len(non_null) >= 2 and all(isinstance(c, str) for c in non_null):
                hdr_i = i
                break

    headers = [("" if c is None else str(c).strip()) for c in rows[hdr_i]]
    body = [r for r in rows[hdr_i + 1 :] if any(c is not None and str(c).strip() != "" for c in r)]
    if not body:
        return pd.DataFrame(columns=headers)

    width = len(headers)
    padded = [list(r[:width]) + [None] * max(0, width - len(r)) for r in body]
    df = pd.DataFrame(padded, columns=headers)

    for col in df.columns:
        if col.strip().lower() == "date":
            df[col] = [coerce_excel_datetime(v) for v in df[col]]
        elif col.strip().lower() in {"isin", "description", "cusip", "ticker"}:
            df[col] = [None if v is None else str(v).strip() for v in df[col]]
        else:
            coerced = [coerce_float(v) for v in df[col]]
            # Only numeric-ify a column that is actually numeric; otherwise a
            # descriptive column silently becomes all-NaN.
            if any(v is not None for v in coerced):
                df[col] = coerced
    return df
