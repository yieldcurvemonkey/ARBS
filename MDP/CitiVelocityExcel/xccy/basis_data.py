r"""The cross-currency basis curve as a value object, and how to fetch one.

``RATES.XCCY_OIS_SWAP.<ccy1>.<ccy2>.<fwd>.<tenor>.{BASE_LEG,SPREAD_LEG}.BASIS_SPREAD``
is the one Velocity family that validated 1,097/1,097 - every recorded tag is
shape-correct end to end. This module turns a set of those tags into an
:class:`XccyBasisCurve`: a tenor-indexed strip of basis spreads in basis points,
with the provenance of every point attached.

Three things here are **assumptions, not observations**, because they cannot be
settled without a live add-in and a market cross-check. Each is a keyword knob:

``spread_ccy``
    Which currency's leg carries the quoted spread. The harvest records both
    ``BASE_LEG.BASIS_SPREAD`` and ``SPREAD_LEG.BASIS_SPREAD`` under every tenor
    but says nothing about which *currency* either maps to. The default follows
    the market convention that the spread sits on the non-USD leg
    (:func:`default_spread_ccy`); it is NOT confirmed against Velocity data.

``collateral_ccy``
    Which currency the swap is assumed collateralised in, i.e. which discount
    curve is taken as given and which is implied. Defaults to USD for any pair
    containing USD (:func:`default_collateral_ccy`).

sign
    ``+10bp`` is taken to mean "the spread leg pays its RFR **plus** 10bp". If
    Velocity signs its BASIS_SPREAD the other way the whole strip flips, and
    every downstream number flips with it. Pass ``sign=-1`` to
    :func:`fetch_xccy_basis` / :func:`basis_from_quotes` to invert.

``AUD_BBSW`` and ``NZD_BKBM`` are IBOR-indexed legs, not OIS legs. They are
carried here as data but :func:`ois_index_for_currency` refuses them, so the
OIS-leg builders in :mod:`~MDP.CitiVelocityExcel.xccy.rl_xccy` and
:mod:`~MDP.CitiVelocityExcel.xccy.ql_xccy` cannot silently price them as OIS.
"""

from __future__ import annotations

import datetime
import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

import pandas as pd

from MDP.CitiVelocityExcel import tags as cv_tags
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog, sort_tenors, tenor_years
from MDP.CitiVelocityExcel.curves.conventions import CurveConvention, conventions_for
from MDP.CitiVelocityExcel.errors import CatalogError, UnknownTagError

__all__ = [
    "XccyBasisCurve",
    "XCCY_TENORS",
    "XCCY_BASE_CURRENCIES",
    "XCCY_QUOTE_CURRENCIES",
    "PRIMARY_OIS_INDEX",
    "IBOR_LEG_TOKENS",
    "assert_ois_pair",
    "basis_from_quotes",
    "conventions_for_currency",
    "default_collateral_ccy",
    "default_spread_ccy",
    "fetch_xccy_basis",
    "iso_currency",
    "ois_index_for_currency",
]

_logger = logging.getLogger(__name__)

#: The tenor axis actually observed in the 1,097 validated XCCY tags. The
#: catalog walk was depth-capped at ``<ccy1>.<ccy2>.<fwd>``, so
#: ``catalog.options()`` returns ``[]`` one level below and a grid built from it
#: would be EMPTY - this constant is what makes ``tenors=None`` mean something.
XCCY_TENORS: Tuple[str, ...] = (
    "1M",
    "3M",
    "6M",
    "9M",
    "1Y",
    "18M",
    "2Y",
    "3Y",
    "4Y",
    "5Y",
    "6Y",
    "7Y",
    "8Y",
    "9Y",
    "10Y",
    "11Y",
    "12Y",
    "15Y",
    "20Y",
    "25Y",
    "30Y",
)

#: ``RATES.XCCY_OIS_SWAP.<ccy1>`` - the recorded base-currency tokens.
XCCY_BASE_CURRENCIES: Tuple[str, ...] = (
    "AUD",
    "AUD_BBSW",
    "CAD",
    "CHF",
    "DKK",
    "EUR",
    "GBP",
    "ILS",
    "JPY",
    "NOK",
    "NZD",
    "NZD_BKBM",
    "SEK",
    "SGD",
    "THB",
    "USD",
)

