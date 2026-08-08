r"""Fetch Citi Velocity bond quotes in EOD, intraday or live mode.

This is the bond analogue of
:mod:`MDP.IRSwaps.CITIVELO_EXCEL.fetcher`, and it deliberately reuses that
module's :func:`~MDP.IRSwaps.CITIVELO_EXCEL.timestamps.resolve_request` rather
than growing a fourth mode dispatch. The reason is recorded there and is worth
repeating: ``pd.Timestamp`` is a subclass of ``datetime.datetime``, which is a
subclass of ``datetime.date``, so an ``isinstance`` ladder is wrong in **both**
directions - ``isinstance(x, date)`` swallows every intraday request, and an
``isinstance(x, datetime)`` branch placed first makes the midnight-is-EOD rule
unreachable.

One request for the whole basket
--------------------------------
Every bond's every value goes out as **one** batched call, not one call per bond.
A 300-name warm at eight values is 2,400 tags; issued per bond that is 300 round
trips into an Excel add-in whose memory only a human restart reclaims. The
batching seam is :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes`, which is
also where the cache lives, so a fully warm **EOD** request opens no workbook at
all.

That last claim is deliberately narrow. The ONLINE intraday path goes through
``fetch_windowed``, which takes the client directly and therefore neither reads
nor writes the tag cache - see below for why it has to. So a repeated intraday
request costs a live call every time, while a repeated EOD or offline-intraday
one does not.

Only what Citi actually serves is asked for
-------------------------------------------
Coverage is per bond and uneven - ``PRICE`` for 2,105 of 2,162 ISINs,
``ASW_4_USD`` for 1,081, and ``CAS`` for 381 of which exactly one is American
(``US3133EPSW68``, an FFCB agency; no US Treasury serves it) - and it is read
from the committed validation harvest through
:attr:`~MDP.CitiVelocityExcel.bonds.resolution.BondResolution.available_values`.
A value a bond does not serve is reported as ``unavailable`` and its tag is
**never built**. That is the whole point: an unserved tag that falls through to a
live ``CVTSHIST`` call, once per bond, is a warm that spends its Excel budget
discovering something already committed to JSON.

``unavailable`` and ``empty`` are different answers
---------------------------------------------------
``unavailable``
    Citi does not serve that value for that bond. Never requested. Asking again
    changes nothing.
``empty``
    Citi does serve it, and no row came back inside this window. Measured:
    ``OAS`` returned nothing over a one-week window and a full history over five
    years (``catalog/bond_values2.json``, ``valid_5y_only``), and ``ASW_4_JPY``
    behaved the same way. So an empty ``OAS`` is a **normal** outcome whose fix
    is a wider window.
``failed``
    The tag went out and the TRANSPORT failed for it: a rejected tag, an
    unentitled one, an add-in that is not signed in, an Excel that went away
    mid-run. Nothing here is evidence about the market and widening the window
    cannot help. The reason is carried per value.

Collapsing the first two would turn "widen your window" into "this bond has no
OAS", which is false for 1,401 of the 2,162 ISINs. Collapsing the third into
``empty`` tells a caller to widen a window when Excel disconnected - and, worse,
lets a 300-name warm come back silently partial during an add-in hiccup. When the
transport fails for EVERY tag in the request there is no per-tag information left
and :class:`BondQuoteTransportError` is raised instead.

Coverage that was never established is not coverage
---------------------------------------------------
The validation sweep covered **2,147 of the 2,162** ISINs. For the fifteen it
missed (thirteen Canadian, two Italian) ``available_values`` is empty, and that is
not a statement about what Citi serves. Those bonds are asked rather than assumed
away, and their quotes carry ``coverage_validated=False`` so no message about them
claims a coverage fact that was never checked.

The intraday path goes through the chunker
------------------------------------------
``CVTSHIST`` downsamples by **requested span**, silently, and the ``MI01`` cliff
is exactly 7 days (measured 2026-08-07; the block comes back looking like a
successful minute request with a tenth of the rows). So the live intraday path
runs through :func:`MDP.CitiVelocityExcel.windowed.fetch_windowed`, which tiles
the range under the cliff and *verifies* the spacing it got.

``fetch_windowed`` needs a connected client - it pushes and drops a worksheet per
window - so it cannot run offline. The **offline** intraday path therefore serves
from the tag cache through ``CitiVeloQuotes.frame`` with the window clamped to
:data:`MDP.CitiVelocityExcel.windowed.MAX_SPAN`, which is the same cliff
expressed as a bound instead of as a chunker. Nothing is silently coarsened
either way.
"""

from __future__ import annotations

import dataclasses
import datetime
import logging
import threading
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import pandas as pd

try:  # stdlib on 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - only on ancient interpreters
    from backports.zoneinfo import ZoneInfo  # type: ignore

from MDP.CitiVelocityExcel import tags as T
from MDP.CitiVelocityExcel.bonds import values as V
from MDP.CitiVelocityExcel.bonds.resolution import BondResolution
from MDP.CitiVelocityExcel.errors import CitiVelocityError
from MDP.CitiVelocityExcel.quotes import CitiVeloQuotes
from MDP.CitiVelocityExcel.windowed import MAX_SPAN, fetch_windowed
from MDP.IRSwaps.CITIVELO_EXCEL.timestamps import (
    ResolvedRequest,
    from_wire_naive,
    resolve_request,
    wire_timezone,
)

__all__ = [
    "BOND_MARKET_TIMEZONES",
    "CITI_QUOTE_PREFIX",
    "COMPUTED_FRB_VALUES",
    "DEFAULT_BOND_VALUES",
    "DEFAULT_MAX_PRICE_LAG",
    "BondQuoteTransportError",
    "CitiBondQuote",
    "CitiVeloBondFetcher",
    "build_pricer_args",
    "market_timezone",
]

_logger = logging.getLogger(__name__)


class BondQuoteTransportError(CitiVelocityError):
    """The vendor transport failed, so this request says nothing about the market.

    A ``CitiVelocityError`` (i.e. a ``RuntimeError``) rather than a ``ValueError``
    on purpose: the per-bond handler in ``FixedRateBondsMDP`` catches the bond-level
    ``ValueError`` family and drops that one bond, which is right for "no PRICE in
    this window" and badly wrong for "Excel went away" - the second must take the
    whole basket down rather than return a silently partial dict.
    """


