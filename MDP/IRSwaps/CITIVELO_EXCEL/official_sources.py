r"""Overnight fixings from each currency's own publisher, for the curves Citi
does not cover.

Why this exists
---------------
:mod:`MDP.IRSwaps.CITIVELO_EXCEL.fixings` gets overnight fixings from Citi's
``RATES.MONEY_MARKETS.<ccy>.<index>.ON`` tags, which serve twelve of the twenty
curves. The other eight have no Citi tag at all, and a seasoned OIS cannot be
priced without the fixings it has already compounded over. This module fills in
what it can from the central banks and statistics agencies directly, following
the shape of :mod:`MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FixingsFetcher` - a
per-source method, dispatched through a map keyed by curve.

What actually serves
--------------------
Every endpoint below was probed on 2026-08-07. Three answered; five did not, and
they are recorded as unavailable **with the reason**, because a currency that
silently returns nothing is indistinguishable from one nobody tried.

=============  ==============================  ==========================
curve          source                          status
=============  ==============================  ==========================
USD-FEDFUNDS   NY Fed ``effr/search.json``     serves, from 2016
NOK-NOWA-1D    Norges Bank ``SHORT_RATES``     serves, 3,735 rows to 2011
ZAR-ZARONIA    SARB ``GetTimeseries...``       serves, dated range works
MXN-FONDEO-1D  Banxico SIE                     **needs a free API token**
DKK-TNDKK-1D   Nationalbanken                  no public API found
ILS-SHIR-1D    Bank of Israel                  SDMX serves, no SHIR flow
SGD-SORA-1D    MAS                             eservices under maintenance
THB-THOR-1D    Bank of Thailand                needs an API key
=============  ==============================  ==========================

Units
-----
Every method here returns **percent**, indexed by fixing date, ascending - the
unit :class:`~MDP.IRSwaps.CITIVELO_EXCEL.fixings.FixingsResult` carries and the
unit ``rl.IRS(leg2_rate_fixings=...)`` expects. Note this differs from
``FixingsFetcher``, whose methods return decimals; the conversion belongs at the
boundary and happens here, once, rather than at every call site.

Never invent a number
---------------------
A source that does not answer raises or returns empty. It never falls back to a
policy rate, a neighbouring currency, or a carried-forward constant: an OIS
priced off a fabricated fixing is wrong in a way that looks entirely healthy.
The one interpolation performed is calendar gap-filling *within* a series the
publisher did serve, which is the standard convention for a non-publication day.
"""

from __future__ import annotations

import datetime
import io
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import pandas as pd

__all__ = [
    "OFFICIAL_SOURCES",
    "UNAVAILABLE",
    "SourceStatus",
    "OfficialFixingsFetcher",
    "official_source_status",
]

_logger = logging.getLogger(__name__)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/csv, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

#: Currencies with no reachable public source, and exactly why. Measured
#: 2026-08-07 - see the module docstring table.
UNAVAILABLE: Dict[str, str] = {
    "MXN_T_FONDEO": (
        "Banxico's SIE API requires a free per-user token. Probed without one: "
        "HTTP 400 'Token invalido'. Set BANXICO_TOKEN and MXN starts serving; "
        "registration is a human step this code cannot do."
    ),
    "DKK_TNDKK": (
        "No public Danmarks Nationalbank API found. nationalbanken.statistikbank.dk "
        "returns 404 on every /api/v1 shape tried (tables, tableinfo, data, subjects), "
        "and DESTR is not carried by the ECB Data Portal's FM dataflow."
    ),
    "ILS_SHIR": (
        "Bank of Israel's SDMX endpoint serves (39 dataflows listed) but publishes no "
        "SHIR or TELBOR flow; BOI.STATISTICS/TLB 404s. The public GetInterest endpoint "
        "returns the POLICY rate (3.5%), which is not the overnight fixing."
    ),
    "SGD_SORA": (
        "MAS eservices.mas.gov.sg returns its maintenance page and the statistics API "
        "path 404s. Worth re-probing; this looks like an outage rather than a removal."
    ),
    "THB_THOR": (
        "Bank of Thailand's API requires a registered client key; the unauthenticated "
        "host refused the connection outright."
    ),
}


