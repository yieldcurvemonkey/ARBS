r"""Published overnight fixings for the Citi Velocity curves' float legs.

Why this exists
---------------
A par or forward-starting swap needs no fixing history - its first accrual period
starts at or after spot. A **seasoned** swap does: rateslib must compound the RFR
over the days that have already elapsed, and without them it either raises
"RFRs could not be calculated" or forecasts the elapsed days off a curve that does
not extend back that far, whose discount factors are zero. Before this module,
nineteen of the twenty curves carried an empty fixings series and any seasoned
swap on them raised.

Where the numbers come from, and why Citi is trusted
----------------------------------------------------
Citi publishes ``RATES.MONEY_MARKETS.<ccy>.<index>.ON``. Measured live on
2026-08-07, it serves **21 years** of daily history (from 2005-01-03) for nine of
the twenty curve currencies.

Whether that can be trusted rests on the one currency where this repo has an
independent source. It was checked, and the answer is unambiguous:

    Citi  RATES.MONEY_MARKETS.USD.SOFR.ON   vs   the New York Fed's own SOFR
    2,056 overlapping business days, 2018-04-02 .. 2026-06-25
    max |difference| = 0.000000 bp,  0 of 2,056 dates differ at all

So Citi's money-market ON series **is** the official published fixing, in percent.
That is what licenses using it for the eight currencies where nothing else is
available here.

**But Citi's tail goes stale, and the amount differs per currency.** On
2026-08-07 the last published fixing was:

===============  ============  =====================================
currency         Citi's last   comment
===============  ============  =====================================
EUR, GBP, JPY,   2026-08-06    current (previous business day)
CHF, AUD, NZD
USD              2026-06-25    **six weeks stale** - the NY Fed had 29
                               more business days
SEK              2026-06-26    six weeks stale
CAD              2026-04-29    **three months stale**
NOK, DKK         (nothing)     the tag serves no data at all
===============  ============  =====================================

A fixings series that stops six weeks ago does not fail loudly - it silently
under-fixes every seasoned swap whose accrual crosses the gap. So the resolver
prefers an official source where this repo has one (USD only), fills the rest from
Citi, and **reports the gap** between the last fixing and the date the curve
actually needs. :class:`FixingsResult.assert_covers` turns that into a refusal.

How this is served, and why that is not an implementation detail
----------------------------------------------------------------
A fixing series is never the thing a caller asked for. It is a detail of building
a curve whose NODES came from the store, so the way it is fetched decides whether
a fully warmed, fully offline curve request succeeds.

It used to decide the wrong way. ``citi_fixings`` asked the tag cache for
``start=2005-01-01, end=today``; ``CitiVeloTagCache.missing_spans`` treats an
explicit ``start`` earlier than the cached first row as a missing head, and any
``end`` past the cached last row as a missing tail. Citi's USD tail is frozen six
weeks back, so BOTH spans reopened on every call and neither could ever be
filled. Measured 2026-08-08 against the warm cache - 5,427 rows, complete - the
answer was ``[(2005-01-01, 2005-01-03), (2026-06-25, 2026-08-08)]``: two fetches
per call, forever, for a series already on disk. A signed-out Excel then took the
whole curve build down with an ``AddInNotSignedInError``.

So the request is unbounded (the head closes through the ``history_start``
sidecar, the tail through :data:`_FIXINGS_MAX_STALENESS`) and, when Excel refuses
anyway, the cached rows are re-served rather than raised. Serving them is safe by
construction: :meth:`FixingsResult.assert_covers` and the callers' own staleness
gate already refuse a series that does not reach the date being priced, so this
cannot silently under-fix a float leg - it can only let a curve finish building.

The five currencies with no coverage at all
-------------------------------------------
``ILS``, ``MXN``, ``SGD``, ``THB`` and ``ZAR`` are absent from
``RATES.MONEY_MARKETS`` entirely, and so is Fed Funds (``FFT``, ``BGCR``,
``TGCR``, ``FEDFUND`` and ``EFFR`` were all probed under ``USD`` and none serves).
Those curves get an empty series, exactly as before, and a seasoned swap on them
still raises - which is correct, and is why nothing here invents a number.
"""

from __future__ import annotations

import datetime
import logging
import threading
import warnings
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

import pandas as pd

