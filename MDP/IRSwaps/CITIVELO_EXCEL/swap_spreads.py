r"""Citi Velocity's PUBLISHED swap spread, ``RATES.OIS.<index>.SWAP_SPREAD.<tenor>``.

This is a **quoted number Citi disseminates**, not something this repo computes.
The repo already has two computed swap spreads (``IRSwapValue.MMSS`` and
``IRSwapValue.SPREADOVER``, both built by ``MDP/IRSwapSpreads/IRSwapSpreadsMDP.py``
out of a swap curve and a UST bond pricer); Citi's is a third, independent number
that will not agree with either. The full comparison - what each is a spread
between, what each is built from, the sign convention and why they disagree - is
written out on
:meth:`~Query.IRSwaps.IRSwapValue.IRSwapValueFunctionMap._citivelo_swap_spread`,
next to the enum members it has to be told apart from. Read that before using
this.

The tenor axis is per index and is NOT the par grid
---------------------------------------------------
``PAR`` serves 44 tenors for every index. ``SWAP_SPREAD`` serves a small, ragged,
per-index subset that includes MONEY-MARKET tenors and omits obvious swap ones.
From the harvested DAG catalog (``catalog/dag_rates_deep.json``), 13 of the 20 OIS
indices carry a ``SWAP_SPREAD`` sub-type at all, and their axes differ:

==================  ==  =========================================================
index                n  tenors
==================  ==  =========================================================
``USD_SOFR``        11  1M 3M 6M 1Y 2Y 3Y 5Y 7Y 10Y 20Y 30Y
``USD_FEDFUND``     11  1M 3M 6M 1Y 2Y 3Y 5Y 7Y 10Y 20Y 30Y
``JPY_TONAR``       12  3M 6M 1Y 2Y 3Y 5Y 7Y 10Y 15Y 20Y 30Y 40Y
``JPY_TONAR_JSCC``  12  3M 6M 1Y 2Y 3Y 5Y 7Y 10Y 15Y 20Y 30Y 40Y
``JPY_TONAR_LCH``   12  3M 6M 1Y 2Y 3Y 5Y 7Y 10Y 15Y 20Y 30Y 40Y
``GBP_SONIA``       10  2Y 3Y 5Y 7Y 10Y 15Y 20Y 30Y 40Y 50Y
``AUD_AONIA``        7  2Y 3Y 5Y 7Y 10Y 20Y 30Y
``NZD_NZIONA``       5  2Y 5Y 7Y 10Y 20Y
``CAD_CORRA``        4  2Y 5Y 10Y 30Y
``CHF_SARON``        4  2Y 5Y 10Y 30Y
``DKK_TNDKK``        4  2Y 5Y 10Y 30Y
``SEK_STINA``        4  2Y 5Y 10Y 30Y
``NOK_NOWA``         3  2Y 5Y 10Y
==================  ==  =========================================================

Read off the committed catalog on 2026-08-08 and pinned by
``tests/test_citivelo_swap_spread.py`` - the counts AND the membership - because a
table nobody checks goes stale and then gets believed.

``EUR_EUROSTR`` has **no** ``SWAP_SPREAD`` sub-type, and neither do ``ILS_SHIR``,
``MXN_T_FONDEO``, ``SGD_SORA``, ``THB_THOR``, ``ZAR_ZARONIA``, ``EUR_EONIA``.

So there is no "the eleven tenors": USD happens to have eleven, GBP has ten and a
*different* ten (no 1M/3M/6M/1Y, but 15Y/40Y/50Y). :func:`swap_spread_tenors`
reads the axis from the catalog per index. Nothing here re-spells
``tags.SWAP_SPREAD_LIQUID_TENORS`` - that tuple is the USD axis under a generic
name, and using it for GBP would ask for four tenors that do not exist and miss
three that do.

Only the USD axis has been measured to SERVE
--------------------------------------------
The table above is what the catalog RECORDS. What ``CVTSHIST`` actually serves has
been measured for ``USD_SOFR`` only - 11 of 11 tenors, ``MDP/CitiVelocityExcel/
README.md:415``, a prior session. For the other twelve indices the axis is
catalog-recorded and **never observed to serve**; ``tags.py`` makes the same
distinction ("only ``SWAP_SPREAD_LIQUID_TENORS`` are known to serve") and it is
carried over here rather than quietly dropped. That matters because
:func:`fetch_swap_spreads` RAISES on the first tenor that returns nothing, so one
unserved tenor takes a whole-axis batch down: off USD, pass an explicit tenor list
or use :func:`swap_spread_history`, whose absent tenors are absent columns.

``CVMETADATA`` is unsound for this family
-----------------------------------------
It reports **zero** valid tenors for ``SWAP_SPREAD`` while ``CVTSHIST`` serves the
USD axis, and ``RATES.OIS.USD_SOFR.SWAP_SPREAD.10Y`` hard-fails an entire
``CVMETADATA`` batch to ``#VALUE!`` even when probed alone - see
``MDP/CitiVelocityExcel/testing.py`` (``poison_metadata_tags``), which reproduces
that behaviour because the client has to survive it. **Never call
``quotes.metadata()`` on this family.** Validate with
:meth:`CitiVeloQuotes.validate`, which goes through ``CVTSHIST`` with known-good
control tags in front.

Units: served exactly as published, unscaled, and UNVERIFIED
------------------------------------------------------------
Nothing here multiplies or divides the served number. As of 2026-08-08 **zero
``SWAP_SPREAD`` tags are cached and Excel was unavailable**, so whether Citi
publishes basis points (``-64.2``) or a decimal/percent form (``-0.642``) has not
been measured and is not asserted. The discriminator is pure magnitude - a USD
10Y swap spread is tens of basis points, so ``|x| > 1`` is bp and ``|x| < 1`` is
not - and the check that settles it is ``scripts/citivelo_swap_spread_tieout.py``,
which fetches the axis and prints Citi's raw level beside the repo's computed
``SPREADOVER`` in bp. :data:`UNIT` records the current state as the string
``"as_published"`` so a downstream consumer cannot mistake an assumption for a
measurement; when the tie-out has run, change it to ``"bp"`` and say where.

The three modes are the curve source's three modes
---------------------------------------------------
Mode dispatch is :func:`~MDP.IRSwaps.CITIVELO_EXCEL.timestamps.resolve_request` -
the same function ``fetcher.py`` uses, not a fourth copy of it. A bare
``datetime.date`` (or a midnight ``pandas.Timestamp``) is EOD and reads the
``DAILY`` series; a ``datetime`` with a time is intraday and reads ``MI01``;
``"live"`` is ``MI01`` bounded above by now. The frequency table and the lookback
windows are **imported** from ``fetcher.py`` rather than restated, because two
copies of "MI01 looks back 5 days" is exactly how one of them ends up past the
6-day downsampling cliff without anybody noticing.

The axis is SPOT-starting, and Citi does not say so
----------------------------------------------------
The tenor segment of ``RATES.OIS.<index>.SWAP_SPREAD.<tenor>`` is a MATURITY, the
same way ``PAR``'s is; a forward start would be a ``(forward, tenor)`` pair, which
is what the separate ``FWD`` sub-type carries and which has no swap-spread
analogue. Nothing in the tag, the catalog or the returned number says this, so
:func:`swap_spread_for_curve` checks it: a package whose effective date is more
than :data:`MAX_SPOT_START_LAG` away from the curve's own as-of raises
:class:`SpotStartRequiredError` rather than returning the spot quote for a forward
trade. Without that check a 5Yx5Y forward derives tenor ``5Y`` from
``maturity - effective`` and reads the SPOT 5Y number, byte-identical to the spot
answer - the residual against the swap's own forward rate is then the entire
forward/spot spread.
"""