#: ``RATES.XCCY_OIS_SWAP.<ccy1>.<ccy2>`` - the recorded quote-currency tokens.
XCCY_QUOTE_CURRENCIES: Tuple[str, ...] = (
    "AUD",
    "AUD_BBSW",
    "CAD",
    "CHF",
    "EUR",
    "GBP",
    "JPY",
    "NOK",
    "NZD",
    "NZD_BKBM",
    "SEK",
    "USD",
)

#: Citi tokens whose leg is IBOR-indexed (3M BBSW / 3M BKBM), not RFR-OIS.
#: The OIS builders refuse these rather than price a term-fixing leg as OIS.
IBOR_LEG_TOKENS: Tuple[str, ...] = ("AUD_BBSW", "NZD_BKBM")

#: ISO currency -> the Citi OIS index token this package strips that leg from.
#: JPY is ambiguous: Citi publishes ``JPY_TONAR``, ``JPY_TONAR_JSCC`` and
#: ``JPY_TONAR_LCH`` and the JSCC/LCH basis is real. Cross-currency clears at
#: LCH, so ``JPY_TONAR_LCH`` would arguably be the better default; ``JPY_TONAR``
#: is used because it is the token with the deepest recorded history. Override
#: with the ``ois_index`` knob on :func:`conventions_for_currency`.
PRIMARY_OIS_INDEX: Dict[str, str] = {
    "AUD": "AUD_AONIA",
    "CAD": "CAD_CORRA",
    "CHF": "CHF_SARON",
    "DKK": "DKK_TNDKK",
    "EUR": "EUR_EUROSTR",
    "GBP": "GBP_SONIA",
    "ILS": "ILS_SHIR",
    "JPY": "JPY_TONAR",
    "NOK": "NOK_NOWA",
    "NZD": "NZD_NZIONA",
    "SEK": "SEK_STINA",
    "SGD": "SGD_SORA",
    "THB": "THB_THOR",
    "USD": "USD_SOFR",
}

#: Beyond this the quote is not a basis spread in basis points; something else
#: (a decimal, a percentage, a price) has been handed to the builder.
_MAX_PLAUSIBLE_BP = 1000.0


# ------------------------------------------------------------------ #
#                        currency token helpers                      #
# ------------------------------------------------------------------ #


def iso_currency(token: str) -> str:
    """The ISO code inside a Citi XCCY currency token.

    ``"AUD_BBSW" -> "AUD"``, ``"USD" -> "USD"``.

    Parameters
    ----------
    token
        A Citi cross-currency leg token.

    Returns
    -------
    str
        The three-letter ISO code, upper-cased.
    """
    return str(token).strip().upper().split("_", 1)[0]


def default_spread_ccy(base_ccy: str, quote_ccy: str) -> str:
    """Which leg is assumed to carry the quoted basis spread.

    Market convention puts the basis on the **non-USD** leg of a USD pair. For a
    cross with no USD leg (``EUR/GBP``, ``NZD/AUD``) the convention is not
    universal and the base currency is used.

    Returns
    -------
    str
        ISO code of the currency assumed to carry the spread.

    Notes
    -----
    UNVERIFIED against Velocity. The harvest records ``BASE_LEG`` and
    ``SPREAD_LEG`` but not which currency either denotes.
    """
    a, b = iso_currency(base_ccy), iso_currency(quote_ccy)
    if a == "USD" and b != "USD":
        return b
    if b == "USD" and a != "USD":
        return a
    return a


def default_collateral_ccy(base_ccy: str, quote_ccy: str) -> str:
    """Which currency the swap is assumed collateralised in.

    USD for any pair containing USD, else the quote currency. The collateral
    currency's own OIS curve is taken as given; the other currency's discount
    curve is what the basis implies.
    """
    a, b = iso_currency(base_ccy), iso_currency(quote_ccy)
    if "USD" in (a, b):
        return "USD"
    return b


