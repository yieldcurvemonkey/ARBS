
import asyncio
import datetime
import importlib.util
import itertools
import os
import random
import re
import threading
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import pandas as pd
import pytz
import rateslib as rl
import requests

from Caching.LayeredCacheMixin import LayeredCacheMixin
from MDP.IRSwaps.BARCHART_STIRF.rl import BARCHART_STIRF_CURVE
from MDP.MarketDataProvider import MarketDataProvider
from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher
from Query.FXForwards.backends.rateslib.RLFXForwardPricer import RLFXForwardPricer
from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

DateLike = Union[datetime.date, datetime.datetime, str, Literal["live"]]
InstrumentLike = RLFXForwardPricer

_CORE6 = {"USD", "EUR", "CAD", "GBP", "JPY", "CHF"}
_PAIR_STRIP_CODES = ["O", "A", "S", "B", "C", "D", "E", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "1", "2", "3"]
_BOOTSTRAP_EXCLUDED_SUFFIXES = {"O", "A", "S"}
_PAIR_RE = re.compile(r"^[A-Z]{6}$")
_RAW_SYMBOL_RE = re.compile(r"^(?P<pair>[A-Z]{6})\.(?P<suffix>[AOSBCDEGHJKMNQUVX123])$")

_TENOR_TO_SUFFIX = {
    "ON": "O",
    "O": "O",
    "N": "O",
    "TN": "A",
    "TOM": "A",
    "A": "A",
    "SPOT": "S",
    "S": "S",
    "1W": "B",
    "2W": "C",
    "3W": "D",
    "1M": "E",
    "2M": "G",
    "3M": "H",
    "4M": "J",
    "5M": "K",
    "6M": "M",
    "7M": "N",
    "8M": "Q",
    "9M": "U",
    "10M": "V",
    "11M": "X",
    "1Y": "1",
    "2Y": "2",
    "3Y": "3",
}

_SUFFIX_TO_TENOR_LABEL = {
    "O": "ON",
    "A": "TN",
    "S": "SPOT",
    "B": "1W",
    "C": "2W",
    "D": "3W",
    "E": "1M",
    "G": "2M",
    "H": "3M",
    "J": "4M",
    "K": "5M",
    "M": "6M",
    "N": "7M",
    "Q": "8M",
    "U": "9M",
    "V": "10M",
    "X": "11M",
    "1": "1Y",
    "2": "2Y",
    "3": "3Y",
}

_SUFFIX_TO_SETTLEMENT_TENOR = {
    "B": "1w",
    "C": "2w",
    "D": "3w",
    "E": "1m",
    "G": "2m",
    "H": "3m",
    "J": "4m",
    "K": "5m",
    "M": "6m",
    "N": "7m",
    "Q": "8m",
    "U": "9m",
    "V": "10m",
    "X": "11m",
    "1": "1y",
    "2": "2y",
    "3": "3y",
}

_BASE_CURVE_CONFIG_BY_CCY = {
    "USD": "USD-SOFR-1D-Q12xM12STIRT",
    "EUR": "EUR-ESTR-LONDON-Q12STIRT",
    "CAD": "CAD-CORRA-Q8STIRT",
    "GBP": "GBP-SONIA-Q12STIRT",
    "JPY": "JPY-TONA-JPX-Q12STIRT",
    "CHF": "CHF-SARON-Q12STIRT",
}

_EURUSD_CURVE_PROFILES = {
    "eurusd_ois_mix23_estr_ldn": {
        "USD": "USD-OIS-Q12xM12STIRT-MIX23",
        "EUR": "EUR-ESTR-LONDON-Q12STIRT",
    },
    "eurusd_ois_mix23_estr_nyc": {
        "USD": "USD-OIS-Q12xM12STIRT-MIX23",
        "EUR": "EUR-ESTR-NYC-Q12STIRT",
    },
    "eurusd_sofr_estr_ldn": {
        "USD": "USD-SOFR-1D-Q12xM12STIRT",
        "EUR": "EUR-ESTR-LONDON-Q12STIRT",
    },
    "eurusd_sofr_estr_nyc": {
        "USD": "USD-SOFR-1D-Q12xM12STIRT",
        "EUR": "EUR-ESTR-NYC-Q12STIRT",
    },
}

_CCY_REFERENCE_KEY = {
    "USD": "USD-SOFR-1D",
    "EUR": "EUR-ESTR",
    "CAD": "CAD-CORRA",
    "GBP": "GBP-SONIA",
    "JPY": "JPY-TONA",
    "CHF": "CHF-SARON",
}

_CCY_CALENDAR = {
    ccy: RATESLIB_CURVE_DEFINITIONS[_CCY_REFERENCE_KEY[ccy]].get("Calendar", "nyc")
    for ccy in _CCY_REFERENCE_KEY
}

_CCY_BUSCONV = {
    ccy: str(RATESLIB_CURVE_DEFINITIONS[_CCY_REFERENCE_KEY[ccy]].get("BusinessConvention", "mf")).lower()
    for ccy in _CCY_REFERENCE_KEY
}

_NY_TZ = pytz.timezone("America/New_York")
_CHI_TZ = pytz.timezone("America/Chicago")
_UTC_TZ = pytz.UTC


