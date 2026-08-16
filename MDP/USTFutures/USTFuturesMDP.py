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
from MDP.USTFutures.basis_report_quality import OnBadData, enforce_basis_report_quality
from Query.USTFutures._USTFutureGenericPricer import _USTFutureGenericPricer
from Query.USTFutures.backends.rateslib.RLUSTFuturePricer import RLUSTFuturePricer
from definitions.USTFutures import (
    UST_FUTURE_ROOT_ALIASES,
    normalize_barchart_ust_future_price,
    to_barchart_root,
    to_globex_root,
)

from MDP.FixedRateBonds.FixedRateBondsMDP import FixedRateBondsMDP
from MDP.USTFutures.treasury_conversion_factors import (
    build_delivery_basket_frame,
    contract_specs_fingerprint,
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


# Z3N (3-Year) and TWE (20-Year) are reachable now that their BarChart roots are known -- ZE and
# ZZ, verified on the tick grid rather than the price band. TWE is listed but effectively
# untraded from 2024 (flat prints, zero volume), so expect a symbol, not a panel.
_INTERNAL_ROOTS = {"TU", "FV", "TY", "US", "WN", "UXY", "Z3N", "TWE"}
_BARCHART_ROOTS = {to_barchart_root(k): k for k in _INTERNAL_ROOTS}
_CME_QUARTERLY_MONTH_CODES = {
    "H": [1, 2, 3],
    "M": [4, 5, 6],
    "U": [7, 8, 9],
    "Z": [10, 11, 12],
}
# Bump to invalidate the layered price cache. v2 -> v3: prices cached under the old vendor-root map
# put the EUR/NOK future under the Ultra Bond's key.
_USTF_CACHE_VERSION = "USTF_GET_DATA_v3"

# Bump to invalidate the basket-definition cache. BUMP THIS ON EVERY CHANGE TO _CONTRACT_SPECS.
#   v1 -> v2: the TY deliverable window changed, so every cached ZN basket was wrong.
#   v2 -> v3: the TY grade became vintage-aware (no 8-year cap before Sept 2023).
#
# v3 exists because v2 was not enough and the failure was invisible: after the vintage change the
# rebuilt TY panel still showed a median basket of 10 deliverables in EVERY year, when pre-2023
# years should hold ~16-17. The spec was right -- a direct build_delivery_basket_frame call
# reproduced CME's published December-2017 basket 17/17 -- but this cache was still serving
# baskets computed by the previous spec, and nothing in the returned dict says which spec built it.
_USTF_BASKET_CACHE_VERSION = "USTF_BASKET_v3"

# Stamped into every basis report and REQUIRED on read. Any cached report without it -- or with an
# older value -- is treated as a cache miss and rebuilt.
#
# This is the invalidation knob for the basis-report store, and it has to be a stamp rather than a
# file delete: USTFutureStore._read_partition falls back to pulling the partition from Supabase
# when the local files are missing, so `rm -rf` on the local cache is silently undone by the next
# read. Bump this whenever a change alters the numbers in a report.
#   v1 -> v2 (2026-08-14): Ultra Bond vendor root, ZN deliverable window, historical repo rate,
#                          Act/360 conventions, basket/risk alignment.
#   v2 -> v3 (2026-08-14): the ZN deliverable grade is vintage-dependent -- the "less than 8 years"
#                          cap commences with the September 2023 contract month, so v2 truncated
#                          every pre-2023 ZN basket by ~7 notes.
#   v3 -> v4 (2026-08-15): the delivery date used for carry was the contract's IMM DATE. Line 1210
#                          calls `_resolve_delivery(None)`, and that fallback returned the third
#                          Wednesday -- which is not a delivery date. Every net basis, BNOC and
#                          implied repo in every report carried to the wrong day. Measured on the
#                          existing reports: min net basis moves -0.71 to -5.67/32 and the maximum
#                          implied repo changes sign on the 2020 dates (USZ20 -39.23% -> +26.04%,
#                          TYZ20 -26.22% -> +17.69%). Reports built before this cannot be reused.
_BASIS_REPORT_SCHEMA_VERSION = 4

# Which BarChart series a stored price came from. Until the EOD endpoint was repaired, `interval=1`
# was the only thing that worked, so every price in the store and in the layered cache is a
# one-minute bar taken nearest 14:00 Chicago. `interval=None` now serves the exchange's daily
# SETTLEMENT instead, and the two are not the same number: measured over 59 sampled days across six
# contracts and three eras, settle vs the 14:00 CT bar has median 0.0/32, mean absolute 0.79/32 and
# a maximum of 4.0/32 (October 2020).
#
# 0.79/32 is small but not nothing against a net basis whose healthy range is +-11/32, so the two
# conventions must not be mixed in one panel without saying so. Neither the layered cache key nor
# the snapshot partition used to record which one it held, so an EOD backfill would have silently
# overwritten -- and been served in place of -- minute-derived prices. Both now carry the tag.
#
# Rows written before this existed carry no tag and are all one-minute bars, hence the legacy
# default. The default interval is unchanged (1), so warm caches stay warm.
_PRICE_SOURCE_EOD_SETTLE = "barchart_eod_settle"
_PRICE_SOURCE_LEGACY = "barchart_1m"


def _price_source_tag(interval: Optional[int]) -> str:
    return _PRICE_SOURCE_EOD_SETTLE if interval is None else f"barchart_{int(interval)}m"


def _price_cache_suffix(interval: Optional[int]) -> str:
    """Cache-key suffix for the price series. Empty for the historical default, so v3 stays valid."""
    tag = _price_source_tag(interval)
    return "" if tag == _PRICE_SOURCE_LEGACY else f"-{tag}"


# Same idea for the price SNAPSHOT store, which had no version marker at all.
#
# Deleting the local partitions is NOT enough and is not a theory: after removing all 1,855 local
# WN snapshot partitions, USTFutureStore._read_partition pulled WNM20 straight back from Supabase
# still carrying price=112.496875 -- the EUR/NOK-derived value. A plausibility band cannot catch
# these either, because the old decoder mapped the FX rate INTO the range of a real bond price.
#
# Requiring the stamp for every root would invalidate ~10,760 good partitions and force a full
# refetch of contracts that were never wrong. Only WN's vendor root was mis-mapped, so only WN is
# quarantined. If another root's vendor mapping ever changes, add it here and bump the version.
_SNAPSHOT_SCHEMA_VERSION = 2
_SNAPSHOT_QUARANTINE_ROOTS = {"WN"}


def _snapshot_root(symbol: str) -> str:
    m = re.match(r"^(?P<root>[A-Z0-9]{1,3}?)[FGHJKMNQUVXZ]\d{1,2}$", str(symbol).strip().upper())
    return m.group("root") if m else str(symbol).strip().upper()


def _normalize_symbol(sym: str) -> Optional[str]:
    s = (sym or "").strip().upper().replace("/", "")
    if not s:
        return None

    m = re.match(r"^(?P<root>[A-Z][A-Z0-9]{0,2})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s

    root = m.group("root")
    code = m.group("code")

    if root in _INTERNAL_ROOTS:
        return s
    if root in _BARCHART_ROOTS:
        return f"{_BARCHART_ROOTS[root]}{code}"
    # Exchange spellings a caller may reasonably type -- notably "UB", the CME Globex code for the
    # Ultra Bond, which is NOT its BarChart root. Resolving it here keeps every downstream key
    # (cache keys, store partitions, fetched column names) on the one internal spelling.
    if root in UST_FUTURE_ROOT_ALIASES:
        return f"{UST_FUTURE_ROOT_ALIASES[root]}{code}"
    return s


def _to_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    m = re.match(r"^(?P<root>[A-Z][A-Z0-9]{0,2})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
    if not m:
        return s
    root = m.group("root")
    code = m.group("code")
    barchart_root = to_barchart_root(root)
    return f"{barchart_root}{code}"


def _from_barchart_symbol(sym: str) -> str:
    s = (sym or "").strip().upper().replace("/", "")
    m = re.match(r"^(?P<root>[A-Z][A-Z0-9]{0,2})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", s)
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
    m = re.match(r"^(?P<root>[A-Z][A-Z0-9]{0,2})(?P<code>[FGHJKMNQUVXZ]\d{1,2})$", norm)
    if not m:
        return f"/{norm}" if norm else str(sym)
    root = m.group("root")
    code = m.group("code")
    # thinkorswim / Schwab speak CME Globex, where the Ultra Bond is /UB. BarChart's UD belongs
    # only on the BarChart path.
    return f"/{to_globex_root(root)}{code}"


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
        if interval is None and isinstance(df, pd.DataFrame) and not df.empty:
            # ``queryeod`` bars are date-stamped and timezone-naive, but everything downstream
            # works in Chicago wall time and locates the price with
            # ``index.get_indexer([ts_dt], method="nearest")`` -- which raises outright on a naive
            # index against an aware target ("Cannot compare dtypes datetime64[ns] and
            # datetime64[ns, America/Chicago]"). So an EOD frame is stamped at the moment its price
            # actually refers to: the daily settlement, which this module already treats as 14:00
            # Chicago (see ``_as_datetime``).
            #
            # That 14:00 is measured, not assumed. Over 59 sampled days across six contracts and
            # three eras, the settle and the 14:00 CT one-minute bar agree with median 0.0/32 and
            # mean absolute 0.79/32 (max 4.0/32, in October 2020).
            df = df.copy()
            idx = pd.to_datetime(df.index)
            if getattr(idx, "tz", None) is None:
                df.index = (idx.normalize() + pd.Timedelta(hours=14)).tz_localize(chi)
            else:
                df.index = idx.tz_convert(chi)
            df.index.name = "Date"

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
        """Resolve a bare root to a contract. One resolver, shared -- see definitions.USTFutures.

        This used to inline its own IMM-date arithmetic. Three other sites did the same, and they
        agreed only because all four happened to be written identically; a fix to one would have
        made `warm_ustf_cache` warm `TYU26` while `usd_swaps` read `TYZ26`, and every warm would
        have become a miss with no error. They now all call `front_month`.

        Note the two-digit year here was also `int(...strftime('%y'))`, which drops the leading zero
        (`TYH8`, not `TYH08`). Harmless 2010-2069, wrong for any pre-2010 backfill. `front_month`
        formats it properly.
        """
        resolved = str(sym)
        if len(resolved) > 3:
            return resolved
        from definitions.USTFutures import front_month

        return front_month(cls._to_chicago_datetime(ts_dt).date(), resolved)

    @classmethod
    def _get_ust_future_store(cls):
        state = cls._CORE_STORE_STATE
        with state["lock"]:
            if state["store"] is None:
                from Caching.ust_future_store import USTFutureStore

                state["store"] = USTFutureStore.default()
            return state["store"]

    def _read_core_snapshot_row(
        self,
        *,
        symbol: str,
        trading_date: datetime.date,
        price_source: str = _PRICE_SOURCE_LEGACY,
    ) -> Optional[dict]:
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
        # A settlement price and a one-minute bar for the same instant are different numbers
        # (see _PRICE_SOURCE_EOD_SETTLE), and a partition can hold both. Select rather than take
        # the last row, or which convention a panel gets is down to file ordering. Untagged rows
        # predate the tag and are all one-minute bars.
        sources = (
            df["price_source"].astype("string").fillna(_PRICE_SOURCE_LEGACY)
            if "price_source" in df.columns
            else pd.Series(_PRICE_SOURCE_LEGACY, index=df.index, dtype="string")
        )
        df = df[sources == str(price_source)]
        if df.empty:
            return None
        if _snapshot_root(symbol) in _SNAPSHOT_QUARANTINE_ROOTS:
            # A partition can hold BOTH a stale unstamped row and a fresh stamped one (a non
            # overwrite write lands a second file in the same directory and _read_partition
            # concatenates them), and both carry the same timestamp -- so filter rather than
            # inspect, or which row wins is down to file ordering.
            if "schema_version" not in df.columns:
                return None
            versions = pd.to_numeric(df["schema_version"], errors="coerce")
            df = df[versions >= _SNAPSHOT_SCHEMA_VERSION]
            if df.empty:
                # Pre-stamp snapshot for a quarantined root -> cannot be trusted. Treat as a miss
                # so the price is refetched under the corrected vendor root and rewritten (which
                # also pushes the correction back to Supabase).
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
        price_source: str = _PRICE_SOURCE_LEGACY,
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
                    "schema_version": _SNAPSHOT_SCHEMA_VERSION,
                    "price_source": str(price_source),
                }
            ]
        )
        # Quarantined roots always overwrite: leaving the stale unstamped file beside the new one
        # keeps a known-bad price on disk (and in Supabase) for no benefit.
        overwrite = overwrite or (_snapshot_root(symbol) in _SNAPSHOT_QUARANTINE_ROOTS)
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
            # Written by enforce_basis_report_quality so the verdict travels WITH the data.
            # A flag that only exists in a log line is a flag nobody reads.
            "data_ok",
            "data_quality_reason",
            "schema_version",
            "spec_fingerprint",
        ]

    @staticmethod
    def _basis_report_cache_is_current(df: pd.DataFrame) -> bool:
        """Is this cached basis report one the CURRENT code produced?

        Anything without a schema_version column predates the stamp and is therefore pre-fix.
        """
        if "schema_version" not in df.columns or "spec_fingerprint" not in df.columns:
            return False
        versions = pd.to_numeric(df["schema_version"], errors="coerce").dropna()
        if not len(versions) or not bool((versions == _BASIS_REPORT_SCHEMA_VERSION).all()):
            return False
        # The deliverable-grade table is an input to every number in the report, so a report built
        # under a different spec is stale even at the same schema version.
        return bool((df["spec_fingerprint"].astype(str) == contract_specs_fingerprint()).all())

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
        # A settlement price and a one-minute bar are different numbers for the same instant, so
        # they must not share a cache key or a snapshot row. See _PRICE_SOURCE_EOD_SETTLE.
        price_source = _price_source_tag(interval)
        price_cache_suffix = _price_cache_suffix(interval)
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

        _shared_usts_mdp = None
        if include_basket:
            _shared_usts_mdp = FixedRateBondsMDP(source=usts_mdp_source)

        with self:
            out: Dict[str, InstrumentLike] = {}
            missing: List[str] = []

            for sym in resolved_symbols:
                if core_ts_dt is not None and not force_refresh:
                    core_row = self._read_core_snapshot_row(
                        symbol=sym, trading_date=as_of_date, price_source=price_source
                    )
                    if core_row is not None:
                        basket_data = None
                        if include_basket:
                            basket_data = self.get_delivery_basket(
                                as_of=as_of_date,
                                symbol=sym,
                                usts_mdp=_shared_usts_mdp,
                                usts_mdp_source=usts_mdp_source,
                                source=basket_source,
                                ignore_cache=force_refresh,
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

                cache_key = f"{_USTF_CACHE_VERSION}::{ts_iso}-{sym}-{self.source}{price_cache_suffix}"
                cached = None if (force_refresh or use_live) else self._threadsafe_cache_get(cache_key)
                if cached is not None:
                    ref_dt = self._parse_reference_date(cached.get("timestamp"))
                    basket_data = None
                    if include_basket:
                        basket_data = self.get_delivery_basket(
                            as_of=as_of_date,
                            symbol=sym,
                            usts_mdp=_shared_usts_mdp,
                            usts_mdp_source=usts_mdp_source,
                            source=basket_source,
                            ignore_cache=force_refresh,
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
                        self._persist_core_snapshot(
                            symbol=sym,
                            price=float(cached["price"]),
                            canonical_ts_dt=core_ts_dt,
                            overwrite=force_refresh,
                            price_source=price_source,
                        )
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
                        "price_source": price_source,
                    }
                    basket_data = None
                    if include_basket:
                        basket_data = self.get_delivery_basket(
                            as_of=as_of_date,
                            symbol=sym,
                            usts_mdp=_shared_usts_mdp,
                            usts_mdp_source=usts_mdp_source,
                            source=basket_source,
                            ignore_cache=force_refresh,
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
                        cache_key = f"{_USTF_CACHE_VERSION}::{ts_iso}-{sym}-{self.source}{price_cache_suffix}"
                        cache_key2 = f"{_USTF_CACHE_VERSION}::{args['timestamp']}-{sym}-{self.source}{price_cache_suffix}"
                        self._threadsafe_cache_put(cache_key, args)
                        self._threadsafe_cache_put(cache_key2, args)
                    if core_ts_dt is not None:
                        self._persist_core_snapshot(
                            symbol=sym,
                            price=float(series.loc[idx]),
                            canonical_ts_dt=core_ts_dt,
                            overwrite=force_refresh,
                            price_source=price_source,
                        )

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
        # The spec fingerprint is part of the key, so ANY change to _CONTRACT_SPECS invalidates
        # every cached basket automatically. Relying on a hand-bumped version is what let a
        # corrected spec sit behind stale baskets earlier in this very branch.
        cache_key = (
            f"{_USTF_BASKET_CACHE_VERSION}|{contract_specs_fingerprint()}|"
            f"{source}|{symbol}|{as_of.isoformat()}"
        )
        with self:
            cached = self._threadsafe_basket_cache_get(cache_key)

        if cached is not None and "issue_dates" not in cached:
            cached = None
        if cached is None or ignore_cache:
            root, contract_imm_date, tcf_period = resolve_delivery_contract(symbol, as_of)
            basket_df = build_delivery_basket_frame(as_of=as_of, symbol=symbol, force_refresh=bool(ignore_cache))
            if basket_df.empty:
                raise ValueError(f"No CME TCF deliverables found for {symbol} at period {tcf_period}.")

            # Exclude WI (when-issued) bonds whose issue_date is after as_of —
            # FedInvest has no price for them yet, causing noisy fetch failures.
            if "issue_date" in basket_df.columns:
                issued = basket_df["issue_date"].apply(
                    lambda d: d <= as_of if isinstance(d, datetime.date) else True
                )
                basket_df = basket_df[issued].reset_index(drop=True)

            delivery_start, delivery_end = delivery_business_window(contract_imm_date)
            spec = get_contract_spec(root)
            contract_coupon = float(basket_df["futures_coupon"].iloc[0]) if "futures_coupon" in basket_df.columns else 6.0

            # preserve row-order to keep conversion factors aligned with basket_pricers
            issue_dates = (
                basket_df["issue_date"].apply(lambda d: d.isoformat() if isinstance(d, datetime.date) else str(d)).tolist()
                if "issue_date" in basket_df.columns
                else [None] * len(basket_df)
            )
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
                "issue_dates": issue_dates,
                "contract_coupon": float(contract_coupon),
                "calc_mode": spec.calc_mode,
                "contract_imm_date": contract_imm_date,
            }

            with self:
                self._threadsafe_basket_cache_put(cache_key, cached)

        # hydrate cached definition -> live cash pricers for this as_of close
        close_2pm = pytz.timezone("America/Chicago").localize(datetime.datetime(as_of.year, as_of.month, as_of.day, 14, 0))

        cusips: List[str] = list(cached["cusips"])
        cfs_cached: List[float] = list(cached["conversion_factors"])
        issue_dates_raw: List[Any] = cached.get("issue_dates") or [None] * len(cusips)

        # Skip WI bonds whose issue_date > as_of — FedInvest has no price yet.
        # Handles both fresh caches (filtered at build) and stale caches (unfiltered).
        eligible_cusips: List[str] = []
        eligible_cfs: List[float] = []
        for c, cf, isd_raw in zip(cusips, cfs_cached, issue_dates_raw):
            if isd_raw is not None:
                try:
                    isd = datetime.date.fromisoformat(str(isd_raw)[:10])
                    if isd > as_of:
                        continue
                except (ValueError, TypeError):
                    pass
            eligible_cusips.append(c)
            eligible_cfs.append(cf)

        cash_pricers = usts_mdp.get_data({"cusips": list(set(eligible_cusips)), "timestamp": close_2pm})

        basket_pricers: List[Any] = []
        conversion_factors: List[float] = []
        for cusip, cf in zip(eligible_cusips, eligible_cfs):
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

        # Use the pricer's OWN basket rather than fetching a second one.
        #
        # This used to call get_delivery_basket() again here, with ignore_cache=force_refresh,
        # while get_pricer() had already built its basket straight off the basket cache. The row
        # loop below then zipped THAT basket's cusips/labels/prices/CFs against gross_basis,
        # bnoc and irr vectors computed from the pricer's basket. Whenever the two disagreed --
        # exactly what happens on the first force_refresh after a deliverable-window change, when
        # the cache still holds the old basket -- every risk number was silently attached to the
        # wrong bond. It also cost a duplicate FixedRateBondsMDP round-trip per report.
        basket_pricers = list(pricer._basket_pricers)
        basket_cfs = pricer.conversion_factors()
        if len(basket_pricers) != len(basket_cfs):
            raise ValueError(
                f"Basket/conversion-factor length mismatch for {resolved_symbol}: "
                f"{len(basket_pricers)} pricers vs {len(basket_cfs)} factors"
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

        if not (len(basket_pricers) == len(gross_basis_vec) == len(bnoc_vec) == len(irr_vec)):
            raise ValueError(
                f"Basis vectors misaligned with the basket for {resolved_symbol}: "
                f"basket={len(basket_pricers)} gross={len(gross_basis_vec)} "
                f"bnoc={len(bnoc_vec)} irr={len(irr_vec)}"
            )

        rows: List[Dict[str, Any]] = []
        for bond_pricer, cf, gross_basis, bnoc, irr in zip(
            basket_pricers,
            basket_cfs,
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
                    "schema_version": _BASIS_REPORT_SCHEMA_VERSION,
                    "spec_fingerprint": contract_specs_fingerprint(),
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
        on_bad_data: OnBadData = "raise",
    ) -> pd.DataFrame:
        ts_dt = _as_datetime(timestamp)
        resolved_symbol = self._resolve_contract_symbol(_normalize_symbol(symbol) or symbol, ts_dt)
        # force_refresh skips the cache READ but must NOT skip the WRITE -- otherwise there is no
        # way to repair a poisoned entry through this API, and the store (plus whatever Supabase
        # holds) keeps serving the old value forever.
        core_ts_dt = self._basis_report_core_timestamp(
            timestamp=timestamp,
            basket_source=basket_source,
            usts_mdp_source=usts_mdp_source,
            curve_id=curve_id,
            repo_rate=repo_rate,
        )
        trading_date = self._trading_date_for_timestamp(core_ts_dt or ts_dt)

        if core_ts_dt is not None and not force_refresh:
            cached_df = self._get_ust_future_store().read_basis_report_day(resolved_symbol, trading_date)
            if not cached_df.empty and not self._basis_report_cache_is_current(cached_df):
                # Stale schema -> treat as a miss. Do NOT trust a report built by older code.
                cached_df = pd.DataFrame()
            if not cached_df.empty:
                cached_df = cached_df.loc[
                    :, [col for col in self._basis_report_columns() if col in cached_df.columns]
                ].copy()
                # Gate the CACHED path too. A cache written before a fix still holds the corrupt
                # rows, and the read path is where a consumer meets them.
                return enforce_basis_report_quality(
                    cached_df, symbol=resolved_symbol, on_bad_data=on_bad_data
                )

        report_df = self._build_basis_report_frame(
            symbol=resolved_symbol,
            timestamp=timestamp,
            basket_source=basket_source,
            usts_mdp_source=usts_mdp_source,
            curve_id=curve_id,
            repo_rate=repo_rate,
            force_refresh=force_refresh,
        )
        report_df = enforce_basis_report_quality(
            report_df, symbol=resolved_symbol, on_bad_data=on_bad_data
        )
        # Never persist a report that failed the gate, whatever on_bad_data says. "warn" means the
        # CALLER wants to carry on past a bad day; it does not mean the bad day should be cached
        # and handed to everyone else afterwards. (Learned the hard way: a backfill running with
        # on_bad_data="warn" wrote the failing reports into the store, and the next run served
        # them from cache -- with a fresh schema stamp, so they looked current.)
        failed_gate = "data_ok" in report_df.columns and not bool(report_df["data_ok"].all())
        if core_ts_dt is not None and not report_df.empty and not failed_gate:
            self._get_ust_future_store().write_basis_report_day(resolved_symbol, trading_date, report_df, overwrite=force_refresh)
        return report_df

    def get_ctd(
        self,
        as_of: datetime.date,
        symbol: str,
        usts_mdp: Optional[FixedRateBondsMDP] = None,
        repo: Optional[float] = None,
        source: Optional[str] = "RL_CME_TCF",
        on_bad_data: OnBadData = "raise",
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
            # get_ctd is a THIRD public exit from this surface -- it calls the builder directly and
            # so never passed through get_basis_report's gate. Gate it here or it stays the one way
            # to read a corrupt basis report without being told.
            report_df = enforce_basis_report_quality(
                report_df, symbol=str(symbol), on_bad_data=on_bad_data
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
