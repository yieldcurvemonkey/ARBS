import asyncio
import logging
import re
import sys
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Tuple, Union

import httpx
import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import pyzipper
import requests
import tqdm
import tqdm.asyncio
import ujson


def _generate_business_days(start_date: date, end_date: date) -> List[date]:
    """
    Generate business days (Monday-Friday) between start_date and end_date, excluding US federal holidays.

    This replaces pandas.date_range with CustomBusinessDay(calendar=USFederalHolidayCalendar()).
    """
    # US Federal Holidays for common years - simplified version
    # For production use, consider using QuantLib calendar or a dedicated holiday library
    def get_us_federal_holidays(year: int) -> List[date]:
        holidays = []
        # New Year's Day
        holidays.append(date(year, 1, 1))
        # Independence Day
        holidays.append(date(year, 7, 4))
        # Veterans Day
        holidays.append(date(year, 11, 11))
        # Christmas Day
        holidays.append(date(year, 12, 25))
        # Add other fixed holidays as needed
        return holidays

    # Collect all holidays in the range
    all_holidays = set()
    for year in range(start_date.year, end_date.year + 1):
        all_holidays.update(get_us_federal_holidays(year))

    # Generate business days
    business_days = []
    current = start_date
    while current <= end_date:
        # Monday = 0, Friday = 4, Saturday = 5, Sunday = 6
        if current.weekday() < 5 and current not in all_holidays:
            business_days.append(current)
        current += timedelta(days=1)

    return business_days


