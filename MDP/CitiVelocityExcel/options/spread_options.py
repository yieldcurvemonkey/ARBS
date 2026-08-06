r"""Single-look CMS spread options: ``RATES.SPREAD_OPTIONS.<ccy>.<kind>.<value>.<expiry>.<pair>``.

A **single-look** CMS spread option is ONE European option on the difference of
two forward CMS rates observed at ONE expiry::

    payoff = annuity x max( eta * ( CMS_long(T) - CMS_short(T) - K ), 0 )

It is *not* a CMS spread cap or floor. A cap is a **strip** of such options, one
per accrual period of a swap, each on its own fixing of the spread. The two are
different instruments with different vega, different correlation exposure and
different prices; the whole reason this module exists is to keep them apart.

What is verified and what is not
--------------------------------
**The tag shape below ``PRICE``/``VOL`` is UNVERIFIED.** The Function Builder
walk was depth-capped above the expiry level, so ``RATES.SPREAD_OPTIONS`` is
recorded only to ``<ccy>.<kind>.{PRICE,VOL}``. The expiry and pair levels come
from the desk's documented shape.  :func:`~MDP.CitiVelocityExcel.tags.spread_option`
warns about this and so does :func:`fetch_spread_options`; validate with
``client.validate_with_controls([...])`` before trusting a fetch.  The *units* of
the served ``PRICE`` and ``VOL`` are equally unverified - :class:`SpreadOptionQuote`
stores whatever the add-in returns, unconverted, and says so.

**The pricing below is verified**, against QuantLib, at the numbers ``_smoke.py``
prints. Both checks are quoted with their control, because a check without one
says nothing about which of its assumptions is doing the work:

* the closed-form Hagan convexity adjustment in
  :func:`hagan_convexity_adjustment`, on a 10Y CMS at 1Y/2Y/5Y/10Y expiries with
  a 100 bp normal vol, matches ``ql.LinearTsrPricer`` to **0.006 bp on a flat
  curve** - where Hagan's own flat-yield assumption is true, so that gap is pure
  algebra - and to **0.20 bp on a 3.0%-to-4.7% sloped curve**, which is the
  approximation's real cost and the number to quote;
* the Bachelier single look in :func:`single_look_spread_option_price` matches
  ``ql.LognormalCmsSpreadPricer``'s caplet rate to **9e-15 bp** across ``rho`` in
  ``[-0.5, +0.99]`` when the swaption surface is NORMAL. That is a wiring check,
  not a model check: with normal marginals and a normal copula the pricer's 2-d
  integral collapses to this same formula. Against a LOGNORMAL surface with
  ATM-matched vols the two differ by about **0.5 bp** on a 1Y 10Y-2Y cap, and
  that is the honest model error bar.

Why the option formula is Bachelier and not something cleverer
--------------------------------------------------------------
Under the annuity measure of the *payment* leg each CMS rate is (to the linear
swap-rate approximation) a martingale, and a difference of two jointly-normal
rates is normal. So a normal model on the spread is not an approximation bolted
on for convenience - it is the natural model, which is why the spread vol is the
exact quadratic form

    sigma_S^2 = sigma_l^2 + sigma_s^2 - 2 rho sigma_l sigma_s .

That closed form is also what makes :func:`implied_correlation` exact rather than
a root search: invert the price for ``sigma_S`` with the repo's own Bachelier
inverter and then solve the quadratic for ``rho``.

What QuantLib can and cannot do here
------------------------------------
QuantLib 1.41 has no CMS-spread *option* instrument. What it has is
**coupon-based**: ``SwapSpreadIndex``, ``CmsSpreadCoupon``,
``CappedFlooredCmsSpreadCoupon`` and ``LognormalCmsSpreadPricer``, i.e. the
machinery for a cap/floor **strip**. :func:`build_ql_cms_spread` builds exactly
that and labels it as such; it never presents a strip as a single look. Its
one-period mode is the closest QuantLib analogue available and is still not the
same instrument - see :attr:`QlCmsSpreadBuild.caveat`.

rateslib is not in this picture at all: rateslib 2.1.1 has no IR vol surface, no
swaption and no CMS coupon (its only vol classes are FX). Its role here is the
discount curve and the forward swap rate, nothing more - and note that
``rateslib`` quotes rates in PERCENT, which :func:`forward_swap_rate` divides out.

Units
-----
**Every rate, vol and strike in this module is in DECIMALS**: ``0.0425`` for
4.25%, ``0.01`` for a 100 bp normal vol, ``0.0020`` for a 20 bp strike. Three
neighbours use other units - the sibling
:class:`MDP.CitiVelocityExcel.vol.cube_data.SwaptionCubeData` stores vols in
basis points, Citi's ``PAR`` tags serve percent, rateslib returns percent - so
every pricer calls :func:`assert_decimal_rate`, which raises on any magnitude
above 1.0. Nothing real is above 1.0 in these units, and a 1e4 error otherwise
looks exactly like a price.
"""

from __future__ import annotations

import datetime
import logging
import math
import re
import warnings
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.catalog import TENOR_RE, CitiVeloCatalog, tenor_years
from MDP.CitiVelocityExcel.errors import CitiVelocityError, UnknownTagError
from MDP.CitiVelocityExcel.tags import spread_option
from Query.Base.bachelier import bachelier_price, implied_normal_vol

__all__ = [
    "SPREAD_OPTION_CURRENCIES",
    "SPREAD_OPTION_KINDS",
    "SPREAD_IS_LONG_MINUS_SHORT",
    "UNVERIFIED_TAG_NOTE",
    "QUANTLIB_SINGLE_LOOK_NOTE",
    "SpreadOptionQuote",
    "QlCmsSpreadBuild",
    "assert_decimal_rate",
    "split_concatenated_tenors",
    "parse_pair",
    "pair_token",
    "normalise_right",
    "fetch_spread_options",
    "hagan_g_ratio",
    "hagan_convexity_adjustment",
    "forward_swap_rate",
    "cms_rate",
    "spread_normal_vol",
    "correlation_from_spread_vol",
    "single_look_spread_option_price",
    "implied_correlation",
    "build_ql_cms_spread",
]

_logger = logging.getLogger(__name__)

#: The two currencies ``RATES.SPREAD_OPTIONS`` was harvested with. Both carry all
#: three kinds; nothing below ``PRICE``/``VOL`` was ever walked.
SPREAD_OPTION_CURRENCIES: Tuple[str, ...] = ("EUR", "USD")

#: ``OPT_CAP`` is a call on the spread, ``OPT_FLR`` a put, ``OPT_STR`` a straddle.
SPREAD_OPTION_KINDS: Tuple[str, ...] = ("OPT_CAP", "OPT_FLR", "OPT_STR")

#: How a pair token is read into a payoff. The documented tokens (``2Y5Y``,
#: ``5Y10Y``, ``10Y30Y``) list the SHORTER tenor first, and the market convention
#: for a "10s30s" CMS spread option is the steepener ``CMS(30Y) - CMS(10Y)``.
#: UNVERIFIED, like everything below the measure level: neither the token order
#: nor the payoff orientation has been confirmed against the add-in. Flip it by
#: passing ``sign=-1`` to :meth:`SpreadOptionQuote.spread`.
SPREAD_IS_LONG_MINUS_SHORT: bool = True

#: Repeated verbatim wherever this family is touched, because the failure it
#: guards against is silent: a well-formed tag that the add-in simply does not
#: serve looks identical to a tag with no data today.
UNVERIFIED_TAG_NOTE: str = (
    "RATES.SPREAD_OPTIONS was harvested only to the <ccy>.<kind>.{PRICE,VOL} level. "
    "The expiry and pair levels - and the units of the served values - are the desk's "
    "documented shape and are UNVERIFIED. Validate with "
    "client.validate_with_controls([...]) before building on a fetch."
)

#: Stated on the QuantLib route so a strip can never be mistaken for a single look.
QUANTLIB_SINGLE_LOOK_NOTE: str = (
    "QuantLib 1.41 has no CMS-spread option instrument. Its CMS-spread machinery "
    "(SwapSpreadIndex / CmsSpreadCoupon / CappedFlooredCmsSpreadCoupon / "
    "LognormalCmsSpreadPricer) prices a cap/floor STRIP of coupons. A one-period leg "
    "is the closest analogue to a single look but still differs in two ways: (1) it "
    "pays accrual x DF(payment date), not a caller-supplied annuity; (2) its fixing is "
    "convexity- and timing-adjusted to the coupon's own payment date. Use "
    "single_look_spread_option_price for the single look."
)

