import asyncio
import logging
import warnings
from datetime import datetime
from typing import Dict, List, Optional

import threading
import httpx
import pandas as pd
import tqdm
import tqdm.asyncio

from Caching.DiskCacheMixin import DiskCacheMixin

warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
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


class FedInvestDataFetcher(BaseFetcher, DiskCacheMixin):
    _FEDINVEST_CACHE = "_fedinvest_prices_cache"

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
    ):
        BaseFetcher.__init__(
            self,
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            error_verbose=error_verbose,
        )
        DiskCacheMixin.__init__(self)

        self._open_count = 0
        self._open_lock = threading.RLock()
        self._cache_ready = False

    def _ensure_cache(self):
        if self._cache_ready and hasattr(self, self._FEDINVEST_CACHE):
            return
        cache_path = DiskCacheMixin.default_cache_path("FedInvest_Prices_Cache")
        self.open_cache(
            cache_attr=self._FEDINVEST_CACHE,
            path=cache_path,
            encode=None,
            decode=None,
        )
        self._cache_ready = True

    def __open__(self):
        with self._open_lock:
            if self._open_count == 0:
                self._ensure_cache()
            self._open_count += 1
        return self  # enables `with fetcher as f:` or `with fetcher.__open__() as f:`

    def __close__(self, *, commit: bool = True):
        with self._open_lock:
            if self._open_count <= 0:
                return
            self._open_count -= 1
            if self._open_count == 0:
                try:
                    if commit:
                        # auto-committed (DiskCache)
                finally:
                    try:
                        self.close_cache()
                    finally:
                        self._cache_ready = False

    def __enter__(self):
        return self.__open__()

    def __exit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    async def __aenter__(self):
        return self.__open__()

    async def __aexit__(self, exc_type, exc, tb):
        self.__close__(commit=(exc_type is None))

    def __del__(self):
        try:
            self.__close__(commit=False)
        except Exception:
            pass

    async def _fetch_cusip_prices_fedinvest(
        self,
        client: httpx.AsyncClient,
        date: datetime,
        cusips: List[str],
        uid: Optional[int | str],
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
    ):
        payload = {
            "priceDate.month": date.month,
            "priceDate.day": date.day,
            "priceDate.year": date.year,
            "submit": "Show Prices",
        }
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            # "Content-Length": "100",
            "Content-Type": "application/x-www-form-urlencoded",
            "Dnt": "1",
            "Host": "savingsbonds.gov",
            "Origin": "https://savingsbonds.gov",
            "Referer": "https://savingsbonds.gov/GA-FI/FedInvest/selectSecurityPriceDate",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        }
        self._logger.debug(f"UST Prices - {date} Payload: {payload}")
        cols_to_return = ["cusip", "type", "coupon", "offer_price", "bid_price", "eod_price"]
        retries = 0
        try:
            while retries < max_retries:
                try:
                    url = "https://savingsbonds.gov/GA-FI/FedInvest/selectSecurityPriceDate"
                    response = await client.post(
                        url,
                        data=payload,
                        headers=headers,
                        follow_redirects=False,
                        timeout=self._global_timeout,
                    )
                    if response.is_redirect:
                        redirect_url = response.headers.get("Location")
                        self._logger.debug(f"UST Prices - {date} Redirecting to {redirect_url}")
                        response = await client.get(redirect_url, headers=headers)

                    response.raise_for_status()
                    tables = pd.read_html(response.content, header=0)
                    df = tables[0]
                    if cusips:
                        missing_cusips = [cusip for cusip in cusips if cusip not in df["CUSIP"].values]
                        if missing_cusips:
                            self._logger.warning(f"UST Prices Warning - The following CUSIPs are not found in the DataFrame: {missing_cusips}")
                    df = df[df["CUSIP"].isin(cusips)] if cusips else df
                    df.columns = df.columns.str.lower()
                    # df = df.query("`security type` not in ['TIPS', 'MARKET BASED FRN']")
                    df = df.rename(
                        columns={
                            "buy": "offer_price",
                            "security type": "type",
                            "rate": "coupon",
                            "sell": "bid_price",
                            "end of day": "eod_price",
                        }
                    )
                    df["coupon"] = df["coupon"].str.replace("%", "", regex=False).astype(float)

                    if uid:
                        return date, df[cols_to_return], uid
                    return date, df[cols_to_return]

                except httpx.HTTPStatusError as e:
                    self._logger.error(f"UST Prices - Bad Status for {date}: {response.status_code}")
                    if response.status_code == 404:
                        if uid:
                            return date, df[cols_to_return], uid
                        return date, df[cols_to_return]
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"UST Prices - Throttled. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    self._logger.error(f"UST Prices - Error for {date}: {e}")
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"UST Prices - Throttled. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

            raise ValueError(f"UST Prices - Max retries exceeded for {date}")
        except Exception as e:
            self._logger.error(e)
            if uid:
                return date, pd.DataFrame(columns=cols_to_return), uid
            return date, pd.DataFrame(columns=cols_to_return)

    async def _fetch_cusip_prices_fedinvest_with_semaphore(self, semaphore, *args, **kwargs):
        async with semaphore:
            return await self._fetch_cusip_prices_fedinvest(*args, **kwargs)

    async def _build_fetch_tasks_cusip_prices_fedinvest(
        self,
        client: httpx.AsyncClient,
        dates: List[datetime],
        cusips: Optional[List[str]] = None,
        uid: Optional[str | int] = None,
        max_concurrent_tasks: int = 64,
    ):
        semaphore = asyncio.Semaphore(max_concurrent_tasks)
        tasks = [
            self._fetch_cusip_prices_fedinvest_with_semaphore(
                semaphore,
                client=client,
                date=date,
                cusips=cusips,
                uid=uid,
            )
            for date in dates
        ]
        return tasks

    def runner(
        self,
        dates: List[datetime],
        show_tqdm: Optional[bool] = False,
        max_concurrent_tasks: Optional[int] = 1,
        max_connections: Optional[int] = 1,
        max_keepalive_connections: Optional[int] = 1,
        refresh_cache: Optional[bool] = False,
    ):

        async def build_tasks(client: httpx.AsyncClient, dates):
            tasks = await self._build_fetch_tasks_cusip_prices_fedinvest(
                client=client,
                dates=dates,
                max_concurrent_tasks=max_concurrent_tasks,
            )
            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING FEDINVEST HISTORICAL PRICES...")
            return await asyncio.gather(*tasks)

        async def run_fetch_all(dates):
            limits = httpx.Limits(max_connections=max_connections, max_keepalive_connections=max_keepalive_connections)
            async with httpx.AsyncClient(limits=limits, timeout=self._global_timeout, mounts=self._httpx_proxies, verify=False, http2=True) as client:
                all_data = await build_tasks(client=client, dates=dates)
                return all_data

        self._ensure_cache()
        cache = getattr(self, self._FEDINVEST_CACHE)

        if refresh_cache:
            dates_to_fetch = dates
        else:
            cached = {d.date() for d in cache.keys()}
            dates_to_fetch = [d for d in dates if d.date() not in cached]

        if not dates_to_fetch:
            return {dt: cache[pd.Timestamp(dt.date())] for dt in dates}

        fetched_dict = dict(asyncio.run(run_fetch_all(dates=dates_to_fetch)))
        for dt, df in fetched_dict.items():
            cache[pd.Timestamp(dt.date())] = df
        if fetched_dict:
            # auto-committed (DiskCache)

        out: Dict[datetime, pd.DataFrame] = {}
        for dt in dates:
            key = pd.Timestamp(dt.date())
            out[dt] = cache[key]

        self.close_cache()
        return out
