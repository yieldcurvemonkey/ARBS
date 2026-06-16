import asyncio
import logging
import random
import re
import threading
import time
import warnings
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from functools import reduce
from io import StringIO
from typing import Annotated, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote, unquote, urlencode, urlparse

import httpx
import pandas as pd
import pytz
import requests
import tqdm
import tqdm.asyncio
from requests.adapters import HTTPAdapter

warnings.simplefilter(action="ignore", category=FutureWarning)

import sys

if sys.platform == "win32":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)


class BaseFetcher:
    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: bool = False,
        info_verbose: bool = False,
        warning_verbose: bool = False,
        error_verbose: bool = False,
    ):
        self._global_timeout = global_timeout
        self._proxies = proxies if proxies else {"http": None, "https": None}

        # httpx/socksio only understands socks5:// — not socks5h:// (remote DNS).
        # requests/PySocks handles socks5h natively, so keep self._proxies as-is
        # for the token-fetch Session but downgrade the scheme for httpx transports.
        def _httpx_proxy_url(url: Optional[str]) -> Optional[str]:
            if url and url.startswith("socks5h://"):
                return "socks5://" + url[len("socks5h://"):]
            return url

        self._httpx_proxies = {
            "http://": httpx.AsyncHTTPTransport(proxy=_httpx_proxy_url(self._proxies["http"])),
            "https://": httpx.AsyncHTTPTransport(proxy=_httpx_proxy_url(self._proxies["https"])),
        }

        self._debug_verbose = debug_verbose
        self._info_verbose = info_verbose
        self._error_verbose = error_verbose
        self._warning_verbose = warning_verbose
        self._setup_logger()

    def _setup_logger(self):
        self._logger = logging.getLogger(self.__class__.__name__)

        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            self._logger.addHandler(handler)

        if self._debug_verbose:
            self._logger.setLevel(logging.DEBUG)
        elif self._info_verbose:
            self._logger.setLevel(logging.INFO)
        elif self._error_verbose:
            self._logger.setLevel(logging.ERROR)
        elif self._warning_verbose:
            self._logger.setLevel(logging.WARNING)
        else:
            self._logger.disabled = True


class AsyncRateLimiter:
    """
    Simple sliding-window async rate limiter.
    Example: max_calls=8, period=1.0 -> at most 8 requests per second.
    """

    def __init__(self, max_calls: int, period: float = 1.0):
        self.max_calls = max(1, int(max_calls))
        self.period = max(float(period), 0.01)
        self._calls = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        loop = asyncio.get_running_loop()

        while True:
            async with self._lock:
                now = loop.time()

                while self._calls and (now - self._calls[0]) >= self.period:
                    self._calls.popleft()

                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return

                sleep_for = self.period - (now - self._calls[0])

            await asyncio.sleep(max(sleep_for, 0.01))


