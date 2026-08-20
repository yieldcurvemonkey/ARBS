"""The contract every holdings provider honours, and the three failure modes it must not blur.

Why this file exists
--------------------
``providers/ishares.py`` learned its lessons expensively and wrote them down. A second
and third issuer must not re-learn them, and -- more importantly -- must not learn a
*different* set, because the panel builder in ``RVUtils/ETFRebalance/holdings_panel.py``
reads all issuers through one set of column names and one ``Asset Class`` filter. An
issuer whose frame calls par ``faceAmount`` does not fail; it produces an empty book,
silently, and every weight computed from it is wrong by the amount that went missing.
:func:`validate_frame` is what turns that into an exception at parse time.

The three outcomes a fetch can have, which are NOT interchangeable
------------------------------------------------------------------
``None``      -- the host answered 200 with something that is not a holdings document.
                 This is the ONLY genuine "there is no file for this date".
``Blocked``   -- the host refused (403/429/5xx). A refusal is not a data point. The
                 iShares backfill recorded 2,515 WAF refusals as absences and exited 0;
                 the manifest it wrote would have been honoured by the resume that was
                 meant to catch the failure.
``LayoutChanged`` -- the document arrived and is a holdings document, but its shape is
                 not the one this parser was written against. Guessing a header row is
                 how every column shifts by one and nothing complains.

A fourth, specific to the two current-only issuers added in 2026-08
-------------------------------------------------------------------
Neither SSGA nor Vanguard honours a date parameter. Vanguard's is accepted and **silently
ignored**: ``?asOfDate=2026-06-30`` returns HTTP 200 with ``asOfDate 2026-07-31`` in the
body and no error. A fetcher that keyed on the request would write a year of identical
month-end snapshots under twelve different dates. Every provider therefore keys on the
date the DOCUMENT reports, and :func:`check_requested_date` makes a disagreement visible
to the caller instead of smoothing it over.
"""

from __future__ import annotations

import datetime
import random
import re
import time
import warnings
from dataclasses import dataclass
from typing import Optional, Sequence

import pandas as pd
import requests

__all__ = [
    "HoldingsFile", "FetchError", "Blocked", "LayoutChanged", "WrongDocument",
    "IgnoredDateRequest", "BLOCKED_STATUSES", "REQUIRED_COLS", "OPTIONAL_ANALYTIC_COLS",
    "validate_frame", "check_weight_units", "isin_check_digit_ok", "isin_to_cusip",
    "ISIN_RE", "WEIGHT_GATE_MIN_ROWS", "WEIGHT_GATE_BAND",
    "check_requested_date", "get_with_retries", "BROWSER_HEADERS",
]


# --------------------------------------------------------------------------- the record


@dataclass(frozen=True)
class HoldingsFile:
    """One published holdings document, already parsed.

    ``as_of`` is what the document says about itself. ``requested`` is what the caller
    asked for. They are separate fields precisely because they disagree routinely, and
    the store keys rows on ``as_of`` while the manifest keys attempts on ``requested``.
    """

    ticker: str
    as_of: datetime.date          # the date the DOCUMENT claims, not the one requested
    requested: datetime.date
    shares_outstanding: float     # NaN when the issuer does not publish it -- see below
    content_sha1: str
    frame: pd.DataFrame

    @property
    def honoured_request(self) -> bool:
        """Did the host serve the date that was asked for?

        False for every SSGA and Vanguard fetch that names a past date, because neither
        endpoint has a date parameter that does anything. Exposed as a property so a
        caller can branch on it rather than re-deriving the comparison and getting the
        timezone or the type wrong.
        """
        return self.as_of == self.requested


class FetchError(RuntimeError):
    pass


class Blocked(FetchError):
    """The host refused the request. Distinct from "there is no file for this date"."""


class LayoutChanged(FetchError):
    """A holdings document arrived in a shape this parser was not written against.

    Raised rather than guessed at. The concrete hazard on the SSGA workbook is a fixed
    row offset: the header sits at row 4 today, and if a preamble line is added or
    removed a hard-coded offset reads a data row as the header, after which every column
    in the frame is one row out of alignment and the numbers still look like numbers.
    """


class WrongDocument(FetchError):
    """The document is well formed but describes a different fund than the one asked for."""


class IgnoredDateRequest(FetchError):
    """The host answered 200 for a date it then did not serve."""


#: Statuses that mean "the host is refusing you", never "this date has no file".
#:
#: 403 is the important one and it was learned the hard way. A six-worker iShares
#: backfill over 2016-2026 succeeded 143 times and was then served ``403 Access Denied``
#: -- an Akamai WAF page, not a fund document -- for the remaining 2,515 days. The first
#: version of that fetcher returned ``None`` for any non-200, so the runner wrote 2,515
#: rows asserting that iShares publishes no holdings for most of TLT's history. It ran to
#: completion, exited 0, and produced a manifest that resume would have honoured.
BLOCKED_STATUSES = frozenset({403, 429, 500, 502, 503, 504})


