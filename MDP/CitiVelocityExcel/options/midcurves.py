r"""Midcurve swaptions: ``RATES.MIDCURVES.<ccy>.<kind>.<value>.<expiry>.<underlying>``.

A **midcurve** is an option expiring at ``T`` on a swap that *starts later than*
``T``. Written ``<expiry>`` on ``<start>x<tenor>``: a 1Y option on a ``1Y1Y``
underlying expires in one year, on a swap that begins one year after that and
runs for one year. The underlying token is a forward-swap token, so the option's
exercise date and the swap's start date are two different dates - which is the
whole point, and the one thing a plain-swaption model gets wrong.

What is verified and what is not
--------------------------------
**The tag shape below the currency is UNVERIFIED.** ``RATES.MIDCURVES`` was
harvested only to ``RATES.MIDCURVES.<ccy>`` - five currencies (``EUR``,
``EURIBOR``, ``GBP``, ``USD``, ``USD_SOFR``) with *no recorded children*. The
kind, value, expiry and underlying levels all come from the desk's documented
shape. :func:`~MDP.CitiVelocityExcel.tags.midcurve` warns, and so does
:func:`fetch_midcurves`. Validate with ``client.validate_with_controls([...])``
before relying on a fetch, and treat the units of ``PRICE`` and ``VOL`` as
unknown until you have seen them.

Why the pricing formula is *just* Bachelier
-------------------------------------------
Under the annuity measure of the underlying forward-starting swap, the forward
swap rate is a martingale whatever the start date is. So a midcurve is priced by
the same Bachelier formula as a spot-starting swaption, and
:func:`midcurve_price` is deliberately a thin wrapper over
:func:`Query.Base.bachelier.bachelier_price`. **All of the midcurve-specific
content lives in the two inputs**, not in the formula:

* the FORWARD is the ``start``-forward ``tenor`` swap rate seen from today, not
  the ``expiry``-forward one (:func:`midcurve_forward`);
* the ANNUITY is that forward swap's annuity discounted to today;
* the VOL is the vol of that forward rate over ``[0, T]``, which is not a node
  on a standard expiry x tenor swaption grid (:func:`midcurve_from_vol_cube`).

Saying "a midcurve is Bachelier" is therefore true and useless on its own; the
cross-check in ``_smoke.py`` that :func:`midcurve_price` equals a straight
Bachelier call is a tautology by construction, and is reported as such.

Neither library gives you the vol
---------------------------------
rateslib 2.1.1 has no IR volatility object at all - no swaption, no cube, no
``rateslib.volatility`` module; its only vol classes are FX
(``FXDeltaVolSmile``, ``FXDeltaVolSurface``, ``FXSabrSmile``, ``FXSabrSurface``,
``VolValue``). QuantLib 1.41 has ``SwaptionVolatilityMatrix`` and
``SabrSwaptionVolatilityCube``, but they are indexed by (option tenor, swap
tenor) with no forward-start axis, so a midcurve vol is not a lookup there
either. :func:`midcurve_from_vol_cube` is where that gap is closed, explicitly
and with the assumption named.

Units
-----
Rates, vols and strikes here are in DECIMALS. The obvious source of a midcurve
vol - the sibling :class:`MDP.CitiVelocityExcel.vol.cube_data.SwaptionCubeData` -
stores vols in **basis points**, so :func:`midcurve_from_vol_cube` reads that
cube's own ``vol_unit`` attribute and converts, and :func:`midcurve_price` calls
:func:`~MDP.CitiVelocityExcel.options.spread_options.assert_decimal_rate` as a
backstop. An un-converted 90 bp vol raises there instead of pricing an option
10,000 times too expensive.
"""

from __future__ import annotations

import datetime
import logging
import math
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel.catalog import TENOR_RE, CitiVeloCatalog, tenor_years
from MDP.CitiVelocityExcel.errors import CitiVelocityError, UnknownTagError
# ``_asof`` and ``_series_reader`` are imported private-to-private on purpose:
# both families fetch the same PRICE/VOL shape through the same client-or-cache
# adapter, and a second copy of that adapter is a second place for the offline
# path to rot. ``spread_options`` owns them because it also owns the tenor-pair
# grammar and the normal-vol spread algebra that a midcurve decomposition reuses.
from MDP.CitiVelocityExcel.options.spread_options import (
    _asof,
    _series_reader,
    assert_decimal_rate,
    forward_swap_rate,
    normalise_right,
    spread_normal_vol,
    split_concatenated_tenors,
)
from MDP.CitiVelocityExcel.tags import midcurve
from Query.Base.bachelier import bachelier_price, implied_normal_vol

__all__ = [
    "MIDCURVE_CURRENCIES",
    "MIDCURVE_KINDS",
    "MIDCURVE_START_IS_RELATIVE_TO_EXPIRY",
    "UNVERIFIED_TAG_NOTE",
    "MidcurveQuote",
    "assert_decimal_rate",
    "parse_underlying",
    "underlying_token",
    "fetch_midcurves",
    "midcurve_forward",
    "midcurve_price",
    "midcurve_implied_vol",
    "midcurve_from_vol_cube",
    "midcurve_vol_from_decomposition",
    "add_tenors",
]

