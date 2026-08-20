"""SEC Form N-PORT (NPORT-P) holdings, from EDGAR -- the only cross-issuer HISTORY there is.

Why this provider exists
------------------------
SSGA serves one workbook (whatever is current) and Vanguard serves one month-end, both
with no working date parameter. Neither can be backfilled, so on the issuer endpoints
alone a multi-issuer signal can only be *observed forward*, never tested. Every
registered fund, however, files portfolio holdings with the SEC on Form N-PORT, and the
public part of that filing is a small structured XML on EDGAR going back to 2019. That
is the entire historical basis for an aggregated SPTL/VGLT/EDV/ZROZ signal.

What it actually gives you -- measured 2026-08-20, not assumed
---------------------------------------------------------------
**Quarterly. Not monthly, and not before November 2027.** Funds file N-PORT with the SEC
monthly, but only the report for the third month of each fiscal quarter is made public,
so EDGAR shows one NPORT-P per quarter. Measured over all 27-29 filings for each of
SPTL/VGLT/TLT/EDV/ZROZ, the gap between consecutive ``repPdDate`` values is 90-92 days
with **no exceptions**.

The August 2024 amendments would have made every monthly report public. They have not
taken effect and will not soon: the SEC delayed the compliance date from 2025-11-17 to
**2027-11-17** for fund groups with $1bn+ net assets (and to 2028-05-18 for smaller
ones), and in February 2026 proposed scaling the amendments back further. So quarterly
is not a temporary state of the world to design around -- it is the granularity for at
least another year and a half, and possibly permanently.

**Before 2019 there is more history, but not in this format.** Form N-Q carried the
quarterly schedule for the fiscal quarters N-PORT now covers, and N-CSR/N-CSRS carry the
other two. Counts measured 2026-08-20: SPTL 23 N-Q back to 2007-11-29 plus 38 N-CSR(S);
VGLT 19 back to 2010-01-28 plus 33; EDV 25 back to 2007-07-27; ZROZ 18 back to
2010-05-28. Together they would roughly double the sample. They are **not implemented
here** because the payload is an unstructured ``.txt``/HTML schedule of investments
(SPTL's oldest N-Q is a 734 KB text file), so it needs a bespoke table parser per filing
agent rather than one XML schema -- a different piece of work with a different risk of
silently mis-parsing a column.

**Window: 2019-Q3/Q4 to 2026-Q2.** First filings: SPTL/ZROZ 2019-09-30, TLT/VGLT/EDV
2019-11-30. Roughly 27 observations per fund.

**Publication lag 53-62 days, median 57-60.** This is the single most dangerous property
of this data and the reason :func:`parse` writes ``filing_date`` and ``available_from``
into every row. The holdings are as of a quarter-end that is *two months in the past* by
the time anybody outside the fund can see them. A panel that keys on ``date``
(= ``repPdDate``) alone hands SPTL and VGLT a two-month lookahead, which is far larger
than any edge this study is chasing. ``available_from`` is the date the document became
public; nothing may condition on a row before it.

**The two issuers never share an observation date.** SPTL and ZROZ report on calendar
quarter-ends (Mar/Jun/Sep/Dec); TLT, VGLT and EDV report on Feb/May/Aug/Nov fiscal
quarter-ends. So a cross-issuer panel refreshes in alternating halves, eight times a
year, never all at once. ``repPdEnd`` is *not* the holdings date -- it is fiscal-year
machinery and one TLT filing carries ``2027-02-28``. Key on ``repPdDate``, always.

Units, established by measurement rather than by reading the schema
--------------------------------------------------------------------
``pctVal``      -- **percent**, not a fraction. ``pctVal / (valUSD / netAssets)`` is
                   100.0 to twelve significant figures across all 97 SPTL bond rows, and
                   the column sums to 99.05. Mapped straight onto ``Weight (%)``.
``balance``     -- par, but **only when ``units`` is ``PA``**. A fund can report the same
                   field in shares (``NS``) or contracts; SPTL's money-market sweep line
                   does exactly that. Mapping ``NS`` onto ``Par Value`` would put a share
                   count into a par column and every weight derived from par would be
                   wrong by that line. :func:`parse` refuses instead.
``annualizedRt``-- coupon in percent, rounded to 2dp (``4.38`` for the 4-3/8s of 2038).
                   iShares rounds identically, so the two tie out, but neither is an
                   exact coupon and neither may be used as a join key. Join on CUSIP.
``valUSD``      -- market value, and it is **CLEAN -- it excludes accrued interest**,
                   which is the opposite of the iShares convention. Measured on four
                   quarters of TLT: ``100 * valUSD / balance`` minus the iShares *clean*
                   quoted ``Price`` on the same ``repPdDate`` has a median of +0.0009,
                   -0.0002, -0.0004 and -0.0010 price points -- zero. The same iShares
                   file's own ``Market Value / Par Value`` sits +0.148 to +0.544 above
                   its quoted price, i.e. iShares publishes a **dirty** market value.
                   This does not cancel in a cross-sectional comparison: accrued is
                   ``coupon x days-since-coupon``, so it differs bond by bond. Mixing an
                   iShares weight with an N-PORT weight tilts the active weight toward
                   high-coupon bonds by construction. Prefer PAR-based weights, which
                   tie out bit-exactly (see below).

The alignment that makes the two sources comparable -- MEASURED, and not one business
day of pedantry
-----------------------------------------------------------------------------------
An N-PORT report stamped ``repPdDate`` D carries the par amounts of the iShares daily
file stamped the **previous business day**. Not approximately: on all 27 TLT quarters the
L1 distance between the two par-share vectors is 0.000000000000, the per-CUSIP par ratio
is exactly 1.0 for every holding, and the CUSIP sets are identical. The same metric is
0.0176 against the file stamped D itself, so the comparison discriminates.

The prices, however, are D's. So an N-PORT report is *positions from D-1 valued at D's
close*, which is what a settled-basis fund accounting book looks like at a month end
whose rebalance trades have not settled yet.

Why this matters more than it sounds: month-end IS the index rebalance, so the holdings
that differ between the two datings are exactly the bonds being traded into and out of
the index -- the entire subject of this study. On 2024-02-29 the iShares file already
carried $721mm of the newly-issued 30y (912810TX6) while the N-PORT report for the same
date carried $116mm, the pre-rebalance figure. Joining N-PORT to a daily panel on
calendar date misallocates 1.1%-3.8% of the book (L1 in par share, median 2.1%) and
misallocates it precisely onto the rebalance names. :func:`align_to_daily` does the
shift; use it rather than joining on ``date``.

Why the history cannot instead be MODELLED from float
------------------------------------------------------
The obvious shortcut -- SPTL and VGLT hold nearly the whole board, so reconstruct their
weights from free float and skip the scraping -- was tested on these 27 quarters and it
does not work, for a reason worth stating precisely because the summary statistic looks
encouraging.

Regressing each fund's weight on the ex-SOMA float-implied weight (through the origin,
``float_panel.benchmark_fit``) gives a median R^2 of 0.958 for SPTL and 0.998 for VGLT in
the 20y+ bucket; total-outstanding fits far worse (0.56 / 0.77), which independently
confirms the study's ex-SOMA benchmark choice. But the residual of that regression **is
the active weight**, which is the entire signal. Measured: the ratio of residual
dispersion to active-weight dispersion is 0.988-1.001, and the correlation between the
two is 0.998-0.9998. A float reconstruction therefore reproduces the benchmark and
**none** of the deviation from it. A synthetic pre-2019 history built this way would
have approximately zero active weight by construction -- a dataset in which the strategy
cannot have a signal, which would then be reported as the strategy not working.

The same numbers carry the other implication the reconstruction was meant to test: only
0.2% (VGLT 20y+) to 4.2% (SPTL 10y+) of the cross-sectional variance of these funds'
weights is discretionary. Median active-weight dispersion is 18.7bp of portfolio weight
for SPTL and 5.5bp for VGLT. VGLT tracks its index roughly three times more tightly than
SPTL, so as an *independent* view VGLT carries the less information of the two.

Rate limiting and identification
---------------------------------
EDGAR asks for a descriptive ``User-Agent`` carrying a contact address and rate-limits
at 10 requests/second. Both are honoured: the UA comes from ``ARBS_EDGAR_CONTACT`` and
requests are paced by a module-level limiter. **The default contact is a placeholder** --
an operator running a real backfill should set ``ARBS_EDGAR_CONTACT`` to a genuine
address, which is also why it is an environment variable rather than a literal in the
source. EDGAR is not WAF-protected and the proxy pool is deliberately not used here.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from typing import Iterable, Optional, Sequence

import pandas as pd
import requests

from MDP.ETFHoldings.providers import _base
from MDP.ETFHoldings.providers._base import (
    Blocked,
    FetchError,
    HoldingsFile,
    LayoutChanged,
    WrongDocument,
)

__all__ = [
    "SERIES", "NportSeries", "contact", "list_filings", "fetch_filing", "parse",
    "iter_fund", "align_to_daily", "BACKFILLABLE", "VALIDATION_ONLY",
    "Blocked", "FetchError", "LayoutChanged", "WrongDocument",
]

ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"
BROWSE = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={series}"
    "&type={form}&dateb=&owner=include&count=100&start={start}&output=atom"
)

#: Placeholder. SEC guidance is "Sample Company Name AdminContact@<domain>.com"; an
#: operator should export a real address. It is NOT defaulted to the repo owner's
#: personal email -- a private address does not belong in an outbound header.
DEFAULT_CONTACT = "ARBS-Research arbs-research-contact@example.com"


def contact() -> str:
    return os.environ.get("ARBS_EDGAR_CONTACT", DEFAULT_CONTACT).strip() or DEFAULT_CONTACT


# --------------------------------------------------------------------------- pacing


class _Pacer:
    """Sequential rate limiter. EDGAR's published ceiling is 10 req/s; we use 5."""

    def __init__(self, rate: float = 5.0) -> None:
        self._min_gap = 1.0 / max(0.1, rate)
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            gap = self._min_gap - (now - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()


_PACER = _Pacer(float(os.environ.get("ARBS_EDGAR_RATE", "5") or 5))


def _headers() -> dict:
    return {"User-Agent": contact(), "Accept-Encoding": "gzip, deflate"}


def _get(url: str, *, ticker: str, label: str, session=None, max_attempts: int = 5) -> requests.Response:
    _PACER.wait()
    return _base.get_with_retries(
        url, ticker=ticker, label=label, headers=_headers(),
        session=session, pool=None, max_attempts=max_attempts, timeout=120.0,
    )


# --------------------------------------------------------------------------- registry


class NportSeries:
    """A fund's EDGAR coordinates. ``cik`` is the TRUST; ``series_id`` is the fund."""

    __slots__ = ("ticker", "cik", "series_id", "class_id", "trust")

    def __init__(self, ticker: str, cik: str, series_id: str, class_id: str, trust: str) -> None:
        self.ticker, self.cik, self.series_id = ticker, str(int(cik)), series_id
        self.class_id, self.trust = class_id, trust

    def __repr__(self) -> str:  # pragma: no cover
        return f"NportSeries({self.ticker}, cik={self.cik}, series={self.series_id})"


#: Resolved from ``https://www.sec.gov/files/company_tickers_mf.json`` on 2026-08-20,
#: which is the SEC's own ticker -> (cik, seriesId, classId) map for funds. Hard-coded
#: rather than fetched at import so a backfill is reproducible and does not depend on a
#: network call to start; the mapping is stable (a series id is permanent for the life
#: of the fund).
SERIES: dict[str, NportSeries] = {
    s.ticker: s
    for s in [
        NportSeries("SPTL", "1064642", "S000017329", "C000047966", "SPDR SERIES TRUST"),
        NportSeries("VGLT", "1021882", "S000026861", "C000080849", "VANGUARD SCOTTSDALE FUNDS"),
        NportSeries("EDV",  "52848",   "S000018789", "C000051981", "VANGUARD BOND INDEX FUNDS"),
        NportSeries("ZROZ", "1450011", "S000026750", "C000080240", "PIMCO ETF TRUST"),
        # TLT is here for VALIDATION ONLY. Its daily iShares history already covers every
        # one of these dates, so N-PORT adds nothing -- but having the same fund on both
        # paths is what lets the parser be checked against a known answer. Do NOT write
        # these rows into the store: ``store.append_holdings`` dedupes on (date, CUSIP)
        # last-write-wins, so a quarter-end N-PORT row would REPLACE the richer daily
        # iShares row for that date with one whose Price/Duration columns are NaN.
        NportSeries("TLT",  "1100663", "S000004360", "C000012090", "ISHARES TRUST"),
    ]
}

#: The funds this provider is actually for -- everything whose issuer serves no history.
BACKFILLABLE: tuple[str, ...] = ("SPTL", "VGLT", "EDV", "ZROZ")

#: TLT must never be written to the holdings store from this path. See above.
VALIDATION_ONLY: frozenset[str] = frozenset({"TLT"})


# --------------------------------------------------------------------------- listing

_RE_ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)