from __future__ import annotations

import datetime
import logging
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.catalog import CitiVeloCatalog, sort_tenors
from MDP.CitiVelocityExcel.errors import UnknownTagError
from MDP.IRSwaps.CITIVELO_EXCEL.fetcher import (
    DEFAULT_MAX_EOD_GAP,
    DEFAULT_MAX_STALENESS,
    StaleCurveError,
    _FREQ,
    _LOOKBACK,
)
from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import (
    ResolvedRequest,
    from_wire_naive,
    resolve_request,
    to_wire_naive,
    wire_timezone,
)

__all__ = [
    "FREQ_BY_MODE",
    "LOOKBACK_BY_MODE",
    "MAX_SPOT_START_LAG",
    "SOURCE_TOKEN",
    "UNIT",
    "SpotStartRequiredError",
    "SwapSpreadQuote",
    "SwapSpreadUnavailableError",
    "indices_with_swap_spread",
    "swap_spread_for_curve",
    "swap_spread_history",
    "swap_spread_tag",
    "swap_spread_tenors",
    "fetch_swap_spread",
    "fetch_swap_spreads",
    "tenor_for_swap",
]

_logger = logging.getLogger(__name__)

#: Frequency and lookback per resolved mode. Imported from ``fetcher.py`` on
#: purpose - see the module docstring. ``tests/test_citivelo_swap_spread.py``
#: pins them equal so a future divergence is a test failure, not a silent one.
FREQ_BY_MODE: Mapping[str, str] = _FREQ
LOOKBACK_BY_MODE: Mapping[str, datetime.timedelta] = _LOOKBACK

#: What ``meta_data["source"]`` must say for a curve to be able to serve this.
SOURCE_TOKEN = "citivelo_excel"

#: The unit of the number this module returns. **BASIS POINTS**, measured
#: 2026-08-08 over 2026-07-08..08-07 (23 daily observations per tenor) and no
#: longer assumed: USD_SOFR reads 10Y -41.78, 30Y -75.11, 2Y -14.56 as published,
#: which is the right magnitude, sign and term structure for USD swap spreads and
#: is three orders of magnitude away from a decimal reading.
#:
#: Cross-checked against the repo's independently computed ``SPREADOVER`` for the
#: same days and tenors: median difference **-0.0015 to +0.39 bp** across 2Y, 3Y,
#: 5Y, 7Y, 10Y, 20Y and 30Y (2Y +0.036, 3Y +0.386, 5Y +0.015, 7Y +0.067,
#: 10Y -0.002, 20Y -0.069, 30Y -0.156). Two different constructions from two
#: different data sources landing sub-basis-point on six of seven tenors is what
#: makes the unit settled rather than merely plausible.
#:
#: The MEAN difference over the same days is ~150,000 bp and is meaningless: the
#: repo's ``SPREADOVER`` failed to price on 9 of 23 days and returns values like
#: -151,276 bp when it does, which no mean survives. That is a repo-side gap, not
#: a disagreement with Citi. Quote the median; the raw per-day series is in
#: ``harvest/swap_spread_tieout/USD_SOFR_tieout_SPREADOVER.json``.
#:
#: STILL NOT MEASURED off USD: no other index's axis has been fetched.
UNIT = "bp"

