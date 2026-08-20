"""iShares daily holdings, from BlackRock's ``get-fund-document`` endpoint.

The endpoint
------------
``https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1/
get-fund-document?...&portfolioId={pid}&asOfDate={YYYYMMDD}&component=holdings``

It returns **CSV**, not JSON, with a keyed preamble (fund name, holdings as-of date,
inception, shares outstanding) followed by a blank line and then the holdings table.
Measured 2026-08-20: it serves a dated file for every business day back to at least
2016-01-04, and the holdings header has not changed a single column between 2021-01-04
and 2026-08-19.

Three things the caller must not get wrong
------------------------------------------
**1. The as-of date in the file is the key, never the requested date.** Ask for a market
holiday and the endpoint still answers 200 with a file. Requesting 2026-06-19
(Juneteenth) returned a document that produced a zero-change day against 2026-06-18 --
i.e. the previous file served again. Keying on the request would have written a
duplicate row and made ``diff()`` book a real day of rebalancing as two half-days.
:func:`parse` therefore returns the date the *document* claims, and the writer keys on
that.

**2. The document is a point-in-time snapshot published AFTER the close it describes.**
Nothing in this module knows when it was published; the panel builder enforces the
execution lag. See ``RVUtils/ETFRebalance/panel.py``.

**3. Numbers arrive as thousands-separated strings and "-" means missing.**
``Par Value`` of ``"2,243,213,900.00"`` parses to a float only with ``thousands=","``,
and a ``"-"`` in ``Duration`` is absence, not zero -- a zero duration on a 30-year bond
would sail through every downstream check.

Rate limiting
-------------
No documented limit. The fetcher below is deliberately unhurried and 429-aware: a prior
ARBS project took a rate-limit storm from an unthrottled, 429-blind intraday fetcher and
recorded thousands of empty responses as data. Backoff here is exponential with a cap,
and a request that never succeeds returns ``None`` rather than an empty frame.
"""

from __future__ import annotations

import datetime
import hashlib
import io
import random
import re
import time
from typing import Optional

import pandas as pd
import requests

from MDP.ETFHoldings.providers import _base

BASE_URL = (
    "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v1"
    "/get-fund-document"
    "?appType=PRODUCT_PAGE&appSubType=ISHARES&targetSite=us-ishares&locale=en_US"
    "&portfolioId={pid}&userType=individual&asOfDate={date}&component=holdings"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.ishares.com/us/products/etf-investments",
}

#: Every numeric column in the holdings table. Anything not here stays a string.
NUMERIC_COLS = (
    "Market Value", "Weight (%)", "Notional Value", "Par Value", "Price",
    "Duration", "YTM (%)", "FX Rate", "Coupon (%)", "Mod. Duration",
    "Yield to Call (%)", "Yield to Worst (%)", "Real Duration", "Real YTM (%)",
)

_RE_ASOF = re.compile(r'Fund Holdings as of,"([^"]+)"')
_RE_SHARES = re.compile(r'Shares Outstanding,"?([\d,\.]+)"?')
_RE_HEADER = re.compile(r"^Name,Sector,Asset Class,", re.MULTILINE)


#: The record, the exceptions and the refusal set now live in ``_base`` so that the three
#: issuers raise ONE ``Blocked`` and return ONE ``HoldingsFile``. They are re-exported
#: under their original names because ``tests/test_etf_rebalance.py`` and
#: ``tests/_mutate_etf_rebalance.py`` refer to ``ishares.Blocked`` /
#: ``ishares.BLOCKED_STATUSES``, and because a caller that catches
#: ``ishares.Blocked`` must also catch a refusal raised by the SSGA or Vanguard path.
HoldingsFile = _base.HoldingsFile
FetchError = _base.FetchError