class BaseFetcher:
    def __init__(
        self,
        global_timeout: Optional[int] = 10,
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


def datetime_today_utc():
    return datetime(
        year=datetime.now(timezone.utc).year,
        month=datetime.now(timezone.utc).month,
        day=datetime.now(timezone.utc).day,
    )


class DTCCFetcher(BaseFetcher):
    pddata_dtcc_base_url = "https://pddata.dtcc.com/ppd"

    def __init__(
        self,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        warning_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
    ):
        super().__init__(
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )

    def _get_dtcc_url_and_header(
        self,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        date_string: str,
    ) -> Tuple[str, Dict[str, str]]:
        if agency == "SEC" and asset_class in ["COMMODITIES", "FOREX"]:
            raise ValueError(f"SEC does not store {asset_class} in their SDR data.")

        is_intraday_report = len(date_string.split("_")) == 4
        if is_intraday_report:
            # e.g. .../intraday/cftc/CFTC_SLICE_RATES_2023_01_15_10_420.zip
            dtcc_url = f"{self.pddata_dtcc_base_url}/api/report/intraday/{agency.lower()}/{agency}_SLICE_{asset_class}_{date_string}.zip"
        else:
            # e.g. .../cumulative/cftc/CFTC_CUMULATIVE_RATES_2023_01_15.zip
            dtcc_url = f"{self.pddata_dtcc_base_url}/api/report/cumulative/{agency.lower()}/{agency}_CUMULATIVE_{asset_class}_{date_string}.zip"

        dtcc_headers = {
            "authority": "pddata.dtcc.com",
            "method": "GET",
            "path": dtcc_url.split(".com")[1],
            "scheme": "https",
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9",
            "dnt": "1",
            "priority": "u=1, i",
            "referer": f"{self.pddata_dtcc_base_url}/{agency.lower()}dashboard",
            "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) " "AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/130.0.0.0 Safari/537.36"),
        }
        return dtcc_url, dtcc_headers

    async def _fetch_dtcc_sdr_data_helper(
        self,
        client: httpx.AsyncClient,
        date_string: str,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        max_retries: Optional[int] = 5,
        backoff_factor: Optional[int] = 1,
    ) -> Optional[BytesIO]:
        dtcc_sdr_url, dtcc_sdr_header = self._get_dtcc_url_and_header(date_string=date_string, agency=agency, asset_class=asset_class)

        retries = 0
        while retries < max_retries:
            try:
                async with client.stream("GET", dtcc_sdr_url, headers=dtcc_sdr_header, timeout=self._global_timeout) as response:
                    response.raise_for_status()
                    zip_buffer = BytesIO()
                    async for chunk in response.aiter_bytes():
                        zip_buffer.write(chunk)
                    zip_buffer.seek(0)
                return zip_buffer

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    self._logger.debug(f"DTCCFetcher - 404 for {agency}-{asset_class}-{date_string}. Skipping.")
                    return None

                # attempt exponential backoff
                retries += 1
                wait_time = backoff_factor * (2 ** (retries - 1))
                self._logger.debug(f"DTCCFetcher - HTTP Error {e.response.status_code} for {agency}-{asset_class}-{date_string}. " f"Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

            except (httpx.RequestError, Exception) as e:
                retries += 1
                wait_time = backoff_factor * (2 ** (retries - 1))
                self._logger.debug(f"DTCCFetcher - Connection/Other Error {e} for {agency}-{asset_class}-{date_string}. " f"Retrying in {wait_time}s...")
                await asyncio.sleep(wait_time)

        self._logger.error(f"DTCCFetcher - Max retries exceeded for {agency}-{asset_class}-{date_string}.")
        return None

    @staticmethod
    def _parse_filename_to_datetime(filename: str) -> datetime:
        """
        Extract date from the file name by patterning on '_YYYY_MM_DD'.

        :param filename: e.g. "CFTC_IR_2023_01_15"
        :return: datetime(2023, 1, 15)
        """
        match = re.search(r"_(\d{4})_(\d{2})_(\d{2})$", filename)
        if not match:
            raise ValueError(f"DTCCFetcher - Filename does not contain a valid date: {filename}")
        year, month, day = map(int, match.groups())
        return datetime(year, month, day)

    @staticmethod
    def _read_single_file(
        file_buffer: bytes,
        file_name: str,
        convert_key_into_dt: bool,
        use_pyarrow: Optional[bool] = False,
    ) -> Tuple[Optional[Union[str, datetime]], Optional[pl.DataFrame]]:
        file_name_lower = file_name.lower()
        extension = None
        if file_name_lower.endswith((".xls", ".xlsx")):
            extension = "excel"
        elif file_name_lower.endswith(".csv"):
            extension = "csv"
        else:
            # Not a recognized extension
            return None, None

        buffer_io = BytesIO(file_buffer)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if extension == "excel":
                # Read Excel using openpyxl and convert to polars
                try:
                    import openpyxl
                    wb = openpyxl.load_workbook(buffer_io, read_only=True, data_only=True)
                    ws = wb.active
                    data = list(ws.values)
                    if data:
                        headers = data[0]
                        rows = data[1:]
                        df = pl.DataFrame(rows, schema=headers, orient="row")
                    else:
                        df = pl.DataFrame()
                    wb.close()
                except ImportError:
                    # Fallback: if openpyxl not available, read with pandas and convert
                    import pandas as pd
                    pd_df = pd.read_excel(buffer_io)
                    df = pl.from_pandas(pd_df)
            else:  # csv
                if use_pyarrow:
                    try:
                        table = pacsv.read_csv(buffer_io)
                        df = pl.from_arrow(table)
                    except ImportError:
                        buffer_io.seek(0)
                        df = pl.read_csv(buffer_io)
                else:
                    df = pl.read_csv(buffer_io)

        key = file_name
        if convert_key_into_dt:
            try:
                key = DTCCFetcher._parse_filename_to_datetime(file_name.split(".")[0])
            except ValueError:
                # fallback: keep as string if parse fails
                pass

        return key, df

    def _extract_dataframes_from_zip(
        self,
        zip_buffer: BytesIO,
        convert_key_into_dt: Optional[bool] = False,
        parallelize: Optional[bool] = False,
        max_extraction_workers: Optional[int] = 3,
        use_pyarrow: Optional[bool] = False,
    ) -> Dict[Union[str, datetime], pl.DataFrame]:
        if not zip_buffer:
            return {}

        dataframes: Dict[Union[str, datetime], pl.DataFrame] = {}
        with pyzipper.AESZipFile(zip_buffer) as zip_file:
            allowed_extensions = (".xlsx", ".xls", ".csv")
            candidates = [info for info in zip_file.infolist() if not info.is_dir() and info.filename.lower().endswith(allowed_extensions)]
            if not candidates:
                return {}

            def process_single_entry(info):
                file_name = info.filename
                file_content = zip_file.read(file_name)
                key, df = self._read_single_file(
                    file_buffer=file_content,
                    file_name=file_name,
                    convert_key_into_dt=convert_key_into_dt,
                    use_pyarrow=use_pyarrow,
                )
                return key, df

            if parallelize and len(candidates) > 1:
                with ThreadPoolExecutor(max_workers=max_extraction_workers) as executor:
                    results = list(executor.map(process_single_entry, candidates))
            else:
                results = [process_single_entry(info) for info in candidates]

            for key, df in results:
                if key is not None and df is not None:
                    dataframes[key] = df
        return dataframes

    async def _fetch_zip_and_extract(
        self,
        semaphore: asyncio.Semaphore,
        client: httpx.AsyncClient,
        date_string: str,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        parallelize: bool,
        max_extraction_workers: int,
        convert_key_into_dt: bool,
        use_pyarrow: bool,
        task_id: Optional[Any] = None,
    ) -> Dict[Union[str, datetime], pl.DataFrame]:
        async with semaphore:
            zip_buffer = await self._fetch_dtcc_sdr_data_helper(
                client=client,
                date_string=date_string,
                agency=agency,
                asset_class=asset_class,
            )

        # Use run_in_executor for CPU-bound extraction
        if zip_buffer is None:
            return {}

        loop = asyncio.get_event_loop()
        partial_func = partial(
            self._extract_dataframes_from_zip,
            zip_buffer=zip_buffer,
            convert_key_into_dt=convert_key_into_dt,
            parallelize=parallelize,
            max_extraction_workers=max_extraction_workers,
            use_pyarrow=use_pyarrow,
        )
        dataframes = await loop.run_in_executor(None, partial_func)
        if task_id:
            return dataframes, task_id
        return dataframes

    async def _run_fetch_tasks(
        self,
        date_strings: List[str],
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        parallelize: bool,
        max_extraction_workers: int,
        max_concurrent_tasks: int,
        client: httpx.AsyncClient,
        convert_key_into_dt: bool,
        use_pyarrow: bool,
        tqdm_desc: Optional[str] = "FETCHING DTCC SDR DATASETS...",
    ) -> List[Dict[Union[str, datetime], pl.DataFrame]]:
        semaphore = asyncio.Semaphore(max_concurrent_tasks)
        tasks = []
        for ds in date_strings:
            task = asyncio.create_task(
                self._fetch_zip_and_extract(
                    semaphore=semaphore,
                    client=client,
                    date_string=ds,
                    agency=agency,
                    asset_class=asset_class,
                    parallelize=parallelize,
                    max_extraction_workers=max_extraction_workers,
                    convert_key_into_dt=convert_key_into_dt,
                    use_pyarrow=use_pyarrow,
                )
            )
            tasks.append(task)

        if tqdm_desc:
            results = await tqdm.asyncio.tqdm.gather(*tasks, desc=tqdm_desc)
        else:
            results = await asyncio.gather(*tasks)
        return results

    def fetch_historical_reports(
        self,
        start_date: date,
        end_date: date,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        parallelize: Optional[bool] = False,
        max_extraction_workers: Optional[int] = 3,
        use_pyarrow: Optional[bool] = False,
        one_df: Optional[bool] = False,
        show_tqdm: Optional[bool] = True,
        ts_col: Optional[Literal["Event timestamp", "Execution Timestamp"]] = "Event timestamp",
    ) -> Dict[date, pl.DataFrame] | pl.DataFrame:
        bdates = _generate_business_days(start_date, end_date)
        date_strings = [d.strftime("%Y_%m_%d") for d in bdates]

        async def run():
            limits = httpx.Limits(
                max_connections=max_concurrent_tasks,
                max_keepalive_connections=max_keepalive_connections,
            )
            async with httpx.AsyncClient(limits=limits, timeout=self._global_timeout, mounts=self._httpx_proxies, verify=False, http2=True) as client:
                results = await self._run_fetch_tasks(
                    date_strings=date_strings,
                    agency=agency,
                    asset_class=asset_class,
                    parallelize=parallelize,
                    max_extraction_workers=max_extraction_workers,
                    max_concurrent_tasks=max_concurrent_tasks,
                    client=client,
                    convert_key_into_dt=True,
                    use_pyarrow=use_pyarrow,
                    tqdm_desc="FETCHING HISTORICAL SDR REPORTS..." if show_tqdm else None,
                )
                return results

        all_results = asyncio.run(run())
        merged_data: Dict[date, pl.DataFrame] = {}
        for daily_dict in all_results:
            for k, v_df in daily_dict.items():
                k = k.date()
                if isinstance(k, date) and isinstance(v_df, pl.DataFrame):
                    # Convert datetime columns
                    v_df = v_df.with_columns([
                        pl.col("Event timestamp").str.to_datetime(time_unit="us", time_zone="UTC").alias("Event timestamp"),
                        pl.col("Execution Timestamp").str.to_datetime(time_unit="us", time_zone="UTC").alias("Execution Timestamp"),
                        pl.col("Effective Date").str.to_datetime().alias("Effective Date"),
                        pl.col("Expiration Date").str.to_datetime().alias("Expiration Date"),
                    ])
                    v_df = v_df.sort(ts_col)
                    # Filter by date range
                    v_df = v_df.filter(
                        (pl.col(ts_col).dt.date() >= start_date) & (pl.col(ts_col).dt.date() <= end_date)
                    )
                    merged_data[k] = v_df

        if len(merged_data.keys()) == 0:
            return pl.DataFrame()

        if one_df:
            return pl.concat(merged_data.values())
        else:
            return merged_data

    def fetch_intraday_reports(
        self,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        start_timestamp: Optional[datetime] = None,
        end_timestamp: Optional[datetime] = None,
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        parallelize: Optional[bool] = False,
        max_extraction_workers: Optional[int] = 3,
        use_pyarrow: Optional[bool] = False,
        show_tqdm: Optional[bool] = True,
        ts_col: Optional[Literal["Event timestamp", "Execution Timestamp"]] = "Event timestamp",
    ) -> pl.DataFrame:
        slice_ids = self._get_dtcc_intraday_slide_ids(agency=agency, asset_class=asset_class, start_timestamp=start_timestamp, end_timestamp=end_timestamp)

        async def run_intra_slices():
            limits = httpx.Limits(
                max_connections=max_concurrent_tasks,
                max_keepalive_connections=max_keepalive_connections,
            )
            async with httpx.AsyncClient(limits=limits, timeout=self._global_timeout, mounts=self._httpx_proxies, verify=False, http2=True) as client:
                results = await self._run_fetch_tasks(
                    date_strings=slice_ids,
                    agency=agency,
                    asset_class=asset_class,
                    parallelize=parallelize,
                    max_extraction_workers=max_extraction_workers,
                    max_concurrent_tasks=max_concurrent_tasks,
                    client=client,
                    convert_key_into_dt=False,
                    use_pyarrow=use_pyarrow,
                    tqdm_desc="FETCHING INTRADAY SDR SLICES..." if show_tqdm else None,
                )
                return results

        all_results = asyncio.run(run_intra_slices())
        combined_results: Dict[str, pl.DataFrame] = {}
        for res_dict in all_results:
            combined_results.update(res_dict)  # merges each slice's data

        if not combined_results:
            return pl.DataFrame()

        list_of_dfs = []
        for slice_id_str, df in combined_results.items():
            df = df.clone()
            df = df.with_columns(pl.lit(slice_id_str).alias("report_slice"))
            list_of_dfs.append(df)

        combined_df = pl.concat(list_of_dfs)
        combined_df = combined_df.with_columns([
            pl.col("Event timestamp").str.to_datetime(time_unit="us", time_zone="UTC").alias("Event timestamp"),
            pl.col("Execution Timestamp").str.to_datetime(time_unit="us", time_zone="UTC").alias("Execution Timestamp"),
            pl.col("Effective Date").str.to_datetime().alias("Effective Date"),
            pl.col("Expiration Date").str.to_datetime().alias("Expiration Date"),
        ])
        combined_df = combined_df.sort(ts_col)

        if start_timestamp:
            combined_df = combined_df.filter(pl.col(ts_col) >= start_timestamp)
        if end_timestamp:
            combined_df = combined_df.filter(pl.col(ts_col) <= end_timestamp)

        return combined_df

    def fetch_reports(
        self,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        start_date: datetime,
        end_date: datetime,
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        parallelize: Optional[bool] = False,
        max_extraction_workers: Optional[int] = 3,
        use_pyarrow: Optional[bool] = False,
        show_tqdm: Optional[bool] = True,
    ) -> pl.DataFrame:
        append_intraday = False
        if end_date.astimezone(timezone.utc).date() == datetime_today_utc().date() and end_date.weekday() < 5:
            append_intraday = True

        historical_sdr_df = self.fetch_historical_reports(
            agency=agency,
            asset_class=asset_class,
            start_date=start_date.astimezone(timezone.utc),
            end_date=end_date.astimezone(timezone.utc),
            max_concurrent_tasks=max_concurrent_tasks,
            max_keepalive_connections=max_keepalive_connections,
            parallelize=parallelize,
            max_extraction_workers=max_extraction_workers,
            use_pyarrow=use_pyarrow,
            one_df=True,
            show_tqdm=show_tqdm,
        )
        if append_intraday:
            intraday_sdr_df = self.fetch_intraday_reports(
                agency=agency,
                asset_class=asset_class,
                start_timestamp=start_date.astimezone(timezone.utc) if start_date.tzinfo is not None else None,
                end_timestamp=end_date.astimezone(timezone.utc) if end_date.tzinfo is not None else None,
                max_concurrent_tasks=max_concurrent_tasks,
                max_keepalive_connections=max_keepalive_connections,
                parallelize=parallelize,
                max_extraction_workers=max_extraction_workers,
                use_pyarrow=use_pyarrow,
                show_tqdm=show_tqdm,
            )
            sdr_df = pl.concat([historical_sdr_df, intraday_sdr_df])
        else:
            sdr_df = historical_sdr_df

        if sdr_df.is_empty():
            return pl.DataFrame()

        # Replace empty strings and nulls with None
        for col in sdr_df.columns:
            sdr_df = sdr_df.with_columns(
                pl.when(pl.col(col).is_in(["", " ", "None", "NaN"]))
                .then(None)
                .otherwise(pl.col(col))
                .alias(col)
            )
        return sdr_df.sort("Event timestamp")

    def _get_dtcc_intraday_slide_ids(
        self,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        start_timestamp: Optional[datetime] = None,
        end_timestamp: Optional[datetime] = None,
    ):
        hist_intr_asset_class_id_mapper = {
            "COMMODITIES": "CO",
            "CREDITS": "CR",
            "EQUITIES": "EQ",
            "FOREX": "FX",
            "RATES": "IR",
        }
        if asset_class not in hist_intr_asset_class_id_mapper:
            raise ValueError(f"Unsupported asset class: {asset_class}")

        intraday_ids_url = f"{self.pddata_dtcc_base_url}/api/slice/{agency}/{hist_intr_asset_class_id_mapper[asset_class]}"
        intraday_report_ids_headers = {
            "authority": "pddata.dtcc.com",
            "method": "GET",
            "path": f"/ppd/api/slice/{agency}/{hist_intr_asset_class_id_mapper[asset_class]}",
            "scheme": "https",
            "accept": "application/json, text/plain, */*",
            "accept-encoding": "gzip, deflate, br, zstd",
            "accept-language": "en-US,en;q=0.9",
            "dnt": "1",
            "priority": "u=1, i",
            "referer": f"{self.pddata_dtcc_base_url}/{agency.lower()}dashboard",
            "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"),
        }

        intraday_report_ids_res = requests.get(
            intraday_ids_url,
            headers=intraday_report_ids_headers,
            proxies=self._proxies,
        )
        intraday_report_ids_res.raise_for_status()

        intraday_report_ids = ujson.loads(intraday_report_ids_res.content.decode("utf-8"))
        intraday_report_ids_df = pl.DataFrame(intraday_report_ids)
        intraday_report_ids_df = intraday_report_ids_df.with_columns(
            pl.col("dissemDTM").str.to_datetime(time_unit="us", time_zone="UTC").alias("dissemDTM")
        )
        if start_timestamp:
            # Ensure start_timestamp is tz-aware
            if start_timestamp.tzinfo is None:
                start_timestamp = start_timestamp.replace(tzinfo=timezone.utc)
            intraday_report_ids_df = intraday_report_ids_df.filter(pl.col("dissemDTM") >= start_timestamp)
        if end_timestamp:
            # Ensure end_timestamp is tz-aware
            if end_timestamp.tzinfo is None:
                end_timestamp = end_timestamp.replace(tzinfo=timezone.utc)
            intraday_report_ids_df = intraday_report_ids_df.filter(pl.col("dissemDTM") <= end_timestamp)

        # Extract slice IDs from filenames
        return [
            str(row["fileName"]).split(f"_{asset_class}_")[1].split(".")[0]
            for row in intraday_report_ids_df.to_dicts()
        ]


