import asyncio
import logging
import warnings
from datetime import datetime, timezone
from functools import reduce
from typing import Dict, List, Literal, Optional, Tuple

import httpx
import numpy as np
import pandas as pd  # Keep for compatibility
import polars as pl
import pytz
import requests
import tqdm
import tqdm.asyncio
import ujson as json
from requests.models import PreparedRequest

warnings.simplefilter(action="ignore", category=FutureWarning)

import sys

if sys.platform == "win32":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)


def get_isin_from_cusip(cusip_str, country_code: str = "US"):
    isin_to_digest = country_code + cusip_str.upper()

    get_numerical_code = lambda c: str(ord(c) - 55)
    encode_letters = lambda c: c if c.isdigit() else get_numerical_code(c)
    to_digest = "".join(map(encode_letters, isin_to_digest))

    ints = [int(s) for s in to_digest[::-1]]
    every_second_doubled = [x * 2 for x in ints[::2]] + ints[1::2]

    sum_digits = lambda i: sum(divmod(i, 10))
    digit_sum = sum([sum_digits(i) for i in every_second_doubled])

    check_digit = (10 - digit_sum % 10) % 10
    return isin_to_digest + str(check_digit)


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


class WSJFetcher(BaseFetcher):
    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        warning_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
    ):
        super().__init__(
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )

    async def _fetch_timeseries(
        self,
        client: httpx.AsyncClient,
        wsj_ticker_key: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
        uid: Optional[str | int] = None,
        intraday_timestamp: Optional[bool] = False,
        append_most_recent_last: Optional[bool] = False,
    ):
        payload = {
            "Step": "P1D",
            "TimeFrame": "all",
            "EntitlementToken": "57494d5ed7ad44af85bc59a51dd87c90",
            "IncludeMockTick": True,
            "FilterNullSlots": True,
            "FilterClosedPoints": True,
            "IncludeClosedSlots": True,
            "IncludeOfficialClose": True,
            "InjectOpen": True,
            "ShowPreMarket": True,
            "ShowAfterHours": True,
            "UseExtendedTimeFrame": True,
            "WantPriorClose": True,
            "IncludeCurrentQuotes": True,
            "ResetTodaysAfterHoursPercentChange": False,
            "Series": [
                {
                    "Key": wsj_ticker_key,
                    "Dialect": "Charting",
                    "Kind": "Ticker",
                    "SeriesId": "s1",
                    "DataTypes": ["Last"],
                }
            ],
        }
        params = {
            "json": json.dumps(payload),
            "ckey": "57494d5ed7",
        }
        url = "https://api.wsj.net/api/michelangelo/timeseries/history"
        prep_url = PreparedRequest()
        prep_url.prepare_url(url, params)
        headers = {
            "authority": "api.wsj.net",
            "method": "GET",
            "path": prep_url.path_url,
            "scheme": "https",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Dylan2010.EntitlementToken": "57494d5ed7ad44af85bc59a51dd87c90",
            "sec-ch-ua-mobile": "?0",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.74 Safari/537.36",
            "sec-ch-ua-platform": '"macOS"',
            "Origin": "https://www.wsj.com",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.wsj.com/",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        }

        cols_to_return = ["Date", wsj_ticker_key]
        retries = 0
        try:
            while retries < max_retries:
                try:
                    response = await client.get(prep_url.url, headers=headers)
                    response.raise_for_status()
                    json_data = response.json()
                    if intraday_timestamp:
                        df = pd.DataFrame(
                            {"Date": json_data["Series"][0]["CurrentQuote"]["DateUtc"], wsj_ticker_key: [d[0] for d in json_data["Series"][0]["DataPoints"]]}
                        )
                    else:
                        df = pd.DataFrame({"Date": json_data["TimeInfo"]["Ticks"], wsj_ticker_key: [d[0] for d in json_data["Series"][0]["DataPoints"]]})

                    if append_most_recent_last:
                        intraday_df = pd.DataFrame(
                            {"Date": json_data["Series"][0]["CurrentQuote"]["DateUtc"], wsj_ticker_key: [d[0] for d in json_data["Series"][0]["DataPoints"]]}
                        ).tail(1)

                        df = pd.concat([df.head(-1), intraday_df])

                    df["Date"] = pd.to_datetime(df["Date"], unit="ms", utc=True)
                    df = df.drop_duplicates(subset=["Date"]).sort_values(by="Date")
                    if start_date:
                        df = df[df["Date"].dt.date >= start_date.date()]
                    if end_date:
                        df = df[df["Date"].dt.date <= end_date.date()]

                    if uid:
                        return wsj_ticker_key, df, uid
                    return wsj_ticker_key, df

                except httpx.HTTPStatusError as e:
                    self._logger.error(f"WSJ - Bad Status: {response.status_code}")
                    if response.status_code == 404:
                        if uid:
                            return wsj_ticker_key, pd.DataFrame(columns=cols_to_return), uid
                        return wsj_ticker_key, pd.DataFrame(columns=cols_to_return)

                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"WSJ- Throttled for {wsj_ticker_key}. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    self._logger.error(f"WSJ - Error: {str(e)}")
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"WSJ - Throttled for {wsj_ticker_key}. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

            raise ValueError(f"WSJ  - Max retries exceeded for {wsj_ticker_key}")

        except Exception as e:
            self._logger.error(e)
            if uid:
                return wsj_ticker_key, pd.DataFrame(columns=cols_to_return), uid
            return wsj_ticker_key, pd.DataFrame(columns=cols_to_return)

    async def _fetch_timeseries_with_semaphore(self, semaphore, *args, **kwargs):
        async with semaphore:
            return await self._fetch_timeseries(*args, **kwargs)

    def wsj_timeseries_api(
        self,
        wsj_ticker_keys: List[str],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        intraday_timestamp: Optional[bool] = False,
        append_most_recent_last: Optional[bool] = False,
        one_df: Optional[bool] = False,
        show_tqdm: Optional[bool] = False,
        max_concurrent_tasks: int = 64,
    ):
        async def build_tasks(
            client: httpx.AsyncClient,
            wsj_ticker_keys: List[str],
            start_date: datetime,
            end_date: datetime,
        ):
            semaphore = asyncio.Semaphore(max_concurrent_tasks)
            tasks = [
                self._fetch_timeseries_with_semaphore(
                    semaphore=semaphore,
                    client=client,
                    wsj_ticker_key=wsj_ticker_key,
                    start_date=start_date,
                    end_date=end_date,
                    max_retries=3,
                    intraday_timestamp=intraday_timestamp,
                    append_most_recent_last=append_most_recent_last,
                )
                for wsj_ticker_key in wsj_ticker_keys
            ]

            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING DATA FROM WSJ...")
            return await asyncio.gather(*tasks)

        async def run_fetch_all(
            wsj_ticker_keys: List[str],
            start_date: datetime,
            end_date: datetime,
        ):
            async with httpx.AsyncClient(timeout=self._global_timeout, mounts=self._httpx_proxies, verify=False, http2=True) as client:
                all_data = await build_tasks(
                    client=client,
                    wsj_ticker_keys=wsj_ticker_keys,
                    start_date=start_date,
                    end_date=end_date,
                )
                return all_data

        dfs: List[Tuple[str, pd.DataFrame]] = asyncio.run(
            run_fetch_all(
                wsj_ticker_keys=wsj_ticker_keys,
                start_date=start_date,
                end_date=end_date,
            )
        )

        if one_df:
            dict_df = {}
            for symbol, df in dfs:
                if df is not None:
                    dict_df[symbol] = df

            merge_dfs_on_column = lambda dfs_dict, on_column: reduce(lambda left, right: pd.merge(left, right, on=on_column, how="outer"), dfs_dict.values())
            return merge_dfs_on_column(dict_df, "Date").reset_index(drop=True).set_index("Date")

        return dict(dfs)

    async def _fetch_ust_intraday_timeseries(
        self,
        client: httpx.AsyncClient,
        wsj_ticker_key: str,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
        uid: Optional[str | int] = None,
    ):
        payload = {
            "Step": "PT1M",
            "TimeFrame": "D10",
            "EntitlementToken": "57494d5ed7ad44af85bc59a51dd87c90",
            "IncludeMockTick": True,
            "FilterNullSlots": True,
            "FilterClosedPoints": True,
            "IncludeClosedSlots": True,
            "IncludeOfficialClose": True,
            "InjectOpen": True,
            "ShowPreMarket": True,
            "ShowAfterHours": True,
            "UseExtendedTimeFrame": True,
            "WantPriorClose": True,
            "IncludeCurrentQuotes": True,
            "ResetTodaysAfterHoursPercentChange": False,
            "Series": [
                {
                    "Key": wsj_ticker_key,
                    "Dialect": "Charting",
                    "Kind": "Ticker",
                    "SeriesId": "s1",
                    "DataTypes": ["Last"],
                }
            ],
        }
        params = {
            "json": json.dumps(payload),
            "ckey": "57494d5ed7",
        }
        url = "https://api.wsj.net/api/michelangelo/timeseries/history"
        prep_url = PreparedRequest()
        prep_url.prepare_url(url, params)
        headers = {
            "authority": "api.wsj.net",
            "method": "GET",
            "path": prep_url.path_url,
            "scheme": "https",
            "Connection": "keep-alive",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Dylan2010.EntitlementToken": "57494d5ed7ad44af85bc59a51dd87c90",
            "sec-ch-ua-mobile": "?0",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.74 Safari/537.36",
            "sec-ch-ua-platform": '"macOS"',
            "Origin": "https://www.wsj.com",
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Referer": "https://www.wsj.com/",
            "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        }

        cols_to_return = ["Date", wsj_ticker_key]
        retries = 0
        try:
            while retries < max_retries:
                try:
                    response = await client.get(prep_url.url, headers=headers)
                    response.raise_for_status()
                    json_data = response.json()
                    df = pd.DataFrame({"Timestamp": json_data["TimeInfo"]["Ticks"], wsj_ticker_key: [d[0] for d in json_data["Series"][0]["DataPoints"]]})

                    df["Timestamp"] = pd.to_datetime(df["Timestamp"], unit="ms", utc=True)
                    df = df.drop_duplicates(subset=["Timestamp"]).sort_values(by="Timestamp")

                    if uid:
                        return wsj_ticker_key, df, uid
                    return wsj_ticker_key, df

                except httpx.HTTPStatusError as e:
                    self._logger.error(f"WSJ - Bad Status: {response.status_code}")
                    if response.status_code == 404:
                        if uid:
                            return wsj_ticker_key, pd.DataFrame(columns=cols_to_return), uid
                        return wsj_ticker_key, pd.DataFrame(columns=cols_to_return)

                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"WSJ- Throttled for {wsj_ticker_key}. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    self._logger.error(f"WSJ - Error: {str(e)}")
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"WSJ - Throttled for {wsj_ticker_key}. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

            raise ValueError(f"WSJ  - Max retries exceeded for {wsj_ticker_key}")

        except Exception as e:
            self._logger.error(e)
            if uid:
                return wsj_ticker_key, pd.DataFrame(columns=cols_to_return), uid
            return wsj_ticker_key, pd.DataFrame(columns=cols_to_return)

    async def _fetch_ust_intraday_timeseries_with_semaphore(self, semaphore, *args, **kwargs):
        async with semaphore:
            return await self._fetch_ust_intraday_timeseries(*args, **kwargs)

    def ust_intraday_timeseries(self, wsj_ticker_keys: Dict[str, str], show_tqdm: Optional[bool] = False):
        async def build_tasks(
            client: httpx.AsyncClient,
            wsj_ticker_keys: List[str],
        ):
            semaphore = asyncio.Semaphore(64)
            tasks = [
                self._fetch_ust_intraday_timeseries_with_semaphore(
                    semaphore=semaphore,
                    client=client,
                    wsj_ticker_key=wsj_ticker_key,
                    max_retries=3,
                )
                for wsj_ticker_key in wsj_ticker_keys
            ]

            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING DATA FROM WSJ...")
            return await asyncio.gather(*tasks)

        async def run_fetch_all(
            wsj_ticker_keys: List[str],
        ):
            async with httpx.AsyncClient(timeout=self._global_timeout, mounts=self._httpx_proxies, verify=False, http2=True) as client:
                all_data = await build_tasks(
                    client=client,
                    wsj_ticker_keys=wsj_ticker_keys,
                )
                return all_data

        dfs: List[Tuple[str, pd.DataFrame]] = asyncio.run(
            run_fetch_all(
                wsj_ticker_keys=wsj_ticker_keys.keys(),
            )
        )

        dict_df = {}
        for symbol, df in dfs:
            if df is not None:
                dict_df[wsj_ticker_keys[symbol]] = df

        merge_dfs_on_column = lambda dfs_dict, on_column: reduce(lambda left, right: pd.merge(left, right, on=on_column, how="outer"), dfs_dict.values())
        df = merge_dfs_on_column(dict_df, "Timestamp").reset_index(drop=True).set_index("Timestamp")
        return df.rename(columns=wsj_ticker_keys)

    def fetch_live_ust_quotes(
        self,
        cusips: List[str],
        *,
        batch_size: int = 50,
        max_concurrent_tasks: int = 16,
        show_tqdm: bool = False,
    ) -> Dict[str, Dict[str, float]]:
        from requests.models import PreparedRequest

        url = "https://api.wsj.net/api/dylan/quotes/v2/comp/quoteByDialect"

        base_params = {
            "dialect": "official",
            "needed": "CompositeTrading|BluegrassChannels",
            "MaxInstrumentMatches": "1",
            "accept": "application/json",
            "EntitlementToken": "cecc4267a0194af89ca343805a3e57af",
            "ckey": "cecc4267a0",
            "dialects": "Charting",
            # "id" will be filled per batch
        }

        def _chunks(lst: List[str], n: int):
            for i in range(0, len(lst), n):
                yield lst[i : i + n]

        async def _fetch_batch(client: httpx.AsyncClient, batch: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
            # WSJ expects ids like: Bond-US-<ISIN_WITHOUT_COUNTRY_PREFIX>
            ids = ",".join([f"Bond-US-{get_isin_from_cusip(c, 'US')[2:]}" for c in batch])

            params = dict(base_params)
            params["id"] = ids

            prep = PreparedRequest()
            prep.prepare_url(url, params)

            headers = {
                "authority": "api.wsj.net",
                "method": "GET",
                "path": prep.path_url,
                "scheme": "https",
                "Connection": "keep-alive",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
                "sec-ch-ua": '" Not A;Brand";v="99", "Chromium";v="99", "Google Chrome";v="99"',
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "sec-ch-ua-mobile": "?0",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.74 Safari/537.36",
                "sec-ch-ua-platform": '"macOS"',
                "Origin": "https://www.wsj.com",
                "Sec-Fetch-Site": "cross-site",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "Referer": "https://www.wsj.com/",
                "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
            }

            out: Dict[str, Dict[str, Optional[float]]] = {}
            try:
                resp = await client.get(prep.url, headers=headers)
                resp.raise_for_status()
                payload = resp.json().get("InstrumentResponses", [])

                for entry in payload:
                    try:
                        match = entry["Matches"][0]
                        c = match["Instrument"]["Cusip"]
                        price = match.get("BondSpecific", {}).get("TradePrice", {}).get("Value")
                        ytm = match.get("BondSpecific", {}).get("Yield")
                        timestamp = match.get("CompositeTrading", {}).get("Last", {}).get("Time")
                        out[c] = {
                            "price": price,
                            "ytm": ytm,
                            "timestamp": pytz.UTC.localize(datetime.fromisoformat(timestamp)).astimezone(pytz.timezone("America/New_York")),
                        }
                    except Exception:
                        # If WSJ couldn't match, keep None values so caller sees it's missing
                        # Try to back-fill CUSIP if possible
                        try:
                            c = entry["RequestedSymbol"].split("-")[-1]  # last token is ISIN w/o country in some cases
                        except Exception:
                            c = None
                        if c:
                            out.setdefault(c, {"price": None, "ytm": None, "timestamp": None})
                return out

            except Exception as e:
                self._logger.error(f"WSJ live quotes batch failed: {e}")
                # Return empty for this batch; caller will simply miss these until retry
                return out

        async def _runner(batches: List[List[str]]) -> Dict[str, Dict[str, Optional[float]]]:
            semaphore = asyncio.Semaphore(max_concurrent_tasks)

            async with httpx.AsyncClient(
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                verify=False,
                http2=True,
            ) as client:

                async def _guarded(batch):
                    async with semaphore:
                        return await _fetch_batch(client, batch)

                tasks = [_guarded(b) for b in batches]
                if show_tqdm:
                    results = await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING LIVE UST QUOTES...")
                else:
                    results = await asyncio.gather(*tasks)

            merged: Dict[str, Dict[str, Optional[float]]] = {}
            for d in results:
                merged.update(d)
            return merged

        batches = list(_chunks(cusips, batch_size))
        return asyncio.run(_runner(batches))