__all__ = [
    "MONEY_MARKET_ON_TAG",
    "NO_FIXING_SOURCE",
    "FixingsResult",
    "FixingsUnavailableError",
    "citi_fixings",
    "official_fixings",
    "fixings_for",
    "reset_publisher_fixings_cache",
    "reset_fixings_cache",
]

_logger = logging.getLogger(__name__)

#: ``citi_index -> RATES.MONEY_MARKETS.<ccy>.<index>.ON``, for the nine that were
#: measured to serve on 2026-08-07. ``NOK_NOWA`` and ``DKK_TNDKK`` have a
#: well-formed tag in the catalog grammar that returns no rows, so they are listed
#: in :data:`NO_FIXING_SOURCE` instead - a tag that exists but serves nothing is
#: worse than no tag, because it looks like coverage.
MONEY_MARKET_ON_TAG: Dict[str, str] = {
    "USD_SOFR": "RATES.MONEY_MARKETS.USD.SOFR.ON",
    "EUR_EUROSTR": "RATES.MONEY_MARKETS.EUR.EUROSTR.ON",
    "EUR_EONIA": "RATES.MONEY_MARKETS.EUR.EUROSTR.ON",
    "GBP_SONIA": "RATES.MONEY_MARKETS.GBP.SONIA.ON",
    "JPY_TONAR": "RATES.MONEY_MARKETS.JPY.TONAR.ON",
    "JPY_TONAR_JSCC": "RATES.MONEY_MARKETS.JPY.TONAR.ON",
    "JPY_TONAR_LCH": "RATES.MONEY_MARKETS.JPY.TONAR.ON",
    "CAD_CORRA": "RATES.MONEY_MARKETS.CAD.CORRA.ON",
    "CHF_SARON": "RATES.MONEY_MARKETS.CHF.SARON.ON",
    "AUD_AONIA": "RATES.MONEY_MARKETS.AUD.AONIA.ON",
    "NZD_NZIONA": "RATES.MONEY_MARKETS.NZD.NZIONA.ON",
    "SEK_STINA": "RATES.MONEY_MARKETS.SEK.STINA.ON",
}

#: Curves with no fixing source at all. Named explicitly so "no fixings" is a
#: recorded fact rather than an empty lookup that reads like an oversight.
NO_FIXING_SOURCE: Dict[str, str] = {
    "USD_FEDFUND": "RATES.MONEY_MARKETS has no Fed Funds entry; FFT, BGCR, TGCR, "
    "FEDFUND and EFFR were all probed under USD on 2026-08-07 and none serves.",
    "NOK_NOWA": "RATES.MONEY_MARKETS.NOK.NOWA.ON is well-formed but serves no rows.",
    "DKK_TNDKK": "RATES.MONEY_MARKETS.DKK.TNDKK.ON is well-formed but serves no rows.",
    "ILS_SHIR": "ILS is absent from RATES.MONEY_MARKETS.",
    "MXN_T_FONDEO": "MXN is absent from RATES.MONEY_MARKETS.",
    "SGD_SORA": "SGD is absent from RATES.MONEY_MARKETS.",
    "THB_THOR": "THB is absent from RATES.MONEY_MARKETS.",
    "ZAR_ZARONIA": "ZAR is absent from RATES.MONEY_MARKETS.",
}

#: Curve names for which this repo has an INDEPENDENT official source.
_OFFICIAL_SOURCE_CURVES = {"USD-SOFR-1D"}

#: How long a cached fixing series may go unrefreshed before its tail is
#: re-requested from Citi.
#:
#: The number matters far less than the fact that there is one at all.
#: :func:`citi_fixings` used to ask for ``end=date.today()``, and
#: ``CitiVeloTagCache.missing_spans`` opens a tail span for any ``end`` that runs
#: past what the cache holds. Citi's USD tail is frozen six weeks back and CAD's
#: three months (see the module docstring), so that span could never be filled:
#: the fetch returned nothing new, the cache did not advance, and the next call
#: asked again - forever. Every process went to Excel for a series that was
#: already complete on disk, and a signed-out Excel took the whole curve build
#: down with it. MEASURED 2026-08-08 on the warm cache:
#: ``missing_spans(start=2005-01-01, end=today)`` returned
#: ``[(2005-01-01, 2005-01-03), (2026-06-25, 2026-08-08)]`` - two spans, neither
#: fillable, on every single call.
#:
#: An unbounded ``end`` routes the tail through this gate instead, and a fetch
#: DOES satisfy it: the span starts at ``cov.last`` INCLUSIVE, so Citi returns at
#: least that row, ``write`` runs and ``fetched_at`` advances even when nothing
#: new arrived.
#:
#: Twelve hours means at most two refreshes a day. A fixing for date D publishes
#: on D+1 and :func:`fixings_for` drops anything dated on or after the curve's own
#: reference date, so half a day of staleness cannot change a historical answer -
#: only how soon a brand-new fixing is picked up.
_FIXINGS_MAX_STALENESS = datetime.timedelta(hours=12)

