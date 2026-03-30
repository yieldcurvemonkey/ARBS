from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import itertools
import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from Caching.timeseries_cache import _atomic_write_bytes, _write_parquet_bytes

logger = logging.getLogger(__name__)

_CACHE_SCHEMA = 1
_DEFAULT_TIMEOUT = 20
_DEFAULT_CACHE_TTL = dt.timedelta(hours=6)
_DEFAULT_CORE_COMPRESSION = "zstd"
_DEFAULT_BULK_CHUNK_WEEKS = 13
_DEFAULT_PROXY_TTL_SECONDS = 600
_USER_AGENT = "Mozilla/5.0 (compatible; ARBS ForexFactoryCalendarFetcher/1.0)"
_CACHE_LOCK = threading.Lock()
_PROXY_LOCK = threading.Lock()
_FOREX_FACTORY_PROXY_STATE: dict[str, object] = {
    "lock": threading.RLock(),
    "initialized": False,
}

_RETURN_COLUMNS = [
    "EventId",
    "WeekAnchor",
    "Date",
    "TimeLabel",
    "Timestamp",
    "TimestampNYC",
    "CalendarTimeZone",
    "Currency",
    "Impact",
    "ImpactRank",
    "Title",
    "DetailLevel",
    "Actual",
    "Forecast",
    "Previous",
    "ActualOutcome",
    "PreviousRevised",
    "PreviousRevisionDirection",
    "SourceURL",
]