def ois_index_for_currency(ccy: str, *, ois_index: Optional[str] = None) -> str:
    """The Citi OIS index token for a cross-currency leg.

    Parameters
    ----------
    ccy
        A Citi XCCY currency token (``"EUR"``, ``"AUD_BBSW"``).
    ois_index
        Explicit override, e.g. ``"JPY_TONAR_LCH"``.

    Raises
    ------
    UnknownTagError
        The token is IBOR-indexed (``AUD_BBSW``, ``NZD_BKBM``) or has no OIS
        curve in :data:`PRIMARY_OIS_INDEX`.
    """
    token = str(ccy).strip().upper()
    if ois_index:
        return str(ois_index).strip().upper()
    if token in IBOR_LEG_TOKENS:
        raise UnknownTagError(
            f"{token} is a 3M IBOR-indexed cross-currency leg, not an OIS leg; this package's "
            "cross-currency builders construct RFR-OIS legs on both sides and would price it "
            f"wrongly. Use the RFR pair ({iso_currency(token)}) instead, or pass an explicit "
            "ois_index= and build the IBOR leg yourself."
        )
    iso = iso_currency(token)
    if iso not in PRIMARY_OIS_INDEX:
        raise UnknownTagError(
            f"No OIS index mapped for cross-currency leg {ccy!r}. Known: "
            f"{', '.join(sorted(PRIMARY_OIS_INDEX))}. Pass ois_index= to override."
        )
    return PRIMARY_OIS_INDEX[iso]


def assert_ois_pair(*tokens: str) -> None:
    """Raise unless every Citi leg token names an RFR-OIS leg.

    The guard the OIS-leg builders need, because :func:`iso_currency` is lossy in
    exactly the direction that matters: ``AUD_BBSW`` and ``NZD_BKBM`` both reduce
    to an ISO code that HAS an RFR spec (``AUD``, ``NZD``), so a strip carrying
    the IBOR token reaches a builder looking like a perfectly ordinary RFR pair.
    Checking the raw token before it is reduced is the only place the difference
    is still visible.

    Parameters
    ----------
    *tokens
        Citi cross-currency leg tokens, verbatim - e.g. ``basis.base_ccy`` and
        ``basis.quote_ccy``, NOT their ISO reductions.

    Raises
    ------
    UnknownTagError
        Naming the offending token and the RFR pair to use instead. See
        :func:`ois_index_for_currency`, which carries the message.
    """
    for token in tokens:
        ois_index_for_currency(token)


def conventions_for_currency(ccy: str, *, ois_index: Optional[str] = None) -> CurveConvention:
    """The :class:`CurveConvention` for one side of a cross-currency pair."""
    return conventions_for(ois_index_for_currency(ccy, ois_index=ois_index))


# ------------------------------------------------------------------ #
#                             the record                             #
# ------------------------------------------------------------------ #


