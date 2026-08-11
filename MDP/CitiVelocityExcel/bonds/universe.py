r"""The Citi Velocity bond universe: descriptions in, typed descriptors out.

Bonds are a **two-step mechanism**, not a tag family. ``RATES.BOND`` has zero
children in the DAG because the ISIN universe is far too large for a browse
tree, so:

1. ``CVCURVEBOND("RATES.BONDS.BY_COUNTRY.<CTRY>.<CCY>.ASSET_TYPE_<TYPE>.<MEASURE>.<yyyymmdd>")``
   returns ``Date | ISIN | Description | <measure>`` - the universe;
2. ``RATES.BOND.<ISIN>.<value>`` is one bond's timeseries.

This module turns step 1's ``Description`` column into something a pricer can
use. The committed catalog holds 2,162 ISINs over 18 countries, and
:class:`BondUniverse` reads them without touching Excel.

The date order is MM/DD/YYYY, and that is measured, not assumed
----------------------------------------------------------------
Across all 2,162 committed descriptions the FIRST date field is never greater
than 12, while the SECOND exceeds 12 in 1,647 of them. A day-first reading would
therefore have to explain 1,647 months numbered 13-31. The order is US
month-first, unambiguously. ``_DAY_FIRST_COUNTRIES`` exists as an override hook
and is deliberately **empty**: no country in this universe emits day-first, and
guessing per country would be inventing a rule the data contradicts.

What the descriptions actually look like
----------------------------------------
2,157 of 2,162 are exactly ``<TICKER> <COUPON> <MM/DD/YY[YY]>``. The remaining
five are::

    BADWUR 7 3/4 08/18/26                             mixed-fraction coupon
    BTPS 3 1/4 03/05/30                               mixed-fraction coupon
    BTPS 0 3/4 11/16/33                               mixed-fraction coupon
    BTPS 3 1/4 06/13/27                               mixed-fraction coupon
    CHINA(PEOPLES REP)-0% SNR 03/12/2027 CNY100000    a prospectus line, not a ticker

plus ten ``Float`` coupons (``CCTS Float 04/15/29``) and one ``ZERO``
(``FHLMC ZERO 11/15/38``). Nineteen carry a two-digit year.

The parser never guesses. A coupon it cannot read comes back ``None`` (which is
also the right answer for a floater), a ticker that is not ticker-shaped comes
back ``""``, and an unreadable date comes back ``None``. It does not, for
example, decide that ``REP)-0%`` means zero.
"""

from __future__ import annotations

import datetime
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.catalog import BondRef, CitiVeloCatalog
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.tags import BOND_VALUES, bond_curve

__all__ = [
    "BondDescriptor",
    "BondUniverse",
    "parse_bond_description",
    "fetch_universe",
    "cross_currency_asw_legs",
    "ASW_CURRENCIES",
]

_logger = logging.getLogger(__name__)

#: ``MM/DD/YY`` or ``MM/DD/YYYY``, anchored so a stray number cannot match.
_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$")

#: A plausible bond ticker: starts with a letter, then letters/digits and the few
#: punctuation marks issuers actually use. Rejects ``CHINA(PEOPLES``, which is the
#: one description in the universe that is a prospectus line rather than a ticker.
_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9&._/+-]{0,14}$")

#: ``a b/c`` and ``b/c`` coupon spellings - four BTPs and one German Land quote
#: their coupon as a mixed fraction rather than a decimal.
_WHOLE_RE = re.compile(r"^(\d+)$")
_FRACTION_RE = re.compile(r"^(\d+)/(\d+)$")

#: Coupon words that carry information. ``ZERO`` is a real 0% coupon; the floater
#: words mean "there is no fixed coupon", which is ``None``, not zero.
_ZERO_WORDS = frozenset({"ZERO", "ZEROCPN", "0%"})
_FLOAT_WORDS = frozenset({"FLOAT", "FLOATING", "FLTG", "FRN", "VAR"})

#: Countries whose descriptions are day-first. EMPTY on measured evidence: the
#: first date field never exceeds 12 in any of the 2,162 committed descriptions
#: while the second exceeds 12 in 1,647 of them.
_DAY_FIRST_COUNTRIES: frozenset[str] = frozenset()