#: How far the last published fixing may sit behind the date a curve needs before
#: :meth:`FixingsResult.assert_covers` refuses. Five calendar days spans a long
#: weekend; anything more and a seasoned swap is compounding over days nobody has
#: a number for.
DEFAULT_MAX_FIXING_GAP = datetime.timedelta(days=5)

_WARNED: set[str] = set()
_LOCK = threading.RLock()


class FixingsUnavailableError(RuntimeError):
    """The fixings do not reach the date the curve needs."""


@dataclass(frozen=True)
class FixingsResult:
    """A fixing history plus everything needed to judge whether to trust it.

    ``series`` is in **percent**, indexed by fixing date, ascending - the unit
    ``rl.IRS(leg2_rate_fixings=...)`` expects and the unit Citi publishes. The
    repo's own ``_fetch_fixings`` returns decimals and is scaled here, once.
    """

    curve_name: str
    citi_index: str
    series: pd.Series
    source: str
    note: str = ""
    contributions: Dict[str, int] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return self.series is None or self.series.empty

    @property
    def last_date(self) -> Optional[datetime.date]:
        if self.empty:
            return None
        return self.series.index.max().date()

    @property
    def first_date(self) -> Optional[datetime.date]:
        if self.empty:
            return None
        return self.series.index.min().date()

    def gap_to(self, needed: datetime.date) -> Optional[datetime.timedelta]:
        """How far the last fixing sits behind ``needed``. ``None`` when empty."""
        if self.last_date is None:
            return None
        return datetime.timedelta(days=(needed - self.last_date).days)

    def assert_covers(
        self, needed: datetime.date, *, max_gap: datetime.timedelta = DEFAULT_MAX_FIXING_GAP
    ) -> None:
        """Raise unless the fixings reach within ``max_gap`` of ``needed``.

        Call this before pricing anything seasoned. It is deliberately NOT called
        on every curve build: a par swap needs no fixings and refusing to build a
        curve because a fixing is stale would be worse than the disease.
        """
        if self.empty:
            raise FixingsUnavailableError(
                f"citivelo_excel: no published fixings for {self.curve_name} "
                f"({self.citi_index}). {self.note or NO_FIXING_SOURCE.get(self.citi_index, '')} "
                "A par or forward-starting swap does not need them; a seasoned one does."
            )
        gap = self.gap_to(needed)
        if gap is not None and gap > max_gap:
            raise FixingsUnavailableError(
                f"citivelo_excel: {self.curve_name} fixings stop at {self.last_date}, "
                f"{gap.days} days before {needed}, past the {max_gap.days}-day limit "
                f"(source: {self.source}). Compounding over days with no published fixing "
                "would silently under-fix the float leg."
            )

    def describe(self) -> str:
        if self.empty:
            return f"{self.curve_name}: no fixings ({self.note})"
        return (
            f"{self.curve_name}: {len(self.series)} fixings {self.first_date}..{self.last_date} "
            f"via {self.source}"
        )


# ------------------------------------------------------------------ #
#                             providers                              #
# ------------------------------------------------------------------ #