def parse(text: str, *, ticker: str, requested: datetime.date) -> Optional[HoldingsFile]:
    """Parse one CSV document. ``None`` when the response is not a holdings file."""
    m_asof = _RE_ASOF.search(text)
    m_hdr = _RE_HEADER.search(text)
    if m_asof is None or m_hdr is None:
        return None

    try:
        as_of = pd.Timestamp(m_asof.group(1)).date()
    except Exception:
        return None

    m_sh = _RE_SHARES.search(text)
    shares = float(m_sh.group(1).replace(",", "")) if m_sh else float("nan")

    body = text[m_hdr.start():]
    try:
        df = pd.read_csv(io.StringIO(body), thousands=",", na_values=["-", "", "N/A"])
    except Exception as exc:
        raise FetchError(f"{ticker} {requested}: holdings table would not parse: {exc}") from exc

    # A footer line ("The content contained herein...") arrives as a one-column row.
    df = df[df["Name"].notna() & df.get("Asset Class").notna()].copy()

    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "Maturity" in df.columns:
        df["Maturity"] = pd.to_datetime(df["Maturity"], errors="coerce")

    df.insert(0, "ticker", ticker)
    df.insert(1, "date", pd.Timestamp(as_of))
    df["shares_outstanding"] = shares
    df["requested_date"] = pd.Timestamp(requested)

    return HoldingsFile(
        ticker=ticker,
        as_of=as_of,
        requested=requested,
        shares_outstanding=shares,
        content_sha1=hashlib.sha1(text.encode("utf-8", "replace")).hexdigest(),
        frame=df.reset_index(drop=True),
    )


#: Statuses that mean "the host is refusing you", never "this date has no file".
#:
#: 403 is the important one and it was learned the hard way. A six-worker backfill over
#: 2016-2026 succeeded 143 times and was then served ``403 Access Denied`` -- an Akamai
#: WAF page, not a fund document -- for the remaining 2,515 days. The first version of
#: this function returned ``None`` for any non-200, so the runner wrote 2,515 rows
#: asserting that iShares publishes no holdings for most of TLT's history. It ran to
#: completion, exited 0, and produced a manifest that resume would have honoured. The
#: block is IP-level and outlasts a four-attempt backoff, so a refusal has to
#: **propagate as an exception** and stop the run rather than be absorbed into the data.
BLOCKED_STATUSES = _base.BLOCKED_STATUSES
Blocked = _base.Blocked


def fetch(
    portfolio_id: str,
    date: datetime.date,
    *,
    ticker: str,
    session: Optional[requests.Session] = None,
    pool=None,
    max_attempts: int = 4,
    timeout: float = 30.0,
) -> Optional[HoldingsFile]:
    """One (fund, date).

    Returns ``None`` **only** for a 200 response that is not a holdings document -- the
    genuine "no file for this date" answer. Any refusal raises :class:`Blocked` after
    its retries are exhausted, so the caller can pause instead of recording absence.

    ``pool`` is a :class:`~MDP.ETFHoldings.proxy_pool.ProxyPool`. When given, each
    attempt takes a different exit and a refusal benches only that exit -- the WAF
    counts per IP, so a retry from the address that was just refused is a wasted
    request. Without a pool this falls back to the direct connection, which is fine for
    a handful of dates and is what tripped the block on twenty thousand.
    """
    url = BASE_URL.format(pid=portfolio_id, date=date.strftime("%Y%m%d"))
    last: Optional[str] = None

    for attempt in range(max_attempts):
        ex = pool.acquire() if pool is not None else None
        sess = ex.session if ex is not None else (session or requests)
        proxies = ex.proxies if ex is not None else None

        try:
            resp = sess.get(url, headers=HEADERS, timeout=timeout, proxies=proxies)
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
                wait = float(resp.headers.get("Retry-After", 0) or 0) or min(90.0, 5.0 * 2.0 ** attempt)
                time.sleep(wait + random.random())
            continue

        if resp.status_code != 200:
            raise Blocked(f"{ticker} {date}: unexpected HTTP {resp.status_code}")

        if ex is not None:
            pool.report_ok(ex)
        return parse(resp.text, ticker=ticker, requested=date)

    raise Blocked(f"{ticker} {date}: refused after {max_attempts} attempts ({last})")