@dataclass(frozen=True, eq=False)
class XccyBasisCurve:
    """One cross-currency basis strip: tenor -> basis spread in basis points.

    ``eq=False`` because the payload is a :class:`pandas.Series`; the generated
    ``__eq__`` would compare it elementwise and raise on truth-value ambiguity.

    Attributes
    ----------
    pair
        ``"<ccy1>/<ccy2>"`` using the Citi tokens verbatim, e.g. ``"EUR/USD"``.
    base_ccy, quote_ccy
        Citi's ``ccy1`` and ``ccy2`` tokens, verbatim (may be ``AUD_BBSW``).
    forward
        Forward-start token: ``"SPOT"``, ``"1Y"``, ...
    leg
        ``"SPREAD_LEG"`` or ``"BASE_LEG"`` - which Velocity leg was read.
    spreads
        Float series in **basis points**, indexed by tenor token, ascending in
        maturity.
    as_of
        Observation date the strip was reduced to, or ``None`` for "latest".
    spread_ccy
        ISO code of the currency whose leg is assumed to carry the spread. See
        :func:`default_spread_ccy` - this is an assumption, not an observation.
    tags
        ``{tenor: velocity_tag}`` provenance for every point.
    observed
        ``{tenor: date}`` - the actual timestamp each point was taken from,
        which is NOT necessarily ``as_of`` (a tenor can be stale).
    requested_tenors
        What the caller asked for, so :meth:`validate` can tell a ragged strip
        from a deliberately short one.
    """

    pair: str
    base_ccy: str
    quote_ccy: str
    forward: str
    leg: str
    spreads: pd.Series
    as_of: Optional[datetime.date]
    spread_ccy: str = ""
    tags: Mapping[str, str] = field(default_factory=dict)
    observed: Mapping[str, datetime.date] = field(default_factory=dict)
    requested_tenors: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.spread_ccy:
            object.__setattr__(
                self, "spread_ccy", default_spread_ccy(self.base_ccy, self.quote_ccy)
            )
        if not self.requested_tenors:
            object.__setattr__(self, "requested_tenors", tuple(self.spreads.index.astype(str)))

    # -- access ---------------------------------------------------------

    def tenors(self) -> list[str]:
        """Tenor tokens present, sorted by maturity rather than lexically."""
        return sort_tenors([str(t) for t in self.spreads.index])

    def at(self, tenor: str) -> float:
        """The basis spread in bp at one tenor.

        Raises
        ------
        CatalogError
            The tenor is not in the strip; the message lists what is.
        """
        token = str(tenor).strip().upper()
        if token not in self.spreads.index:
            raise CatalogError(
                f"{self.pair} basis has no {tenor!r} point. Present: {', '.join(self.tenors())}. "
                "Widen the tenors= argument to fetch_xccy_basis to add it."
            )
        return float(self.spreads.loc[token])

    def years(self) -> pd.Series:
        """Approximate year fraction per tenor, for plotting and interpolation."""
        idx = self.tenors()
        return pd.Series([tenor_years(t) for t in idx], index=idx, name="years")

    def to_frame(self) -> pd.DataFrame:
        """``tenor | years | spread_bp | observed | tag``, ascending in maturity."""
        idx = self.tenors()
        return pd.DataFrame(
            {
                "tenor": idx,
                "years": [tenor_years(t) for t in idx],
                "spread_bp": [float(self.spreads.loc[t]) for t in idx],
                "observed": [self.observed.get(t) for t in idx],
                "tag": [self.tags.get(t) for t in idx],
            }
        ).set_index("tenor")

    def __len__(self) -> int:
        return int(self.spreads.shape[0])

    def __repr__(self) -> str:  # pragma: no cover - display only
        return (
            f"<XccyBasisCurve {self.pair} {self.forward} {self.leg} "
            f"n={len(self)} spread_ccy={self.spread_ccy} as_of={self.as_of}>"
        )

    # -- integrity ------------------------------------------------------

    def validate(self, *, max_abs_bp: float = _MAX_PLAUSIBLE_BP) -> None:
        """Raise unless the strip is a usable basis curve.

        Checks, in order: non-empty; every requested tenor present; every value
        finite; every value within ``max_abs_bp`` of zero.

        Raises
        ------
        ValueError
            With the specific defect and the knob that fixes it. A ragged or
            all-NaN strip is never returned quietly - the repo has a recorded
            incident where a silently NULL risk column shipped as "success".
        """
        if len(self) == 0:
            raise ValueError(
                f"{self.pair} {self.forward} {self.leg}: the basis strip is EMPTY. Every requested "
                f"tenor failed or returned no rows ({len(self.requested_tenors)} requested). Check "
                "the pair exists in RATES.XCCY_OIS_SWAP and that the add-in is signed in."
            )
        missing = [t for t in self.requested_tenors if t not in self.spreads.index]
        if missing:
            raise ValueError(
                f"{self.pair} {self.forward} {self.leg}: basis strip is RAGGED - "
                f"{len(missing)} of {len(self.requested_tenors)} requested tenors returned no "
                f"data: {', '.join(missing)}. Either narrow tenors= to the ones that quote, or "
                "check the as_of date is a business day for both currencies."
            )
        bad = [t for t in self.spreads.index if not math.isfinite(float(self.spreads.loc[t]))]
        if bad:
            raise ValueError(
                f"{self.pair} {self.forward} {self.leg}: non-finite basis at {', '.join(bad)}. "
                "A NaN in a calibration input becomes a NaN curve, so it is refused here."
            )
        wild = [
            t
            for t in self.spreads.index
            if abs(float(self.spreads.loc[t])) > float(max_abs_bp)
        ]
        if wild:
            worst = max(abs(float(self.spreads.loc[t])) for t in wild)
            raise ValueError(
                f"{self.pair} {self.forward} {self.leg}: |basis| reaches {worst:.1f} at "
                f"{', '.join(wild)}, which is not a basis spread in basis points. Velocity's "
                "BASIS_SPREAD units are documented as bp but UNVERIFIED against live data - if "
                "this family in fact quotes in decimals, pass scale=1e4 to fetch_xccy_basis. "
                "Raise max_abs_bp= if the level is genuinely this wide."
            )


# ------------------------------------------------------------------ #
#                            construction                            #
# ------------------------------------------------------------------ #