class ForexFactoryImpact(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    HOLIDAY = "holiday"
    NON_ECONOMIC = "non_economic"
    UNKNOWN = "unknown"


class ForexFactoryTheme(str, Enum):
    GLOBAL_MACRO = "global_macro"
    FED_SPEAKERS = "fed_speakers"
    ECB_SPEAKERS = "ecb_speakers"
    BOE_SPEAKERS = "boe_speakers"
    BOJ_SPEAKERS = "boj_speakers"
    RBA_SPEAKERS = "rba_speakers"
    RBNZ_SPEAKERS = "rbnz_speakers"
    BOC_SPEAKERS = "boc_speakers"
    SNB_SPEAKERS = "snb_speakers"
    GLOBAL_CENTRAL_BANK_SPEAKERS = "global_central_bank_speakers"
    US_LABOR = "us_labor"
    US_NFP = "us_nfp"
    US_INFLATION = "us_inflation"
    US_CPI = "us_cpi"
    US_PCE = "us_pce"
    US_RATES = "us_rates"
    US_TREASURY_AUCTIONS = "us_treasury_auctions"
    US_GROWTH = "us_growth"
    US_CONSUMER = "us_consumer"
    US_HOUSING = "us_housing"
    US_PMI = "us_pmi"
    EUROZONE_INFLATION = "eurozone_inflation"
    EUROZONE_GROWTH = "eurozone_growth"
    EUROZONE_PMI = "eurozone_pmi"
    EUROZONE_RATES = "eurozone_rates"
    UK_INFLATION = "uk_inflation"
    UK_LABOR = "uk_labor"
    UK_GROWTH = "uk_growth"
    UK_PMI = "uk_pmi"
    JAPAN_INFLATION = "japan_inflation"
    JAPAN_GROWTH = "japan_growth"
    JAPAN_RATES = "japan_rates"
    CHINA_INFLATION = "china_inflation"
    CHINA_GROWTH = "china_growth"
    CHINA_CREDIT = "china_credit"
    AUSTRALIA_LABOR = "australia_labor"
    AUSTRALIA_INFLATION = "australia_inflation"
    CANADA_LABOR = "canada_labor"
    CANADA_INFLATION = "canada_inflation"
    GLOBAL_INFLATION = "global_inflation"
    GLOBAL_LABOR = "global_labor"
    GLOBAL_PMI = "global_pmi"
    GLOBAL_GROWTH = "global_growth"
    GLOBAL_RATES = "global_rates"
    ENERGY = "energy"


@dataclass(frozen=True)
class _ThemeSpec:
    description: str
    currencies: tuple[str, ...] = ()
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    impacts: tuple[ForexFactoryImpact, ...] = ()

    def matches(self, frame: pd.DataFrame) -> pd.Series:
        mask = pd.Series(True, index=frame.index, dtype=bool)

        if self.currencies:
            mask &= frame["Currency"].isin(self.currencies)

        if self.impacts:
            mask &= frame["Impact"].isin([impact.value for impact in self.impacts])

        if self.include_patterns:
            include_mask = pd.Series(False, index=frame.index, dtype=bool)
            for pattern in self.include_patterns:
                include_mask |= frame["Title"].str.contains(pattern, case=False, regex=True, na=False)
            mask &= include_mask

        for pattern in self.exclude_patterns:
            mask &= ~frame["Title"].str.contains(pattern, case=False, regex=True, na=False)

        return mask


_NYC_TIMEZONE = ZoneInfo("America/New_York")
_SPEECH_ACTION = r"(?:Speaks|Remarks|Testifies|Participates|Interview|Press Conference)"

_FED_SPEAKER_PATTERNS = (
    rf"\bFOMC Member\b.*\b{_SPEECH_ACTION}\b",
    rf"\b(?:Fed Chair|Chair Powell|Powell)\b.*\b{_SPEECH_ACTION}\b",
)
_ECB_SPEAKER_PATTERNS = (
    rf"\bECB President\b.*\b{_SPEECH_ACTION}\b",
    rf"\bECB Chief Economist\b.*\b{_SPEECH_ACTION}\b",
    rf"\bECB Exec Board\b.*\b{_SPEECH_ACTION}\b",
    rf"\bECB Governing Council\b.*\b{_SPEECH_ACTION}\b",
    rf"\bGerman Buba President\b.*\b{_SPEECH_ACTION}\b",
)
_BOE_SPEAKER_PATTERNS = (
    rf"\bMPC Member\b.*\b{_SPEECH_ACTION}\b",
    rf"\bBOE Gov\b.*\b{_SPEECH_ACTION}\b",
    rf"\bGov Bailey\b.*\b{_SPEECH_ACTION}\b",
)
_BOJ_SPEAKER_PATTERNS = (
    rf"\bBOJ (?:Gov|Deputy Gov|Board Member)\b.*\b{_SPEECH_ACTION}\b",
)
_RBA_SPEAKER_PATTERNS = (
    rf"\bRBA (?:Gov|Deputy Gov|Assist Gov)\b.*\b{_SPEECH_ACTION}\b",
)
_RBNZ_SPEAKER_PATTERNS = (
    rf"\bRBNZ (?:Gov|Deputy Gov)\b.*\b{_SPEECH_ACTION}\b",
)
_BOC_SPEAKER_PATTERNS = (
    rf"\bBOC Gov\b.*\b{_SPEECH_ACTION}\b",
    rf"\bGov Council Member\b.*\b{_SPEECH_ACTION}\b",
    rf"\bDeputy Gov\b.*\b{_SPEECH_ACTION}\b",
)
_SNB_SPEAKER_PATTERNS = (
    rf"\bSNB Chairman\b.*\b{_SPEECH_ACTION}\b",
    rf"\bGov Board Member\b.*\b{_SPEECH_ACTION}\b",
)
_GLOBAL_CENTRAL_BANK_SPEAKER_PATTERNS = (
    _FED_SPEAKER_PATTERNS
    + _ECB_SPEAKER_PATTERNS
    + _BOE_SPEAKER_PATTERNS
    + _BOJ_SPEAKER_PATTERNS
    + _RBA_SPEAKER_PATTERNS
    + _RBNZ_SPEAKER_PATTERNS
    + _BOC_SPEAKER_PATTERNS
    + _SNB_SPEAKER_PATTERNS
)

_INFLATION_PATTERNS = (
    r"\b(?:Core |Trimmed Mean )?CPI\b",
    r"\b(?:Core )?PCE(?: Price Index)?\b",
    r"\b(?:Core )?PPI\b",
    r"\bRPI\b",
    r"\bHICP\b",
    r"\bCPIF\b",
    r"\bImport Prices\b",
    r"\bExport Prices\b",
    r"\bInflation Expectations\b",
    r"\bNational Core CPI\b",
    r"\bTokyo Core CPI\b",
    r"\bBOJ Core CPI\b",
    r"\bSPPI\b",
)
_LABOR_PATTERNS = (
    r"\b(?:Non-Farm )?Employment Change\b",
    r"\bUnemployment Rate\b",
    r"\bAverage Hourly Earnings\b",
    r"\bAverage Weekly Hours\b",
    r"\bLabor Force Participation Rate\b",
    r"\bADP (?:Non-Farm Employment Change|Weekly Employment Change)\b",
    r"\b(?:Initial|Continuing|Unemployment) Claims\b",
    r"\bJOLTS Job Openings\b",
    r"\bChallenger Job Cuts\b",
    r"\bEmployment Cost Index\b",
    r"\b(?:Revised )?Nonfarm Productivity\b",
    r"\b(?:Revised )?Unit Labor Costs\b",
    r"\bClaimant Count Change\b",
    r"\bAverage Earnings Index\b",
    r"\bILO Unemployment Rate\b",
    r"\bLabor Cost Index\b",
    r"\bWage Price Index\b",
)
_PMI_PATTERNS = (
    r"\b(?:Flash |Final )?Manufacturing PMI\b",
    r"\b(?:Flash |Final )?Services PMI\b",
    r"\b(?:Flash |Final )?Composite PMI\b",
    r"\bISM Manufacturing PMI\b",
    r"\bISM Services PMI\b",
    r"\bChicago PMI\b",
    r"\bManufacturing PMI\b",
    r"\bServices PMI\b",
)
_GROWTH_PATTERNS = (
    r"\bGDP\b",
    r"\bRetail Sales\b",
    r"\bIndustrial Production\b",
    r"\bCapacity Utilization\b",
    r"\bDurable Goods\b",
    r"\bFactory Orders\b",
    r"\bBusiness Inventories\b",
    r"\bCurrent Account\b",
    r"\bTrade Balance\b",
    r"\bGoods Trade Balance\b",
    r"\bConstruction Spending\b",
    r"\bBusiness Climate\b",
    r"\bConsumer Confidence\b",
    r"\bConsumer Sentiment\b",
    r"\bLeading Index\b",
    r"\bFixed Asset Investment\b",
)
_CONSUMER_PATTERNS = (
    r"\bRetail Sales\b",
    r"\bCore Retail Sales\b",
    r"\bConsumer Confidence\b",
    r"\bConsumer Sentiment\b",
    r"\bConsumer Credit\b",
    r"\bPersonal Spending\b",
    r"\bPersonal Income\b",
    r"\bUoM Inflation Expectations\b",
)
_HOUSING_PATTERNS = (
    r"\bHousing Starts\b",
    r"\bBuilding Permits\b",
    r"\bExisting Home Sales\b",
    r"\bNew Home Sales\b",
    r"\bPending Home Sales\b",
    r"\bHPI\b",
    r"\bCase-Shiller\b",
    r"\bMortgage Delinquencies\b",
    r"\bMortgage Applications\b",
)
_AUCTION_PATTERNS = (
    r"\bTreasury .* Auction\b",
    r"\b(?:2|3|5|7|10|20|30)-y (?:Bond|Note) Auction\b",
    r"\b(?:4|8|13|17|26|52)-Week Bill Auction\b",
    r"\bBond Auction\b",
    r"\bNote Auction\b",
    r"\bBill Auction\b",
)
_RATE_DECISION_PATTERNS = (
    r"\bFederal Funds Rate\b",
    r"\bCash Rate\b",
    r"\bOfficial Bank Rate\b",
    r"\bMain Refinancing Rate\b",
    r"\bDeposit Facility Rate\b",
    r"\bFOMC Statement\b",
    r"\bFOMC Press Conference\b",
    r"\bMonetary Policy Summary\b",
    r"\bMonetary Policy Statement\b",
    r"\bRBA Rate Statement\b",
    r"\bRBA Press Conference\b",
    r"\bECB Press Conference\b",
    r"\bMonetary Policy Meeting Minutes\b",
    r"\bSummary of Opinions\b",
    r"\bSummary of Deliberations\b",
)
_ENERGY_PATTERNS = (
    r"\bCrude Oil Inventories\b",
    r"\bAPI Weekly Statistical Bulletin\b",
    r"\bNatural Gas Storage\b",
)
_CHINA_CREDIT_PATTERNS = (
    r"\bNew Loans\b",
    r"\bM2 Money Supply\b",
    r"\bTotal Social Financing\b",
    r"\bAggregate Financing\b",
)

_THEME_SPECS: dict[ForexFactoryTheme, _ThemeSpec] = {
    ForexFactoryTheme.GLOBAL_MACRO: _ThemeSpec(
        description="All Forex Factory macro events: speakers, decisions, auctions, and economic releases.",
    ),
    ForexFactoryTheme.FED_SPEAKERS: _ThemeSpec(
        description="Fed and FOMC speaker events for USD.",
        currencies=("USD",),
        include_patterns=_FED_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.ECB_SPEAKERS: _ThemeSpec(
        description="ECB and euro-area central bank speakers.",
        currencies=("EUR",),
        include_patterns=_ECB_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.BOE_SPEAKERS: _ThemeSpec(
        description="Bank of England and MPC speakers.",
        currencies=("GBP",),
        include_patterns=_BOE_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.BOJ_SPEAKERS: _ThemeSpec(
        description="Bank of Japan speakers.",
        currencies=("JPY",),
        include_patterns=_BOJ_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.RBA_SPEAKERS: _ThemeSpec(
        description="Reserve Bank of Australia speakers.",
        currencies=("AUD",),
        include_patterns=_RBA_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.RBNZ_SPEAKERS: _ThemeSpec(
        description="Reserve Bank of New Zealand speakers.",
        currencies=("NZD",),
        include_patterns=_RBNZ_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.BOC_SPEAKERS: _ThemeSpec(
        description="Bank of Canada speakers.",
        currencies=("CAD",),
        include_patterns=_BOC_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.SNB_SPEAKERS: _ThemeSpec(
        description="Swiss National Bank speakers.",
        currencies=("CHF",),
        include_patterns=_SNB_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.GLOBAL_CENTRAL_BANK_SPEAKERS: _ThemeSpec(
        description="Global central-bank speakers across major DM currencies.",
        include_patterns=_GLOBAL_CENTRAL_BANK_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.US_LABOR: _ThemeSpec(
        description="Broader USD labor-market releases.",
        currencies=("USD",),
        include_patterns=_LABOR_PATTERNS,
    ),
    ForexFactoryTheme.US_NFP: _ThemeSpec(
        description="Core US payroll report components.",
        currencies=("USD",),
        include_patterns=(
            r"\bNon-Farm Employment Change\b",
            r"\bUnemployment Rate\b",
            r"\bAverage Hourly Earnings\b",
            r"\bAverage Weekly Hours\b",
            r"\bLabor Force Participation Rate\b",
        ),
        exclude_patterns=(r"\bADP\b",),
    ),
    ForexFactoryTheme.US_INFLATION: _ThemeSpec(
        description="USD inflation prints and inflation-expectation releases.",
        currencies=("USD",),
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.US_CPI: _ThemeSpec(
        description="USD CPI releases.",
        currencies=("USD",),
        include_patterns=(r"\b(?:Core )?CPI\b", r"\bConsumer Price Index\b"),
    ),
    ForexFactoryTheme.US_PCE: _ThemeSpec(
        description="USD PCE releases.",
        currencies=("USD",),
        include_patterns=(r"\b(?:Core )?PCE(?: Price Index)?\b",),
    ),
    ForexFactoryTheme.US_RATES: _ThemeSpec(
        description="USD rates-sensitive events including FOMC and Treasury auctions.",
        currencies=("USD",),
        include_patterns=_RATE_DECISION_PATTERNS + _AUCTION_PATTERNS + _FED_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.US_TREASURY_AUCTIONS: _ThemeSpec(
        description="US Treasury bill, note, and bond auctions.",
        currencies=("USD",),
        include_patterns=_AUCTION_PATTERNS,
    ),
    ForexFactoryTheme.US_GROWTH: _ThemeSpec(
        description="US growth and activity indicators.",
        currencies=("USD",),
        include_patterns=_GROWTH_PATTERNS,
    ),
    ForexFactoryTheme.US_CONSUMER: _ThemeSpec(
        description="US consumer and spending indicators.",
        currencies=("USD",),
        include_patterns=_CONSUMER_PATTERNS,
    ),
    ForexFactoryTheme.US_HOUSING: _ThemeSpec(
        description="US housing-market releases.",
        currencies=("USD",),
        include_patterns=_HOUSING_PATTERNS,
    ),
    ForexFactoryTheme.US_PMI: _ThemeSpec(
        description="US PMI and survey-based activity indicators.",
        currencies=("USD",),
        include_patterns=_PMI_PATTERNS + (
            r"\bEmpire State Manufacturing Index\b",
            r"\bPhiladelphia Fed Manufacturing Index\b",
            r"\bRichmond Manufacturing Index\b",
            r"\bDallas Fed Manufacturing Index\b",
        ),
    ),
    ForexFactoryTheme.EUROZONE_INFLATION: _ThemeSpec(
        description="Euro-area inflation releases.",
        currencies=("EUR",),
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.EUROZONE_GROWTH: _ThemeSpec(
        description="Euro-area growth and activity indicators.",
        currencies=("EUR",),
        include_patterns=_GROWTH_PATTERNS,
    ),
    ForexFactoryTheme.EUROZONE_PMI: _ThemeSpec(
        description="Euro-area PMI releases.",
        currencies=("EUR",),
        include_patterns=_PMI_PATTERNS,
    ),
    ForexFactoryTheme.EUROZONE_RATES: _ThemeSpec(
        description="Euro-area rates, ECB decisions, and related speakers.",
        currencies=("EUR",),
        include_patterns=_RATE_DECISION_PATTERNS + _AUCTION_PATTERNS + _ECB_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.UK_INFLATION: _ThemeSpec(
        description="UK inflation releases.",
        currencies=("GBP",),
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.UK_LABOR: _ThemeSpec(
        description="UK labor-market releases.",
        currencies=("GBP",),
        include_patterns=_LABOR_PATTERNS,
    ),
    ForexFactoryTheme.UK_GROWTH: _ThemeSpec(
        description="UK growth and activity indicators.",
        currencies=("GBP",),
        include_patterns=_GROWTH_PATTERNS,
    ),
    ForexFactoryTheme.UK_PMI: _ThemeSpec(
        description="UK PMI releases.",
        currencies=("GBP",),
        include_patterns=_PMI_PATTERNS,
    ),
    ForexFactoryTheme.JAPAN_INFLATION: _ThemeSpec(
        description="Japanese inflation releases.",
        currencies=("JPY",),
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.JAPAN_GROWTH: _ThemeSpec(
        description="Japanese growth and activity indicators.",
        currencies=("JPY",),
        include_patterns=_GROWTH_PATTERNS,
    ),
    ForexFactoryTheme.JAPAN_RATES: _ThemeSpec(
        description="Japanese rates, BOJ communications, and JGB auctions.",
        currencies=("JPY",),
        include_patterns=_RATE_DECISION_PATTERNS + _AUCTION_PATTERNS + _BOJ_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.CHINA_INFLATION: _ThemeSpec(
        description="Chinese inflation releases.",
        currencies=("CNY",),
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.CHINA_GROWTH: _ThemeSpec(
        description="Chinese growth and activity indicators.",
        currencies=("CNY",),
        include_patterns=_GROWTH_PATTERNS + _PMI_PATTERNS,
    ),
    ForexFactoryTheme.CHINA_CREDIT: _ThemeSpec(
        description="Chinese credit and liquidity indicators.",
        currencies=("CNY",),
        include_patterns=_CHINA_CREDIT_PATTERNS,
    ),
    ForexFactoryTheme.AUSTRALIA_LABOR: _ThemeSpec(
        description="Australian labor-market releases.",
        currencies=("AUD",),
        include_patterns=_LABOR_PATTERNS,
    ),
    ForexFactoryTheme.AUSTRALIA_INFLATION: _ThemeSpec(
        description="Australian inflation releases.",
        currencies=("AUD",),
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.CANADA_LABOR: _ThemeSpec(
        description="Canadian labor-market releases.",
        currencies=("CAD",),
        include_patterns=_LABOR_PATTERNS,
    ),
    ForexFactoryTheme.CANADA_INFLATION: _ThemeSpec(
        description="Canadian inflation releases.",
        currencies=("CAD",),
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.GLOBAL_INFLATION: _ThemeSpec(
        description="Global inflation releases across major economies.",
        include_patterns=_INFLATION_PATTERNS,
    ),
    ForexFactoryTheme.GLOBAL_LABOR: _ThemeSpec(
        description="Global labor-market releases across major economies.",
        include_patterns=_LABOR_PATTERNS,
    ),
    ForexFactoryTheme.GLOBAL_PMI: _ThemeSpec(
        description="Global PMI and survey-based activity releases.",
        include_patterns=_PMI_PATTERNS,
    ),
    ForexFactoryTheme.GLOBAL_GROWTH: _ThemeSpec(
        description="Global growth, activity, and trade indicators.",
        include_patterns=_GROWTH_PATTERNS,
    ),
    ForexFactoryTheme.GLOBAL_RATES: _ThemeSpec(
        description="Global rates events including central-bank speakers, decisions, and auctions.",
        include_patterns=_RATE_DECISION_PATTERNS + _AUCTION_PATTERNS + _GLOBAL_CENTRAL_BANK_SPEAKER_PATTERNS,
    ),
    ForexFactoryTheme.ENERGY: _ThemeSpec(
        description="Energy and inventory releases useful for oil and gas macro.",
        include_patterns=_ENERGY_PATTERNS,
    ),
}

_IMPACT_CLASS_MAP = {
    "red": (ForexFactoryImpact.HIGH.value, 3),
    "ora": (ForexFactoryImpact.MEDIUM.value, 2),
    "yel": (ForexFactoryImpact.LOW.value, 1),
    "gra": (ForexFactoryImpact.HOLIDAY.value, 0),
    "gry": (ForexFactoryImpact.NON_ECONOMIC.value, 0),
    "grey": (ForexFactoryImpact.NON_ECONOMIC.value, 0),
}


def _default_cache_dir() -> Path:
    try:
        from platformdirs import user_cache_dir

        return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "forex_factory_calendar"
    except Exception:
        if os.name == "nt":
            return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "forex_factory_calendar"
        return Path.home() / ".cache" / "arbs" / "forex_factory_calendar"


def _default_core_base_dir() -> Path:
    arbs_cache = os.getenv("ARBS_CACHE_DIR")
    if arbs_cache:
        return Path(arbs_cache) / "forex_factory_calendar_store"
    try:
        from platformdirs import user_cache_dir

        return Path(user_cache_dir(appname="ARBS", appauthor=False)) / "forex_factory_calendar_store"
    except Exception:
        if os.name == "nt":
            return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "ARBS" / "Cache" / "forex_factory_calendar_store"
        return Path.home() / ".cache" / "arbs" / "forex_factory_calendar_store"


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=_RETURN_COLUMNS)


def _coerce_date(value: dt.date | dt.datetime | str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return pd.Timestamp(value).date()


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _event_text(node) -> str:
    if node is None:
        return ""
    return _normalize_text(node.get_text(" ", strip=True))


def _calendar_week_anchor(value: dt.date) -> dt.date:
    return value - dt.timedelta(days=value.weekday())


def _format_day_query(value: dt.date) -> str:
    return f"{value.strftime('%b').lower()}{value.day}.{value.year}"


def _coerce_timezone(tz_name: str | None) -> ZoneInfo | None:
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return None


def _clean_enum_values(values: str | Enum | Sequence[str | Enum] | None, enum_cls: type[Enum]) -> list[Enum]:
    if values is None:
        return []
    if isinstance(values, (str, enum_cls)):
        values = [values]

    cleaned: list[Enum] = []
    for value in values:
        if isinstance(value, enum_cls):
            cleaned.append(value)
        else:
            cleaned.append(enum_cls(value))
    return cleaned


def _get_calendar_sync(base_dir: str | os.PathLike[str] | Path | None = None):
    from Caching.supabase_engine import SUPABASE_ENABLED

    if not SUPABASE_ENABLED:
        return None

    from Caching.supabase_engine import get_engine
    from Caching.supabase_forex_factory_calendar_sync import SupabaseForexFactoryCalendarSync

    if base_dir is None:
        return SupabaseForexFactoryCalendarSync.from_defaults()
    return SupabaseForexFactoryCalendarSync(base_dir=Path(base_dir), engine=get_engine())


def _socks_proxy_available() -> bool:
    return importlib.util.find_spec("socks") is not None or importlib.util.find_spec("socksio") is not None


def _build_socks5h(host: str) -> dict[str, str]:
    user = os.getenv("NORDVPN_USER", "3G5mmfKXWfCGFGT4yDL34Tzn")
    pwd = os.getenv("NORDVPN_PASS", "VN33uViQZp6pXVzdgsGskhNg")
    if not user or not pwd:
        raise ValueError("Missing NORDVPN_USER/NORDVPN_PASS in environment.")
    url = f"socks5h://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:1080"
    return {"http": url, "https": url}


def _preflight_proxy(proxies: Mapping[str, str] | None, timeout: int = 6) -> bool:
    try:
        response = requests.get(
            "https://api.ipify.org?format=json",
            proxies=proxies,
            timeout=timeout,
            headers={"Connection": "close", "User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
        return True
    except Exception:
        return False


def _proxy_rotation_enabled() -> bool:
    raw = os.getenv("ARBS_FOREX_FACTORY_ENABLE_NORD_ROTATION")
    if raw is None or raw == "":
        return True
    return raw.strip().lower() not in {"0", "false", "f", "no", "n", "off"}


def _proxy_ttl_seconds() -> int:
    raw = os.getenv("ARBS_FOREX_FACTORY_PROXY_TTL_SECONDS")
    if raw is None or raw == "":
        return _DEFAULT_PROXY_TTL_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_PROXY_TTL_SECONDS


def _default_proxy_hosts() -> list[str | None]:
    configured = os.getenv("ARBS_FOREX_FACTORY_PROXY_HOSTS")
    if configured:
        hosts: list[str | None] = []
        for token in configured.split(","):
            token = token.strip()
            if not token:
                continue
            if token.lower() in {"none", "direct"}:
                hosts.append(None)
            else:
                hosts.append(token)
        if hosts:
            return hosts
    return [
        "atlanta.us.socks.nordhold.net",
        "chicago.us.socks.nordhold.net",
        "dallas.us.socks.nordhold.net",
        "los-angeles.us.socks.nordhold.net",
        "new-york.us.socks.nordhold.net",
        "phoenix.us.socks.nordhold.net",
        "san-francisco.us.socks.nordhold.net",
        "us.socks.nordhold.net",
        None,
    ]


def _init_proxy_state() -> dict[str, object]:
    state = _FOREX_FACTORY_PROXY_STATE
    with state["lock"]:
        if bool(state.get("initialized")):
            return state

        hosts = list(_default_proxy_hosts())
        socks_enabled = _socks_proxy_available() and _proxy_rotation_enabled()
        if not socks_enabled:
            hosts = [None]
        random.shuffle(hosts)
        state.update(
            {
                "initialized": True,
                "hosts": hosts,
                "cycler": itertools.cycle(hosts),
                "socks_enabled": socks_enabled,
                "ttl": _proxy_ttl_seconds(),
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
            }
        )
        return state


def _get_cached_proxy() -> tuple[dict[str, str] | None, str | None]:
    state = _init_proxy_state()
    ttl = float(state.get("ttl", 0.0) or 0.0)
    if ttl > 0 and (time.time() - float(state.get("chosen_at", 0.0) or 0.0)) < ttl:
        return state.get("proxies"), state.get("host")
    return None, None


def _choose_proxy(*, force_rotate: bool = False) -> tuple[dict[str, str] | None, str | None]:
    state = _init_proxy_state()
    if not force_rotate:
        cached_proxy, cached_host = _get_cached_proxy()
        if cached_proxy is not None or cached_host is not None:
            return cached_proxy, cached_host

    hosts = list(state.get("hosts") or [])
    cycler = state.get("cycler")
    if not hosts or cycler is None:
        return None, None

    last_host = state.get("host")
    direct_fallback: tuple[dict[str, str] | None, str | None] | None = None
    proxied_fallback: tuple[dict[str, str] | None, str | None] | None = None

    for _ in range(len(hosts)):
        host = next(cycler)
        if host is None:
            if direct_fallback is None:
                direct_fallback = (None, None)
            continue
        if not bool(state.get("socks_enabled")):
            continue
        try:
            proxies = _build_socks5h(host)
        except Exception:
            continue
        if _preflight_proxy(proxies):
            state["proxies"] = proxies
            state["host"] = host
            state["chosen_at"] = time.time()
            return proxies, host
        if proxied_fallback is None and host != last_host:
            proxied_fallback = (proxies, host)

    fallback = proxied_fallback or direct_fallback or (None, None)
    state["proxies"], state["host"] = fallback
    state["chosen_at"] = time.time()
    return fallback


class ForexFactoryCalendarFetcher:
    base_url = "https://www.forexfactory.com/calendar"

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        cache_ttl: dt.timedelta = _DEFAULT_CACHE_TTL,
        global_timeout: int = _DEFAULT_TIMEOUT,
        proxies: Mapping[str, str] | None = None,
        output_timezone: str | None = "UTC",
        core_base_dir: str | os.PathLike[str] | None = None,
        core_compression: str = _DEFAULT_CORE_COMPRESSION,
        proxy_rotation_enabled: bool | None = None,
    ) -> None:
        if session is None:
            self._session = requests.Session()
            self._session.headers["User-Agent"] = _USER_AGENT
        else:
            self._session = session
            self._session.headers.setdefault("User-Agent", _USER_AGENT)
        self._session.headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        if proxies:
            self._session.proxies.update(dict(proxies))

        self._cache_dir = Path(cache_dir) if cache_dir else _default_cache_dir()
        self._cache_ttl = cache_ttl
        self._global_timeout = global_timeout
        self._output_timezone_name = output_timezone
        self._output_timezone = _coerce_timezone(output_timezone)
        self._core_base_dir = Path(core_base_dir) if core_base_dir else _default_core_base_dir()
        self._core_compression = core_compression
        self._manual_proxies = dict(proxies) if proxies else None
        self._proxy_rotation_enabled = (
            _proxy_rotation_enabled() if proxy_rotation_enabled is None and not proxies else bool(proxy_rotation_enabled)
        )
        if output_timezone and self._output_timezone is None:
            raise ValueError(f"Unknown output timezone: {output_timezone}")

    @classmethod
    def theme_descriptions(cls) -> dict[ForexFactoryTheme, str]:
        return {theme: spec.description for theme, spec in _THEME_SPECS.items()}

    @property
    def core_base_dir(self) -> Path:
        return self._core_base_dir

    @property
    def proxy_rotation_enabled(self) -> bool:
        return self._proxy_rotation_enabled

    def fetch_theme(
        self,
        theme: ForexFactoryTheme | str,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
        **kwargs,
    ) -> pd.DataFrame:
        return self.fetch_range(start_date=start_date, end_date=end_date, themes=[theme], **kwargs)

    def fetch_week(
        self,
        anchor_date: dt.date | dt.datetime | str,
        *,
        themes: ForexFactoryTheme | str | Sequence[ForexFactoryTheme | str] | None = None,
        currencies: str | Sequence[str] | None = None,
        impacts: ForexFactoryImpact | str | Sequence[ForexFactoryImpact | str] | None = None,
        use_cache: bool = True,
        force_refresh: bool = False,
        use_core: bool = True,
        pull_core: bool = False,
        push_core: bool = False,
        show_tqdm: bool = False,
    ) -> pd.DataFrame:
        week_anchor = _calendar_week_anchor(_coerce_date(anchor_date))
        week_end = week_anchor + dt.timedelta(days=6)
        return self.fetch_range(
            start_date=week_anchor,
            end_date=week_end,
            themes=themes,
            currencies=currencies,
            impacts=impacts,
            use_cache=use_cache,
            force_refresh=force_refresh,
            use_core=use_core,
            pull_core=pull_core,
            push_core=push_core,
            show_tqdm=show_tqdm,
        )

    def fetch_range(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
        *,
        themes: ForexFactoryTheme | str | Sequence[ForexFactoryTheme | str] | None = None,
        currencies: str | Sequence[str] | None = None,
        impacts: ForexFactoryImpact | str | Sequence[ForexFactoryImpact | str] | None = None,
        use_cache: bool = True,
        force_refresh: bool = False,
        use_core: bool = True,
        pull_core: bool = False,
        push_core: bool = False,
        bulk_chunk_weeks: int = _DEFAULT_BULK_CHUNK_WEEKS,
        show_tqdm: bool = True,
    ) -> pd.DataFrame:
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        if end < start:
            raise ValueError("end_date must be on or after start_date")

        if use_core:
            frame = self._fetch_range_via_core(
                start=start,
                end=end,
                use_cache=use_cache,
                force_refresh=force_refresh,
                pull_core=pull_core,
                push_core=push_core,
                bulk_chunk_weeks=bulk_chunk_weeks,
                show_tqdm=show_tqdm,
            )
        else:
            frame = self._fetch_range_from_web(
                start=start,
                end=end,
                use_cache=use_cache,
                force_refresh=force_refresh,
                bulk_chunk_weeks=bulk_chunk_weeks,
                show_tqdm=show_tqdm,
            )

        return self._apply_filters(frame, themes=themes, currencies=currencies, impacts=impacts)

    def fetch_year(
        self,
        year: int,
        **kwargs,
    ) -> pd.DataFrame:
        start = dt.date(int(year), 1, 1)
        end = dt.date(int(year), 12, 31)
        return self.fetch_range(start, end, **kwargs)

    def fetch_years(
        self,
        years: int | Sequence[int],
        *,
        combine: bool = True,
        **kwargs,
    ) -> pd.DataFrame | dict[int, pd.DataFrame]:
        if isinstance(years, int):
            years = [years]
        cleaned_years = [int(year) for year in years]
        results = {year: self.fetch_year(year, **kwargs) for year in cleaned_years}
        if not combine:
            return results
        non_empty = [frame for frame in results.values() if not frame.empty]
        if not non_empty:
            return _empty_frame()
        return self._normalize_frame(pd.concat(non_empty, ignore_index=True))

    def rotate_proxy(self) -> tuple[dict[str, str] | None, str | None]:
        if not self._proxy_rotation_enabled:
            return self._clear_session_proxy()
        return self._configure_session_proxy(force_rotate_proxy=True)

    def _apply_filters(
        self,
        frame: pd.DataFrame,
        *,
        themes: ForexFactoryTheme | str | Sequence[ForexFactoryTheme | str] | None,
        currencies: str | Sequence[str] | None,
        impacts: ForexFactoryImpact | str | Sequence[ForexFactoryImpact | str] | None,
    ) -> pd.DataFrame:
        if frame.empty:
            return frame.copy()

        mask = pd.Series(True, index=frame.index, dtype=bool)

        if currencies is not None:
            if isinstance(currencies, str):
                currencies = [currencies]
            normalized_currencies = {str(currency).upper() for currency in currencies}
            mask &= frame["Currency"].isin(normalized_currencies)

        cleaned_impacts = _clean_enum_values(impacts, ForexFactoryImpact)
        if cleaned_impacts:
            mask &= frame["Impact"].isin([impact.value for impact in cleaned_impacts])

        cleaned_themes = _clean_enum_values(themes, ForexFactoryTheme)
        if cleaned_themes:
            theme_mask = pd.Series(False, index=frame.index, dtype=bool)
            for theme in cleaned_themes:
                theme_mask |= _THEME_SPECS[theme].matches(frame)
            mask &= theme_mask

        return frame.loc[mask].reset_index(drop=True)

    def _cache_path(self, week_anchor: dt.date) -> Path:
        return self._cache_dir / f"{week_anchor.isoformat()}.json"

    def _partition_dir(self, trading_date: dt.date) -> Path:
        return self._core_base_dir / f"date={trading_date.isoformat()}"

    def has_day(self, trading_date: dt.date | dt.datetime | str) -> bool:
        trading_date = _coerce_date(trading_date)
        part_dir = self._partition_dir(trading_date)
        return part_dir.exists() and any(part_dir.glob("*.parquet"))

    def available_local_dates(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
    ) -> set[dt.date]:
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        dates: set[dt.date] = set()
        current = start
        while current <= end:
            if self.has_day(current):
                dates.add(current)
            current += dt.timedelta(days=1)
        return dates

    def write_day(
        self,
        trading_date: dt.date | dt.datetime | str,
        frame: pd.DataFrame,
        *,
        overwrite: bool = False,
        push_to_core: bool = False,
    ) -> dict[str, object]:
        trading_date = _coerce_date(trading_date)
        storage_frame = self._storage_frame(frame)
        if not storage_frame.empty:
            storage_frame = storage_frame.loc[storage_frame["Date"] == trading_date].reset_index(drop=True)
        table = pa.Table.from_pandas(storage_frame, preserve_index=False)
        payload = _write_parquet_bytes(table, compression=self._core_compression)
        sha = hashlib.sha256(payload).hexdigest()
        part_dir = self._partition_dir(trading_date)
        final_path = part_dir / f"{sha}.parquet"

        if overwrite:
            for old_path in part_dir.glob("*.parquet"):
                try:
                    old_path.unlink()
                except OSError:
                    pass

        if not final_path.exists():
            _atomic_write_bytes(final_path, payload)

        meta = {
            "path": str(final_path),
            "size": len(payload),
            "sha256": sha,
            "rows": int(len(storage_frame)),
        }
        if push_to_core:
            self.push_day(trading_date)
        return meta

    def read_day(
        self,
        trading_date: dt.date | dt.datetime | str,
        *,
        pull_missing: bool = False,
    ) -> pd.DataFrame:
        trading_date = _coerce_date(trading_date)
        part_dir = self._partition_dir(trading_date)
        pq_files = sorted(part_dir.glob("*.parquet"))
        if not pq_files and pull_missing:
            self.pull_day(trading_date)
            pq_files = sorted(part_dir.glob("*.parquet"))
        if not pq_files:
            return _empty_frame()

        tables = [pq.read_table(path) for path in pq_files]
        table = tables[0] if len(tables) == 1 else pa.concat_tables(tables, promote_options="default")
        frame = table.to_pandas()
        return self._normalize_frame(frame)

    def read_range(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
        *,
        pull_missing: bool = False,
    ) -> pd.DataFrame:
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        frames: list[pd.DataFrame] = []
        current = start
        while current <= end:
            day_frame = self.read_day(current, pull_missing=pull_missing)
            if not day_frame.empty:
                frames.append(day_frame)
            current += dt.timedelta(days=1)

        if not frames:
            return _empty_frame()
        frame = pd.concat(frames, ignore_index=True)
        return self._normalize_frame(frame)

    def push_day(self, trading_date: dt.date | dt.datetime | str) -> bool:
        trading_date = _coerce_date(trading_date)
        sync = _get_calendar_sync(self._core_base_dir)
        if sync is None:
            return False
        return bool(sync.push_day(trading_date))

    def pull_day(self, trading_date: dt.date | dt.datetime | str) -> bool:
        trading_date = _coerce_date(trading_date)
        sync = _get_calendar_sync(self._core_base_dir)
        if sync is None:
            return False
        return bool(sync.pull_day(trading_date))

    def prefetch_range(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
    ) -> list[dt.date]:
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        sync = _get_calendar_sync(self._core_base_dir)
        if sync is None:
            return []
        return list(sync.prefetch_range(start, end))

    def _load_or_fetch_week_html(
        self,
        week_anchor: dt.date,
        *,
        use_cache: bool,
        force_refresh: bool,
    ) -> tuple[str, str]:
        cache_path = self._cache_path(week_anchor)
        if use_cache and not force_refresh:
            cached = self._load_cached_week(cache_path)
            if cached is not None:
                return cached

        url = f"{self.base_url}?week={_format_day_query(week_anchor)}"
        html = self._request_week_html(url)

        if use_cache:
            self._save_cached_week(cache_path, url=url, html=html)

        return html, url

    def _fetch_week_from_web(
        self,
        week_anchor: dt.date,
        *,
        use_cache: bool,
        force_refresh: bool,
    ) -> pd.DataFrame:
        html, source_url = self._load_or_fetch_week_html(week_anchor, use_cache=use_cache, force_refresh=force_refresh)
        frame = self._parse_week_html(html=html, week_anchor=week_anchor, source_url=source_url)
        return self._normalize_frame(frame)

    def _fetch_range_from_web(
        self,
        *,
        start: dt.date,
        end: dt.date,
        use_cache: bool,
        force_refresh: bool,
        bulk_chunk_weeks: int = _DEFAULT_BULK_CHUNK_WEEKS,
        show_tqdm: bool = True,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        week_batches = self._iter_week_batches(start, end, bulk_chunk_weeks=bulk_chunk_weeks)
        week_anchors = [week_anchor for batch in week_batches for week_anchor in batch]
        iterator = self._progress_iter(
            week_anchors,
            desc="Fetching Forex Factory weeks",
            show_tqdm=show_tqdm,
        )
        for week_anchor in iterator:
            frame = self._fetch_week_from_web(week_anchor, use_cache=use_cache, force_refresh=force_refresh)
            if not frame.empty:
                frames.append(frame)

        if not frames:
            return _empty_frame()

        frame = pd.concat(frames, ignore_index=True)
        frame = self._normalize_frame(frame)
        return frame.loc[(frame["Date"] >= start) & (frame["Date"] <= end)].reset_index(drop=True)

    def _all_dates(self, start: dt.date, end: dt.date) -> list[dt.date]:
        dates: list[dt.date] = []
        current = start
        while current <= end:
            dates.append(current)
            current += dt.timedelta(days=1)
        return dates

    def _write_date_partitions(
        self,
        *,
        frame: pd.DataFrame,
        trading_dates: Sequence[dt.date],
        overwrite: bool,
        push_to_core: bool,
    ) -> dict[dt.date, dict[str, object]]:
        normalized = self._normalize_frame(frame)
        results: dict[dt.date, dict[str, object]] = {}
        for trading_date in trading_dates:
            day_frame = normalized.loc[normalized["Date"] == trading_date].reset_index(drop=True) if not normalized.empty else _empty_frame()
            results[trading_date] = self.write_day(trading_date, day_frame, overwrite=overwrite, push_to_core=push_to_core)
        return results

    def _store_week_from_web(
        self,
        week_anchor: dt.date,
        *,
        use_cache: bool,
        force_refresh: bool,
        overwrite: bool,
        push_to_core: bool,
    ) -> pd.DataFrame:
        week_frame = self._fetch_week_from_web(week_anchor, use_cache=use_cache, force_refresh=force_refresh)
        week_dates = [week_anchor + dt.timedelta(days=offset) for offset in range(7)]
        self._write_date_partitions(
            frame=week_frame,
            trading_dates=week_dates,
            overwrite=overwrite,
            push_to_core=push_to_core,
        )
        return week_frame

    def _fetch_range_via_core(
        self,
        *,
        start: dt.date,
        end: dt.date,
        use_cache: bool,
        force_refresh: bool,
        pull_core: bool,
        push_core: bool,
        bulk_chunk_weeks: int = _DEFAULT_BULK_CHUNK_WEEKS,
        show_tqdm: bool = True,
    ) -> pd.DataFrame:
        if force_refresh:
            week_batches = self._iter_week_batches(start, end, bulk_chunk_weeks=bulk_chunk_weeks)
            week_anchors = [week_anchor for batch in week_batches for week_anchor in batch]
            iterator = self._progress_iter(
                week_anchors,
                desc="Refreshing Forex Factory weeks",
                show_tqdm=show_tqdm,
            )
            for week_anchor in iterator:
                self._store_week_from_web(
                    week_anchor,
                    use_cache=use_cache,
                    force_refresh=True,
                    overwrite=True,
                    push_to_core=push_core,
                )
            return self.read_range(start, end, pull_missing=False)

        if pull_core:
            self.prefetch_range(start, end)

        missing_dates = [date_value for date_value in self._all_dates(start, end) if not self.has_day(date_value)]
        missing_weeks = sorted({_calendar_week_anchor(date_value) for date_value in missing_dates})
        week_batches = self._iter_week_batches(start, end, bulk_chunk_weeks=bulk_chunk_weeks, explicit_weeks=missing_weeks)
        week_anchors = [week_anchor for batch in week_batches for week_anchor in batch]
        iterator = self._progress_iter(
            week_anchors,
            desc="Fetching missing Forex Factory weeks",
            show_tqdm=show_tqdm,
        )
        for week_anchor in iterator:
            self._store_week_from_web(
                week_anchor,
                use_cache=use_cache,
                force_refresh=False,
                overwrite=False,
                push_to_core=push_core,
            )
        return self.read_range(start, end, pull_missing=False)

    def _iter_week_batches(
        self,
        start: dt.date,
        end: dt.date,
        bulk_chunk_weeks: int,
        *,
        explicit_weeks: Sequence[dt.date] | None = None,
    ) -> list[list[dt.date]]:
        weeks: list[dt.date]
        if explicit_weeks is not None:
            weeks = list(explicit_weeks)
        else:
            weeks = []
            current = _calendar_week_anchor(start)
            last = _calendar_week_anchor(end)
            while current <= last:
                weeks.append(current)
                current += dt.timedelta(days=7)

        chunk_size = max(1, int(bulk_chunk_weeks))
        return [weeks[i : i + chunk_size] for i in range(0, len(weeks), chunk_size)]

    def _progress_iter(
        self,
        items: Sequence[dt.date],
        *,
        desc: str,
        show_tqdm: bool,
    ):
        if not show_tqdm:
            return items
        return tqdm(items, total=len(items), desc=desc, dynamic_ncols=True)

    def _configure_session_proxy(
        self,
        *,
        force_rotate_proxy: bool = False,
    ) -> tuple[dict[str, str] | None, str | None]:
        if not self._proxy_rotation_enabled:
            return self._clear_session_proxy()

        with _PROXY_LOCK:
            proxies, host = _choose_proxy(force_rotate=force_rotate_proxy)
            if hasattr(self._session, "proxies"):
                self._session.proxies.clear()
                if proxies:
                    self._session.proxies.update(proxies)
            return proxies, host

    def _clear_session_proxy(self) -> tuple[dict[str, str] | None, str | None]:
        with _PROXY_LOCK:
            if hasattr(self._session, "proxies"):
                self._session.proxies.clear()
                if self._manual_proxies:
                    self._session.proxies.update(self._manual_proxies)
            return None, None

    def _request_week_html(self, url: str) -> str:
        attempts = 2 if self._proxy_rotation_enabled else 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                self._configure_session_proxy(force_rotate_proxy=attempt > 0)
                response = self._session.get(url, timeout=self._global_timeout)
                response.raise_for_status()
                response.encoding = response.encoding or response.apparent_encoding
                return response.text
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"Failed to fetch Forex Factory week URL: {url}")

    def _load_cached_week(self, cache_path: Path) -> tuple[str, str] | None:
        if not cache_path.exists():
            return None

        with _CACHE_LOCK:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                if payload.get("schema") != _CACHE_SCHEMA:
                    return None
                fetched_at = dt.datetime.fromisoformat(payload["fetched_at"])
                age = dt.datetime.now(dt.timezone.utc) - fetched_at
                if age > self._cache_ttl:
                    return None
                return payload["html"], payload["url"]
            except Exception:
                logger.debug("Failed to load Forex Factory cache: %s", cache_path, exc_info=True)
                return None

    def _save_cached_week(self, cache_path: Path, *, url: str, html: str) -> None:
        payload = {
            "schema": _CACHE_SCHEMA,
            "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "url": url,
            "html": html,
        }

        with _CACHE_LOCK:
            try:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = cache_path.with_suffix(f".tmp-{threading.get_ident()}.json")
                tmp_path.write_text(json.dumps(payload), encoding="utf-8")
                tmp_path.replace(cache_path)
            except Exception:
                logger.debug("Failed to save Forex Factory cache: %s", cache_path, exc_info=True)

    def _parse_week_html(
        self,
        *,
        html: str,
        week_anchor: dt.date,
        source_url: str,
    ) -> pd.DataFrame:
        soup = BeautifulSoup(html, "lxml")
        calendar_timezone = self._parse_calendar_timezone(html)
        current_date: dt.date | None = None
        current_time_label: str | None = None
        records: list[dict[str, object]] = []

        for row in soup.select("tr.calendar__row[data-event-id]"):
            next_date = self._row_date(row, current_date, calendar_timezone, week_anchor)
            if next_date != current_date:
                current_time_label = None
            current_date = next_date
            if current_date is None:
                continue

            raw_time_label = _event_text(row.select_one("td.calendar__time"))
            if raw_time_label:
                current_time_label = raw_time_label
            time_label = raw_time_label or current_time_label or ""

            actual, actual_outcome = self._parse_value_cell(row.select_one("td.calendar__actual"))
            forecast, _ = self._parse_value_cell(row.select_one("td.calendar__forecast"))
            previous, previous_outcome = self._parse_value_cell(row.select_one("td.calendar__previous"))
            impact, impact_rank = self._parse_impact(row.select_one("td.calendar__impact"))

            record = {
                "EventId": int(row["data-event-id"]),
                "WeekAnchor": week_anchor,
                "Date": current_date,
                "TimeLabel": time_label,
                "Timestamp": self._parse_timestamp(
                    event_date=current_date,
                    time_label=time_label,
                    calendar_timezone=calendar_timezone,
                ),
                "TimestampNYC": pd.NaT,
                "CalendarTimeZone": calendar_timezone,
                "Currency": _event_text(row.select_one("td.calendar__currency")).upper(),
                "Impact": impact,
                "ImpactRank": impact_rank,
                "Title": _event_text(row.select_one("span.calendar__event-title")),
                "DetailLevel": self._parse_detail_level(row.select_one("td.calendar__detail a")),
                "Actual": actual,
                "Forecast": forecast,
                "Previous": previous,
                "ActualOutcome": actual_outcome,
                "PreviousRevised": previous_outcome is not None,
                "PreviousRevisionDirection": previous_outcome,
                "SourceURL": source_url,
            }
            records.append(record)

        if not records:
            return _empty_frame()

        frame = pd.DataFrame.from_records(records, columns=_RETURN_COLUMNS)
        return self._normalize_frame(frame)

    def _parse_calendar_timezone(self, html: str) -> str:
        js_match = re.search(r"timezone_name:\s*'([^']+)'", html)
        if js_match:
            return js_match.group(1)

        header_match = re.search(r"Calendar Time Zone:\s*([^<(]+)", html)
        if header_match:
            return header_match.group(1).strip()

        return "UTC"

    def _row_date(
        self,
        row,
        current_date: dt.date | None,
        calendar_timezone: str,
        week_anchor: dt.date,
    ) -> dt.date | None:
        dateline = row.get("data-day-dateline")
        if dateline:
            tzinfo = _coerce_timezone(calendar_timezone)
            utc_dt = dt.datetime.fromtimestamp(int(dateline), tz=dt.timezone.utc)
            if tzinfo is not None:
                return utc_dt.astimezone(tzinfo).date()
            return utc_dt.date()

        date_cell = row.select_one("td.calendar__date")
        if date_cell is not None:
            date_text = _event_text(date_cell)
            match = re.search(r"([A-Za-z]{3})\s+(\d{1,2})", date_text)
            if match:
                parsed = pd.Timestamp(f"{match.group(1)} {match.group(2)} {week_anchor.year}").date()
                if parsed < week_anchor - dt.timedelta(days=7):
                    return parsed.replace(year=parsed.year + 1)
                if parsed > week_anchor + dt.timedelta(days=370):
                    return parsed.replace(year=parsed.year - 1)
                return parsed

        return current_date

    def _parse_impact(self, impact_cell) -> tuple[str, int]:
        if impact_cell is None:
            return ForexFactoryImpact.UNKNOWN.value, -1

        icon = impact_cell.select_one("span.icon")
        classes = icon.get("class", []) if icon is not None else []
        for class_name in classes:
            match = re.match(r"icon--ff-impact-([a-z]+)", class_name)
            if match:
                return _IMPACT_CLASS_MAP.get(match.group(1), (ForexFactoryImpact.UNKNOWN.value, -1))

        return ForexFactoryImpact.UNKNOWN.value, -1

    def _parse_detail_level(self, detail_link) -> int | None:
        if detail_link is None:
            return None

        for class_name in detail_link.get("class", []):
            match = re.match(r"calendar__detail-link--level-(\d+)", class_name)
            if match:
                return int(match.group(1))
        return None

    def _parse_value_cell(self, value_cell) -> tuple[str, str | None]:
        if value_cell is None:
            return "", None

        span = value_cell.find("span")
        node = span or value_cell
        value = _event_text(node)
        classes = node.get("class", []) if hasattr(node, "get") else []
        direction = None
        if "better" in classes:
            direction = "better"
        elif "worse" in classes:
            direction = "worse"
        elif "revised" in classes:
            direction = "revised"

        return value, direction

    def _parse_timestamp(
        self,
        *,
        event_date: dt.date,
        time_label: str,
        calendar_timezone: str,
    ) -> pd.Timestamp | pd.NaT:
        cleaned = time_label.lower().replace(" ", "")
        if not cleaned or cleaned in {"all-day", "allday", "tentative"}:
            return pd.NaT

        fmt = "%I:%M%p" if ":" in cleaned else "%I%p"
        try:
            parsed_time = dt.datetime.strptime(cleaned, fmt).time()
        except ValueError:
            return pd.NaT

        tzinfo = _coerce_timezone(calendar_timezone)
        timestamp = pd.Timestamp(dt.datetime.combine(event_date, parsed_time))
        if tzinfo is not None:
            timestamp = timestamp.tz_localize(tzinfo, ambiguous=False, nonexistent="shift_forward")

        if self._output_timezone is not None and timestamp.tzinfo is not None:
            return timestamp.tz_convert(self._output_timezone)

        return timestamp

    def _storage_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        storage = self._normalize_frame(frame).copy()
        if storage.empty:
            return storage
        storage["Timestamp"] = pd.to_datetime(storage["Timestamp"], utc=True, errors="coerce")
        return storage

    def _normalize_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        normalized = frame.copy()
        for column in _RETURN_COLUMNS:
            if column not in normalized.columns:
                normalized[column] = pd.NA

        if normalized.empty:
            return normalized[_RETURN_COLUMNS].copy()

        for date_column in ("WeekAnchor", "Date"):
            parsed = pd.to_datetime(normalized[date_column], errors="coerce")
            normalized[date_column] = parsed.dt.date

        timestamp_utc = pd.to_datetime(normalized["Timestamp"], utc=True, errors="coerce")
        normalized["TimestampNYC"] = timestamp_utc.dt.tz_convert(_NYC_TIMEZONE)
        timestamp = timestamp_utc
        if self._output_timezone is not None:
            timestamp = timestamp.dt.tz_convert(self._output_timezone)
        normalized["Timestamp"] = timestamp

        normalized["EventId"] = pd.array(normalized["EventId"], dtype="Int64")
        normalized["ImpactRank"] = pd.array(normalized["ImpactRank"], dtype="Int64")
        normalized["DetailLevel"] = pd.array(normalized["DetailLevel"], dtype="Int64")
        normalized["PreviousRevised"] = normalized["PreviousRevised"].fillna(False).astype(bool)

        for text_column in (
            "TimeLabel",
            "CalendarTimeZone",
            "Currency",
            "Impact",
            "Title",
            "Actual",
            "Forecast",
            "Previous",
            "SourceURL",
        ):
            normalized[text_column] = normalized[text_column].fillna("").astype(str)
        normalized["Currency"] = normalized["Currency"].str.upper()

        for optional_text in ("ActualOutcome", "PreviousRevisionDirection"):
            normalized[optional_text] = normalized[optional_text].where(pd.notna(normalized[optional_text]), None)

        normalized = normalized[_RETURN_COLUMNS]
        normalized = normalized.sort_values(
            by=["Date", "Timestamp", "EventId"],
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)
        return normalized


def fetch_forex_factory_calendar(
    start_date: dt.date | dt.datetime | str,
    end_date: dt.date | dt.datetime | str,
    *,
    themes: ForexFactoryTheme | str | Sequence[ForexFactoryTheme | str] | None = None,
    currencies: str | Sequence[str] | None = None,
    impacts: ForexFactoryImpact | str | Sequence[ForexFactoryImpact | str] | None = None,
    use_cache: bool = True,
    force_refresh: bool = False,
    cache_dir: str | os.PathLike[str] | None = None,
    cache_ttl: dt.timedelta = _DEFAULT_CACHE_TTL,
    global_timeout: int = _DEFAULT_TIMEOUT,
    output_timezone: str | None = "UTC",
    core_base_dir: str | os.PathLike[str] | None = None,
    use_core: bool = True,
    pull_core: bool = False,
    push_core: bool = False,
    bulk_chunk_weeks: int = _DEFAULT_BULK_CHUNK_WEEKS,
    proxy_rotation_enabled: bool | None = None,
    show_tqdm: bool = True,
) -> pd.DataFrame:
    fetcher = ForexFactoryCalendarFetcher(
        cache_dir=cache_dir,
        cache_ttl=cache_ttl,
        global_timeout=global_timeout,
        output_timezone=output_timezone,
        core_base_dir=core_base_dir,
        proxy_rotation_enabled=proxy_rotation_enabled,
    )
    return fetcher.fetch_range(
        start_date=start_date,
        end_date=end_date,
        themes=themes,
        currencies=currencies,
        impacts=impacts,
        use_cache=use_cache,
        force_refresh=force_refresh,
        use_core=use_core,
        pull_core=pull_core,
        push_core=push_core,
        bulk_chunk_weeks=bulk_chunk_weeks,
        show_tqdm=show_tqdm,
    )


__all__ = [
    "ForexFactoryCalendarFetcher",
    "ForexFactoryImpact",
    "ForexFactoryTheme",
    "fetch_forex_factory_calendar",
]