def official_fixings(curve_name: str) -> pd.Series:
    """The repo's own independent fixing source, in PERCENT. Empty when none.

    Two routes, tried in order:

    1. ``USD-SOFR-1D`` goes through ``MDP.IRSwaps.fixings_cache`` (the New York
       Fed). Preferred over Citi for that curve not because the numbers differ -
       they are identical to 0.000000 bp across 2,056 days - but because Citi's
       tail was six weeks stale when this was measured and the Fed's was current.
    2. Everything else goes to
       :mod:`MDP.IRSwaps.CITIVELO_EXCEL.official_sources`, which reaches each
       currency's own publisher directly. That covers the curves Citi has no
       ``RATES.MONEY_MARKETS`` tag for at all - USD Fed Funds, NOK and ZAR today,
       MXN once a Banxico token is set.

    Empty means "no source", never "the rate is zero"; callers fall back to Citi
    and, failing that, refuse to price rather than invent a fixing.
    """
    if str(curve_name).upper() not in _OFFICIAL_SOURCE_CURVES:
        return _publisher_fixings(curve_name)
    try:
        from MDP.IRSwaps.fixings_cache.fixings_cache import _fetch_fixings

        series = _fetch_fixings(
            as_of_date=datetime.date.today(), curve_name="USD-SOFR-1D"
        ).dropna().sort_index()
    except Exception as exc:  # noqa: BLE001 - an offline machine is not a failure here
        _warn_once(
            f"official-{curve_name}",
            f"citivelo_excel: the official fixing source for {curve_name} is unavailable "
            f"({type(exc).__name__}: {exc}); falling back to Citi's published series.",
        )
        return pd.Series(dtype="float64")
    if series.empty:
        return series
    # _fetch_fixings returns DECIMAL; every call site in this repo multiplies by
    # 100 at the point of use. Do it once, here, so nothing downstream has to know.
    if abs(float(series.iloc[-1])) < 0.5:
        series = series * 100.0
    series.index = pd.DatetimeIndex(series.index).normalize()
    return series[~series.index.duplicated(keep="last")]


#: Publishers are asked for EVERYTHING they have, from a date earlier than any
#: of these rates existed. Each API clamps to its own inception, so this is not a
#: guess that can be wrong - it is a request for the whole series.
#:
#: This replaced an 800-day rolling window, which was arbitrary and too short: a
#: 10Y swap traded five years ago compounds over fixings the window would simply
#: not contain, and the failure is silent - the series just starts late.
#:
#: There is no cost argument for truncating. Measured 2026-08-07, full history:
#: EFFR 6,558 rows to 2000-07-03 (0.5s), NOWA 3,735 to 2011-09-30 (0.4s),
#: ZARONIA 1,004 to 2022-08-01 (1.8s) - and the fetcher is now process-wide, so
#: this is paid once per run rather than per curve request.
_PUBLISHER_HISTORY_START = datetime.date(1990, 1, 1)

#: ONE fetcher for the whole process, so its cache actually survives.
#:
#: This used to be constructed per call, which made the cache inside it dead on
#: arrival: every curve request performed a live HTTP GET. Measured 2026-08-07,
#: five requests for ``USD-FEDFUNDS-1D`` produced five round trips at ~175 ms
#: each - so a caller resolving fixings per node (a 1,040-node swaption cube, a
#: minute-resolution backfill) would issue a request per node and spend minutes
#: on it, while hammering the New York Fed, Norges Bank and the SARB hard enough
#: to invite a block.
#:
#: The cache key inside the fetcher is ``(index, start, end)`` and ``end`` is
#: today, so the entry rolls over at midnight on its own - fresh fixings without
#: a TTL to tune.
_PUBLISHER_FETCHER: Any = None
_PUBLISHER_FETCHER_LOCK = threading.Lock()


def _shared_publisher_fetcher() -> Any:
    """The process-wide :class:`OfficialFixingsFetcher`, built once."""
    global _PUBLISHER_FETCHER
    if _PUBLISHER_FETCHER is None:
        from MDP.IRSwaps.CITIVELO_EXCEL.official_sources import OfficialFixingsFetcher

        with _PUBLISHER_FETCHER_LOCK:
            if _PUBLISHER_FETCHER is None:
                _PUBLISHER_FETCHER = OfficialFixingsFetcher()
    return _PUBLISHER_FETCHER


def reset_publisher_fixings_cache() -> None:
    """Drop the shared fetcher. For tests, and for a long-lived daemon."""
    global _PUBLISHER_FETCHER
    with _PUBLISHER_FETCHER_LOCK:
        _PUBLISHER_FETCHER = None


@dataclass(frozen=True)
class _MergedSources:
    """The two raw fixing series for one curve, before any date filtering."""

    official: pd.Series
    citi: pd.Series


#: ``(curve_name, citi_index, prefer_official) -> _MergedSources``. Keyed without
#: ``reference_date`` on purpose: the sources are the same series whatever date
#: is being priced, so one entry serves an entire backfill.
_MERGED_CACHE: Dict[Tuple[str, str, bool], "_MergedSources"] = {}
_MERGED_CACHE_LOCK = threading.RLock()