def _entry_field(entry: str, tag: str) -> Optional[str]:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", entry, re.S)
    return m.group(1).strip() if m else None


def list_filings(
    ticker: str,
    *,
    forms: Sequence[str] = ("NPORT-P", "NPORT-P/A"),
    session=None,
) -> pd.DataFrame:
    """Every N-PORT filing EDGAR holds for this fund's SERIES.

    Filtering by ``seriesId`` rather than by CIK is essential: SPDR Series Trust and
    iShares Trust file hundreds of N-PORTs per quarter, one per fund, all under the same
    CIK. ``browse-edgar`` accepts a series id in its ``CIK`` parameter and returns only
    that fund's filings, which turns thousands of candidate documents into 28.
    """
    sp = SERIES[ticker.upper()]
    rows, seen = [], set()
    for start in range(0, 400, 100):
        url = BROWSE.format(series=sp.series_id, form="NPORT", start=start)
        txt = _get(url, ticker=ticker, label="edgar-browse", session=session).text
        entries = _RE_ENTRY.findall(txt)
        new = 0
        for e in entries:
            acc = _entry_field(e, "accession-number")
            if not acc or acc in seen:
                continue
            seen.add(acc)
            new += 1
            rows.append({
                "ticker": sp.ticker, "cik": sp.cik, "series_id": sp.series_id,
                "form": _entry_field(e, "filing-type"),
                "filing_date": _entry_field(e, "filing-date"),
                "accession": acc,
            })
        if new == 0 or len(entries) < 100:
            break

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df[df["form"].isin(forms)].copy()
    df["filing_date"] = pd.to_datetime(df["filing_date"])
    return df.sort_values("filing_date").reset_index(drop=True)