_logger = logging.getLogger(__name__)

#: The five currency tokens recorded under ``RATES.MIDCURVES``. Note that
#: ``EUR``/``EURIBOR`` and ``USD``/``USD_SOFR`` coexist: the RFR and the legacy
#: IBOR books are separate branches, not aliases, and their vols differ.
MIDCURVE_CURRENCIES: Tuple[str, ...] = ("EUR", "EURIBOR", "GBP", "USD", "USD_SOFR")

#: ``OPT_PAY`` is a payer (a call on the swap rate), ``OPT_REC`` a receiver
#: (a put), ``OPT_STR`` a straddle.
MIDCURVE_KINDS: Tuple[str, ...] = ("OPT_PAY", "OPT_REC", "OPT_STR")

#: How ``<expiry>`` and ``<underlying>`` compose. The market convention for a
#: midcurve is that the underlying's forward start is measured **from the option
#: expiry**: a 1Y option on ``1Y1Y`` is an option expiring in 1Y on a swap that
#: starts at 2Y and matures at 3Y. Set to ``False`` (or pass
#: ``start_relative_to='spot'``) if the desk turns out to quote the start from
#: spot instead. UNVERIFIED, like the rest of this family's shape.
MIDCURVE_START_IS_RELATIVE_TO_EXPIRY: bool = True

#: Repeated wherever the family is touched. See the module docstring.
UNVERIFIED_TAG_NOTE: str = (
    "RATES.MIDCURVES was harvested only to RATES.MIDCURVES.<ccy> - five currencies with no "
    "recorded children. The kind, value, expiry and underlying levels - and the units of the "
    "served values - are the desk's documented shape and are UNVERIFIED. Validate with "
    "client.validate_with_controls([...]) before building on a fetch."
)

#: Months per unit, for :func:`add_tenors`. ``D`` and ``W`` are handled in days
#: and deliberately cannot be added to ``M``/``Y`` - see the function.
_MONTHS_PER_UNIT: Dict[str, int] = {"M": 1, "Y": 12}
_DAYS_PER_UNIT: Dict[str, int] = {"D": 1, "W": 7}


# ------------------------------------------------------------------ #
#                       the underlying grammar                       #
# ------------------------------------------------------------------ #


def parse_underlying(token: str) -> Tuple[str, str]:
    r"""``'1Y1Y'`` -> ``('1Y', '1Y')``: the forward start and the swap tenor.

    Uses the same decidable splitting rule as the CMS spread pair - enumerate
    every position at which both halves match ``^\d+[DWMY]$`` and accept only a
    unique one - so ``'1Y10Y'`` resolves to ``('1Y', '10Y')`` and never to
    ``('1Y1', '0Y')``. See
    :func:`~MDP.CitiVelocityExcel.options.spread_options.split_concatenated_tenors`.

    The two positions mean different things here than in a CMS pair: the FIRST is
    the underlying swap's forward start, the SECOND is its tenor. They are not
    interchangeable and are not reordered by maturity.

    Raises
    ------
    ValueError
        When the token does not parse, or parses more than one way.

    Examples
    --------
    >>> parse_underlying("1Y1Y")
    ('1Y', '1Y')
    >>> parse_underlying("1Y10Y")
    ('1Y', '10Y')
    >>> parse_underlying("3M2Y")
    ('3M', '2Y')
    """
    return split_concatenated_tenors(token, what="underlying")


def underlying_token(start: str, tenor: str) -> str:
    """The inverse of :func:`parse_underlying`, round-trip checked.

    Raises
    ------
    ValueError
        When either token is not a Velocity tenor, or when the concatenation
        would not read back as the same pair.
    """
    a = str(start).strip().upper()
    b = str(tenor).strip().upper()
    for token in (a, b):
        if not TENOR_RE.match(token):
            raise ValueError(f"{token!r} is not a Velocity tenor ({TENOR_RE.pattern}).")
    joined = f"{a}{b}"
    if parse_underlying(joined) != (a, b):
        raise ValueError(
            f"{a!r} + {b!r} concatenate to {joined!r}, which does not round-trip through "
            "parse_underlying. Use an explicit separator."
        )
    return joined


