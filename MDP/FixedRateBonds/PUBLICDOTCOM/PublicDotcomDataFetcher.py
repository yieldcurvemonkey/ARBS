import asyncio
import logging
import warnings
from datetime import datetime
from typing import Dict, List, Literal, Optional, Tuple

import httpx
import polars as pl
import requests

warnings.filterwarnings("ignore", category=FutureWarning)  # polars equivalent
warnings.simplefilter(action="ignore", category=FutureWarning)

import sys

if sys.platform == "win32":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)


class DataFetcherBase:
    _global_timeout: int = 10
    _proxies: Dict[str, str] = {"http": None, "https": None}
    _httpx_proxies: Dict[str, str] = {"http://": None, "https://": None}

    _logger = logging.getLogger(__name__)
    _debug_verbose: bool = False
    _error_verbose: bool = False
    _info_verbose: bool = False

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
    ):
        self._global_timeout = global_timeout
        self._proxies = proxies if proxies else {"http": None, "https": None}
        self._httpx_proxies["http://"] = self._proxies["http"]
        self._httpx_proxies["https://"] = self._proxies["https"]

        self._debug_verbose = debug_verbose
        self._error_verbose = error_verbose
        self._info_verbose = info_verbose
        self._no_logs_plz = not debug_verbose and not error_verbose and not info_verbose

        self._setup_logger()

    def _setup_logger(self):
        if not self._logger.hasHandlers():
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
            self._logger.addHandler(handler)

        if self._debug_verbose:
            self._logger.setLevel(logging.DEBUG)
        elif self._info_verbose:
            self._logger.setLevel(logging.INFO)
        elif self._error_verbose:
            self._logger.setLevel(logging.ERROR)
        else:
            self._logger.setLevel(logging.WARNING)

        if self._debug_verbose or self._info_verbose or self._error_verbose:
            self._logger.setLevel(logging.DEBUG)

        if self._no_logs_plz:
            self._logger.disabled = True
            self._logger.propagate = False