# --------------------------------------------------------------------------- parsing


def _local(tag: str) -> str:
    """``{http://www.sec.gov/edgar/nport}invstOrSec`` -> ``invstOrSec``."""
    return tag.rsplit("}", 1)[-1]


def _first(node: ET.Element, name: str) -> Optional[ET.Element]:
    for child in node.iter():
        if _local(child.tag) == name:
            return child
    return None


def _text(node: Optional[ET.Element], name: str) -> Optional[str]:
    if node is None:
        return None
    el = _first(node, name)
    if el is None or el.text is None:
        return None
    t = el.text.strip()
    return t or None


def _num(node: Optional[ET.Element], name: str) -> float:
    t = _text(node, name)
    if t is None:
        return float("nan")
    try:
        return float(t.replace(",", ""))
    except ValueError:
        return float("nan")


#: N-PORT asset categories -> the ``Asset Class`` vocabulary the panel filters on.
#: ``holdings_panel`` keys on the exact string ``"Fixed Income"``; anything that is not
#: mapped to it is excluded from the book, so an unmapped bond category is a silent
#: hole. Unknown categories therefore land in ``"Other"`` and are COUNTED, not dropped.
ASSET_CAT = {
    "DBT": "Fixed Income",     # debt security -- every Treasury line
    "STIV": "Money Market",    # short-term investment vehicle (the lending/sweep pool)
    "EC": "Equity",
    "RE": "Real Estate",
    "LON": "Fixed Income",
    "ABS-MBS": "Fixed Income",
    "ABS-CBDO": "Fixed Income",
    "ABS-O": "Fixed Income",
    "SN": "Fixed Income",
    "DE": "Cash and/or Derivatives",
    "DCO": "Cash and/or Derivatives",
    "DFE": "Cash and/or Derivatives",
    "DFI": "Cash and/or Derivatives",
    "DIR": "Cash and/or Derivatives",
    "DCR": "Cash and/or Derivatives",
    "DOT": "Cash and/or Derivatives",
    "COMM": "Commodity",
    "RA": "Cash and/or Derivatives",
}