def add_tenors(a: str, b: str) -> str:
    """Add two Velocity tenor tokens, e.g. ``'1Y' + '1Y' -> '2Y'``, ``'3M' + '1Y' -> '15M'``.

    Month/year tokens add in months; day/week tokens add in days. **Mixing the
    two raises**, rather than converting a month to 30 days: a midcurve's expiry
    is the date the option dies, and silently sliding it by the 5.25 days a year
    of ``12 x 30`` loses is the kind of error that shows up as a small persistent
    bias rather than as a failure.

    Raises
    ------
    ValueError
        For a non-tenor token, or for a day/week token added to a month/year one.
        The message names the ``combined_start=`` override on
        :func:`midcurve_forward`.
    """
    ta, tb = str(a).strip().upper(), str(b).strip().upper()
    for token in (ta, tb):
        if not TENOR_RE.match(token):
            raise ValueError(f"{token!r} is not a Velocity tenor ({TENOR_RE.pattern}).")
    ua, ub = ta[-1], tb[-1]
    na, nb = int(ta[:-1]), int(tb[:-1])

    if ua in _MONTHS_PER_UNIT and ub in _MONTHS_PER_UNIT:
        months = na * _MONTHS_PER_UNIT[ua] + nb * _MONTHS_PER_UNIT[ub]
        return f"{months // 12}Y" if months % 12 == 0 else f"{months}M"
    if ua in _DAYS_PER_UNIT and ub in _DAYS_PER_UNIT:
        days = na * _DAYS_PER_UNIT[ua] + nb * _DAYS_PER_UNIT[ub]
        return f"{days // 7}W" if days % 7 == 0 else f"{days}D"
    raise ValueError(
        f"Cannot add {ta!r} and {tb!r}: one is in days/weeks and the other in months/years, and "
        "there is no exact conversion between them. Pass the combined forward start explicitly, "
        "e.g. midcurve_forward(..., combined_start='15M')."
    )


