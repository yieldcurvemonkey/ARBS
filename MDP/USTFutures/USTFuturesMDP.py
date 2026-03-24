import datetime
import importlib
import itertools
import os
import random
import re
import threading
import time
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union
from urllib.parse import quote

import pandas as pd
import pytz
import requests

from Caching.layered_cache_mixin import LayeredCacheMixin
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.tos import get_quotes
from MDP.MarketDataProvider import MarketDataProvider
from MDP.USTFutures.BARCHART.BarchartFetcher import BarchartFetcher
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer
from definitions.USTFutures import normalize_barchart_ust_future_price, to_barchart_root

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from MDP.USTFutures.treasury_conversion_factors import (
    build_delivery_basket_frame,
    delivery_business_window,
    get_contract_spec,
    resolve_delivery_contract,
)

DateLike = Union[datetime.date, datetime.datetime, Literal["live"]]
InstrumentLike = _USTFutureGenericPricer


def _as_datetime(ts: DateLike) -> datetime.datetime:
    if ts == "live":
        return datetime.datetime.now(pytz.UTC)
    if isinstance(ts, datetime.datetime):
        return ts

    # 2pm chicago close
    if isinstance(ts, datetime.date):
        return pytz.timezone("America/Chicago").localize(datetime.datetime(ts.year, ts.month, ts.day, 14, 0))

    raise TypeError("timestamp must be date, datetime, or 'live'")


_INTERNAL_ROOTS = {"TU", "FV", "TY", "US", "WN", "UXY"}
_BARCHART_ROOTS = {to_barchart_root(k): k for k in _INTERNAL_ROOTS}
_CME_QUARTERLY_MONTH_CODES = {
    "H": [1, 2, 3],
    "M": [4, 5, 6],
    "U": [7, 8, 9],
    "Z": [10, 11, 12],
}
_USTF_CACHE_VERSION = "USTF_GET_DATA_v2"


def _normalize_symbol(sym: str) -> Optional[str]:
    s = (sym or "").strip().upper().replace("/", "")
    if not s:
        return None

    m = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s

    root = m.group("root")
    code = m.group("code")

    if root in _INTERNAL_ROOTS:
        return s
    if root in _BARCHART_ROOTS:
        return f"{_BARCHART_ROOTS[root]}{code}"
    return s


def _to_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    m = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s
    root = m.group("root")
    code = m.group("code")
    barchart_root = to_barchart_root(root)
    return f"{barchart_root}{code}"


def _from_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    m = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s
    root = m.group("root")
    code = m.group("code")
    if root in _BARCHART_ROOTS:
        return f"{_BARCHART_ROOTS[root]}{code}"
    return s


def _clean_symbols(symbols: Sequence[str]) -> List[str]:
    out = []
    for raw in symbols:
        norm = _normalize_symbol(raw)
        if norm:
            out.append(norm)
    return out


def _to_tos_symbol(sym: str) -> str:
    norm = _normalize_symbol(sym) or str(sym or "").strip().upper().replace("/", "")
    m = re.match(r"^(?P<root>[A-Z]{1,3})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", norm)
    if not m:
        return f"/{norm}" if norm else str(sym)
    root = m.group("root")
    code = m.group("code")
    return f"/{to_barchart_root(root)}{code}"


def _from_tos_symbol(sym: str) -> str:
    s = (sym or "").strip().upper()
    if s.startswith("/"):
        s = s[1:]
    return _normalize_symbol(s) or s


def _should_use_live_quotes(timestamp: DateLike) -> bool:
    if timestamp == "live":
        return True
    if isinstance(timestamp, datetime.date) and not isinstance(timestamp, datetime.datetime):
        return timestamp == datetime.date.today()
    if isinstance(timestamp, datetime.datetime):
        ts_dt = _as_datetime(timestamp)
        now = datetime.datetime.now(pytz.UTC)
        return abs((ts_dt.astimezone(pytz.UTC) - now).total_seconds()) <= 15 * 60
    return False


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


class _ProxyGuard:
    """Force chosen proxies + Connection: close for token fetches (reduce WAF flakiness)."""

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