def _df_to_parquet(df: pl.DataFrame, path: Path, *, compression: Optional[str] = "zstd"):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression=compression)


def _save_daily_dict(
    data: Dict[date, pl.DataFrame],
    base_dir: Union[str, Path],
    *,
    agency: str,
    asset_class: str,
) -> None:
    base = Path(base_dir)
    for d, df in data.items():
        rel = Path(agency, asset_class, f"{d.year:04d}", f"{d.month:02d}")
        _df_to_parquet(df, base / rel / f"{d}.parquet")


def _load_daily_dict(
    dates: Iterable[date],
    base_dir: Union[str, Path],
    *,
    agency: str,
    asset_class: str,
    show_tqdm: Optional[bool] = False,
) -> Dict[date, pl.DataFrame]:
    base = Path(base_dir)
    out: Dict[date, pl.DataFrame] = {}

    if show_tqdm:
        from tqdm import tqdm

        to_iter = tqdm(dates, desc="CACHE HIT...")
    else:
        to_iter = dates

    for d in to_iter:
        fp = base / agency / asset_class / f"{d.year:04d}" / f"{d.month:02d}" / f"{d}.parquet"
        if fp.exists():
            out[d] = pl.read_parquet(fp)
    return out


def _read_intraday_cache(fp: Path) -> pl.DataFrame:
    if not fp.is_file():
        return pl.DataFrame()

    try:
        return pl.read_csv(
            fp,
            try_parse_dates=True,
        )
    except Exception:
        _clear_file(fp)
        return pl.DataFrame()