#: The six legs of the sparse ``ASW_4_<CCY>`` cross-currency matrix.
ASW_CURRENCIES: Tuple[str, ...] = ("USD", "EUR", "GBP", "CHF", "JPY", "AUD")


# ------------------------------------------------------------------ #
#                              parsing                               #
# ------------------------------------------------------------------ #


def _expand_two_digit_year(yy: int, reference: datetime.date) -> int:
    """Map a two-digit year onto the century that keeps the bond alive.

    Candidates are 1900/2000/2100 + ``yy``; the smallest one not already more
    than a year in the past wins. ``08/18/26`` reads as 2026 against a 2026
    reference, and a hypothetical ``03/21/19`` on a 2119-maturity Land bond
    reads as 2119 rather than a matured 2019.
    """
    for century in (1900, 2000, 2100):
        year = century + yy
        if year >= reference.year - 1:
            return year
    return 2000 + yy


def _parse_date_token(token: str, *, day_first: bool, reference: datetime.date) -> Optional[datetime.date]:
    m = _DATE_RE.match(token)
    if not m:
        return None
    a, b, y = int(m.group(1)), int(m.group(2)), m.group(3)
    month, day = (b, a) if day_first else (a, b)
    year = int(y) if len(y) == 4 else _expand_two_digit_year(int(y), reference)
    try:
        return datetime.date(year, month, day)
    except ValueError:
        return None


def _parse_coupon_tokens(tokens: Sequence[str]) -> Optional[float]:
    """Read ``['4.25']``, ``['7', '3/4']``, ``['Float']`` or ``['ZERO']``."""
    if not tokens:
        return None
    upper = [t.upper() for t in tokens]
    if len(tokens) == 1:
        tok, up = tokens[0], upper[0]
        if up in _FLOAT_WORDS:
            return None
        if up in _ZERO_WORDS:
            return 0.0
        frac = _FRACTION_RE.match(tok)
        if frac:
            denom = int(frac.group(2))
            return int(frac.group(1)) / denom if denom else None
        try:
            return float(tok)
        except ValueError:
            return None
    if len(tokens) == 2:
        whole = _WHOLE_RE.match(tokens[0])
        frac = _FRACTION_RE.match(tokens[1])
        if whole and frac:
            denom = int(frac.group(2))
            if denom:
                return int(whole.group(1)) + int(frac.group(1)) / denom
    return None


def _is_coupon_token(token: str) -> bool:
    up = token.upper()
    if up in _FLOAT_WORDS or up in _ZERO_WORDS:
        return True
    if _FRACTION_RE.match(token) or _WHOLE_RE.match(token):
        return True
    try:
        float(token)
    except ValueError:
        return False
    return True


def parse_bond_description(
    text: str,
    *,
    country: Optional[str] = None,
    reference: Optional[datetime.date] = None,
) -> Tuple[str, Optional[float], Optional[datetime.date]]:
    """Split a ``CVCURVEBOND`` description into ticker, coupon and maturity.

    >>> parse_bond_description("T 1.25 08/15/2031")
    ('T', 1.25, datetime.date(2031, 8, 15))
    >>> parse_bond_description("BADWUR 7 3/4 08/18/26")
    ('BADWUR', 7.75, datetime.date(2026, 8, 18))
    >>> parse_bond_description("CCTS Float 04/15/29")
    ('CCTS', None, datetime.date(2029, 4, 15))

    The coupon is taken as the maximal run of number-like tokens ending just
    before the date, so a multi-word ticker and a mixed-fraction coupon are both
    handled without a special case. At least one token is always left for the
    ticker.

    Parameters
    ----------
    text
        The raw ``Description`` cell.
    country
        ISO-3 country of the bond, used only to consult
        ``_DAY_FIRST_COUNTRIES``. That set is empty on measured evidence (see the
        module docstring), so this argument currently never changes the result;
        it exists so a future source with day-first dates can be switched on
        without editing the parser.
    reference
        Date against which a two-digit year is resolved. Defaults to today.

    Returns
    -------
    tuple
        ``(ticker, coupon_percent, maturity)``. Any element that cannot be read
        is ``""`` / ``None`` / ``None`` respectively - the parser never guesses.
        A floating-rate note returns ``None`` for the coupon, which is correct
        rather than a failure.
    """
    ref = reference or datetime.date.today()
    day_first = bool(country) and str(country).strip().upper() in _DAY_FIRST_COUNTRIES
    raw = "" if text is None else str(text).strip()
    if not raw:
        return "", None, None

    tokens = raw.split()
    maturity: Optional[datetime.date] = None
    date_idx: Optional[int] = None
    for i in range(len(tokens) - 1, -1, -1):
        parsed = _parse_date_token(tokens[i], day_first=day_first, reference=ref)
        if parsed is not None:
            maturity, date_idx = parsed, i
            break

    head = tokens[:date_idx] if date_idx is not None else tokens
    cut = len(head)
    while cut > 1 and _is_coupon_token(head[cut - 1]):
        cut -= 1
    coupon = _parse_coupon_tokens(head[cut:])

    ticker_raw = " ".join(head[:cut]).strip()
    ticker = ticker_raw if _TICKER_RE.match(ticker_raw) else ""
    return ticker, coupon, maturity