class PublicDotcomDataFetcher(DataFetcherBase):
    _public_dotcom_jwt: str = None

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
    ):
        super().__init__(
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            error_verbose=error_verbose,
        )

        self._public_dotcom_jwt = self._fetch_public_dotcome_jwt()

    def _fetch_public_dotcome_jwt(self) -> str:
        jwt_url = "https://prod-api.154310543964.hellopublic.com/static/anonymoususer/credentials.json"
        jwt_res = requests.get(jwt_url)
        jwt_res.raise_for_status()
        jwt_str = jwt_res.json()["jwt"]
        return jwt_str

    async def _fetch_cusip_timeseries_public_dotcom(
        self,
        client: httpx.AsyncClient,
        cusip: str,
        jwt_str: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
        uid: Optional[str | int] = None,
        span: Optional[Literal["MAX", "1Y", "6M", "3M", "1M"]] = "MAX",
    ):
        cols_to_return = ["Date", "Price", "YTM"]  # YTW is same as YTM for cash USTs
        retries = 0
        try:
            if cusip is None or not cusip:
                raise ValueError(f"Public.com - invalid CUSIP passed")

            while retries < max_retries:
                try:
                    data_headers = {
                        "authority": "prod-api.154310543964.hellopublic.com",
                        "method": "GET",
                        "path": f"/fixedincomegateway/v1/graph/data?cusip={cusip}&span={span}",
                        "scheme": "https",
                        "accept": "*/*",
                        "accept-encoding": "gzip, deflate, br, zstd",
                        "accept-language": "en-US,en;q=0.9",
                        "cache-control": "no-cache",
                        "content-type": "application/json",
                        "dnt": "1",
                        "origin": "https://public.com",
                        "pragma": "no-cache",
                        "priority": "u=1, i",
                        "sec-ch-ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                        "sec-ch-ua-mobile": "?0",
                        "sec-ch-ua-platform": '"Windows"',
                        "sec-fetch-dest": "empty",
                        "sec-fetch-mode": "cors",
                        "sec-fetch-site": "cross-site",
                        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                        "x-app-version": "web-1.0.9",
                        "authorization": jwt_str,
                    }

                    data_url = f"https://prod-api.154310543964.hellopublic.com/fixedincomegateway/v1/graph/data?cusip={cusip}&span={span}"
                    response = await client.get(data_url, headers=data_headers)
                    response.raise_for_status()
                    df = pl.DataFrame(response.json()["data"])
                    df = df.with_columns(
                        [
                            pl.col("timestamp").str.to_datetime(strict=False).alias("Date"),
                            (pl.col("unitPrice").cast(pl.Float64) * 100).alias("Price"),
                            (pl.col("yieldToWorst").cast(pl.Float64) * 100).alias("YTM"),
                        ]
                    ).select(cols_to_return)
                    if start_date:
                        df = df.filter(pl.col("Date").cast(pl.Date) >= start_date.date())
                    if end_date:
                        df = df.filter(pl.col("Date").cast(pl.Date) <= end_date.date())
                    if uid:
                        return cusip, df, uid
                    return cusip, df

                except httpx.HTTPStatusError as e:
                    self._logger.error(f"Public.com - Bad Status for {cusip}: {response.status_code}")
                    if (
                        response.status_code == 404 or response.status_code == 400
                    ):  # public.com endpoint doesnt throw a 404 specifically
                        if uid:
                            return cusip, pl.DataFrame(schema={col: pl.Utf8 for col in cols_to_return}), uid
                        return cusip, pl.DataFrame(schema={col: pl.Utf8 for col in cols_to_return})

                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(
                        f"Public.com - Throttled for {cusip}. Waiting for {wait_time} seconds before retrying..."
                    )
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    self._logger.error(f"Public.com - Error: {str(e)}")
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(
                        f"Public.com - Throttled for {cusip}. Waiting for {wait_time} seconds before retrying..."
                    )
                    await asyncio.sleep(wait_time)

            raise ValueError(f"Public.com - Max retries exceeded for {cusip}")

        except Exception as e:
            self._logger.error(e)
            if uid:
                return cusip, pl.DataFrame(schema={col: pl.Utf8 for col in cols_to_return}), uid
            return cusip, pl.DataFrame(schema={col: pl.Utf8 for col in cols_to_return})

    async def _fetch_cusip_timeseries_public_dotcome_with_semaphore(self, semaphore, *args, **kwargs):
        async with semaphore:
            return await self._fetch_cusip_timeseries_public_dotcom(*args, **kwargs)

    def public_dotcom_timeseries_api(
        self,
        cusips: List[str],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        refresh_jwt: Optional[bool] = False,
        max_concurrent_tasks: int = 64,
    ):
        if refresh_jwt or not self._public_dotcom_jwt:
            self._public_dotcom_jwt = self._fetch_public_dotcome_jwt()
            if not self._public_dotcom_jwt:
                raise ValueError("Public.com JWT Request Failed")

        async def build_tasks(
            client: httpx.AsyncClient,
            cusips: List[str],
            start_date: datetime,
            end_date: datetime,
            jwt_str: str,
            span: str,
        ):
            semaphore = asyncio.Semaphore(max_concurrent_tasks)
            tasks = [
                self._fetch_cusip_timeseries_public_dotcome_with_semaphore(
                    semaphore=semaphore,
                    client=client,
                    cusip=cusip,
                    start_date=start_date,
                    end_date=end_date,
                    jwt_str=jwt_str,
                    max_retries=1,
                    span=span,
                )
                for cusip in cusips
            ]
            return await asyncio.gather(*tasks)

        async def run_fetch_all(cusips: List[str], start_date: datetime, end_date: datetime, jwt_str: str, span: str):
            async with httpx.AsyncClient(proxy=self._proxies["https"]) as client:
                all_data = await build_tasks(
                    client=client,
                    cusips=cusips,
                    start_date=start_date,
                    end_date=end_date,
                    jwt_str=jwt_str,
                    span=span,
                )
                return all_data

        dfs: List[Tuple[str, pl.DataFrame]] = asyncio.run(
            run_fetch_all(
                cusips=cusips,
                start_date=start_date,
                end_date=end_date,
                jwt_str=self._public_dotcom_jwt,
                span="MAX",
            )
        )
        return dict(dfs)