#: Which Citi sub-type carries the published spread.
SUB_TYPE = "SWAP_SPREAD"

#: How far after a curve's own as-of date a SPOT effective date may land.
#:
#: Spot for these curves is T+2 business days: 4 calendar days across an ordinary
#: weekend, and 6 in the worst holiday case (a Thursday as-of with the Friday and
#: the following Monday both closed). Ten days is the widest slack that still
#: refuses the shortest forward start anybody puts on this value - a 1M forward is
#: 28-31 days out - so the tolerance ADMITS a forward inside ten days and refuses
#: everything from 1M up. That trade-off is deliberate: the alternative is
#: rebuilding each curve's settlement calendar here to reproduce a date the curve
#: already knows, and getting the calendar wrong would refuse legitimate spot
#: trades on exactly the illiquid dates nobody would check.
MAX_SPOT_START_LAG = datetime.timedelta(days=10)


class SwapSpreadUnavailableError(RuntimeError):
    """Citi served no ``SWAP_SPREAD`` quote at or before the requested instant.

    Distinct from :class:`~MDP.IRSwaps.CITIVELO_EXCEL.fetcher.SparseCurveError`,
    which is about a curve built from too few tenors. Here there is exactly one
    tag and it returned nothing.
    """


class SpotStartRequiredError(NotImplementedError):
    """The swap does not start spot, and Citi's published axis does.

    ``RATES.OIS.<index>.SWAP_SPREAD.<tenor>`` indexes a MATURITY, not a
    ``(forward, tenor)`` pair. Serving it for a forward-starting or already-running
    swap returns a real, current, correctly-fetched number **for a different
    trade**, which is why this refuses rather than warns: a wrong number that
    arrives with a warning still ends up in the frame.

    Subclasses :class:`NotImplementedError` so it lands with the multi-leg refusal
    for a caller that already handles one - both are "Citi does not publish this",
    not "the fetch went wrong".
    """


# ------------------------------------------------------------------ #
#                          the tenor axis                            #
# ------------------------------------------------------------------ #


def indices_with_swap_spread(*, catalog: Optional[CitiVeloCatalog] = None) -> Tuple[str, ...]:
    """Every OIS index whose catalog node carries a ``SWAP_SPREAD`` sub-type.

    Read from the catalog, not listed here, because the answer is a property of
    the harvest. Measured on the committed catalog 2026-08-08: 13 of the 20
    indices, and ``EUR_EUROSTR`` is not one of them.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    out: List[str] = []
    for index in cat.options("RATES.OIS"):
        if SUB_TYPE in cat.options(f"RATES.OIS.{index}"):
            out.append(index)
    return tuple(out)


def swap_spread_tenors(
    citi_index: str, *, catalog: Optional[CitiVeloCatalog] = None
) -> Tuple[str, ...]:
    """The tenors this index's ``SWAP_SPREAD`` axis actually carries, in order.

    Raises
    ------
    UnknownTagError
        When ``citi_index`` is not a Citi OIS index, when it has no
        ``SWAP_SPREAD`` sub-type, or when the sub-type node exists with no
        recorded children.

    Notes
    -----
    The last case is the one worth guarding. ``tags.ois()`` validates trailing
    segments with ``allow_unrecorded=True`` - correct in general, because the
    Function Builder walk was depth-capped and our ignorance is not the add-in's
    - but it means a node with an EMPTY option list accepts any string. For this
    family that would turn a typo into a tag that fails silently at the add-in
    instead of raising here, so an empty axis is refused rather than trusted.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    # Round-trips the index and sub-type through the shared builder, so the
    # spelling rules (and their error messages) stay in one place.
    node = T.ois(citi_index, SUB_TYPE, catalog=cat)
    axis = cat.options(node)
    if not axis:
        raise UnknownTagError(
            f"{node!r} has no recorded tenors, so nothing can be validated against it. "
            f"Indices whose SWAP_SPREAD axis IS recorded: "
            f"{', '.join(indices_with_swap_spread(catalog=cat))}."
        )
    return tuple(sort_tenors(axis))