# ------------------------------------------------------------------ #
#                            the record                              #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class BondDescriptor:
    """One bond, as much as Citi tells us about it.

    Attributes
    ----------
    isin
        The ISIN, which is the only identifier ``RATES.BOND.<ISIN>.<value>``
        accepts.
    description
        The raw ``Description`` cell, kept verbatim so a parse can be re-checked.
    ticker
        Issuer ticker (``T``, ``DBR``, ``UKT``, ``FHLB``), or ``""`` when the
        description was not ticker-shaped.
    coupon
        Annual coupon in PERCENT (``4.25`` means 4.25%), or ``None`` for a
        floater or an unreadable coupon.
    maturity
        Redemption date, or ``None`` when neither the description nor the
        universe's own maturity column parsed.
    country, currency, asset_type
        The three segments of the ``CVCURVEBOND`` universe key.
    source
        Where this row came from: ``catalog`` (the committed 2,162-ISIN
        harvest) or ``cvcurvebond`` (a live fetch).
    """

    isin: str
    description: str
    ticker: str
    coupon: Optional[float]
    maturity: Optional[datetime.date]
    country: str
    currency: str
    asset_type: str
    source: str = "catalog"

    @property
    def universe_key(self) -> str:
        return f"{self.country}.{self.currency}.{self.asset_type}"

    @property
    def priceable(self) -> bool:
        """True when both a fixed coupon and a maturity are known.

        A descriptor that is not priceable must NOT be handed to
        :func:`~MDP.CitiVelocityExcel.bonds.rl_bonds.build_rl_bond`; those
        builders raise rather than substitute a zero coupon.
        """
        return self.coupon is not None and self.maturity is not None

    def tag(self, value: str = "YIELD") -> str:
        """The ``RATES.BOND.<ISIN>.<value>`` timeseries tag for this bond."""
        from MDP.CitiVelocityExcel.tags import bond as _bond_tag

        return _bond_tag(self.isin, value)


def _descriptor_from_ref(ref: BondRef, *, reference: Optional[datetime.date] = None) -> BondDescriptor:
    """Descriptor from a catalog row, preferring the harvest's own maturity column.

    The catalog carries a dedicated ``maturity`` field alongside the description,
    and a dedicated field beats a substring. They disagree on exactly ONE of the
    2,162 rows: ``CND10003W0P5 'CHINA(PEOPLES REP)-0% SNR 03/12/2027 CNY100000'``,
    where the description is a prospectus line whose date is day-first (3 Dec
    2027) while the column reads ``12/3/2027`` month-first - the same day. Taking
    the column keeps that row right and costs nothing on the other 2,161. The
    live ``CVCURVEBOND`` path has no such column and falls back to the parse.
    """
    ticker, coupon, maturity = parse_bond_description(
        ref.description, country=ref.country, reference=reference
    )
    if ref.maturity:
        from_column = _parse_date_token(
            str(ref.maturity).strip(),
            day_first=False,
            reference=reference or datetime.date.today(),
        )
        if from_column is not None:
            if maturity is not None and from_column != maturity:
                _logger.debug(
                    "%s: description maturity %s disagrees with the universe column %s; "
                    "taking the column.",
                    ref.isin,
                    maturity,
                    from_column,
                )
            maturity = from_column
    return BondDescriptor(
        isin=ref.isin,
        description=ref.description,
        ticker=ticker,
        coupon=coupon,
        maturity=maturity,
        country=ref.country,
        currency=ref.currency,
        asset_type=ref.asset_type,
        source="catalog",
    )