#: Seven of the thirteen values Citi publishes per bond, chosen against the
#: universe this source actually serves. Re-derived from the committed 16,288-tag
#: harvest; coverage over the whole 2,162 ISINs, then over the 349 US Treasuries:
#: PRICE 2,105/349, YIELD 2,103/349, DURATION 2,097/349, SPREAD_TSY 1,803/349,
#: DV01 1,656/305, ASW_4_USD 1,081/253, ASW_4_AUD 1,120/348.
#:
#: Two values that look like they belong here are deliberately out:
#:
#: ``OAS`` (1,401 of 2,162; 304 of 349 US Treasuries) is **window-dependent** -
#: measured empty over one week and full over five years - and the default EOD
#: lookback is 21 days. Fetching it by default spends a column per bond on
#: something the default window cannot answer, which is the exact cost this module
#: exists to avoid. Ask for it explicitly, with a lookback to match:
#: ``citivelo_values=[..., "OAS"], eod_lookback=timedelta(days=1825)``.
#:
#: ``ASW_4_JPY`` (324 of 2,162; 56 of 349) is the rarest value Citi publishes.
#: ``ASW_4_AUD`` replaces it: 348 of the 349 US Treasuries carry it, against 253
#: for ``ASW_4_USD`` and 56 for JPY. ``FRB_ASW_SPREAD`` still defaults to the USD
#: leg, because that is the bond's own currency and the AUD leg is a CROSS-currency
#: asset swap - a different quantity, now merely reachable without a refetch.
#:
#: ``CAS`` and the remaining ``ASW_4_<CCY>`` legs are addressable and real
#: elsewhere (measured ``CND1000113G9.CAS`` = 43.4983); no US Treasury serves CAS.
DEFAULT_BOND_VALUES: Tuple[str, ...] = (
    "PRICE",
    "YIELD",
    "DURATION",
    "SPREAD_TSY",
    "DV01",
    "ASW_4_USD",
    "ASW_4_AUD",
)

#: How far ``PRICE`` may trail the newest value in the same response before
#: :func:`build_pricer_args` refuses to build a pricer at all.
#:
#: One day, and the choice has a known cost in both directions. The gap is
#: measured in CALENDAR time, so a Friday ``PRICE`` beside a Monday ``YIELD`` is
#: three days and refuses even though it is one business day; and a two-day gap
#: mid-week - the case this guard was written for, ``US91282CNJ61`` EOD 2026-08-06
#: with PRICE last printing 08-04 - refuses as it should. Building business-day
#: logic here would need a per-market calendar this module does not carry and
#: cannot get from the wire, and the failure it would introduce (a holiday
#: silently widening the tolerance) is worse than a refusal a caller can override
#: with ``max_price_lag``. The lag is recorded on the pricer either way.
DEFAULT_MAX_PRICE_LAG = datetime.timedelta(days=1)

#: The zone each bond market's trading day is bucketed by.
#:
#: **This is a market-convention table, not a measurement.** Citi stamps every
#: instrument in America/New_York whatever the currency (that part *is* measured -
#: see ``MDP/IRSwaps/CITIVELO_EXCEL/timestamps.py``), so a JGB print at 22:30 ET
#: on Tuesday belongs to Wednesday's Tokyo session, and bucketing it by the ET
#: calendar date puts a whole morning session on the wrong business day. The
#: entries below are the obvious domestic exchange zone for each of the eighteen
#: countries ``CVCURVEBOND`` populates; none has been checked against a session
#: boundary in Citi's own data the way the wire zone was.
#:
#: The failure this guards against is one business day of misdating on the
#: Asia/Pacific names, which is the same error the sibling curve source has
#: recorded and fixed (JPY_TONAR: the 19:00-06:59 ET block is ONE session and
#: belongs to the later date).
BOND_MARKET_TIMEZONES: Mapping[str, str] = {
    "BRA": "America/Sao_Paulo",
    "CHE": "Europe/Zurich",
    "CHN": "Asia/Shanghai",
    "DEU": "Europe/Berlin",
    "DNK": "Europe/Copenhagen",
    "ESP": "Europe/Madrid",
    "FRA": "Europe/Paris",
    "GBR": "Europe/London",
    "ITA": "Europe/Rome",
    "JPN": "Asia/Tokyo",
    "KOR": "Asia/Seoul",
    "MEX": "America/Mexico_City",
    "NLD": "Europe/Amsterdam",
    "NOR": "Europe/Oslo",
    "NZL": "Pacific/Auckland",
    "SWE": "Europe/Stockholm",
    "USA": "America/New_York",
    "ZAF": "Africa/Johannesburg",
}

#: What an unknown country falls back to. It is the wire zone, so the fallback is
#: "do not convert" rather than "guess" - a silent wrong conversion is worse than
#: a documented no-op.
_FALLBACK_MARKET_TZ = "America/New_York"

#: How far back the window is fetched behind the target before resolving as-of.
#: EOD is wide enough to cross a long weekend plus a holiday; the intraday and
#: live values sit under the measured ``MI01`` 7-day cliff by construction.
_LOOKBACK: Mapping[str, datetime.timedelta] = {
    "eod": datetime.timedelta(days=21),
    "intraday": datetime.timedelta(days=5),
    "live": datetime.timedelta(days=5),
}

#: The ``CVTSHIST`` frequency each mode is served at.
_FREQ: Mapping[str, str] = {"eod": "DAILY", "intraday": "MI01", "live": "MI01"}

#: Per-tag reasons that mean "the market held nothing here", as opposed to "the
#: fetch did not happen". ``block_parser`` records the first for a column that was
#: present and empty, and ``windowed`` records the second for a window that came
#: back with nothing; everything else it can say is a transport failure.
_EMPTY_REASONS = frozenset({"empty", "no data"})


def market_timezone(country: Optional[str]) -> str:
    """The IANA zone a country's bond session is bucketed by.

    Falls back to the wire zone for a country outside the eighteen
    ``CVCURVEBOND`` populates, which makes the day bucket a no-op rather than a
    guess. See :data:`BOND_MARKET_TIMEZONES` for what is and is not measured.
    """
    return BOND_MARKET_TIMEZONES.get(str(country or "").strip().upper(), _FALLBACK_MARKET_TZ)