# ------------------------------------------------------------------ #
#                       the quote record + fetch                     #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class MidcurveQuote:
    """One ``(expiry, underlying)`` midcurve quote, as served.

    ``price`` and ``vol`` are RAW, in whatever units the add-in returns. They are
    not converted, because the units of this family are unverified - see
    :data:`UNVERIFIED_TAG_NOTE`. The sibling ``RATES.VOL`` family quotes
    ``NORMAL`` in basis points, which is the first thing to check.
    """

    currency: str
    kind: str
    expiry: str
    underlying: str
    underlying_start: str
    underlying_tenor: str
    price: Optional[float]
    vol: Optional[float]
    as_of: Optional[pd.Timestamp]
    price_tag: str = ""
    vol_tag: str = ""

    @classmethod
    def from_underlying(
        cls,
        *,
        currency: str,
        kind: str,
        expiry: str,
        underlying: str,
        price: Optional[float] = None,
        vol: Optional[float] = None,
        as_of: Optional[pd.Timestamp] = None,
        price_tag: str = "",
        vol_tag: str = "",
    ) -> "MidcurveQuote":
        """Build a quote, splitting the underlying token into start and tenor."""
        start, tenor = parse_underlying(underlying)
        return cls(
            currency=str(currency).strip().upper(),
            kind=str(kind).strip().upper(),
            expiry=str(expiry).strip().upper(),
            underlying=str(underlying).strip().upper(),
            underlying_start=start,
            underlying_tenor=tenor,
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
        """Approximate year fraction to the option's expiry."""
        return tenor_years(self.expiry)

    @property
    def swap_start_years(self) -> float:
        """Years from today to the underlying swap's start date.

        Expiry plus the underlying's forward start, under
        :data:`MIDCURVE_START_IS_RELATIVE_TO_EXPIRY`.
        """
        if MIDCURVE_START_IS_RELATIVE_TO_EXPIRY:
            return tenor_years(self.expiry) + tenor_years(self.underlying_start)
        return tenor_years(self.underlying_start)

    @property
    def is_true_midcurve(self) -> bool:
        """False when the underlying starts at expiry, i.e. it is a plain swaption."""
        return tenor_years(self.underlying_start) > 0.0


def fetch_midcurves(
    *,
    client: Any,
    currency: str,
    expiries: Sequence[str],
    underlyings: Sequence[str],
    kind: str = "OPT_STR",
    as_of: Any = None,
    cache: Any = None,
    freq: str = "DAILY",
    lookback: Optional[datetime.timedelta] = None,
    catalog: Optional[CitiVeloCatalog] = None,
    warn: bool = True,
) -> List[MidcurveQuote]:
    """Fetch ``PRICE`` and ``VOL`` for an ``expiries x underlyings`` block, as of one date.

    Both values for every combination go out in one batched request.

    Parameters
    ----------
    client
        A :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes`, a raw
        :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient`, or
        ``None`` for a cache-only read.
    currency
        One of :data:`MIDCURVE_CURRENCIES`; validated against the catalog.
        ``USD`` and ``USD_SOFR`` are different books, not aliases.
    expiries, underlyings
        Option expiry tokens (``'1Y'``) and forward-swap tokens (``'1Y1Y'``).
        Underlyings are parsed before any request goes out.
    kind
        ``OPT_PAY``, ``OPT_REC`` or ``OPT_STR``.
    as_of
        Snapshot date; ``None`` takes each tag's latest row. Backward-only.
    cache
        A :class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache`, used only when
        ``client`` is a raw client.

    Returns
    -------
    list[MidcurveQuote]
        One entry per combination for which at least one of ``PRICE``/``VOL``
        resolved.

    Raises
    ------
    CitiVelocityError
        When nothing resolved - the expected outcome if the documented shape is
        wrong, and therefore loud rather than an empty list.

    Notes
    -----
    Everything below the currency is unverified; see :data:`UNVERIFIED_TAG_NOTE`.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    ccy = str(currency).strip().upper()
    kind_token = str(kind).strip().upper()
    if kind_token not in MIDCURVE_KINDS:
        raise UnknownTagError(
            f"Unknown MIDCURVES kind {kind!r}. Accepted: {', '.join(MIDCURVE_KINDS)}."
        )
    expiry_list = [str(e).strip().upper() for e in expiries if str(e).strip()]
    underlying_list = [str(u).strip().upper() for u in underlyings if str(u).strip()]
    if not expiry_list or not underlying_list:
        raise ValueError("fetch_midcurves needs at least one expiry and one underlying.")
    for token in underlying_list:
        parse_underlying(token)  # fail before touching Excel

    if warn:
        warnings.warn(UNVERIFIED_TAG_NOTE, stacklevel=2)

    tags: Dict[Tuple[str, str, str], str] = {}
    for expiry in expiry_list:
        for token in underlying_list:
            for value in ("PRICE", "VOL"):
                tags[(expiry, token, value)] = midcurve(
                    ccy, expiry, token, kind=kind_token, value=value, catalog=cat, warn=False
                )

    when = None if as_of is None else pd.Timestamp(as_of)
    if lookback is None:
        lookback = datetime.timedelta(days=5 if str(freq).upper() in {"MI01", "MI10", "HOURLY"} else 30)
    end = when
    start = None if when is None else when - lookback

    reader = _series_reader(client, cache)
    served = dict(reader(list(dict.fromkeys(tags.values())), freq, start, end) or {})

    out: List[MidcurveQuote] = []
    missing = 0
    for expiry in expiry_list:
        for token in underlying_list:
            price_tag = tags[(expiry, token, "PRICE")]
            vol_tag = tags[(expiry, token, "VOL")]
            price, price_at = _asof(served.get(price_tag), when)
            vol, vol_at = _asof(served.get(vol_tag), when)
            if price is None and vol is None:
                missing += 1
                continue
            stamps = [t for t in (price_at, vol_at) if t is not None]
            out.append(
                MidcurveQuote.from_underlying(
                    currency=ccy,
                    kind=kind_token,
                    expiry=expiry,
                    underlying=token,
                    price=price,
                    vol=vol,
                    as_of=(max(stamps) if stamps else None),
                    price_tag=price_tag,
                    vol_tag=vol_tag,
                )
            )

    if not out:
        raise CitiVelocityError(
            f"RATES.MIDCURVES.{ccy}.{kind_token} served nothing for {len(expiry_list)} expiry(s) x "
            f"{len(underlying_list)} underlying(s). {UNVERIFIED_TAG_NOTE} First tag tried: "
            f"{tags[(expiry_list[0], underlying_list[0], 'VOL')]}"
        )
    if missing:
        _logger.warning(
            "fetch_midcurves: %d of %d (expiry, underlying) combinations served neither PRICE nor "
            "VOL for RATES.MIDCURVES.%s.%s. Everything below the currency level of this family is "
            "unverified.",
            missing,
            len(expiry_list) * len(underlying_list),
            ccy,
            kind_token,
        )
    return out


# ------------------------------------------------------------------ #
#                        forward and price                           #
# ------------------------------------------------------------------ #


def midcurve_forward(
    *,
    curve: Any,
    expiry: str,
    underlying_start: str,
    underlying_tenor: str,
    start_relative_to: str = "expiry",
    combined_start: Optional[str] = None,
    **forward_kwargs: Any,
) -> float:
    """The forward swap rate a midcurve is struck on, in DECIMALS.

    The underlying swap starts at ``expiry + underlying_start`` and runs for
    ``underlying_tenor``. So a 1Y option on ``1Y1Y`` is priced off the **2Y
    forward 1Y** swap rate, not the 1Y forward 1Y rate - getting that wrong is
    the single easiest way to misprice a midcurve, and on an upward-sloping curve
    it is worth tens of basis points.

    Parameters
    ----------
    curve
        Anything
        :func:`~MDP.CitiVelocityExcel.options.spread_options.forward_swap_rate`
        accepts: a float, a rateslib ``Curve``, a QuantLib term structure or
        handle, or a discount-factor callable/mapping.
    expiry
        The option's expiry token.
    underlying_start, underlying_tenor
        The two halves of the underlying token, from :func:`parse_underlying`.
    start_relative_to
        ``'expiry'`` (default, market convention - see
        :data:`MIDCURVE_START_IS_RELATIVE_TO_EXPIRY`) or ``'spot'``, which reads
        the underlying's start from today and makes the tag's expiry level pure
        metadata.
    combined_start
        Overrides the computed forward start. Use it when the expiry and the
        start are in incompatible units (``'2W'`` and ``'1Y'``), which
        :func:`add_tenors` refuses to guess at.
    **forward_kwargs
        Passed through to ``forward_swap_rate`` (``spec``, ``calendar``,
        ``valuation``, ...).

    Raises
    ------
    ValueError
        For an unknown ``start_relative_to``, or when the two tenors cannot be
        added exactly.
    """
    mode = str(start_relative_to).strip().lower()
    if mode not in {"expiry", "spot"}:
        raise ValueError(
            f"start_relative_to must be 'expiry' or 'spot', got {start_relative_to!r}."
        )
    if combined_start is not None:
        start = str(combined_start).strip().upper()
    elif mode == "expiry":
        start = add_tenors(expiry, underlying_start)
    else:
        start = str(underlying_start).strip().upper()
    return forward_swap_rate(curve=curve, forward=start, tenor=underlying_tenor, **forward_kwargs)


def midcurve_price(
    *,
    forward: float,
    strike: float,
    normal_vol: float,
    expiry_years: float,
    annuity: float = 1.0,
    right: str = "OPT_STR",
    discount: float = 1.0,
) -> float:
    r"""Bachelier price of a midcurve swaption.

    .. math:: V = A \cdot D \cdot \mathrm{Bachelier}(\eta;\, F, K, \sigma_N, T)

    Deliberately a thin wrapper over
    :func:`Query.Base.bachelier.bachelier_price`. Under the annuity measure of
    the underlying forward-starting swap the forward rate is a martingale
    regardless of when that swap starts, so the *formula* for a midcurve is the
    same as for a spot-starting swaption. Everything that makes it a midcurve is
    in the inputs:

    * ``forward`` must be the ``expiry + start``-forward rate
      (:func:`midcurve_forward`), not the ``expiry``-forward one;
    * ``annuity`` must be that forward swap's annuity discounted to today;
    * ``normal_vol`` must be the vol of that forward rate over ``[0, T]``, which
      is not a node on a standard swaption grid
      (:func:`midcurve_from_vol_cube`).

    Parameters
    ----------
    forward, strike
        In DECIMALS.
    normal_vol
        Normal vol in DECIMALS (``0.01`` = 100 bp).
    expiry_years
        Time to the option's expiry, in years - NOT to the swap's start.
    annuity
        The underlying swap's annuity (PV of 1 per unit fixed rate), discounted
        to today. ``1.0`` returns the value per unit of annuity, i.e. the option
        premium expressed as a rate.
    right
        ``OPT_PAY``/call, ``OPT_REC``/put, ``OPT_STR``/straddle.
    discount
        An extra discount factor, for a premium paid at a date other than the one
        the annuity already discounts to. Leave at ``1.0`` when ``annuity`` is
        already a today-PV.

    Raises
    ------
    ValueError
        For a negative expiry or vol, or an unknown ``right``.
    """
    if float(expiry_years) < 0.0:
        raise ValueError(f"expiry_years must be non-negative, got {expiry_years!r}.")
    if float(normal_vol) < 0.0:
        raise ValueError(f"normal_vol must be non-negative, got {normal_vol!r}.")
    # The bp-vs-decimal backstop. SwaptionCubeData stores vols in bp, so an
    # un-converted hand-off lands here rather than in a price.
    assert_decimal_rate(normal_vol, "normal_vol")
    assert_decimal_rate(forward, "forward")
    assert_decimal_rate(strike, "strike")
    side = normalise_right(right)
    scale = float(annuity)
    if side == "STRADDLE":
        call = bachelier_price("C", float(strike), float(forward), float(normal_vol),
                               float(expiry_years), float(discount))
        put = bachelier_price("P", float(strike), float(forward), float(normal_vol),
                              float(expiry_years), float(discount))
        return scale * (call + put)
    return scale * bachelier_price(
        side, float(strike), float(forward), float(normal_vol), float(expiry_years), float(discount)
    )


def midcurve_implied_vol(
    *,
    market_price: float,
    forward: float,
    strike: float,
    expiry_years: float,
    annuity: float = 1.0,
    right: str = "OPT_STR",
    discount: float = 1.0,
) -> float:
    """Invert :func:`midcurve_price` for the normal vol, in decimals.

    Straddles are converted to calls through put-call parity before inverting
    (``C = (straddle + (F - K)) / 2`` on the undiscounted value), which is exact
    in Bachelier.

    Raises
    ------
    ValueError
        When the scaling is zero, the value is non-positive, or the inversion
        fails. It never returns ``nan``: the underlying
        :func:`Query.Base.bachelier.implied_normal_vol` does, and a ``nan`` vol
        propagates into a surface as a hole rather than as an error.
    """
    scale = float(annuity) * float(discount)
    if scale == 0.0:
        raise ValueError("midcurve_implied_vol: annuity * discount is zero, so nothing is invertible.")
    side = normalise_right(right)
    fwd = float(forward)
    k = float(strike)
    value = float(market_price) / scale
    if value <= 0.0:
        raise ValueError(
            f"midcurve_implied_vol needs a positive option value; got {market_price!r}, which is "
            f"{value!r} after dividing out annuity*discount={scale!r}."
        )
    if side == "STRADDLE":
        value = 0.5 * (value + (fwd - k))
        side = "C"
        if value <= 0.0:
            raise ValueError(
                f"The straddle price {market_price!r} implies a non-positive call leg ({value!r})."
            )
    vol = implied_normal_vol(side, k, fwd, float(expiry_years), value, 1.0)
    if not math.isfinite(vol):
        intrinsic = max(fwd - k, 0.0) if side == "C" else max(k - fwd, 0.0)
        raise ValueError(
            f"Bachelier inversion failed for value={value!r} (forward={fwd!r}, strike={k!r}, "
            f"T={expiry_years!r}); intrinsic is {intrinsic!r}."
        )
    return float(vol)


# ------------------------------------------------------------------ #
#                    reading a vol off a cube                        #
# ------------------------------------------------------------------ #


def midcurve_vol_from_decomposition(
    *,
    vol_long: float,
    vol_short: float,
    annuity_long: float,
    annuity_short: float,
    correlation: float = 0.99,
) -> float:
    r"""A midcurve vol from two CO-EXPIRING spot-starting swaption vols.

    A swap that starts at ``T + s`` and runs ``n`` years is, seen from ``T``, the
    difference of two swaps that both start at ``T``: the ``(s + n)`` one minus
    the ``s`` one. Annuity-weighting that identity gives the forward rate as an
    annuity-weighted spread of two co-expiring swap rates,

    .. math::
        F_{mid} = w_L F_L - w_S F_S, \quad
        w_L = \frac{A_L}{A_L - A_S}, \quad w_S = \frac{A_S}{A_L - A_S}

    (note :math:`w_L - w_S = 1`), whose normal vol is the usual quadratic form

    .. math::
        \sigma_{mid}^2 = (w_L\sigma_L)^2 + (w_S\sigma_S)^2
                         - 2\rho\, w_L\sigma_L\, w_S\sigma_S .

    Assumptions
    -----------
    * The two annuity weights are **frozen** at today's values; in reality they
      move with the rates. This is the same linear-swap-rate approximation the
      CMS convexity adjustment rests on.
    * ``correlation`` is the correlation between the two co-expiring swap rates.
      It is very high (two overlapping swaps on the same curve) and the answer is
      *extremely* sensitive to it, because ``w_L`` and ``w_S`` are both large
      when ``A_L`` and ``A_S`` are close - i.e. exactly when the underlying is
      short. The default of ``0.99`` is a placeholder, not a measurement: pass
      your own, and check the sensitivity before trusting the number.

    Raises
    ------
    ValueError
        When ``annuity_long <= annuity_short`` (the decomposition would have a
        non-positive or infinite midcurve annuity), or for a correlation outside
        ``[-1, 1]``.
    """
    al = float(annuity_long)
    a_s = float(annuity_short)
    denom = al - a_s
    if denom <= 0.0:
        raise ValueError(
            f"The midcurve annuity A_long - A_short is {denom!r}, which is not positive. The "
            f"long leg must cover the short one (annuity_long={al!r} > annuity_short={a_s!r}); "
            "check that annuity_long is the (start + tenor) swap and annuity_short the (start) one."
        )
    w_long = al / denom
    w_short = a_s / denom
    return spread_normal_vol(
        vol_long=w_long * float(vol_long),
        vol_short=w_short * float(vol_short),
        correlation=correlation,
    )


def midcurve_from_vol_cube(
    *,
    cube: Any,
    expiry: str,
    underlying_start: str,
    underlying_tenor: str,
    method: str = "direct",
    correlation: float = 0.99,
    annuity_long: Optional[float] = None,
    annuity_short: Optional[float] = None,
    unit: str = "auto",
) -> float:
    """Read (or build) a midcurve normal vol from a swaption-cube-shaped object.

    ``cube`` is duck-typed, because this package's own ``vol`` layer
    (``SwaptionCubeData``) is a sibling module that may not be present. Anything
    that answers one of these is accepted, tried in this order:

    ``callable``
        ``cube(expiry, tenor)``.
    ``.normal_vol(...)``
        Tried as ``cube.normal_vol(expiry=..., tenor=...)``, then positionally.
    ``.vol(...)``
        Same two forms.
    ``pandas.DataFrame``
        Rows are expiries, columns are tenors.
    ``Mapping``
        Keyed ``(expiry, tenor)`` or ``'<expiry>x<tenor>'`` or ``'<expiry><tenor>'``.

    Methods, and their interpolation assumptions
    --------------------------------------------
    ``'direct'`` (default)
        Look the vol up at ``(expiry, underlying)``, i.e. at the *forward-swap*
        token ``'1Y1Y'``. This is the right read when ``cube`` is itself a
        MIDCURVE surface - which is what ``RATES.MIDCURVES...VOL`` serves - and
        then no interpolation happens at all.
    ``'tenor'``
        Look the vol up at ``(expiry, underlying_tenor)`` on a standard swaption
        cube, ignoring the forward start entirely. This is the crude desk proxy.
        It is WRONG by construction whenever the start is non-zero: it prices the
        vol of a swap starting at expiry, not at expiry + start. Use it only to
        bracket a number, and expect it to be biased low on an upward-sloping vol
        surface, because a short spot-starting swap is the noisiest point on the
        grid.
    ``'decomposition'``
        Read the two co-expiring vols at ``(expiry, start + tenor)`` and
        ``(expiry, start)`` and combine them with
        :func:`midcurve_vol_from_decomposition`. Requires ``annuity_long`` and
        ``annuity_short``, and is very sensitive to ``correlation``.

    Off-node lookups on a ``Mapping`` or ``DataFrame`` are filled by **bilinear
    interpolation in the normal vol against approximate year fractions on both
    axes, with FLAT extrapolation past the grid edges.** Flat and not linear
    because linear extrapolation off the short end of a vol grid goes negative,
    and a negative vol is not a number a caller can notice. This is not the
    desk's own interpolation and will not reproduce it exactly; when the object
    supplies its own ``normal_vol``/``vol`` method that method is used instead
    and none of this applies.

    Units - the trap this function exists to defuse
    -----------------------------------------------
    Everything else in this sub-package is in DECIMALS, but
    :class:`MDP.CitiVelocityExcel.vol.cube_data.SwaptionCubeData` stores normal
    vols in **basis points** (its ``vol_unit`` attribute says so). Handing its
    output straight to :func:`midcurve_price` is a 1e4 error that produces a
    perfectly plausible-looking number.

    ``unit`` controls the conversion:

    ``'auto'`` (default)
        Read the cube's own ``vol_unit`` attribute if it has one and convert
        accordingly; pass through unchanged if it does not.
    ``'bp'``
        Always divide by 1e4.
    ``'decimal'`` / ``'as_is'``
        Never convert.

    :func:`~MDP.CitiVelocityExcel.options.spread_options.assert_decimal_rate` in
    the pricers is the backstop: a vol above 1.0 raises there rather than being
    priced.

    Returns
    -------
    float
        The normal vol, in decimals when ``unit`` resolved the conversion and in
        the cube's own units when it could not (``'auto'`` on a cube with no
        ``vol_unit``, or ``'as_is'``).

    Raises
    ------
    ValueError
        For an unknown ``method`` or ``unit``, for ``'decomposition'`` without
        annuities, or when the lookup finds nothing. It raises rather than
        returning ``nan``.
    TypeError
        When ``cube`` answers none of the supported protocols.
    """
    mode = str(method).strip().lower()
    start = str(underlying_start).strip().upper()
    tenor = str(underlying_tenor).strip().upper()
    exp = str(expiry).strip().upper()
    scale = _unit_scale(cube, unit)

    if mode == "direct":
        return scale * _read_cube(cube, exp, underlying_token(start, tenor))
    if mode == "tenor":
        return scale * _read_cube(cube, exp, tenor)
    if mode == "decomposition":
        if annuity_long is None or annuity_short is None:
            raise ValueError(
                "midcurve_from_vol_cube(method='decomposition') needs annuity_long (the "
                "start+tenor swap's annuity) and annuity_short (the start swap's annuity). "
                "Without them the two co-expiring vols cannot be weighted, and an unweighted "
                "difference is not a midcurve vol."
            )
        total = add_tenors(start, tenor)
        # The combination is homogeneous of degree one in the vols, so scaling
        # once at the end is identical to scaling both legs first.
        return scale * midcurve_vol_from_decomposition(
            vol_long=_read_cube(cube, exp, total),
            vol_short=_read_cube(cube, exp, start),
            annuity_long=annuity_long,
            annuity_short=annuity_short,
            correlation=correlation,
        )
    raise ValueError(
        f"Unknown method {method!r}. Accepted: 'direct' (the cube is itself a midcurve surface), "
        "'tenor' (crude proxy off a standard cube), 'decomposition' (annuity-weighted difference "
        "of two co-expiring vols)."
    )


def _unit_scale(cube: Any, unit: str) -> float:
    """The multiplier taking the cube's vols into decimals. See the caller."""
    token = str(unit).strip().lower()
    if token == "bp":
        return 1e-4
    if token in {"decimal", "dec", "as_is", "asis"}:
        return 1.0
    if token != "auto":
        raise ValueError(
            f"Unknown unit {unit!r}. Accepted: 'auto' (read the cube's own vol_unit), 'bp', "
            "'decimal', 'as_is'."
        )
    declared = str(getattr(cube, "vol_unit", "") or "").strip().lower()
    if declared in {"bp", "bps", "basis_points"}:
        _logger.debug("midcurve_from_vol_cube: cube declares vol_unit=%r; converting bp -> decimal.",
                      declared)
        return 1e-4
    if declared in {"decimal", "dec", "absolute"}:
        return 1.0
    if declared:
        raise ValueError(
            f"The cube declares vol_unit={declared!r}, which is neither 'bp' nor 'decimal', so "
            "unit='auto' cannot resolve it. Pass unit='bp' or unit='decimal' explicitly."
        )
    return 1.0