def _as_datetime(ts: DateLike) -> datetime.datetime:
    if isinstance(ts, str):
        if ts.strip().lower() == "live":
            return datetime.datetime.now(_UTC_TZ)
        parsed = pd.Timestamp(ts)
        if parsed.tzinfo is None:
            return _NY_TZ.localize(parsed.to_pydatetime())
        return parsed.to_pydatetime()

    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            return _NY_TZ.localize(ts)
        return ts

    if isinstance(ts, datetime.date):
        return _NY_TZ.localize(datetime.datetime.combine(ts, datetime.time(hour=17, minute=0)))

    raise TypeError("timestamp must be date, datetime, iso-string, or 'live'")


def _as_date(ts: DateLike) -> datetime.date:
    if isinstance(ts, str):
        token = ts.strip()
        if token.lower() == "live":
            return datetime.datetime.now(_CHI_TZ).date()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
            return datetime.date.fromisoformat(token)
        parsed = pd.Timestamp(token)
        if parsed.tzinfo is None:
            parsed = pd.Timestamp(_NY_TZ.localize(parsed.to_pydatetime()))
        return parsed.tz_convert(_CHI_TZ).date()
    if isinstance(ts, datetime.datetime):
        if ts.tzinfo is None:
            ts = _NY_TZ.localize(ts)
        return ts.astimezone(_CHI_TZ).date()
    if isinstance(ts, datetime.date):
        return ts
    raise TypeError("timestamp must be date, datetime, iso-string, or 'live'")


def _clean_symbols(symbols: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    for s in symbols:
        token = (s or "").strip()
        if not token:
            continue
        if "x" in token:
            cleaned.extend([p for p in token.split("x") if p])
        elif "/" in token:
            cleaned.extend([p for p in token.split("/") if p])
        else:
            cleaned.append(token)
    return cleaned


def _socksio_available() -> bool:
    return importlib.util.find_spec("socksio") is not None


def _build_socks5h(host: str) -> dict:
    user = os.getenv("NORDVPN_USER", "3G5mmfKXWfCGFGT4yDL34Tzn")
    pwd = os.getenv("NORDVPN_PASS", "VN33uViQZp6pXVzdgsGskhNg")
    if not user or not pwd:
        raise ValueError("Missing NORDVPN_USER/NORDVPN_PASS in environment.")
    url = f"socks5h://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:1080"
    return {"http": url, "https": url}


def _preflight_proxy(proxies: dict | None, timeout: int = 6) -> bool:
    try:
        r = requests.get(
            "https://api.ipify.org?format=json",
            proxies=proxies,
            timeout=timeout,
            headers={"Connection": "close"},
        )
        r.raise_for_status()
        return True
    except Exception:
        return False


def _to_rl_dt(value: Union[datetime.date, datetime.datetime, pd.Timestamp]) -> datetime.datetime:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime.datetime):
        return rl.dt(value.year, value.month, value.day)
    return rl.dt(value.year, value.month, value.day)


def _to_pydate(value: Union[datetime.date, datetime.datetime, pd.Timestamp]) -> datetime.date:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime.datetime):
        return value.date()
    return value


def _as_utc_datetime(ts_like: Any, *, assume_tz: datetime.tzinfo = _CHI_TZ) -> datetime.datetime:
    ts_obj = pd.Timestamp(ts_like)
    if ts_obj.tzinfo is None:
        ts_obj = ts_obj.tz_localize(assume_tz)
    return ts_obj.tz_convert(_UTC_TZ).to_pydatetime()


def _ensure_index_in_chicago(index: pd.Index) -> pd.Index:
    if not isinstance(index, pd.DatetimeIndex):
        return index
    if index.tz is None:
        return index.tz_localize(_CHI_TZ)
    return index.tz_convert(_CHI_TZ)

def _dual_to_float(value: Any) -> Optional[float]:
    try:
        out = float(value)
        if pd.isna(out):
            return None
        return out
    except Exception:
        return None


def _parse_pair(pair: str) -> str:
    p = (pair or "").strip().upper().replace("/", "")
    if not _PAIR_RE.fullmatch(p):
        raise ValueError(f"Invalid FX pair token: {pair}")
    ccy1, ccy2 = p[:3], p[3:]
    if ccy1 not in _CORE6 or ccy2 not in _CORE6:
        raise ValueError(
            f"Unsupported currency pair '{pair}'. Curve-backed FX forwards support only Core6 currencies: {sorted(_CORE6)}."
        )
    return p


def _map_tenor_to_suffix(tenor: str) -> str:
    t = (tenor or "").strip().upper().replace(" ", "")
    if t in _PAIR_STRIP_CODES:
        return t
    suffix = _TENOR_TO_SUFFIX.get(t)
    if suffix is None:
        raise ValueError(f"Unsupported FX forward tenor alias: {tenor}")
    return suffix


def _parse_raw_symbol(symbol: str) -> Tuple[str, str]:
    s = (symbol or "").strip().upper()
    m = _RAW_SYMBOL_RE.fullmatch(s)
    if not m:
        raise ValueError(f"Invalid FX forward symbol '{symbol}'. Expected format PAIR.SUFFIX, e.g. USDCAD.B")
    pair = _parse_pair(m.group("pair"))
    return pair, m.group("suffix")


