# ABOUTME: ANNA-DSB UPI file mapping constants for different swap asset types.
# ABOUTME: Maps product types to CSV filenames for Fixed-Float, OIS, and Basis swaps.

ASSET_TYPE_TO_FILE_NAME = {
    "Fixed - Floating": "Rates-Swap-Fixed_Float.csv",
    "Overnight Index Swap (OIS)": "Rates-Swap-Fixed_Float_OIS.csv",
    "Basis Swap (Float - Float)": "Rates-Swap-Basis.csv",
}

import asyncio
import collections
import logging
import time
import urllib
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import httpx
import pandas as pd
import tqdm
import tqdm.asyncio

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


class AnnaDSBFetcher(BaseFetcher):
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
        self._anna_dsb_prod_url = "https://prod.anna-dsb.com/gui/search/"
        self._anna_dsb_page_size = 5

    def _create_anna_dsb_headers_and_payload(
        self,
        page_num: int,
        asset_class: str,
        instrument_type: str,
        product: str,
        token: str,
        additional_query: Optional[str] = None,
        page_size: Optional[int] = None,
    ):
        query = f"/Header/Level:UPI && ((/Header/AssetClass: {asset_class}) && (/Header/InstrumentType: {instrument_type}) && (/Header/UseCase: {product})"
        if additional_query:
            query = f"{query} && {additional_query})"
        else:
            query = f"{query})"

        payload = {
            "query": query,
            "pageNum": page_num,
            "pageSize": page_size or self._anna_dsb_page_size,
        }
        url_params = urllib.parse.urlencode(payload)

        headers = {
            "authority": "prod.anna-dsb.com",
            "method": "GET",
            "path": f"/gui/search/?{url_params}",
            "scheme": "https",
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9",
            "authorization": f"Bearer {token}",
            "cookie": "_legacy_auth0.H7HELuXAjFLHRt5nZjra2IYvfJc4GoSE.is.authenticated=true; auth0.H7HELuXAjFLHRt5nZjra2IYvfJc4GoSE.is.authenticated=true",
            "dnt": "1",
            "priority": "u=1, i",
            "referer": "https://prod.anna-dsb.com/",
            "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
        }

        return headers, payload, f"{self._anna_dsb_prod_url}?{url_params}"

    async def _fetch_anna_dsb_data(
        self,
        client: httpx.AsyncClient,
        page_num: int,
        asset_class: str,
        instrument_type: str,
        product: str,
        token: str,
        uid: Optional[int | str] = None,
        max_retries: Optional[int] = 5,
        backoff_factor: Optional[int] = 2,
        additional_query: Optional[str] = None,
    ):
        retries = 0
        headers, _, url = self._create_anna_dsb_headers_and_payload(
            page_num=page_num, asset_class=asset_class, instrument_type=instrument_type, product=product, token=token, additional_query=additional_query
        )
        try:
            while retries < max_retries:
                try:
                    response = await client.get(
                        url,
                        headers=headers,
                        follow_redirects=False,
                        timeout=self._global_timeout,
                    )
                    response.raise_for_status()
                    json_data = response.json()

                    if uid is not None:
                        return json_data, uid
                    return json_data

                except httpx.HTTPStatusError as e:
                    self._logger.error(f"ANNA DSB - Bad Status for {page_num}-{asset_class}-{instrument_type}: {response.status_code}")
                    if response.status_code == 404:
                        if uid is not None:
                            return None, uid
                        return None

                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"ANNA DSB - Throttled. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    self._logger.error(f"ANNA DSB - Error for {page_num}-{asset_class}-{instrument_type}: {e}")
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"ANNA DSB - Throttled. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

            raise ValueError(f"ANNA DSB - Max retries exceeded for {page_num}-{asset_class}-{instrument_type}")

        except Exception as e:
            self._logger.error(e)
            if uid is not None:
                return None, uid
            return None

    async def _fetch_anna_dsb_data_semaphore(self, semaphore, *args, **kwargs):
        async with semaphore:
            return await self._fetch_anna_dsb_data(*args, **kwargs)

    def _flatten_data(self, y):
        out = {}

        def flatten(x, name=""):
            if type(x) is dict:
                for a in x:
                    flatten(x[a], name + a + "_")
            elif type(x) is list:
                i = 0
                for a in x:
                    flatten(a, name + str(i) + "_")
                    i += 1
            else:
                out[name[:-1]] = x

        flatten(y)
        return out

    def get_anna_dsb_upis(
        self,
        asset_class: str,
        instrument_type: str,
        product: str,
        token: str,
        num_of_iterations: int,
        start_of_iterations: Optional[int] = 0,
        max_concurrent_tasks: int = 64,
        max_keepalive_connections: int = 5,
        function_timeout_minutes: int = 15,
        additional_query: Optional[str] = None,
        return_errors: Optional[bool] = False,
    ) -> pd.DataFrame:

        async def run_fetch_all(
            start_of_iterations: int,
            num_of_iterations: int,
            asset_class: str,
            instrument_type: str,
            product: str,
            token: str,
            timeout_minutes: int,
            additional_query: str,
        ):
            limits = httpx.Limits(
                max_connections=max_concurrent_tasks,
                max_keepalive_connections=max_keepalive_connections,
            )

            async with httpx.AsyncClient(limits=limits, timeout=self._global_timeout, mounts=self._httpx_proxies, verify=False, http2=True) as client:
                semaphore = asyncio.Semaphore(max_concurrent_tasks)
                tasks = []
                for i in range(start_of_iterations, num_of_iterations):
                    task = asyncio.create_task(
                        self._fetch_anna_dsb_data_semaphore(
                            semaphore=semaphore,
                            client=client,
                            page_num=i,
                            uid=i,
                            asset_class=asset_class,
                            instrument_type=instrument_type,
                            product=product,
                            token=token,
                            additional_query=additional_query,
                        )
                    )
                    tasks.append(task)

                total_timeout = 60 * timeout_minutes
                start_time = time.monotonic()

                results = []
                pending = set(tasks)

                with tqdm.tqdm(total=len(tasks), desc="FETCHING ANNA DSB UPI DATASETS...") as pbar:
                    while pending:
                        now = time.monotonic()
                        elapsed = now - start_time
                        remaining = total_timeout - elapsed

                        if remaining <= 0:
                            print(f"Timeout of {timeout_minutes} minutes reached. Cancelling pending tasks.")
                            for task in pending:
                                task.cancel()
                            break

                        done, pending = await asyncio.wait(pending, timeout=min(1, remaining), return_when=asyncio.FIRST_COMPLETED)

                        for task in done:
                            try:
                                result = task.result()
                                results.append(result)
                            except asyncio.CancelledError:
                                pass
                            except Exception as e:
                                self._logger.error(f"ANNA DSB UPI RUNNER - Something went wrong: {e}")
                                pass
                            finally:
                                pbar.update(1)

                        if not done:
                            await asyncio.sleep(0.1)

                return results

        async def main(
            start_of_iterations: int,
            num_of_iterations: int,
            asset_class: str,
            instrument_type: str,
            product: str,
            token: str,
            additional_query: str,
            timeout_minutes: int,
            return_errors: bool,
        ):
            results = await run_fetch_all(
                start_of_iterations=start_of_iterations,
                num_of_iterations=num_of_iterations,
                asset_class=asset_class,
                instrument_type=instrument_type,
                product=product,
                token=token,
                additional_query=additional_query,
                timeout_minutes=timeout_minutes,
            )

            flat_data = []
            errors = []

            for d, uid in results:
                if not d or not isinstance(d, collections.abc.Mapping):
                    errors.append(uid)
                    continue

                if "records" in d:
                    records = d["records"]
                    if records is None or not isinstance(records, collections.abc.Iterable):
                        errors.append(uid)
                        continue

                    if len(records) > 0:
                        flat_data += records

            df = pd.DataFrame([self._flatten_data(data) for data in flat_data])
            df = df.drop_duplicates(subset=["Identifier_UPI"])

            if return_errors:
                return df, errors
            return df

        return asyncio.run(
            main(
                start_of_iterations=start_of_iterations,
                num_of_iterations=num_of_iterations,
                asset_class=asset_class,
                instrument_type=instrument_type,
                product=product,
                token=token,
                additional_query=additional_query,
                timeout_minutes=function_timeout_minutes,
                return_errors=return_errors,
            )
        )

    def update_product_upi_cache(
        self,
        product_upi_cache_path: str,
        token: str,
    ):
        curr_upi_propduct_cache_df = pd.read_csv(product_upi_cache_path)
        curr_upi_propduct_cache_df["Identifier_LastUpdateDateTime"] = pd.to_datetime(curr_upi_propduct_cache_df["Identifier_LastUpdateDateTime"])
        curr_upi_propduct_cache_df = curr_upi_propduct_cache_df.sort_values(by=["Identifier_LastUpdateDateTime"])
        curr_upi_propduct_cache_df = curr_upi_propduct_cache_df.drop_duplicates(subset="Identifier_UPI", keep="last").reset_index(drop=True)
        curr_upi_propduct_cache_df["date"] = curr_upi_propduct_cache_df["Identifier_LastUpdateDateTime"].dt.date

        days_since_last_fetched: timedelta = datetime.today().date() - curr_upi_propduct_cache_df["date"].max()
        max_created = curr_upi_propduct_cache_df.groupby("date").size().mean()

        asset_class, instrument_type, product = Path(product_upi_cache_path).parts[-1].split(".")[0].split("-")

        updated_upi_product_df = self.get_anna_dsb_upis(
            asset_class=asset_class,
            instrument_type=instrument_type,
            product=product,
            token=token,
            num_of_iterations=max(1, int(max_created * days_since_last_fetched.days)),
            max_concurrent_tasks=256,
            max_keepalive_connections=12,
        )

        if updated_upi_product_df.empty:
            print("FETCHED UPIS EMPTY")
            return

        updated_upi_product_df["Identifier_LastUpdateDateTime"] = pd.to_datetime(updated_upi_product_df["Identifier_LastUpdateDateTime"])
        updated_upi_product_df = pd.concat([updated_upi_product_df, curr_upi_propduct_cache_df.drop(columns=["date"])])
        updated_upi_product_df = updated_upi_product_df.sort_values(by=["Identifier_LastUpdateDateTime"])
        updated_upi_product_df = updated_upi_product_df.drop_duplicates(subset="Identifier_UPI", keep="last").reset_index(drop=True)
        updated_upi_product_df.to_csv(product_upi_cache_path, index=False)

        return updated_upi_product_df