#: Maps every spelling a caller might reach for onto ``C`` / ``P`` / ``STRADDLE``.
_RIGHT_ALIASES: Dict[str, str] = {
    "C": "C", "CALL": "C", "CAP": "C", "CAPLET": "C", "OPT_CAP": "C",
    "PAY": "C", "PAYER": "C", "OPT_PAY": "C",
    "P": "P", "PUT": "P", "FLOOR": "P", "FLR": "P", "FLOORLET": "P", "OPT_FLR": "P",
    "REC": "P", "RECEIVER": "P", "OPT_REC": "P",
    "STR": "STRADDLE", "STRADDLE": "STRADDLE", "OPT_STR": "STRADDLE",
}

#: Day counts the calendar-free discount-factor fallback in
#: :func:`forward_swap_rate` understands. Measured on a sloped curve, using
#: ACT/360 where the quote source is really 30/360 moves a 10Y forward swap rate
#: by ~5 bp - the ACT/360 accrual is ~1.1% larger, the annuity with it, and the
#: rate down by the same 1.1%. That is far bigger than any calendar effect, which
#: is why this is a knob and not an assumption.
_DAYCOUNT_CONVENTIONS: Tuple[str, ...] = ("ACT360", "ACT365F", "ACT365", "30360", "THIRTY360")
_DAYCOUNT_BASE: Dict[str, float] = {"ACT360": 360.0, "ACT365F": 365.0, "ACT365": 365.0}

#: An explicitly separated pair, e.g. ``10Y-30Y``, ``10Y/30Y``, ``10Yx30Y``,
#: ``10Y_30Y``, ``10Y 30Y``, ``10Yv30Y``, ``10Yvs30Y``. Always unambiguous, so it
#: short-circuits the split enumeration in :func:`split_concatenated_tenors`.
_SEPARATED_PAIR_RE = re.compile(
    r"^\s*(\d+[DWMY])\s*(?:[-/_ ]+|X|VS?)\s*(\d+[DWMY])\s*$", re.IGNORECASE
)


# ------------------------------------------------------------------ #
#                        the tenor-pair grammar                      #
# ------------------------------------------------------------------ #


def split_concatenated_tenors(token: str, *, what: str = "pair") -> Tuple[str, str]:
    r"""Split a concatenated tenor pair such as ``10Y30Y`` into its two tenors.

    The naive splits are all wrong somewhere. Splitting in the middle turns
    ``1Y10Y`` into ``('1Y1', '0Y')``; splitting on the *last* unit letter turns it
    into ``('1Y10', 'Y')``; a regex anchored on ``Y`` alone cannot see ``18M2Y``.

    The rule implemented here is: **enumerate every position at which both halves
    are members of the tenor vocabulary** ``^\d+[DWMY]$``, and accept only when
    exactly one such position exists. That is decidable rather than heuristic, and
    it turns "is this ambiguous?" from an assumption into a check. It also happens
    to prove the family is never ambiguous - a valid first half must be digits
    followed by exactly one unit letter, so the split can only fall at the first
    unit letter - but the enumeration is kept because that proof depends on the
    vocabulary, and a vocabulary that later admits a token like ``18`` or ``1Y6M``
    would break it silently.

    Explicit separators (``10Y-30Y``, ``10Y/30Y``, ``10Yx30Y``, ``10Y_30Y``,
    ``10Y 30Y``) are honoured first and are never ambiguous.

    Parameters
    ----------
    token
        The concatenated token, e.g. ``'10Y30Y'`` or ``'1Y1Y'``.
    what
        Noun used in error messages (``'pair'`` for CMS spreads, ``'underlying'``
        for midcurves).

    Returns
    -------
    tuple[str, str]
        The two tenor tokens **in the order they appear**. No reordering is done
        here; see :func:`parse_pair` for what the order means.

    Raises
    ------
    ValueError
        When the token contains no valid split, or more than one. Both messages
        name the candidate splits, because the caller's fix differs: no split
        means the token is not a tenor pair, several means the vocabulary needs
        an explicit separator.

    Examples
    --------
    >>> split_concatenated_tenors("10Y30Y")
    ('10Y', '30Y')
    >>> split_concatenated_tenors("1Y10Y")
    ('1Y', '10Y')
    >>> split_concatenated_tenors("18M2Y")
    ('18M', '2Y')
    """
    text = str(token).strip().upper()
    if not text:
        raise ValueError(f"Empty {what} token.")

    separated = _SEPARATED_PAIR_RE.match(text)
    if separated:
        return separated.group(1), separated.group(2)

    candidates = [
        (text[:i], text[i:])
        for i in range(1, len(text))
        if TENOR_RE.match(text[:i]) and TENOR_RE.match(text[i:])
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError(
            f"{token!r} is not a concatenated tenor {what}: no split of it yields two tenors "
            f"matching {TENOR_RE.pattern}. Expected something like '10Y30Y', '18M2Y' or '10Y-30Y'."
        )
    shown = ", ".join(f"({a!r}, {b!r})" for a, b in candidates)
    raise ValueError(
        f"{token!r} is an ambiguous tenor {what}: {len(candidates)} valid splits exist - {shown}. "
        "Pass it with an explicit separator, e.g. '10Y-30Y'."
    )


def parse_pair(token: str) -> Tuple[str, str]:
    r"""``'10Y30Y'`` -> ``('10Y', '30Y')``, in token order.

    The returned order is **positional**, not economic: it is the order the
    segments appear in the tag. Which leg is the long one is decided by maturity
    in :meth:`SpreadOptionQuote.from_pair`, so a token written the other way round
    (``'30Y10Y'``) still classifies correctly.

    See :func:`split_concatenated_tenors` for the splitting rule, and
    :data:`SPREAD_IS_LONG_MINUS_SHORT` for the payoff orientation this package
    assumes.

    Raises
    ------
    ValueError
        When the token does not parse, or parses more than one way.
    """
    return split_concatenated_tenors(token, what="pair")


def pair_token(tenor_a: str, tenor_b: str) -> str:
    """The inverse of :func:`parse_pair`, with both tenors validated.

    Raises
    ------
    ValueError
        When either token is not a Velocity tenor, or when the concatenation
        would not round-trip through :func:`parse_pair` (which would make the tag
        unreadable even though it is well formed).
    """
    a = str(tenor_a).strip().upper()
    b = str(tenor_b).strip().upper()
    for token in (a, b):
        if not TENOR_RE.match(token):
            raise ValueError(f"{token!r} is not a Velocity tenor ({TENOR_RE.pattern}).")
    joined = f"{a}{b}"
    if parse_pair(joined) != (a, b):
        raise ValueError(
            f"{a!r} + {b!r} concatenate to {joined!r}, which does not round-trip through "
            "parse_pair. Use an explicit separator."
        )
    return joined


def assert_decimal_rate(value: float, name: str) -> float:
    """Guard a rate/vol that must be in decimals, not basis points.

    Every rate and vol in this sub-package is in DECIMALS: ``0.0425`` for 4.25%,
    ``0.01`` for a 100 bp normal vol. The sibling
    :class:`MDP.CitiVelocityExcel.vol.cube_data.SwaptionCubeData` stores vols in
    **basis points**, and Citi's ``PAR`` tags serve **percent**, so a 1e4 or 100x
    slip is the single most likely error a caller can make here - and it does not
    announce itself, it just returns a price that is wrong by four orders of
    magnitude while looking like a number.

    Nothing real is above 1.0 in these units: a 100% swap rate or a 10,000 bp
    normal vol does not exist. So a magnitude above 1.0 is taken as proof of a
    unit error and raised on.

    Raises
    ------
    ValueError
        Naming the field and the two conversions that fix it.
    """
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"{name} is {value!r}; a non-finite rate cannot be priced.")
    if abs(v) > 1.0:
        raise ValueError(
            f"{name}={value!r} is above 1.0, which is not a decimal rate or vol - 100% is not a "
            "real swap rate and 10,000 bp is not a real normal vol. This sub-package works in "
            f"DECIMALS throughout. If {name} came from a vol cube it is probably in basis points "
            "(divide by 1e4); if it came from a Citi PAR tag it is probably in percent (divide "
            "by 100)."
        )
    return v