def _resolve_aliases_bulk(symbols: Iterable[str], timestamp: DateLike) -> "OrderedDict[str, List[str]]":
    _ = timestamp
    aliases: "OrderedDict[str, List[str]]" = OrderedDict()

    for raw in symbols:
        alias = (raw or "").strip()
        if not alias:
            continue

        token = alias.upper().replace(" ", "")
        resolved: List[str] = []

        if ":" in token:
            pair_token, tenor_token = token.split(":", 1)
            pair = _parse_pair(pair_token)
            suffix = _map_tenor_to_suffix(tenor_token)
            resolved = [f"{pair}.{suffix}"]
        elif _RAW_SYMBOL_RE.fullmatch(token):
            pair, suffix = _parse_raw_symbol(token)
            resolved = [f"{pair}.{suffix}"]
        elif _PAIR_RE.fullmatch(token):
            pair = _parse_pair(token)
            resolved = [f"{pair}.{suffix}" for suffix in _PAIR_STRIP_CODES]
        else:
            raise ValueError(
                f"Unsupported FX forward request token '{alias}'. Supported forms: PAIR.SUFFIX, PAIR, or PAIR:TENOR"
            )

        aliases[alias] = resolved

    return aliases


def _pair_currencies(pair: str) -> Tuple[str, str]:
    p = _parse_pair(pair)
    return p[:3], p[3:]


def _curve_configs_for_pair(pair: str, curve_profile_key: Optional[str]) -> Dict[str, str]:
    foreign, domestic = _pair_currencies(pair)

    if pair in {"EURUSD", "USDEUR"}:
        if not curve_profile_key:
            raise ValueError(
                "curve_profile_key is required for EURUSD/USDEUR requests. "
                "Allowed keys: eurusd_ois_mix23_estr_ldn, eurusd_ois_mix23_estr_nyc, eurusd_sofr_estr_ldn"
            )
        key = curve_profile_key.strip().lower()
        if key not in _EURUSD_CURVE_PROFILES:
            raise ValueError(
                f"Unknown curve_profile_key '{curve_profile_key}' for {pair}. "
                "Allowed keys: eurusd_ois_mix23_estr_ldn, eurusd_ois_mix23_estr_nyc, eurusd_sofr_estr_ldn"
            )
        profile = _EURUSD_CURVE_PROFILES[key]
        return {
            "USD": profile["USD"],
            "EUR": profile["EUR"],
            foreign: profile[foreign],
            domestic: profile[domestic],
        }

    return {
        foreign: _BASE_CURVE_CONFIG_BY_CCY[foreign],
        domestic: _BASE_CURVE_CONFIG_BY_CCY[domestic],
    }


def _spot_lag_bdays(pair: str) -> int:
    p = _parse_pair(pair)
    return 1 if p in {"USDCAD", "CADUSD"} else 2


def _pair_calendar(pair: str) -> str:
    foreign, domestic = _pair_currencies(pair)
    calendars = [_CCY_CALENDAR[domestic], _CCY_CALENDAR[foreign]]
    deduped: List[str] = []
    for cal in calendars:
        if cal not in deduped:
            deduped.append(cal)
    return ",".join(deduped)


def _spot_settlement_date(trade_date: datetime.date, pair: str) -> datetime.date:
    lag = _spot_lag_bdays(pair)
    cal = _pair_calendar(pair)
    spot = rl.add_tenor(_to_rl_dt(trade_date), f"{lag}b", modifier="F", calendar=cal)
    return _to_pydate(spot)


def _settlement_date_for_suffix(trade_date: datetime.date, pair: str, suffix: str) -> datetime.date:
    cal = _pair_calendar(pair)
    spot = _spot_settlement_date(trade_date, pair)

    if suffix == "O":
        return _to_pydate(rl.add_tenor(_to_rl_dt(trade_date), "1b", modifier="F", calendar=cal))

    if suffix in {"A", "S"}:
        return spot

    tenor = _SUFFIX_TO_SETTLEMENT_TENOR[suffix]
    foreign, _ = _pair_currencies(pair)
    modifier = _CCY_BUSCONV[foreign]
    return _to_pydate(rl.add_tenor(_to_rl_dt(spot), tenor, modifier=modifier, calendar=cal))


def _points_scale(pair: str) -> float:
    _, domestic = _pair_currencies(pair)
    return 1e2 if domestic == "JPY" else 1e4


def _basis_sign_multiplier(pair: str) -> float:
    """
    Return a sign multiplier so basis is USD-oriented across USD pairs.

    Internal bootstrap computes basis on the pair LHS currency:
      basis_lhs = r(lhs under rhs collateral) - r(lhs pure)

    Market-facing convention requested here:
      - XXXUSD (USD on RHS): keep sign
      - USDXXX (USD on LHS): flip sign
      - non-USD crosses: keep sign
    """
    lhs, rhs = _pair_currencies(pair)
    if lhs == "USD" and rhs != "USD":
        return -1.0
    return 1.0


class _ProxyGuard:
    def __init__(self, proxies: dict | None):
        self.proxies = proxies

    def __enter__(self):
        self._orig_get = requests.get

        def _patched_get(url, *args, **kwargs):
            hdrs = kwargs.pop("headers", {}) or {}
            title_map = {k.title(): v for k, v in hdrs.items()}
            if "Connection" not in title_map:
                hdrs["Connection"] = "close"
            kwargs["headers"] = hdrs
            if self.proxies is not None:
                kwargs["proxies"] = self.proxies
            else:
                kwargs.pop("proxies", None)
            return self._orig_get(url, *args, **kwargs)

        requests.get = _patched_get
        return self

    def __exit__(self, exc_type, exc, tb):
        requests.get = self._orig_get