#: ``issuerCat`` -> the iShares ``Sector`` vocabulary.
ISSUER_CAT = {
    "UST": "Treasuries",
    "USGA": "Agency",
    "USGSE": "Agency",
    "MUN": "Municipal",
    "CORP": "Corporate",
    "RF": "Cash and/or Derivatives",
    "PF": "Cash and/or Derivatives",
}

#: A ``cusip`` field can arrive as a filler when the issuer has none to give.
_CUSIP_PLACEHOLDERS = {"N/A", "NA", "NONE", "000000000", "0", "XXXXXXXXX", ""}
_CUSIP_RE = re.compile(r"^[0-9A-Z]{9}$")


def parse(
    xml_text: str,
    *,
    ticker: str,
    filing_date: datetime.date,
    accession: str,
    expect_series: Optional[str] = None,
    requested: Optional[datetime.date] = None,
) -> HoldingsFile:
    """One ``primary_doc.xml`` -> a frame in the shared provider schema.

    Raises rather than guessing. ``filing_date`` is required because it is the only
    honest point-in-time key this document has, and a frame without it would let the
    panel read a quarter-end two months before it was public.
    """
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as exc:
        raise LayoutChanged(f"nport {ticker} {accession}: XML would not parse: {exc}") from exc

    gen = _first(root, "genInfo")
    if gen is None:
        raise LayoutChanged(
            f"nport {ticker} {accession}: no <genInfo>. This is not an N-PORT primary "
            f"document -- check that the 100MB .htm rendering was not fetched instead."
        )

    series_id = _text(gen, "seriesId")
    if expect_series and series_id and series_id != expect_series:
        raise WrongDocument(
            f"nport {ticker} {accession}: document reports series {series_id}, expected "
            f"{expect_series}. A trust files one N-PORT per fund under one CIK; the "
            f"wrong one would silently supply another fund's book."
        )

    rep_pd_date = _text(gen, "repPdDate")
    if not rep_pd_date:
        raise LayoutChanged(f"nport {ticker} {accession}: no <repPdDate> -- no as-of date.")
    try:
        as_of = pd.Timestamp(rep_pd_date).date()
    except Exception as exc:
        raise LayoutChanged(f"nport {ticker} {accession}: bad repPdDate {rep_pd_date!r}") from exc

    fund = _first(root, "fundInfo")
    net_assets = _num(fund, "netAssets")

    rows = []
    n_bad_units = 0
    for node in root.iter():
        if _local(node.tag) != "invstOrSec":
            continue
        asset_cat = _text(node, "assetCat")
        issuer_cat = _text(node, "issuerCat")
        units = _text(node, "units")
        balance = _num(node, "balance")

        # ``balance`` means par ONLY under units == PA. A share count mapped onto a par
        # column is not detectably wrong downstream -- it is just a number -- so it is
        # refused here instead.
        par = balance if units == "PA" else float("nan")
        if asset_cat == "DBT" and units != "PA":
            n_bad_units += 1

        cusip = (_text(node, "cusip") or "").strip().upper()
        isin_el = _first(node, "isin")
        isin = (isin_el.get("value") if isin_el is not None else None) or None
        if isin:
            isin = isin.strip().upper()
        if cusip in _CUSIP_PLACEHOLDERS or not _CUSIP_RE.match(cusip):
            cusip = _base.isin_to_cusip(isin) if isin else None

        debt = _first(node, "debtSec")
        rows.append({
            "ticker": ticker,
            "date": pd.Timestamp(as_of),
            "Name": _text(node, "title") or _text(node, "name"),
            "Sector": ISSUER_CAT.get(issuer_cat or "", "Other"),
            "Asset Class": ASSET_CAT.get(asset_cat or "", "Other"),
            "Market Value": _num(node, "valUSD"),
            "Weight (%)": _num(node, "pctVal"),          # already PERCENT -- measured
            "Par Value": par,
            "CUSIP": cusip,
            "ISIN": isin,
            "Price": float("nan"),                       # N-PORT publishes no price ...
            "Mod. Duration": float("nan"),               # ... no duration ...
            "YTM (%)": float("nan"),                     # ... and no yield.
            "Maturity": pd.to_datetime(_text(debt, "maturityDt"), errors="coerce")
            if debt is not None else pd.NaT,
            "Coupon (%)": _num(debt, "annualizedRt") if debt is not None else float("nan"),
            "issuer_name": _text(node, "name"),
            "asset_cat": asset_cat,
            "issuer_cat": issuer_cat,
            "units": units,
            "balance": balance,
            "payoff_profile": _text(node, "payoffProfile"),
            "coupon_kind": _text(debt, "couponKind") if debt is not None else None,
        })

    if n_bad_units:
        raise LayoutChanged(
            f"nport {ticker} {accession}: {n_bad_units} debt holdings report units "
            f"other than 'PA'. ``balance`` is only par under PA; mapping shares or "
            f"contracts onto Par Value would corrupt every par-weighted number."
        )

    df = pd.DataFrame(rows)
    if df.empty:
        raise LayoutChanged(f"nport {ticker} {accession}: no <invstOrSec> holdings found.")

    df["shares_outstanding"] = float("nan")   # N-PORT carries no ETF share count
    df["requested_date"] = pd.Timestamp(requested or as_of)
    df["net_assets"] = net_assets
    df["filing_date"] = pd.Timestamp(filing_date)
    # The publication date, named for what a consumer must do with it. Nothing may
    # condition on this row before this date; the holdings are 53-62 days stale here.
    df["available_from"] = pd.Timestamp(filing_date)
    df["accession"] = accession
    df["source"] = "nport"
    df["rep_pd_end"] = _text(gen, "repPdEnd")

    # A weight column that does not sum to about 100 means pctVal was read in the wrong
    # unit, or the holdings list is partial. Either way the book is not usable.
    tot = float(df["Weight (%)"].sum())
    if not (50.0 <= tot <= 150.0):
        raise LayoutChanged(
            f"nport {ticker} {accession}: Weight (%) sums to {tot:.3f}, not ~100. "
            f"pctVal is published as a percent; a fraction here would mean the schema "
            f"changed and every weight is 100x wrong."
        )

    _base.validate_frame(df, ticker=ticker, source="nport")

    return HoldingsFile(
        ticker=ticker,
        as_of=as_of,
        requested=requested or as_of,
        shares_outstanding=float("nan"),
        content_sha1=hashlib.sha1(
            xml_text.encode("utf-8", "replace") if isinstance(xml_text, str) else xml_text
        ).hexdigest(),
        frame=df.reset_index(drop=True),
    )