# ------------------------------------------------------------------ #
#                            the universe                            #
# ------------------------------------------------------------------ #


class BondUniverse:
    """An indexed, filterable view over a set of :class:`BondDescriptor`.

    >>> uni = BondUniverse.from_catalog(country="USA", asset_type="GOVT")
    >>> len(uni) > 300
    True
    >>> uni.lookup("US91282CCS89").ticker
    'T'

    A plain class rather than a dataclass: it owns a lazily built ISIN index and
    an optional catalog handle, which is state, not a value.
    """

    def __init__(
        self,
        descriptors: Iterable[BondDescriptor],
        *,
        catalog: Optional[CitiVeloCatalog] = None,
    ) -> None:
        self._rows: List[BondDescriptor] = list(descriptors)
        self._catalog = catalog
        self._by_isin: Dict[str, BondDescriptor] = {}
        for row in self._rows:
            self._by_isin.setdefault(row.isin.upper(), row)

    # -- construction ---------------------------------------------------

    @classmethod
    def from_catalog(
        cls,
        *,
        country: Optional[str] = None,
        currency: Optional[str] = None,
        asset_type: Optional[str] = None,
        catalog: Optional[CitiVeloCatalog] = None,
        reference: Optional[datetime.date] = None,
    ) -> "BondUniverse":
        """Build from the committed harvest. No Excel needed.

        The PARSE is memoised, the universe object is not
        ---------------------------------------------------
        Every call re-derived a descriptor for every row, and
        ``parse_bond_description`` is not cheap. That is invisible when a process
        builds one universe and expensive when it builds one per date: profiled on
        a forty-date offline pricer loop, ``from_catalog`` was **31% of total
        runtime** - 107,600 descriptions parsed for a catalog that had not changed,
        3.7 s of 12.1 s.

        So the descriptor tuple is cached **on the catalog instance**, keyed by the
        filter and the reference date. Tying it to the catalog rather than to a
        module-level dict is what makes invalidation right for free: replacing
        ``CitiVeloCatalog.default()`` - which is how a re-seeded catalog is
        installed - brings a new cache with it, and a caller passing its own
        catalog gets its own.

        A **new** ``BondUniverse`` is still constructed each call. Descriptors are
        frozen and shareable; the universe owns a mutable ISIN index, and handing
        the same instance to two callers would make one caller's lazy state the
        other's. Rebuilding it over a cached tuple costs microseconds - the parse
        was the whole cost.
        """
        cat = catalog if catalog is not None else CitiVeloCatalog.default()
        key = (
            str(country).upper() if country else None,
            str(currency).upper() if currency else None,
            str(asset_type).upper() if asset_type else None,
            reference,
        )
        memo = getattr(cat, "_descriptor_memo", None)
        if memo is None:
            memo = {}
            try:
                cat._descriptor_memo = memo  # type: ignore[attr-defined]
            except AttributeError:  # a catalog that forbids attributes still works
                memo = None
        cached = memo.get(key) if memo is not None else None
        if cached is None:
            refs = cat.bonds(country=country, currency=currency, asset_type=asset_type)
            cached = tuple(_descriptor_from_ref(r, reference=reference) for r in refs)
            if memo is not None:
                memo[key] = cached
        return cls(cached, catalog=cat)

    @classmethod
    def from_curve_frame(
        cls,
        df: "pd.DataFrame",
        *,
        country: str,
        currency: str,
        asset_type: str,
        catalog: Optional[CitiVeloCatalog] = None,
        reference: Optional[datetime.date] = None,
    ) -> "BondUniverse":
        """Build from a live ``CVCURVEBOND`` grid.

        Parameters
        ----------
        df
            The frame :meth:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient.curve_bond`
            returns: ``Date | ISIN | Description | <measure>``.
        country, currency, asset_type
            The universe key the grid was fetched for. ``CVCURVEBOND`` does not
            echo them back, so they have to be supplied.

        Raises
        ------
        CitiVelocityError
            When the frame has no ``ISIN`` column. An empty frame is accepted
            (that is a real answer for a thin universe such as ``GBR/AGENCY``,
            which has two bonds) but a frame with the wrong SHAPE is not - it
            means the block layout changed and silently returning an empty
            universe would read as "this country has no bonds".
        """
        cat = catalog if catalog is not None else CitiVeloCatalog.default()
        if df is None or len(df.columns) == 0:
            return cls([], catalog=cat)
        cols = {str(c).strip().lower(): c for c in df.columns}
        if "isin" not in cols:
            raise CitiVelocityError(
                "CVCURVEBOND frame has no ISIN column (columns: "
                f"{list(df.columns)}). Expected 'Date | ISIN | Description | <measure>'; "
                "the block layout must have changed - do not treat this as an empty universe."
            )
        isin_col = cols["isin"]
        desc_col = cols.get("description")
        rows: List[BondDescriptor] = []
        for _, row in df.iterrows():
            isin = row[isin_col]
            if isin is None or str(isin).strip() == "":
                continue
            desc = "" if desc_col is None else ("" if row[desc_col] is None else str(row[desc_col]))
            ticker, coupon, maturity = parse_bond_description(
                desc, country=country, reference=reference
            )
            rows.append(
                BondDescriptor(
                    isin=str(isin).strip().upper(),
                    description=desc.strip(),
                    ticker=ticker,
                    coupon=coupon,
                    maturity=maturity,
                    country=str(country).strip().upper(),
                    currency=str(currency).strip().upper(),
                    asset_type=str(asset_type).strip().upper().removeprefix("ASSET_TYPE_"),
                    source="cvcurvebond",
                )
            )
        return cls(rows, catalog=cat)

    # -- access ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self._rows)

    def __iter__(self) -> Iterator[BondDescriptor]:
        return iter(self._rows)

    def __repr__(self) -> str:
        keys = sorted({r.universe_key for r in self._rows})
        shown = ", ".join(keys[:4]) + (f" (+{len(keys) - 4})" if len(keys) > 4 else "")
        return f"<BondUniverse {len(self._rows)} bonds [{shown}]>"

    def lookup(self, isin: str) -> Optional[BondDescriptor]:
        """The descriptor for one ISIN, or ``None`` when it is not in this set."""
        return self._by_isin.get(str(isin).strip().upper())

    def filter(
        self,
        *,
        country: Optional[str] = None,
        currency: Optional[str] = None,
        asset_type: Optional[str] = None,
        ticker: Optional[str] = None,
        maturity_before: Optional[datetime.date] = None,
        maturity_after: Optional[datetime.date] = None,
        priceable: Optional[bool] = None,
    ) -> "BondUniverse":
        """A new universe narrowed by any combination of these.

        Bonds with an unknown maturity are excluded by either maturity filter -
        an unknown date cannot satisfy an inequality, and defaulting it either
        way would silently include or drop them.
        """
        rows = self._rows
        if country:
            token = str(country).strip().upper()
            rows = [r for r in rows if r.country == token]
        if currency:
            token = str(currency).strip().upper()
            rows = [r for r in rows if r.currency == token]
        if asset_type:
            token = str(asset_type).strip().upper().removeprefix("ASSET_TYPE_")
            rows = [r for r in rows if r.asset_type == token]
        if ticker:
            token = str(ticker).strip().upper()
            rows = [r for r in rows if r.ticker.upper() == token]
        if maturity_before is not None:
            rows = [r for r in rows if r.maturity is not None and r.maturity < maturity_before]
        if maturity_after is not None:
            rows = [r for r in rows if r.maturity is not None and r.maturity > maturity_after]
        if priceable is not None:
            rows = [r for r in rows if r.priceable is bool(priceable)]
        return BondUniverse(rows, catalog=self._catalog)

    def to_frame(self) -> "pd.DataFrame":
        """One row per bond, sorted by country then maturity then ISIN."""
        records = [
            {
                "isin": r.isin,
                "ticker": r.ticker,
                "coupon": r.coupon,
                "maturity": r.maturity,
                "country": r.country,
                "currency": r.currency,
                "asset_type": r.asset_type,
                "description": r.description,
                "source": r.source,
                "priceable": r.priceable,
            }
            for r in self._rows
        ]
        df = pd.DataFrame.from_records(
            records,
            columns=[
                "isin", "ticker", "coupon", "maturity", "country", "currency",
                "asset_type", "description", "source", "priceable",
            ],
        )
        if len(df):
            df = df.sort_values(
                ["country", "maturity", "isin"], na_position="last", kind="mergesort"
            ).reset_index(drop=True)
        return df

    def available_values(self, isin: str) -> List[str]:
        """Which ``RATES.BOND.<ISIN>.<value>`` tags were probed valid for this bond.

        Read from the committed 16,288-tag validation set, so it costs nothing
        and needs no Excel. An empty list is NOT proof the bond has no data: the
        sweep covered 2,147 of the 2,162 ISINs, and ``empty`` in a 1-week window
        is not the same as invalid (bond ``OAS`` in particular needs a longer
        window before it shows anything).
        """
        cat = self._catalog if self._catalog is not None else CitiVeloCatalog.default()
        code = str(isin).strip().upper()
        return [v for v in BOND_VALUES if cat.bond_tag_is_validated(f"RATES.BOND.{code}.{v}")]

    def parse_failures(self) -> List[BondDescriptor]:
        """Every descriptor whose coupon or maturity did not parse."""
        return [r for r in self._rows if not r.priceable]