class FXForwardMDP(MarketDataProvider[InstrumentLike], LayeredCacheMixin):
    _FXFWD_PRICER_CACHE = "_fxfwd_pricer_cache"
    _BARCHART_STATE: Dict[str, Any] = {}
    _CURVE_STATE: Dict[str, Any] = {}

    def __init__(self, source: str = "BARCHART_FXFWD-RL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        LayeredCacheMixin.__init__(self)

        self.cache_full_intraday_fetch = bool(kwargs.get("cache_full_intraday_fetch", False))
        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False

        default_hosts = [
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
        self._socksio_enabled = _socksio_available()
        self._barchart_proxy_hosts: List[Optional[str]] = list(kwargs.get("barchart_proxy_hosts", default_hosts))
        if not self._socksio_enabled:
            self._barchart_proxy_hosts = [None]

        random.shuffle(self._barchart_proxy_hosts)
        self._barchart_proxy_ttl: int = int(kwargs.get("barchart_proxy_ttl", 60))

        if not FXForwardMDP._BARCHART_STATE:
            FXForwardMDP._BARCHART_STATE = {
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
                "ttl": self._barchart_proxy_ttl,
                "fetcher": None,
                "cycler": itertools.cycle(self._barchart_proxy_hosts),
                "lock": threading.RLock(),
            }

        if not FXForwardMDP._CURVE_STATE:
            FXForwardMDP._CURVE_STATE = {
                "builder": None,
                "lock": threading.RLock(),
            }

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._FXFWD_PRICER_CACHE):
            return
        cache_path = LayeredCacheMixin.default_cache_path("FXForwardPricer_Cache")
        self.open_cache(cache_attr=self._FXFWD_PRICER_CACHE, path=cache_path, encode=None, decode=None)
        self._cache_ready = True

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._FXFWD_PRICER_CACHE)
            cache[key] = value

    def _threadsafe_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._FXFWD_PRICER_CACHE)
            return cache.get(key)

    def _get_cached_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = FXForwardMDP._BARCHART_STATE
        if time.time() - float(S["chosen_at"]) < float(S["ttl"]):
            return S["proxies"], S["host"]
        return None, None

    def _choose_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = FXForwardMDP._BARCHART_STATE
        cycler = S["cycler"]

        for _ in range(max(1, len(self._barchart_proxy_hosts))):
            host = next(cycler)
            if host is None:
                return None, None

            if not self._socksio_enabled:
                continue

            try:
                proxies = _build_socks5h(host)
            except Exception:
                continue
            if _preflight_proxy(proxies):
                return proxies, host

        return None, None

    def _get_barchart_fetcher(self) -> BarchartFetcher:
        S = FXForwardMDP._BARCHART_STATE
        with S["lock"]:
            proxies, host = self._get_cached_barchart_proxy()
            if proxies is None and host is None:
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                S["fetcher"] = None

            bcf = S["fetcher"]
            if bcf is None:
                bcf = BarchartFetcher(proxies=proxies, debug_verbose=False, error_verbose=True)
                S["fetcher"] = bcf

            try:
                with _ProxyGuard(proxies):
                    bcf._fetch_session_tokens(dummy_symbol="BTC")
            except Exception:
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                bcf = BarchartFetcher(proxies=proxies, debug_verbose=False, error_verbose=True)
                S["fetcher"] = bcf
                with _ProxyGuard(proxies):
                    bcf._fetch_session_tokens(dummy_symbol="BTC")

            return bcf

    def _get_curve_builder(self) -> BARCHART_STIRF_CURVE:
        S = FXForwardMDP._CURVE_STATE
        with S["lock"]:
            if S["builder"] is None:
                S["builder"] = BARCHART_STIRF_CURVE()
            return S["builder"]

    def _fetch_barchart_timeseries(
        self,
        symbols: List[str],
        ts_dt: datetime.datetime,
        *,
        show_tqdm: bool,
        window_minutes: int = 2,
        full_day_intraday: bool = False,
    ) -> pd.DataFrame:
        ts_chi = ts_dt.astimezone(_CHI_TZ)

        def _session_bounds(anchor: datetime.datetime) -> Tuple[datetime.datetime, datetime.datetime]:
            session_open = anchor.replace(hour=17, minute=0, second=0, microsecond=0)
            if anchor < session_open:
                session_open = session_open - datetime.timedelta(days=1)
            return session_open, session_open + datetime.timedelta(hours=23)

        if full_day_intraday:
            start, end = _session_bounds(ts_chi)
        else:
            start = ts_chi - datetime.timedelta(minutes=window_minutes)
            end = ts_chi + datetime.timedelta(minutes=window_minutes)

        bcf = self._get_barchart_fetcher()

        def _call() -> pd.DataFrame:
            return bcf.barchart_timeseries_api(
                barchart_symbols=symbols,
                start_date=start,
                end_date=end,
                interval=1,
                one_df=True,
                show_tqdm=show_tqdm,
                max_concurrent_tasks=min(len(symbols), 36) + 1,
                max_keepalive_connections=max(36, min(len(symbols), 36)) + 1,
            )

        try:
            asyncio.get_running_loop()
            running = True
        except RuntimeError:
            running = False

        if not running:
            df = _call()
        else:
            holder: Dict[str, Any] = {"df": None, "err": None}

            def _worker() -> None:
                try:
                    holder["df"] = _call()
                except Exception as exc:
                    holder["err"] = exc

            th = threading.Thread(target=_worker, daemon=True)
            th.start()
            th.join()
            if holder["err"] is not None:
                raise holder["err"]
            df = holder["df"]

        if df is None or df.empty:
            return pd.DataFrame()

        df = df.copy()
        if isinstance(df.index, pd.DatetimeIndex):
            df.index = _ensure_index_in_chicago(df.index)

        if full_day_intraday:
            if isinstance(df.index, pd.DatetimeIndex):
                full_index = pd.date_range(start=start, end=end, freq="1min", tz=df.index.tz)
                if len(full_index):
                    df = df.sort_index()
                    df = df.reindex(df.index.union(full_index)).sort_index().ffill().bfill()
                    df = df.loc[full_index]
        return df

    def _build_pair_curve_context(
        self,
        *,
        pair: str,
        trade_date: datetime.date,
        spot: float,
        quotes_by_suffix: Dict[str, Dict[str, Any]],
        curve_config_by_ccy: Dict[str, str],
        curve_getter: Any,
    ) -> Dict[str, Any]:
        foreign, domestic = _pair_currencies(pair)
        spot_settle = _spot_settlement_date(trade_date, pair)
        spot_settle_rl = _to_rl_dt(spot_settle)

        context: Dict[str, Any] = {
            "fx_rates": None,
            "fx_forwards": None,
            "basis_by_suffix": {},
            "curve_error": None,
            "curve_names": {
                foreign: curve_config_by_ccy[foreign],
                domestic: curve_config_by_ccy[domestic],
            },
            "spot_settlement": spot_settle,
        }

        try:
            dom_curve = curve_getter(curve_config_by_ccy[domestic])
            for_curve = curve_getter(curve_config_by_ccy[foreign])

            valid_nodes: Dict[datetime.datetime, float] = {}
            for suffix in _PAIR_STRIP_CODES:
                if suffix in _BOOTSTRAP_EXCLUDED_SUFFIXES:
                    continue

                q = quotes_by_suffix.get(suffix)
                if not q:
                    continue

                settle = q["settlement_date"]
                if settle <= spot_settle:
                    continue

                fwd = _dual_to_float(q["forward_rate"])
                if fwd is None or fwd <= 0 or spot <= 0:
                    continue

                settle_rl = _to_rl_dt(settle)
                df_yy = _dual_to_float(dom_curve[settle_rl])
                if df_yy is None or df_yy <= 0:
                    continue

                df_fy = fwd * df_yy / float(spot)
                if pd.isna(df_fy) or df_fy <= 0:
                    continue

                valid_nodes[settle_rl] = float(df_fy)

            if len(valid_nodes) < 6:
                raise RuntimeError(
                    f"Insufficient valid bootstrap tenors for {pair}: need >=6, got {len(valid_nodes)} after filtering O/A/S and invalid quotes"
                )

            nodes: Dict[datetime.datetime, float] = {_to_rl_dt(trade_date): 1.0}

            df_spot_dom = _dual_to_float(dom_curve[spot_settle_rl])
            if df_spot_dom is not None and df_spot_dom > 0:
                nodes[spot_settle_rl] = float(spot) * df_spot_dom / float(spot)

            for k, v in sorted(valid_nodes.items(), key=lambda kv: kv[0]):
                nodes[k] = v

            foreign_ref = _CCY_REFERENCE_KEY[foreign]
            foreign_def = RATESLIB_CURVE_DEFINITIONS[foreign_ref]

            ffyy_curve = rl.Curve(
                nodes=nodes,
                id=f"{pair}-FFYY",
                convention=foreign_def["DayCounter"],
                calendar=foreign_def["Calendar"],
                modifier=foreign_def["BusinessConvention"],
            )

            fx_rates = rl.FXRates(
                {pair.lower(): float(spot)},
                settlement=spot_settle_rl,
                base=foreign.lower(),
            )
            fx_curves = {
                f"{domestic.lower()}{domestic.lower()}": dom_curve,
                f"{foreign.lower()}{foreign.lower()}": for_curve,
                f"{foreign.lower()}{domestic.lower()}": ffyy_curve,
            }
            fx_forwards = rl.FXForwards(fx_rates=fx_rates, fx_curves=fx_curves, base=foreign.lower())

            basis_by_suffix: Dict[str, Optional[float]] = {}
            modifier = str(foreign_def.get("BusinessConvention", "mf"))
            sign_mult = _basis_sign_multiplier(pair)
            for suffix, q in quotes_by_suffix.items():
                settle = q["settlement_date"]
                if settle <= spot_settle:
                    basis_by_suffix[suffix] = None
                    continue

                try:
                    term = _to_rl_dt(settle)
                    r_ffyy = _dual_to_float(ffyy_curve.rate(spot_settle_rl, term, modifier=modifier))
                    r_ffff = _dual_to_float(for_curve.rate(spot_settle_rl, term, modifier=modifier))
                    if r_ffyy is None or r_ffff is None:
                        basis_by_suffix[suffix] = None
                    else:
                        basis_by_suffix[suffix] = ((r_ffyy - r_ffff) * 100.0) * sign_mult
                except Exception:
                    basis_by_suffix[suffix] = None

            context.update(
                {
                    "fx_rates": fx_rates,
                    "fx_forwards": fx_forwards,
                    "basis_by_suffix": basis_by_suffix,
                }
            )
            return context
        except Exception as exc:
            context["curve_error"] = str(exc)
            return context

    def _get_data_for_timestamp(
        self,
        symbols: List[str],
        timestamp: DateLike,
        *,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        cache_full_intraday_fetch: bool = False,
        curve_profile_key: Optional[str] = None,
        window_minutes: int = 2,
    ) -> Dict[str, List[InstrumentLike]]:
        ts_dt = _as_datetime(timestamp)
        trade_date = _as_date(timestamp)
        alias_map = _resolve_aliases_bulk(symbols, timestamp)

        if not alias_map:
            raise ValueError("No valid symbols resolved from request.")

        src = self.source.upper()
        if src not in {"BARCHART_FXFWD-RL", "BARCHART_STIRF-RL"}:
            raise NotImplementedError(f"Unsupported source {self.source}")

        floor_req_to_minute = bool(cache_full_intraday_fetch)
        read_cache = not force_refresh

        self._ensure_pricer_cache()

        pair_symbols_requested: Dict[str, List[str]] = defaultdict(list)
        all_required_symbols: OrderedDict[str, None] = OrderedDict()
        pair_curve_config: Dict[str, Dict[str, str]] = {}

        for _, raw_symbols in alias_map.items():
            for sym in raw_symbols:
                pair, _ = _parse_raw_symbol(sym)
                pair_symbols_requested[pair].append(sym)
                all_required_symbols.setdefault(sym, None)
                all_required_symbols.setdefault(f"^{pair}", None)

        for pair in pair_symbols_requested:
            pair_curve_config[pair] = _curve_configs_for_pair(pair, curve_profile_key=curve_profile_key)

        def _cache_ts_iso(ts_like: Any, *, floor_minute: bool) -> str:
            ts_obj = pd.Timestamp(_as_utc_datetime(ts_like))
            if floor_minute:
                ts_obj = ts_obj.floor("min")
            return ts_obj.isoformat()

        req_ts_key_candidates: List[str] = []

        def _push_key(k: str) -> None:
            if k and k not in req_ts_key_candidates:
                req_ts_key_candidates.append(k)

        _push_key(_cache_ts_iso(ts_dt, floor_minute=floor_req_to_minute))
        _push_key(_cache_ts_iso(ts_dt, floor_minute=True))
        _push_key(_cache_ts_iso(ts_dt, floor_minute=False))
        _push_key(pd.Timestamp(ts_dt).isoformat())
        _push_key(pd.Timestamp(ts_dt).floor("min").isoformat())

        def _get_cached_request_key(symbol: str):
            if not read_cache:
                return None
            for ts_key in req_ts_key_candidates:
                cached_local = self._threadsafe_cache_get(f"{ts_key}-{symbol}-{src}")
                if cached_local is not None:
                    return cached_local
            return None

        def _align_lookup_ts(index: pd.Index, req_ts: datetime.datetime) -> datetime.datetime:
            if not isinstance(index, pd.DatetimeIndex):
                return req_ts
            ts_obj = pd.Timestamp(req_ts)
            if index.tz is None:
                if ts_obj.tzinfo is not None:
                    ts_obj = ts_obj.tz_localize(None)
            else:
                if ts_obj.tzinfo is None:
                    ts_obj = ts_obj.tz_localize(index.tz)
                else:
                    ts_obj = ts_obj.tz_convert(index.tz)
            return ts_obj.to_pydatetime()

        symbol_args: Dict[str, Dict[str, Any]] = {}
        to_fetch: List[str] = []
        for symbol in all_required_symbols.keys():
            cached = _get_cached_request_key(symbol)
            if cached is not None:
                symbol_args[symbol] = cached
            else:
                to_fetch.append(symbol)

        price_df = pd.DataFrame()
        if to_fetch:
            price_df = self._fetch_barchart_timeseries(
                symbols=to_fetch,
                ts_dt=ts_dt,
                show_tqdm=show_tqdm,
                window_minutes=window_minutes,
                full_day_intraday=floor_req_to_minute,
            )
            price_df = price_df.ffill().bfill()
            if price_df.empty:
                raise RuntimeError("Barchart returned no data for requested FX forward symbols.")

            for symbol in price_df.columns:
                series = price_df[symbol].dropna()
                for curr_ts, px in series.items():
                    curr_ts_iso = _cache_ts_iso(curr_ts, floor_minute=floor_req_to_minute)
                    args = {
                        "symbol": symbol,
                        "price": float(px),
                        "timestamp": curr_ts_iso,
                        "schema": 1,
                    }
                    self._threadsafe_cache_put(f"{curr_ts_iso}-{symbol}-{src}", args)

            for symbol in to_fetch:
                if symbol not in price_df.columns:
                    continue

                series = price_df[symbol].dropna()
                if series.empty:
                    continue

                lookup_ts = _align_lookup_ts(series.index, ts_dt)
                pos = series.index.get_indexer([lookup_ts], method="nearest")
                idx = series.index[pos[0]] if pos.size and pos[0] != -1 else series.index[-1]
                idx_iso = _cache_ts_iso(idx, floor_minute=floor_req_to_minute)
                args = {
                    "symbol": symbol,
                    "price": float(series.loc[idx]),
                    "timestamp": idx_iso,
                    "schema": 1,
                }
                symbol_args[symbol] = args

                self._threadsafe_cache_put(f"{idx_iso}-{symbol}-{src}", args)
                for req_ts_key in req_ts_key_candidates:
                    self._threadsafe_cache_put(f"{req_ts_key}-{symbol}-{src}", args)

        for symbol in all_required_symbols.keys():
            if symbol in symbol_args:
                continue
            cached = _get_cached_request_key(symbol)
            if cached is not None:
                symbol_args[symbol] = cached

        pair_market_data: Dict[str, Dict[str, Any]] = {}
        for pair, forward_symbols in pair_symbols_requested.items():
            spot_symbol = f"^{pair}"
            spot_args = symbol_args.get(spot_symbol)
            if spot_args is None:
                raise RuntimeError(f"Missing spot quote for {pair} ({spot_symbol})")

            spot = float(spot_args["price"])
            spot_ts = _as_utc_datetime(spot_args["timestamp"])

            quote_data: Dict[str, Dict[str, Any]] = {}
            for sym in forward_symbols:
                args = symbol_args.get(sym)
                if args is None:
                    continue
                _, suffix = _parse_raw_symbol(sym)
                points_raw = _dual_to_float(args["price"])
                if points_raw is None:
                    continue

                points_decimal = points_raw / _points_scale(pair)
                forward_rate = float(spot) + float(points_decimal)
                settlement_date = _settlement_date_for_suffix(trade_date, pair, suffix)
                quote_ts = _as_utc_datetime(args["timestamp"])

                quote_data[suffix] = {
                    "symbol": sym,
                    "suffix": suffix,
                    "tenor": _SUFFIX_TO_TENOR_LABEL[suffix],
                    "spot": float(spot),
                    "points_raw": float(points_raw),
                    "points_decimal": float(points_decimal),
                    "forward_rate": float(forward_rate),
                    "settlement_date": settlement_date,
                    "quote_timestamp": quote_ts,
                }

            pair_market_data[pair] = {
                "spot": float(spot),
                "spot_symbol": spot_symbol,
                "spot_timestamp": spot_ts,
                "quotes": quote_data,
            }

        curve_builder = self._get_curve_builder()
        curve_obj_cache: Dict[Tuple[str, str, bool, bool], Any] = {}

        def _curve_getter(curve_name: str):
            key = (
                curve_name,
                _cache_ts_iso(ts_dt, floor_minute=False),
                bool(force_refresh),
                bool(cache_full_intraday_fetch),
            )
            if key in curve_obj_cache:
                return curve_obj_cache[key]

            curve = curve_builder.build_curve(
                curve_name=curve_name,
                timestamp=ts_dt,
                kwargs={
                    "force_refresh": bool(force_refresh),
                    "show_tqdm": bool(show_tqdm),
                    "cache_full_intraday_fetch": bool(cache_full_intraday_fetch),
                },
                curve_only=True,
            )
            curve_obj_cache[key] = curve
            return curve

        pair_curve_ctx: Dict[str, Dict[str, Any]] = {}
        for pair, md in pair_market_data.items():
            pair_curve_ctx[pair] = self._build_pair_curve_context(
                pair=pair,
                trade_date=trade_date,
                spot=md["spot"],
                quotes_by_suffix=md["quotes"],
                curve_config_by_ccy=pair_curve_config[pair],
                curve_getter=_curve_getter,
            )

        result: Dict[str, List[InstrumentLike]] = {}
        for alias, raw_symbols in alias_map.items():
            insts: List[InstrumentLike] = []
            for sym in raw_symbols:
                pair, suffix = _parse_raw_symbol(sym)
                pair_md = pair_market_data.get(pair, {})
                q = pair_md.get("quotes", {}).get(suffix)
                if not q:
                    continue

                ctx = pair_curve_ctx.get(pair, {})
                basis_by_suffix = ctx.get("basis_by_suffix", {})

                meta = {
                    "schema": 1,
                    "source": src,
                    "symbol": sym,
                    "pair": pair,
                    "suffix": suffix,
                    "tenor": q["tenor"],
                    "spot_symbol": pair_md.get("spot_symbol"),
                    "spot_lag_bdays": _spot_lag_bdays(pair),
                    "settlement_calendar": _pair_calendar(pair),
                    "curve_profile_key": curve_profile_key,
                    "curve_names": ctx.get("curve_names"),
                    "curve_error": ctx.get("curve_error"),
                    "spot_timestamp": pair_md.get("spot_timestamp"),
                    "quote_timestamp": q["quote_timestamp"],
                }

                insts.append(
                    RLFXForwardPricer(
                        pair=pair,
                        symbol=sym,
                        tenor=q["tenor"],
                        settlement_date=q["settlement_date"],
                        quote_timestamp=q["quote_timestamp"],
                        spot=q["spot"],
                        points_raw=q["points_raw"],
                        points_decimal=q["points_decimal"],
                        forward_rate=q["forward_rate"],
                        basis_bps=basis_by_suffix.get(suffix),
                        fx_rates=ctx.get("fx_rates"),
                        fx_forwards=ctx.get("fx_forwards"),
                        meta_data=meta,
                    )
                )

            if insts:
                result[alias] = insts

        return result

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, List[InstrumentLike]]:
        return self.get_data(request)

    def get_data(self, request: Dict[str, Any]) -> Dict[str, List[InstrumentLike]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamp: DateLike = request.get("timestamp", "live")
        curve_profile_key = request.get("curve_profile_key")
        show_tqdm = bool(request.get("show_tqdm", False))
        force_refresh = bool(request.get("force_refresh", False))
        cache_full_intraday_fetch = bool(request.get("cache_full_intraday_fetch", self.cache_full_intraday_fetch))
        window_minutes = int(request.get("window_minutes", 2))

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")

        with self:
            return self._get_data_for_timestamp(
                symbols,
                timestamp,
                show_tqdm=show_tqdm,
                force_refresh=force_refresh,
                cache_full_intraday_fetch=cache_full_intraday_fetch,
                curve_profile_key=curve_profile_key,
                window_minutes=window_minutes,
            )

    def get_bulk_pricer(self, request: Dict[str, Any]) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:
        return self.get_bulk_data(request)

    def get_bulk_data(self, request: Dict[str, Any]) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamps_raw = request.get("timestamps", None)
        curve_profile_key = request.get("curve_profile_key")
        show_tqdm = bool(request.get("show_tqdm", False))
        force_refresh = bool(request.get("force_refresh", False))
        max_workers = int(request.get("max_workers", 8))
        cache_full_intraday_fetch = bool(request.get("cache_full_intraday_fetch", self.cache_full_intraday_fetch))
        window_minutes = int(request.get("window_minutes", 2))

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")
        if timestamps_raw is None:
            raise ValueError("Request must include 'timestamps'.")

        if isinstance(timestamps_raw, (str, datetime.date, datetime.datetime)):
            timestamps: List[DateLike] = [timestamps_raw]
        else:
            timestamps = list(timestamps_raw)

        if not timestamps:
            raise ValueError("Request 'timestamps' is empty.")

        with self:
            return self.bulk_get_data(
                timestamps=timestamps,
                symbols=symbols,
                curve_profile_key=curve_profile_key,
                show_tqdm=show_tqdm,
                force_refresh=force_refresh,
                max_workers=max_workers,
                cache_full_intraday_fetch=cache_full_intraday_fetch,
                window_minutes=window_minutes,
            )

    def bulk_get_data(
        self,
        timestamps: Sequence[DateLike],
        symbols: Sequence[str],
        *,
        curve_profile_key: Optional[str] = None,
        show_tqdm: bool = False,
        force_refresh: bool = False,
        max_workers: int = 8,
        cache_full_intraday_fetch: bool = False,
        window_minutes: int = 2,
    ) -> Dict[DateLike, Dict[str, List[InstrumentLike]]]:
        jobs: List[Tuple[DateLike, List[str]]] = []
        base_symbols = _clean_symbols(symbols)
        for ts in timestamps:
            jobs.append((ts, base_symbols))

        results: List[Tuple[DateLike, Dict[str, List[InstrumentLike]]]] = []

        with self:

            def _process_one(ts: DateLike, syms: List[str]):
                return ts, self._get_data_for_timestamp(
                    syms,
                    ts,
                    curve_profile_key=curve_profile_key,
                    show_tqdm=show_tqdm,
                    force_refresh=force_refresh,
                    cache_full_intraday_fetch=cache_full_intraday_fetch,
                    window_minutes=window_minutes,
                )

            if max_workers == 1 or len(jobs) == 1:
                iterable = jobs
                if show_tqdm:
                    import tqdm

                    iterable = tqdm.tqdm(iterable, desc="FETCHING FX FORWARDS")
                for ts, syms in iterable:
                    results.append(_process_one(ts, syms))
            else:
                with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fxfwd-mdp") as pool:
                    futures = {pool.submit(_process_one, ts, syms): (ts, syms) for ts, syms in jobs}
                    iterator = as_completed(futures)
                    if show_tqdm:
                        import tqdm

                        iterator = tqdm.tqdm(iterator, total=len(futures), desc="FETCHING FX FORWARDS")
                    for fut in iterator:
                        results.append(fut.result())

            out: Dict[DateLike, Dict[str, List[InstrumentLike]]] = defaultdict(dict)
            for ts, res in results:
                if res:
                    out[ts].update(res)
            return dict(out)

    def __open__(self):
        with self._open_lock:
            if self._open_count == 0:
                self._ensure_pricer_cache()
            self._open_count += 1
        return self

    def __close__(self, *, commit: bool = True):
        with self._open_lock:
            if self._open_count <= 0:
                return
            self._open_count -= 1
            if self._open_count == 0:
                try:
                    if commit:
                        pass  # auto-committed (DiskCache)
                finally:
                    try:
                        self.close_cache()
                    finally:
                        self._cache_ready = False

    def __enter__(self):
        self.__open__()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))