@dataclass(frozen=True)
class SourceStatus:
    """Whether a currency has an official source, and what it is."""

    citi_index: str
    available: bool
    description: str

    def __str__(self) -> str:  # pragma: no cover - operator sugar
        mark = "ok " if self.available else "-- "
        return f"{mark}{self.citi_index:<16}{self.description}"


def _get(url: str, *, timeout: float = 45.0) -> "object":
    import requests

    response = requests.get(url, headers=_UA, timeout=timeout)
    response.raise_for_status()
    return response


def _as_series(mapping: Dict[datetime.date, float]) -> pd.Series:
    if not mapping:
        return pd.Series(dtype="float64")
    series = pd.Series(mapping, dtype="float64").sort_index()
    series.index = pd.DatetimeIndex(series.index)
    return series


# ---------------------------------------------------------------------------
# the sources that answer
# ---------------------------------------------------------------------------


def effr_nyfed(start: datetime.date, end: datetime.date) -> pd.Series:
    """USD Fed Funds (EFFR) from the New York Fed's markets API.

    The same endpoint ``FixingsFetcher._effr_nyfrb`` uses. Kept here rather than
    imported because that class returns decimals and carries a QuantLib
    dependency this package does not otherwise need.
    """
    url = (
        "https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"
        f"?startDate={start:%Y-%m-%d}&endDate={end:%Y-%m-%d}"
    )
    payload = _get(url).json()
    rows = payload.get("refRates", [])
    return _as_series(
        {
            datetime.date.fromisoformat(row["effectiveDate"]): float(row["percentRate"])
            for row in rows
            if row.get("type") == "EFFR" and row.get("percentRate") is not None
        }
    )


def nowa_norges_bank(start: datetime.date, end: datetime.date) -> pd.Series:
    """NOK NOWA from Norges Bank's SDMX API.

    The series key matters: ``SHORT_RATES/B.NOWA.ON.R``. NOWA is NOT in the
    ``IR`` dataflow (which carries only the key policy rate), and the final
    ``R`` selects UNIT_MEASURE=Rate - ``T`` there returns the daily transaction
    COUNT, which is a plausible-looking integer and not a rate at all.
    """
    url = (
        "https://data.norges-bank.no/api/data/SHORT_RATES/B.NOWA.ON.R"
        f"?format=csv&startPeriod={start:%Y-%m-%d}&endPeriod={end:%Y-%m-%d}&locale=en"
    )
    text = _get(url).text
    frame = pd.read_csv(io.StringIO(text), sep=";")
    if frame.empty or "OBS_VALUE" not in frame:
        return pd.Series(dtype="float64")
    series = pd.Series(
        frame["OBS_VALUE"].astype(float).values,
        index=pd.to_datetime(frame["TIME_PERIOD"]),
    ).sort_index()
    return series[~series.index.duplicated(keep="last")]


def zaronia_sarb(start: datetime.date, end: datetime.date) -> pd.Series:
    """ZAR ZARONIA from the South African Reserve Bank.

    ``MMRD855A`` is ZARONIA's timeseries code, found by scanning the money-market
    section of ``CurrentMarketRates``. The undated form of this endpoint returns
    only the last ~25 observations; the dated form serves history.
    """
    url = (
        "https://custom.resbank.co.za/SarbWebApi/WebIndicators/Shared/"
        f"GetTimeseriesObservations/MMRD855A/{start:%Y-%m-%d}/{end:%Y-%m-%d}"
    )
    rows = _get(url).json()
    return _as_series(
        {
            pd.Timestamp(row["Period"]).date(): float(row["Value"])
            for row in rows
            if row.get("Value") is not None
        }
    )