def normalise_right(right: str) -> str:
    """Map any option spelling onto ``'C'``, ``'P'`` or ``'STRADDLE'``.

    Accepts the Velocity kinds (``OPT_CAP``/``OPT_FLR``/``OPT_STR``,
    ``OPT_PAY``/``OPT_REC``) as well as ``call``/``put``/``cap``/``floor``/
    ``payer``/``receiver``/``straddle``.

    Raises
    ------
    ValueError
        Naming the accepted set. There is no default: guessing between a cap and
        a floor is a sign error in the price.
    """
    token = str(right).strip().upper()
    if token in _RIGHT_ALIASES:
        return _RIGHT_ALIASES[token]
    raise ValueError(
        f"Unsupported option right {right!r}. Accepted: {', '.join(sorted(set(_RIGHT_ALIASES)))}."
    )


# ------------------------------------------------------------------ #
#                        the quote record + fetch                    #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class SpreadOptionQuote:
    """One ``(expiry, pair)`` single-look CMS spread option quote, as served.

    ``price`` and ``vol`` are the RAW values the add-in returned, in whatever
    units it returns them. They are deliberately not converted: the units of this
    family are unverified (see :data:`UNVERIFIED_TAG_NOTE`), and a silent
    x100 or x1e4 is exactly the kind of plausible-looking wrong number this
    package refuses to emit. For the sibling ``RATES.VOL`` family the ``NORMAL``
    branch is quoted in basis points and ``PAR`` rates are in percent, so those
    are the two conventions to check first - but check, do not assume.

    ``tenor_long``/``tenor_short`` are assigned by maturity, not by position in
    the token, so ``10Y30Y`` and ``30Y10Y`` classify identically.
    """

    currency: str
    kind: str
    expiry: str
    pair: str
    tenor_long: str
    tenor_short: str
    price: Optional[float]
    vol: Optional[float]
    as_of: Optional[pd.Timestamp]
    price_tag: str = ""
    vol_tag: str = ""

    @classmethod
    def from_pair(
        cls,
        *,
        currency: str,
        kind: str,
        expiry: str,
        pair: str,
        price: Optional[float] = None,
        vol: Optional[float] = None,
        as_of: Optional[pd.Timestamp] = None,
        price_tag: str = "",
        vol_tag: str = "",
    ) -> "SpreadOptionQuote":
        """Build a quote, deriving the long/short legs from the pair token."""
        first, second = parse_pair(pair)
        if tenor_years(second) >= tenor_years(first):
            short_leg, long_leg = first, second
        else:
            short_leg, long_leg = second, first
        return cls(
            currency=str(currency).strip().upper(),
            kind=str(kind).strip().upper(),
            expiry=str(expiry).strip().upper(),
            pair=str(pair).strip().upper(),
            tenor_long=long_leg,
            tenor_short=short_leg,
            price=price,
            vol=vol,
            as_of=as_of,
            price_tag=price_tag,
            vol_tag=vol_tag,
        )

    @property
    def right(self) -> str:
        """``'C'``, ``'P'`` or ``'STRADDLE'`` for this quote's ``kind``."""
        return normalise_right(self.kind)

    @property
    def expiry_years(self) -> float:
        """Approximate year fraction of the expiry token, for pricing."""
        return tenor_years(self.expiry)

    def spread(self, cms_long: float, cms_short: float, *, sign: int = 1) -> float:
        """The spread this quote is on, given the two CMS rates.

        ``sign=-1`` flips the orientation if the desk turns out to quote
        short-minus-long; see :data:`SPREAD_IS_LONG_MINUS_SHORT`.
        """
        oriented = 1.0 if SPREAD_IS_LONG_MINUS_SHORT else -1.0
        return float(sign) * oriented * (float(cms_long) - float(cms_short))


def _series_reader(
    client: Any,
    cache: Any,
) -> Callable[[Sequence[str], str, Any, Any], Mapping[str, pd.Series]]:
    """Adapt whatever the caller passed as ``client`` to one series-fetching call.

    Accepts a :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes` (duck-typed on
    ``.series``), a raw
    :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient` (duck-typed
    on ``.fetch_timeseries``), or ``client=None`` with a cache for an offline
    read. Duck-typing rather than ``isinstance`` keeps the fake COM client in
    :mod:`MDP.CitiVelocityExcel.testing` usable here without a shim.
    """
    if client is not None and hasattr(client, "series"):
        def read_quotes(tags, freq, start, end):
            return client.series(list(tags), freq, start=start, end=end)

        return read_quotes

    if client is not None and hasattr(client, "fetch_timeseries"):
        if cache is not None:
            def read_cached(tags, freq, start, end):
                def fetch(chunk, f, s, e, point):
                    return client.fetch_timeseries(list(chunk), f, start=s, end=e, price_point=point)

                return cache.get(list(tags), freq, start=start, end=end, fetcher=fetch)

            return read_cached

        def read_live(tags, freq, start, end):
            return client.fetch_timeseries(list(tags), freq, start=start, end=end)

        return read_live

    if client is None and cache is not None:
        def read_offline(tags, freq, start, end):
            return cache.get(list(tags), freq, start=start, end=end, fetcher=None)

        return read_offline

    raise TypeError(
        "fetch_spread_options needs a client with .series (CitiVeloQuotes) or "
        ".fetch_timeseries (CitiVelocityExcelClient), or client=None together with a "
        "CitiVeloTagCache for an offline read."
    )


def _asof(series: Optional[pd.Series], when: Optional[pd.Timestamp]) -> Tuple[Optional[float], Optional[pd.Timestamp]]:
    """Backward-looking snapshot of one series, or ``(None, None)``."""
    if series is None or len(series) == 0:
        return None, None
    s = series.dropna()
    if s.empty:
        return None, None
    if when is not None:
        s = s[s.index <= when]
        if s.empty:
            return None, None
    return float(s.iloc[-1]), pd.Timestamp(s.index[-1])