# --------------------------------------------------------------------------- the frame


#: Columns every provider's frame MUST carry, whatever the issuer calls them on the wire.
#:
#: This list is the union of what two downstream readers index directly:
#:   * ``RVUtils/ETFRebalance/holdings_panel.HOLDING_COLS`` and its ``Asset Class`` /
#:     ``Sector`` / ``shares_outstanding`` lookups, and
#:   * ``MDP/ETFHoldings/store.append_holdings`` / ``coverage``, which key on
#:     ``["date", "CUSIP"]``.
#:
#: It is duplicated here rather than imported so that ``MDP`` does not depend on
#: ``RVUtils``. ``tests/test_etf_providers.py`` asserts the two agree, so the duplication
#: cannot drift without a red test.
REQUIRED_COLS: tuple[str, ...] = (
    "ticker", "date", "Name", "Asset Class", "Sector", "CUSIP",
    "Par Value", "Market Value", "Weight (%)", "Maturity", "Coupon (%)",
    "Price", "Mod. Duration", "YTM (%)",
    "shares_outstanding", "requested_date",
)

#: Analytics iShares publishes and the other two do not. Present as all-NaN columns for
#: SSGA and Vanguard so the frame schema is one schema; a NaN here means "this issuer
#: does not publish it", and the panel takes those numbers from ARBS reference data
#: anyway.
OPTIONAL_ANALYTIC_COLS: tuple[str, ...] = ("Price", "Mod. Duration", "YTM (%)")


def validate_frame(df: pd.DataFrame, *, ticker: str, source: str) -> None:
    """Refuse a frame that downstream code would read as an empty book.

    ``holdings_panel.load_holdings`` filters on ``Asset Class == "Fixed Income"`` and
    indexes ``Sector`` and ``shares_outstanding`` directly. A missing filter column is a
    ``KeyError`` (loud, fine); a *present* filter column that never takes the expected
    value is silence -- the fund appears to hold nothing and every bucket weight built
    from it is wrong. Both are checked here, at parse time, where the fix is obvious.
    """
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise LayoutChanged(
            f"{source} {ticker}: parsed frame is missing required columns {missing}. "
            f"Downstream (holdings_panel.HOLDING_COLS, store.append_holdings) indexes "
            f"these by name; a frame without them joins to nothing."
        )
    if df.empty:
        raise LayoutChanged(f"{source} {ticker}: parsed frame has zero rows.")
    n_fi = int((df["Asset Class"].astype(str) == "Fixed Income").sum())
    if n_fi == 0:
        raise LayoutChanged(
            f"{source} {ticker}: {len(df)} rows parsed but NONE classified 'Fixed "
            f"Income'. holdings_panel filters on exactly that string, so this document "
            f"would silently produce an empty book rather than an error."
        )


#: A complete fund book. Below this the weight-units gate is skipped, because a
#: two-position stub has no reason to sum to anything in particular.
WEIGHT_GATE_MIN_ROWS = 20

#: How far the published weights may sum from 100 before the document is refused.
#: Measured over the whole book: SPTL 99.40, VGLT 99.96, EDV 99.98 -- the residual is
#: receivables and payables the holdings file does not list. The band is deliberately
#: wide, because it is not a precision check; it exists to catch a factor of 100.
WEIGHT_GATE_BAND = (50.0, 150.0)


def check_weight_units(df: pd.DataFrame, *, ticker: str, source: str) -> None:
    """Refuse a document whose weight column changed units under us.

    An issuer switching ``Weight`` from percent (``2.29``) to fraction (``0.0229``) is a
    change nothing else would notice: the numbers stay numbers, the frame stays the same
    shape, and every active weight downstream comes out a hundred times too small --
    which reads as "this fund tracks its index almost perfectly", the most plausible
    possible wrong answer. This repo has already paid for one 100x units flip of exactly
    this kind (STIRFO ``delta_abs`` quoted in percent, hedges sized 100x).

    Only applied to a complete book (``WEIGHT_GATE_MIN_ROWS``). Test fixtures and any
    genuinely tiny fund are exempt, and say so, rather than being silently waived.
    """
    if len(df) < WEIGHT_GATE_MIN_ROWS:
        return
    total = float(pd.to_numeric(df["Weight (%)"], errors="coerce").sum(skipna=True))
    lo, hi = WEIGHT_GATE_BAND
    if not (lo <= total <= hi):
        raise LayoutChanged(
            f"{source} {ticker}: the {len(df)} published weights sum to {total:.4f}, "
            f"outside [{lo}, {hi}]. A complete book sums to ~100 in PERCENT. "
            f"{'This looks like a fraction, i.e. a factor of 100. ' if total < 5 else ''}"
            f"Storing it would make every active weight in this fund wrong by that "
            f"factor, and the result would look like unusually tight index tracking."
        )


# --------------------------------------------------------------------------- identifiers


ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def _isin_body_digits(isin: str) -> str:
    out = []
    for ch in isin[:11]:
        out.append(ch if ch.isdigit() else str(ord(ch) - 55))
    return "".join(out)