# ------------------------------------------------------------------ #
#                         cross-currency ASW                         #
# ------------------------------------------------------------------ #


def cross_currency_asw_legs(
    descriptor: BondDescriptor,
    *,
    catalog: Optional[CitiVeloCatalog] = None,
) -> List[str]:
    """Which ``ASW_4_<CCY>`` legs are actually populated for this bond.

    ``ASW_4_<CCY>`` is a **sparse cross-currency matrix, not the bond's own
    currency**. Measured over the committed validation set: a bund carries
    ``ASW_4_USD/GBP/CHF/AUD`` but NOT ``ASW_4_EUR``; a gilt carries
    ``ASW_4_EUR/GBP/AUD``; a Treasury carries ``ASW_4_USD/JPY``. Counts over all
    16,288 validated tags: AUD 1,120, GBP 1,110, USD 1,081, CHF 689, EUR 418,
    JPY 324 - against 2,105 bonds with a ``PRICE``. There is no derivable rule,
    which is why this reads the validated set rather than computing anything.

    Returns
    -------
    list of str
        Currency codes, in the fixed ``ASW_CURRENCIES`` order. Empty when none
        were validated for this ISIN - which is a statement about the sweep, not
        a guarantee the add-in would refuse the tag.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    code = str(descriptor.isin).strip().upper()
    return [c for c in ASW_CURRENCIES if cat.bond_tag_is_validated(f"RATES.BOND.{code}.ASW_4_{c}")]


# ------------------------------------------------------------------ #
#                            live fetch                              #
# ------------------------------------------------------------------ #


def fetch_universe(
    *,
    client: Any,
    country: str,
    currency: str,
    asset_type: str,
    measure: str = "YIELD",
    when: Optional[datetime.date] = None,
) -> BondUniverse:
    """Fetch one country's bond universe live through ``CVCURVEBOND``.

    Parameters
    ----------
    client
        A :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient`, or
        anything with a compatible ``curve_bond(tag) -> DataFrame``.
    country, currency, asset_type
        Universe key segments, e.g. ``("USA", "USD", "GOVT")``. ``asset_type``
        accepts either ``GOVT`` or ``ASSET_TYPE_GOVT``.
    measure
        The measure column ``CVCURVEBOND`` returns alongside the ISIN. Note this
        vocabulary is NOT the per-bond timeseries vocabulary: ``CVCURVEBOND``
        accepts ``OAS`` but not ``DV01``.
    when
        Snapshot date. Defaults to today.

    Returns
    -------
    BondUniverse
        With ``source="cvcurvebond"`` on every descriptor.

    Raises
    ------
    UnknownTagError
        For an unknown asset type or measure (raised by
        :func:`~MDP.CitiVelocityExcel.tags.bond_curve`).
    CitiVelocityError
        When the grid comes back without an ISIN column.

    Notes
    -----
    This is the only function in this module that needs a live, signed-in Excel.
    Everything else runs off the committed catalog. It is therefore **unverified
    against the live add-in in this build** - it has been exercised only against
    :mod:`MDP.CitiVelocityExcel.testing`'s fake COM surface.
    """
    tag = bond_curve(country, currency, asset_type, measure, when)
    df = client.curve_bond(tag)
    return BondUniverse.from_curve_frame(
        df,
        country=country,
        currency=currency,
        asset_type=asset_type,
        reference=when,
    )