def swap_spread_tag(
    citi_index: str, tenor: str, *, catalog: Optional[CitiVeloCatalog] = None
) -> str:
    """``RATES.OIS.<index>.SWAP_SPREAD.<tenor>``, with the tenor checked first.

    Raises
    ------
    UnknownTagError
        Naming the accepted axis in full. It is short (3-12 entries) and ragged
        per index, so printing it is worth more than a "did you mean" - a caller
        asking USD for ``4Y``, ``15Y`` or ``25Y`` is not making a typo, they are
        assuming the 44-tenor ``PAR`` grid, and the message has to say so.

    Notes
    -----
    The membership test below overlaps ``tags._pick``, which would also reject an
    off-axis tenor whenever the node has recorded children. That overlap is
    deliberate and is kept for one reason: the message. ``_pick``'s is a generic
    "Unknown segment"; the caller's actual mistake here is almost always the
    assumption that this family shares ``PAR``'s 44-tenor axis, and naming that
    assumption is the difference between a two-minute fix and an hour.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    axis = swap_spread_tenors(citi_index, catalog=cat)
    token = str(tenor).strip().upper()
    if token not in axis:
        node = T.ois(citi_index, SUB_TYPE, catalog=cat)
        raise UnknownTagError(
            f"Unknown SWAP_SPREAD tenor {tenor!r} under {node}. "
            f"Accepted: {', '.join(axis)}. Citi's SWAP_SPREAD axis is a small "
            "per-index subset and is NOT the 44-tenor PAR grid."
        )
    return T.ois_swap_spread(citi_index, token, catalog=cat)


# ------------------------------------------------------------------ #
#                             the quote                              #
# ------------------------------------------------------------------ #


@dataclass(frozen=True)
class SwapSpreadQuote:
    """One published ``SWAP_SPREAD`` print, with everything needed to judge it.

    Attributes
    ----------
    value
        The number Citi served, **unscaled**. See :data:`UNIT`.
    quoted_at
        Tz-aware, in the wire zone: when the print this value came from is
        stamped.
    requested_at
        Tz-aware: the instant asked for. ``None`` in live mode.
    lag
        ``requested_at`` (or now, in live mode) minus ``quoted_at``. Positive.
    """

    citi_index: str
    tenor: str
    tag: str
    mode: str
    freq: str
    value: float
    unit: str
    quoted_at: datetime.datetime
    requested_at: Optional[datetime.datetime]
    lag: datetime.timedelta
    n_rows_fetched: int = 0

    def describe(self) -> str:
        return (
            f"{self.citi_index} SWAP_SPREAD {self.tenor} {self.mode} = {self.value} "
            f"({self.unit}) @ {self.quoted_at:%Y-%m-%d %H:%M:%S %Z}, lag "
            f"{self.lag.total_seconds() / 60:.1f} min"
        )

    def to_meta(self) -> Dict[str, Any]:
        return {
            "source": SOURCE_TOKEN,
            "family": f"RATES.OIS.{self.citi_index}.{SUB_TYPE}",
            "tag": self.tag,
            "tenor": self.tenor,
            "mode": self.mode,
            "freq": self.freq,
            "unit": self.unit,
            "quoted_at": self.quoted_at.isoformat(),
            "requested_at": None if self.requested_at is None else self.requested_at.isoformat(),
            "lag_seconds": self.lag.total_seconds(),
            "wire_timezone": wire_timezone().key,
        }


def _default_quotes(*, offline: bool, client_kwargs: Optional[Mapping[str, Any]]) -> Any:
    from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

    return CitiVeloQuotes(offline=offline, client_kwargs=dict(client_kwargs or {}))


def _close_quietly(quotes: Any, *, subject: str) -> None:
    """Close a lazily-built quotes object without letting a teardown mask a result.

    Swallowing is right - the quote is already in hand and re-raising here would
    throw away a good number for a bad goodbye - but swallowing SILENTLY is not:
    a ``close()`` that failed because the add-in wedged mid-drain left no trace
    anywhere, and the next call reconnected into an Excel that had already broken
    once. Logged at WARNING with the traceback, which is the only record there is.
    """
    try:
        quotes.close()
    except Exception:  # noqa: BLE001 - a close failure must not mask the result
        _logger.warning(
            "citivelo_excel: closing the quotes built for %s failed; the quote itself is "
            "unaffected, but this Excel session has already misbehaved once.",
            subject,
            exc_info=True,
        )


def _warn_if_running_session(day: datetime.date, *, subject: str, stacklevel: int = 3) -> None:
    """Warn when ``day`` is today: Citi's DAILY row for today is not a close.

    Carried over from ``CitiVeloExcelCurveFetcher._resolve`` (fetcher.py:355-366),
    which raises the same warning for the same reason and was measured on
    2026-08-07: the DAILY series already carried a row stamped 2026-08-07 00:00 at
    10:47 ET, i.e. mid-session. It is the running level, not a settled close, and
    labelling it ``eod`` without saying so is stale-data-served-as-final in its
    other direction.
    """
    today = datetime.datetime.now(wire_timezone()).date()
    if day < today:
        return
    when = "TODAY" if day == today else f"in the FUTURE (today is {today})"
    warnings.warn(
        f"citivelo_excel: {subject} dated {day} is {when}. Citi's daily series carries a row "
        "for the current, incomplete session, so that row is the running level rather than a "
        "settled close. Ask for the previous business day, or use an intraday/live request if "
        "the running level is what you meant.",
        stacklevel=stacklevel,
    )


def _window(request: ResolvedRequest) -> Tuple[datetime.datetime, datetime.datetime]:
    """The naive wire-zone ``[start, end]`` to ask ``CVTSHIST`` for.

    Identical in shape to ``CitiVeloExcelCurveFetcher._fetch_window``, including
    bounding live ABOVE by now: an unbounded end lets a clock skew on the add-in
    side hand back a future stamp, which then reads as a negative lag.
    """
    lookback = LOOKBACK_BY_MODE[request.mode]
    if request.mode == "eod":
        end = datetime.datetime.combine(request.eod_date, datetime.time(23, 59, 59))
    elif request.mode == "intraday":
        end = request.wire_instant
    else:
        end = datetime.datetime.now(wire_timezone()).replace(tzinfo=None)
    return end - lookback, end


def _targets(
    request: ResolvedRequest,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """``(asof_target, lag_origin)`` for a resolved request.

    The EOD search runs to the END of the requested day but the lag is measured
    from its START, because Citi stamps daily rows at midnight - measuring against
    23:59:59 would make every EOD quote look 24 h stale. Same rule as the curve
    fetcher, for the same reason.
    """
    if request.mode == "live":
        return None, None
    if request.mode == "intraday":
        target = pd.Timestamp(request.wire_instant)
        return target, target
    return (
        pd.Timestamp(datetime.datetime.combine(request.eod_date, datetime.time(23, 59, 59))),
        pd.Timestamp(datetime.datetime.combine(request.eod_date, datetime.time())),
    )


def _limit_for(request: ResolvedRequest) -> Optional[datetime.timedelta]:
    return DEFAULT_MAX_EOD_GAP if request.mode == "eod" else DEFAULT_MAX_STALENESS


def _resolve_one(
    *,
    citi_index: str,
    tenor: str,
    tag: str,
    request: ResolvedRequest,
    frame: pd.DataFrame,
    max_staleness: Optional[datetime.timedelta],
) -> SwapSpreadQuote:
    freq = FREQ_BY_MODE[request.mode]
    if frame is None or frame.empty or tag not in frame.columns:
        raise SwapSpreadUnavailableError(
            f"citivelo_excel: no {freq} rows for {tag} in the window ending "
            f"{request.describe()}. CVMETADATA cannot be used to check this family "
            "(it reports zero valid tenors and poisons its own batch); validate with "
            "CitiVeloQuotes.validate, which goes through CVTSHIST with controls."
        )

    target, lag_from = _targets(request)
    series = frame[tag].dropna()
    if target is not None:
        series = series[series.index <= target]
    if series.empty:
        raise SwapSpreadUnavailableError(
            f"citivelo_excel: {tag} has no {freq} print at or before {request.describe()} "
            f"(the fetched window holds {len(frame)} row(s))."
        )

    quoted_at = from_wire_naive(series.index[-1])
    now = datetime.datetime.now(wire_timezone())
    lag = (from_wire_naive(lag_from) if lag_from is not None else now) - quoted_at

    if max_staleness is not None and lag > max_staleness:
        unit, size, limit = (
            ("d", lag.total_seconds() / 86_400, max_staleness.total_seconds() / 86_400)
            if request.mode == "eod"
            else ("h", lag.total_seconds() / 3600, max_staleness.total_seconds() / 3600)
        )
        raise StaleCurveError(
            f"citivelo_excel: the newest {tag} print at or before {request.describe()} is "
            f"{quoted_at:%Y-%m-%d %H:%M:%S %Z}, which is {size:.1f} {unit} stale against a "
            f"limit of {limit:.1f} {unit}. An as-of search is backward and unbounded, so "
            "serving this would have looked like a current quote."
        )

    return SwapSpreadQuote(
        citi_index=citi_index,
        tenor=tenor,
        tag=tag,
        mode=request.mode,
        freq=freq,
        value=float(series.iloc[-1]),
        unit=UNIT,
        quoted_at=quoted_at,
        requested_at=None if target is None else from_wire_naive(target),
        lag=lag,
        n_rows_fetched=int(len(frame)),
    )


def fetch_swap_spreads(
    citi_index: str,
    tenors: Optional[Sequence[str]] = None,
    timestamp: Union[str, datetime.date, datetime.datetime, pd.Timestamp, None] = "live",
    *,
    quotes: Any = None,
    offline: bool = False,
    catalog: Optional[CitiVeloCatalog] = None,
    strict_tz: Optional[bool] = None,
    force_refresh: bool = False,
    max_staleness: Optional[datetime.timedelta] = ...,  # type: ignore[assignment]
    client_kwargs: Optional[Mapping[str, Any]] = None,
    _request: Optional[ResolvedRequest] = None,
) -> Dict[str, SwapSpreadQuote]:
    """``{tenor: SwapSpreadQuote}`` for one index at one instant.

    ``tenors=None`` asks for the whole recorded axis. Every tenor goes out in ONE
    ``CVTSHIST`` call - the batching is the point, and a per-tenor loop would be
    eleven round trips through the add-in for USD.

    A tenor that served nothing **raises** rather than being quietly omitted from
    the returned dict. A short dict is how a caller concludes Citi stopped
    publishing 1M when the real cause was a five-minute window; pass an explicit
    ``tenors`` list to ask only for what is wanted, or use
    :func:`swap_spread_history`, which is a frame and reports absence as a
    missing column.

    Parameters
    ----------
    timestamp
        ``"live"``, a bare date (EOD), or a datetime (intraday). Classified by
        :func:`~MDP.IRSwaps.CITIVELO_EXCEL.timestamps.resolve_request`, so a
        midnight ``pandas.Timestamp`` is EOD.
    quotes
        A :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes` (or anything with
        the same ``frame`` method). Built lazily when omitted; injectable is what
        lets this be tested with no Excel at all.
    max_staleness
        Default is the curve source's: 7 days for EOD, 12 hours otherwise. Pass
        ``None`` to disable, knowingly.
    _request
        Internal. A pre-resolved request, used by :func:`swap_spread_for_curve`
        so the mode is taken from the curve's metadata rather than re-dispatched.
    """
    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    axis = swap_spread_tenors(citi_index, catalog=cat)
    wanted = [str(t).strip().upper() for t in (tenors if tenors is not None else axis)]
    if not wanted:
        raise ValueError("fetch_swap_spreads: no tenors requested.")
    tag_by_tenor = {t: swap_spread_tag(citi_index, t, catalog=cat) for t in wanted}
    # ``swap_spread_tag`` normalises the index spelling; take it from a built tag
    # so the quote records what was actually asked for.
    resolved_index = next(iter(tag_by_tenor.values())).split(".")[2]

    request = _request if _request is not None else resolve_request(timestamp, strict=strict_tz)
    limit = _limit_for(request) if max_staleness is ... else max_staleness

    if request.mode == "eod":
        _warn_if_running_session(
            request.eod_date, subject=f"{resolved_index} SWAP_SPREAD EOD", stacklevel=4
        )

    owns = quotes is None
    if owns:
        quotes = _default_quotes(offline=offline, client_kwargs=client_kwargs)
    try:
        start, end = _window(request)
        frame = quotes.frame(
            list(tag_by_tenor.values()),
            FREQ_BY_MODE[request.mode],
            start=start,
            end=end,
            force_refresh=force_refresh,
        )
    finally:
        if owns:
            _close_quietly(quotes, subject=f"{resolved_index} SWAP_SPREAD {request.describe()}")

    return {
        tenor: _resolve_one(
            citi_index=resolved_index,
            tenor=tenor,
            tag=tag,
            request=request,
            frame=frame,
            max_staleness=limit,
        )
        for tenor, tag in tag_by_tenor.items()
    }


def fetch_swap_spread(
    citi_index: str,
    tenor: str,
    timestamp: Union[str, datetime.date, datetime.datetime, pd.Timestamp, None] = "live",
    **kwargs: Any,
) -> SwapSpreadQuote:
    """One published spread. Thin wrapper over :func:`fetch_swap_spreads`."""
    return fetch_swap_spreads(citi_index, [tenor], timestamp, **kwargs)[str(tenor).strip().upper()]


def swap_spread_history(
    citi_index: str,
    tenors: Optional[Sequence[str]] = None,
    *,
    start: datetime.date,
    end: datetime.date,
    freq: str = "DAILY",
    quotes: Any = None,
    offline: bool = False,
    catalog: Optional[CitiVeloCatalog] = None,
    force_refresh: bool = False,
    client_kwargs: Optional[Mapping[str, Any]] = None,
) -> pd.DataFrame:
    """A ``DAILY`` history of the axis, columns named by TENOR rather than by tag.

    ``DAILY`` only, and that is a guard rather than a limitation. ``CVTSHIST``
    silently downsamples an ``MI01`` request whose SPAN exceeds six days - the
    block looks identical either way - so a naive intraday range read here would
    return ten-minute data labelled as one-minute. The chunking-and-verifying
    route is ``MDP.CitiVelocityExcel.windowed.fetch_windowed``, which needs a
    connected client; ask for it there, explicitly.

    Returns
    -------
    pandas.DataFrame
        Tenor-named columns, and **a tenor that served nothing has no column** -
        including when nothing served at all, which returns a frame with no
        columns rather than the requested tenors as zero-row ones. Column
        presence is therefore a usable coverage test on every path.

    Warns
    -----
    UserWarning
        When ``end`` is today. Citi's DAILY series carries a row for the current,
        incomplete session, so the last row of the returned frame is a running
        level rather than a settled close.
    """
    token = str(freq).strip().upper()
    if token != "DAILY":
        raise ValueError(
            f"swap_spread_history serves DAILY only, not {freq!r}. CVTSHIST downsamples an "
            "MI01 request spanning more than 6 days without saying so; use "
            "MDP.CitiVelocityExcel.windowed.fetch_windowed for an intraday RANGE, or "
            "fetch_swap_spreads() for an intraday POINT."
        )

    cat = catalog if catalog is not None else CitiVeloCatalog.default()
    axis = swap_spread_tenors(citi_index, catalog=cat)
    wanted = [str(t).strip().upper() for t in (tenors if tenors is not None else axis)]
    tag_by_tenor = {t: swap_spread_tag(citi_index, t, catalog=cat) for t in wanted}
    _warn_if_running_session(
        pd.Timestamp(end).date(), subject=f"{citi_index} SWAP_SPREAD history end", stacklevel=3
    )

    owns = quotes is None
    if owns:
        quotes = _default_quotes(offline=offline, client_kwargs=client_kwargs)
    try:
        frame = quotes.frame(
            list(tag_by_tenor.values()),
            "DAILY",
            start=start,
            end=end,
            force_refresh=force_refresh,
        )
    finally:
        if owns:
            _close_quietly(quotes, subject=f"{citi_index} SWAP_SPREAD {start}..{end}")

    if frame is None or frame.empty:
        # NO columns, deliberately. This function is what ``fetch_swap_spreads``
        # points at *because* absence reads as a missing column, and returning
        # every requested tenor as a zero-row column contradicts that at exactly
        # the moment it matters: ``scripts/daily_cache_warmer.py`` logs
        # ``len(frame.columns)`` as "served N/M tenors" and would have reported
        # "served 11/11" for a window that served nothing at all.
        return pd.DataFrame(index=pd.DatetimeIndex([], name="Date"), dtype=float)
    tag_to_tenor = {tag: tenor for tenor, tag in tag_by_tenor.items()}
    out = frame.rename(columns=tag_to_tenor)
    return out[[t for t in wanted if t in out.columns]]


# ------------------------------------------------------------------ #
#                        the value-map entry point                   #
# ------------------------------------------------------------------ #

#: Roughly a month, in days. Used only to turn a swap's own effective/maturity
#: dates back into a tenor token; a tenor the caller states explicitly never
#: touches this.
_DAYS_PER_MONTH = 365.25 / 12.0


def tenor_for_swap(curve: Any, swap: Any) -> str:
    """The tenor token a swap's own dates imply, e.g. ``10Y`` or ``3M``.

    Derived from ``curve.maturity_date(swap) - curve.effective_date(swap)`` and
    rounded to whole months, then spelled in years when it is a whole number of
    them. Checked at both ends of the USD axis: a 1M swap is 28-31 days ->
    0.92-1.02 months -> ``1M``; a 30Y swap is 10,957 days -> 359.98 months ->
    ``30Y``. It is a derivation, not a lookup, so a caller who knows the tenor
    should pass it - see ``value_kwargs={"tenor": ...}``.

    This is a DURATION, and it says nothing about the start. A 5Yx5Y forward and a
    spot 5Y both come back ``5Y``; an already-running 10Y comes back ``10Y`` and
    not its remaining 8Y. Citi's axis is spot-starting, so the start is checked
    separately by :func:`_assert_spot_starting`, which is called from
    :func:`swap_spread_for_curve` where the curve's own as-of date is known.
    """
    effective = curve.effective_date(swap)
    maturity = curve.maturity_date(swap)
    days = (maturity - effective).days
    if days <= 0:
        raise ValueError(
            f"citivelo_excel: cannot derive a tenor from a swap whose maturity {maturity} "
            f"is not after its effective date {effective}."
        )
    months = int(round(days / _DAYS_PER_MONTH))
    if months <= 0:
        raise ValueError(
            f"citivelo_excel: a {days}-day swap is shorter than the finest tenor Citi "
            "publishes a swap spread for."
        )
    return f"{months // 12}Y" if months % 12 == 0 else f"{months}M"


def _as_of_date(request: ResolvedRequest) -> datetime.date:
    """The calendar day the curve is priced on, whichever mode resolved it."""
    if request.mode == "eod":
        return request.eod_date
    return request.wire_instant.date()


def _assert_spot_starting(*, curve: Any, swap: Any, request: ResolvedRequest, citi_index: str) -> None:
    """Refuse a swap that does not start spot. See :class:`SpotStartRequiredError`.

    Measured against the curve's OWN as-of date, not against today: an EOD curve
    for 2026-08-06 is priced spot off 2026-08-06 whenever it is asked for, and
    comparing to the wall clock would refuse every historical point in a
    timeseries. ``TB/IRSwapsTB.py:124`` rebuilds the package from the curve at each
    reference date, so the effective date moves with the curve and this stays a
    per-date property rather than a refusal wall.

    The tolerance is asymmetric on purpose: ``+MAX_SPOT_START_LAG`` forward, but
    only one day backward. A spot start is never BEFORE the as-of date, so the
    backward side needs no calendar slack at all - the single day is there for the
    one case that produces it legitimately, an intraday request whose wire-zone
    instant has rolled past midnight relative to the date the package was built
    on. Anything further back is a seasoned trade.
    """
    effective = pd.Timestamp(curve.effective_date(swap)).date()
    maturity = pd.Timestamp(curve.maturity_date(swap)).date()
    as_of = _as_of_date(request)
    lag = (effective - as_of).days

    if lag > MAX_SPOT_START_LAG.days:
        raise SpotStartRequiredError(
            f"CITIVELO_SWAP_SPREAD is Citi's SPOT-starting published quote, and this swap "
            f"starts {lag} days after the curve's own as-of date: effective {effective}, "
            f"maturity {maturity}, as-of {as_of} (tolerance "
            f"{MAX_SPOT_START_LAG.days} days, which covers T+2 across a holiday weekend). "
            f"RATES.OIS.{citi_index}.SWAP_SPREAD.<tenor> indexes a MATURITY, not a "
            "(forward, tenor) pair - answering here would return the SPOT quote for that "
            "many years, a real number for a different trade, and differencing it against "
            "this swap's own forward rate would leave the whole forward/spot spread as a "
            "residual. Citi publishes forwards under the FWD sub-type, which carries no "
            "swap spread; there is no published forward swap spread to serve."
        )

    if lag < -1:
        raise SpotStartRequiredError(
            f"CITIVELO_SWAP_SPREAD is Citi's SPOT-starting published quote, and this swap "
            f"started {-lag} days before the curve's own as-of date: effective {effective}, "
            f"maturity {maturity}, as-of {as_of}. Its remaining life is "
            f"{(maturity - as_of).days} days, but the tenor a published quote would be read "
            f"at is derived from the ORIGINAL {(maturity - effective).days}-day span, so the "
            "quote would come off the wrong point of the axis. Price a spot-starting swap of "
            "the remaining tenor, or use the computed IRSwapValue.MMSS, which pins the swap "
            "to a bond's maturity from spot."
        )


def _request_from_curve_meta(meta: Mapping[str, Any]) -> ResolvedRequest:
    """The request that reproduces the curve's OWN instant. Not a re-dispatch.

    The curve already resolved the caller's ``timestamp`` once, and its metadata
    records the answer. Re-running :func:`resolve_request` on the curve's stamp
    would be a second, different decision - and a wrong one for a live curve,
    whose stamp is an instant in the past by the time this runs.

    * ``eod``  -> EOD for the curve's own reference date, so the spread comes off
      the same ``DAILY`` row the curve did.
    * ``intraday`` / ``live`` -> **intraday at the curve's snapshot instant**. A
      live curve deliberately does NOT re-ask for "live": the spread has to be
      from the same instant as the curve, and "live" a second later is a
      different number that would silently make the pair inconsistent.
    """
    mode = str(meta.get("mode") or "").strip().lower()
    if mode == "eod":
        raw = meta.get("reference_date")
        if raw is None:
            raise ValueError(
                "citivelo_excel: an EOD curve without a reference_date on its metadata "
                "cannot say which day's published spread to read."
            )
        if isinstance(raw, datetime.datetime):
            eod_date = raw.date()
        elif isinstance(raw, datetime.date):
            eod_date = raw
        else:
            # Every citivelo_excel path writes reference_date as an ISO string.
            eod_date = pd.Timestamp(raw).date()
        return ResolvedRequest(mode="eod", requested=raw, eod_date=eod_date)

    if mode not in {"intraday", "live"}:
        raise ValueError(
            f"citivelo_excel: unknown curve mode {meta.get('mode')!r} on the curve metadata; "
            "expected one of eod, intraday, live."
        )
    stamp = meta.get("timestamp")
    if stamp is None:
        raise ValueError(
            "citivelo_excel: a curve without a timestamp on its metadata cannot say which "
            "instant's published spread to read."
        )
    return ResolvedRequest(
        mode="intraday",
        requested=stamp,
        wire_instant=to_wire_naive(stamp),
    )


def swap_spread_for_curve(
    *,
    curve: Any,
    package: Sequence[Any],
    tenor: Optional[str] = None,
    quotes: Any = None,
    catalog: Optional[CitiVeloCatalog] = None,
    max_staleness: Optional[datetime.timedelta] = ...,  # type: ignore[assignment]
    offline: bool = False,
    force_refresh: bool = False,
    return_quote: bool = False,
    client_kwargs: Optional[Mapping[str, Any]] = None,
) -> Union[float, SwapSpreadQuote]:
    """Citi's published swap spread for a one-leg package priced on a Citi curve.

    The instant and the index come from the CURVE, not from the caller: a
    published spread paired with a curve from a different minute is two markets
    stitched together, and neither number would be wrong on its own.

    ``client_kwargs`` only reaches anything when ``quotes`` is omitted and one is
    built here; it is exposed because this is the only door the value map opens,
    and a batch caller that cannot inject a ``quotes`` object had no way to tune
    the connect at all.

    Raises
    ------
    SpotStartRequiredError
        When the package's effective date is more than
        :data:`MAX_SPOT_START_LAG` from the curve's own as-of date, in either
        direction. Citi's axis is spot-starting and nothing in the tag says so, so
        a forward-starting swap would otherwise be served the SPOT quote for its
        derived tenor - the right shape of number for the wrong trade.
    NotImplementedError
        For a package with more than one leg. A published outright spread has no
        curve or fly analogue in this family - Citi publishes ``CURVES`` and
        ``BFLY`` as their own sub-types - and risk-weighting two published spreads
        would invent a number Citi never quoted. Same restriction, for the same
        reason, as ``IRSwapSpreadsMDP.swap_rate_percent``.
        (``SpotStartRequiredError`` is a subclass of this.)
    ValueError
        When the curve did not come from the ``citivelo_excel`` source. The
        message names the source that was actually found, because the usual cause
        is an ``IRSwapsMDP`` built on a different token and the failure is
        otherwise invisible - every other value on the map would have answered.
    UnknownTagError
        When the tenor is off Citi's ragged per-index axis.
    """
    if len(package) != 1:
        raise NotImplementedError(
            f"CITIVELO_SWAP_SPREAD is an outright published quote; got a {len(package)}-leg "
            "package. Citi publishes CURVES and BFLY as separate sub-types - combining two "
            "published spreads here would invent a number that was never quoted."
        )

    meta = getattr(curve, "meta_data", None)
    if meta is None:
        meta = curve.meta() if hasattr(curve, "meta") else None
    if not isinstance(meta, Mapping):
        raise ValueError(
            "CITIVELO_SWAP_SPREAD needs the curve's metadata to know which index and instant "
            f"to read, and this curve carries {type(meta).__name__}. Build it through "
            "IRSwapsMDP(source='CITIVELO_EXCEL')."
        )
    source = meta.get("source")
    if source != SOURCE_TOKEN:
        raise ValueError(
            f"CITIVELO_SWAP_SPREAD is served by the {SOURCE_TOKEN!r} curve source; this curve "
            f"came from {source!r}. It is a quote Citi publishes, not something computable "
            "from a curve - see IRSwapValue.MMSS / SPREADOVER for the computed spreads, which "
            "work on any curve source."
        )
    citi_index = meta.get("citi_index")
    if not citi_index:
        raise ValueError(
            "CITIVELO_SWAP_SPREAD needs meta_data['citi_index'] to build the tag; this curve "
            f"has {citi_index!r}."
        )

    # The request comes first: the spot-start check needs the curve's own as-of
    # date, and it has to run whether or not the caller stated a tenor - an
    # explicitly-tenored forward is the same wrong number as a derived one.
    request = _request_from_curve_meta(meta)
    _assert_spot_starting(
        curve=curve, swap=package[0], request=request, citi_index=str(citi_index)
    )

    token = str(tenor).strip().upper() if tenor is not None else tenor_for_swap(curve, package[0])
    quote = fetch_swap_spreads(
        str(citi_index),
        [token],
        None,
        quotes=quotes,
        offline=offline,
        catalog=catalog,
        force_refresh=force_refresh,
        max_staleness=max_staleness,
        client_kwargs=client_kwargs,
        _request=request,
    )[token]
    return quote if return_quote else quote.value