@dataclasses.dataclass(frozen=True)
class CitiBondQuote:
    """Everything Citi served for one bond at one instant, plus what it did not.

    Attributes
    ----------
    isin
        The ISIN the tags were built from.
    cusip
        The CUSIP when one exists (US and CA), else ``None``.
    token
        Exactly what the caller originally asked for - a CUSIP, an ISIN, or the
        alias that was resolved to one upstream. Kept so an unexpected bond can
        be traced to the token that produced it.
    mode
        ``eod`` | ``intraday`` | ``live``, as decided by ``resolve_request``.
    as_of
        **Tz-aware, in the wire zone.** The newest constituent stamp at or before
        the request. When nothing served this is the requested instant itself, so
        the field is never naive and never ``None``; ``served`` says which.
    market_date
        The business date this quote belongs to **in the bond's own market**. For
        intraday and live the wire stamp is converted to
        :func:`market_timezone` first; for EOD it is Citi's own date label, left
        alone. Both halves matter: converting an Asia/Pacific intraday stamp is
        what stops a whole morning session landing a day early, and *not*
        converting an EOD label is what stops MXN's date going backwards (midnight
        ET is the previous day in Mexico City).
    quoted
        ``{citi_value: float}`` for every value that served a row. Keyed by the
        Citi token (``PRICE``, ``ASW_4_USD``), not by any repo-side name.
    tags
        ``{citi_value: tag}`` for every value that was actually requested.
    unavailable
        Values that were *asked for* and that Citi does not serve for this bond.
        **Never requested** on the wire. A subset of ``serves``'s complement.
    empty
        Values Citi does serve for this bond that returned no row in this window.
        Distinct from ``unavailable``; see the module docstring.
    failed
        ``{citi_value: reason}`` for values whose tag went out and whose TRANSPORT
        failed. Disjoint from ``empty``, and the distinction is the whole point:
        one means "widen the window", the other means "the fetch did not happen".
    serves
        This bond's whole served vocabulary out of the harvested validation set,
        independent of what was asked for. Carried because "Citi does not serve
        CAS for this bond" is knowable for a value nobody requested, and without
        it that question can only be answered "you did not ask for it" - which
        sends the reader to change their request rather than their expectation.
        **Empty means the sweep never covered this bond**, not that Citi serves
        nothing; ``coverage_validated`` is the flag that says which.
    coverage_validated
        Whether the harvested sweep covered this ISIN at all. ``False`` for the
        fifteen of 2,162 it missed.
    stamps
        ``{citi_value: tz-aware stamp}`` - each value is taken as-of
        independently, so an illiquid ``OAS`` can legitimately be older than the
        ``PRICE`` beside it, and the spread is visible rather than averaged away.
        This is not a curiosity: :func:`build_pricer_args` dates the pricer by
        ``stamps['PRICE']``, because that is the number it prices from.
    """

    isin: str
    cusip: Optional[str]
    token: str
    mode: str
    as_of: datetime.datetime
    quoted: Mapping[str, float]
    tags: Mapping[str, str]
    unavailable: Tuple[str, ...]
    empty: Tuple[str, ...]
    market_date: datetime.date
    market_timezone: str
    freq: str
    requested: Tuple[str, ...] = ()
    serves: Tuple[str, ...] = ()
    stamps: Mapping[str, datetime.datetime] = dataclasses.field(default_factory=dict)
    failed: Mapping[str, str] = dataclasses.field(default_factory=dict)
    coverage_validated: bool = True

    @property
    def served(self) -> bool:
        """Whether any value at all came back for this bond."""
        return bool(self.quoted)

    @property
    def constituent_spread(self) -> datetime.timedelta:
        """Newest minus oldest constituent stamp; zero when fewer than two served."""
        if len(self.stamps) < 2:
            return datetime.timedelta(0)
        return max(self.stamps.values()) - min(self.stamps.values())

    @property
    def price_lag(self) -> datetime.timedelta:
        """How far ``PRICE`` trails the newest value in the same response.

        Zero when PRICE *is* the newest, and zero when nothing served. This is the
        number that decides whether a pricer can honestly be built: everything the
        pricer computes comes from PRICE, and the quoted book beside it comes from
        whatever printed last.
        """
        stamp = self.stamps.get("PRICE")
        if stamp is None or not self.stamps:
            return datetime.timedelta(0)
        return max(self.stamps.values()) - stamp

    def get(self, citi_value: str) -> Optional[float]:
        """Citi's number for one value, or ``None`` if it did not serve."""
        return self.quoted.get(str(citi_value).strip().upper())

    def market_date_of(self, citi_value: str) -> Optional[datetime.date]:
        """The market date of ONE value's own print, or ``None`` if it did not serve.

        ``market_date`` is the date of the response as a whole - the newest stamp
        across every value. That is the right label for the response and the wrong
        one for a pricer, which is dated by the single quote it is built from.
        """
        stamp = self.stamps.get(str(citi_value).strip().upper())
        if stamp is None:
            return None
        return _market_date(self.mode, stamp, self.market_timezone)

    def quoted_book(self) -> Dict[str, float]:
        """The ``{citi_value: float}`` book for :data:`~...values.QUOTED_KEY`."""
        return {k: float(v) for k, v in self.quoted.items()}

    def coverage_book(self) -> Dict[str, Any]:
        """The book for :data:`~...values.COVERAGE_KEY`, as plain lists.

        Plain lists rather than tuples because this ends up inside a pricer's
        ``meta_data``, which is round-tripped through a JSON-ish DiskCache; a
        tuple would come back as a list anyway and the asymmetry would show up as
        a spurious cache miss in a comparison.
        """
        return {
            "requested": list(self.requested),
            "unavailable": list(self.unavailable),
            "empty": list(self.empty),
            "failed": sorted(self.failed),
            "serves": list(self.serves),
            "validated": bool(self.coverage_validated),
        }

    def failure_book(self) -> Dict[str, str]:
        """``{citi_value: reason}`` for :data:`~...values.FAILURES_KEY`."""
        return {str(k): str(v) for k, v in self.failed.items()}

    def provenance_book(self) -> Dict[str, Dict[str, Any]]:
        """Quoted-side provenance, keyed by Citi value token.

        Plain dicts, not :class:`~...values.Provenance` instances: this is stored
        on a pricer's ``meta_data`` and read back after a DiskCache round trip, so
        it must not depend on class identity. ``provenance_of`` reconstructs.
        """
        return {
            value: dataclasses.asdict(V.quoted_provenance(value, tag))
            for value, tag in self.tags.items()
            if value in self.quoted
        }

    def describe(self) -> str:
        lag = f", PRICE {self.price_lag} behind" if self.price_lag else ""
        unswept = "" if self.coverage_validated else ", coverage NOT validated"
        return (
            f"{self.isin} {self.mode} @ {self.as_of:%Y-%m-%d %H:%M:%S %Z} "
            f"({self.market_date} {self.market_timezone}): "
            f"{len(self.quoted)} quoted, {len(self.empty)} empty, "
            f"{len(self.failed)} failed, {len(self.unavailable)} unavailable"
            f"{lag}{unswept}"
        )