def _read_cube(cube: Any, expiry: str, tenor: str) -> float:
    """One vol out of a duck-typed cube. See :func:`midcurve_from_vol_cube`."""
    if cube is None:
        raise TypeError("midcurve_from_vol_cube needs a cube; got None.")

    # A cube that carries its own accessor owns its own interpolation; ask it
    # first, before falling back to the grid rules documented on the caller.
    for name in ("normal_vol", "vol"):
        method = getattr(cube, name, None)
        if callable(method):
            try:
                return _finite(method(expiry=expiry, tenor=tenor), expiry, tenor)
            except TypeError:
                return _finite(method(expiry, tenor), expiry, tenor)

    if callable(cube) and not isinstance(cube, Mapping):
        return _finite(cube(expiry, tenor), expiry, tenor)

    grid = _cube_grid(cube)
    if not grid:
        raise ValueError(f"The supplied cube is empty, so ({expiry}, {tenor}) cannot be read.")
    if (expiry, tenor) in grid:
        return _finite(grid[(expiry, tenor)], expiry, tenor)
    if not TENOR_RE.match(tenor):
        # 'direct' mode asks for a forward-swap token like '1Y1Y'; that axis has
        # no ordering, so an off-node read cannot be interpolated - only missed.
        raise ValueError(
            f"({expiry}, {tenor}) is not on the supplied cube and {tenor!r} is a forward-swap "
            "token, not a tenor, so it cannot be interpolated. Either the cube is not a midcurve "
            "surface (try method='tenor' or method='decomposition') or that node is absent. "
            f"Cube holds {len(grid)} node(s)."
        )
    return _bilinear(grid, expiry, tenor)