def basis_from_quotes(
    *,
    quotes: Mapping[str, float] | pd.Series,
    ccy1: str,
    ccy2: str,
    as_of: Optional[datetime.date] = None,
    forward: str = "SPOT",
    leg: str = "SPREAD_LEG",
    spread_ccy: Optional[str] = None,
    scale: float = 1.0,
    sign: int = 1,
    tags: Optional[Mapping[str, str]] = None,
    observed: Optional[Mapping[str, datetime.date]] = None,
    requested_tenors: Optional[Sequence[str]] = None,
    validate: bool = True,
) -> XccyBasisCurve:
    """Build an :class:`XccyBasisCurve` from quotes already in hand.

    The offline path: use it for hand-entered strips, for replaying a cached
    frame, and for the synthetic curves in tests.

    Parameters
    ----------
    quotes
        ``{tenor: basis_bp}``. Tenor tokens are upper-cased; order is irrelevant.
    ccy1, ccy2
        Citi base and quote currency tokens.
    as_of
        Observation date recorded on the curve.
    forward, leg
        Recorded verbatim; ``leg`` is Velocity's ``SPREAD_LEG``/``BASE_LEG``.
    spread_ccy
        Override for which leg carries the spread. Defaults to
        :func:`default_spread_ccy`.
    scale
        Multiplier applied to every quote, for when the source is not in bp
        (``scale=1e4`` converts decimals).
    sign
        ``-1`` flips the whole strip, for when the source signs the basis the
        other way round.
    validate
        Run :meth:`XccyBasisCurve.validate` before returning. Leave True.

    Returns
    -------
    XccyBasisCurve

    Raises
    ------
    ValueError
        Empty input, or a strip that fails :meth:`XccyBasisCurve.validate`.
    """
    if int(sign) not in (1, -1):
        raise ValueError(f"sign must be +1 or -1, got {sign!r}.")
    raw = pd.Series(dict(quotes), dtype="float64") if not isinstance(quotes, pd.Series) else quotes.astype("float64")
    if raw.empty:
        raise ValueError(
            f"No quotes supplied for {ccy1}/{ccy2} {forward} {leg}. basis_from_quotes needs at "
            "least one tenor."
        )
    series = pd.Series(
        [float(v) * float(scale) * int(sign) for v in raw.to_numpy()],
        index=[str(t).strip().upper() for t in raw.index],
        dtype="float64",
        name=f"{iso_currency(ccy1)}{iso_currency(ccy2)}_basis_bp",
    )
    series = series[~series.index.duplicated(keep="last")]
    series = series.reindex(sort_tenors(list(series.index)))

    curve = XccyBasisCurve(
        pair=f"{str(ccy1).strip().upper()}/{str(ccy2).strip().upper()}",
        base_ccy=str(ccy1).strip().upper(),
        quote_ccy=str(ccy2).strip().upper(),
        forward=str(forward).strip().upper(),
        leg=str(leg).strip().upper(),
        spreads=series,
        as_of=as_of,
        spread_ccy=(str(spread_ccy).strip().upper() if spread_ccy else ""),
        tags=dict(tags or {}),
        observed=dict(observed or {}),
        requested_tenors=tuple(str(t).strip().upper() for t in (requested_tenors or series.index)),
    )
    if validate:
        curve.validate()
    return curve


