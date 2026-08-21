"""State Street (SPDR) daily holdings, from the ``holdings-daily-us-en-{ticker}.xlsx`` file.

The endpoint
------------
``https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/
holdings-daily-us-en-{ticker}.xlsx``

Measured 2026-08-20 for SPTL: HTTP 200, 25,902 bytes, ``PK\\x03\\x04`` zip magic,
``application/vnd.openxmlformats-officedocument.spreadsheetml.sheet``. The request
**301-redirects** to the same path without the ``/us/en/intermediary`` segment, so
``allow_redirects`` must stay on; a fetcher that turned it off would receive a 301 body
and, if it mapped non-200 to "no file", record an absence for a fund that publishes
every business day.

What the workbook looks like (SPTL, 2026-08-19)
-----------------------------------------------
One sheet, ``holdings``, 195 rows x 9 columns::

    r0  Fund Name:      State Street(R) SPDR(R) Portfolio Long Te...
    r1  Ticker Symbol:  SPTL
    r2  Holdings:       As of 19-Aug-2026
    r3  (blank)
    r4  Name | Identifier | SEDOL | Weight | Coupon | Par Value | Market Value |
        Local Currency | Maturity
    r5+ 109 data rows, then blanks, then seven disclaimer lines that occupy column 0 only

**Nothing here is read off a fixed offset.** The header row is located by looking for the
row that contains both ``Name`` and ``Identifier``; the as-of line by scanning the cells
above it for ``As of ...``. If either cannot be found the parse raises
:class:`~MDP.ETFHoldings.providers._base.LayoutChanged` rather than falling back to
row 4 -- a preamble line added or removed upstream would otherwise shift every column by
one row and the numbers would still parse as numbers.

Three issuer-specific traps
---------------------------
**1. ``Identifier`` is an ISIN, not a CUSIP.** ``US912810UU06`` -> ``912810UU0``. But the
column is not homogeneous: SPTL's file also carries ``924QSGII3`` (the SSgA government
money-market sweep, 1.07% of the fund) and ``999USDZ92`` (the USD cash line). Slicing
``[2:11]`` off those yields nine characters that look exactly like a CUSIP. The ISIN
check digit is what separates the two populations, so it is verified rather than
assumed; a row whose identifier is not a valid US ISIN is classified into the cash
bucket and keeps its raw identifier as its key.

**2. There is no shares-outstanding line.** SSGA does not publish a share count in this
file, so ``shares_outstanding`` is ``NaN`` -- not zero, and not derived from anything.
The consequence is concrete and must not be discovered later: ``holdings_panel``
computes ``par_per_share = par / shares_out``, so it is NaN for this fund, and the
``par_per_share`` signal in ``signals.py`` is therefore **dead** for SPTL rather than
merely noisy. ``ETFSpec.publishes_shares_outstanding`` is the flag a caller checks to
refuse instead of quietly producing an all-NaN column. What the file *does* carry is
market value, so ``fund_market_value`` is written alongside as the honest normaliser.

**3. Current file only.** No date parameter was found; the URL has no ``asOfDate`` and
the path is not versioned. This provider therefore serves a *snapshot*: run it once a
business day and a forward panel accumulates. Asking it for a historical date returns
today's file, which is why :func:`fetch` warns when a caller names a date the document
does not report -- see ``_base.check_requested_date``.

Total market value ties out to the fund: $10.987bn across the 109 data rows against
$10.848bn AUM (etfdb, 2026-08-20). SPTL is a standalone ETF, so the document describes
the ETF. That is NOT true of the Vanguard funds -- see ``vanguard.py``.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import re
from typing import Optional

import numpy as np
import pandas as pd

from MDP.ETFHoldings.providers._base import (  # noqa: F401  (re-exported on purpose)
    BLOCKED_STATUSES,
    Blocked,
    FetchError,
    HoldingsFile,
    LayoutChanged,
    WrongDocument,
    check_requested_date,
    check_weight_units,
    get_with_retries,
    isin_to_cusip,
    validate_frame,
)

BASE_URL = (
    "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us"
    "/holdings-daily-us-en-{ticker}.xlsx"
)

HEADERS = {
    "Accept": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
               "application/vnd.ms-excel,*/*"),
    "Referer": "https://www.ssga.com/us/en/intermediary/etfs/fund-finder",
}

#: The columns the workbook is expected to have, and what each becomes in the shared
#: schema. ``Identifier`` is handled separately because it needs converting, not renaming.
COLUMN_MAP = {
    "Name": "Name",
    "Weight": "Weight (%)",
    "Coupon": "Coupon (%)",
    "Par Value": "Par Value",
    "Market Value": "Market Value",
    "Maturity": "Maturity",
    "SEDOL": "SEDOL",
    "Local Currency": "Currency",
}

#: Cells that must both appear in a row for it to be the header row.
_HEADER_KEYS = ("name", "identifier")

#: How far into the sheet the header is allowed to be. Generous -- the point of the scan
#: is to survive a preamble line being added, not to allow the header anywhere at all.
_MAX_HEADER_SCAN = 30

_RE_ASOF = re.compile(r"as\s+of\s*:?\s*(.+?)\s*$", re.IGNORECASE)
_RE_TICKER_LABEL = re.compile(r"^\s*ticker\s*symbol\s*:?\s*$", re.IGNORECASE)

#: A workbook is a zip. Anything else from this URL is an error page, not a holdings doc.
_ZIP_MAGIC = b"PK\x03\x04"


def _cells(row: pd.Series) -> list[str]:
    return [str(v).strip() for v in row.tolist() if not (isinstance(v, float) and np.isnan(v))]


def _find_header_row(raw: pd.DataFrame) -> int:
    for i in range(min(_MAX_HEADER_SCAN, len(raw))):
        low = {c.lower() for c in _cells(raw.iloc[i])}
        if all(k in low for k in _HEADER_KEYS):
            return i
    raise LayoutChanged(
        "ssga: no row in the first "
        f"{min(_MAX_HEADER_SCAN, len(raw))} contains both 'Name' and 'Identifier'. "
        "The header row moved or was renamed; reading a fixed offset from here would "
        "shift every column."
    )


def _find_as_of(raw: pd.DataFrame, header_row: int) -> datetime.date:
    for i in range(header_row):
        for cell in _cells(raw.iloc[i]):
            m = _RE_ASOF.search(cell)
            if m is None:
                continue
            try:
                return pd.Timestamp(m.group(1)).date()
            except Exception as exc:
                raise LayoutChanged(
                    f"ssga: found an 'As of' cell {cell!r} whose date will not parse: {exc}"
                ) from exc
    raise LayoutChanged(
        "ssga: no 'As of <date>' cell above the header row. Without the document's own "
        "date the row would have to be keyed on the request, and this endpoint serves "
        "the current file whatever you ask for."
    )


def _check_ticker(raw: pd.DataFrame, header_row: int, ticker: str) -> None:
    """The URL is keyed by ticker and 301-redirects. Confirm we got the fund we asked for."""
    for i in range(header_row):
        cells = _cells(raw.iloc[i])
        for j, cell in enumerate(cells):
            if _RE_TICKER_LABEL.match(cell) and j + 1 < len(cells):
                got = cells[j + 1].strip().upper()
                if got and got != ticker.upper():
                    raise WrongDocument(
                        f"ssga: asked for {ticker.upper()} and the workbook says its "
                        f"ticker is {got}. A redirect served a different fund; storing "
                        f"this would attribute one fund's book to another."
                    )
                return


def parse(content: bytes, *, ticker: str, requested: datetime.date) -> Optional[HoldingsFile]:
    """Parse one SSGA holdings workbook.

    Returns ``None`` only when the bytes are not a workbook at all -- an HTML error page,
    an empty body, a maintenance stub. A workbook that *is* a holdings document but whose
    shape is unfamiliar raises :class:`LayoutChanged`, because from this URL a workbook
    is a holdings document by construction and an unrecognised shape means the layout
    moved, not that there is no file.
    """
    if not content or not content.startswith(_ZIP_MAGIC):
        return None
    try:
        xl = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    except Exception:
        return None

    names = {s.lower(): s for s in xl.sheet_names}
    if "holdings" in names:
        sheet = names["holdings"]
    elif len(xl.sheet_names) == 1:
        sheet = xl.sheet_names[0]
    else:
        raise LayoutChanged(
            f"ssga {ticker}: workbook has sheets {xl.sheet_names} and none is 'holdings'."
        )

    raw = xl.parse(sheet_name=sheet, header=None)
    if raw.empty:
        raise LayoutChanged(f"ssga {ticker}: sheet {sheet!r} is empty.")

    hdr = _find_header_row(raw)
    as_of = _find_as_of(raw, hdr)
    _check_ticker(raw, hdr, ticker)

    body = raw.iloc[hdr + 1:].copy()
    body.columns = [str(c).strip() for c in raw.iloc[hdr].tolist()]

    missing = [c for c in ("Name", "Identifier", "Weight", "Par Value", "Market Value",
                           "Maturity", "Coupon") if c not in body.columns]
    if missing:
        raise LayoutChanged(
            f"ssga {ticker}: header row {hdr} is missing columns {missing}; got "
            f"{list(body.columns)}."
        )

    # Disclaimer lines occupy column 0 only. A row with no identifier is not a position.
    body = body[body["Identifier"].notna()].copy()
    if body.empty:
        raise LayoutChanged(f"ssga {ticker}: header found at row {hdr} but no rows carry an Identifier.")

    ident = body["Identifier"].astype(str).str.strip().str.upper()
    cusip = ident.map(isin_to_cusip)
    is_security = cusip.notna()
    if not bool(is_security.any()):
        raise LayoutChanged(
            f"ssga {ticker}: {len(body)} rows parsed and NOT ONE Identifier converts to a "
            f"CUSIP (first few: {ident.head(3).tolist()}). The Identifier column moved."
        )

    name_u = body["Name"].astype(str).str.upper()
    out = pd.DataFrame(index=body.index)
    out["ticker"] = ticker.upper()
    out["date"] = pd.Timestamp(as_of)
    for src, dst in COLUMN_MAP.items():
        out[dst] = body[src] if src in body.columns else np.nan
    out["ISIN"] = ident.where(is_security)
    # A cash line keeps its own identifier as the key: NaN keys collapse together in
    # ``store.append_holdings``, which dedupes on ["date", "CUSIP"].
    out["CUSIP"] = cusip.where(is_security, ident)
    out["Asset Class"] = np.where(is_security, "Fixed Income", "Cash and/or Derivatives")
    out["Sector"] = np.where(
        ~is_security, "Cash",
        np.where(name_u.str.contains("STRIP", na=False), "Treasury STRIPS", "Treasuries"),
    )

    for c in ("Weight (%)", "Coupon (%)", "Par Value", "Market Value"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    out["Maturity"] = pd.to_datetime(out["Maturity"], format="%m/%d/%Y", errors="coerce")

    # Published by iShares, not by SSGA. Present as NaN so one schema serves all issuers.
    for c in ("Price", "Mod. Duration", "YTM (%)"):
        out[c] = np.nan

    # NOT published. NaN, never zero -- a zero share count would make par_per_share inf.
    out["shares_outstanding"] = np.nan
    out["fund_market_value"] = float(out["Market Value"].sum(skipna=True))
    out["requested_date"] = pd.Timestamp(requested)

    out = out.reset_index(drop=True)
    validate_frame(out, ticker=ticker, source="ssga")
    check_weight_units(out, ticker=ticker, source="ssga")

    return HoldingsFile(
        ticker=ticker.upper(),
        as_of=as_of,
        requested=requested,
        shares_outstanding=float("nan"),
        content_sha1=hashlib.sha1(content).hexdigest(),
        frame=out,
    )


def fetch(
    fund_id: str,
    requested: Optional[datetime.date] = None,
    *,
    ticker: str,
    session=None,
    pool=None,
    max_attempts: int = 4,
    timeout: float = 45.0,
    strict_date: bool = False,
) -> Optional[HoldingsFile]:
    """The current holdings workbook for one SPDR fund.

    ``fund_id`` is the ticker as it appears in the URL (``ETFSpec.fund_id``).
    ``requested`` is bookkeeping only -- there is no date parameter to send. Pass it and
    a mismatch against the document's own date warns (or raises under ``strict_date``);
    leave it ``None`` for "whatever is current", which is the normal mode.

    Returns ``None`` only for a 200 that is not a workbook. Any refusal raises
    :class:`Blocked` after its retries, so the caller pauses instead of recording absence.
    """
    asked = requested is not None
    req = requested or datetime.date.today()
    url = BASE_URL.format(ticker=fund_id.lower())

    resp = get_with_retries(
        url, ticker=ticker, label="ssga", headers=HEADERS, session=session, pool=pool,
        max_attempts=max_attempts, timeout=timeout, allow_redirects=True,
    )
    hf = parse(resp.content, ticker=ticker, requested=req)
    if hf is None:
        return None
    return check_requested_date(hf, asked=asked, strict=strict_date, source="ssga")