def _cube_grid(cube: Any) -> Dict[Tuple[str, str], float]:
    """Normalise a DataFrame or Mapping cube to ``{(expiry, tenor): vol}``."""
    if isinstance(cube, pd.DataFrame):
        out: Dict[Tuple[str, str], float] = {}
        for exp in cube.index:
            for ten in cube.columns:
                value = cube.at[exp, ten]
                if pd.notna(value):
                    out[(str(exp).strip().upper(), str(ten).strip().upper())] = float(value)
        return out
    if isinstance(cube, Mapping):
        out = {}
        for key, value in cube.items():
            if value is None:
                continue
            if isinstance(key, tuple) and len(key) == 2:
                out[(str(key[0]).strip().upper(), str(key[1]).strip().upper())] = float(value)
                continue
            text = str(key).strip().upper()
            for sep in ("X", "/", "-", " "):
                if sep in text:
                    left, _, right = text.partition(sep)
                    if TENOR_RE.match(left) and TENOR_RE.match(right):
                        out[(left, right)] = float(value)
                        break
            else:
                try:
                    left, right = split_concatenated_tenors(text, what="cube key")
                except ValueError:
                    continue
                out[(left, right)] = float(value)
        return out
    raise TypeError(
        f"midcurve_from_vol_cube cannot read a cube of type {type(cube).__name__}. Accepted: a "
        "callable (expiry, tenor) -> vol, an object with .normal_vol/.vol, a pandas DataFrame "
        "indexed expiry x tenor, or a mapping keyed (expiry, tenor)."
    )