def _clear_file(fp: Path) -> None:
    try:
        if fp.exists():
            fp.unlink()
    except Exception:
        # If deletion fails for any reason, just ignore and fall back to ignoring the file content
        pass


def _write_intraday_cache(df: pl.DataFrame, fp: Path):
    fp.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(fp)


def _concat_dfs(
    frames: Iterable[pl.DataFrame],
    *,
    unique_subset: Optional[List[str]] = None,
    sort_by: Optional[str] = None,
    use_polars: bool = False,  # Kept for backwards compatibility but ignored
    show_tqdm: bool = False,
    tqdm_desc: Optional[str] = None,
    chunk_size: Optional[int] = 256,
    filter_func: Optional[Callable[[pl.DataFrame], pl.DataFrame]] = None,
) -> pl.DataFrame:
    def _iter_with_progress(it, desc: str):
        if not show_tqdm:
            return it
        try:
            from tqdm import tqdm as _tqdm
        except ImportError as e:
            raise ImportError("show_tqdm=True requires 'tqdm'. Install with: pip install tqdm") from e
        return _tqdm(it, desc=desc, unit="df")

    def _chunk_indices(n: int, k: int):
        if k is None or k <= 0:
            yield 0, n
            return
        for start in range(0, n, k):
            yield start, min(start + k, n)

    frames = [f for f in frames if f is not None and not f.is_empty()]
    if not frames:
        return pl.DataFrame()

    if filter_func is not None:
        filtered: List[pl.DataFrame] = []
        for df in _iter_with_progress(frames, tqdm_desc or "Pre-filtering"):
            res = filter_func(df)
            if res is not None and not res.is_empty():
                filtered.append(res)
        frames = filtered
        if not frames:
            return pl.DataFrame()

    def _align_to_union(pl_frames: List[pl.DataFrame]) -> List[pl.DataFrame]:
        union_cols: List[str] = []
        seen = set()
        for f in pl_frames:
            for c in f.columns:
                if c not in seen:
                    seen.add(c)
                    union_cols.append(c)

        aligned: List[pl.DataFrame] = []
        for f in pl_frames:
            missing = [c for c in union_cols if c not in f.columns]
            if missing:
                f = f.with_columns([pl.lit(None).alias(c) for c in missing])
            aligned.append(f.select(union_cols))
        return aligned

    pl_frames = _align_to_union(frames)

    if len(pl_frames) == 1:
        out_pl = pl_frames[0]
    else:
        first_chunk = True
        out_pl = None
        index_iter = range(0, len(pl_frames), max(1, chunk_size or len(pl_frames)))
        if show_tqdm:
            index_iter = _iter_with_progress(index_iter, tqdm_desc or "Concatenating")
        for i0 in index_iter:
            i1 = min(i0 + (chunk_size or len(pl_frames)), len(pl_frames))
            chunk = pl.concat(pl_frames[i0:i1], how="vertical_relaxed")
            out_pl = chunk if first_chunk else pl.concat([out_pl, chunk], how="vertical_relaxed")  # type: ignore[arg-type]
            first_chunk = False

    if unique_subset:
        cols = [c for c in unique_subset if c in out_pl.columns]  # type: ignore[union-attr]
        if cols:
            out_pl = out_pl.unique(subset=cols, keep="first", maintain_order=True)  # type: ignore[assignment]

    if sort_by and (sort_by in out_pl.columns):  # type: ignore[operator]
        out_pl = out_pl.sort(sort_by)  # type: ignore[assignment]

    return out_pl  # type: ignore[return-value]