def fetch_spread_options(
    *,
    client: Any,
    currency: str,
    expiries: Sequence[str],
    pairs: Sequence[str],
    kind: str = "OPT_CAP",
    as_of: Any = None,
    cache: Any = None,
    freq: str = "DAILY",
    lookback: Optional[datetime.timedelta] = None,
    catalog: Optional[CitiVeloCatalog] = None,
    warn: bool = True,
) -> List[SpreadOptionQuote]:
    """Fetch ``PRICE`` and ``VOL`` for an ``expiries x pairs`` block, as of one date.

    Both values for every combination go out in ONE batched request, so a 4x5
    block is one ``CVTSHIST`` call and not forty.

    Parameters
    ----------
    client
        A :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes`, a raw
        :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient`, or
        ``None`` for a cache-only read.
    currency
        ``USD`` or ``EUR``; validated against the harvested catalog.
    expiries, pairs
        Option expiry tokens (``'1Y'``) and concatenated tenor pairs
        (``'10Y30Y'``). Pairs are validated through :func:`parse_pair` before any
        request goes out.
    kind
        ``OPT_CAP`` (call on the spread), ``OPT_FLR`` (put) or ``OPT_STR``
        (straddle).
    as_of
        Snapshot date. ``None`` takes the latest row each tag has. Resolution is
        backward-only (as-of), never nearest: a nearest-match snapshot on this
        repo's sibling intraday source was measured answering with data up to 55
        minutes in the future.
    cache
        A :class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache`. Used only when
        ``client`` is a raw client - ``CitiVeloQuotes`` owns its own cache.
    freq, lookback
        Fetch granularity and how far back to pull. ``lookback`` defaults to 30
        days of daily data, enough to survive a holiday run without pulling full
        history on a cold cache.

    Returns
    -------
    list[SpreadOptionQuote]
        One entry per ``(expiry, pair)`` for which at least one of ``PRICE`` and
        ``VOL`` resolved. Combinations that served nothing are omitted and
        counted in a log warning.

    Raises
    ------
    CitiVelocityError
        When NOTHING resolved. That is the expected failure if the documented
        expiry/pair shape is wrong, and it must be loud: an empty list would read
        as "the market was quiet", which is a different and much rarer thing.

    Notes
    -----
    The expiry and pair levels of this tag family are unverified - see
    :data:`UNVERIFIED_TAG_NOTE`.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    ccy = str(currency).strip().upper()
    kind_token = str(kind).strip().upper()
    if kind_token not in SPREAD_OPTION_KINDS:
        raise UnknownTagError(
            f"Unknown SPREAD_OPTIONS kind {kind!r}. Accepted: {', '.join(SPREAD_OPTION_KINDS)}."
        )
    expiry_list = [str(e).strip().upper() for e in expiries if str(e).strip()]
    pair_list = [str(p).strip().upper() for p in pairs if str(p).strip()]
    if not expiry_list or not pair_list:
        raise ValueError("fetch_spread_options needs at least one expiry and one pair.")
    for token in pair_list:
        parse_pair(token)  # fail before touching Excel, not after

    if warn:
        warnings.warn(UNVERIFIED_TAG_NOTE, stacklevel=2)

    tags: Dict[Tuple[str, str, str], str] = {}
    for expiry in expiry_list:
        for pair in pair_list:
            for value in ("PRICE", "VOL"):
                tags[(expiry, pair, value)] = spread_option(
                    ccy, expiry, pair, kind=kind_token, value=value, catalog=cat, warn=False
                )

    when = None if as_of is None else pd.Timestamp(as_of)
    if lookback is None:
        lookback = datetime.timedelta(days=5 if str(freq).upper() in {"MI01", "MI10", "HOURLY"} else 30)
    end = when
    start = None if when is None else when - lookback

    reader = _series_reader(client, cache)
    served = dict(reader(list(dict.fromkeys(tags.values())), freq, start, end) or {})

    out: List[SpreadOptionQuote] = []
    missing = 0
    for expiry in expiry_list:
        for pair in pair_list:
            price_tag = tags[(expiry, pair, "PRICE")]
            vol_tag = tags[(expiry, pair, "VOL")]
            price, price_at = _asof(served.get(price_tag), when)
            vol, vol_at = _asof(served.get(vol_tag), when)
            if price is None and vol is None:
                missing += 1
                continue
            stamps = [t for t in (price_at, vol_at) if t is not None]
            out.append(
                SpreadOptionQuote.from_pair(
                    currency=ccy,
                    kind=kind_token,
                    expiry=expiry,
                    pair=pair,
                    price=price,
                    vol=vol,
                    as_of=(max(stamps) if stamps else None),
                    price_tag=price_tag,
                    vol_tag=vol_tag,
                )
            )

    if not out:
        raise CitiVelocityError(
            f"RATES.SPREAD_OPTIONS.{ccy}.{kind_token} served nothing for "
            f"{len(expiry_list)} expiry(s) x {len(pair_list)} pair(s). {UNVERIFIED_TAG_NOTE} "
            f"First tag tried: {tags[(expiry_list[0], pair_list[0], 'VOL')]}"
        )
    if missing:
        _logger.warning(
            "fetch_spread_options: %d of %d (expiry, pair) combinations served neither PRICE nor "
            "VOL for RATES.SPREAD_OPTIONS.%s.%s. The expiry/pair levels of this family are "
            "unverified.",
            missing,
            len(expiry_list) * len(pair_list),
            ccy,
            kind_token,
        )
    return out


# ------------------------------------------------------------------ #
#                          CMS convexity                             #
# ------------------------------------------------------------------ #


def hagan_g_ratio(
    *,
    forward: float,
    tenor_years_: float,
    fixed_frequency: int = 2,
    payment_delay_years: float = 0.0,
) -> float:
    r"""``G'(S0)/G(S0)`` for Hagan's standard (bond-math) CMS model.

    The convexity adjustment for a swap rate paid outside its own annuity measure
    is, under the linear swap-rate model,

    .. math::
        E^{T_p}[S_T] - S_0 = \frac{G'(S_0)}{G(S_0)} \, \mathrm{Var}^A(S_T)

    where :math:`G(S) = P(T_p)/A` is the ratio of the payment-date discount bond
    to the annuity, both written as functions of the swap rate alone. Hagan's
    *standard* model uses flat-yield bond math for both::

        A(S)      = (1 - (1 + S/q)^-N) / S           N = q * n, q payments per year
        P(T_p)/P(T_s) = (1 + S/q)^(-delta * q)       delta = payment delay in years

    so that

    .. math::
        \frac{G'}{G} = \frac{1}{S} - \frac{\delta}{1 + S/q}
                       - \frac{(N/q)\,(1+S/q)^{-N-1}}{1 - (1+S/q)^{-N}}

    which is what this returns.

    Assumptions, and what they cost
    -------------------------------
    * **Flat yield curve at the forward swap rate.** The annuity and the payment
      bond are both discounted at ``S0``. Measured against QuantLib's
      ``LinearTsrPricer`` on a 10Y CMS with a 100 bp normal vol, 1Y to 10Y
      expiry: **0.001-0.006 bp on a flat 4% curve** (the control - there the
      assumption is true, so this is algebra only) and **0.04-0.20 bp on a
      3.0%-to-4.7% sloped curve**, the closed form running LOW. That 0.20 bp at
      10Y expiry is the flat-yield approximation's real cost.
    * **First-order (linear) TSR.** ``P(T_p)/A`` is linearised around ``S0``. The
      difference against ``GFunctionFactory.ParallelShifts``, which is a
      different linearisation of the same idea, was **0.18 bp at 1Y, 0.89 bp at
      5Y and 1.96 bp at 10Y** expiry on the sloped curve - four to ten times the
      curve-shape error. Model choice, not curve shape, is what limits any
      linear-TSR adjustment, and it grows with expiry. Treat a 5Y+ CMS
      adjustment as good to about 1 bp and a 10Y one to about 2 bp.
    * **No smile.** The variance is taken from a single vol. A replication-based
      adjustment integrating the full smile will differ by more than either
      number above whenever the smile is not flat; that is a genuinely different
      model, not a refinement of this one.

    Parameters
    ----------
    forward
        The forward par swap rate, in DECIMALS (``0.0425``), not percent.
    tenor_years_
        Swap tenor in years. Trailing underscore because ``tenor_years`` is the
        catalog's tenor-parsing function, imported here.
    fixed_frequency
        Fixed-leg payments per year: 1 annual, 2 semi-annual, 4 quarterly.
    payment_delay_years
        ``T_p - T_s``: how long after the underlying swap's start date the CMS
        payment lands. ``0.0`` means paid at the swap start.

    Raises
    ------
    ValueError
        For a non-positive forward or tenor. A CMS convexity adjustment at a
        zero or negative forward is not defined in this parameterisation
        (``1/S`` diverges); use a shifted or normal-model replication instead.
    """
    s = float(forward)
    n = float(tenor_years_)
    q = float(int(fixed_frequency))
    if q <= 0:
        raise ValueError(f"fixed_frequency must be a positive integer, got {fixed_frequency!r}.")
    if n <= 0:
        raise ValueError(f"Swap tenor must be positive, got {tenor_years_!r} years.")
    if s <= 0.0:
        raise ValueError(
            f"Hagan's standard CMS model is not defined at a non-positive forward "
            f"({s!r}); its G function carries a 1/S term. Pass an explicit "
            "convexity_adjustment=<float> instead, or use a normal-model replication."
        )
    big_n = n * q
    x = 1.0 + s / q
    u = x ** (-big_n)
    return 1.0 / s - float(payment_delay_years) / x - (big_n / q) * x ** (-big_n - 1.0) / (1.0 - u)


def hagan_convexity_adjustment(
    *,
    forward: float,
    normal_vol: float,
    expiry_years: float,
    tenor_years_: float,
    fixed_frequency: int = 2,
    payment_delay_years: float = 0.0,
) -> float:
    """The CMS convexity adjustment in DECIMALS, from a NORMAL vol.

    ``adjustment = (G'/G) * sigma_N^2 * T``. Add it to the forward par swap rate
    to get the CMS rate. See :func:`hagan_g_ratio` for the model, its assumptions
    and the measured error against QuantLib.

    Parameters
    ----------
    forward
        Forward par swap rate in decimals.
    normal_vol
        Normal (Bachelier) vol of that swap rate, in DECIMALS - ``0.01`` for
        100 bp, not ``100``. Citi's ``RATES.VOL...NORMAL`` branch quotes in basis
        points; divide by 1e4.
    expiry_years
        Time to the CMS fixing, in years.
    tenor_years_, fixed_frequency, payment_delay_years
        As in :func:`hagan_g_ratio`.

    Returns
    -------
    float
        The adjustment in decimals. Multiply by 1e4 for basis points.
    """
    if float(expiry_years) < 0.0:
        raise ValueError(f"expiry_years must be non-negative, got {expiry_years!r}.")
    if float(normal_vol) < 0.0:
        raise ValueError(f"normal_vol must be non-negative, got {normal_vol!r}.")
    assert_decimal_rate(forward, "forward")
    assert_decimal_rate(normal_vol, "normal_vol")
    ratio = hagan_g_ratio(
        forward=forward,
        tenor_years_=tenor_years_,
        fixed_frequency=fixed_frequency,
        payment_delay_years=payment_delay_years,
    )
    return ratio * float(normal_vol) ** 2 * float(expiry_years)


def _is_rateslib_curve(obj: Any) -> bool:
    return type(obj).__module__.split(".")[0] == "rateslib" and hasattr(obj, "nodes")


def _is_quantlib_curve(obj: Any) -> bool:
    return type(obj).__module__.split(".")[0] == "QuantLib" and (
        hasattr(obj, "discount") or hasattr(obj, "currentLink")
    )


def forward_swap_rate(
    *,
    curve: Any,
    forward: Any,
    tenor: str,
    spec: str = "usd_irs",
    fixed_frequency: int = 2,
    convention: str = "act360",
    currency: str = "USD",
    calendar: Any = None,
    settlement_days: int = 2,
    fixed_leg_tenor: str = "6M",
    ibor_tenor: str = "3M",
    valuation: Any = None,
) -> float:
    """The forward-starting par swap rate, in DECIMALS, from whatever curve you have.

    Four backends, in the order they are tried:

    ``float``
        Returned as-is. The escape hatch for "I already know the forward".
    rateslib ``Curve``
        Priced with ``rateslib.IRS(effective=..., termination=tenor, spec=spec)``.
        Exact schedules and calendars. **rateslib quotes rates in percent**; the
        result is divided by 100 here so this function's contract stays decimals.
    QuantLib term structure or handle
        Priced with a ``ql.SwapIndex`` over a generic ``ql.IborIndex`` built from
        ``currency``/``calendar``/``fixed_leg_tenor``. Verified to reproduce a
        ``ql.USDLibor``-based index to 1e-13 on a sloped zero curve.
    callable / mapping of discount factors
        ``df(date) -> float`` (or ``{date: df}``). The annuity is built from an
        unadjusted month-arithmetic schedule. This route has no holiday calendar,
        and measured against the QuantLib route on the same discount factors that
        costs **at most 0.29 bp** across 1Yx10Y, 1Yx2Y, 2Yx1Y, 5Yx5Y and 0Dx10Y -
        i.e. the missing calendar is not the thing to worry about. **The day
        count is**: running the same schedule at ACT/360 against a 30/360 quote
        source moved the rate by up to **6.9 bp**, 24x the calendar effect,
        because an ACT/360 accrual is ~1.1% larger and the rate falls with the
        annuity. Set ``convention`` to whatever your quotes really use.

    Parameters
    ----------
    forward
        Forward-start tenor token (``'1Y'``) or a number of years.
    tenor
        Swap tenor token (``'10Y'``).
    convention
        Fixed-leg day count for the discount-factor route only:
        ``act360``, ``act365f``/``act365`` or ``30360``/``thirty360``. Ignored by
        the rateslib route (which takes it from ``spec``) and the QuantLib route
        (30/360 bond basis).
    valuation
        Today, for the DF and QuantLib routes. Defaults to the curve's own
        reference date where one is available, else ``datetime.date.today()``.

    Raises
    ------
    TypeError
        Naming the four accepted curve forms.
    """
    if isinstance(curve, (int, float)) and not isinstance(curve, bool):
        return float(curve)

    fwd_years = float(forward) if isinstance(forward, (int, float)) else tenor_years(str(forward))
    tenor_token = str(tenor).strip().upper()
    if not TENOR_RE.match(tenor_token):
        raise ValueError(f"{tenor!r} is not a Velocity tenor ({TENOR_RE.pattern}).")

    if _is_rateslib_curve(curve):
        import rateslib as rl

        start = curve.nodes.initial if valuation is None else _as_datetime(valuation)
        # rateslib 2.1.1 keeps the calendar on Curve.meta, not on the Curve itself.
        cal = getattr(getattr(curve, "meta", None), "calendar", None)
        tenor_in = _years_to_tenor(fwd_years)
        effective = (
            rl.add_tenor(start, tenor_in, "MF", cal)
            if cal is not None
            else rl.add_tenor(start, tenor_in, "MF")
        )
        irs = rl.IRS(effective=effective, termination=tenor_token, spec=spec, curves=curve)
        return float(irs.rate()) / 100.0  # rateslib quotes rates in PERCENT

    if _is_quantlib_curve(curve):
        import QuantLib as ql

        handle = curve if hasattr(curve, "currentLink") else ql.YieldTermStructureHandle(curve)
        cal = calendar if calendar is not None else ql.TARGET()
        ccy = getattr(ql, f"{str(currency).strip().upper()}Currency")()
        ibor = ql.IborIndex(
            "CMS-IBOR", ql.Period(ibor_tenor), int(settlement_days), ccy, cal,
            ql.ModifiedFollowing, False, ql.Actual360(), handle,
        )
        index = ql.SwapIndex(
            "CMS-SWAP", ql.Period(tenor_token), int(settlement_days), ccy, cal,
            ql.Period(fixed_leg_tenor), ql.ModifiedFollowing,
            ql.Thirty360(ql.Thirty360.BondBasis), ibor,
        )
        ref = handle.referenceDate()
        fixing = cal.advance(ref, ql.Period(_years_to_tenor(fwd_years)))
        return float(index.fixing(fixing))

    if callable(curve) or isinstance(curve, Mapping):
        return _df_forward_swap_rate(
            curve,
            fwd_years=fwd_years,
            tenor_token=tenor_token,
            fixed_frequency=fixed_frequency,
            convention=convention,
            valuation=valuation,
        )

    raise TypeError(
        f"forward_swap_rate cannot read a curve of type {type(curve).__name__}. Accepted: a float "
        "(the forward itself), a rateslib Curve, a QuantLib YieldTermStructure or handle, or a "
        "callable/mapping of discount factors keyed by date."
    )


def _as_datetime(when: Any) -> datetime.datetime:
    if isinstance(when, datetime.datetime):
        return when
    if isinstance(when, datetime.date):
        return datetime.datetime(when.year, when.month, when.day)
    return pd.Timestamp(when).to_pydatetime()


def _years_to_tenor(years: float) -> str:
    """``1.0 -> '1Y'``, ``0.25 -> '3M'``. Months when the year count is not whole."""
    months = int(round(float(years) * 12.0))
    if months <= 0:
        return "0D"
    if months % 12 == 0:
        return f"{months // 12}Y"
    return f"{months}M"


def _add_months(when: datetime.date, months: int) -> datetime.date:
    """Calendar month arithmetic with end-of-month clamping (no business roll)."""
    total = when.month - 1 + int(months)
    year = when.year + total // 12
    month = total % 12 + 1
    day = min(when.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28,
                         31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return datetime.date(year, month, day)


def _year_fraction(start: datetime.date, end: datetime.date, convention: str) -> float:
    """Accrual fraction under one of :data:`_DAYCOUNT_CONVENTIONS`.

    30/360 uses the US (bond basis) day adjustment: a 31st is pulled back to the
    30th, and an end-of-month 31st only when the start is already a 30th or 31st.
    """
    if convention in {"30360", "THIRTY360"}:
        d1, d2 = start.day, end.day
        if d1 == 31:
            d1 = 30
        if d2 == 31 and d1 == 30:
            d2 = 30
        return (360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)) / 360.0
    return (end - start).days / _DAYCOUNT_BASE[convention]


def _df_forward_swap_rate(
    curve: Any,
    *,
    fwd_years: float,
    tenor_token: str,
    fixed_frequency: int,
    convention: str,
    valuation: Any,
) -> float:
    """Forward par swap rate from raw discount factors. Calendar-free; see caller."""
    token = str(convention).strip().upper().replace("/", "")
    if token not in _DAYCOUNT_CONVENTIONS:
        raise ValueError(
            f"Unsupported convention {convention!r} for the discount-factor route. "
            f"Accepted: {', '.join(_DAYCOUNT_CONVENTIONS)}."
        )
    df: Callable[[datetime.date], float]
    if isinstance(curve, Mapping):
        lookup = {pd.Timestamp(k).date(): float(v) for k, v in curve.items()}

        def df(d: datetime.date) -> float:
            try:
                return lookup[d]
            except KeyError as exc:
                raise KeyError(
                    f"No discount factor for {d.isoformat()} in the supplied mapping. Pass a "
                    "callable df(date) -> float if the schedule dates are not node dates."
                ) from exc
    else:
        df = curve  # type: ignore[assignment]

    today = datetime.date.today() if valuation is None else _as_datetime(valuation).date()
    start = _add_months(today, int(round(fwd_years * 12.0)))
    n_years = tenor_years(tenor_token)
    q = int(fixed_frequency)
    n_periods = int(round(n_years * q))
    if n_periods < 1:
        raise ValueError(f"Tenor {tenor_token!r} at frequency {q} yields no fixed-leg periods.")

    annuity = 0.0
    prev = start
    step = int(round(12 / q))
    for i in range(1, n_periods + 1):
        pay = _add_months(start, step * i)
        annuity += _year_fraction(prev, pay, token) * float(df(pay))
        prev = pay
    end = prev
    if annuity <= 0.0:
        raise ValueError(
            "The discount-factor route produced a non-positive annuity; the curve is not "
            "usable for a forward swap rate at this tenor."
        )
    return (float(df(start)) - float(df(end))) / annuity


def cms_rate(
    *,
    curve: Any,
    forward: Any,
    tenor: str,
    convexity_adjustment: Any = "hagan",
    normal_vol: Optional[float] = None,
    expiry_years: Optional[float] = None,
    fixed_frequency: int = 2,
    payment_delay_years: float = 0.0,
    **forward_kwargs: Any,
) -> float:
    """The convexity-adjusted forward CMS rate, in DECIMALS.

    ``cms_rate(curve=c, forward='1Y', tenor='10Y', normal_vol=0.01)`` is the 1Y
    forward 10Y CMS rate: the 1Y-forward 10Y par swap rate plus Hagan's standard
    convexity adjustment.

    Parameters
    ----------
    curve
        Anything :func:`forward_swap_rate` accepts, including a plain float
        forward.
    forward
        Forward-start tenor token or years. Doubles as the expiry for the
        convexity adjustment unless ``expiry_years`` overrides it.
    tenor
        Swap tenor token.
    convexity_adjustment
        ``'hagan'`` (default) computes :func:`hagan_convexity_adjustment` and
        REQUIRES ``normal_vol``. A ``float`` is added directly, in decimals -
        pass ``0.0`` to get the unadjusted par forward. A callable is invoked as
        ``f(forward_par_rate)`` and its result added.
    normal_vol
        Normal vol in decimals. Required by the ``'hagan'`` route.
    payment_delay_years
        ``T_p - T_s`` for the CMS payment. ``0.0`` (paid at the swap start) is the
        right choice for a single-look spread option settled at expiry.
    **forward_kwargs
        Passed through to :func:`forward_swap_rate` (``spec``, ``calendar``,
        ``valuation``, ...).

    Raises
    ------
    ValueError
        When ``convexity_adjustment='hagan'`` and no ``normal_vol`` is given. It
        raises rather than falling back to zero, because an unadjusted rate
        returned from a function called ``cms_rate`` is a wrong number wearing a
        right name - the adjustment is 3.8 bp at 1Y and 19 bp at 5Y on a 10Y CMS
        with a 100 bp vol.
    """
    par = forward_swap_rate(curve=curve, forward=forward, tenor=tenor, **forward_kwargs)

    if convexity_adjustment is None:
        adjustment = 0.0
    elif isinstance(convexity_adjustment, str):
        token = convexity_adjustment.strip().lower()
        if token not in {"hagan", "standard"}:
            raise ValueError(
                f"Unknown convexity_adjustment {convexity_adjustment!r}. Use 'hagan', a float in "
                "decimals, a callable f(par_rate) -> float, or 0.0 for no adjustment."
            )
        if normal_vol is None:
            raise ValueError(
                "cms_rate(convexity_adjustment='hagan') needs normal_vol (in decimals: 0.01 for "
                "100 bp). Pass it, or pass convexity_adjustment=0.0 to ask explicitly for the "
                "unadjusted forward par rate. On a 10Y CMS with a 100 bp vol the adjustment is "
                "3.8 bp at 1Y and 19 bp at 5Y, so defaulting it to zero would be a silent error."
            )
        expiry = (
            float(expiry_years)
            if expiry_years is not None
            else (float(forward) if isinstance(forward, (int, float)) else tenor_years(str(forward)))
        )
        adjustment = hagan_convexity_adjustment(
            forward=par,
            normal_vol=float(normal_vol),
            expiry_years=expiry,
            tenor_years_=tenor_years(str(tenor)),
            fixed_frequency=fixed_frequency,
            payment_delay_years=payment_delay_years,
        )
    elif callable(convexity_adjustment):
        adjustment = float(convexity_adjustment(par))
    else:
        adjustment = float(convexity_adjustment)

    return par + adjustment


# ------------------------------------------------------------------ #
#                           the single look                          #
# ------------------------------------------------------------------ #


def spread_normal_vol(*, vol_long: float, vol_short: float, correlation: float) -> float:
    r"""``sqrt(sigma_l^2 + sigma_s^2 - 2 rho sigma_l sigma_s)``.

    The normal vol of a difference of two jointly-normal rates. Both inputs must
    be in the same units; the output is in those units.

    Raises
    ------
    ValueError
        For a correlation outside ``[-1, 1]`` or a negative vol. The quadratic
        form stays non-negative on that domain, so a negative variance here can
        only mean bad inputs, and returning ``nan`` would hide them.
    """
    sl = float(vol_long)
    ss = float(vol_short)
    rho = float(correlation)
    if sl < 0.0 or ss < 0.0:
        raise ValueError(f"Vols must be non-negative, got vol_long={sl!r}, vol_short={ss!r}.")
    if not -1.0 <= rho <= 1.0:
        raise ValueError(f"correlation must lie in [-1, 1], got {rho!r}.")
    variance = sl * sl + ss * ss - 2.0 * rho * sl * ss
    return math.sqrt(max(variance, 0.0))


def correlation_from_spread_vol(*, spread_vol: float, vol_long: float, vol_short: float) -> float:
    """Invert :func:`spread_normal_vol` for ``rho``.

    Raises
    ------
    ValueError
        When either leg vol is zero (``rho`` is then unidentified: the spread vol
        does not depend on it), or when ``spread_vol`` lies outside the
        achievable band ``[|sigma_l - sigma_s|, sigma_l + sigma_s]``. The message
        quotes the band.
    """
    sl = float(vol_long)
    ss = float(vol_short)
    sv = float(spread_vol)
    if sl <= 0.0 or ss <= 0.0:
        raise ValueError(
            f"Correlation is unidentified when a leg vol is zero (vol_long={sl!r}, "
            f"vol_short={ss!r}): the spread vol does not depend on rho."
        )
    lo, hi = abs(sl - ss), sl + ss
    if not lo - 1e-12 <= sv <= hi + 1e-12:
        raise ValueError(
            f"A spread vol of {sv!r} is not attainable from leg vols {sl!r} and {ss!r}: rho in "
            f"[-1, 1] spans spread vols [{lo!r}, {hi!r}]. Either a leg vol is wrong or the "
            "quoted price is not consistent with a two-factor normal model."
        )
    rho = (sl * sl + ss * ss - sv * sv) / (2.0 * sl * ss)
    return min(1.0, max(-1.0, rho))


def single_look_spread_option_price(
    *,
    forward_long: float,
    forward_short: float,
    vol_long: float,
    vol_short: float,
    correlation: float,
    strike: float,
    expiry_years: float,
    annuity: float = 1.0,
    right: str = "OPT_CAP",
    discount: float = 1.0,
) -> float:
    r"""Bachelier price of ONE European option on ``CMS_long - CMS_short``.

    .. math::
        V = A \cdot D \cdot \mathrm{Bachelier}(\eta;\, S_0, K, \sigma_S, T),
        \qquad \sigma_S^2 = \sigma_l^2 + \sigma_s^2 - 2\rho\sigma_l\sigma_s

    with :math:`S_0 = F_l - F_s`. The option formula itself is
    :func:`Query.Base.bachelier.bachelier_price` (QuantLib's
    ``bachelierBlackFormula``) rather than a re-derivation.

    This is a **single look**, not a strip: one payoff, at one expiry, on one
    fixing of the spread. Measured against ``ql.LognormalCmsSpreadPricer``'s
    caplet rate on a 1Y expiry 10Y-2Y spread with 100 bp leg vols, ``rho`` from
    -0.5 to +0.99: agreement to 9e-15 bp with a NORMAL swaption surface (a wiring
    check - the pricer's integral collapses to this formula when the marginals
    and the copula are both normal) and a ~0.5 bp gap against a LOGNORMAL surface
    with ATM-matched vols, which is the genuine model difference.

    Parameters
    ----------
    forward_long, forward_short
        The two forward CMS rates in DECIMALS. Convexity-adjust them first with
        :func:`cms_rate` - the adjustment does not cancel in the spread, because
        the two legs have different ``G'/G``.
    vol_long, vol_short
        Normal vols of the two CMS rates in DECIMALS (``0.01`` = 100 bp). These
        are vols of the CMS rates, which for a short expiry are close to but not
        equal to the corresponding swaption vols.
    correlation
        Correlation between the two rates.
    strike
        Strike on the SPREAD, in decimals. A 20 bp strike is ``0.0020``.
    expiry_years
        Time to expiry in years.
    annuity
        Multiplier on the payoff: notional x accrual for a cash-settled look, or
        the cash annuity for an annuity-settled one. ``1.0`` gives the value per
        unit of payoff.
    right
        ``OPT_CAP``/call, ``OPT_FLR``/put, ``OPT_STR``/straddle. Straddles are
        priced as call + put (put-call parity holds exactly in Bachelier).
    discount
        Discount factor from today to the payment date.

    Returns
    -------
    float
        ``annuity * discount * E[payoff]``.

    Raises
    ------
    ValueError
        For a negative expiry, a bad ``right`` or a correlation outside
        ``[-1, 1]``.
    """
    if float(expiry_years) < 0.0:
        raise ValueError(f"expiry_years must be non-negative, got {expiry_years!r}.")
    side = normalise_right(right)
    for value, name in (
        (forward_long, "forward_long"), (forward_short, "forward_short"),
        (vol_long, "vol_long"), (vol_short, "vol_short"), (strike, "strike"),
    ):
        assert_decimal_rate(value, name)
    sigma = spread_normal_vol(vol_long=vol_long, vol_short=vol_short, correlation=correlation)
    fwd = float(forward_long) - float(forward_short)
    scale = float(annuity)

    if side == "STRADDLE":
        call = bachelier_price("C", float(strike), fwd, sigma, float(expiry_years), float(discount))
        put = bachelier_price("P", float(strike), fwd, sigma, float(expiry_years), float(discount))
        return scale * (call + put)
    return scale * bachelier_price(
        side, float(strike), fwd, sigma, float(expiry_years), float(discount)
    )


def implied_correlation(
    *,
    market_price: float,
    forward_long: float,
    forward_short: float,
    vol_long: float,
    vol_short: float,
    strike: float,
    expiry_years: float,
    annuity: float = 1.0,
    right: str = "OPT_CAP",
    discount: float = 1.0,
) -> float:
    """The ``rho`` that reprices ``market_price``. Exact, not a root search.

    Two closed-form steps rather than a solver:

    1. strip the ``annuity * discount`` scaling, convert a straddle to a call
       through put-call parity (``C = (straddle + (F - K)) / 2`` on the
       undiscounted forward value), and invert the Bachelier formula for
       ``sigma_S`` with :func:`Query.Base.bachelier.implied_normal_vol`;
    2. solve ``sigma_S^2 = sigma_l^2 + sigma_s^2 - 2 rho sigma_l sigma_s`` for
       ``rho`` with :func:`correlation_from_spread_vol`.

    Both steps are exact inverses of :func:`single_look_spread_option_price`, so
    the round trip is limited only by the vol inverter's own tolerance.

    Parameters
    ----------
    market_price
        The traded price, on the same scale as
        :func:`single_look_spread_option_price` returns (i.e. including
        ``annuity`` and ``discount``).

    Other parameters as in :func:`single_look_spread_option_price`.

    Raises
    ------
    ValueError
        When the price is non-positive, when the Bachelier inversion fails, or
        when the implied spread vol lies outside the band any ``rho`` in
        ``[-1, 1]`` can produce. Each message says which of the three it was; it
        never returns ``nan``, because a ``nan`` correlation propagates into a
        risk report as a blank rather than as an error.
    """
    scale = float(annuity) * float(discount)
    if scale == 0.0:
        raise ValueError("implied_correlation: annuity * discount is zero, so no price is invertible.")
    side = normalise_right(right)
    fwd = float(forward_long) - float(forward_short)
    k = float(strike)
    value = float(market_price) / scale  # undiscounted expected payoff

    if value <= 0.0:
        raise ValueError(
            f"implied_correlation needs a positive option value; got {market_price!r} which is "
            f"{value!r} after dividing out annuity*discount={scale!r}."
        )
    if side == "STRADDLE":
        # C + P = value and C - P = F - K  =>  C = (value + F - K) / 2.
        value = 0.5 * (value + (fwd - k))
        side = "C"
        if value <= 0.0:
            raise ValueError(
                f"The straddle price {market_price!r} implies a non-positive call value "
                f"({value!r}); it is below the intrinsic value of its own put leg."
            )

    sigma = implied_normal_vol(side, k, fwd, float(expiry_years), value, 1.0)
    if not math.isfinite(sigma):
        intrinsic = max(fwd - k, 0.0) if side == "C" else max(k - fwd, 0.0)
        raise ValueError(
            f"Bachelier inversion failed for value={value!r} (forward={fwd!r}, strike={k!r}, "
            f"T={expiry_years!r}). Intrinsic is {intrinsic!r}; a price at or below intrinsic has "
            "no implied vol."
        )
    return correlation_from_spread_vol(spread_vol=sigma, vol_long=vol_long, vol_short=vol_short)


# ------------------------------------------------------------------ #
#                     the QuantLib route (a STRIP)                   #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class QlCmsSpreadBuild:
    """The QuantLib CMS-spread object graph, plus what it actually priced.

    ``npv`` is the value of a cap/floor/collar **strip** of ``n_periods``
    coupons - see :attr:`caveat`. :attr:`is_single_look` is always ``False``:
    QuantLib has no single-look CMS spread option, and this record exists partly
    to make that impossible to forget.
    """

    swap_index_long: Any
    swap_index_short: Any
    spread_index: Any
    cms_pricer: Any
    spread_pricer: Any
    plain_leg: Tuple[Any, ...]
    option_leg: Tuple[Any, ...]
    forward_spread: float
    adjusted_spread: float
    option_rates: Tuple[float, ...]
    npv: float
    n_periods: int
    right: str
    strike: float
    caveat: str = QUANTLIB_SINGLE_LOOK_NOTE
    is_single_look: bool = False

    @property
    def is_strip(self) -> bool:
        return self.n_periods > 1


def build_ql_cms_spread(
    *,
    discount_curve: Any,
    tenor_long: str,
    tenor_short: str,
    expiry: Any,
    correlation: float,
    strike: float,
    normal_vol: Optional[float] = None,
    swaption_vol: Any = None,
    right: str = "OPT_CAP",
    n_periods: int = 1,
    accrual_tenor: str = "1Y",
    nominal: float = 1.0,
    mean_reversion: float = 1e-4,
    integration_points: int = 32,
    currency: str = "USD",
    calendar: Any = None,
    fixed_leg_tenor: str = "6M",
    ibor_tenor: str = "3M",
    settlement_days: int = 2,
    day_count: Any = None,
    warn: bool = True,
) -> QlCmsSpreadBuild:
    """Build QuantLib's CMS-spread machinery. **This prices a STRIP, not a single look.**

    QuantLib 1.41 has ``SwapSpreadIndex``, ``CmsSpreadCoupon``,
    ``CappedFlooredCmsSpreadCoupon`` and ``LognormalCmsSpreadPricer`` - all
    coupon-based, i.e. the components of a CMS spread **cap/floor**. There is no
    CMS-spread option instrument. So this function does what QuantLib can do and
    labels it honestly; the single look is
    :func:`single_look_spread_option_price`.

    With ``n_periods=1`` the leg is a single coupon, which is the closest
    analogue QuantLib offers. It is still a different instrument: it pays
    ``nominal x accrual x max(S - K, 0)`` on the coupon's payment date, and its
    fixing carries the timing adjustment to that date, whereas a single look pays
    a caller-supplied annuity at settlement. Reported in
    :attr:`QlCmsSpreadBuild.caveat`.

    Parameters
    ----------
    discount_curve
        A ``ql.YieldTermStructure`` or a handle to one.
    tenor_long, tenor_short
        Swap tenors of the two CMS legs, e.g. ``'10Y'`` and ``'2Y'``. The spread
        index is built with gearings ``+1`` on the long leg and ``-1`` on the
        short, i.e. ``S = CMS_long - CMS_short``.
    expiry
        The fixing date: a tenor token (``'1Y'``), a ``datetime.date`` or a
        ``ql.Date``.
    correlation
        Correlation between the two CMS rates, passed to the spread pricer's
        bivariate integration.
    strike
        Cap/floor strike on the spread, in decimals.
    normal_vol, swaption_vol
        Supply exactly one. ``normal_vol`` (decimals) builds a flat
        ``ql.ConstantSwaptionVolatility`` with ``ql.Normal``; ``swaption_vol``
        takes a ``ql.SwaptionVolatilityStructure`` or handle as-is.
    right
        ``OPT_CAP`` prices the caplet(s), ``OPT_FLR`` the floorlet(s),
        ``OPT_STR`` their sum.
    n_periods, accrual_tenor
        Strip length. ``n_periods=1`` with ``accrual_tenor='1Y'`` is one annual
        coupon fixing at ``expiry``.

    Raises
    ------
    ValueError
        When neither or both of ``normal_vol``/``swaption_vol`` are given, or for
        a bad ``right``.

    Notes
    -----
    QuantLib's evaluation date is process-global state. This function reads it
    and never sets it; set ``ql.Settings.instance().evaluationDate`` yourself
    before calling, and remember that doing so affects every other QuantLib
    object alive in the process.

    ``LognormalCmsSpreadPricer`` refuses an explicit ``volatilityType`` when the
    swaption surface is ATM-only ("if only an atm surface is given, the
    volatility type must be inherited"), so the type is always inherited here.
    """
    import QuantLib as ql

    side = normalise_right(right)
    if (normal_vol is None) == (swaption_vol is None):
        raise ValueError(
            "build_ql_cms_spread needs exactly one of normal_vol (a flat normal vol in decimals) "
            "and swaption_vol (a ql.SwaptionVolatilityStructure or handle)."
        )
    if int(n_periods) < 1:
        raise ValueError(f"n_periods must be at least 1, got {n_periods!r}.")
    if warn and int(n_periods) == 1:
        warnings.warn(QUANTLIB_SINGLE_LOOK_NOTE, stacklevel=2)

    handle = (
        discount_curve
        if hasattr(discount_curve, "currentLink")
        else ql.YieldTermStructureHandle(discount_curve)
    )
    cal = calendar if calendar is not None else ql.TARGET()
    dc = day_count if day_count is not None else ql.Actual365Fixed()
    ccy = getattr(ql, f"{str(currency).strip().upper()}Currency")()
    ref = handle.referenceDate()

    ibor = ql.IborIndex(
        "CMS-IBOR", ql.Period(ibor_tenor), int(settlement_days), ccy, cal,
        ql.ModifiedFollowing, False, ql.Actual360(), handle,
    )

    def swap_index(tenor: str) -> Any:
        return ql.SwapIndex(
            "CMS-SWAP", ql.Period(str(tenor).strip().upper()), int(settlement_days), ccy, cal,
            ql.Period(fixed_leg_tenor), ql.ModifiedFollowing,
            ql.Thirty360(ql.Thirty360.BondBasis), ibor,
        )

    long_index = swap_index(tenor_long)
    short_index = swap_index(tenor_short)
    spread_index = ql.SwapSpreadIndex(
        f"CMS-{tenor_long}-{tenor_short}", long_index, short_index, 1.0, -1.0
    )

    if swaption_vol is not None:
        vol_handle = (
            swaption_vol
            if hasattr(swaption_vol, "currentLink")
            else ql.SwaptionVolatilityStructureHandle(swaption_vol)
        )
    else:
        vol_handle = ql.SwaptionVolatilityStructureHandle(
            ql.ConstantSwaptionVolatility(
                ref, cal, ql.ModifiedFollowing,
                ql.QuoteHandle(ql.SimpleQuote(float(normal_vol))), dc, ql.Normal, 0.0,
            )
        )

    mr = ql.QuoteHandle(ql.SimpleQuote(float(mean_reversion)))
    cms_pricer = ql.LinearTsrPricer(vol_handle, mr)
    # volatilityType deliberately omitted: an ATM-only surface makes it an error.
    spread_pricer = ql.LognormalCmsSpreadPricer(
        cms_pricer, ql.QuoteHandle(ql.SimpleQuote(float(correlation))), handle,
        int(integration_points),
    )

    fixing = _ql_date(expiry, reference=ref, calendar=cal)
    start = cal.advance(fixing, int(settlement_days), ql.Days)

    plain: List[Any] = []
    option: List[Any] = []
    rates: List[float] = []
    npv = 0.0
    period_start = start
    null = ql.nullDouble()
    for _ in range(int(n_periods)):
        period_end = cal.advance(period_start, ql.Period(accrual_tenor))
        pay = period_end
        base = ql.CmsSpreadCoupon(
            pay, float(nominal), period_start, period_end, int(settlement_days),
            spread_index, 1.0, 0.0, ql.Date(), ql.Date(), dc, False,
        )
        base.setPricer(spread_pricer)
        plain.append(base)

        rate = 0.0
        if side in {"C", "STRADDLE"}:
            capped = ql.CappedFlooredCmsSpreadCoupon(
                pay, float(nominal), period_start, period_end, int(settlement_days),
                spread_index, 1.0, 0.0, float(strike), null, ql.Date(), ql.Date(), dc, False,
            )
            capped.setPricer(spread_pricer)
            option.append(capped)
            rate += base.rate() - capped.rate()
        if side in {"P", "STRADDLE"}:
            floored = ql.CappedFlooredCmsSpreadCoupon(
                pay, float(nominal), period_start, period_end, int(settlement_days),
                spread_index, 1.0, 0.0, null, float(strike), ql.Date(), ql.Date(), dc, False,
            )
            floored.setPricer(spread_pricer)
            option.append(floored)
            rate += floored.rate() - base.rate()

        rates.append(float(rate))
        npv += float(nominal) * base.accrualPeriod() * float(rate) * float(handle.discount(pay))
        period_start = period_end

    first = plain[0]
    return QlCmsSpreadBuild(
        swap_index_long=long_index,
        swap_index_short=short_index,
        spread_index=spread_index,
        cms_pricer=cms_pricer,
        spread_pricer=spread_pricer,
        plain_leg=tuple(plain),
        option_leg=tuple(option),
        forward_spread=float(first.indexFixing()),
        adjusted_spread=float(first.adjustedFixing()),
        option_rates=tuple(rates),
        npv=float(npv),
        n_periods=int(n_periods),
        right=side,
        strike=float(strike),
    )


def _ql_date(when: Any, *, reference: Any, calendar: Any) -> Any:
    """Resolve a tenor token, ``date`` or ``ql.Date`` to a ``ql.Date``."""
    import QuantLib as ql

    if isinstance(when, ql.Date):
        return when
    if isinstance(when, str):
        token = when.strip().upper()
        if TENOR_RE.match(token):
            return calendar.advance(reference, ql.Period(token))
        when = pd.Timestamp(token).date()
    if isinstance(when, datetime.datetime):
        when = when.date()
    if isinstance(when, datetime.date):
        return ql.Date(when.day, when.month, when.year)
    raise TypeError(f"Cannot resolve {when!r} to a QuantLib date.")