# --------------------------------------------------------------------------- fetching


def fetch_filing(
    ticker: str,
    accession: str,
    filing_date: datetime.date,
    *,
    cik: Optional[str] = None,
    session=None,
) -> HoldingsFile:
    """Fetch and parse one filing's ``primary_doc.xml``.

    Deliberately fetches ``primary_doc.xml`` and never the filing's ``.htm`` rendering:
    the structured XML for SPTL is 123 KB while the HTML rendering of the same filing is
    **101 MB**. Both contain the same holdings.
    """
    sp = SERIES.get(ticker.upper())
    cik = cik or (sp.cik if sp else None)
    if cik is None:
        raise KeyError(f"{ticker!r} has no EDGAR series registered and no cik was given.")
    url = ARCHIVE.format(cik=cik, acc=accession.replace("-", ""))
    resp = _get(url, ticker=ticker, label="edgar-nport", session=session)
    return parse(
        resp.text, ticker=ticker.upper(), filing_date=filing_date, accession=accession,
        expect_series=sp.series_id if sp else None,
    )


def align_to_daily(df: pd.DataFrame, *, date_col: str = "date") -> pd.DataFrame:
    """Shift an N-PORT frame onto the dating convention of the issuers' daily files.

    Adds ``book_date`` = the previous US Treasury business day of ``repPdDate``, which is
    the date whose iShares file carries bit-identical par (measured on all 27 TLT
    quarters; see the module docstring). ``date`` is left untouched so the regulatory
    as-of remains recoverable.

    The distinction is not cosmetic. ``repPdDate`` is a month end, month end is the index
    rebalance, and the rows that disagree between the two datings are the bonds being
    rebalanced -- which is the population this study trades. A panel that joins on
    ``date`` silently attributes the pre-rebalance book to the post-rebalance day.
    """
    import QuantLib as ql

    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    out = df.copy()
    uniq = pd.to_datetime(pd.Series(out[date_col].unique()))
    mapping = {}
    for ts in uniq:
        d = ql.Date(ts.day, ts.month, ts.year)
        prev = cal.advance(d, ql.Period(-1, ql.Days))
        while not cal.isBusinessDay(prev):
            prev = cal.advance(prev, ql.Period(-1, ql.Days))
        mapping[ts] = pd.Timestamp(datetime.date(prev.year(), prev.month(), prev.dayOfMonth()))
    out["book_date"] = pd.to_datetime(out[date_col]).map(mapping)
    return out


def iter_fund(
    ticker: str,
    *,
    session=None,
    filings: Optional[pd.DataFrame] = None,
) -> Iterable[HoldingsFile]:
    """Every public N-PORT holdings document for one fund, oldest first, deduped.

    Two funds in the registry need the dedupe and it is not cosmetic: ZROZ filed an
    ``NPORT-P/A`` amendment four days after its 2021-09-30 original, and VGLT's
    2020-05-31 report appears twice. Keeping the LATEST filing for a ``repPdDate`` is the
    correct rule -- an amendment supersedes -- and keeping both would double-count that
    quarter in any panel built by concatenation.
    """
    fl = list_filings(ticker, session=session) if filings is None else filings
    best: dict[datetime.date, HoldingsFile] = {}
    for _, r in fl.iterrows():
        hf = fetch_filing(ticker, r["accession"], r["filing_date"].date(), session=session)
        prev = best.get(hf.as_of)
        if prev is None or pd.Timestamp(hf.frame["filing_date"].iloc[0]) >= pd.Timestamp(
            prev.frame["filing_date"].iloc[0]
        ):
            best[hf.as_of] = hf
    for k in sorted(best):
        yield best[k]