def fondeo_banxico(start: datetime.date, end: datetime.date) -> pd.Series:
    """MXN overnight TIIE / Fondeo from Banxico's SIE API.

    Requires a free token in ``BANXICO_TOKEN``. Without it Banxico answers HTTP
    400 ``Token invalido``, so this raises with that instruction rather than
    returning an empty series that would read as "the rate does not exist".
    """
    token = os.environ.get("BANXICO_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "MXN fixings need a free Banxico SIE token in BANXICO_TOKEN "
            "(register at https://www.banxico.org.mx/SieAPIRest/service/v1/token)."
        )
    # SF331451 is the overnight TIIE (Fondeo Bancario) daily series.
    url = (
        "https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF331451/datos/"
        f"{start:%Y-%m-%d}/{end:%Y-%m-%d}?token={token}"
    )
    payload = _get(url).json()
    observations = payload["bmx"]["series"][0].get("datos", [])
    out: Dict[datetime.date, float] = {}
    for row in observations:
        try:
            out[datetime.datetime.strptime(row["fecha"], "%d/%m/%Y").date()] = float(row["dato"])
        except (KeyError, ValueError):
            continue
    return _as_series(out)


#: ``citi_index -> fetcher``. The dispatch map, mirroring ``FixingsFetcher``'s
#: ``_func_map``. Absence from this map means :data:`UNAVAILABLE` explains why.
OFFICIAL_SOURCES: Dict[str, Callable[[datetime.date, datetime.date], pd.Series]] = {
    "USD_FEDFUND": effr_nyfed,
    "NOK_NOWA": nowa_norges_bank,
    "ZAR_ZARONIA": zaronia_sarb,
    "MXN_T_FONDEO": fondeo_banxico,
}

_DESCRIPTIONS: Dict[str, str] = {
    "USD_FEDFUND": "EFFR, New York Fed markets API",
    "NOK_NOWA": "NOWA, Norges Bank SDMX SHORT_RATES/B.NOWA.ON.R",
    "ZAR_ZARONIA": "ZARONIA, SARB timeseries MMRD855A",
    "MXN_T_FONDEO": "Overnight TIIE, Banxico SIE SF331451 (needs BANXICO_TOKEN)",
}


def official_source_status() -> List[SourceStatus]:
    """One row per currency this module knows about, available or not.

    Used by the verification report so "no fixings for THB" is visibly a
    measured fact with a reason attached, not a gap in the table.
    """
    out: List[SourceStatus] = []
    for index, description in sorted(_DESCRIPTIONS.items()):
        needs_token = index == "MXN_T_FONDEO" and not os.environ.get("BANXICO_TOKEN", "").strip()
        out.append(SourceStatus(index, not needs_token, description))
    for index, reason in sorted(UNAVAILABLE.items()):
        if index in _DESCRIPTIONS:
            continue
        out.append(SourceStatus(index, False, reason))
    return out


class OfficialFixingsFetcher:
    """Fetch overnight fixings from each currency's own publisher.

    Instantiated per use; the only state is an in-process cache, because a
    backfill asks for the same currency once per day it builds.
    """

    def __init__(self, *, logger: Optional[logging.Logger] = None):
        self._logger = logger or _logger
        self._cache: Dict[tuple, pd.Series] = {}

    def available_for(self, citi_index: str) -> bool:
        return citi_index in OFFICIAL_SOURCES

    def reason_unavailable(self, citi_index: str) -> str:
        return UNAVAILABLE.get(
            citi_index, f"No official source is wired up for {citi_index}."
        )

    def fetch(
        self,
        citi_index: str,
        start: datetime.date,
        end: datetime.date,
    ) -> pd.Series:
        """Overnight fixings in PERCENT for ``[start, end]``, ascending.

        Raises
        ------
        KeyError
            When no source is wired up, carrying the measured reason.
        """
        fetcher = OFFICIAL_SOURCES.get(citi_index)
        if fetcher is None:
            raise KeyError(self.reason_unavailable(citi_index))
        key = (citi_index, start, end)
        if key not in self._cache:
            series = fetcher(start, end)
            self._logger.info(
                "official fixings %s: %d row(s) %s..%s",
                citi_index,
                len(series),
                series.index[0].date() if len(series) else "-",
                series.index[-1].date() if len(series) else "-",
            )
            self._cache[key] = series
        return self._cache[key]