def fetch_xccy_basis(
    *,
    client: Any,
    ccy1: str,
    ccy2: str,
    tenors: Optional[Sequence[str]] = None,
    forward: str = "SPOT",
    leg: str = "SPREAD_LEG",
    as_of: Optional[datetime.date] = None,
    cache: Optional[Any] = None,
    freq: str = "DAILY",
    price_point: str = "CLOSE",
    catalog: Optional[CitiVeloCatalog] = None,
    spread_ccy: Optional[str] = None,
    scale: float = 1.0,
    sign: int = 1,
    lookback_days: int = 10,
    validate: bool = True,
) -> XccyBasisCurve:
    """Read one cross-currency basis strip from Velocity, cache-first when given one.

    Every tenor is fetched in a single ``CVTSHIST`` batch (or a single cache
    read), then reduced to the last observation at or before ``as_of``.

    Parameters
    ----------
    client
        A :class:`~MDP.CitiVelocityExcel.com_client.CitiVelocityExcelClient` (or
        the fake from :mod:`MDP.CitiVelocityExcel.testing`). May be ``None`` when
        ``cache`` alone should serve the read.
    ccy1, ccy2
        Citi base and quote currency tokens.
    tenors
        Defaults to :data:`XCCY_TENORS`. The catalog walk stopped above the tenor
        level for this family, so ``catalog.options()`` is empty there and cannot
        supply the axis.
    forward
        ``"SPOT"`` or a forward-start token from the recorded axis.
    leg
        ``"SPREAD_LEG"`` (the quoted basis) or ``"BASE_LEG"``.
    as_of
        Reduce each series to its last value at or before this date. ``None``
        takes each series' last value.
    cache
        A :class:`~MDP.CitiVelocityExcel.cache.CitiVeloTagCache`. When given, the
        read is cached-then-live and ``client`` supplies only the missing spans.
    lookback_days
        How far back a point may be stale before it is dropped (and the strip
        therefore fails :meth:`XccyBasisCurve.validate` as ragged). Only applies
        when ``as_of`` is given.
    scale, sign
        See :func:`basis_from_quotes`.

    Returns
    -------
    XccyBasisCurve

    Raises
    ------
    ValueError
        The strip came back empty or ragged (see
        :meth:`XccyBasisCurve.validate`).
    """
    axis = [str(t).strip().upper() for t in (tenors if tenors is not None else XCCY_TENORS)]
    grid = cv_tags.xccy_basis_grid(
        ccy1, ccy2, tenors=axis, forward=forward, leg=leg, catalog=catalog
    )
    tag_list = [grid[t] for t in axis]

    start = None
    end = None
    if as_of is not None:
        end = datetime.datetime(as_of.year, as_of.month, as_of.day)
        start = end - datetime.timedelta(days=max(int(lookback_days), 1) * 3 + 30)

    if cache is not None:

        def _fetch_span(
            tags_: Sequence[str],
            freq_: str,
            start_: Optional[datetime.datetime],
            end_: Optional[datetime.datetime],
            point_: str,
        ) -> Mapping[str, pd.Series]:
            """Adapter matching :data:`MDP.CitiVelocityExcel.cache.Fetcher`."""
            return client.fetch_timeseries(
                tags_, freq_, start=start_, end=end_, price_point=point_
            )

        fetcher = _fetch_span if client is not None else None
        series_by_tag = cache.get(
            tag_list,
            freq,
            start=start,
            end=end,
            price_point=price_point,
            fetcher=fetcher,
        )
    else:
        if client is None:
            raise ValueError(
                "fetch_xccy_basis needs a client, a cache, or both; both were None. "
                "Use basis_from_quotes() for an offline strip."
            )
        series_by_tag = client.fetch_timeseries(
            tag_list, freq, start=start, end=end, price_point=price_point
        )

    quotes: Dict[str, float] = {}
    observed: Dict[str, datetime.date] = {}
    cutoff = None if as_of is None else pd.Timestamp(as_of) + pd.Timedelta(days=1)
    floor = (
        None
        if as_of is None
        else pd.Timestamp(as_of) - pd.Timedelta(days=int(lookback_days))
    )
    for tenor in axis:
        s = series_by_tag.get(grid[tenor])
        if s is None or len(s) == 0:
            continue
        s = s.dropna()
        if cutoff is not None:
            s = s[s.index < cutoff]
        if floor is not None:
            s = s[s.index >= floor]
        if s.empty:
            continue
        quotes[tenor] = float(s.iloc[-1])
        stamp = s.index[-1]
        observed[tenor] = stamp.date() if hasattr(stamp, "date") else stamp

    if not quotes:
        # Construct the empty strip so validate() can name the pair and the knobs,
        # rather than raising a bare "no data" from inside the fetch loop.
        empty = XccyBasisCurve(
            pair=f"{str(ccy1).strip().upper()}/{str(ccy2).strip().upper()}",
            base_ccy=str(ccy1).strip().upper(),
            quote_ccy=str(ccy2).strip().upper(),
            forward=str(forward).strip().upper(),
            leg=str(leg).strip().upper(),
            spreads=pd.Series(dtype="float64"),
            as_of=as_of,
            spread_ccy=(str(spread_ccy).strip().upper() if spread_ccy else ""),
            tags=grid,
            observed={},
            requested_tenors=tuple(axis),
        )
        if validate:
            empty.validate()
        return empty

    _logger.debug(
        "fetch_xccy_basis %s/%s %s %s: %d/%d tenors", ccy1, ccy2, forward, leg, len(quotes), len(axis)
    )
    return basis_from_quotes(
        quotes=quotes,
        ccy1=ccy1,
        ccy2=ccy2,
        as_of=as_of,
        forward=forward,
        leg=leg,
        spread_ccy=spread_ccy,
        scale=scale,
        sign=sign,
        tags=grid,
        observed=observed,
        requested_tenors=axis,
        validate=validate,
    )