def _merged_sources(
    curve_name: str, citi_index: str, prefer_official: bool, quotes: Any
) -> "_MergedSources":
    """Both source series for one curve, fetched at most once per process.

    ``quotes`` is honoured but NOT part of the key: an explicit quotes object is
    a caller supplying its own tag cache, so it bypasses the shared entry rather
    than poisoning it for everyone else.
    """
    if quotes is not None:
        return _MergedSources(
            official=official_fixings(curve_name) if prefer_official else pd.Series(dtype="float64"),
            citi=citi_fixings(citi_index, quotes=quotes),
        )
    key = (str(curve_name), str(citi_index), bool(prefer_official))
    hit = _MERGED_CACHE.get(key)
    if hit is None:
        with _MERGED_CACHE_LOCK:
            hit = _MERGED_CACHE.get(key)
            if hit is None:
                hit = _MergedSources(
                    official=(
                        official_fixings(curve_name)
                        if prefer_official
                        else pd.Series(dtype="float64")
                    ),
                    citi=citi_fixings(citi_index),
                )
                _MERGED_CACHE[key] = hit
    return hit


#: ``(curve_name, citi_index, reference_date, prefer_official, fill_gaps) ->
#: FixingsResult``. Bounded, LRU, and populated ONLY when ``quotes is None``.
#:
#: The merged-sources cache above removed the two source lookups (232 ms + 237
#: ms) but left the per-call work: the ``reference_date`` filter builds a 5,456
#: element object array of ``datetime.date``, and ``fill_calendar_gaps`` walks
#: 21 years of calendar days asking ``is_bus_day``. Measured 2026-08-08 that is
#: **7.9 ms per call, 26% of a warmed minute observation** - and a minute
#: timeseries pays it 841 times for ONE distinct answer, because every
#: observation in a session shares a reference date.
#:
#: ``reference_date`` is part of the key, not a filter applied to a shared
#: entry. That is the whole point: an entry cached for a later date contains
#: fixings an earlier request must not see, and serving them would leak future
#: rates into a historical curve - invisible in any timing benchmark, and the
#: exact failure this key shape exists to prevent.
_RESULT_CACHE: "OrderedDict[Tuple[str, str, Optional[datetime.date], bool, bool], FixingsResult]" = (
    OrderedDict()
)
_RESULT_CACHE_LOCK = threading.RLock()

#: Distinct (curve, reference_date) answers retained. A backfill walks dates in
#: order, so a small window suffices; 20 curves x a few dates in flight is the
#: shape this is sized for. Each entry is a ~5,500-element float series (~90 KB
#: with its index), so this bounds the cache at roughly 45 MB in the worst case.
_RESULT_CACHE_MAX = 512


def reset_fixings_cache() -> None:
    """Drop every cached fixing series - the merged sources and the publisher.

    For tests, and for any process that outlives a publication: fixings for date
    D appear on D+1, so a daemon running past midnight wants a fresh pull.
    """
    with _MERGED_CACHE_LOCK:
        _MERGED_CACHE.clear()
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE.clear()
    reset_publisher_fixings_cache()