class CitiVeloBondFetcher:
    """Turn ``(resolutions, timestamp)`` into one :class:`CitiBondQuote` per bond.

    >>> from MDP.CitiVelocityExcel.bonds.resolution import resolve_bonds
    >>> resolved, _ = resolve_bonds(["91282CNJ6"])          # doctest: +SKIP
    >>> f = CitiVeloBondFetcher(offline=True)               # doctest: +SKIP
    >>> f.fetch(resolved.values(), datetime.date(2026, 8, 6))  # doctest: +SKIP
    {'US91282CNJ61': <CitiBondQuote ...>}

    Parameters
    ----------
    quotes
        A :class:`~MDP.CitiVelocityExcel.quotes.CitiVeloQuotes`. Built lazily when
        omitted, so a fully-cached request opens no workbook and needs no
        signed-in Excel.
    offline
        Serve only from the tag cache. Passed on to a lazily-built ``quotes``, and
        kept here as well because it also selects the intraday transport: offline
        cannot push the per-window worksheets ``fetch_windowed`` needs, so it
        clamps the window under the measured cliff instead.

        ``None`` (the default) adopts the state of an injected ``quotes``, which is
        published as ``CitiVeloQuotes.offline``. Left unreconciled, the natural
        spelling ``CitiVeloBondFetcher(quotes=CitiVeloQuotes(offline=True))`` took
        the ONLINE intraday path and ``client()`` raised inside what the caller
        believed was an offline fetch. Passing a value that CONTRADICTS the
        injected reader raises rather than picking a winner: ``offline=True`` over
        a live-capable reader still reaches Excel on any cache miss, which defeats
        the flag's stated purpose, and there is no reading of the pair that is
        safe to guess.
    values
        Default value list. ``None`` means :data:`DEFAULT_BOND_VALUES`.
    window
        Intraday chunk width. ``None`` takes ``windowed.DEFAULT_WINDOW``; it is
        validated against the measured cliff either way.
    eod_lookback, intraday_lookback
        How far back the window is fetched before resolving as-of. Widen the
        intraday one for an illiquid bond whose last print is days old - the
        chunker keeps each *request* under the cliff regardless, so a wide
        lookback costs calls rather than resolution.
    """

    def __init__(
        self,
        *,
        quotes: Optional[CitiVeloQuotes] = None,
        offline: Optional[bool] = None,
        values: Optional[Sequence[str]] = None,
        window: Optional[datetime.timedelta] = None,
        eod_lookback: Optional[datetime.timedelta] = None,
        intraday_lookback: Optional[datetime.timedelta] = None,
        client_kwargs: Optional[Mapping[str, Any]] = None,
    ):
        self._quotes = quotes
        self._owns_quotes = quotes is None
        # getattr rather than an isinstance check: a duck-typed reader in a test
        # that says nothing about its own state has nothing to reconcile, and must
        # not be forced to grow a property to stay usable.
        declared = getattr(quotes, "offline", None) if quotes is not None else None
        if offline is None:
            self._offline = bool(declared) if declared is not None else False
        else:
            self._offline = bool(offline)
            if declared is not None and bool(declared) != self._offline:
                raise ValueError(
                    f"offline={offline!r} contradicts the injected reader, which reports "
                    f"offline={bool(declared)!r}. This flag selects the intraday TRANSPORT "
                    f"here and the connect policy there, so a mismatch either crashes in "
                    f"client() or reaches Excel from a path documented as offline. Pass one "
                    f"or the other, not both."
                )
        self._values = tuple(values) if values is not None else DEFAULT_BOND_VALUES
        self._window = window
        intraday = intraday_lookback or _LOOKBACK["intraday"]
        self._lookback = {
            "eod": eod_lookback or _LOOKBACK["eod"],
            "intraday": intraday,
            "live": intraday,
        }
        self._client_kwargs = dict(client_kwargs or {})
        self._lock = threading.RLock()

    # -- lifecycle ------------------------------------------------------

    @property
    def offline(self) -> bool:
        return self._offline

    def quotes(self) -> CitiVeloQuotes:
        with self._lock:
            if self._quotes is None:
                self._quotes = CitiVeloQuotes(
                    offline=self._offline, client_kwargs=self._client_kwargs
                )
            return self._quotes

    def close(self) -> None:
        """Close the reader this fetcher OWNS, and leave an injected one alone.

        Nulling ``_quotes`` unconditionally was an escalation, not a tidy-up: the
        next ``quotes()`` built a fresh ``CitiVeloQuotes(offline=False)`` whose
        first cache miss calls ``connect()``, so ``with CitiVeloBondFetcher(quotes=
        my_fake) as f: ...`` followed by any later ``f.fetch(...)`` silently turned
        a hermetic fetcher into one that opens a live Excel - and ``_owns_quotes``
        stayed False, so nothing closed that client either (this package has a
        recorded 62-accumulated-workbook leak).
        """
        with self._lock:
            if self._quotes is not None and self._owns_quotes:
                self._quotes.close()
                self._quotes = None

    def __enter__(self) -> "CitiVeloBondFetcher":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- the request ----------------------------------------------------

    def plan(
        self,
        resolutions: Iterable[BondResolution],
        *,
        values: Optional[Sequence[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """What would be asked for, per bond, without asking for it.

        Split out from :meth:`fetch` so the "never request an unserved value"
        rule is testable on its own, and so a warm can size itself before it
        opens Excel.

        A bond the validation sweep never covered is asked for in full rather than
        skipped. ``available_values`` returning ``[]`` is not evidence: its own
        docstring says the sweep covered 2,147 of the 2,162 ISINs, and treating the
        gap as a coverage fact reported fifteen bonds as ones Citi does not serve
        without ever asking the wire. The entry carries ``validated=False`` so
        nothing downstream restates the claim either.

        Returns
        -------
        ``{isin: {'resolution', 'tags', 'unavailable', 'requested', 'validated'}}``
        """
        wanted = self._normalise_values(values)
        out: Dict[str, Dict[str, Any]] = {}
        for resolution in resolutions:
            validated = bool(resolution.available_values)
            served = [v for v in wanted if resolution.serves(v)] if validated else list(wanted)
            unavailable = tuple(v for v in wanted if v not in served)
            out[resolution.isin] = {
                "resolution": resolution,
                # Built here and only here: a tag for a KNOWN-unserved value does
                # not exist anywhere in this module.
                "tags": {v: T.bond(resolution.isin, v) for v in served},
                "unavailable": unavailable,
                "requested": tuple(served),
                "validated": validated,
            }
        return out

    def fetch(
        self,
        resolutions: Iterable[BondResolution],
        timestamp: Union[str, datetime.date, datetime.datetime, pd.Timestamp, None] = "live",
        values: Optional[Sequence[str]] = None,
        *,
        strict_tz: Optional[bool] = None,
        force_refresh: bool = False,
    ) -> Dict[str, CitiBondQuote]:
        """One :class:`CitiBondQuote` per bond, keyed by ISIN.

        Parameters
        ----------
        resolutions
            :class:`~MDP.CitiVelocityExcel.bonds.resolution.BondResolution` objects.
            Aliases (``CT10``) are **not** handled here - they are resolved to a
            CUSIP upstream, in ``FixedRateBondsMDP``, so that this repo keeps one
            alias table rather than four.
        timestamp
            ``'live'``/``None``, a ``date`` (EOD), a datetime at exactly midnight
            (also EOD - it is the common spelling of "that day", and it is the
            reading that round-trips, because the add-in stamps ``DAILY`` rows at
            midnight), or any other datetime (intraday).
        values
            Citi value tokens. ``None`` uses this fetcher's default.

        Raises
        ------
        BondQuoteTransportError
            When the transport failed for EVERY tag in the request. Returning a
            basket of bonds all reporting "no rows in this window" would be a
            statement about the market that this request cannot support.

        Notes
        -----
        Bonds that Citi does not quote at all are absent from the input by
        construction: ``resolve_bond`` raises for them. A bond present here with
        an empty ``quoted`` served nothing in this window, which is a different
        statement and is reported rather than dropped - and a bond whose values
        FAILED on the transport is a third statement again, on ``quote.failed``.
        """
        plan = self.plan(resolutions, values=values)
        if not plan:
            return {}

        request = resolve_request(timestamp, strict=strict_tz)
        freq = _FREQ[request.mode]
        start, end = self._window_bounds(request)

        # One call for the union of every bond's tags. Order is stable and
        # de-duplicated so two bonds sharing a tag cost one column, not two.
        all_tags: List[str] = []
        seen: set = set()
        for entry in plan.values():
            for tag in entry["tags"].values():
                if tag not in seen:
                    seen.add(tag)
                    all_tags.append(tag)

        frame, failed_tags = self._fetch_frame(
            all_tags, freq, start, end, force_refresh=force_refresh
        )
        return self._resolve(
            plan, request, frame, freq=freq, end=end, failed_tags=failed_tags
        )

    # -- internals ------------------------------------------------------

    def _normalise_values(self, values: Optional[Sequence[str]]) -> Tuple[str, ...]:
        """Upper-case, de-duplicate, and reject a token Citi has no such value for.

        Rejecting rather than ignoring: a typo'd value silently dropped here comes
        back as "Citi does not serve it for this bond", which sends the reader
        looking at coverage instead of at their own string.
        """
        raw = self._values if values is None else values
        out: List[str] = []
        for value in raw:
            token = V.spec_for(value).citi  # raises with the vocabulary in the message
            if token not in out:
                out.append(token)
        return tuple(out)

    def _window_bounds(self, request: ResolvedRequest) -> Tuple[datetime.datetime, datetime.datetime]:
        """The naive wire-zone ``[start, end]`` to ask ``CVTSHIST`` for."""
        if request.mode == "eod":
            end = datetime.datetime.combine(request.eod_date, datetime.time(23, 59, 59))
        elif request.mode == "intraday":
            end = request.wire_instant
        else:
            # Live is bounded ABOVE by now in the wire zone rather than left open:
            # an unbounded end lets a clock skew on the add-in side hand back a
            # future stamp, which then reads as a negative lag.
            end = datetime.datetime.now(wire_timezone()).replace(tzinfo=None)
        return end - self._lookback[request.mode], end

    def _fetch_frame(
        self,
        tags: Sequence[str],
        freq: str,
        start: datetime.datetime,
        end: datetime.datetime,
        *,
        force_refresh: bool,
    ) -> Tuple[pd.DataFrame, Dict[str, str]]:
        """``(frame, {tag: transport failure reason})`` by whichever transport fits.

        The second element is what keeps a dead transport from being reported as an
        empty market. Both halves of it are per TAG and neither includes "the
        window held no rows": ``CVTSHIST`` distinguishes "no such tag" from "no
        rows here" and so does this. When the transport failed for EVERY tag there
        is nothing per-tag left to say and :class:`BondQuoteTransportError` is
        raised instead - a caller must not be handed a basket of "empty" bonds
        because Excel went away.

        Not modelled: a PARTIAL window failure inside a chunked intraday range.
        The tags in the surviving windows still resolve, so an as-of can land on an
        older print than it would have with every window intact. The windows are
        logged, the affected tags are not individually knowable from
        ``fetch_windowed``'s per-window log, and inventing per-tag lineage here
        would be a guess. What that costs is one deliberate over-report: once ANY
        window has failed, a tag that produced nothing at all is attributed to the
        failure rather than to the market. That direction is chosen on purpose -
        "the fetch broke, retry" is recoverable advice, "widen the window" is not.
        """
        if not tags:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date")), {}

        if freq == "DAILY" or self._offline:
            if freq != "DAILY":
                # No client, so no per-window sheets, so no chunker. Clamp instead:
                # the cliff is a span threshold, and a request held under it is
                # served at full resolution. Measured 2026-08-07 - MI01 at 6 days
                # is 1-minute data, at 7 days it is 10-minute. Indexed by the
                # frequency actually asked for, not by MI01: a future coarse mode
                # would otherwise be clamped to MI01's 6 days against its own
                # measured 60, silently truncating 90% of the lookback.
                start = max(start, end - MAX_SPAN[freq])
            reported: Dict[str, str] = {}
            frame = self.quotes().frame(
                list(tags),
                freq,
                start=start,
                end=end,
                force_refresh=force_refresh,
                failures=reported,
            )
            return frame, self._transport_failures(reported, tags)

        series, windows = fetch_windowed(
            self.quotes().client(), list(tags), freq, start, end, window=self._window
        )
        # "no data" is this window holding no rows - the market, not the transport.
        broken = [w for w in windows if w.error and w.error.strip().lower() != "no data"]
        if broken:
            _logger.warning(
                "citivelo bonds: %d of %d %s windows failed: %s",
                len(broken), len(windows), freq, "; ".join(str(w) for w in broken[:3]),
            )
        reported = {}
        if broken:
            reason = "; ".join(dict.fromkeys(w.error for w in broken))[:400]
            reported = {t: reason for t in tags if t not in series}
        failed = self._transport_failures(reported, tags)
        if not series:
            return pd.DataFrame(index=pd.DatetimeIndex([], name="Date")), failed
        ordered = [t for t in tags if t in series]
        frame = pd.concat({t: series[t] for t in ordered}, axis=1)[ordered]
        frame.index.name = "Date"
        return frame.sort_index(), failed

    @staticmethod
    def _transport_failures(reported: Mapping[str, str], tags: Sequence[str]) -> Dict[str, str]:
        """The subset of per-tag reasons that are about the TRANSPORT, not the market.

        ``CitiVeloQuotes.series`` hands back the add-in's own per-tag reasons, and
        one of them - ``"empty"`` - means the column was there and held no rows in
        this window. That is the ``empty`` classification, whose documented fix is
        a wider window. Everything else (``"bad tag"``, ``"no column"``,
        ``"#NAME?"``, ``"no block"``, a COM disconnect) means the number was never
        asked for or was refused.
        """
        wanted = {str(t) for t in tags}
        failed = {
            str(tag): str(reason)
            for tag, reason in dict(reported or {}).items()
            # Restricted to this request's own tags: a shared reader's failure
            # record is per fetch, and attributing someone else's rejected tag
            # here would raise the all-tags alarm on a request that was fine.
            if str(tag) in wanted
            and str(reason).strip().lower() not in _EMPTY_REASONS
        }
        if failed and len(failed) >= len(wanted):
            raise BondQuoteTransportError(
                f"Every one of the {len(wanted)} bond tag(s) in this request failed on the "
                f"transport: {'; '.join(sorted(set(failed.values())))[:400]}. This is not an "
                f"empty market - Citi was never asked, or was asked and refused - so no bond in "
                f"this basket can be reported as 'no rows in the window'. Check that Excel is "
                f"alive and the add-in is signed in, then retry."
            )
        return failed

    def _resolve(
        self,
        plan: Mapping[str, Mapping[str, Any]],
        request: ResolvedRequest,
        frame: pd.DataFrame,
        *,
        freq: str,
        end: datetime.datetime,
        failed_tags: Optional[Mapping[str, str]] = None,
    ) -> Dict[str, CitiBondQuote]:
        """Per bond, per value, the newest print at or before the target."""
        # The EOD search runs to the END of the requested day, because a daily row
        # could in principle be stamped at any time of it; live is unbounded above
        # only in the sense that the window already ended at "now".
        target: Optional[pd.Timestamp]
        if request.mode == "live":
            target = None
        elif request.mode == "intraday":
            target = pd.Timestamp(request.wire_instant)
        else:
            target = pd.Timestamp(
                datetime.datetime.combine(request.eod_date, datetime.time(23, 59, 59))
            )

        failed_by_tag = dict(failed_tags or {})
        out: Dict[str, CitiBondQuote] = {}
        for isin, entry in plan.items():
            resolution: BondResolution = entry["resolution"]
            quoted: Dict[str, float] = {}
            stamps: Dict[str, datetime.datetime] = {}
            empty: List[str] = []
            failed: Dict[str, str] = {}

            for value, tag in entry["tags"].items():
                series = frame[tag].dropna() if tag in frame.columns else pd.Series(dtype=float)
                if target is not None and not series.empty:
                    series = series[series.index <= target]
                if series.empty:
                    reason = failed_by_tag.get(tag)
                    if reason:
                        failed[value] = reason
                    else:
                        empty.append(value)
                    continue
                quoted[value] = float(series.iloc[-1])
                stamps[value] = from_wire_naive(series.index[-1])

            if stamps:
                as_of = max(stamps.values())
            else:
                # Nothing served. The instant is still the one that was asked for,
                # so as_of stays tz-aware and comparable; `served` is False and the
                # empty list says which values produced nothing.
                as_of = from_wire_naive(target if target is not None else end)

            country = resolution.descriptor.country if resolution.descriptor else ""
            tz_name = market_timezone(country)
            out[isin] = CitiBondQuote(
                isin=isin,
                cusip=resolution.cusip,
                token=resolution.token,
                mode=request.mode,
                as_of=as_of,
                quoted=quoted,
                tags=dict(entry["tags"]),
                unavailable=tuple(entry["unavailable"]),
                empty=tuple(empty),
                market_date=_market_date(request.mode, as_of, tz_name),
                market_timezone=tz_name,
                freq=freq,
                requested=tuple(entry["requested"]),
                serves=tuple(resolution.available_values),
                stamps=stamps,
                failed=failed,
                coverage_validated=bool(entry.get("validated", True)),
            )
        return out


def _market_date(
    mode: str, as_of: datetime.datetime, tz_name: str
) -> datetime.date:
    """The business date a quote belongs to, in the bond's own market.

    **Intraday and live convert; EOD does not**, and that asymmetry is the point.

    Citi stamps every instrument in America/New_York, so an Asia/Pacific session
    straddles two ET dates - the sibling curve source measured JPY_TONAR running
    19:00 ET through 06:59 ET the next day as one continuous block belonging to
    the LATER date. Bucketing an intraday stamp by its ET calendar date puts a
    whole morning session one business day early.

    An EOD row is different: it is stamped with the label **Citi** assigned it,
    at midnight ET, and re-deriving that label through a local zone moves it for
    every market west of New York - midnight ET is the previous day in Mexico
    City, so MXN's EOD date would silently go backwards. So EOD keeps the wire
    date of the row that actually answered - which is Citi's own label, and which
    is NOT necessarily the date that was asked for: an as-of search over a
    Saturday resolves to Friday's close, and dating that quote Saturday would
    price a Friday price one day forward.

    Takes a bare ``mode`` and ONE stamp rather than the whole request, because the
    same rule has to answer it for a single value's own print - which is how
    :func:`build_pricer_args` dates the pricer.
    """
    if mode == "eod":
        return as_of.date()
    return as_of.astimezone(ZoneInfo(tz_name)).date()


# ------------------------------------------------------------------ #
#                     handing a quote to a pricer                    #
# ------------------------------------------------------------------ #

#: Every ``FixedRateBondValue`` the pricer derives locally from Citi's ``PRICE``,
#: with the unit each is in. Citi also publishes ``YIELD``, ``DURATION`` and
#: ``DV01``, and those numbers are kept in the quoted book - but the pricer is
#: built from ``PRICE`` and re-solves its own yield, so what ``FRB_YTM`` returns
#: is the computed number and the provenance says so. Recording it as "quoted"
#: because Citi happened to publish a yield in the same response would be a false
#: audit trail, and the two differ by whatever the clean/dirty and compounding
#: readings are wrong by - which is exactly what the calibration exists to settle.
COMPUTED_FRB_VALUES: Mapping[str, str] = {
    "YTM": "percent",
    "DIRTY_PRICE": "price_points",
    "NPV": "currency",
    "PV01": "currency_per_bp",
    "DV01": "currency_per_bp",
    "MOD_DURATION": "years",
    "CONVEXITY": "years_squared",
}

#: Prefix for a quoted provenance entry displaced by a computed one of the same
#: name. Exactly one name collides today - ``DV01`` is both a Citi value token and
#: a ``FixedRateBondValue`` member, and on this source they are DIFFERENT NUMBERS:
#: Citi publishes its own DV01 (scale and sign unverified) while ``FRB_DV01``
#: returns the backend's PV01 off the locally re-solved yield.
#:
#: The flat book therefore records what ``FRB_DV01`` actually returns - computed -
#: and Citi's published one keeps its provenance under ``CITI:DV01`` rather than
#: being silently overwritten. ``SPREAD_TSY``, ``OAS`` and ``CAS`` share a name
#: across the two namespaces too, but there they mean the same quoted number and
#: there is nothing to displace.
CITI_QUOTE_PREFIX = "CITI:"

#: Backend token -> (pricer class name, provenance backend label).
_BACKENDS: Mapping[str, Tuple[str, str, str]] = {
    "QL": ("ql_frb_id", "QLFixedRateBondPricer", "quantlib"),
    "RL": ("rl_frb_id", "RLFixedRateBondPricer", "rateslib"),
}


def build_pricer_args(
    quote: CitiBondQuote,
    *,
    backend: str,
    ref_meta: Mapping[str, Any],
    frb_id: str = "USTS",
    source: str = "citivelo_excel",
    max_price_lag: Optional[datetime.timedelta] = DEFAULT_MAX_PRICE_LAG,
) -> Dict[str, Any]:
    """The ``_build_pricer_from_args`` payload for one Citi bond quote.

    Lives here rather than in ``FixedRateBondsMDP`` so the branch there stays a
    dispatch and this stays testable without a market data provider.

    ``clean_price`` is Citi's ``PRICE``. **That reading is UNVERIFIED** - if the
    number is in fact dirty, every downstream yield is wrong by the accrued
    interest, which on the calibration set runs 0.0163 to 3.1844 price points.
    The interpretation is therefore written into the provenance book rather than
    asserted: ``provenance_of(meta, 'CLEAN_PRICE').verified`` is ``False`` and its
    ``note`` says what would settle it. Nothing here quietly promotes it - and the
    seven values solved FROM it inherit that standing rather than declaring
    themselves verified.

    Dated by the quote it is priced from
    ------------------------------------
    ``reference_date`` is ``stamps['PRICE']``'s market date, **not** the quote's
    ``market_date``. The two differ whenever the values in one response disagree,
    which happens for real: on ``US91282CNJ61`` EOD 2026-08-06 the last PRICE print
    was 08-04 while YIELD, DURATION, SPREAD_TSY and DV01 kept printing through
    08-06. ``market_date`` is derived from the NEWEST stamp, so pricing off PRICE
    while dating by the response handed QuantLib and rateslib a two-day-old clean
    price with today's reference date, and both then applied two extra days of
    accrual to it. FRB_YTM, FRB_MOD_DURATION, FRB_DV01, FRB_NPV and every spline
    residual built on that pricer were wrong, silently, with a provenance book
    saying the number was fine.

    When they disagree
    ------------------
    The disagreement is **recorded always** (``citivelo_price_lag_seconds``,
    ``citivelo_constituent_spread_seconds``, and both dates side by side) and
    **refused past a threshold** - ``max_price_lag``, defaulting to
    :data:`DEFAULT_MAX_PRICE_LAG`. Refusing is the deliberate choice: dating by
    PRICE makes the pricer internally consistent, but the quoted book beside it
    still holds a YIELD and a SPREAD_TSY from a different day, so any comparison
    across the two - which is most of what this source exists for - is comparing
    days, not bonds. A number that is quietly two days old is worse than no number,
    because only one of the two is visible downstream. Pass a wider
    ``max_price_lag`` (or ``None``) to accept it anyway; the pricer is still dated
    by PRICE.

    Parameters
    ----------
    backend
        ``'QL'`` or ``'RL'``. This selects the *key* in the returned dict, because
        ``_build_pricer_from_args`` dispatches on key presence (``ql_frb_id`` vs
        ``rl_frb_id``) rather than on any explicit backend field.
    ref_meta
        The UST reference-data row for this bond: ``issue_date``,
        ``maturity_date``, ``cpn`` and whatever else the row carried. Passed
        through unchanged apart from the Velocity books added below.
    max_price_lag
        Refuse when ``PRICE`` trails the newest served value by more than this.
        ``None`` disables the check.

    Raises
    ------
    ValueError
        For an unknown ``backend``. A programming error, and deliberately NOT a
        :class:`~...values.NoQuotedPriceError`, so a caller that drops a bond per
        failure does not drop every bond in the basket over one.
    values.NoQuotedPriceError
        When Citi served no ``PRICE`` for this bond in this window. A pricer
        cannot be built without a quote, and substituting one would be inventing
        a market.
    values.StalePriceError
        When ``PRICE`` is older than ``max_price_lag`` behind the rest of the
        response.
    """
    token = str(backend).strip().upper()
    try:
        id_key, pricer_cls, backend_label = _BACKENDS[token]
    except KeyError:
        raise ValueError(f"Unknown bond pricing backend {backend!r}; use 'QL' or 'RL'.") from None

    price = quote.get("PRICE")
    if price is None:
        if "PRICE" in quote.failed:
            why = f"the fetch for PRICE FAILED: {quote.failed['PRICE']}"
        elif "PRICE" in quote.unavailable:
            why = "Citi does not serve PRICE for it"
        elif not quote.coverage_validated:
            why = (
                "it returned no PRICE row, and this bond's coverage was never validated "
                "(the sweep covered 2,147 of 2,162 ISINs), so nothing here says whether Citi "
                "serves it at all"
            )
        else:
            why = (
                f"it returned no PRICE row in the {quote.freq} window ending "
                f"{quote.as_of:%Y-%m-%d %H:%M}"
            )
        raise V.NoQuotedPriceError(
            f"No Citi PRICE for {quote.isin} ({quote.token}): {why}. "
            f"Served: {', '.join(sorted(quote.quoted)) or '(nothing)'}."
        )

    # A quote that carries a PRICE always carries its stamp - they are written
    # together - but a hand-built one need not, and falling back to the response's
    # own label is the only honest answer when the price's own date is unknown.
    price_stamp = quote.stamps.get("PRICE") or quote.as_of
    price_date = quote.market_date_of("PRICE") or quote.market_date
    lag = quote.price_lag
    if lag > datetime.timedelta(0):
        _logger.warning(
            "citivelo bonds: %s PRICE last printed %s, %s behind the newest value in the same "
            "response (%s). Pricing at the PRICE date.",
            quote.isin, price_date, lag, quote.market_date,
        )
    if max_price_lag is not None and lag > max_price_lag:
        raise V.StalePriceError(
            f"Citi's PRICE for {quote.isin} ({quote.token}) last printed {price_date}, {lag} "
            f"behind the newest value in the same response ({quote.market_date}). The pricer "
            f"would be dated {price_date} while the quoted book beside it - "
            f"{', '.join(sorted(v for v in quote.quoted if v != 'PRICE')) or '(nothing else)'} - "
            f"carries numbers from up to {quote.market_date}, so anything comparing the two "
            f"compares days. Ask for an earlier instant, or pass max_price_lag to accept it."
        )

    price_tag = quote.tags["PRICE"]
    provenance: Dict[str, Dict[str, Any]] = dict(quote.provenance_book())
    # CLEAN_PRICE is the FRB-side name for the same number, recorded under both
    # so a consumer asking about the value it actually called does not have to
    # know Citi's spelling.
    price_provenance = V.quoted_provenance("PRICE", price_tag)
    provenance["CLEAN_PRICE"] = dataclasses.asdict(price_provenance)
    for frb_value, unit in COMPUTED_FRB_VALUES.items():
        computed = dataclasses.asdict(
            V.computed_provenance(
                backend_label,
                f"{pricer_cls}.{frb_value.lower()}",
                unit=unit,
                inputs=price_tag,
                # A number solved from an unverified quote is not verified. All
                # seven of these come out of Citi's PRICE, whose clean-vs-dirty
                # reading is worth up to 3.1844 price points; hardcoding True here
                # made a consumer filtering on `verified` keep every number that
                # inherits the uncertainty and drop the only one that declares it.
                verified=price_provenance.verified,
                note=(
                    ""
                    if price_provenance.verified
                    else f"Inherits the standing of its input: {price_provenance.note}"
                ),
            )
        )
        displaced = provenance.get(frb_value)
        if displaced is not None and displaced.get("origin") == "quoted":
            # See CITI_QUOTE_PREFIX. Keyed aside rather than dropped, so the fact
            # that Citi ALSO published a number under this name stays auditable.
            provenance[f"{CITI_QUOTE_PREFIX}{frb_value}"] = displaced
        provenance[frb_value] = computed

    meta: Dict[str, Any] = dict(ref_meta)
    # NAIVE, and that is load-bearing. `carry_roll._infer_pricing_timestamp` reads
    # this exact field and branches on `tzinfo is not None` BEFORE its
    # midnight-means-date rule, so an offset-bearing spelling here - which was the
    # only one in FixedRateBondsMDP - made an EOD pricer classify as INTRADAY, and
    # `_infer_universe_source` then expanded the carry/roll universe against
    # USTS_WEBULL_WSJ_LIVE-RL, a live intraday broker feed, over the network, at a
    # historical midnight. Every sibling branch writes naive; so does this one. The
    # wire offset is kept below, where no classifier looks.
    meta["timestamp"] = price_stamp.replace(tzinfo=None).isoformat()
    meta["isin"] = quote.isin
    meta["citivelo_mode"] = quote.mode
    meta["citivelo_freq"] = quote.freq
    meta["citivelo_market_date"] = price_date.isoformat()
    meta["citivelo_market_timezone"] = quote.market_timezone
    # The response's own label and instant, beside the price's. They differ exactly
    # when the constituents disagree, and both are needed to audit that.
    meta["citivelo_basket_market_date"] = quote.market_date.isoformat()
    meta["citivelo_as_of"] = quote.as_of.isoformat()
    meta["citivelo_price_timestamp"] = price_stamp.isoformat()
    meta["citivelo_price_lag_seconds"] = float(lag.total_seconds())
    meta["citivelo_constituent_spread_seconds"] = float(
        quote.constituent_spread.total_seconds()
    )
    meta[V.QUOTED_KEY] = quote.quoted_book()
    meta[V.COVERAGE_KEY] = quote.coverage_book()
    meta[V.FAILURES_KEY] = quote.failure_book()
    meta[V.PROVENANCE_KEY] = provenance

    return {
        id_key: frb_id,
        "reference_date": price_date.isoformat(),
        "clean_price": float(price),
        "meta_data": meta,
        "schema": 1,
        "source": source,
    }