def isin_check_digit_ok(isin: str) -> bool:
    """Luhn check on the letter-expanded ISIN body.

    Worth the twelve lines: SSGA publishes an ``Identifier`` column that mixes ISINs
    with internal 9-character codes (``924QSGII3`` for the SSgA government money market
    fund, ``999USDZ92`` for the USD cash line). Slicing ``[2:11]`` off one of those
    produces a nine-character string that *looks* exactly like a CUSIP and joins to
    nothing -- or, worse, to the wrong bond. The check digit is what separates the two
    populations without a hand-maintained exclusion list.
    """
    if not isinstance(isin, str) or not ISIN_RE.match(isin):
        return False
    total = 0
    for i, ch in enumerate(reversed(_isin_body_digits(isin))):
        d = int(ch)
        if i % 2 == 0:                     # the digit adjacent to the check digit doubles
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(isin[11])


def isin_to_cusip(isin: str) -> Optional[str]:
    """``US912810UU06`` -> ``912810UU0``. ``None`` when the input is not a US ISIN.

    Only ``US``-prefixed ISINs embed a CUSIP as their NSIN. A ``GB``/``XS`` ISIN sliced
    the same way yields nine characters of a completely different numbering scheme, so
    the prefix is checked rather than assumed -- a Treasury fund will never hit that
    branch, and the first fund that does will get ``None`` instead of a fabricated CUSIP.
    """
    if not isinstance(isin, str):
        return None
    s = isin.strip().upper()
    if not s.startswith("US") or not isin_check_digit_ok(s):
        return None
    return s[2:11]


# --------------------------------------------------------------------------- date guard


def check_requested_date(
    hf: HoldingsFile,
    *,
    asked: bool,
    strict: bool,
    source: str,
) -> HoldingsFile:
    """Make an ignored date request visible.

    ``asked`` is False when the caller wanted "whatever is current" -- the normal mode
    for the two current-only issuers, where a mismatch is expected and silence is
    correct. It is True when the caller named a date. In that case the mismatch is the
    thing that would corrupt the panel, so it warns always and raises under ``strict``.
    """
    if not asked or hf.honoured_request:
        return hf
    msg = (
        f"{source} {hf.ticker}: asked for {hf.requested}, the document reports "
        f"{hf.as_of}. This endpoint has no working date parameter -- it serves the "
        f"current file and says nothing. The row is keyed on {hf.as_of}."
    )
    if strict:
        raise IgnoredDateRequest(msg)
    warnings.warn(msg, RuntimeWarning, stacklevel=3)
    return hf


# --------------------------------------------------------------------------- transport


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def get_with_retries(
    url: str,
    *,
    ticker: str,
    label: str,
    headers: Optional[dict] = None,
    session: Optional[requests.Session] = None,
    pool=None,
    max_attempts: int = 4,
    timeout: float = 30.0,
    allow_redirects: bool = True,
    ok_statuses: Sequence[int] = (200,),
) -> requests.Response:
    """One GET, retried across exits, that raises on refusal instead of returning it.

    ``pool`` is a :class:`~MDP.ETFHoldings.proxy_pool.ProxyPool`. When given, each
    attempt takes a different exit and a refusal benches only that exit -- a WAF counts
    per IP, so retrying from the address that was just refused is a wasted request.
    Without a pool this falls back to the direct connection, which is fine for a handful
    of dates and is exactly what tripped the block on twenty thousand.

    Returns the response only for a status in ``ok_statuses``. Everything else raises
    :class:`Blocked`, so no caller can accidentally record a refusal as absence.
    """
    last: Optional[str] = None
    hdrs = {**BROWSER_HEADERS, **(headers or {})}

    for attempt in range(max_attempts):
        ex = pool.acquire() if pool is not None else None
        sess = ex.session if ex is not None else (session or requests)
        proxies = ex.proxies if ex is not None else None

        try:
            resp = sess.get(url, headers=hdrs, timeout=timeout, proxies=proxies,
                            allow_redirects=allow_redirects)
        except Exception as exc:            # network flake -- retry, possibly elsewhere
            last = f"{type(exc).__name__}: {exc}"
            if ex is not None:
                pool.report_blocked(ex, transient=True)
            else:
                time.sleep(min(30.0, 2.0 ** attempt) + random.random())
            continue

        if resp.status_code in BLOCKED_STATUSES:
            last = f"HTTP {resp.status_code}"
            if ex is not None:
                pool.report_blocked(ex)
            else:
                wait = float(resp.headers.get("Retry-After", 0) or 0) or min(
                    90.0, 5.0 * 2.0 ** attempt)
                time.sleep(wait + random.random())
            continue

        if resp.status_code not in ok_statuses:
            raise Blocked(f"{label} {ticker}: unexpected HTTP {resp.status_code}")

        if ex is not None:
            pool.report_ok(ex)
        return resp

    raise Blocked(f"{label} {ticker}: refused after {max_attempts} attempts ({last})")
