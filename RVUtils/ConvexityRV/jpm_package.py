"""Parsers for the J.P. Morgan *U.S. Futures and Options Package* daily PDFs.

The package is a ~76-page daily PDF ("Derivatives Strategy", J.P. Morgan
Securities LLC / plc).  A local archive of 1,716 issues covering
2019-08-27 .. 2026-08-13 lives outside this repo; this module knows how to
find the volatility pages inside one and turn them into tidy tables.

Two document generations
------------------------
``legacy``   2019-08-27 .. 2024-11-17  (1,306 files)
    Cover carries ``As of 3:00 pm <Weekday>, <Month DD, YYYY>`` and
    ``For Business: <Weekday>, <Month DD, YYYY>``.  Report pages carry a
    bare ``DD Month YYYY`` header line (== the *As of* date).

``v2025``    2024-12-12 .. 2026-08-13  (410 files; note the 25-day corpus gap)
    Cover carries no dates.  Report pages carry ``<Mon DD, YYYY>`` (2024-12 ..
    2025) or the explicitly labelled ``Closes as Of: <Mon DD, YYYY>`` (2026).
    In both cases that page header date is the *close* (as-of) date.

Date convention (IMPORTANT)
---------------------------
The mark is a **3:00 pm New York close on the as-of date**, published for use
on the *next* business day.  Every row therefore carries two dates:

``as_of``          the close the numbers describe  -> **this is the join key**
``business_date``  the "For Business" date the sheet is filed under

The PDF *filename* is neither: it is the date the file was downloaded and
disagrees with ``For Business`` on 273 of the 1,306 legacy files (Friday
packages saved on the Saturday, holiday rolls, ...).  Never join on it.

Layout handling
---------------
Every table here is positional, not tabular: the plain ``get_text("text")``
dump interleaves row labels with values in the v2025 generation and glues
adjacent cells together in both.  All parsers therefore work from
``get_text("words")`` (x0, y0, x1, y1, word), cluster words into rows by y,
and take the **last ``n_cols`` value-like tokens of each row** as the data,
with everything to their left as the row label.  That rule survives:

* labels that begin with a digit ("10 day", "3 Year High", "20 day Low"),
* the ``*`` footnote marker emitted as its own token,
* cells glued into one token (``$167.35$167.35``),
* the v2025 section-header typo ``VOLATLITY``.

Anything that does not match hard-fails with :class:`JpmParseError` rather
than emitting NaN, so a layout change shows up as a counted failure with a
reason instead of a quietly empty column.

Units and semantics, as measured over the whole archive
-------------------------------------------------------
``pct_*``  the page's ``VOLATILITY`` block.  For Treasury products this is a
    lognormal **price** vol in percent; for money-market products (Eurodollar,
    SOFR 3M, the MidCurves) it is a lognormal **yield** vol in percent -- the
    page says so in its own footnote and the archive bears it out: on the
    MidCurve pages ``(100 - F) * pct/100 / sqrt(252)`` reproduces the printed
    basis-point figure with a median ratio of 1.0020 over 6,224 rows.

``bp_*``   the ``BASIS POINT VOLATILITY`` block is a **daily** basis-point
    yield vol, not an annualised one.  The Dec-2024 issues label it
    "Implied (bp) per day" outright, and against our own SOFR panel
    ``ABPV / (bp * sqrt(252))`` has median 0.9977, IQR (0.9932, 1.0024).
    Multiply by ``sqrt(252)`` to compare with an annualised ABPV.

``pct_impl_business_day``  is **not** the previous day's implied vol.  It is
    the same option re-implied on a 252-business-day clock instead of a
    365-calendar-day one: ``Current * sqrt(cal/bus) * sqrt(252/365)``
    reproduces it to a median 0.25% of the vol level (p90 1.8%) over 18,749
    rows.  The date-handling check that *does* work is the printed
    ``Change (1d)``, which equals ``Current(t) - Current(t-1)`` on 98.0% of
    Treasury rows and 99.6% of MidCurve rows with a median residual of 0.0000.

``days_cal`` / ``days_bus``  calendar and business days from ``as_of`` to
    option expiry.  ``as_of + days_cal`` lands exactly on the CME option
    expiry on 99.986% of 21,286 Treasury rows -- and on 0.014% / 0.000% if
    ``as_of`` is shifted by -1 / +1 day, which is what pins the date
    convention absolutely rather than merely self-consistently.

``futures_price``  Treasury prices are 32nds; so are money-market prices in
    the v2025 generation (see :func:`parse_price_32nds`).  Legacy Eurodollar
    pages print plain decimals.  The raw string is always kept alongside.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import fitz  # PyMuPDF

__all__ = [
    "JpmParseError",
    "REPORT_TITLES",
    "Word",
    "PageDates",
    "cluster_rows",
    "row_text",
    "normalise_text",
    "locate_reports",
    "document_dates",
    "page_header_date",
    "page_dates",
    "parse_price_32nds",
    "parse_vol_summary",
    "parse_otc_exchange",
    "parse_maturity_structure",
    "parse_skew_report",
    "parse_swaption_report",
    "product_family",
]


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
class JpmParseError(RuntimeError):
    """Raised when a page does not match the expected layout.

    Carries enough context (source file, 1-based page number, offending row
    label) that the batch driver can bucket failures by reason without
    re-opening the PDF.
    """

    def __init__(self, reason: str, *, source: str = "", page: int | None = None,
                 label: str = "") -> None:
        self.reason = reason
        self.source = source
        self.page = page
        self.label = label
        bits = [reason]
        if source:
            bits.append(f"source={source}")
        if page is not None:
            bits.append(f"page={page}")
        if label:
            bits.append(f"label={label!r}")
        super().__init__(" | ".join(bits))


class JpmEmptyPage(JpmParseError):
    """The layout matched but every cell was '-' / 'N/A'.

    This is a *legitimate* state (the Eurodollar MidCurve page is fully
    dashed on many dates once ED wound down), not a parse failure, so the
    driver records it separately as ``parsed_empty``.
    """


# --------------------------------------------------------------------------
# text plumbing
# --------------------------------------------------------------------------
Word = tuple[float, float, float, float, str, int, int, int]

#: Report titles we look for.  Matching is on normalised page text; page 1 is
#: always skipped because it is the table of contents and lists every title.
REPORT_TITLES: tuple[str, ...] = (
    "Treasury Volatility Summary",
    "Eurodollar Volatility Summary",
    "Eurodollar MidCurve Volatility Summary",
    "Treasury OTC and Exchange Volatility",
    "Maturity Structure of Treasury Volatility",
    "U.S. Treasuries Volatility Skew Report",
    "Eurodollar Volatility Skew Report",
    "Cross Market Volatility Spread Report",
    "Short-Dated SOFR Swaption Volatility Report",
    "Short-Dated Swaption Volatility Report",
    "Volatility Summary - Other",
    "Volatility Summary - Currencies",
)

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}
_MONTHS_FULL = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"])}


def normalise_text(s: str) -> str:
    """Fold the PDF's mojibake into plain ASCII-ish text.

    The archive's OTC page renders typographic apostrophes as U+FFFD
    ("OTC 30�s"), and other pages use U+2019.  Both must collapse to the
    same key or panel-title matching silently misses.
    """
    s = unicodedata.normalize("NFKC", s)
    for ch in ("’", "‘", "´", "�", "ﬂ", "ﬁ"):
        s = s.replace(ch, "'")
    return s.replace("–", "-").replace("—", "-").replace("\xa0", " ")


def cluster_rows(page: "fitz.Page", *, ytol: float = 2.0,
                 ymin: float = -1e9, ymax: float = 1e9) -> list[list[Word]]:
    """Group a page's words into visual rows, ordered top-to-bottom.

    ``ytol`` is the vertical tolerance in points; 2.0 keeps the ~9pt table
    rows apart while tolerating the sub-point baseline jitter seen inside a
    single row (e.g. ``3 Year High`` sits 0.5pt above its own numbers).
    """
    words = [w for w in page.get_text("words")
             if ymin <= (w[1] + w[3]) / 2.0 <= ymax]
    rows: list[list[Word]] = []
    cur: list[Word] = []
    anchor: float | None = None
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2.0, w[0])):
        yc = (w[1] + w[3]) / 2.0
        if anchor is None or abs(yc - anchor) <= ytol:
            if anchor is None:
                anchor = yc
            cur.append(w)
        else:
            rows.append(sorted(cur, key=lambda w: w[0]))
            cur = [w]
            anchor = yc
    if cur:
        rows.append(sorted(cur, key=lambda w: w[0]))
    return rows


def row_text(row: Sequence[Word]) -> str:
    return normalise_text(" ".join(w[4] for w in row))


def row_y(row: Sequence[Word]) -> float:
    return sum((w[1] + w[3]) / 2.0 for w in row) / len(row)


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------
_RE_AS_OF = re.compile(
    r"As of\s*3:00\s*pm\s*[A-Za-z]+,\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")
_RE_FOR_BUS_LONG = re.compile(
    r"For Business:\s*[A-Za-z]+,\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})")
_RE_FOR_BUS_SHORT = re.compile(
    r"For Business:\s*(?:[A-Za-z]{3},\s*)?([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})")
_RE_CLOSES_AS_OF = re.compile(
    r"Closes as Of:?\s*(?:[A-Za-z]+day\s+)?(\d{1,2})?\s*([A-Za-z]{3,9})\.?\s*"
    r"(\d{1,2})?,?\s*(\d{4})")
#: page-header date, legacy generation: "08 June 2023"
_RE_HDR_LEGACY = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$")
#: page-header date, v2025 generation: "Dec 11, 2024" / "Aug 12, 2026"
_RE_HDR_V2025 = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})$")


def _month(tok: str) -> int | None:
    tok = tok.strip(".").capitalize()
    if tok in _MONTHS_FULL:
        return _MONTHS_FULL[tok]
    return _MONTHS.get(tok[:3])


def _mk(y: str | int, m: str | int, d: str | int) -> _dt.date | None:
    mm = _month(str(m)) if not str(m).isdigit() else int(m)
    if not mm:
        return None
    try:
        return _dt.date(int(y), mm, int(d))
    except ValueError:
        return None


@dataclass(frozen=True)
class PageDates:
    """Dates recovered for one page / one document."""

    as_of: _dt.date | None
    business_date: _dt.date | None
    generation: str  # "legacy" | "v2025"
    source: str = ""  # where as_of came from


def page_header_date(page: "fitz.Page") -> tuple[_dt.date | None, str]:
    """Return the as-of (3pm close) date printed in the page's top-left header.

    Both generations put it on the second or third header line at x<200:
    legacy ``08 June 2023``; v2025 ``Dec 11, 2024`` or the labelled
    ``Closes as Of: Aug 12, 2026``.  Returns ``(date, kind)``.
    """
    for row in cluster_rows(page, ymax=70.0):
        left = [w for w in row if w[0] < 200.0]
        if not left:
            continue
        txt = normalise_text(" ".join(w[4] for w in left)).strip()
        m = _RE_CLOSES_AS_OF.search(txt)
        if m:
            g = m.groups()
            if g[0] and g[2] is None:      # "Wednesday 12 August 2026"
                d = _mk(g[3], g[1], g[0])
            else:                           # "Aug 12, 2026"
                d = _mk(g[3], g[1], g[2])
            if d:
                return d, "page:Closes as Of"
        m = _RE_HDR_LEGACY.match(txt)
        if m and _month(m.group(2)):
            d = _mk(m.group(3), m.group(2), m.group(1))
            if d:
                return d, "page:legacy header"
        m = _RE_HDR_V2025.match(txt)
        if m and _month(m.group(1)):
            d = _mk(m.group(3), m.group(1), m.group(2))
            if d:
                return d, "page:v2025 header"
    return None, ""


def page_dates(page: "fitz.Page", doc: PageDates) -> PageDates:
    """Dates for one page, preferring the page's own stamps to the file's.

    Individual reports inside one package are *not* always struck at the same
    time -- on 2025-01-15 the Roll report carries "For Business: Jan 14" while
    the Cross-Market page still says "For Business: Mon, Jan 13" and was
    "Produced: Sat, Jan 11".  Anything we parse therefore takes its own page's
    header date when it has one, and only falls back to the document.
    """
    as_of, src = page_header_date(page)
    txt = normalise_text(page.get_text("text"))
    bus = None
    m = _RE_FOR_BUS_SHORT.search(txt)
    if m:
        bus = _mk(m.group(3), m.group(1), m.group(2))
    if as_of is None:
        as_of, src = doc.as_of, doc.source
    if bus is None:
        bus = doc.business_date if as_of == doc.as_of else _next_business_day(as_of) \
            if as_of else None
    return PageDates(as_of, bus, doc.generation, src)


def _next_business_day(d: _dt.date) -> _dt.date:
    n = d + _dt.timedelta(days=1)
    while n.weekday() >= 5:
        n += _dt.timedelta(days=1)
    return n


def document_dates(doc: "fitz.Document") -> PageDates:
    """File-level dates: cover first (legacy), page headers otherwise.

    ``generation`` is decided by the presence of the cover's
    ``As of 3:00 pm`` stamp, which is exactly the 1,306 legacy files.
    """
    cover = normalise_text(doc[0].get_text("text"))
    m_as = _RE_AS_OF.search(cover)
    m_fb = _RE_FOR_BUS_LONG.search(cover)
    if m_as:
        as_of = _mk(m_as.group(3), m_as.group(1), m_as.group(2))
        bus = _mk(m_fb.group(3), m_fb.group(1), m_fb.group(2)) if m_fb else None
        return PageDates(as_of, bus or (_next_business_day(as_of) if as_of else None),
                         "legacy", "cover:As of 3:00 pm")

    # v2025: no cover dates.  Take the first page header date we can find and
    # the first "For Business" stamp anywhere in the document.
    as_of = None
    src = ""
    for i in range(1, min(doc.page_count, 40)):
        as_of, src = page_header_date(doc[i])
        if as_of:
            break
    bus = None
    for i in range(min(doc.page_count, 40)):
        t = normalise_text(doc[i].get_text("text"))
        m = _RE_FOR_BUS_SHORT.search(t)
        if m:
            cand = _mk(m.group(3), m.group(1), m.group(2))
            if cand and as_of and cand > as_of:
                bus = cand
                break
    if bus is None and as_of is not None:
        bus = _next_business_day(as_of)
    return PageDates(as_of, bus, "v2025", src)


# --------------------------------------------------------------------------
# report location
# --------------------------------------------------------------------------
def locate_reports(doc: "fitz.Document",
                   titles: Iterable[str] = REPORT_TITLES) -> dict[str, list[int]]:
    """Map report title -> list of 1-based page numbers where it appears.

    Located by **title text**, never by index: page numbers drift by up to 30
    pages across the archive (Treasury Volatility Summary sits on p29 in 2019,
    p26 in 2023, p19 in Nov-2024 and p30 in 2026).  Page 1 is skipped because
    it is the table of contents.

    Note the v2025 generation prints ``Treasury Volatility Summary`` on *two*
    consecutive pages -- the Treasury products and, mis-titled, the
    ``Secured ON Financing Rate 3M`` (SOFR) products.  Callers must therefore
    disambiguate on the product row, not on the title.
    """
    titles = tuple(titles)
    norm = tuple(normalise_text(t) for t in titles)
    out: dict[str, list[int]] = {t: [] for t in titles}
    for i in range(1, doc.page_count):
        txt = normalise_text(doc[i].get_text("text"))
        for t, nt in zip(titles, norm):
            if nt in txt:
                out[t].append(i + 1)
    return {k: v for k, v in out.items() if v}


# --------------------------------------------------------------------------
# value tokenisation
# --------------------------------------------------------------------------
_MISSING = {"-", "--", "N/A", "NA", "n/a", "*"}
_RE_NUM = re.compile(r"^[+-]?\$?[\d,]*\.?\d+%?$")
_RE_DAYS = re.compile(r"^\d+/\d+$")
_RE_PX32 = re.compile(r"^\d+-\d{2,3}[+#]?$")
_RE_DOLLAR_SPLIT = re.compile(r"(?<=\d)(?=\$)")


def _split_glued(tokens: Sequence[Word]) -> list[tuple[str, float, float]]:
    """Explode glued cells into (text, x0, x1) triples.

    The v2025 BPV row emits ``$167.35$167.35`` as one word when two adjacent
    cells touch; splitting on the ``$`` boundary restores the cell count.  The
    synthetic x-span is apportioned evenly, which is only used for the
    left-edge sanity check.
    """
    out: list[tuple[str, float, float]] = []
    for w in tokens:
        txt = normalise_text(w[4]).strip()
        if not txt:
            continue
        parts = _RE_DOLLAR_SPLIT.split(txt) if txt.count("$") > 1 else [txt]
        n = len(parts)
        span = (w[2] - w[0]) / n if n else 0.0
        for k, p in enumerate(parts):
            out.append((p, w[0] + k * span, w[0] + (k + 1) * span))
    return out


def _is_value(tok: str) -> bool:
    if tok in _MISSING:
        return True
    return bool(_RE_NUM.match(tok) or _RE_DAYS.match(tok) or _RE_PX32.match(tok))


def _to_float(tok: str) -> float | None:
    if tok in _MISSING:
        return None
    t = tok.replace(",", "").replace("%", "").replace("$", "")
    try:
        return float(t)
    except ValueError:
        return None


def parse_price_32nds(tok: str) -> float | None:
    """Decode a JPM futures-price string to a decimal price.

    Three notations occur in the archive::

        "127-20"   -> 127 + 20/32
        "113-235"  -> 113 + 23.5/32     (third digit is eighths of a 32nd)
        "106-11+"  -> 106 + 11.5/32     (v2025 uses '+' for the half)
        "99.880"   -> 99.880            (legacy Eurodollar pages: plain decimal)

    The v2025 generation prints *money-market* futures in 32nds too, which is
    a formatter quirk rather than an exchange convention: SFRU26 shows as
    ``96-06`` on 2026-08-13 while the package's own SOFR pack page prints
    96.190 for the same contract (96 + 6/32 = 96.1875).  Reading that dash as
    a decimal point would be wrong by ~0.13, so we always decode 32nds and
    keep the raw string alongside.
    """
    tok = normalise_text(tok).strip()
    if not tok or tok in _MISSING:
        return None
    if _RE_NUM.match(tok):
        return _to_float(tok)
    m = re.match(r"^(\d+)-(\d{2})(\d)?([+#])?$", tok)
    if not m:
        return None
    whole = int(m.group(1))
    ticks = int(m.group(2))
    frac = 0.0
    if m.group(3) is not None:
        frac = {"0": 0.0, "1": 0.125, "2": 0.25, "3": 0.375, "4": 0.5,
                "5": 0.5, "6": 0.75, "7": 0.75, "8": 0.875,
                "9": 0.875}.get(m.group(3), 0.0)
    if m.group(4) in ("+", "#"):
        frac = 0.5 if m.group(4) == "+" else 0.75
    return whole + (ticks + frac) / 32.0


# --------------------------------------------------------------------------
# volatility-summary family (Treasury / Eurodollar / MidCurve / SOFR)
# --------------------------------------------------------------------------
_RE_EXPIRY = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)$")
_RE_YY = re.compile(r"^\d{2}$")
#: the Dec-2024/2025 issues glue the pair into one token: "Jan25"
_RE_EXPIRY_GLUED = re.compile(
    r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[-\s]?(\d{2})$")

#: canonical metric name for each printed row label, keyed by (section, label)
#: Section banners.  Matched as a *prefix* of the normalised label because the
#: Dec-2024 issues append " per day" and the v2025 issues misspell the first
#: one as "VOLATLITY".
_SECTIONS = {
    "volatility": "pct",
    "volatlity": "pct",            # v2025 typo, kept deliberately
    "basis point volatility": "bp",
    "basis point volatlity": "bp",
    "yield change required to...": "yc",
}
_SUBSECTIONS = {
    "implied (%)": ("pct", "implied"),
    "historical (%)": ("pct", "hist"),
    "volatility cones (%)": ("pct", "cone"),
    "implied (bp)": ("bp", "implied"),
    "historical (bp)": ("bp", "hist"),
    "volatility cones (bp)": ("bp", "cone"),
}
#: metrics that must appear on every non-empty volatility-summary page.  A
#: layout drift that silently renames a section (as the Dec-2024 issues do,
#: labelling the basis-point block "Implied (bp) per day") shows up here as a
#: hard failure instead of a set of quietly missing columns.
_REQUIRED_METRICS = (
    "pct_impl_current", "pct_impl_business_day", "pct_hist_10d",
    "bp_impl_current", "bp_hist_10d", "yc_breakeven_exp",
)


def _canon_label(text: str) -> str:
    """Lower-case a row label and repair the glued-parenthesis variants.

    The Dec-2024 issues emit ``Change(5d)`` as a single token where every
    other vintage emits ``Change (5d)``.
    """
    low = normalise_text(text).strip().lower()
    low = re.sub(r"(?<=[a-z0-9])\(", " (", low)
    return re.sub(r"\s+", " ", low).strip()


def _match_prefix(low: str, table: dict) -> Any:
    for key, val in table.items():
        if low == key or low.startswith(key + " "):
            return val
    return None
#: printed row label -> (metric stem, whether the subsection is part of the name)
#:
#: The section prefix ("pct" / "bp" / "yc") always applies.  The subsection
#: ("impl" / "hist" / "cone") is folded in only where it disambiguates: the
#: cone rows and "% Historic Above Implied" carry their own stem, and the
#: "2Yr Event Risk" row happens to sit inside the Historical block but is not
#: a historical volatility, so it keeps a bare name.
_ROWS: dict[str, tuple[str, bool]] = {
    "current": ("current", True),
    "change (1d)": ("chg_1d", True),
    "change (5d)": ("chg_5d", True),
    "change (20d)": ("chg_20d", True),
    "20 day high": ("high_20d", True),
    "20 day low": ("low_20d", True),
    "business day": ("business_day", True),
    "10 day": ("10d", True),
    "20 day": ("20d", True),
    "50 day": ("50d", True),
    "2yr event risk": ("event_risk_2yr", False),
    "year high": ("cone_high", False),
    "year average": ("cone_avg", False),
    "year low": ("cone_low", False),
    "% historic above implied": ("hist_above_impl", False),
    "% historical above implied": ("hist_above_impl", False),
    "offset 1 c-day decay": ("offset_1c", False),
    "offset 1 b-day decay": ("offset_1b", False),
    "offset 1 month decay": ("offset_1m", False),
    "break even at expiry": ("breakeven_exp", False),
    "break even at exp": ("breakeven_exp", False),
}
#: short names for the subsections used in metric keys
_SUB_KEY = {"implied": "impl", "hist": "hist", "cone": "cone"}
_META_ROWS = {
    "bpv per contract": "bpv_per_contract",
    "cal/bus days to expiry": "days",
    "days to expiration": "days_cal_only",
    "futures price": "futures_price",
}

#: products we recognise on a volatility-summary page, longest first so that
#: "5 Year Treasury Note" wins over "Treasury Note"
_PRODUCTS: tuple[str, ...] = (
    "Ultra Treasury Bond", "Ultra 10 Year Treasury Note",
    "5 Year Treasury Note", "2 Year Treasury Note", "10 Year Treasury Note",
    "Treasury Bond", "Treasury Note",
    "Secured ON Financing Rate 3M", "Secured ON Financing Rate 1M",
    "Secured ON Financing Rate",
    "Eurodollar 1Yr MidCurve", "Eurodollar 2Yr MidCurve",
    "Eurodollar 3Yr MidCurve", "Eurodollar 4Yr MidCurve",
    "Eurodollar 5Yr MidCurve",
    "SOFR 1Yr MidCurve", "SOFR 2Yr MidCurve", "SOFR 3Yr MidCurve",
    "SOFR 4Yr MidCurve", "SOFR 5Yr MidCurve",
    "Eurodollar",
)

_TREASURY_PRODUCTS = {
    "Treasury Bond", "Treasury Note", "5 Year Treasury Note",
    "2 Year Treasury Note", "10 Year Treasury Note",
    "Ultra Treasury Bond", "Ultra 10 Year Treasury Note",
}


def product_family(product: str) -> str:
    """Route a product label to one of ``treasury`` / ``midcurve`` / ``stir``."""
    if product in _TREASURY_PRODUCTS:
        return "treasury"
    if "MidCurve" in product:
        return "midcurve"
    return "stir"


def _find_expiry_row(rows: list[list[Word]]) -> tuple[int, list[dict[str, Any]]]:
    """Locate the ``Jun 23  Jul 23 ...`` column-header row.

    Returns its index plus one dict per column with the month token, the
    2-digit year and the x-extent of the "Mon YY" pair.
    """
    best: tuple[int, list[dict[str, Any]]] | None = None
    for i, row in enumerate(rows):
        toks = [(normalise_text(w[4]).strip(), w) for w in row]
        cols: list[dict[str, Any]] = []
        k = 0
        while k < len(toks):
            a, wa = toks[k]
            mg = _RE_EXPIRY_GLUED.match(a)
            if mg:
                cols.append({"mon": mg.group(1), "yy": mg.group(2),
                             "x0": wa[0], "x1": wa[2],
                             "xc": (wa[0] + wa[2]) / 2.0})
                k += 1
                continue
            if k + 1 < len(toks):
                b, wb = toks[k + 1]
                if _RE_EXPIRY.match(a) and _RE_YY.match(b):
                    cols.append({"mon": a, "yy": b, "x0": wa[0], "x1": wb[2],
                                 "xc": (wa[0] + wb[2]) / 2.0})
                    k += 2
                    continue
            k += 1
        if len(cols) >= 3 and (best is None or len(cols) > len(best[1])):
            best = (i, cols)
    if best is None:
        raise JpmParseError("no expiry header row (>=3 'Mon YY' pairs) found")
    return best


def _find_product_row(rows: list[list[Word]], hdr_idx: int) -> list[dict[str, Any]]:
    """Read the product banner immediately above the expiry header row."""
    for j in range(hdr_idx - 1, max(hdr_idx - 4, -1), -1):
        txt = row_text(rows[j])
        found: list[dict[str, Any]] = []
        consumed = [False] * len(rows[j])
        for name in _PRODUCTS:
            start = 0
            toks = [normalise_text(w[4]).strip() for w in rows[j]]
            want = name.split()
            while start <= len(toks) - len(want):
                if toks[start:start + len(want)] == want and not any(
                        consumed[start:start + len(want)]):
                    for c in range(start, start + len(want)):
                        consumed[c] = True
                    found.append({
                        "product": name,
                        "x0": rows[j][start][0],
                        "x1": rows[j][start + len(want) - 1][2],
                    })
                start += 1
        if found:
            for f in found:
                f["xc"] = (f["x0"] + f["x1"]) / 2.0
            return sorted(found, key=lambda f: f["x0"])
        if txt.strip():
            continue
    return []


def _find_product_row_anywhere(rows: list[list[Word]]) -> list[dict[str, Any]]:
    """Fallback product scan over the whole page (v2025 SOFR page prints the
    product banner as a detached block)."""
    found: list[dict[str, Any]] = []
    for row in rows:
        toks = [normalise_text(w[4]).strip() for w in row]
        consumed = [False] * len(row)
        for name in _PRODUCTS:
            want = name.split()
            start = 0
            while start <= len(toks) - len(want):
                if toks[start:start + len(want)] == want and not any(
                        consumed[start:start + len(want)]):
                    for c in range(start, start + len(want)):
                        consumed[c] = True
                    found.append({"product": name, "x0": row[start][0],
                                  "x1": row[start + len(want) - 1][2]})
                start += 1
    for f in found:
        f["xc"] = (f["x0"] + f["x1"]) / 2.0
    return sorted(found, key=lambda f: f["x0"])


def _assign_columns(cols: list[dict[str, Any]],
                    prods: list[dict[str, Any]]) -> None:
    """Attach a product to every expiry column by nearest banner centre.

    Column groups are contiguous by construction; we assert that afterwards so
    an interleaved assignment (which would mean the banner scan misfired)
    hard-fails instead of producing a scrambled panel.
    """
    if not prods:
        raise JpmParseError("no product banner found above the expiry header")
    if len(prods) == 1:
        for c in cols:
            c["product"] = prods[0]["product"]
        return
    for c in cols:
        c["product"] = min(prods, key=lambda p: abs(p["xc"] - c["xc"]))["product"]
    seen: list[str] = []
    for c in cols:
        if not seen or seen[-1] != c["product"]:
            if c["product"] in seen:
                raise JpmParseError(
                    f"non-contiguous product/column assignment: "
                    f"{[c['product'] for c in cols]}")
            seen.append(c["product"])
    # ...and the column groups must appear in the same left-to-right order as
    # the banners themselves.  Contiguity alone would happily accept a whole
    # panel shifted one product sideways, which is exactly the failure that
    # puts Treasury Bond numbers under the Treasury Note heading.
    banner_order = [p["product"] for p in sorted(prods, key=lambda p: p["x0"])]
    expected = [p for p in banner_order if p in set(seen)]
    if seen != expected:
        raise JpmParseError(
            f"product/column order {seen} does not match banner order {expected}")


def _expiry_ym(mon: str, yy: str, as_of: _dt.date | None) -> str:
    """Expand "Jun 23" to "2023-06"; the century comes from the as-of date."""
    m = _MONTHS[mon]
    y = int(yy)
    if as_of is not None:
        base = as_of.year // 100 * 100
        y = base + y
        if y < as_of.year - 1:
            y += 100
    else:
        y = 2000 + y
    return f"{y:04d}-{m:02d}"


def parse_vol_summary(page: "fitz.Page", *, as_of: _dt.date | None = None,
                      source: str = "") -> list[dict[str, Any]]:
    """Parse one *… Volatility Summary* page into one dict per (product, expiry).

    Works for the Treasury, Eurodollar, Eurodollar-MidCurve and (v2025) SOFR
    variants -- they are the same table with different banners.

    Raises :class:`JpmParseError` if the header cannot be found or a data row
    does not yield exactly ``n_cols`` value tokens; raises
    :class:`JpmEmptyPage` if the layout matched but every cell is missing.
    """
    pno = page.number + 1
    try:
        rows = cluster_rows(page)
        hdr_idx, cols = _find_expiry_row(rows)
        prods = _find_product_row(rows, hdr_idx) or _find_product_row_anywhere(rows)
        _assign_columns(cols, prods)
        n = len(cols)
        left_guard = min(c["x0"] for c in cols) - 12.0

        recs = [{
            "product": c["product"],
            "expiry_label": f"{c['mon']} {c['yy']}",
            "expiry_ym": _expiry_ym(c["mon"], c["yy"], as_of),
            "col_index": k,
        } for k, c in enumerate(cols)]

        section = ""
        sub = ""
        cone_years: float | None = None
        nonmissing = 0
        for row in rows[hdr_idx + 1:]:
            toks = _split_glued(row)
            if not toks:
                continue
            txt = " ".join(t[0] for t in toks)
            low = _canon_label(txt)

            hit = _match_prefix(low, _SUBSECTIONS)
            if hit is not None:
                section, sub = hit
                continue
            hit = _match_prefix(low, _SECTIONS)
            if hit is not None:
                section = hit
                sub = ""
                continue
            if low.startswith("volatility is price") or low.startswith("* historical"):
                break  # footnotes

            # The '*' footnote marker ("historical volatility is taken from
            # old otr bond") is emitted as its own word directly after the
            # cell it annotates.  Drop it from the column count but remember
            # WHICH column it belonged to -- it is printed only against the
            # Treasury Bond block, so flagging the whole page would be wrong.
            stars: set[int] = set()
            kept: list[tuple[str, float, float]] = []
            for t in toks:
                if t[0] == "*":
                    if kept:
                        stars.add(len(kept) - 1)
                else:
                    kept.append(t)
            toks = kept
            if len(toks) < n + 1:
                continue
            vals = toks[-n:]
            if not all(_is_value(t[0]) for t in vals):
                continue
            label_toks = toks[:-n]
            label = " ".join(t[0] for t in label_toks).strip()
            low_lbl = _canon_label(label)
            if vals[0][1] < left_guard - 25.0:
                raise JpmParseError(
                    f"value block starts left of the first column "
                    f"(x0={vals[0][1]:.0f} < {left_guard:.0f})",
                    source=source, page=pno, label=label)

            # cone rows print "3 Year High" / "2 Year Low"; keep the window
            mcone = re.match(r"^(\d+)\s+year\s+(high|average|low)$", low_lbl)
            if mcone:
                cone_years = float(mcone.group(1))
                low_lbl = f"year {mcone.group(2)}"

            if low_lbl in _META_ROWS:
                key = _META_ROWS[low_lbl]
                for r, v in zip(recs, vals):
                    tok = v[0]
                    if key == "bpv_per_contract":
                        r["bpv_per_contract"] = _to_float(tok)
                    elif key == "days":
                        if tok in _MISSING:
                            r["days_cal"] = r["days_bus"] = None
                        else:
                            a, _, b = tok.partition("/")
                            r["days_cal"] = int(a) if a.isdigit() else None
                            r["days_bus"] = int(b) if b.isdigit() else None
                    elif key == "days_cal_only":
                        r["days_cal"] = int(tok) if tok.isdigit() else None
                    else:
                        r["futures_price_raw"] = None if tok in _MISSING else tok
                        r["futures_price"] = parse_price_32nds(tok)
                continue

            spec = _ROWS.get(low_lbl)
            if spec is None:
                continue
            base, use_sub = spec
            if not section:
                raise JpmParseError("data row outside any section",
                                    source=source, page=pno, label=label)
            metric = (f"{section}_{_SUB_KEY[sub]}_{base}"
                      if (use_sub and sub) else f"{section}_{base}")
            off = len(toks) - n
            for i, (r, v) in enumerate(zip(recs, vals)):
                fv = _to_float(v[0])
                r[metric] = fv
                if fv is not None:
                    nonmissing += 1
                if (off + i) in stars:
                    r["hist_from_old_otr"] = True

        for r in recs:
            r.setdefault("hist_from_old_otr", False)
            r["cone_years"] = cone_years

        if nonmissing == 0:
            raise JpmEmptyPage("layout matched but every cell is missing",
                               source=source, page=pno)
        missing = [m for m in _REQUIRED_METRICS if m not in recs[0]]
        if missing:
            raise JpmParseError(
                f"required metrics absent after parse: {missing}",
                source=source, page=pno)
        return recs
    except JpmParseError as exc:
        if not exc.source:
            exc.source = source
        if exc.page is None:
            exc.page = pno
        raise


# --------------------------------------------------------------------------
# Treasury OTC and Exchange Volatility
# --------------------------------------------------------------------------
#: panel titles seen in the archive, normalised (apostrophes folded to ')
_OTC_PANEL = re.compile(
    r"OTC\s+(\d+)'s\s*/\s*(CBOT\s+(\d+)'s|1-Yr\s+Eurodollar\s+midcurves"
    r"|1-Yr\s+SOFR\s+midcurves|.+)$")


def _split_row_groups(row: Sequence[Word],
                      gap: float = 25.0) -> list[tuple[str, float, float]]:
    """Split one visual row into left-to-right groups separated by a wide gap.

    Both grid pages put two independent panels on the same baseline, so the
    row ``OTC 30's / CBOT 30's      OTC 10's / CBOT 10's`` has to be cut back
    into two labels before either can be matched.
    """
    groups: list[tuple[str, float, float]] = []
    cur: list[Word] = []
    for w in row:
        if cur and w[0] - cur[-1][2] > gap:
            groups.append((row_text(cur), cur[0][0], cur[-1][2]))
            cur = []
        cur.append(w)
    if cur:
        groups.append((row_text(cur), cur[0][0], cur[-1][2]))
    return groups


def _bands(x0s: Sequence[float], *, pad: float = 20.0) -> list[tuple[float, float]]:
    """Turn panel left edges into non-overlapping x bands.

    A band runs from just left of its own panel to just left of the next
    panel, so a panel's *table* (which is indented well to the right of its
    title, and whose last column can sit 90pt further right still) stays
    inside its own band without bleeding into its neighbour's.
    """
    out: list[tuple[float, float]] = []
    for i, x in enumerate(x0s):
        hi = x0s[i + 1] - pad if i + 1 < len(x0s) else 1e9
        out.append((x - pad, hi))
    return out


def parse_otc_exchange(page: "fitz.Page", *, source: str = "") -> list[dict[str, Any]]:
    """Parse *Treasury OTC and Exchange Volatility* into one row per panel.

    Layout is a 2x2 grid of charts.  Under each chart sits a 3-column x 2-row
    table::

                       Current   6M Avg   FV
        Implied          N/A      N/A     0.84
        Historical       0.93     1.02

    i.e. **five** cells, not three: ``Implied`` has a fair-value column that
    ``Historical`` does not.  (The FV cell is a model fair value, and the
    Implied Current/6M-Avg cells are ``N/A`` on most dates -- see the coverage
    report for the measured population rate.)
    """
    pno = page.number + 1
    rows = cluster_rows(page)
    panels: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        groups = _split_row_groups(row)
        xs = [g[1] for g in groups]
        for (txt, x0, _x1), (lo, hi) in zip(groups, _bands(xs)):
            t = re.sub(r"\s+", " ", txt.strip())
            if t.startswith("OTC ") and "/" in t:
                panels.append({"panel": t, "x0": x0, "lo": lo, "hi": hi,
                               "y": row_y(row), "row_idx": i})
    if not panels:
        raise JpmParseError("no 'OTC x's / ...' panel titles found",
                            source=source, page=pno)

    out: list[dict[str, Any]] = []
    for p in panels:
        # the "Current  6M Avg  FV" header lives below this panel's title and
        # inside its x band; stop at the next panel title in the same band
        hdr = None
        for row in rows[p["row_idx"] + 1:]:
            band = [w for w in row if p["lo"] <= w[0] < p["hi"]]
            if not band:
                continue
            txt = row_text(band).strip()
            if re.match(r"^Current\s+(6M|1\s*Yr|3M)\s+Avg\s+FV$", txt):
                hdr = (row, band)
                break
            if txt.startswith("OTC ") and "/" in txt:
                break
        if hdr is None:
            raise JpmParseError("panel has no 'Current <window> Avg FV' header",
                                source=source, page=pno, label=p["panel"])
        hrow, hband = hdr
        anchors: list[float] = []
        avg_label = ""
        k = 0
        while k < len(hband):
            tok = normalise_text(hband[k][4])
            if tok == "Current" or tok == "FV":
                anchors.append((hband[k][0] + hband[k][2]) / 2.0)
                k += 1
            elif tok == "Avg":
                anchors.append((hband[k][0] + hband[k][2]) / 2.0)
                k += 1
            else:
                avg_label = (avg_label + " " + tok).strip()
                k += 1
        if len(anchors) != 3:
            raise JpmParseError(f"expected 3 column anchors, got {len(anchors)}",
                                source=source, page=pno, label=p["panel"])

        rec: dict[str, Any] = {"panel": p["panel"], "avg_label": avg_label}
        m = _OTC_PANEL.match(p["panel"])
        rec["numerator"] = f"OTC {m.group(1)}s" if m else None
        rec["denominator"] = re.sub(r"\s+", " ", normalise_text(m.group(2))) if m else None
        hy = row_y(hrow)
        saw_label = False
        for row in rows:
            if row_y(row) <= hy or row_y(row) > hy + 40:
                continue
            band = [w for w in row if p["lo"] <= w[0] < p["hi"]]
            if not band:
                continue
            lab = normalise_text(band[0][4]).strip()
            if lab not in ("Implied", "Historical"):
                continue
            saw_label = True
            key = lab.lower()
            for w in band[1:]:
                xc = (w[0] + w[2]) / 2.0
                j = min(range(3), key=lambda a: abs(anchors[a] - xc))
                col = ("current", "avg", "fv")[j]
                rec[f"{key}_{col}"] = _to_float(normalise_text(w[4]))
        if not saw_label:
            # the Implied/Historical stubs are missing entirely -> layout broke
            raise JpmParseError("panel table had no Implied/Historical rows",
                                source=source, page=pno, label=p["panel"])
        # a stub with no numbers next to it is a *source* gap (seen on
        # 2024-01-05..11, where the 30s and 10s panels print no values at all),
        # so it is emitted as an all-null row rather than failing the page
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# Maturity Structure of Treasury Volatility
# --------------------------------------------------------------------------
def parse_maturity_structure(page: "fitz.Page", *,
                             source: str = "") -> list[dict[str, Any]]:
    """Parse the four ``Ratio of Price Volatility`` panels.

    Each panel prints a ``Current / <avg> Avg`` block with an ``Implied`` and a
    ``Historical`` value.  The average window label drifts (``6M Avg`` in the
    legacy generation, ``1 Yr Avg`` in v2025), so it is captured rather than
    assumed.
    """
    pno = page.number + 1
    rows = cluster_rows(page)

    labels: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        groups = _split_row_groups(row)
        xs = [g[1] for g in groups]
        for (txt, x0, _x1), (lo, hi) in zip(groups, _bands(xs)):
            m = re.match(r"^\(Front\s+(\w+)\)\s*/\s*\(Front\s+(\w+)\)$",
                         txt.strip())
            if m:
                labels.append({"num": m.group(1), "den": m.group(2),
                               "x0": x0, "lo": lo, "hi": hi, "y": row_y(row),
                               "row_idx": i})
    if not labels:
        raise JpmParseError("no '(Front a)/(Front b)' ratio labels found",
                            source=source, page=pno)

    out: list[dict[str, Any]] = []
    for lab in labels:
        hdr = None
        for row in rows[lab["row_idx"] + 1:]:
            band = [w for w in row if lab["lo"] <= w[0] < lab["hi"]]
            if not band:
                continue
            txt = row_text(band).strip()
            if re.match(r"^Current\s+(6M|1\s*Yr|1M|3M)\s*Avg$", txt):
                hdr = (row, band)
                break
            if re.match(r"^\(Front\s+\w+\)/\(Front\s+\w+\)$", txt):
                break
        if hdr is None:
            raise JpmParseError("ratio panel has no 'Current <window> Avg' header",
                                source=source, page=pno,
                                label=f"{lab['num']}/{lab['den']}")
        hrow, hband = hdr
        anchors: list[float] = []
        avg_label = ""
        for w in hband:
            tok = normalise_text(w[4])
            if tok in ("Current", "Avg"):
                anchors.append((w[0] + w[2]) / 2.0)
            else:
                avg_label = (avg_label + " " + tok).strip()
        if len(anchors) != 2:
            raise JpmParseError(f"expected 2 column anchors, got {len(anchors)}",
                                source=source, page=pno,
                                label=f"{lab['num']}/{lab['den']}")
        rec: dict[str, Any] = {
            "ratio": f"{lab['num']}/{lab['den']}",
            "numerator": lab["num"], "denominator": lab["den"],
            "avg_label": avg_label,
        }
        hy = row_y(hrow)
        got = 0
        for row in rows:
            if row_y(row) <= hy or row_y(row) > hy + 40:
                continue
            band = [w for w in row if lab["lo"] <= w[0] < lab["hi"]]
            if not band:
                continue
            key = normalise_text(band[0][4]).strip().lower()
            if key not in ("implied", "historical"):
                continue
            for w in band[1:]:
                xc = (w[0] + w[2]) / 2.0
                col = "current" if abs(anchors[0] - xc) <= abs(anchors[1] - xc) else "avg"
                rec[f"{key}_{col}"] = _to_float(normalise_text(w[4]))
                got += 1
        if got == 0:
            raise JpmParseError("ratio panel had no Implied/Historical rows",
                                source=source, page=pno,
                                label=f"{lab['num']}/{lab['den']}")
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# U.S. Treasuries Volatility Skew Report
# --------------------------------------------------------------------------
_RE_SKEW_CAPTION = re.compile(
    r"^(?P<mon>[A-Z][a-z]{2})\s+(?P<yy>\d{2})\s+(?P<prod>.+?)\s+futures\s*@\s*"
    r"(?P<px>[\d\-\.\+#]+);\s*ATM\s*imp\.?\s*vol\.?\s*=\s*(?P<atm>[\d\.]+%|N/A);"
    r"\s*Vol\.?\s*beta\s*=\s*(?P<beta>[-\d\.]+|N/A)")


def parse_skew_report(page: "fitz.Page", *, source: str = "") -> dict[str, list]:
    """Parse *U.S. Treasuries Volatility Skew Report*.

    Two products per page.  Each panel has a caption line carrying the futures
    price, the ATM implied vol and the vol beta, plus a strike table with
    columns ``Strike | P/C | Actual | Model | Avg. | Vega | Act.-Mod. |
    Act.-Avg. | Z-Score``.  The chart's own axis tick labels live at x>=335 and
    are excluded by the column x-band, which is why this page is tractable at
    all.

    Returns ``{"captions": [...], "strikes": [...]}``.
    """
    pno = page.number + 1
    rows = cluster_rows(page)
    captions: list[dict[str, Any]] = []
    hdrs: list[tuple[int, list[float]]] = []
    for i, row in enumerate(rows):
        txt = row_text(row).strip()
        m = _RE_SKEW_CAPTION.match(txt)
        if m:
            captions.append({
                "expiry_label": f"{m.group('mon')} {m.group('yy')}",
                "product": m.group("prod").strip(),
                "futures_price_raw": m.group("px"),
                "futures_price": parse_price_32nds(m.group("px")),
                "atm_vol_pct": _to_float(m.group("atm")) if m.group("atm") != "N/A" else None,
                "vol_beta": _to_float(m.group("beta")) if m.group("beta") != "N/A" else None,
                "y": row_y(row),
            })
        band = [w for w in row if w[0] < 335]
        if band and row_text(band).strip().startswith("Strike Actual Model Avg. Vega"):
            hdrs.append((i, [(w[0] + w[2]) / 2.0 for w in band]))
    if not captions:
        raise JpmParseError("no skew caption lines found", source=source, page=pno)

    strikes: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        band = [w for w in row if w[0] < 335]
        if len(band) < 9:
            continue
        toks = [normalise_text(w[4]).strip() for w in band]
        if not re.match(r"^\d+(\.\d+)?$", toks[0]) or toks[1] not in ("P", "C"):
            continue
        nums = [_to_float(t) for t in toks[2:9]]
        if any(v is None for v in nums):
            continue
        y = row_y(row)
        cap = min(captions, key=lambda c: (abs(c["y"] - y) if c["y"] > y else 1e9))
        strikes.append({
            "expiry_label": cap["expiry_label"], "product": cap["product"],
            "strike": float(toks[0]), "put_call": toks[1],
            "actual": nums[0], "model": nums[1], "avg": nums[2], "vega": nums[3],
            "act_minus_mod": nums[4], "act_minus_avg": nums[5], "z_score": nums[6],
        })
    for c in captions:
        c.pop("y", None)
    return {"captions": captions, "strikes": strikes}


# --------------------------------------------------------------------------
# Short-Dated (SOFR) Swaption Volatility Report
# --------------------------------------------------------------------------
#: ``Options on <n>yr Swaps`` -> underlying swap tenor in years.  Matched as a
#: token *subsequence*, never against the whole row: the tenor caption shares
#: its visual row with chart axis labels ("60d Hist", "Volatility (bp)",
#: "Maturity Structure of 3M Vol.") in both generations, so an anchored match
#: silently finds only some of the five blocks -- which then shifts every
#: tenor label by one and is invisible in the output.
_RE_SWPN_TENOR_TOK = re.compile(r"^(\d+)yr$")

#: option maturity labels as printed.  ``12m`` in the legacy generation became
#: ``1y`` in v2025; both mean twelve months and are normalised to 12.
_SWPN_MATURITY_MONTHS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12, "1y": 12}


def _subseq(toks: Sequence[str], pat: Sequence[str]) -> int:
    """Index of the first occurrence of ``pat`` inside ``toks``, else -1."""
    n = len(pat)
    for i in range(len(toks) - n + 1):
        if list(toks[i:i + n]) == list(pat):
            return i
    return -1


def _swpn_band_rows(page: "fitz.Page", right: float, ytol: float) -> list[list[Word]]:
    """Cluster into rows using **only** words left of ``right``.

    Clustering the whole page cannot work here.  ``cluster_rows`` anchors each
    row on its first word and admits everything within ``ytol`` of that
    anchor, so a chart tick label 4pt above a table row silently becomes the
    anchor and pushes the table row's own *label* into the next cluster --
    observed on 2019-08-26, where the 5yr ``3m`` row split into ``61.32 5.15
    0.16 1.14`` at y=325.8 and a lone ``3m`` at y=327.6, and the row came out
    all-None.  Dropping the chart words *before* clustering removes the
    spurious anchors entirely.
    """
    words = [w for w in page.get_text("words") if (w[0] + w[2]) / 2.0 <= right]
    rows: list[list[Word]] = []
    cur: list[Word] = []
    anchor: float | None = None
    for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2.0, w[0])):
        yc = (w[1] + w[3]) / 2.0
        if anchor is None or abs(yc - anchor) <= ytol:
            if anchor is None:
                anchor = yc
            cur.append(w)
        else:
            rows.append(sorted(cur, key=lambda w: w[0]))
            cur = [w]
            anchor = yc
    if cur:
        rows.append(sorted(cur, key=lambda w: w[0]))
    return rows


def _swpn_scan(rows: Sequence[Sequence[Word]]) -> tuple[
        list[tuple[float, int]],
        list[tuple[float, float, list[float]]],
        list[tuple[float, list[float]]]]:
    """``(tenor captions, implied-column headers, historical-column headers)``.

    The tenor caption is matched as a token *subsequence*, never against the
    whole row: it shares its visual row with chart axis labels in both
    generations, and an anchored match finds only some of the five blocks --
    which then shifts every tenor label by one and is invisible in the output.

    The column headers are matched the same way for symmetry, but there it is
    defensive rather than load-bearing: over 246 sampled archive files the
    ``Mat % bp Chg Chg`` run always starts at index 0 of its row.
    """
    tenor_at: list[tuple[float, int]] = []
    header_at: list[tuple[float, float, list[float]]] = []
    hist_at: list[tuple[float, list[float]]] = []
    for row in rows:
        toks = [normalise_text(w[4]).strip() for w in row]
        for i, t in enumerate(toks):
            m = _RE_SWPN_TENOR_TOK.match(toks[i + 2]) if i + 2 < len(toks) else None
            if (t == "Options" and toks[i + 1:i + 2] == ["on"]
                    and toks[i + 3:i + 4] == ["Swaps"] and m):
                tenor_at.append((row_y(row), int(m.group(1))))
                break
        j = _subseq(toks, ["Mat", "%", "bp", "Chg", "Chg"])
        if j >= 0:
            header_at.append((row_y(row),
                              (row[j][0] + row[j][2]) / 2.0,
                              [(w[0] + w[2]) / 2.0 for w in row[j + 1:j + 5]]))
        k = _subseq(toks, ["10d", "20d", "60d"])
        if k >= 0:
            hist_at.append((row_y(row),
                            [(w[0] + w[2]) / 2.0 for w in row[k:k + 3]]))
    return tenor_at, header_at, hist_at


def _swpn_pick(row: Sequence[Word], anchors: Sequence[float],
               *, xtol: float = 6.0) -> list[float | None]:
    """Value under each column anchor, matched by x-centre, else ``None``.

    The four implied columns sit at fixed x across the whole archive but the
    *centres* drift a couple of points between generations (``%`` at 65 in
    2019, 74 in 2026), so matching is nearest-anchor-within-tolerance rather
    than by token order.  Order matching would silently mis-assign a row that
    is missing one cell, which is exactly the failure this page can produce.
    """
    out: list[float | None] = [None] * len(anchors)
    for w in row:
        xc = (w[0] + w[2]) / 2.0
        tok = normalise_text(w[4]).strip()
        if not _is_value(tok):
            continue
        j = min(range(len(anchors)), key=lambda k: abs(anchors[k] - xc))
        if abs(anchors[j] - xc) <= xtol and out[j] is None:
            out[j] = _to_float(tok)
    return out


def parse_swaption_report(page: "fitz.Page", *, source: str = "") -> list[dict[str, Any]]:
    """Parse *Short-Dated [SOFR] Swaption Volatility Report* -> one row per
    (swap tenor, option maturity).

    This is J.P. Morgan's **OTC swaption** grid, and the only page in the
    package that quotes the OTC leg in numbers rather than in a chart.  It is
    what makes the listed-vs-OTC basis testable against an outside source in
    our own units: the ``bp`` column is a **daily** basis-point normal yield
    vol, on the same convention as the ``BASIS POINT VOLATILITY`` block of the
    Treasury Volatility Summary.

    Layout (identical in structure across both generations, only the x-anchors
    and the ``12m``/``1y`` label differ)::

        Options on 10yr Swaps
                Implied Vol.   5d   20d      Historical BP Vol.
        Mat       %      bp   Chg   Chg      10d    20d    60d
        1m     30.75   6.64 -0.59 -0.60     7.84   6.08   7.43
        3m     31.05   6.63 -0.60 -0.79    *1dc   1wc    2wc
        6m     31.67   6.64 -0.48 -0.52     6.08   5.28   4.66
        12m    32.40   6.60 -0.33 -0.29

    The historical block is **not** per option maturity: the row aligned with
    ``1m`` is the 10/20/60-day realised bp vol of the spot swap rate, and the
    row aligned with ``6m`` is one-month realised bp vol measured over 1-day,
    1-week and 2-week changes (the page's own footnote).  Both are therefore
    carried as block-level fields repeated on every maturity of that tenor,
    never as a per-maturity quantity.

    Each page carries five tenor blocks (1/2/5/10/30yr) in a single left-hand
    column; the charts to their right are excluded by the column x-band
    derived from the ``Mat`` header itself, not by a hard-coded x.
    """
    pno = page.number + 1
    # Pass 1 finds the column band on the whole page; passes 2..3 re-cluster
    # inside that band so the charts cannot anchor a row.  Pass 1 needs a loose
    # ytol because the whole-page headers carry up to 3pt of baseline jitter
    # ("%" sits 2.9pt above its own "Mat bp Chg Chg" on the 2026 issues, "20d"
    # 2.5pt above "10d 60d"), and it only has to find *one* header to fix the
    # band.  4.0 is safe: data rows are 11-12pt apart.
    #
    # The band restriction, not the tolerance, is what makes this work: with
    # the chart words dropped first, ytol 2.0 / 3.0 / 4.0 / 6.0 / 8.0 all give
    # byte-identical output over 341 sampled archive pages.
    rows: Sequence[Sequence[Word]] = cluster_rows(page, ytol=4.0)
    tenor_at, header_at, hist_at = _swpn_scan(rows)
    if not tenor_at:
        raise JpmParseError("no 'Options on <n>yr Swaps' blocks found",
                            source=source, page=pno)
    if not header_at:
        raise JpmParseError("no 'Mat % bp Chg Chg' header found",
                            source=source, page=pno)

    right = 0.0
    for _ in range(3):
        new_right = max([a for _, anc in hist_at for a in anc]
                        + [a for _, _, anc in header_at for a in anc]) + 12.0
        if new_right <= right:
            break
        right = new_right
        rows = _swpn_band_rows(page, right, ytol=4.0)
        tenor_at, header_at, hist_at = _swpn_scan(rows)
        if not tenor_at or not header_at:
            raise JpmParseError("column band lost the table headers",
                                source=source, page=pno)

    tenor_at.sort()
    out: list[dict[str, Any]] = []
    for k, (y0, tenor) in enumerate(tenor_at):
        y1 = tenor_at[k + 1][0] if k + 1 < len(tenor_at) else 1e9
        hdr = [h for h in header_at if y0 < h[0] < y1]
        if not hdr:
            raise JpmParseError("tenor block without a column header",
                                source=source, page=pno, label=f"{tenor}yr")
        _, mat_x, imp_anchors = hdr[0]
        hist_anchors = next((a for yh, a in hist_at if y0 < yh < y1), None)

        # value rows: leftmost token is the maturity label under 'Mat'
        block: list[tuple[str, list[float | None], float]] = []
        for row in rows:
            y = row_y(row)
            if not (y0 < y < y1):
                continue
            band = [w for w in row if (w[0] + w[2]) / 2.0 <= right]
            if not band:
                continue
            lab = normalise_text(band[0][4]).strip()
            if lab not in _SWPN_MATURITY_MONTHS:
                continue
            if abs((band[0][0] + band[0][2]) / 2.0 - mat_x) > 8.0:
                continue
            block.append((lab, _swpn_pick(band[1:], imp_anchors), y))

        if not block:
            raise JpmParseError("tenor block with no maturity rows",
                                source=source, page=pno, label=f"{tenor}yr")

        # the two historical triples, keyed by the maturity row they sit
        # nearest to: the 10d/20d/60d figures next to ``1m`` and the
        # 1dc/1wc/2wc figures next to ``6m``.  In the legacy generation they
        # share the maturity row itself; in v2025 they sit on their own row a
        # few points below it -- nearest-y handles both without a branch.
        hist: dict[str, list[float | None]] = {}
        if hist_anchors is not None:
            for row in rows:
                y = row_y(row)
                if not (y0 < y < y1):
                    continue
                band = [w for w in row if (w[0] + w[2]) / 2.0 <= right]
                vals = _swpn_pick(band, hist_anchors)
                if all(v is None for v in vals):
                    continue
                near = min(block, key=lambda b: abs(b[2] - y))
                hist.setdefault(near[0], vals)

        h_daily = hist.get("1m", [None, None, None])
        h_chg = hist.get("6m", [None, None, None])
        for lab, vals, _y in block:
            out.append({
                "tenor_years": tenor,
                "maturity_label": lab,
                "maturity_months": _SWPN_MATURITY_MONTHS[lab],
                "impl_pct": vals[0],
                "impl_bp_day": vals[1],
                "impl_bp_chg_5d": vals[2],
                "impl_bp_chg_20d": vals[3],
                "hist_bp_10d": h_daily[0],
                "hist_bp_20d": h_daily[1],
                "hist_bp_60d": h_daily[2],
                "hist_bp_1dc": h_chg[0],
                "hist_bp_1wc": h_chg[1],
                "hist_bp_2wc": h_chg[2],
            })

    if all(r["impl_bp_day"] is None for r in out):
        raise JpmEmptyPage("swaption grid parsed but every implied cell empty",
                           source=source, page=pno)
    return out