class BarchartFetcher(BaseFetcher):
    _current_laravel_token: str = None
    _current_xsrf_token: str = None
    _BARCHART_MAX_RECORD = 5_000
    _SOCKS5_AUTH_RETRY_SLEEP_SECONDS = 60
    _SESSION_TOKEN_TTL_SECONDS = 60
    _SESSION_TOKEN_POOL_SIZE = 3
    _SESSION_TOKEN_FORCE_REFRESH_COOLDOWN_SECONDS = 5
    _TOKEN_WARM_MAX_WORKERS = 16
    _SHARED_SESSION_TOKEN_CACHE: Dict[str, Dict[str, object]] = {}
    _SHARED_SESSION_TOKEN_CACHE_LOCK = threading.RLock()
    _STIR_ROOT_CODE_RE = re.compile(
        r"^(SR[13]|SFR|SER|FF|ZQ|SQ|SL|RA|EB|IJ|RG|IM|TV|J8|JU|T0|IT|J2)([FGHJKMNQUVXZ]\d{2})$",
        re.IGNORECASE,
    )
    _STIR_ROOT_TO_BARCHART = {
        "SR3": "SQ",
        "SFR": "SQ",
        "SQ": "SQ",
        "SR1": "SL",
        "SER": "SL",
        "SL": "SL",
        "ZQ": "ZQ",
        "FF": "ZQ",
        "RA": "RA",  # Eurex 3M ESTR
        "EB": "EB",  # ICE 3M ESTR
        "IJ": "IJ",  # ICE 1M ESTR
        "RG": "RG",  # B3 3M CORRA
        "IM": "IM",  # ICE 3M Euribor
        "TV": "TV",  # Eurex 3M Euribor
        "J8": "J8",  # ICE 3M SONIA
        "JU": "JU",  # ICE 1M SONIA
        "T0": "T0",  # JPX 3M TONA
        "IT": "IT",  # TFX 3M TONA
        "J2": "J2",  # Eurex 3M SARON
    }

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        warning_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
        session_token_ttl_seconds: Optional[int] = None,
        session_token_pool_size: Optional[int] = None,
        session_token_scope: Optional[str] = None,
        session_token_force_refresh_cooldown_seconds: Optional[int] = None,
        proxy_auth_retries: int = 1,
    ):
        super().__init__(
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )
        ttl = self._SESSION_TOKEN_TTL_SECONDS if session_token_ttl_seconds is None else int(session_token_ttl_seconds)
        pool_size = self._SESSION_TOKEN_POOL_SIZE if session_token_pool_size is None else int(session_token_pool_size)
        force_refresh_cooldown = (
            self._SESSION_TOKEN_FORCE_REFRESH_COOLDOWN_SECONDS
            if session_token_force_refresh_cooldown_seconds is None
            else int(session_token_force_refresh_cooldown_seconds)
        )
        self._session_token_ttl_seconds = max(1, ttl)
        self._session_token_pool_size = max(1, pool_size)
        self._session_token_scope = session_token_scope
        self._session_token_force_refresh_cooldown_seconds = max(0, force_refresh_cooldown)
        # Default SOCKS5-auth retry budget for this fetcher. The single-proxy path keeps the
        # heal-and-retry default (1 -> one 60s wait); fan-out workers set 0 so a flaky proxy
        # raises instantly and is evicted/requeued instead of stalling a whole shard for 60s.
        self._proxy_auth_retries = max(0, int(proxy_auth_retries))
        self._last_history_status_by_symbol: Dict[str, Dict[str, object]] = {}
        # Token fetches use a fresh, self-closing session per call (_make_token_http_session)
        # so the pool warm can run them concurrently; there is no long-lived session to hold.

    def close(self) -> None:
        # Per-call token sessions close themselves; nothing long-lived to release.
        return None

    def get_history_statuses(self) -> Dict[str, Dict[str, object]]:
        return dict(self._last_history_status_by_symbol)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @classmethod
    def _normalize_barchart_symbol(cls, symbol: str) -> str:
        s = (symbol or "").strip().upper().replace("/", "")
        m = cls._STIR_ROOT_CODE_RE.match(s)
        if not m:
            return s
        root, code = m.group(1).upper(), m.group(2).upper()
        return f"{cls._STIR_ROOT_TO_BARCHART.get(root, root)}{code}"

    @classmethod
    def clear_shared_session_token_cache(cls):
        with cls._SHARED_SESSION_TOKEN_CACHE_LOCK:
            cls._SHARED_SESSION_TOKEN_CACHE.clear()

    @staticmethod
    def _proxy_scope_component(proxy_url: Optional[str]) -> str:
        if not proxy_url:
            return ""
        parsed = urlparse(proxy_url)
        scheme = (parsed.scheme or "").lower()
        host = (parsed.hostname or "").lower()
        port = str(parsed.port or "")
        username = parsed.username or ""
        password = parsed.password or ""
        return f"{scheme}|{host}|{port}|{username}|{password}"

    def _session_cache_key(self) -> str:
        if self._session_token_scope:
            return f"scope:{self._session_token_scope}"
        http_scope = self._proxy_scope_component(self._proxies.get("http"))
        https_scope = self._proxy_scope_component(self._proxies.get("https"))
        proxy_scope = f"{http_scope}|{https_scope}" if (http_scope or https_scope) else "direct"
        return f"default:{proxy_scope}"

    @staticmethod
    def _normalize_cookie_token(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        token = unquote(str(value)).strip()
        if len(token) >= 2 and token[0] == token[-1] == '"':
            token = token[1:-1]
        return token or None

    @classmethod
    def _token_cookie_header(cls, token_pair: Tuple[str, str]) -> str:
        laravel = cls._normalize_cookie_token(token_pair[0]) or ""
        xsrf = cls._normalize_cookie_token(token_pair[1]) or ""
        xsrf_cookie = quote(xsrf, safe="")
        return f"laravel_token={laravel}; XSRF-TOKEN={xsrf_cookie}"

    def _apply_session_token(self, token_pair: Tuple[str, str]) -> Tuple[str, str]:
        laravel = self._normalize_cookie_token(token_pair[0])
        xsrf = self._normalize_cookie_token(token_pair[1])
        if not laravel or not xsrf:
            raise ValueError("Invalid Barchart token pair")
        self._current_laravel_token, self._current_xsrf_token = laravel, xsrf
        return laravel, xsrf

    @staticmethod
    def _empty_token_slot() -> Dict[str, object]:
        return {"token_pair": None, "expires_at": 0.0}

    @staticmethod
    def _is_socks5_auth_error(exc: Exception) -> bool:
        message = str(exc or "").lower()
        return "socks5 authentication failed" in message or "socks authentication failed" in message

    def _proxy_auth_retry_sleep_seconds(self) -> int:
        return max(0, int(self._SOCKS5_AUTH_RETRY_SLEEP_SECONDS))

    def _get_shared_session_token_with_proxy_retry(
        self,
        dummy_symbol: Optional[str] = "BTC",
        force_refresh: bool = False,
        log_context: str = "Barchart session token fetch",
        max_proxy_auth_retries: Optional[int] = None,
    ) -> Tuple[str, str]:
        retries = 0
        if max_proxy_auth_retries is None:
            max_proxy_auth_retries = self._proxy_auth_retries
        max_retries = max(0, int(max_proxy_auth_retries))
        while True:
            try:
                return self._get_shared_session_token(dummy_symbol=dummy_symbol, force_refresh=force_refresh)
            except Exception as exc:
                if retries >= max_retries or not self._is_socks5_auth_error(exc):
                    raise
                retries += 1
                wait_seconds = self._proxy_auth_retry_sleep_seconds()
                self._logger.warning(
                    f"{log_context} - SOCKS5 authentication failed for {dummy_symbol}: {exc}. "
                    f"Waiting {wait_seconds} seconds before retrying proxy authentication."
                )
                time.sleep(wait_seconds)

    async def _get_shared_session_token_with_proxy_retry_async(
        self,
        dummy_symbol: Optional[str] = "BTC",
        force_refresh: bool = False,
        log_context: str = "Barchart session token fetch",
        max_proxy_auth_retries: Optional[int] = None,
    ) -> Tuple[str, str]:
        retries = 0
        if max_proxy_auth_retries is None:
            max_proxy_auth_retries = self._proxy_auth_retries
        max_retries = max(0, int(max_proxy_auth_retries))
        while True:
            try:
                return self._get_shared_session_token(dummy_symbol=dummy_symbol, force_refresh=force_refresh)
            except Exception as exc:
                if retries >= max_retries or not self._is_socks5_auth_error(exc):
                    raise
                retries += 1
                wait_seconds = self._proxy_auth_retry_sleep_seconds()
                self._logger.warning(
                    f"{log_context} - SOCKS5 authentication failed for {dummy_symbol}: {exc}. "
                    f"Waiting {wait_seconds} seconds before retrying proxy authentication."
                )
                await asyncio.sleep(wait_seconds)

    def _get_or_create_cache_entry_unlocked(self, cache_key: str) -> Dict[str, object]:
        entry = self._SHARED_SESSION_TOKEN_CACHE.get(cache_key)
        if not isinstance(entry, dict):
            entry = {}
            self._SHARED_SESSION_TOKEN_CACHE[cache_key] = entry

        tokens = entry.get("tokens")
        if not isinstance(tokens, list):
            tokens = []
        tokens = [slot if isinstance(slot, dict) else self._empty_token_slot() for slot in tokens]

        target_size = int(self._session_token_pool_size)
        if len(tokens) < target_size:
            tokens.extend(self._empty_token_slot() for _ in range(target_size - len(tokens)))
        elif len(tokens) > target_size:
            tokens = tokens[:target_size]

        rr_index = entry.get("rr_index", 0)
        try:
            rr_index = int(rr_index)
        except Exception:
            rr_index = 0

        entry["tokens"] = tokens
        entry["rr_index"] = rr_index % max(1, target_size)
        return entry

    @staticmethod
    def _token_slot_is_valid(slot: Dict[str, object], now: float) -> bool:
        token_pair = slot.get("token_pair")
        if not (isinstance(token_pair, tuple) and len(token_pair) == 2):
            return False
        try:
            expires_at = float(slot.get("expires_at", 0.0))
        except Exception:
            return False
        return now < expires_at

    def _get_shared_session_token(
        self,
        dummy_symbol: Optional[str] = "BTC",
        force_refresh: bool = False,
    ) -> Tuple[str, str]:
        cache_key = self._session_cache_key()

        with self._SHARED_SESSION_TOKEN_CACHE_LOCK:
            entry = self._get_or_create_cache_entry_unlocked(cache_key)
            tokens = entry["tokens"]  # type: ignore[index]
            slot_count = max(1, len(tokens))
            idx = int(entry.get("rr_index", 0)) % slot_count
            now = time.time()
            last_forced_refresh_at = float(entry.get("last_forced_refresh_at", 0.0) or 0.0)
            force_refresh_cooldown = float(self._session_token_force_refresh_cooldown_seconds)

            # Prevent refresh storms: only one forced refresh per cooldown window.
            if force_refresh and force_refresh_cooldown > 0.0:
                if now - last_forced_refresh_at < force_refresh_cooldown:
                    force_refresh = False

            slot = tokens[idx]
            if force_refresh or not self._token_slot_is_valid(slot=slot, now=now):
                token_pair = self._get_new_session_token(dummy_symbol=dummy_symbol)
                slot["token_pair"] = token_pair
                slot["expires_at"] = now + float(self._session_token_ttl_seconds)
            else:
                token_pair = slot["token_pair"]
            entry["rr_index"] = (idx + 1) % slot_count
            entry["updated_at"] = now
            if force_refresh:
                entry["last_forced_refresh_at"] = now
            return self._apply_session_token(token_pair)

    def _get_new_session_token_with_proxy_retry(
        self,
        dummy_symbol: Optional[str] = "BTC",
        max_proxy_auth_retries: Optional[int] = None,
    ) -> Tuple[str, str]:
        """Raw token fetch with the same SOCKS5-auth retry behavior as the cached path."""
        retries = 0
        if max_proxy_auth_retries is None:
            max_proxy_auth_retries = self._proxy_auth_retries
        max_retries = max(0, int(max_proxy_auth_retries))
        while True:
            try:
                return self._get_new_session_token(dummy_symbol=dummy_symbol)
            except Exception as exc:
                if retries >= max_retries or not self._is_socks5_auth_error(exc):
                    raise
                retries += 1
                time.sleep(self._proxy_auth_retry_sleep_seconds())

    def _get_shared_session_token_pool(
        self,
        pool_size: int,
        dummy_symbol: Optional[str] = "BTC",
    ) -> List[Tuple[str, str]]:
        """Warm/return a rotation of ``pool_size`` shared session tokens.

        Cold/expired slots are fetched concurrently with network I/O happening *outside*
        the shared cache lock. This preserves the sequential contract -- exactly the
        invalid slots in the rotation get a fresh token, ``rr_index`` advances by
        ``pool_size``, and the last token in the rotation becomes the instance's current
        token -- while collapsing N serial round-trips into one parallel batch.
        """
        size = max(1, int(pool_size))
        cache_key = self._session_cache_key()

        # Phase 1 (locked): plan the rotation; find the distinct invalid slots to warm.
        with self._SHARED_SESSION_TOKEN_CACHE_LOCK:
            entry = self._get_or_create_cache_entry_unlocked(cache_key)
            tokens = entry["tokens"]  # type: ignore[index]
            slot_count = max(1, len(tokens))
            start_idx = int(entry.get("rr_index", 0)) % slot_count
            now = time.time()
            rotation = [(start_idx + i) % slot_count for i in range(size)]
            need_indices: List[int] = []
            seen: set = set()
            for idx in rotation:
                if idx in seen:
                    continue
                seen.add(idx)
                if not self._token_slot_is_valid(slot=tokens[idx], now=now):
                    need_indices.append(idx)
            entry["rr_index"] = (start_idx + size) % slot_count
            entry["updated_at"] = now

        # Phase 2 (unlocked): fetch the needed tokens concurrently (no lock held).
        fetched: Dict[int, Tuple[str, str]] = {}
        if len(need_indices) == 1:
            fetched[need_indices[0]] = self._get_new_session_token_with_proxy_retry(dummy_symbol=dummy_symbol)
        elif need_indices:
            max_workers = max(1, min(len(need_indices), int(self._TOKEN_WARM_MAX_WORKERS)))
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bc-tokwarm") as executor:
                future_to_idx = {
                    executor.submit(self._get_new_session_token_with_proxy_retry, dummy_symbol): idx
                    for idx in need_indices
                }
                for future in as_completed(future_to_idx):
                    fetched[future_to_idx[future]] = future.result()

        # Phase 3 (locked): install fetched tokens and build the rotation result.
        with self._SHARED_SESSION_TOKEN_CACHE_LOCK:
            entry = self._get_or_create_cache_entry_unlocked(cache_key)
            tokens = entry["tokens"]  # type: ignore[index]
            slot_count = max(1, len(tokens))
            now = time.time()
            expires_at = now + float(self._session_token_ttl_seconds)
            for idx, token_pair in fetched.items():
                if idx >= len(tokens):
                    continue
                slot = tokens[idx]
                # Another thread may have filled it meanwhile; only fill if still invalid.
                if not self._token_slot_is_valid(slot=slot, now=now):
                    slot["token_pair"] = token_pair
                    slot["expires_at"] = expires_at
            result: List[Tuple[str, str]] = []
            for idx in rotation:
                slot = tokens[idx % slot_count]
                token_pair = slot.get("token_pair")
                if isinstance(token_pair, tuple) and len(token_pair) == 2:
                    result.append(self._apply_session_token(token_pair))
            return result

    def _make_token_http_session(self) -> requests.Session:
        """Build a short-lived requests.Session (own connection pool) for one token fetch.

        Each token fetch uses its own session so the pool warm can issue many fetches
        concurrently without serializing on a shared session lock or racing on a shared
        cookie jar. The proxy config is mirrored from the instance.
        """
        session = requests.Session()
        adapter = HTTPAdapter(pool_connections=2, pool_maxsize=2)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session_proxies = {k: v for k, v in (self._proxies or {}).items() if v}
        if session_proxies:
            session.proxies.update(session_proxies)
        return session

    def _get_new_session_token(self, dummy_symbol: Optional[str] = "BTC") -> Tuple[str, str]:
        """
        Fetch and return a new session token pair (laravel_token, XSRF-TOKEN).
        This method is used to build a pool of tokens.
        """
        interactive_chart_url = f"https://www.barchart.com/futures/quotes/{quote(dummy_symbol)}/interactive-chart"
        interactive_chart_headers = {
            "dnt": "1",
            "referer": f"https://www.barchart.com/futures/quotes/{quote(dummy_symbol)}/interactive-chart",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "Connection": "close",
        }
        # Fresh session per call: no shared lock, so concurrent pool warming is truly parallel.
        session = self._make_token_http_session()
        try:
            interactive_chart_res = session.get(
                interactive_chart_url,
                headers=interactive_chart_headers,
                timeout=self._global_timeout,
            )
        finally:
            session.close()
        interactive_chart_res.raise_for_status()

        laravel_token = self._normalize_cookie_token(interactive_chart_res.cookies.get("laravel_token"))
        xsrf_token = self._normalize_cookie_token(interactive_chart_res.cookies.get("XSRF-TOKEN"))
        if laravel_token and xsrf_token:
            return laravel_token, xsrf_token

        set_cookie_header = interactive_chart_res.headers.get("Set-Cookie")
        if not set_cookie_header:
            raise ValueError("Barchart Session Token Cookie Parsing Error: missing Set-Cookie header")

        cookie_pairs = unquote(set_cookie_header).split("; ")
        cleaned_cookie_pairs = []
        for pair in cookie_pairs:
            if ", " in pair:
                newpair1, newpair2 = pair.split(", ")
                cleaned_cookie_pairs.append(newpair1)
                cleaned_cookie_pairs.append(newpair2)
            else:
                cleaned_cookie_pairs.append(pair)

        cookie_dict = {}
        for pair in cleaned_cookie_pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
                cookie_dict[key] = self._normalize_cookie_token(value)

        if "laravel_token" in cookie_dict and "XSRF-TOKEN" in cookie_dict:
            return cookie_dict["laravel_token"], cookie_dict["XSRF-TOKEN"]
        else:
            raise ValueError("Barchart Session Token Cookie Parsing Error: could not find laravel_token and XSRF-TOKEN")

    def _fetch_session_tokens(self, dummy_symbol: Optional[str] = "BTC"):
        """
        Fallback session token fetch which also sets the instance tokens.
        """
        self._get_shared_session_token_pool(pool_size=self._session_token_pool_size, dummy_symbol=dummy_symbol)

    def _parse_aspx_response_to_df(self, response_content: bytes, columns: Optional[List[str]] = None):
        if isinstance(response_content, bytes):
            response_content = response_content.decode("utf-8")

        data_stream = StringIO(response_content)
        df = pd.read_csv(data_stream, header=None)
        if columns and len(columns) == len(df.columns):
            df.columns = columns
        if columns and len(columns) - 1 == len(df.columns):
            df.columns = columns[:-1]

        return df

    @staticmethod
    def _history_retry_sleep_seconds(
        attempt: int,
        *,
        backoff_factor: float,
        retry_after: Optional[str] = None,
        jitter: float = 0.5,
    ) -> float:
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except (TypeError, ValueError):
                pass
        base_sleep = max(float(backoff_factor), 0.0) * (2 ** max(int(attempt) - 1, 0))
        if jitter > 0.0:
            base_sleep += random.uniform(0.0, float(jitter))
        return max(base_sleep, 0.0)

    async def _fetch_intraday_timeseries(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        interval: Literal[1, 5, 10, 15, 30, 60, 120, 240],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        columns: Optional[List[str]] = ["Date", "temp", "Open", "High", "Low", "Close", "Volume"],
        set_dt_index: Optional[bool] = True,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
        uid: Optional[str | int] = None,
        session_token: Optional[Tuple[str, str]] = None,
    ) -> Tuple[str, pd.DataFrame] | Tuple[str, pd.DataFrame, str]:

        token = session_token

        # Validate timezone info & consistency
        def _tz_ok(dt: Optional[datetime]) -> bool:
            return (dt is None) or (dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None)

        if not _tz_ok(start_date) or not _tz_ok(end_date):
            raise ValueError("start_date and end_date must include timezone information if provided.")

        # Barchart intraday timestamps are always exchange-local (Central for futures/forex).
        exchange_tz = pytz.timezone("America/Chicago")
        request_tzinfo = (start_date or end_date).tzinfo if (start_date or end_date) else exchange_tz
        request_tz_name = getattr(request_tzinfo, "zone", None) or getattr(request_tzinfo, "key", None)
        request_tz = pytz.timezone(request_tz_name) if request_tz_name else request_tzinfo
        start_exchange = start_date.astimezone(exchange_tz) if start_date is not None else None
        end_exchange = end_date.astimezone(exchange_tz) if end_date is not None else None

        base_url = (
            f"https://www.barchart.com/proxies/timeseries/historical/queryminutes.ashx?"
            f"symbol={quote(symbol)}&interval={interval}&maxrecords={self._BARCHART_MAX_RECORD}"
            f"&volume=contract&order=asc"
        )

        def build_headers(token: Tuple[str, str]):
            token_pair = self._apply_session_token(token)
            return {
                "dnt": "1",
                "referer": f"https://www.barchart.com/futures/quotes/{quote(symbol)}/interactive-chart",
                "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                "cookie": self._token_cookie_header(token_pair),
                "x-xsrf-token": token_pair[1],
            }

        # Helper: fetch a single slice with retries, optionally with an end cursor
        async def _fetch_slice(token: Tuple[str, str], end_cursor: Optional[datetime]) -> Optional[pd.DataFrame]:
            headers = build_headers(token=token)

            # build URL with optional &end
            if end_cursor is not None:
                if end_cursor.tzinfo is None or end_cursor.tzinfo.utcoffset(end_cursor) is None:
                    raise ValueError("Internal error: end_cursor must be tz-aware.")
                end_str = end_cursor.astimezone(exchange_tz).strftime("%Y%m%d%H%M")
                url = f"{base_url}&end={end_str}"
            else:
                url = base_url  # latest

            retries = 0
            last_status_code: Optional[int] = None
            while retries < max_retries:
                try:
                    if retries > 0:
                        # First retry rotates to the next token; later retries can force-refresh.
                        should_force_refresh = retries >= 2
                        if last_status_code in (401, 403):
                            should_force_refresh = True
                        token = await self._get_shared_session_token_with_proxy_retry_async(
                            dummy_symbol=symbol,
                            force_refresh=should_force_refresh,
                            log_context="Barchart Intraday token refresh",
                        )
                        headers = build_headers(token=token)

                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    last_status_code = None
                    if not resp.content:
                        self._logger.debug(f"Empty content received for symbol {symbol}")
                        return None

                    df_slice = self._parse_aspx_response_to_df(resp.content, columns=columns)
                    if df_slice is None or df_slice.empty:
                        return None

                    # Clean/prepare
                    if "temp" in df_slice.columns:
                        df_slice = df_slice.drop(columns=["temp"])
                    if "Date" not in df_slice.columns:
                        return None

                    # Parse and localize/conform tz
                    df_slice["Date"] = pd.to_datetime(df_slice["Date"], errors="coerce")
                    df_slice = df_slice.dropna(subset=["Date"])
                    if getattr(df_slice["Date"].dt, "tz", None) is None:
                        df_slice["Date"] = df_slice["Date"].dt.tz_localize(exchange_tz)
                    else:
                        df_slice["Date"] = df_slice["Date"].dt.tz_convert(exchange_tz)

                    return df_slice

                except httpx.HTTPStatusError:
                    status = getattr(resp, "status_code", "unknown")
                    try:
                        last_status_code = int(status)
                    except Exception:
                        last_status_code = None
                    self._logger.debug(f"Barchart Intraday - Bad Status for {symbol}: {status}")
                    if status == 404:
                        return None
                except Exception as e:
                    last_status_code = None
                    self._logger.debug(f"Barchart Intraday - Error for {symbol}: {str(e)}")

                retries += 1
                wait_time = backoff_factor * (2 ** (retries - 1))
                self._logger.debug(f"Barchart Intraday - Throttled for {symbol}. Waiting {wait_time}s before retrying (attempt {retries}/{max_retries})...")

                await asyncio.sleep(wait_time)

            return None

        try:
            if token is None:
                token = await self._get_shared_session_token_with_proxy_retry_async(
                    dummy_symbol=symbol,
                    force_refresh=False,
                    log_context="Barchart Intraday token fetch",
                )

            # Cursoring: start with end_date (if provided), else latest (None)
            # Each slice returns up to MAX_RECORD rows ending at `end_cursor` (inclusive), going backwards.
            # We page backward until we cross start_date or can’t get more.
            end_cursor = end_exchange if end_exchange is not None else None
            slices: List[pd.DataFrame] = []
            seen_earliest: Optional[pd.Timestamp] = None

            # Safety cap: avoid infinite loops if API behaves unexpectedly.
            # For 1-min data, 1000 slices already covers ~500k rows ~1yr intraday min data.
            MAX_SLICES = 100

            for _ in range(MAX_SLICES):
                df_slice = await _fetch_slice(token=token, end_cursor=end_cursor)
                if df_slice is None or df_slice.empty:
                    break

                # If the API returns future/open-ended rows when no end is provided, cap by end_date if present
                if end_exchange is not None:
                    df_slice = df_slice[df_slice["Date"] <= end_exchange]

                slices.append(df_slice)

                earliest = df_slice["Date"].min()
                latest = df_slice["Date"].max()

                # Stop if we already covered start_date
                if start_exchange is not None and earliest <= start_exchange:
                    break

                # Detect no-progress and break
                if seen_earliest is not None and earliest >= seen_earliest:
                    break
                seen_earliest = earliest

                # Page one interval earlier than the earliest we saw to avoid overlap
                # (Barchart’s `end` is inclusive). Subtract `interval` minutes.
                step_minutes = int(interval)
                end_cursor = earliest - pd.Timedelta(minutes=step_minutes)

            if not slices:
                if uid:
                    return symbol, None, uid
                return symbol, None

            df = pd.concat(slices, ignore_index=True)
            df = df.drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"])
            if getattr(df["Date"].dt, "tz", None) is None:
                df["Date"] = df["Date"].dt.tz_localize(exchange_tz)
            else:
                df["Date"] = df["Date"].dt.tz_convert(exchange_tz)
            df_copy = df.copy()

            if start_exchange is not None:
                df = df[df["Date"] >= start_exchange]
            if end_exchange is not None:
                df = df[df["Date"] <= end_exchange]

            if df.empty and not df_copy.empty and start_exchange and end_exchange:
                df_copy = df_copy.set_index("Date")
                new_index = pd.date_range(start=start_exchange, end=end_exchange, freq=f"{interval}min", tz=exchange_tz)
                combined_index = df_copy.index.union(new_index)
                df_reindexed = df_copy.reindex(combined_index)
                df_filled = df_reindexed.ffill().bfill()
                df = df_filled.loc[new_index].reset_index().rename(columns={"index": "Date"})

            if request_tz is not None:
                df["Date"] = df["Date"].dt.tz_convert(request_tz)

            if set_dt_index:
                df = df.set_index("Date")

            if uid:
                return symbol, df, uid
            return symbol, df

        except Exception as e:
            self._logger.debug(e)
            if uid:
                return symbol, None, uid
            return symbol, None

    @staticmethod
    def _format_eod_boundary(value: Optional[datetime | date | str]) -> Optional[str]:
        """Format a date boundary as YYYYMMDD for the queryeod ``start``/``end`` params."""
        if value is None:
            return None
        if isinstance(value, (datetime, date)):
            return value.strftime("%Y%m%d")
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.strftime("%Y%m%d")

    def _build_eod_url(
        self,
        symbol: str,
        *,
        start: Optional[datetime | date | str] = None,
        end: Optional[datetime | date | str] = None,
        server_side_dates: bool = False,
    ) -> str:
        """Build the queryeod URL.

        By default no date bounds are sent (the endpoint returns full history, which is
        what the per-symbol frame cache wants so one fetch serves every window). When
        ``server_side_dates`` is set, ``&start=&end=`` shrink the payload server-side --
        used for cheap incremental tail refreshes of an already-cached symbol.
        """
        url = (
            f"https://www.barchart.com/proxies/timeseries/historical/queryeod.ashx?"
            f"symbol={quote(symbol)}&data=daily&maxrecords={self._BARCHART_MAX_RECORD}"
            f"&volume=contract&order=asc"
        )
        if server_side_dates:
            start_str = self._format_eod_boundary(start)
            end_str = self._format_eod_boundary(end)
            if start_str:
                url += f"&start={start_str}"
            if end_str:
                url += f"&end={end_str}"
        return url

    async def _fetch_eod_timeseries(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        columns: Optional[List[str]] = ["Symbol", "Date", "Open", "High", "Low", "Close", "Volume", "Open Interest"],
        set_dt_index: Optional[bool] = True,
        max_retries: Optional[int] = 5,
        backoff_factor: Optional[float] = 1.5,
        uid: Optional[str | int] = None,
        session_token: Optional[Tuple[str, str]] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        server_side_dates: bool = False,
    ) -> Tuple[str, pd.DataFrame] | Tuple[str, pd.DataFrame, str]:
        token = session_token
        saw_429 = False

        try:
            if token is None:
                token = await self._get_shared_session_token_with_proxy_retry_async(
                    dummy_symbol=symbol,
                    force_refresh=False,
                    log_context="Barchart EOD token fetch",
                )

            url = self._build_eod_url(
                symbol,
                start=start_date,
                end=end_date,
                server_side_dates=server_side_dates,
            )

            def _build_headers(token_pair: Tuple[str, str]) -> Dict[str, str]:
                token_pair = self._apply_session_token(token_pair)
                return {
                    "dnt": "1",
                    "referer": f"https://www.barchart.com/futures/quotes/{quote(symbol)}/interactive-chart",
                    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                    "cookie": self._token_cookie_header(token_pair),
                    "x-xsrf-token": token_pair[1],
                }

            headers = _build_headers(token)
            max_attempts = max(1, int(max_retries or 1))
            last_status_code: Optional[int] = None

            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        # First retry rotates to the next token; later retries can force-refresh.
                        should_force_refresh = attempt >= 3
                        if last_status_code in (401, 403):
                            should_force_refresh = True
                        token = await self._get_shared_session_token_with_proxy_retry_async(
                            dummy_symbol=symbol,
                            force_refresh=should_force_refresh,
                            log_context="Barchart EOD token refresh",
                        )
                        headers = _build_headers(token)

                    if rate_limiter is not None:
                        await rate_limiter.acquire()

                    response = await client.get(url, headers=headers)

                    if response.status_code == 429:
                        saw_429 = True
                        last_status_code = 429
                        sleep_for = self._history_retry_sleep_seconds(
                            attempt,
                            backoff_factor=float(backoff_factor or 0.0),
                            retry_after=response.headers.get("Retry-After"),
                        )
                        self._logger.warning(
                            f"Barchart EOD - 429 for {symbol} on attempt {attempt}/{max_attempts}. "
                            f"Sleeping {sleep_for:.2f}s"
                        )
                        if attempt < max_attempts:
                            await asyncio.sleep(sleep_for)
                            continue
                        self._last_history_status_by_symbol[str(symbol)] = {
                            "status_code": 429,
                            "reason": "max_retries_exceeded",
                            "saw_429": saw_429,
                        }
                        self._logger.error(f"Barchart EOD - Max retries exceeded for {symbol}: HTTP 429")
                        if uid:
                            return symbol, None, uid
                        return symbol, None

                    response.raise_for_status()
                    last_status_code = None
                    df = self._parse_aspx_response_to_df(response.content, columns=columns)

                    if "Symbol" in df.columns:
                        df = df.drop(columns=["Symbol"])

                    if "Date" in df.columns:
                        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                        if set_dt_index:
                            df = df.set_index("Date")
                        if start_date:
                            df = df[df["Date"] >= start_date] if not set_dt_index else df[df.index >= start_date]
                        if end_date:
                            df = df[df["Date"] <= end_date] if not set_dt_index else df[df.index <= end_date]

                    self._last_history_status_by_symbol[str(symbol)] = {
                        "status_code": 200,
                        "reason": "ok",
                        "saw_429": saw_429,
                    }

                    if uid:
                        return symbol, df, uid
                    return symbol, df

                except pd.errors.EmptyDataError:
                    self._logger.error(f"Barchart EOD - Empty data error: No columns to parse from file for symbol {symbol}")
                    self._last_history_status_by_symbol[str(symbol)] = {
                        "status_code": None,
                        "reason": "empty_data",
                        "saw_429": saw_429,
                    }
                    if uid:
                        return symbol, None, uid
                    return symbol, None

                except httpx.HTTPStatusError as e:
                    status = e.response.status_code if e.response is not None else last_status_code
                    try:
                        last_status_code = int(status) if status is not None else None
                    except Exception:
                        last_status_code = None
                    if last_status_code == 429:
                        saw_429 = True
                    if last_status_code == 404:
                        self._last_history_status_by_symbol[str(symbol)] = {
                            "status_code": 404,
                            "reason": "http_404",
                            "saw_429": saw_429,
                        }
                        if uid:
                            return symbol, None, uid
                        return symbol, None

                    if attempt < max_attempts:
                        sleep_for = self._history_retry_sleep_seconds(
                            attempt,
                            backoff_factor=float(backoff_factor or 0.0),
                            retry_after=e.response.headers.get("Retry-After") if e.response is not None else None,
                        )
                        self._logger.warning(
                            f"Barchart EOD - HTTP {last_status_code} for {symbol} on attempt {attempt}/{max_attempts}. "
                            f"Sleeping {sleep_for:.2f}s"
                        )
                        await asyncio.sleep(sleep_for)
                        continue

                    self._last_history_status_by_symbol[str(symbol)] = {
                        "status_code": last_status_code,
                        "reason": "max_retries_exceeded",
                        "saw_429": saw_429,
                    }
                    self._logger.error(f"Barchart EOD - Max retries exceeded for {symbol}: {e}")
                    if uid:
                        return symbol, None, uid
                    return symbol, None

                except Exception as e:
                    last_status_code = None
                    if attempt < max_attempts:
                        sleep_for = self._history_retry_sleep_seconds(
                            attempt,
                            backoff_factor=float(backoff_factor or 0.0),
                        )
                        self._logger.warning(
                            f"Barchart EOD - Error for {symbol} on attempt {attempt}/{max_attempts}: {e}. "
                            f"Sleeping {sleep_for:.2f}s"
                        )
                        await asyncio.sleep(sleep_for)
                        continue

                    self._last_history_status_by_symbol[str(symbol)] = {
                        "status_code": last_status_code,
                        "reason": "max_retries_exceeded",
                        "saw_429": saw_429,
                    }
                    self._logger.error(f"Barchart EOD - Max retries exceeded for {symbol}: {e}")
                    if uid:
                        return symbol, None, uid
                    return symbol, None

            self._last_history_status_by_symbol[str(symbol)] = {
                "status_code": last_status_code,
                "reason": "max_retries_exceeded",
                "saw_429": saw_429,
            }
            if uid:
                return symbol, None, uid
            return symbol, None

        except Exception as e:
            self._last_history_status_by_symbol.setdefault(
                str(symbol),
                {
                    "status_code": None,
                    "reason": "exception",
                    "saw_429": saw_429,
                },
            )
            self._logger.error(e)
            if uid:
                return symbol, None, uid
            return symbol, None

    async def _fetch_intraday_timeseries_with_semaphore(self, semaphore, *args, **kwargs):
        await asyncio.sleep(0.2)
        async with semaphore:
            return await self._fetch_intraday_timeseries(*args, **kwargs)

    async def _fetch_eod_timeseries_with_semaphore(self, semaphore, *args, **kwargs):
        async with semaphore:
            return await self._fetch_eod_timeseries(*args, **kwargs)

    def barchart_timeseries_api(
        self,
        barchart_symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]] = None,
        max_concurrent_tasks: Optional[int] = 8,
        max_keepalive_connections: Optional[int] = 8,
        max_requests_per_second: Optional[int] = 6,
        one_df: Optional[bool] = False,
        show_tqdm: Optional[bool] = True,
        merge_val_col: Optional[Literal["Open", "High", "Low", "Close", "Volume", "Open Interest"]] = "Close",
        eod_server_side_dates: bool = False,
        eod_max_retries: Optional[int] = None,
        eod_backoff_factor: Optional[float] = None,
    ):
        barchart_symbols = [self._normalize_barchart_symbol(s) for s in barchart_symbols]
        effective_max_concurrent = max(1, int(max_concurrent_tasks or 1))
        effective_max_keepalive = max(1, int(max_keepalive_connections or effective_max_concurrent))
        # Optional per-call overrides for the EOD retry budget. Fan-out workers pass small
        # values so a degraded proxy fails fast and its batch is re-stolen by a healthy worker
        # instead of grinding through the full 5-attempt exponential backoff.
        eod_retry_kwargs: Dict[str, object] = {}
        if eod_max_retries is not None:
            eod_retry_kwargs["max_retries"] = int(eod_max_retries)
        if eod_backoff_factor is not None:
            eod_retry_kwargs["backoff_factor"] = float(eod_backoff_factor)

        async def build_eod_tasks(
            client: httpx.AsyncClient,
            barchart_symbols: List[str],
            start_date: datetime,
            end_date: datetime,
            rate_limiter: Optional[AsyncRateLimiter],
        ):
            semaphore = asyncio.Semaphore(effective_max_concurrent)
            tasks = [
                self._fetch_eod_timeseries_with_semaphore(
                    semaphore=semaphore,
                    client=client,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    set_dt_index=not one_df,
                    rate_limiter=rate_limiter,
                    server_side_dates=eod_server_side_dates,
                    **eod_retry_kwargs,
                )
                for symbol in barchart_symbols
            ]
            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING EOD DATA FROM BARCHART...")
            return await asyncio.gather(*tasks)

        async def build_intraday_tasks(
            client: httpx.AsyncClient,
            barchart_symbols: List[str],
            start_date: datetime,
            end_date: datetime,
            interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]] = None,
        ):
            semaphore = asyncio.Semaphore(effective_max_concurrent)
            tasks = [
                self._fetch_intraday_timeseries_with_semaphore(
                    semaphore=semaphore,
                    client=client,
                    symbol=symbol,
                    interval=interval,
                    start_date=start_date,
                    end_date=end_date,
                    set_dt_index=not one_df,
                )
                for symbol in barchart_symbols
            ]
            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING INTRADAY DATA FROM BARCHART...")
            return await asyncio.gather(*tasks)

        async def run_fetch_all(
            barchart_symbols: List[str],
            start_date: datetime,
            end_date: datetime,
            interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]] = None,
        ):
            pool_size = effective_max_concurrent
            # Warm token slots for this proxy scope; requests still rotate per call.
            await asyncio.to_thread(self._get_shared_session_token_pool, pool_size, "BTC")
            rate_limiter = (
                AsyncRateLimiter(max_calls=max_requests_per_second, period=1.0)
                if max_requests_per_second is not None
                else None
            )

            limits = httpx.Limits(
                max_connections=effective_max_concurrent,
                max_keepalive_connections=effective_max_keepalive,
            )
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                verify=False,
                http2=True,
            ) as client:
                if interval:
                    all_data = await build_intraday_tasks(
                        client=client,
                        barchart_symbols=barchart_symbols,
                        start_date=start_date,
                        end_date=end_date,
                        interval=interval,
                    )
                else:
                    all_data = await build_eod_tasks(
                        client=client,
                        barchart_symbols=barchart_symbols,
                        start_date=start_date,
                        end_date=end_date,
                        rate_limiter=rate_limiter,
                    )
                return all_data

        dfs: List[Tuple[str, pd.DataFrame]] = asyncio.run(
            run_fetch_all(barchart_symbols=barchart_symbols, start_date=start_date, end_date=end_date, interval=interval)
        )

        if one_df:

            def merge_dfs_on_column(dfs_dict: Dict[str, pd.DataFrame], on_column: str, merge_val_col: str):
                dfs_dict = {key: df[[on_column, merge_val_col]].rename(columns={merge_val_col: key}) for key, df in dfs_dict.items() if df is not None}
                if not dfs_dict:
                    return pd.DataFrame(columns=[on_column])
                merged_df = reduce(lambda left, right: pd.merge(left, right, on=on_column, how="outer"), dfs_dict.values())
                merged_df.sort_values(by=on_column, inplace=True)
                return merged_df

            merged = merge_dfs_on_column(dict(dfs), "Date", merge_val_col)
            if len(merged.columns) - 2 == len(barchart_symbols):
                print(f"MISSING DATA! Expected #Cols {len(barchart_symbols)}, Got {len(merged.columns)}")
            df = merged.set_index("Date")
            return df[(df.index >= start_date) & (df.index <= end_date)]

        return dict(dfs)

    @staticmethod
    def _coerce_history_boundary(value: Optional[datetime | date | str]) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        token = str(value).strip()
        if not token:
            return None
        parsed = pd.to_datetime(token, errors="coerce")
        if pd.isna(parsed):
            raise ValueError(f"Invalid Barchart history boundary: {value!r}")
        if isinstance(parsed, pd.Timestamp):
            return parsed.to_pydatetime()
        return parsed

    @staticmethod
    def _normalize_history_dataframe(symbol: str, df: Optional[pd.DataFrame]) -> pd.DataFrame:
        columns = [
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "openinterest",
            "delta",
            "gamma",
            "theta",
            "vega",
            "impliedVolatility",
        ]
        if df is None or df.empty:
            empty = pd.DataFrame(columns=columns)
            empty.index.name = "date"
            return empty

        normalized = df.copy()
        if "Date" in normalized.columns:
            normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce")
            normalized = normalized.set_index("Date")
        if normalized.index.name is None:
            normalized.index.name = "Date"

        rename_map = {
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Open Interest": "openinterest",
            "Delta": "delta",
            "Gamma": "gamma",
            "Theta": "theta",
            "Vega": "vega",
            "Implied Volatility": "impliedVolatility",
            "ImpliedVolatility": "impliedVolatility",
            "symbol": "symbol",
            "Symbol": "symbol",
        }
        normalized = normalized.rename(columns=rename_map)

        if "symbol" not in normalized.columns:
            normalized["symbol"] = symbol
        else:
            normalized["symbol"] = normalized["symbol"].fillna(symbol)

        for column in columns:
            if column not in normalized.columns:
                normalized[column] = 0.0 if column not in {"symbol"} else symbol

        numeric_columns = [column for column in columns if column != "symbol"]
        for column in numeric_columns:
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

        normalized.index = pd.to_datetime(normalized.index, errors="coerce")
        normalized = normalized[~normalized.index.isna()].sort_index()
        normalized.index.name = "date"
        return normalized[columns]

    def fetch_futures_options_timeseries(
        self,
        *,
        start: datetime | date | str,
        end: datetime | date | str,
        symbols: List[str],
        max_concurrent_tasks: Optional[int] = 8,
        max_keepalive_connections: Optional[int] = 8,
        max_requests_per_second: Optional[int] = 6,
        show_tqdm: Optional[bool] = False,
    ) -> Dict[str, pd.DataFrame]:
        start_dt = self._coerce_history_boundary(start)
        end_dt = self._coerce_history_boundary(end)
        if start_dt is None or end_dt is None:
            raise ValueError("fetch_futures_options_timeseries requires start and end")
        if end_dt < start_dt:
            raise ValueError("fetch_futures_options_timeseries requires end >= start")
        self._last_history_status_by_symbol.clear()

        fetched = self.barchart_timeseries_api(
            barchart_symbols=symbols,
            start_date=start_dt,
            end_date=end_dt,
            interval=None,
            max_concurrent_tasks=max_concurrent_tasks,
            max_keepalive_connections=max_keepalive_connections,
            max_requests_per_second=max_requests_per_second,
            one_df=False,
            show_tqdm=show_tqdm,
        )
        return {
            str(symbol): self._normalize_history_dataframe(str(symbol), frame)
            for symbol, frame in fetched.items()
        }

    def get_historical_bid_offer_quotes(
        self,
        symbol: str,
        start: Optional[datetime | str] = None,
        end: Optional[datetime | str] = None,
        maxrecords: Optional[int] = None,
        order: Optional[Literal["asc", "desc"]] = "desc",
        sessionfilter: Optional[str] = None,
        exchange_id: Optional[bool] = False,
        participant_id: Optional[bool] = False,
        set_dt_index: Optional[bool] = True,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
    ) -> pd.DataFrame:
        def _format_tick_dt(value: Optional[datetime | str]) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value.strftime("%Y%m%d%H%M%S")
            out = str(value).strip()
            return out or None

        def _looks_like_datetime_col(col: pd.Series) -> bool:
            parsed = pd.to_datetime(col, errors="coerce")
            return parsed.notna().sum() > 0

        def _assign_quote_columns(df: pd.DataFrame) -> pd.DataFrame:
            if df.empty:
                return df

            has_symbol_col = False
            if df.shape[1] >= 2:
                first_col_is_dt = _looks_like_datetime_col(df.iloc[:, 0])
                second_col_is_dt = _looks_like_datetime_col(df.iloc[:, 1])
                has_symbol_col = (not first_col_is_dt) and second_col_is_dt

            effective_cols = df.shape[1] - (1 if has_symbol_col else 0)
            if effective_cols == 7:
                quote_cols = ["DateTime", "TradingDay", "QuoteCondition", "BidPrice", "BidSize", "OfferPrice", "OfferSize"]
            elif effective_cols == 8:
                quote_cols = ["DateTime", "TradingDay", "ExchangeId", "QuoteCondition", "BidPrice", "BidSize", "OfferPrice", "OfferSize"]
            elif effective_cols == 9:
                quote_cols = [
                    "DateTime",
                    "TradingDay",
                    "QuoteCondition",
                    "BidPrice",
                    "BidSize",
                    "BidParticipantId",
                    "OfferPrice",
                    "OfferSize",
                    "OfferParticipantId",
                ]
            elif effective_cols == 10:
                quote_cols = [
                    "DateTime",
                    "TradingDay",
                    "ExchangeId",
                    "QuoteCondition",
                    "BidPrice",
                    "BidSize",
                    "BidParticipantId",
                    "OfferPrice",
                    "OfferSize",
                    "OfferParticipantId",
                ]
            else:
                quote_cols = [f"Column{i}" for i in range(effective_cols)]

            df.columns = (["Symbol"] if has_symbol_col else []) + quote_cols
            return df

        order_val = (order or "").lower()
        if order_val and order_val not in {"asc", "desc"}:
            raise ValueError("order must be either 'asc' or 'desc'.")

        args = {
            "symbol": symbol,
            "type": "Q",
        }
        if order_val:
            args["order"] = order_val
        start_val = _format_tick_dt(start)
        end_val = _format_tick_dt(end)
        if start_val:
            args["start"] = start_val
        if end_val:
            args["end"] = end_val
        if maxrecords is not None:
            args["maxrecords"] = int(maxrecords)
        if sessionfilter is not None:
            args["sessionfilter"] = sessionfilter
        if exchange_id:
            args["exchId"] = "true"
        if participant_id:
            args["participantID"] = "true"

        url = f"https://www.barchart.com/proxies/historical/queryticks.ashx?{urlencode(args)}"
        print(url)

        retries = 0
        while retries < max_retries:
            try:
                if retries > 0 or self._current_laravel_token is None or self._current_xsrf_token is None:
                    self._fetch_session_tokens(dummy_symbol=symbol)

                headers = {
                    "dnt": "1",
                    "referer": f"https://www.barchart.com/futures/quotes/{quote(symbol)}/interactive-chart",
                    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                    "cookie": self._token_cookie_header((self._current_laravel_token, self._current_xsrf_token)),
                    "x-xsrf-token": self._current_xsrf_token,
                }

                res = requests.get(url, headers=headers, proxies=self._proxies, timeout=self._global_timeout)
                res.raise_for_status()

                if not res.content:
                    return pd.DataFrame()

                df = self._parse_aspx_response_to_df(res.content)
                if df is None or df.empty:
                    return pd.DataFrame()

                df = _assign_quote_columns(df)

                if "DateTime" in df.columns:
                    df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
                    df = df.dropna(subset=["DateTime"])

                for col in ["TradingDay", "BidPrice", "BidSize", "OfferPrice", "OfferSize"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                if set_dt_index and "DateTime" in df.columns:
                    df = df.set_index("DateTime")
                    df = df.sort_index()

                return df

            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status == 404:
                    return pd.DataFrame()
                self._logger.error(f"Barchart historical quotes bad status for {symbol}: {status}")
            except pd.errors.EmptyDataError:
                return pd.DataFrame()
            except Exception as e:
                self._logger.error(f"Barchart historical quotes error for {symbol}: {e}")

            retries += 1
            if retries < max_retries:
                wait_time = backoff_factor * (2 ** (retries - 1))
                time.sleep(wait_time)

        raise ValueError(f"Barchart historical quotes - max retries exceeded for {symbol}")

    def get_option_quotes(
        self, symbols: List[str], max_concurrent_tasks: Optional[int] = 64, max_keepalive_connections: Optional[int] = 16, show_tqdm: Optional[bool] = True
    ) -> Dict[str, Dict[Annotated[str, "call or put"], pd.DataFrame]]:

        async def fetch_symbol(client: httpx.AsyncClient, symbol: str, session_token: Optional[Tuple[str, str]] = None):
            try:
                if session_token is None:
                    session_token = await asyncio.to_thread(self._get_shared_session_token, symbol, False)
                session_token = self._apply_session_token(session_token)
                fields_list = [
                    "strike",
                    "openPrice",
                    "highPrice",
                    "lowPrice",
                    "lastPrice",
                    "priceChange",
                    "bidPrice",
                    "askPrice",
                    "volume",
                    "openInterest",
                    "premium",
                    "tradeTime",
                    "longSymbol",
                    "optionType",
                    "symbol",
                    "symbolCode",
                    "symbolType",
                    "strikePrice",
                    "optionType",
                    "baseSymbol",
                    "optImpliedVolatility",
                    "delta",
                    "gamma",
                    "theta",
                    "vega",
                    "impliedVolatilitySkew",
                ]
                args = {
                    "symbol": f"{symbol}",
                    "list": "futures.options",
                    "fields": ",".join(fields_list),
                    "meta": "field.shortName,field.description,field.type,lists.lastUpdate",
                    "groupBy": "optionType",
                    "orderBy": "strike",
                    "orderDir": "asc",
                    "raw": "1",
                }
                url = f"https://www.barchart.com/proxies/core-api/v1/quotes/get?{urlencode(args)}"
                headers = {
                    "dnt": "1",
                    "referer": f"https://www.barchart.com/futures/quotes/{symbol}/options?futuresOptionsView=merged&moneyness=allRows&futuresOptionsTime=intraday",
                    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                    "cookie": self._token_cookie_header(session_token),
                    "x-xsrf-token": session_token[1],
                }
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                json_data = response.json()["data"]

                return symbol, {
                    "call": pd.DataFrame([opt["raw"] for opt in json_data["Call"]]),
                    "put": pd.DataFrame([opt["raw"] for opt in json_data["Put"]]),
                }

            except Exception as e:
                self._logger.error(f"Failed to fetch option quotes from Barchart for {symbol}: {e}")

        async def run_all(symbols: list):
            pool_size = max(1, int(max_concurrent_tasks or 1))
            await asyncio.to_thread(self._get_shared_session_token_pool, pool_size, "BTC")

            limits = httpx.Limits(max_connections=max_concurrent_tasks, max_keepalive_connections=max_keepalive_connections)
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                verify=False,
                http2=True,
            ) as client:
                tasks = [fetch_symbol(client, symbol) for symbol in symbols]
                if show_tqdm:
                    results = await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING OPTION QUOTES...")
                else:
                    results = await asyncio.gather(*tasks)
                out: Dict[str, Dict[str, pd.DataFrame]] = {}
                for item in results:
                    if not isinstance(item, tuple) or len(item) != 2:
                        continue
                    sym, payload = item
                    if sym is None or payload is None:
                        continue
                    out[str(sym)] = payload
                return out

        return asyncio.run(run_all(symbols))

    def get_single_option_quotes(self, symbol: str):
        fields_list = [
            "strike",
            "openPrice",
            "highPrice",
            "lowPrice",
            "lastPrice",
            "priceChange",
            "bidPrice",
            "askPrice",
            "volume",
            "openInterest",
            "premium",
            "tradeTime",
            "longSymbol",
            "optionType",
            "symbol",
            "symbolCode",
            "symbolType",
            "strikePrice",
            "optionType",
            "baseSymbol",
            "optImpliedVolatility",
            "delta",
            "gamma",
            "theta",
            "vega",
            "impliedVolatilitySkew",
        ]
        args = {
            "symbol": f"{symbol}",
            "list": "futures.options",
            "fields": ",".join(fields_list),
            "meta": "field.shortName,field.description,field.type,lists.lastUpdate",
            "groupBy": "optionType",
            "orderBy": "strike",
            "orderDir": "asc",
            "raw": "1",
        }
        url = f"https://www.barchart.com/proxies/core-api/v1/quotes/get?{urlencode(args)}"

        self._fetch_session_tokens()
        headers = {
            "dnt": "1",
            "referer": f"https://www.barchart.com/futures/quotes/{symbol}/options?futuresOptionsView=merged&moneyness=allRows&futuresOptionsTime=intraday",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "cookie": self._token_cookie_header((self._current_laravel_token, self._current_xsrf_token)),
            "x-xsrf-token": self._current_xsrf_token,
        }
        res = requests.get(url, headers=headers)
        return {
            "call": pd.DataFrame([opt["raw"] for opt in res.json()["data"]["Call"]]),
            "put": pd.DataFrame([opt["raw"] for opt in res.json()["data"]["Put"]]),
        }