class USTFuturesMDP(MarketDataProvider[InstrumentLike], LayeredCacheMixin):
    _UST_PRICER_CACHE = "USTFuturePricer_Cache"
    _UST_BASKET_CACHE = "USTFutureDeliveryBasket_Cache"
    _BARCHART_STATE: Dict[str, Any] = {}
    _CORE_STORE_STATE: Dict[str, Any] = {"store": None, "lock": threading.RLock()}

    def __init__(self, source: str = "BARCHART_USTF-RL", **kwargs: Any):
        MarketDataProvider.__init__(self, source, **kwargs)
        LayeredCacheMixin.__init__(self)
        self._schwab_app_key = kwargs.get("schwab_app_key") or os.getenv("SCHWABDEV_APP_KEY") or os.getenv("SCHWAB_APP_KEY") or "zm3GYiQREbtrpBHACURcNzFJIObUq2aX"
        self._schwab_app_secret = kwargs.get("schwab_app_secret") or os.getenv("SCHWABDEV_APP_SECRET") or os.getenv("SCHWAB_APP_SECRET") or "SznUHXvKPZUnmxG9"
        self._schwab_scope = kwargs.get("schwab_scope", "pystonk")
        self._open_lock = threading.RLock()
        self._open_count = 0
        self._cache_ready = False
        self._basket_cache_ready = False

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

        if not USTFuturesMDP._BARCHART_STATE:
            USTFuturesMDP._BARCHART_STATE = {
                "proxies": None,
                "host": None,
                "chosen_at": 0.0,
                "ttl": self._barchart_proxy_ttl,
                "cycler": itertools.cycle(self._barchart_proxy_hosts),
                "lock": threading.RLock(),
            }

    def _ensure_pricer_cache(self) -> None:
        if self._cache_ready and hasattr(self, self._UST_PRICER_CACHE):
            return
        cache_path = LayeredCacheMixin.default_cache_path("USTFuturePricer_Cache")
        self.open_cache(cache_attr=self._UST_PRICER_CACHE, path=cache_path, encode=None, decode=None)
        self._cache_ready = True

    def _threadsafe_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._UST_PRICER_CACHE)
            cache[key] = value

    def _threadsafe_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_pricer_cache()
            cache = getattr(self, self._UST_PRICER_CACHE)
            return cache.get(key)

    def _ensure_basket_cache(self) -> None:
        if self._basket_cache_ready and hasattr(self, self._UST_BASKET_CACHE):
            return
        cache_path = LayeredCacheMixin.default_cache_path("USTFutureDeliveryBasket_Cache")
        self.open_cache(cache_attr=self._UST_BASKET_CACHE, path=cache_path, encode=None, decode=None)
        self._basket_cache_ready = True

    def _threadsafe_basket_cache_get(self, key: str):
        with self._open_lock:
            self._ensure_basket_cache()
            cache = getattr(self, self._UST_BASKET_CACHE)
            return cache.get(key)

    def _threadsafe_basket_cache_put(self, key: str, value: dict) -> None:
        with self._open_lock:
            self._ensure_basket_cache()
            cache = getattr(self, self._UST_BASKET_CACHE)
            cache[key] = value

    def _get_cached_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = USTFuturesMDP._BARCHART_STATE
        if time.time() - float(S["chosen_at"]) < float(S["ttl"]):
            return S["proxies"], S["host"]
        return None, None

    def _choose_barchart_proxy(self) -> tuple[dict | None, str | None]:
        S = USTFuturesMDP._BARCHART_STATE
        cycler = S["cycler"]

        for _ in range(len(self._barchart_proxy_hosts)):
            host = next(cycler)
            if host is None:
                return None, None
            try:
                proxies = _build_socks5h(host)
            except Exception:
                continue
            if _preflight_proxy(proxies):
                return proxies, host

        return None, None

    def _get_barchart_fetcher(self) -> BarchartFetcher:
        S = USTFuturesMDP._BARCHART_STATE
        with S["lock"]:
            def _safe_close(fetcher: Optional[BarchartFetcher]) -> None:
                if fetcher is None:
                    return
                try:
                    fetcher.close()
                except Exception:
                    pass

            def _build_fetcher(fetcher_proxies: Optional[dict], fetcher_host: Optional[str]) -> BarchartFetcher:
                scope_host = fetcher_host if fetcher_host is not None else "direct"
                return BarchartFetcher(
                    proxies=fetcher_proxies,
                    debug_verbose=False,
                    error_verbose=True,
                    session_token_ttl_seconds=max(1, int(S["ttl"])),
                    session_token_scope=f"{self.__class__.__name__}:{scope_host}",
                )

            proxies, host = self._get_cached_barchart_proxy()
            if proxies is None and host is None:
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()

            bcf = _build_fetcher(proxies, host)
            try:
                bcf._fetch_session_tokens(dummy_symbol="BTC")
            except Exception:
                _safe_close(bcf)
                proxies, host = self._choose_barchart_proxy()
                S["proxies"], S["host"], S["chosen_at"] = proxies, host, time.time()
                bcf = _build_fetcher(proxies, host)
                bcf._fetch_session_tokens(dummy_symbol="BTC")

            return bcf

    def _fetch_barchart_timeseries(
        self,
        tickers: List[str],
        ts_dt: datetime.datetime,
        *,
        show_tqdm: bool,
        interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]],
    ) -> pd.DataFrame:
        chi = pytz.timezone("America/Chicago")
        ts_chi = ts_dt.astimezone(chi)

        start = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 0, 1))
        end = chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 23, 59))

        barchart_syms = [_to_barchart_symbol(t) for t in tickers]
        bcf = self._get_barchart_fetcher()
        try:
            df = bcf.barchart_timeseries_api(
                barchart_symbols=barchart_syms,
                start_date=start,
                end_date=end,
                interval=interval,
                one_df=True,
                show_tqdm=show_tqdm,
                max_concurrent_tasks=len(barchart_syms) + 1,
            )
        finally:
            try:
                bcf.close()
            except Exception:
                pass
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.copy()
            for col in df.columns:
                series = pd.to_numeric(df[col], errors="coerce")
                df[col] = series.map(
                    lambda value, symbol=str(col): normalize_barchart_ust_future_price(symbol, float(value))
                    if pd.notna(value)
                    else value
                )
        return df

    def _fetch_tos_live_quotes(self, tickers: List[str], ts_dt: datetime.datetime) -> pd.DataFrame:
        tos_map = {ticker: _to_tos_symbol(ticker) for ticker in tickers}
        quote_kwargs: Dict[str, Any] = {"symbols": list(tos_map.values())}
        if self._schwab_app_key and self._schwab_app_secret:
            quote_kwargs["app_key"] = self._schwab_app_key
            quote_kwargs["app_secret"] = self._schwab_app_secret
            quote_kwargs["scope"] = self._schwab_scope

        quotes = get_quotes(**quote_kwargs)
        if not quotes:
            return pd.DataFrame()

        rows: Dict[str, Tuple[datetime.datetime, float]] = {}
        for orig_sym, tos_sym in tos_map.items():
            q = quotes.get(tos_sym)
            if not q:
                q = quotes.get(_from_tos_symbol(tos_sym))
            if not q:
                continue

            price = q.get("last")
            if price is None:
                price = q.get("mid")
            if price is None:
                price = q.get("mark")
            if price is None:
                price = q.get("bid")
            if price is None:
                price = q.get("ask")
            if price is None:
                continue

            quote_time = q.get("quoteTime")
            if quote_time is None:
                quote_ts = ts_dt
            else:
                quote_ts = pd.to_datetime(quote_time, unit="ms", utc=True).tz_convert(ts_dt.tzinfo)

            normalized_price = normalize_barchart_ust_future_price(
                _to_barchart_symbol(orig_sym),
                float(price),
            )
            rows[orig_sym] = (quote_ts, float(normalized_price))

        if not rows:
            return pd.DataFrame()

        latest_ts = max(ts for ts, _ in rows.values())
        return pd.DataFrame({sym: [px] for sym, (_, px) in rows.items()}, index=[latest_ts])

    @staticmethod
    def _parse_reference_date(timestamp: Any) -> datetime.date:
        if isinstance(timestamp, str):
            try:
                return datetime.date.fromisoformat(timestamp.split("T")[0])
            except ValueError:
                return pd.Timestamp(timestamp).date()
        if isinstance(timestamp, (datetime.date, datetime.datetime)):
            return _as_datetime(timestamp).date()
        return datetime.date.today()

    @staticmethod
    def _to_chicago_datetime(ts_dt: datetime.datetime) -> datetime.datetime:
        chi = pytz.timezone("America/Chicago")
        if ts_dt.tzinfo is None:
            return chi.localize(ts_dt)
        return ts_dt.astimezone(chi)

    @classmethod
    def _trading_date_for_timestamp(cls, ts_dt: datetime.datetime) -> datetime.date:
        return cls._to_chicago_datetime(ts_dt).date()

    @classmethod
    def _session_minute_for_timestamp(cls, ts_dt: datetime.datetime) -> int:
        ts_chi = cls._to_chicago_datetime(ts_dt)
        return (ts_chi.hour * 60) + ts_chi.minute

    @classmethod
    def _to_utc_datetime(cls, ts_dt: datetime.datetime) -> datetime.datetime:
        if ts_dt.tzinfo is None:
            ts_dt = cls._to_chicago_datetime(ts_dt)
        return ts_dt.astimezone(pytz.UTC).replace(microsecond=0)

    @staticmethod
    def _core_source_enabled(source: str) -> bool:
        return str(source).upper() == "BARCHART_USTF-RL"

    @classmethod
    def _canonical_core_timestamp(cls, timestamp: DateLike) -> Optional[datetime.datetime]:
        if timestamp == "live":
            return None
        chi = pytz.timezone("America/Chicago")
        if isinstance(timestamp, datetime.date) and not isinstance(timestamp, datetime.datetime):
            return chi.localize(datetime.datetime(timestamp.year, timestamp.month, timestamp.day, 14, 0))
        ts_dt = _as_datetime(timestamp)
        ts_chi = cls._to_chicago_datetime(ts_dt)
        if (ts_chi.hour, ts_chi.minute, ts_chi.second, ts_chi.microsecond) == (14, 0, 0, 0):
            return chi.localize(datetime.datetime(ts_chi.year, ts_chi.month, ts_chi.day, 14, 0))
        return None

    @classmethod
    def _resolve_contract_symbol(cls, sym: str, ts_dt: datetime.datetime) -> str:
        resolved = str(sym)
        if len(resolved) > 3:
            return resolved
        import rateslib as rl

        if rl.dt(ts_dt.year, ts_dt.month, ts_dt.day) >= rl.get_imm(year=ts_dt.year, month=ts_dt.month):
            contract_imm_date = rl.next_imm(start=rl.dt(ts_dt.year, ts_dt.month, ts_dt.day))
            if contract_imm_date.month == 3:
                return f"{resolved}H{int(contract_imm_date.strftime('%y'))}"
            if contract_imm_date.month == 6:
                return f"{resolved}M{int(contract_imm_date.strftime('%y'))}"
            if contract_imm_date.month == 9:
                return f"{resolved}U{int(contract_imm_date.strftime('%y'))}"
            if contract_imm_date.month == 12:
                return f"{resolved}Z{int(contract_imm_date.strftime('%y'))}"

        for m_code, month_nums in _CME_QUARTERLY_MONTH_CODES.items():
            if ts_dt.month in month_nums:
                return f"{resolved}{m_code}{int(ts_dt.strftime('%y'))}"
        return resolved

    @classmethod
    def _get_ust_future_store(cls):
        state = cls._CORE_STORE_STATE
        with state["lock"]:
            if state["store"] is None:
                from Caching.ust_future_store import USTFutureStore

                state["store"] = USTFutureStore.default()
            return state["store"]

    def _read_core_snapshot_row(self, *, symbol: str, trading_date: datetime.date) -> Optional[dict]:
        store = self._get_ust_future_store()
        df = store.read_snapshot_day(symbol, trading_date)
        if df.empty:
            return None
        if "symbol" in df.columns:
            df = df[df["symbol"].astype(str) == str(symbol)]
        if "trading_date" in df.columns:
            df = df[pd.to_datetime(df["trading_date"], errors="coerce").dt.date == trading_date]
        if df.empty:
            return None
        if "timestamp_utc" in df.columns:
            df = df.sort_values("timestamp_utc", kind="mergesort")
        return df.iloc[-1].to_dict()

    def _persist_core_snapshot(
        self,
        *,
        symbol: str,
        price: float,
        canonical_ts_dt: datetime.datetime,
        overwrite: bool = False,
    ) -> None:
        if not self._core_source_enabled(self.source):
            return
        trading_date = self._trading_date_for_timestamp(canonical_ts_dt)
        timestamp_utc = self._to_utc_datetime(canonical_ts_dt)
        snapshot_df = pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "timestamp_utc": pd.Timestamp(timestamp_utc),
                    "trading_date": trading_date,
                    "session_minute": self._session_minute_for_timestamp(canonical_ts_dt),
                    "price": float(price),
                }
            ]
        )
        self._get_ust_future_store().write_snapshot_day(symbol, trading_date, snapshot_df, overwrite=overwrite)

    @staticmethod
    def _basis_report_columns() -> List[str]:
        return [
            "cusip",
            "label",
            "clean_price",
            "ytm",
            "invoice_cf",
            "gross_basis",
            "bnoc",
            "irr",
            "is_ctd",
            "symbol",
            "timestamp_utc",
            "trading_date",
            "session_minute",
            "futures_price",
            "futures_ytm",
            "repo_rate",
            "settlement_date",
            "delivery_date",
        ]

    def _basis_report_core_timestamp(
        self,
        *,
        timestamp: DateLike,
        basket_source: str,
        usts_mdp_source: str,
        curve_id: str,
        repo_rate: Optional[float],
    ) -> Optional[datetime.datetime]:
        if not self._core_source_enabled(self.source):
            return None
        if str(basket_source) != "RL_CME_TCF":
            return None
        if str(usts_mdp_source) != "USTS_FEDINVEST_WSJ_LIVE-RL":
            return None
        if str(curve_id) != "USD-SOFR-1D":
            return None
        if repo_rate is not None:
            return None
        return self._canonical_core_timestamp(timestamp)

    def _pricer_timestamp_utc(self, pricer: RLUSTFuturePricer, fallback_ts: datetime.datetime) -> datetime.datetime:
        meta = pricer.meta()
        raw_ts = meta.get("timestamp") if isinstance(meta, dict) else None
        if raw_ts is not None:
            ts_obj = pd.Timestamp(raw_ts)
            if ts_obj.tzinfo is None:
                ts_obj = ts_obj.tz_localize(pytz.UTC)
            else:
                ts_obj = ts_obj.tz_convert(pytz.UTC)
            return ts_obj.to_pydatetime().replace(microsecond=0)
        return self._to_utc_datetime(fallback_ts)

    def _build_pricer(
        self,
        symbol: str,
        price: float,
        ts_dt: datetime.datetime,
        *,
        delivery: Optional[Tuple[datetime.date, datetime.date]] = None,
        basket_pricers: Optional[List[Any]] = None,
        conversion_factors: Optional[List[float]] = None,
        contract_coupon: Optional[float] = None,
        currency: str = "USD",
        curve_id: str = "USD-SOFR-1D",
        calc_mode: Optional[str] = None,
        meta_data: Optional[Any] = None,
    ) -> RLUSTFuturePricer:
        return RLUSTFuturePricer(
            symbol=symbol,
            reference_date=ts_dt,
            price=float(price),
            delivery=delivery,
            basket=basket_pricers,
            conversion_factors=conversion_factors,
            coupon=contract_coupon or 6.0,
            currency=currency,
            curve_id=curve_id,
            calc_mode=calc_mode,
            meta_data=meta_data,
        )

    @staticmethod
    def _build_pricer_from_args(args: Dict[str, Any]) -> RLUSTFuturePricer:
        symbol = args["symbol"]
        price = float(args["price"])
        timestamp_str = args["timestamp"]

        if isinstance(timestamp_str, str):
            try:
                ref_date = datetime.date.fromisoformat(timestamp_str.split("T")[0])
            except ValueError:
                ref_date = pd.Timestamp(timestamp_str).date()
        elif isinstance(timestamp_str, (datetime.date, datetime.datetime)):
            ref_date = _as_datetime(timestamp_str).date()
        else:
            ref_date = datetime.date.today()

        return RLUSTFuturePricer(
            symbol=symbol,
            reference_date=ref_date,
            price=price,
            delivery=args.get("delivery"),
            basket=args.get("basket_pricers"),
            conversion_factors=args.get("conversion_factors"),
            coupon=args.get("contract_coupon", 6.0),
            currency=args.get("currency", "USD"),
            curve_id=args.get("curve_id", "USD-SOFR-1D"),
            calc_mode=args.get("calc_mode"),
            meta_data=args,
        )

    def get_pricer(self, request: Dict[str, Any]) -> Dict[str, InstrumentLike]:
        symbols = _clean_symbols(request.get("symbols") or request.get("tickers") or [])
        timestamp: DateLike = request.get("timestamp", "live")
        show_tqdm = bool(request.get("show_tqdm", False))
        interval = request.get("interval", 1)
        force_refresh = bool(request.get("force_refresh", False))
        include_basket = bool(request.get("include_basket", True))
        basket_source = request.get("basket_source", "RL_CME_TCF")
        curve_id = request.get("curve_id", "USD-SOFR-1D")
        currency = request.get("currency", "USD")
        contract_coupon = request.get("contract_coupon", 6)
        usts_mdp_source = request.get("usts_mdp_source", "USTS_FEDINVEST_WSJ_LIVE-RL")

        if not symbols:
            raise ValueError("Request must include 'symbols' or 'tickers'.")

        ts_dt = _as_datetime(timestamp)
        as_of_date = self._trading_date_for_timestamp(ts_dt)
        ts_iso = ts_dt.isoformat()
        src = str(self.source).upper()
        live_quote_sources = {"BARCHART_TOS_LIVE_USTF-RL", "SCHWAB_APP_USTF-RL"}
        if src not in {"BARCHART_USTF-RL", *live_quote_sources}:
            raise NotImplementedError(f"Unsupported source {self.source}")
        use_live = src in live_quote_sources and _should_use_live_quotes(timestamp)
        core_ts_dt = None if (use_live or not self._core_source_enabled(self.source)) else self._canonical_core_timestamp(timestamp)
        resolved_symbols = [self._resolve_contract_symbol(sym, ts_dt) for sym in symbols]

        with self:
            out: Dict[str, InstrumentLike] = {}
            missing: List[str] = []

            for sym in resolved_symbols:
                if core_ts_dt is not None and not force_refresh:
                    core_row = self._read_core_snapshot_row(symbol=sym, trading_date=as_of_date)
                    if core_row is not None:
                        basket_data = None
                        if include_basket:
                            basket_data = self.get_delivery_basket(
                                as_of=as_of_date,
                                symbol=sym,
                                usts_mdp_source=usts_mdp_source,
                                source=basket_source,
                            )
                        snapshot_ts = pd.Timestamp(core_row.get("timestamp_utc", self._to_utc_datetime(core_ts_dt)))
                        if snapshot_ts.tzinfo is None:
                            snapshot_ts = snapshot_ts.tz_localize(pytz.UTC)
                        out[sym] = self._build_pricer(
                            symbol=sym,
                            price=float(core_row["price"]),
                            ts_dt=snapshot_ts.to_pydatetime(),
                            delivery=basket_data["delivery"] if basket_data else None,
                            basket_pricers=basket_data["basket_pricers"] if basket_data else None,
                            conversion_factors=basket_data["conversion_factors"] if basket_data else None,
                            contract_coupon=basket_data.get("contract_coupon") if basket_data else contract_coupon,
                            currency=currency,
                            curve_id=curve_id,
                            calc_mode=basket_data.get("calc_mode") if basket_data else None,
                            meta_data={
                                "schema": 1,
                                "symbol": sym,
                                "price": float(core_row["price"]),
                                "timestamp": snapshot_ts.isoformat(),
                                "core_source": "snapshot_store",
                            },
                        )
                        continue

                cache_key = f"{_USTF_CACHE_VERSION}::{ts_iso}-{sym}-{self.source}"
                cached = None if (force_refresh or use_live) else self._threadsafe_cache_get(cache_key)
                if cached is not None:
                    ref_dt = self._parse_reference_date(cached.get("timestamp"))
                    basket_data = None
                    if include_basket:
                        basket_data = self.get_delivery_basket(
                            as_of=as_of_date,
                            symbol=sym,
                            usts_mdp_source=usts_mdp_source,
                            source=basket_source,
                        )
                    out[sym] = self._build_pricer(
                        symbol=sym,
                        price=float(cached["price"]),
                        ts_dt=ref_dt,
                        delivery=basket_data["delivery"] if basket_data else None,
                        basket_pricers=basket_data["basket_pricers"] if basket_data else None,
                        conversion_factors=basket_data["conversion_factors"] if basket_data else None,
                        contract_coupon=basket_data.get("contract_coupon") if basket_data else contract_coupon,
                        currency=currency,
                        curve_id=curve_id,
                        calc_mode=basket_data.get("calc_mode") if basket_data else None,
                        meta_data=cached,
                    )
                    if core_ts_dt is not None:
                        self._persist_core_snapshot(symbol=sym, price=float(cached["price"]), canonical_ts_dt=core_ts_dt, overwrite=force_refresh)
                else:
                    missing.append(sym)

            if missing:
                if use_live:
                    df = self._fetch_tos_live_quotes(missing, ts_dt)
                else:
                    df = self._fetch_barchart_timeseries(missing, ts_dt, show_tqdm=show_tqdm, interval=interval)
                if df.empty:
                    raise ValueError(f"No data returned from {src} for requested UST futures.")

                if not use_live:
                    df = df.rename(columns={c: _from_barchart_symbol(str(c)) for c in df.columns})
                latest = df.iloc[-1]

                for sym in missing:
                    if sym not in df:
                        continue
                    series = df[sym].dropna()
                    if series.empty:
                        continue
                    if isinstance(series.index, pd.DatetimeIndex):
                        pos = series.index.get_indexer([ts_dt], method="nearest")
                        idx = series.index[pos[0]] if pos.size and pos[0] != -1 else series.index[-1]
                        ts_stamp = idx.isoformat() if hasattr(idx, "isoformat") else str(idx)
                    else:
                        idx = series.index[-1]
                        ts_stamp = ts_iso
                    ref_dt = self._parse_reference_date(ts_stamp)
                    args = {
                        "symbol": sym,
                        "price": float(series.loc[idx]),
                        "timestamp": ts_stamp,
                        "schema": 1,
                    }
                    basket_data = None
                    if include_basket:
                        basket_data = self.get_delivery_basket(
                            as_of=as_of_date,
                            symbol=sym,
                            usts_mdp_source=usts_mdp_source,
                            source=basket_source,
                        )
                    out[sym] = self._build_pricer(
                        symbol=sym,
                        price=float(series.loc[idx]),
                        ts_dt=ref_dt,
                        delivery=basket_data["delivery"] if basket_data else None,
                        basket_pricers=basket_data["basket_pricers"] if basket_data else None,
                        conversion_factors=basket_data["conversion_factors"] if basket_data else None,
                        contract_coupon=basket_data.get("contract_coupon") if basket_data else contract_coupon,
                        currency=currency,
                        curve_id=curve_id,
                        calc_mode=basket_data.get("calc_mode") if basket_data else None,
                        meta_data=args,
                    )
                    if not use_live:
                        cache_key = f"{_USTF_CACHE_VERSION}::{ts_iso}-{sym}-{self.source}"
                        cache_key2 = f"{_USTF_CACHE_VERSION}::{args['timestamp']}-{sym}-{self.source}"
                        self._threadsafe_cache_put(cache_key, args)
                        self._threadsafe_cache_put(cache_key2, args)
                    if core_ts_dt is not None:
                        self._persist_core_snapshot(symbol=sym, price=float(series.loc[idx]), canonical_ts_dt=core_ts_dt, overwrite=force_refresh)

            if not out:
                raise ValueError("No matching UST futures prices for requested symbols.")
            return out

    def bulk_get_data(
        self,
        timestamps: Sequence[DateLike],
        symbols: Sequence[str],
        *,
        show_tqdm: bool = False,
    ) -> Dict[DateLike, Dict[str, InstrumentLike]]:
        out: Dict[DateLike, Dict[str, InstrumentLike]] = {}
        for ts in timestamps:
            out[ts] = self.get_pricer({"symbols": symbols, "timestamp": ts, "show_tqdm": show_tqdm})
        return out

    def get_delivery_basket(
        self,
        *,
        as_of: datetime.date,
        symbol: str,
        usts_mdp_source: Optional[str] = "USTS_FEDINVEST_WSJ_LIVE-RL",
        usts_mdp: Optional[FixedRateBondsMDP] = None,
        source: str = "RL_CME_TCF",
        ignore_cache: Optional[bool] = False,
    ) -> Dict[str, Any]:
        if source not in {"RL_CME_TCF", "INTERNAL_CF"}:
            raise ValueError(f"Unsupported delivery basket source: {source}")

        if usts_mdp is None:
            usts_mdp = FixedRateBondsMDP(source=usts_mdp_source)

        # cache only the *reference* basket definition (cusips/cfs/delivery window/etc),
        # NOT the live cash pricers (they depend on usts_mdp + timestamp).
        cache_key = f"{source}|{symbol}|{as_of.isoformat()}"
        with self:
            cached = self._threadsafe_basket_cache_get(cache_key)

        if cached is None or ignore_cache:
            root, contract_imm_date, tcf_period = resolve_delivery_contract(symbol, as_of)
            basket_df = build_delivery_basket_frame(as_of=as_of, symbol=symbol, force_refresh=bool(ignore_cache))
            if basket_df.empty:
                raise ValueError(f"No CME TCF deliverables found for {symbol} at period {tcf_period}.")

            delivery_start, delivery_end = delivery_business_window(contract_imm_date)
            spec = get_contract_spec(root)
            contract_coupon = float(basket_df["futures_coupon"].iloc[0]) if "futures_coupon" in basket_df.columns else 6.0

            # preserve row-order to keep conversion factors aligned with basket_pricers
            cached = {
                "schema": 1,
                "source": source,
                "as_of": as_of.isoformat(),
                "symbol": symbol,
                "root": root,
                "period": int(tcf_period),
                "delivery": (delivery_start.isoformat(), delivery_end.isoformat()),
                "cusips": basket_df["cusip"].tolist(),
                "conversion_factors": [float(x) for x in basket_df["invoice_conversion_factor"].tolist()],
                "contract_coupon": float(contract_coupon),
                "calc_mode": spec.calc_mode,
                "contract_imm_date": contract_imm_date,
            }

            with self:
                self._threadsafe_basket_cache_put(cache_key, cached)

        # hydrate cached definition -> live cash pricers for this as_of close
        close_2pm = pytz.timezone("America/Chicago").localize(datetime.datetime(as_of.year, as_of.month, as_of.day, 14, 0))

        cusips: List[str] = list(cached["cusips"])
        cash_pricers = usts_mdp.get_data({"cusips": list(set(cusips)), "timestamp": close_2pm})

        basket_pricers: List[Any] = []
        conversion_factors: List[float] = []
        for cusip, cf in zip(cusips, cached["conversion_factors"]):
            pr = cash_pricers.get(cusip)
            if pr is None:
                continue
            basket_pricers.append(pr)
            conversion_factors.append(float(cf))

        if not basket_pricers:
            raise ValueError(f"No deliverable bond pricers resolved for {symbol}.")

        d0, d1 = cached["delivery"]
        return {
            "delivery": (datetime.date.fromisoformat(d0), datetime.date.fromisoformat(d1)),
            "basket_pricers": basket_pricers,
            "conversion_factors": conversion_factors,
            "contract_coupon": float(cached["contract_coupon"]),
            "calc_mode": cached["calc_mode"],
        }

    def _build_basis_report_frame(
        self,
        *,
        symbol: str,
        timestamp: DateLike,
        basket_source: str = "RL_CME_TCF",
        usts_mdp_source: str = "USTS_FEDINVEST_WSJ_LIVE-RL",
        curve_id: str = "USD-SOFR-1D",
        repo_rate: Optional[float] = None,
        force_refresh: bool = False,
        usts_mdp: Optional[FixedRateBondsMDP] = None,
    ) -> pd.DataFrame:
        ts_dt = _as_datetime(timestamp)
        as_of_date = self._trading_date_for_timestamp(ts_dt)
        pricers = self.get_pricer(
            {
                "symbols": [symbol],
                "timestamp": timestamp,
                "include_basket": True,
                "basket_source": basket_source,
                "usts_mdp_source": usts_mdp_source,
                "curve_id": curve_id,
                "force_refresh": force_refresh,
            }
        )
        resolved_symbol, pricer = next(iter(pricers.items()))
        basket = self.get_delivery_basket(
            as_of=as_of_date,
            symbol=resolved_symbol,
            usts_mdp_source=usts_mdp_source,
            usts_mdp=usts_mdp,
            source=basket_source,
            ignore_cache=force_refresh,
        )

        fut = pricer.build_pricable()
        fut_price = float(pricer.price(fut))
        fut_ytm = float(pricer.yield_to_maturity(fut))
        ctd = pricer.ctd()
        ctd_meta = (ctd.meta() or {}) if ctd else {}
        ctd_cusip = ctd_meta.get("cusip")

        repo_used = pricer._resolve_repo_rate(repo_rate=repo_rate, curve_name=curve_id)
        if isinstance(repo_used, Sequence) and not isinstance(repo_used, (str, bytes)):
            raise ValueError("get_basis_report only supports scalar repo_rate inputs")
        repo_used = float(repo_used)

        settlement_dt = pricer._resolve_settlement(None)
        delivery_dt = pricer._resolve_delivery(None)
        gross_basis_vec = pricer.gross_basis()
        bnoc_vec = pricer.bnoc(repo_rate=repo_used, settlement=settlement_dt, delivery=delivery_dt)
        irr_vec = pricer.implied_repo(settlement=settlement_dt, delivery=delivery_dt)
        timestamp_utc = self._pricer_timestamp_utc(pricer, ts_dt)
        trading_date = self._trading_date_for_timestamp(ts_dt)
        session_minute = self._session_minute_for_timestamp(timestamp_utc)
        settlement_date = settlement_dt.date() if isinstance(settlement_dt, datetime.datetime) else settlement_dt
        delivery_date = delivery_dt.date() if isinstance(delivery_dt, datetime.datetime) else delivery_dt

        rows: List[Dict[str, Any]] = []
        for bond_pricer, cf, gross_basis, bnoc, irr in zip(
            basket["basket_pricers"],
            basket["conversion_factors"],
            gross_basis_vec,
            bnoc_vec,
            irr_vec,
        ):
            meta = bond_pricer.meta() or {}
            rows.append(
                {
                    "cusip": meta.get("cusip"),
                    "label": meta.get("label"),
                    "clean_price": float(bond_pricer.clean_price()),
                    "ytm": float(bond_pricer.ytm()),
                    "invoice_cf": float(cf),
                    "gross_basis": float(gross_basis),
                    "bnoc": float(bnoc),
                    "irr": float(irr),
                    "is_ctd": meta.get("cusip") == ctd_cusip,
                    "symbol": resolved_symbol,
                    "timestamp_utc": pd.Timestamp(timestamp_utc),
                    "trading_date": trading_date,
                    "session_minute": session_minute,
                    "futures_price": fut_price,
                    "futures_ytm": fut_ytm,
                    "repo_rate": repo_used,
                    "settlement_date": settlement_date,
                    "delivery_date": delivery_date,
                }
            )

        if not rows:
            return pd.DataFrame(columns=self._basis_report_columns())

        return (
            pd.DataFrame(rows, columns=self._basis_report_columns())
            .sort_values(["is_ctd", "gross_basis"], ascending=[False, True], kind="mergesort")
            .reset_index(drop=True)
        )

    def get_basis_report(
        self,
        *,
        symbol: str,
        timestamp: DateLike = "live",
        basket_source: str = "RL_CME_TCF",
        usts_mdp_source: str = "USTS_FEDINVEST_WSJ_LIVE-RL",
        curve_id: str = "USD-SOFR-1D",
        repo_rate: Optional[float] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        ts_dt = _as_datetime(timestamp)
        resolved_symbol = self._resolve_contract_symbol(_normalize_symbol(symbol) or symbol, ts_dt)
        core_ts_dt = None if force_refresh else self._basis_report_core_timestamp(
            timestamp=timestamp,
            basket_source=basket_source,
            usts_mdp_source=usts_mdp_source,
            curve_id=curve_id,
            repo_rate=repo_rate,
        )
        trading_date = self._trading_date_for_timestamp(core_ts_dt or ts_dt)

        if core_ts_dt is not None:
            cached_df = self._get_ust_future_store().read_basis_report_day(resolved_symbol, trading_date)
            if not cached_df.empty:
                return cached_df.loc[:, [col for col in self._basis_report_columns() if col in cached_df.columns]].copy()

        report_df = self._build_basis_report_frame(
            symbol=resolved_symbol,
            timestamp=timestamp,
            basket_source=basket_source,
            usts_mdp_source=usts_mdp_source,
            curve_id=curve_id,
            repo_rate=repo_rate,
            force_refresh=force_refresh,
        )
        if core_ts_dt is not None and not report_df.empty:
            self._get_ust_future_store().write_basis_report_day(resolved_symbol, trading_date, report_df, overwrite=force_refresh)
        return report_df

    def get_ctd(
        self, as_of: datetime.date, symbol: str, usts_mdp: Optional[FixedRateBondsMDP] = None, repo: Optional[float] = None, source: Optional[str] = "RL_CME_TCF"
    ):
        # symbol_to_rl_spec = {
        #     "TU": "us_gb_2y",
        #     "3Y": "us_gb_3y",
        #     "FV": "us_gb_5y",
        #     "TY": "us_gb_10y",
        #     "UXY": "us_gb_10y",
        #     "US": "us_gb_30y",
        #     "TWE": "us_gb_30y",
        #     "WN": "us_gb_30y",
        # }

        if source in {"RL_CME_TCF", "INTERNAL_CF"}:
            report_df = self._build_basis_report_frame(
                symbol=symbol,
                timestamp=as_of,
                basket_source=str(source),
                usts_mdp_source=str(getattr(usts_mdp, "source", "USTS_FEDINVEST_WSJ_LIVE-RL")) if usts_mdp is not None else "USTS_FEDINVEST_WSJ_LIVE-RL",
                curve_id="USD-SOFR-1D",
                repo_rate=repo,
                usts_mdp=usts_mdp,
            )
            legacy_df = report_df.rename(columns={"invoice_cf": "invoice_conversion_factor"}).copy()
            legacy_df["gross_basis_rl"] = legacy_df["gross_basis"]
            return legacy_df.sort_values(by="irr", ascending=False, kind="mergesort").reset_index(drop=True)

    def __open__(self):
        with self._open_lock:
            if self._open_count == 0:
                self._ensure_pricer_cache()
                self._ensure_basket_cache()
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
                        self._basket_cache_ready = False

    def __enter__(self):
        return self.__open__()

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))
