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
from dataclasses import dataclass, field
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


#: How much history a publisher is asked for. Long enough to cover the
#: compounding period of any seasoned OIS this package prices.
_PUBLISHER_LOOKBACK = datetime.timedelta(days=800)


def _publisher_fixings(curve_name: str) -> pd.Series:
    """Overnight fixings straight from the currency's own publisher, in PERCENT.

    Empty - not an exception - when the currency has no reachable source, so a
    caller can fall through to Citi. The reason is logged once rather than
    swallowed, because "NOK has no fixings" should be traceable to the endpoint
    that did not answer.
    """
    from MDP.IRSwaps.CITIVELO_EXCEL.curve_names import citi_index_for_curve_name
    from MDP.IRSwaps.CITIVELO_EXCEL.official_sources import OfficialFixingsFetcher

    try:
        citi_index = citi_index_for_curve_name(curve_name)
    except Exception:  # noqa: BLE001 - an unknown curve simply has no source
        return pd.Series(dtype="float64")

    fetcher = OfficialFixingsFetcher()
    if not fetcher.available_for(citi_index):
        return pd.Series(dtype="float64")

    end = datetime.date.today()
    try:
        series = fetcher.fetch(citi_index, end - _PUBLISHER_LOOKBACK, end)
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

    Served through the ordinary tag cache, so a warm cache needs no Excel.
    """
    tag = MONEY_MARKET_ON_TAG.get(str(citi_index).upper())
    if tag is None:
        return pd.Series(dtype="float64")
    if quotes is None:
        from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes

        quotes = CitiVeloQuotes()
    frame = quotes.frame(
        [tag],
        "DAILY",
        start=start or datetime.date(2005, 1, 1),
        end=end or datetime.date.today(),
    )
    if frame is None or frame.empty or tag not in frame.columns:
        return pd.Series(dtype="float64")
    series = frame[tag].dropna().sort_index()
    series.index = pd.DatetimeIndex(series.index).normalize()
    return series[~series.index.duplicated(keep="last")]


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
    """
    citi_index = str(citi_index).upper()
    contributions: Dict[str, int] = {}

    official = official_fixings(curve_name) if prefer_official else pd.Series(dtype="float64")
    citi = citi_fixings(citi_index, quotes=quotes)
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