def _publisher_fixings(curve_name: str) -> pd.Series:
    """Overnight fixings straight from the currency's own publisher, in PERCENT.

    Empty - not an exception - when the currency has no reachable source, so a
    caller can fall through to Citi. The reason is logged once rather than
    swallowed, because "NOK has no fixings" should be traceable to the endpoint
    that did not answer.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import citi_index_for_curve_name

    try:
        citi_index = citi_index_for_curve_name(curve_name)
    except Exception:  # noqa: BLE001 - an unknown curve simply has no source
        return pd.Series(dtype="float64")

    fetcher = _shared_publisher_fetcher()
    if not fetcher.available_for(citi_index):
        return pd.Series(dtype="float64")

    end = datetime.date.today()
    try:
        series = fetcher.fetch(citi_index, _PUBLISHER_HISTORY_START, end)
    except Exception as exc:  # noqa: BLE001 - an offline machine is not a failure
        _warn_once(
            f"publisher-{citi_index}",
            f"citivelo_excel: the official publisher for {citi_index} is unavailable "
            f"({type(exc).__name__}: {exc}); falling back to Citi's published series.",
        )
        return pd.Series(dtype="float64")
    if series.empty:
        return series
    series.index = pd.DatetimeIndex(series.index).normalize()
    return series[~series.index.duplicated(keep="last")]


def citi_fixings(
    citi_index: str,
    *,
    quotes: Any = None,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
) -> pd.Series:
    """Citi's published overnight fixing for one curve, in PERCENT.

    Served through the ordinary tag cache, and - unlike the rest of this package -
    it must be able to answer when Excel is not there at all. A fixing series is
    not the thing a caller asked for; it is a detail of building a curve whose
    NODES came from the store, and dying on it turns a fully cached curve request
    into a hard failure. See :func:`_citi_series`.
    """
    tag = MONEY_MARKET_ON_TAG.get(str(citi_index).upper())
    if tag is None:
        return pd.Series(dtype="float64")
    if quotes is None:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()

    raw = _citi_series(quotes, tag, start=start, end=end)
    if raw is None or len(raw) == 0:
        return pd.Series(dtype="float64")
    series = raw.dropna().sort_index()
    if series.empty:
        return pd.Series(dtype="float64")
    series.index = pd.DatetimeIndex(series.index).normalize()
    return series[~series.index.duplicated(keep="last")]


def _citi_series(
    quotes: Any,
    tag: str,
    *,
    start: Optional[datetime.date] = None,
    end: Optional[datetime.date] = None,
) -> Optional[pd.Series]:
    """One tag's daily series: the cache first, Excel only when it must.

    The bounds are left UNBOUNDED unless the caller named a window, and that is
    not cosmetic. ``CitiVeloTagCache.missing_spans`` consults the ``history_start``
    sidecar - the thing that lets a cache say "I already hold everything there
    is" - only on the ``start is None`` branch, and it re-opens the tail for any
    ``end`` past what is cached. The previous call passed
    ``start=2005-01-01, end=today`` and so took the other branch at BOTH ends,
    producing two permanently unfillable spans per call (see
    :data:`_FIXINGS_MAX_STALENESS`). ``fetch_timeseries`` turns an unbounded
    request into ``CVTSHIST(..., "MAX", "", "")``, which the add-in truncates to
    the tag's own history, so nothing is lost by not naming 2005.

    When Excel refuses - not signed in, not running, died mid-call - the cached
    rows are re-served instead of propagating. That is safe by construction rather
    than by optimism: :meth:`FixingsResult.assert_covers` and the callers' own
    staleness gate already refuse a series that does not reach the date being
    priced, so a stale answer here cannot silently under-fix a float leg. What it
    can do is let a curve whose nodes came from the store finish building.
    """
    from MDP.CitiVelocityExcel.errors import CitiVelocityError

    before = _coverage(quotes, tag)
    try:
        got = quotes.series(
            [tag], "DAILY", start=start, end=end, max_staleness=_FIXINGS_MAX_STALENESS
        )
    except CitiVelocityError as exc:
        _warn_once(
            f"citi-fixings-offline-{tag}",
            f"citivelo_excel: Excel would not serve {tag} ({type(exc).__name__}: {exc}); "
            "re-serving the cached fixings. The staleness gate still applies, so a "
            "series that does not reach the date being priced is refused rather than used.",
        )
        return _cached_only(quotes, tag, start=start, end=end)

    if start is None and end is None:
        _record_history_start(quotes, tag, before=before)
    return got.get(tag)


def _coverage(quotes: Any, tag: str) -> Any:
    """The tag cache's coverage for ``tag``, or ``None`` when there is no cache."""
    cache = getattr(quotes, "cache", None)
    if cache is None:
        return None
    try:
        return cache.coverage(tag, "DAILY", "CLOSE")
    except Exception as exc:  # noqa: BLE001 - a cache that cannot be read is not fatal
        _logger.debug("citivelo_excel: could not read cache coverage for %s: %s", tag, exc)
        return None


def _cached_only(
    quotes: Any,
    tag: str,
    *,
    start: Optional[datetime.date],
    end: Optional[datetime.date],
) -> Optional[pd.Series]:
    """Re-serve one tag from the tag cache with no fetcher at all.

    Goes to the cache directly rather than building a second
    ``CitiVeloQuotes(offline=True)``: offline raises when the request is not fully
    cached, and the whole point here is that it may not be.
    """
    cache = getattr(quotes, "cache", None)
    if cache is None:
        return None
    try:
        got = cache.get(
            [tag], "DAILY", start=start, end=end, price_point="CLOSE", fetcher=None
        )
    except Exception as exc:  # noqa: BLE001 - the degrade path must not raise either
        _logger.debug("citivelo_excel: cached-only read failed for %s: %s", tag, exc)
        return None
    return got.get(tag)