class SDRDataBuilder:

    def __init__(
        self,
        cache_path: str,
        show_tqdm: Optional[bool] = False,
        intraday_cache_ttl: Optional[timedelta] = timedelta(days=3),
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 12,
        max_extraction_workers: Optional[int] = 8,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        warning_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
    ):
        self.dtcc_sdr_fetcher = DTCCFetcher(
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )
        self._parquet_cache_dir = Path(cache_path)
        self._show_tqdm = show_tqdm
        # self._use_polars = use_polars
        self._intraday_cache_ttl = intraday_cache_ttl

        self._max_concurrent_tasks = max_concurrent_tasks
        self._max_keepalive_connections = max_keepalive_connections
        self._max_extraction_workers = max_extraction_workers

    def grab_intraday_sdr_trades(
        self,
        start_timestamp: datetime,
        end_timestamp: datetime,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
    ) -> pl.DataFrame:
        # Ensure timestamps are tz-aware
        if start_timestamp.tzinfo is None:
            start_timestamp = start_timestamp.replace(tzinfo=timezone.utc)
        if end_timestamp.tzinfo is None:
            end_timestamp = end_timestamp.replace(tzinfo=timezone.utc)

        cache_fp = self._parquet_cache_dir / "intraday.csv"
        cache_df = _read_intraday_cache(cache_fp)
        ts_col = "Event timestamp"

        if not cache_df.is_empty() and self._intraday_cache_ttl is not None:
            try:
                last_cached = cache_df[ts_col].max()
            except Exception:
                # If the column is missing or unparsable, nuke the cache
                _clear_file(cache_fp)
                cache_df = pl.DataFrame()
            else:
                now_utc = datetime.now(timezone.utc)
                if (now_utc - last_cached) > self._intraday_cache_ttl:
                    _clear_file(cache_fp)
                    cache_df = pl.DataFrame()

        if cache_df.is_empty():
            fetch_from = start_timestamp
        else:
            last_cached = cache_df[ts_col].max()

            today_utc_midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

            if last_cached < today_utc_midnight:
                fetch_from = today_utc_midnight
            else:
                fetch_from = last_cached + timedelta(seconds=1)

            fetch_from = max(fetch_from, start_timestamp)

        if fetch_from > end_timestamp:
            result_df = cache_df.filter(
                (pl.col(ts_col) >= start_timestamp) & (pl.col(ts_col) <= end_timestamp)
            )
            return result_df

        new_df = self.dtcc_sdr_fetcher.fetch_intraday_reports(
            agency=agency,
            asset_class=asset_class,
            start_timestamp=fetch_from,
            end_timestamp=end_timestamp,
            max_concurrent_tasks=self._max_concurrent_tasks,
            max_keepalive_connections=self._max_keepalive_connections,
            max_extraction_workers=self._max_extraction_workers,
            use_pyarrow=True,
            show_tqdm=self._show_tqdm,
            ts_col=ts_col,
        )

        combined = pl.concat([cache_df, new_df]).unique(subset=["report_slice", ts_col]).sort(ts_col)
        _write_intraday_cache(combined, cache_fp)

        return combined.filter((pl.col(ts_col) >= start_timestamp) & (pl.col(ts_col) <= end_timestamp))

    def grab_historical_sdr_trades(
        self,
        start_date: date,
        end_date: date,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        one_df: Optional[bool] = True,
    ):
        all_days = _generate_business_days(start_date, end_date)
        cached_days: Dict[date, pl.DataFrame] = {}
        to_fetch = all_days

        cached_days = _load_daily_dict(all_days, self._parquet_cache_dir, agency=agency, asset_class=asset_class, show_tqdm=self._show_tqdm)
        to_fetch = [d for d in all_days if d not in cached_days]

        fresh: Dict[date, pl.DataFrame] | pl.DataFrame = {}
        if to_fetch:
            fresh = self.dtcc_sdr_fetcher.fetch_historical_reports(
                start_date=min(to_fetch),
                end_date=max(to_fetch),
                agency=agency,
                asset_class=asset_class,
                max_concurrent_tasks=self._max_concurrent_tasks,
                max_keepalive_connections=self._max_keepalive_connections,
                max_extraction_workers=self._max_extraction_workers,
                use_pyarrow=True,
                one_df=False,
                show_tqdm=self._show_tqdm,
            )
            _save_daily_dict(fresh, self._parquet_cache_dir, agency=agency, asset_class=asset_class)

        merged = {**cached_days, **fresh}

        if one_df:
            return _concat_dfs(
                merged.values(),
                use_polars=True,
                show_tqdm=False,
                unique_subset=["Dissemination Identifier"],
                sort_by="Event timestamp",
                chunk_size=1000,
            )

        return merged

    def grab_sdr_trades(
        self,
        start_timestamp: datetime,
        end_timestamp: datetime,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        *,
        ts_col: Literal["Event timestamp", "Execution Timestamp"] = "Event timestamp",
        filter_func: Optional[Callable[[pl.DataFrame], pl.DataFrame]] = lambda df: df,
    ) -> pl.DataFrame:
        # Ensure timestamps are tz-aware
        if start_timestamp.tzinfo is None:
            start_ts = start_timestamp.replace(tzinfo=timezone.utc)
        else:
            start_ts = start_timestamp.astimezone(timezone.utc)

        if end_timestamp.tzinfo is None:
            end_ts = end_timestamp.replace(tzinfo=timezone.utc)
        else:
            end_ts = end_timestamp.astimezone(timezone.utc)

        today_utc = datetime.now(timezone.utc).date()

        hist_start_date = start_ts.date()
        hist_end_date = min(end_ts.date(), today_utc - timedelta(days=1))

        dfs = []

        if hist_start_date <= hist_end_date:
            hist_df = self.grab_historical_sdr_trades(
                start_date=hist_start_date,
                end_date=hist_end_date,
                agency=agency,
                asset_class=asset_class,
                one_df=True,
            )
            if not hist_df.is_empty():
                filtered = hist_df.filter((pl.col(ts_col) >= start_ts) & (pl.col(ts_col) <= end_ts))
                dfs.append(filtered)

        if end_ts.date() >= today_utc:
            intra_start = max(start_ts, datetime.combine(today_utc, datetime.min.time(), tzinfo=timezone.utc))
            intra_df = self.grab_intraday_sdr_trades(
                start_timestamp=intra_start,
                end_timestamp=end_ts,
                agency=agency,
                asset_class=asset_class,
            )
            dfs.append(intra_df)

        if not dfs:
            return pl.DataFrame()

        out = _concat_dfs(
            dfs,
            use_polars=True,
            show_tqdm=False,
            unique_subset=["Dissemination Identifier"],
            sort_by="Event timestamp",
            chunk_size=1000,
            filter_func=filter_func,
        )

        if "report_slice" in out.columns:
            out = out.drop("report_slice")
        return out
