import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from urllib.parse import quote

import httpx
import pandas as pd
import pytz
import ujson as json
import sys


class BaseFetcher:
    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, Optional[str]]] = None,
        debug_verbose: bool = False,
        info_verbose: bool = False,
        warning_verbose: bool = False,
        error_verbose: bool = False,
    ):
        self._global_timeout = global_timeout
        self._proxies = proxies if proxies else {"http": None, "https": None}
        self._httpx_proxies = {
            "http://": httpx.AsyncHTTPTransport(proxy=self._proxies["http"]),
            "https://": httpx.AsyncHTTPTransport(proxy=self._proxies["https"]),
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


@dataclass
class WebullHeaders:
    search: Dict[str, str]
    trend: Dict[str, str]


class WebullFintechFetcher(BaseFetcher):

    SEARCH_URL = "https://quotes-gw.webullfintech.com/api/search/pc/tickers?brokerId=8&keyword={kw}&pageIndex=1&pageSize=1"
    TREND_URL = "https://quotes-gw.webullfintech.com/api/bonds/charts/trend?tickerIds={tid}&period={period}&count={count}&timestamp={ts}"
    FUTURES_URL = (
        "https://quotes-gw.webullfintech.com/api/futures/charts/query" "?type={bar_type}&count={count}&timestamp={ts}&restorationType={restoration}&tickerIds={tid}"
    )

    DEFAULT_HEADERS = WebullHeaders(
        search={
            "app": "global",
            "app-group": "broker",
            "appid": "wb_web_app",
            "device-type": "Web",
            "did": "r3hak6sv4n9gki9f74n22twnz2b27lly",
            "dnt": "1",
            "hl": "en",
            "os": "web",
            "osv": "i9zh",
            "ph": "Windows Chrome",
            "platform": "web",
            "referer": "https://app.webull.com/",
            "reqid": "iylkk7vr4u287ax0izrqvzhxb7igg_00",
            "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "t_time": "1761262351567",
            "tz": "America/Chicago",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
            "ver": "5.10.0",
            "x-s": "0fc8876ecfe8d29078bc928d5122de73def17eee232925b37f49637ed581bf7f",
            "x-sv": "xodp2vg9",
        },
        trend={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9",
            "cache-control": "max-age=0",
            "dnt": "1",
            "priority": "u=0, i",
            "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
            "sec-fetch-user": "?1",
            "upgrade-insecure-requests": "1",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
        },
    )

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, Optional[str]]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        warning_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
        cache_path: Optional[Union[str, Path]] = None,
        autosave_cache: bool = True,
    ):
        super().__init__(
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )

        self._cache_path = Path(cache_path).expanduser() if cache_path else self._default_cache_path()
        self._autosave_cache = autosave_cache
        self._cusip_cache: Dict[str, int] = {}
        self._cache_lock = asyncio.Lock()
        self._load_cusip_cache()

    @staticmethod
    def _require_tz(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError("start/end must be timezone-aware.")
        return dt

    @staticmethod
    def _build_search_url(keyword: str) -> str:
        return WebullFintechFetcher.SEARCH_URL.format(kw=quote(keyword))

    @staticmethod
    def _build_trend_url(ticker_id: Union[str, int], period: str, count: int, ts_epoch: int) -> str:
        return WebullFintechFetcher.TREND_URL.format(tid=str(ticker_id), period=period, count=count, ts=ts_epoch)

    @staticmethod
    def _build_futures_url(ticker_id: Union[str, int], *, bar_type: str, count: int, ts_epoch: int, restoration: int = 0) -> str:
        return WebullFintechFetcher.FUTURES_URL.format(bar_type=bar_type, count=int(count), ts=int(ts_epoch), restoration=int(restoration), tid=str(ticker_id))

    @staticmethod
    def _normalize_future_symbol(sym: str) -> str:
        """
        Normalize common BBG-style CBOT rates tickers to Globex roots, preserving any
        contract month/year suffix (e.g., 'TY'->'ZN', 'TYZ5'->'ZNZ5', 'FVH6'->'ZFH6').
        """
        s = (sym or "").strip().upper()
        if not s:
            return s

        # Split into alphabetic root and the remaining suffix (month/year, etc.)
        i = 0
        while i < len(s) and s[i].isalpha():
            i += 1
        root, suf = s[:i], s[i:]  # e.g., 'TY' + 'Z5'

        bbg_to_globex = {
            "TU": "ZT",  # 2Y Note
            "FV": "ZF",  # 5Y Note
            "TY": "ZN",  # 10Y Note
            "UXY": "TN",  # Ultra 10Y
            "US": "ZB",  # 30Y Bond
            "WN": "UB",  # Ultra Bond
        }

        to_return = bbg_to_globex.get(root, root) + suf
        return (
            to_return.replace("SFR", "SR3")
            .replace("SER", "SR1")
            .replace("FF", "ZQ")
            .replace("UXY", "TN")
            .replace("US", "ZB")
            .replace("ZT", "ZTMAIN")
            .replace("TU", "ZTMAIN")
            .replace("ZF", "ZFMAIN")
            .replace("FV", "ZFMAIN")
        )

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        method: Literal["GET", "POST"],
        url: str,
        headers: Optional[Dict[str, str]] = None,
        max_retries: int = 3,
        backoff_factor: int = 1,
    ) -> Optional[httpx.Response]:
        retries = 0
        last_exc: Optional[Exception] = None
        while retries <= max_retries:
            try:
                resp = await client.request(method, url, headers=headers)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                # 404/403 etc.: break early for some codes
                status = e.response.status_code if e.response else None
                if status in {401, 403, 404}:
                    self._logger.debug(f"HTTP {status} for {url}")
                    return None
                last_exc = e
            except Exception as e:
                last_exc = e

            retries += 1
            wait_time = backoff_factor * (2 ** (retries - 1))
            self._logger.debug(f"Retry {retries}/{max_retries} for {url} in {wait_time}s: {last_exc}")
            await asyncio.sleep(wait_time)
        return None

    def _default_cache_path(self) -> Path:
        try:
            if os.name == "nt":  # Windows
                base = os.getenv("LOCALAPPDATA")
                if not base:
                    base = Path.home() / "AppData" / "Local"
                return Path(base) / "WebullFintech" / "cusip_cache.json"
            elif sys.platform == "darwin":  # macOS
                return Path.home() / "Library" / "Caches" / "webull_fintech" / "cusip_cache.json"
            else:  # Linux / other
                base = os.getenv("XDG_CACHE_HOME")
                base = Path(base) if base else (Path.home() / ".cache")
                return base / "webull_fintech" / "cusip_cache.json"
        except Exception:
            # last-resort fallback
            return Path.home() / ".webull_cusip_cache.json"

    def _normalize_cusip(self, cusip: str) -> str:
        return cusip.strip().upper()

    def _load_cusip_cache(self) -> None:
        if not self._cache_path:
            return
        try:
            if self._cache_path.exists():
                with open(self._cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cusip_cache = {self._normalize_cusip(k): int(v) for k, v in data.items()}
        except Exception as e:
            self._logger.debug(f"Failed to load CUSIP cache: {e}")
            self._cusip_cache = {}

    def _save_cusip_cache(self) -> None:
        if not self._cache_path:
            return
        try:
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._cusip_cache, f, ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self._cache_path)  # atomic on Windows & POSIX
        except Exception as e:
            self._logger.debug(f"Failed to save CUSIP cache: {e}")

    async def _cache_get_ticker(self, cusip: str) -> Optional[int]:
        return self._cusip_cache.get(self._normalize_cusip(cusip))

    async def _cache_set_ticker(self, cusip: str, ticker_id: int) -> None:
        key = self._normalize_cusip(cusip)
        async with self._cache_lock:
            self._cusip_cache[key] = int(ticker_id)
            if self._autosave_cache:
                self._save_cusip_cache()

    # Optional public utilities
    def save_cusip_cache(self) -> None:
        self._save_cusip_cache()

    def clear_cusip_cache(self) -> None:
        self._cusip_cache.clear()
        if self._autosave_cache:
            self._save_cusip_cache()

    async def _get_ticker_id_from_cusip(
        self,
        client: httpx.AsyncClient,
        cusip: str,
        headers: WebullHeaders,
    ) -> Optional[int]:
        url = self._build_search_url(cusip)

        cached = await self._cache_get_ticker(cusip)
        if cached is not None:
            return cached

        # 2) fetch & cache
        resp = await self._request_with_retries(client, "GET", url, headers=headers.search)
        if not resp:
            return None
        try:
            data = resp.json().get("data", [])
            if not data:
                return None
            tid = int(pd.DataFrame(data)["tickerId"].iloc[-1])
            await self._cache_set_ticker(cusip, tid)
            return tid
        except Exception as e:
            self._logger.debug(f"Failed to parse search response for {cusip}: {e}")
            return None

    @staticmethod
    def _parse_value_list_to_df(value_list: List[str], value_col: str = "ytm") -> pd.DataFrame:
        # Webull returns strings like: "<epoch>,<value>"
        if not value_list:
            return pd.DataFrame(columns=["timestamp", value_col])
        parsed = []
        for s in value_list:
            try:
                ts_s = s.split(",")[0]
                val_s = s.split(",")[1]
                parsed.append({"timestamp": int(ts_s), value_col: float(val_s)})
            except Exception:
                continue
        if not parsed:
            return pd.DataFrame(columns=["timestamp", value_col])
        df = pd.DataFrame(parsed)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        return df

    async def _fetch_trend_slice(
        self,
        client: httpx.AsyncClient,
        ticker_id: Union[str, int],
        as_of_epoch: int,
        *,
        period: str = "d1",
        count: int = 500,
        headers: Optional[Dict[str, str]] = None,
        value_key: str = "yieldData",
        value_col: str = "ytm",
        max_retries: int = 3,
        backoff_factor: int = 1,
    ) -> Optional[pd.DataFrame]:
        url = self._build_trend_url(ticker_id, period, count, as_of_epoch)
        resp = await self._request_with_retries(client, "GET", url, headers=headers, max_retries=max_retries, backoff_factor=backoff_factor)
        if not resp:
            return None
        try:
            payload = resp.json()
            if not payload:
                return None
            # endpoint sometimes returns a list; sometimes object
            node = payload[0] if isinstance(payload, list) else payload
            if value_key not in node or not node[value_key]:
                return None

            return self._parse_value_list_to_df(node[value_key], value_col=value_col)
        except Exception as e:
            self._logger.debug(f"Failed to parse trend slice for {ticker_id}: {e}")
            return None

    async def _intraday_for_ticker(
        self,
        client: httpx.AsyncClient,
        ticker_id: Union[str, int],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        period: str,
        slice_count: int,
        headers: Dict[str, str],
        value_key: str,
        value_col: str,
        max_slices: int = 200,
        max_retries: int = 3,
        backoff_factor: int = 1,
    ) -> Optional[pd.DataFrame]:
        start = self._require_tz(start)
        end = self._require_tz(end)

        # Default to 'now' (UTC) if no end
        cursor_dt = end if end is not None else datetime.now(timezone.utc)
        if cursor_dt.tzinfo is None or cursor_dt.tzinfo.utcoffset(cursor_dt) is None:
            raise ValueError("end must be timezone-aware or None.")

        slices: List[pd.DataFrame] = []
        seen_earliest: Optional[pd.Timestamp] = None

        for _ in range(max_slices):
            df_slice = await self._fetch_trend_slice(
                client,
                ticker_id=ticker_id,
                as_of_epoch=int(cursor_dt.timestamp()),
                period=period,
                count=int(min(max(slice_count, 1), 500)),
                headers=headers,
                value_key=value_key,
                value_col=value_col,
                max_retries=max_retries,
                backoff_factor=backoff_factor,
            )
            if df_slice is None or df_slice.empty:
                break

            # Keep only rows <= end if provided
            if end is not None:
                df_slice = df_slice[df_slice["timestamp"] <= end.astimezone(timezone.utc)]
            if df_slice.empty:
                break

            slices.append(df_slice)

            earliest = df_slice["timestamp"].min()
            # Stop if we crossed the start boundary
            if start is not None and earliest <= start.astimezone(timezone.utc):
                break

            # Detect no progress
            if seen_earliest is not None and earliest >= seen_earliest:
                break
            seen_earliest = earliest

            # Step back one minute earlier than earliest to avoid overlap
            cursor_dt = (earliest - pd.Timedelta(minutes=1)).to_pydatetime()
            cursor_dt = cursor_dt.replace(tzinfo=timezone.utc)

        if not slices:
            return None

        df = pd.concat(slices, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")

        # Final windowing
        if start is not None:
            df = df[df["timestamp"] >= start.astimezone(timezone.utc)]
        if end is not None:
            df = df[df["timestamp"] <= end.astimezone(timezone.utc)]

        df = df.set_index("timestamp")
        return df

    async def _resolve_ticker_ids_for_cusips(
        self,
        client: httpx.AsyncClient,
        cusips: List[str],
        headers: WebullHeaders,
        max_concurrent_tasks: int,
        show_tqdm: bool,
    ) -> Dict[str, Optional[int]]:
        sem = asyncio.Semaphore(max_concurrent_tasks)

        async def _task(cusip: str):
            await asyncio.sleep(0.05)
            async with sem:
                tid = await self._get_ticker_id_from_cusip(client, cusip, headers)
                return cusip, tid

        tasks = [_task(c) for c in cusips]
        if show_tqdm:
            import tqdm.asyncio

            pairs = await tqdm.asyncio.tqdm.gather(*tasks, desc="RESOLVING TICKER IDS...")
        else:
            pairs = await asyncio.gather(*tasks)
        return dict(pairs)

    async def _fetch_all_intraday(
        self,
        client: httpx.AsyncClient,
        ticker_by_key: Dict[str, Optional[int]],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        period: str,
        slice_count: int,
        headers_trend: Dict[str, str],
        value_key: str,
        value_col: str,
        max_concurrent_tasks: int,
        show_tqdm: bool,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        sem = asyncio.Semaphore(max_concurrent_tasks)

        async def _task(key: str, tid: Optional[int]):
            if tid is None:
                return key, None
            async with sem:
                df = await self._intraday_for_ticker(
                    client,
                    ticker_id=tid,
                    start=start,
                    end=end,
                    period=period,
                    slice_count=slice_count,
                    headers=headers_trend,
                    value_key=value_key,
                    value_col=value_col,
                )
                return key, df

        tasks = [_task(k, v) for k, v in ticker_by_key.items()]
        if show_tqdm:
            import tqdm.asyncio

            results = await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING WEBULL INTRADAY...")
        else:
            results = await asyncio.gather(*tasks)
        return dict(results)

    def intraday_by_cusips(
        self,
        cusips: List[str],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        period: str = "d1",
        slice_count: int = 500,
        value_key: str = "yieldData",
        value_col: str = "ytm",
        max_concurrent_tasks: int = 32,
        max_keepalive_connections: int = 32,
        merge_val_col: Optional[str] = None,
        show_tqdm: bool = False,
    ) -> Union[Dict[str, Optional[pd.DataFrame]], pd.DataFrame]:
        start_passed = start
        start = start - timedelta(days=3)

        headers = WebullFintechFetcher.DEFAULT_HEADERS
        limits = httpx.Limits(max_connections=max_concurrent_tasks, max_keepalive_connections=max_keepalive_connections)

        async def _run():
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                http2=True,
                verify=False,
            ) as client:
                # 1) resolve cusip -> tickerId concurrently
                ticker_by_cusip = await self._resolve_ticker_ids_for_cusips(
                    client, cusips=cusips, headers=headers, max_concurrent_tasks=max_concurrent_tasks, show_tqdm=show_tqdm
                )
                # 2) fetch each intraday series concurrently
                df_by_cusip = await self._fetch_all_intraday(
                    client,
                    ticker_by_key=ticker_by_cusip,
                    start=start,
                    end=end,
                    period=period,
                    slice_count=slice_count,
                    headers_trend=headers.trend,
                    value_key=value_key,
                    value_col=value_col,
                    max_concurrent_tasks=max_concurrent_tasks,
                    show_tqdm=show_tqdm,
                )
                return df_by_cusip

        results: Dict[str, Optional[pd.DataFrame]] = asyncio.run(_run())

        frames: Dict[str, pd.DataFrame] = {k: v for k, v in results.items() if isinstance(v, pd.DataFrame) and not v.empty}
        if not frames:
            return pd.DataFrame()

        def _merge(dfs_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
            cols = []
            for cusip, df in dfs_dict.items():
                colname = cusip
                value_name = merge_val_col or value_col
                cols.append(df.rename(columns={value_col: colname})[[cusip if cusip in df.columns else colname]])
            # The above attempted to rename; do a clean per-cusip selection/rename instead:
            cols = []
            for cusip, df in dfs_dict.items():
                value_name = merge_val_col or value_col
                series = df[value_name].rename(cusip)
                cols.append(series)
            merged = pd.concat(cols, axis=1)
            return merged.sort_index()

        ny = pytz.timezone("America/New_York")
        df = _merge(frames)
        df.index = df.index.tz_convert(ny)

        grid = pd.date_range(start=start, end=end, freq="1min", tz=ny)
        pos = grid.indexer_between_time(time(7, 00), time(17, 00))
        session_index = grid[pos]
        df = df.reindex(session_index).ffill().bfill()

        start_ny = ny.localize(start_passed) if start_passed.tzinfo is None else start_passed.astimezone(ny)
        end_ny = ny.localize(end) if end.tzinfo is None else end.astimezone(ny)
        return df.loc[(df.index >= start_ny) & (df.index <= end_ny)]

    def intraday_by_ticker_ids(
        self,
        ticker_ids: Dict[str, Union[str, int]],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        headers_trend: Dict[str, str],
        period: str = "d1",
        slice_count: int = 500,
        value_key: str = "yieldData",
        value_col: str = "ytm",
        max_concurrent_tasks: int = 64,
        max_keepalive_connections: int = 16,
        one_df: bool = False,
        merge_val_col: Optional[str] = None,
        show_tqdm: bool = False,
    ) -> Union[Dict[str, Optional[pd.DataFrame]], pd.DataFrame]:
        limits = httpx.Limits(max_connections=max_concurrent_tasks, max_keepalive_connections=max_keepalive_connections)

        async def _run():
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                http2=True,
                headers={"Connection": "close"},
                verify=False,
            ) as client:
                out = await self._fetch_all_intraday(
                    client,
                    ticker_by_key=ticker_ids,
                    start=start,
                    end=end,
                    period=period,
                    slice_count=slice_count,
                    headers_trend=headers_trend,
                    value_key=value_key,
                    value_col=value_col,
                    max_concurrent_tasks=max_concurrent_tasks,
                    show_tqdm=show_tqdm,
                )
                return out

        results: Dict[str, Optional[pd.DataFrame]] = asyncio.run(_run())
        if not one_df:
            return results

        frames: Dict[str, pd.DataFrame] = {k: v for k, v in results.items() if isinstance(v, pd.DataFrame) and not v.empty}
        if not frames:
            return pd.DataFrame()
        merged = pd.concat([df[value_col].rename(k) for k, df in frames.items()], axis=1)
        return merged.sort_index()

    async def _eod_for_ticker(
        self,
        client: httpx.AsyncClient,
        ticker_id: Union[str, int],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        period: str = "y1",
        count: int = 350,
        headers: Dict[str, str],
        value_key: str = "yieldData",
        value_col: str = "ytm",
        max_slices: int = 50,
        max_retries: int = 3,
        backoff_factor: int = 1,
    ) -> Optional[pd.DataFrame]:
        cursor_dt = pytz.timezone("America/New_York").localize(datetime(end.year, end.month, end.day, 17, 00))

        slices: List[pd.DataFrame] = []
        seen_earliest: Optional[pd.Timestamp] = None

        for _ in range(max_slices):
            df_slice = await self._fetch_trend_slice(
                client,
                ticker_id=ticker_id,
                as_of_epoch=int(cursor_dt.timestamp()),
                period=period,
                count=count,
                headers=headers,
                value_key=value_key,
                value_col=value_col,
                max_retries=max_retries,
                backoff_factor=backoff_factor,
            )
            if df_slice is None or df_slice.empty:
                break

            # Keep only rows <= end if provided
            if end is not None:
                df_slice = df_slice[df_slice["timestamp"].dt.date <= end]
            if df_slice.empty:
                break

            slices.append(df_slice)

            earliest = df_slice["timestamp"].min()
            # Stop if we crossed the start boundary
            if start is not None and earliest.date() <= start:
                break

            # Detect no progress
            if seen_earliest is not None and earliest >= seen_earliest:
                break
            seen_earliest = earliest

            # Move cursor back just before earliest to fetch prior years
            cursor_dt = (earliest - pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=timezone.utc)

        if not slices:
            return None

        df = pd.concat(slices, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")

        if start is not None:
            df = df[df["timestamp"].dt.date >= start]
        if end is not None:
            df = df[df["timestamp"].dt.date <= end]

        df["timestamp"] = df["timestamp"].dt.date
        return df.set_index("timestamp")

    async def _fetch_all_eod(
        self,
        client: httpx.AsyncClient,
        ticker_by_key: Dict[str, Optional[int]],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        period: str,
        count: int,
        headers_trend: Dict[str, str],
        value_key: str,
        value_col: str,
        max_concurrent_tasks: int,
        show_tqdm: bool,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        sem = asyncio.Semaphore(max_concurrent_tasks)

        async def _task(key: str, tid: Optional[int]):
            if tid is None:
                return key, None
            async with sem:
                df = await self._eod_for_ticker(
                    client,
                    ticker_id=tid,
                    start=start,
                    end=end,
                    period=period,
                    count=count,
                    headers=headers_trend,
                    value_key=value_key,
                    value_col=value_col,
                )
                return key, df

        tasks = [_task(k, v) for k, v in ticker_by_key.items()]
        if show_tqdm:
            import tqdm.asyncio

            results = await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING WEBULL EOD...")
        else:
            results = await asyncio.gather(*tasks)
        return dict(results)

    def eod_by_cusips(
        self,
        cusips: List[str],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        period: str = "y1",
        count: int = 350,
        value_key: str = "yieldData",
        value_col: str = "ytm",
        max_concurrent_tasks: int = 64,
        max_keepalive_connections: int = 16,
        one_df: bool = True,
        merge_val_col: Optional[str] = None,
        show_tqdm: bool = True,
    ) -> Union[Dict[str, Optional[pd.DataFrame]], pd.DataFrame]:
        headers = WebullFintechFetcher.DEFAULT_HEADERS
        limits = httpx.Limits(max_connections=max_concurrent_tasks, max_keepalive_connections=max_keepalive_connections)

        async def _run():
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                http2=True,
                verify=False,
            ) as client:
                ticker_by_cusip = await self._resolve_ticker_ids_for_cusips(
                    client, cusips=cusips, headers=headers, max_concurrent_tasks=max_concurrent_tasks, show_tqdm=show_tqdm
                )
                df_by_cusip = await self._fetch_all_eod(
                    client,
                    ticker_by_key=ticker_by_cusip,
                    start=start,
                    end=end,
                    period=period,
                    count=count,
                    headers_trend=headers.trend,
                    value_key=value_key,
                    value_col=value_col,
                    max_concurrent_tasks=max_concurrent_tasks,
                    show_tqdm=show_tqdm,
                )
                return df_by_cusip

        results: Dict[str, Optional[pd.DataFrame]] = asyncio.run(_run())
        if not one_df:
            return results

        frames: Dict[str, pd.DataFrame] = {k: v for k, v in results.items() if isinstance(v, pd.DataFrame) and not v.empty}
        if not frames:
            return pd.DataFrame()
        merged = pd.concat([(df[(merge_val_col or value_col)]).rename(k) for k, df in frames.items()], axis=1)
        return merged.sort_index()

    async def _get_ticker_id_from_symbol(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        headers: WebullHeaders,
    ) -> Optional[int]:
        """
        Resolve a futures symbol (BBG or Globex root) to Webull tickerId via SEARCH_URL.
        Tries normalized-to-Globex then the raw input.
        """
        for key in (self._normalize_future_symbol(symbol), symbol.strip().upper()):
            url = self._build_search_url(key)
            resp = await self._request_with_retries(client, "GET", url, headers=headers.search)
            if not resp:
                continue
            try:
                data = resp.json().get("data", []) or []
                if not data:
                    continue
                # Prefer entries whose symbol/root match our query if possible
                df = pd.DataFrame(data)
                # Heuristic: pick last item (Webull often appends the best match last), but
                # if we have an exact case-insensitive symbol match, prefer it.
                tid = None
                if "symbol" in df.columns:
                    exact = df[df["symbol"].astype(str).str.casefold() == key.casefold()]
                    if not exact.empty:
                        tid = int(exact["tickerId"].iloc[-1])
                if tid is None:
                    tid = int(df["tickerId"].iloc[-1])
                return tid
            except Exception:
                continue
        return None

    async def _resolve_ticker_ids_for_symbols(
        self,
        client: httpx.AsyncClient,
        symbols: List[str],
        headers: WebullHeaders,
        max_concurrent_tasks: int,
        show_tqdm: bool,
    ) -> Dict[str, Optional[int]]:
        sem = asyncio.Semaphore(max_concurrent_tasks)

        async def _task(sym: str):
            await asyncio.sleep(0.05)
            async with sem:
                tid = await self._get_ticker_id_from_symbol(client, sym, headers)
                return sym, tid

        tasks = [_task(s) for s in symbols]
        if show_tqdm:
            import tqdm.asyncio

            pairs = await tqdm.asyncio.tqdm.gather(*tasks, desc="RESOLVING FUTURES TICKER IDS...")
        else:
            pairs = await asyncio.gather(*tasks)
        return dict(pairs)

    async def _fetch_all_intraday_futures(
        self,
        client: httpx.AsyncClient,
        ticker_by_key: Dict[str, Optional[int]],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        bar_type: str,
        slice_count: int,
        headers_trend: Dict[str, str],
        value_col: str,
        max_concurrent_tasks: int,
        show_tqdm: bool,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        sem = asyncio.Semaphore(max_concurrent_tasks)

        async def _task(key: str, tid: Optional[int]):
            if tid is None:
                return key, None
            async with sem:
                df = await self._intraday_futures_for_ticker(
                    client,
                    ticker_id=tid,
                    start=start,
                    end=end,
                    bar_type=bar_type,
                    slice_count=slice_count,
                    headers=headers_trend,
                    value_col=value_col,
                )
                return key, df

        tasks = [_task(k, v) for k, v in ticker_by_key.items()]
        if show_tqdm:
            import tqdm.asyncio

            results = await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING FUTURES INTRADAY...")
        else:
            results = await asyncio.gather(*tasks)
        return dict(results)

    @staticmethod
    def _parse_futures_payload_to_df(payload: Any, value_col: str = "last") -> pd.DataFrame:
        """
        Webull futures charts may come back in a few shapes. We try, in order:
        - node["data"] as list[str] like "epoch,open,high,low,close,volume,oi"
        - node["klineList"] as list[str] with the same shape
        - node with arrays 't' (timestamps) and 'c' (closes)
        - node["candles"] as list[dict] with 'time'/'close'
        Returns DataFrame with columns: timestamp (UTC) and <value_col> (close/last).
        """
        node = payload[0] if isinstance(payload, list) and payload else payload
        if not node:
            return pd.DataFrame(columns=["timestamp", value_col])

        def _from_string_list(lst: List[str]) -> pd.DataFrame:
            rows = []
            for s in lst or []:
                try:
                    parts = s.split(",")
                    ts = int(parts[0])
                    # Prefer close as value
                    if len(parts) >= 5:
                        close = float(parts[4])
                    elif len(parts) >= 2:
                        close = float(parts[1])
                    else:
                        continue
                    rows.append({"timestamp": ts, value_col: close})
                except Exception:
                    continue
            if not rows:
                return pd.DataFrame(columns=["timestamp", value_col])
            df = pd.DataFrame(rows)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
            return df

        # 1) "data" key with list[str]
        if isinstance(node.get("data", None), list) and node["data"] and isinstance(node["data"][0], str):
            return _from_string_list(node["data"])

        # 2) "klineList" key with list[str]
        if isinstance(node.get("klineList", None), list) and node["klineList"] and isinstance(node["klineList"][0], str):
            return _from_string_list(node["klineList"])

        # 3) separate arrays 't' and 'c'
        if all(k in node for k in ("t", "c")) and isinstance(node["t"], list) and isinstance(node["c"], list):
            try:
                ts = pd.to_datetime(pd.Series(node["t"]).astype("int64"), unit="s", utc=True)
                cl = pd.Series(node["c"]).astype(float)
                df = pd.DataFrame({"timestamp": ts, value_col: cl})
                return df
            except Exception:
                pass

        # 4) "candles": list of dicts
        if isinstance(node.get("candles", None), list) and node["candles"]:
            rows = []
            for c in node["candles"]:
                try:
                    ts = int(c.get("time")) if "time" in c else None
                    close = float(c.get("close")) if "close" in c else None
                    if ts is None or close is None:
                        continue
                    rows.append({"timestamp": ts, value_col: close})
                except Exception:
                    continue
            if rows:
                df = pd.DataFrame(rows)
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
                return df

        return pd.DataFrame(columns=["timestamp", value_col])

    async def _fetch_futures_slice(
        self,
        client: httpx.AsyncClient,
        ticker_id: Union[str, int],
        as_of_epoch: int,
        *,
        bar_type: str = "m1",
        count: int = 800,
        headers: Optional[Dict[str, str]] = None,
        value_col: str = "last",
        max_retries: int = 3,
        backoff_factor: int = 1,
    ) -> Optional[pd.DataFrame]:
        url = self._build_futures_url(ticker_id, bar_type=bar_type, count=count, ts_epoch=as_of_epoch, restoration=0)
        resp = await self._request_with_retries(client, "GET", url, headers=headers, max_retries=max_retries, backoff_factor=backoff_factor)
        if not resp:
            return None
        try:
            payload = resp.json()
            df = self._parse_futures_payload_to_df(payload, value_col=value_col)
            if df is None or df.empty:
                return None
            return df
        except Exception:
            return None

    async def _intraday_futures_for_ticker(
        self,
        client: httpx.AsyncClient,
        ticker_id: Union[str, int],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        bar_type: str,
        slice_count: int,
        headers: Dict[str, str],
        value_col: str,
        max_slices: int = 200,
        max_retries: int = 3,
        backoff_factor: int = 1,
    ) -> Optional[pd.DataFrame]:
        start = self._require_tz(start)
        end = self._require_tz(end)
        cursor_dt = end if end is not None else datetime.now(timezone.utc)
        if cursor_dt.tzinfo is None or cursor_dt.tzinfo.utcoffset(cursor_dt) is None:
            raise ValueError("end must be timezone-aware or None.")

        slices: List[pd.DataFrame] = []
        seen_earliest: Optional[pd.Timestamp] = None

        for _ in range(max_slices):
            df_slice = await self._fetch_futures_slice(
                client,
                ticker_id=ticker_id,
                as_of_epoch=int(cursor_dt.timestamp()),
                bar_type=bar_type,
                count=int(min(max(slice_count, 1), 800)),
                headers=headers,
                value_col=value_col,
                max_retries=max_retries,
                backoff_factor=backoff_factor,
            )
            if df_slice is None or df_slice.empty:
                break

            # Keep only rows <= end if provided
            if end is not None:
                df_slice = df_slice[df_slice["timestamp"] <= end.astimezone(timezone.utc)]
            if df_slice.empty:
                break

            slices.append(df_slice)

            earliest = df_slice["timestamp"].min()
            if start is not None and earliest <= start.astimezone(timezone.utc):
                break

            if seen_earliest is not None and earliest >= seen_earliest:
                break
            seen_earliest = earliest

            cursor_dt = (earliest - pd.Timedelta(minutes=1)).to_pydatetime().replace(tzinfo=timezone.utc)

        if not slices:
            return None

        df = pd.concat(slices, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
        if start is not None:
            df = df[df["timestamp"] >= start.astimezone(timezone.utc)]
        if end is not None:
            df = df[df["timestamp"] <= end.astimezone(timezone.utc)]
        return df.set_index("timestamp")

    def intraday_by_tickers(
        self,
        tickers: List[str],
        start: datetime,
        end: datetime,
        *,
        bar_type: str = "m1",
        slice_count: int = 800,
        value_col: str = "last",
        max_concurrent_tasks: int = 32,
        max_keepalive_connections: int = 32,
        show_tqdm: bool = True,
    ) -> pd.DataFrame:
        if start is None or end is None:
            raise ValueError("start and end are required (timezone-aware datetimes).")
        start_passed = start
        start = start - timedelta(days=3)

        headers = WebullFintechFetcher.DEFAULT_HEADERS
        limits = httpx.Limits(max_connections=max_concurrent_tasks, max_keepalive_connections=max_keepalive_connections)

        async def _run():
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                http2=True,
                verify=False,
            ) as client:
                ticker_by_sym = await self._resolve_ticker_ids_for_symbols(
                    client, symbols=tickers, headers=headers, max_concurrent_tasks=max_concurrent_tasks, show_tqdm=show_tqdm
                )
                df_by_sym = await self._fetch_all_intraday_futures(
                    client,
                    ticker_by_key=ticker_by_sym,
                    start=start,
                    end=end,
                    bar_type=bar_type,
                    slice_count=slice_count,
                    headers_trend=headers.trend,
                    value_col=value_col,
                    max_concurrent_tasks=max_concurrent_tasks,
                    show_tqdm=show_tqdm,
                )
                return df_by_sym

        results: Dict[str, Optional[pd.DataFrame]] = asyncio.run(_run())
        frames = {k: v for k, v in results.items() if isinstance(v, pd.DataFrame) and not v.empty}
        if not frames:
            return pd.DataFrame()

        # Merge and regularize to NY session 07:00–17:00 (mirrors intraday_by_cusips)
        merged = pd.concat([df[value_col].rename(k) for k, df in frames.items()], axis=1).sort_index()
        chi = pytz.timezone("America/Chicago")
        merged.index = merged.index.tz_convert(chi)

        grid = pd.date_range(start=start, end=end, freq="1min", tz=chi)
        pos = grid.indexer_between_time(start.time(), end.time())
        session_index = grid[pos]
        merged = merged.reindex(session_index).ffill().bfill()

        start_chi = chi.localize(start_passed) if start_passed.tzinfo is None else start_passed.astimezone(chi)
        end_chi = chi.localize(end) if end.tzinfo is None else end.astimezone(chi)
        return merged.loc[(merged.index >= start_chi) & (merged.index <= end_chi)]

    async def _eod_futures_for_ticker(
        self,
        client: httpx.AsyncClient,
        ticker_id: Union[str, int],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        bar_type: str = "d1",
        count: int = 800,
        headers: Dict[str, str],
        value_col: str = "last",
        max_slices: int = 50,
        max_retries: int = 3,
        backoff_factor: int = 1,
    ) -> Optional[pd.DataFrame]:
        # Coerce start/end to dates for daily slicing
        start_date = start.date() if isinstance(start, datetime) else start
        end_date = end.date() if isinstance(end, datetime) else end

        # Cursor anchor: 17:00 America/Chicago on 'end' if provided, else now()
        chi = pytz.timezone("America/Chicago")
        if end_date is None:
            cursor_dt = datetime.now(chi)
        else:
            cursor_dt = chi.localize(datetime(end_date.year, end_date.month, end_date.day, 17, 0))

        slices: List[pd.DataFrame] = []
        seen_earliest: Optional[pd.Timestamp] = None

        for _ in range(max_slices):
            df_slice = await self._fetch_futures_slice(
                client,
                ticker_id=ticker_id,
                as_of_epoch=int(cursor_dt.timestamp()),
                bar_type=bar_type,  # 'd1' by default
                count=int(min(max(count, 1), 800)),
                headers=headers,
                value_col=value_col,
                max_retries=max_retries,
                backoff_factor=backoff_factor,
            )
            if df_slice is None or df_slice.empty:
                break

            # Restrict to <= end_date (if provided)
            if end_date is not None:
                df_slice = df_slice[df_slice["timestamp"].dt.date <= end_date]
            if df_slice.empty:
                break

            slices.append(df_slice)

            earliest = df_slice["timestamp"].min()
            # Stop if we crossed the start boundary (if provided)
            if start_date is not None and earliest.date() <= start_date:
                break

            # No progress safeguard
            if seen_earliest is not None and earliest >= seen_earliest:
                break
            seen_earliest = earliest

            # Step back one day before the earliest bar we have so far
            cursor_dt = (earliest - pd.Timedelta(days=1)).to_pydatetime().replace(tzinfo=timezone.utc)

        if not slices:
            return None

        df = pd.concat(slices, ignore_index=True)
        df = df.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")

        if start_date is not None:
            df = df[df["timestamp"].dt.date >= start_date]
        if end_date is not None:
            df = df[df["timestamp"].dt.date <= end_date]

        df["timestamp"] = df["timestamp"].dt.date
        df = df.set_index("timestamp")
        return df.rename(columns={value_col: value_col})

    async def _fetch_all_eod_futures(
        self,
        client: httpx.AsyncClient,
        ticker_by_key: Dict[str, Optional[int]],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        bar_type: str,
        count: int,
        headers_trend: Dict[str, str],
        value_col: str,
        max_concurrent_tasks: int,
        show_tqdm: bool,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        sem = asyncio.Semaphore(max_concurrent_tasks)

        async def _task(key: str, tid: Optional[int]):
            if tid is None:
                return key, None
            async with sem:
                df = await self._eod_futures_for_ticker(
                    client,
                    ticker_id=tid,
                    start=start,
                    end=end,
                    bar_type=bar_type,
                    count=count,
                    headers=headers_trend,
                    value_col=value_col,
                )
                return key, df

        tasks = [_task(k, v) for k, v in ticker_by_key.items()]
        if show_tqdm:
            import tqdm.asyncio

            results = await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING FUTURES EOD...")
        else:
            results = await asyncio.gather(*tasks)
        return dict(results)

    def eod_by_tickers(
        self,
        tickers: List[str],
        start: Optional[datetime],
        end: Optional[datetime],
        *,
        bar_type: str = "d1",
        count: int = 800,
        value_col: str = "last",
        max_concurrent_tasks: int = 32,
        max_keepalive_connections: int = 32,
        one_df: bool = True,
        show_tqdm: bool = True,
    ) -> Union[Dict[str, Optional[pd.DataFrame]], pd.DataFrame]:
        headers = WebullFintechFetcher.DEFAULT_HEADERS
        limits = httpx.Limits(max_connections=max_concurrent_tasks, max_keepalive_connections=max_keepalive_connections)

        async def _run():
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                http2=True,
                verify=False,
            ) as client:
                ticker_by_sym = await self._resolve_ticker_ids_for_symbols(
                    client, symbols=tickers, headers=headers, max_concurrent_tasks=max_concurrent_tasks, show_tqdm=show_tqdm
                )
                df_by_sym = await self._fetch_all_eod_futures(
                    client,
                    ticker_by_key=ticker_by_sym,
                    start=start,
                    end=end,
                    bar_type=bar_type,
                    count=count,
                    headers_trend=headers.trend,
                    value_col=value_col,
                    max_concurrent_tasks=max_concurrent_tasks,
                    show_tqdm=show_tqdm,
                )
                return df_by_sym

        results: Dict[str, Optional[pd.DataFrame]] = asyncio.run(_run())
        if not one_df:
            return results

        frames: Dict[str, pd.DataFrame] = {k: v for k, v in results.items() if isinstance(v, pd.DataFrame) and not v.empty}
        if not frames:
            return pd.DataFrame()

        # Merge on daily date index
        merged = pd.concat(
            [(df[value_col] if value_col in df.columns else df.iloc[:, 0]).rename(sym) for sym, df in frames.items()],
            axis=1,
        )
        return merged.sort_index()