def _record_history_start(quotes: Any, tag: str, *, before: Any) -> None:
    """Close the head span for good, using what an unbounded fetch returned.

    ``missing_spans`` re-opens ``(None, first)`` on every call until the sidecar
    records a ``history_start``, so without this the head costs an Excel round
    trip forever even once the tail is quiet. The value cannot be guessed - too
    early never closes the head, too late silently truncates history - so it is
    taken from what an unbounded request actually brought back. ``CVTSHIST`` at
    ``MAX`` is truncated to the tag's own history by the add-in, so the first row
    of an unbounded answer IS the inception.

    Three guards keep a guess from becoming a permanent truncation:

    * ``quotes.offline`` - an offline reader never asked the add-in anything, so
      what is on disk proves nothing about what exists upstream;
    * ``fetched_at`` must have advanced, which happens only on a ``write``, which
      happens only when a fetch returned rows. A wire that answered with nothing
      leaves it untouched and is not evidence of anything;
    * ``first`` must not have moved earlier. If the head fetch DID bring older
      rows, the true inception is further back still and the next call - which
      now starts from the earlier first - is the one that settles it.
    """
    if getattr(quotes, "offline", False):
        return
    cache = getattr(quotes, "cache", None)
    if cache is None:
        return
    after = _coverage(quotes, tag)
    if after is None or after.first is None or after.n_rows == 0:
        return
    if after.history_start is not None:
        return
    if before is not None:
        if after.fetched_at is None or after.fetched_at == before.fetched_at:
            return  # nothing was written, so nothing was learned
        if before.first is not None and after.first < before.first:
            return  # older rows arrived; this is not the bottom yet
    try:
        cache.set_history_start(tag, "DAILY", after.first, price_point="CLOSE")
    except Exception as exc:  # noqa: BLE001 - a sidecar that will not write is not fatal
        _logger.debug("citivelo_excel: could not record history_start for %s: %s", tag, exc)


# ------------------------------------------------------------------ #
#                             the resolver                           #
# ------------------------------------------------------------------ #


def fill_calendar_gaps(series: pd.Series, citi_index: str) -> Tuple[pd.Series, int]:
    """Forward-fill the leg calendar's business days that the publisher skipped.

    Returns ``(filled, n_filled)``.

    Two libraries' holiday lists never agree, and neither agrees with the
    publisher's. Measured on 2024-08-06..2026-08-06: rateslib's ``syd`` calendar
    calls **8** days business days that Citi's AONIA series does not publish (and
    ``tyo`` one for TONAR). rateslib needs a rate for every business day in an
    elapsed accrual period, so a single such day makes a seasoned swap raise -
    ``AUD-AONIA-1D`` and ``JPY-TONAR-1D`` both did.

    Carrying the previous fixing forward is what actually happens: an index does
    not move on a day it is not published. This repo already relies on that
    reasoning in ``IRSwapsMDP._asof_fixings``, which measured the substitution at
    **~0.0012 bp on a seasoned 5Y**.

    Filling happens ONLY inside ``[first, last]``. Extending past the last
    published fixing would be inventing data, and that is what the staleness gate
    exists to refuse instead.
    """
    if series is None or series.empty:
        return series, 0
    from MDP.CitiVelocityExcel.curves.conventions import conventions_for

    calendar = conventions_for(citi_index).rl_calendar_object()
    first = series.index.min().to_pydatetime()
    last = series.index.max().to_pydatetime()
    wanted = []
    day = first
    while day <= last:
        if calendar.is_bus_day(day):
            wanted.append(day)
        day += datetime.timedelta(days=1)
    if not wanted:
        return series, 0
    index = pd.DatetimeIndex(wanted)
    filled = series.reindex(series.index.union(index)).ffill().reindex(
        series.index.union(index)
    )
    n_filled = int(len(filled) - len(series))
    return filled.astype("float64"), max(0, n_filled)