def _finite(value: Any, expiry: str, tenor: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(
            f"The cube returned {value!r} for ({expiry}, {tenor}). A non-finite vol is not a "
            "usable quote; fix the surface rather than propagating it into a price."
        )
    return result


def _bilinear(grid: Mapping[Tuple[str, str], float], expiry: str, tenor: str) -> float:
    """Bilinear in (expiry_years, tenor_years) with flat extrapolation. See caller."""
    expiries = sorted({e for e, _ in grid}, key=tenor_years)
    tenors = sorted({t for _, t in grid}, key=tenor_years)
    if not expiries or not tenors:
        raise ValueError(f"The cube has no usable axis; cannot read ({expiry}, {tenor}).")

    def bracket(axis: Sequence[str], want: str) -> Tuple[str, str, float]:
        target = tenor_years(want)
        lo = axis[0]
        hi = axis[-1]
        if target <= tenor_years(lo):
            return lo, lo, 0.0
        if target >= tenor_years(hi):
            return hi, hi, 0.0
        for a, b in zip(axis, axis[1:]):
            ya, yb = tenor_years(a), tenor_years(b)
            if ya <= target <= yb:
                return a, b, (0.0 if yb == ya else (target - ya) / (yb - ya))
        return hi, hi, 0.0

    e0, e1, we = bracket(expiries, expiry)
    t0, t1, wt = bracket(tenors, tenor)
    corners = [(e0, t0), (e0, t1), (e1, t0), (e1, t1)]
    missing = [c for c in corners if c not in grid]
    if missing:
        raise ValueError(
            f"Cannot interpolate ({expiry}, {tenor}): the surrounding grid nodes {missing} are "
            "absent. The cube is ragged; fill it or read a node that exists."
        )
    lower = grid[(e0, t0)] * (1.0 - wt) + grid[(e0, t1)] * wt
    upper = grid[(e1, t0)] * (1.0 - wt) + grid[(e1, t1)] * wt
    return float(lower * (1.0 - we) + upper * we)