def fixings_for(
    curve_name: str,
    citi_index: str,
    *,
    reference_date: Optional[datetime.date] = None,
    quotes: Any = None,
    prefer_official: bool = True,
    fill_gaps: bool = True,
) -> FixingsResult:
    """Published fixings for one curve, best source first.

    Parameters
    ----------
    reference_date
        The curve's own anchor. Fixings dated on or after it are dropped: a fixing
        for date D is published on D+1, so a curve anchored at D cannot know it.
        This matches what ``IRSwapsMDP._asof_fixings`` already does for USD.
    prefer_official
        Use the independent source where one exists and let Citi fill only the
        dates it does not cover. The two agree exactly, so this is about the tail,
        not about the values.

    Notes
    -----
    The two series are combined rather than one chosen: Citi reaches back to
    2005-01-03 while the Fed cache here starts 2018-04-02, and the Fed's tail is
    the fresher one. Union with the official source winning on collision gives the
    longest correct history available.

    The whole result is memoised on ``(curve_name, citi_index, reference_date,
    prefer_official, fill_gaps)`` when no explicit ``quotes`` is supplied - see
    :data:`_RESULT_CACHE`. The returned ``series`` is a **copy**, because callers
    hand it straight to ``RLIRSwapCurve`` and this repo has call sites that
    assign into a fixings series they were given.
    """
    citi_index = str(citi_index).upper()

    if quotes is None:
        key = (
            str(curve_name), citi_index, reference_date,
            bool(prefer_official), bool(fill_gaps),
        )
        with _RESULT_CACHE_LOCK:
            hit = _RESULT_CACHE.get(key)
            if hit is not None:
                _RESULT_CACHE.move_to_end(key)
        if hit is None:
            hit = _fixings_for_uncached(
                curve_name, citi_index,
                reference_date=reference_date,
                quotes=None,
                prefer_official=prefer_official,
                fill_gaps=fill_gaps,
            )
            with _RESULT_CACHE_LOCK:
                _RESULT_CACHE[key] = hit
                _RESULT_CACHE.move_to_end(key)
                while len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
                    _RESULT_CACHE.popitem(last=False)
        return replace(hit, series=hit.series.copy(), contributions=dict(hit.contributions))

    return _fixings_for_uncached(
        curve_name, citi_index,
        reference_date=reference_date,
        quotes=quotes,
        prefer_official=prefer_official,
        fill_gaps=fill_gaps,
    )


def _fixings_for_uncached(
    curve_name: str,
    citi_index: str,
    *,
    reference_date: Optional[datetime.date] = None,
    quotes: Any = None,
    prefer_official: bool = True,
    fill_gaps: bool = True,
) -> FixingsResult:
    """:func:`fixings_for` without the result memo. The real work lives here."""
    citi_index = str(citi_index).upper()
    contributions: Dict[str, int] = {}

    # The two source lookups are the whole cost of this function and they do not
    # depend on reference_date, so they are resolved once per process rather than
    # once per call. MEASURED 2026-08-08 on USD-SOFR-1D: official_fixings 232 ms
    # + citi_fixings 237 ms, against 11 ms to read the day's parquet and 1.3 ms
    # to reconstruct the curve - i.e. fixings were 97% of a warmed store read.
    #
    # That is per CURVE REQUEST, so a timeseries paid it every time: a single
    # day of minute curves (~1,100 points) spent ~8 minutes re-fetching and
    # re-merging the same 5,456-row history.
    #
    # Only the merged series is cached. The reference_date filter and the gap
    # fill stay per call, because they are cheap (~9 ms) and depend on the date.
    cached = _merged_sources(curve_name, citi_index, prefer_official, quotes)
    official, citi = cached.official, cached.citi
    contributions["official"] = int(official.size)
    contributions["citi"] = int(citi.size)

    if official.empty and citi.empty:
        note = NO_FIXING_SOURCE.get(
            citi_index, "no published overnight fixing tag is known for this curve"
        )
        return FixingsResult(
            curve_name=str(curve_name), citi_index=citi_index,
            series=pd.Series(dtype="float64"), source="none", note=note,
            contributions=contributions,
        )

    if official.empty:
        merged, source = citi, "citi_money_markets"
    elif citi.empty:
        merged, source = official, "official"
    else:
        merged = official.combine_first(citi).sort_index()
        source = "official+citi"

    if reference_date is not None and not merged.empty:
        merged = merged[merged.index.date < reference_date]

    if fill_gaps and not merged.empty:
        merged, n_filled = fill_calendar_gaps(merged, citi_index)
        contributions["calendar_filled"] = n_filled

    return FixingsResult(
        curve_name=str(curve_name),
        citi_index=citi_index,
        series=merged.astype("float64"),
        source=source,
        contributions=contributions,
    )


def _warn_once(key: str, message: str) -> None:
    with _LOCK:
        if key in _WARNED:
            return
        _WARNED.add(key)
    warnings.warn(message, stacklevel=3)
