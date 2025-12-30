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
import pandas as pd
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import pyzipper
import requests
import tqdm
import tqdm.asyncio
import ujson
from pandas.errors import DtypeWarning
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay


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
    ) -> Tuple[Optional[Union[str, datetime]], Optional[pd.DataFrame]]:
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
            warnings.simplefilter("ignore", DtypeWarning)
            if extension == "excel":
                df = pd.read_excel(buffer_io)
            else:  # csv
                if use_pyarrow:
                    try:
                        table = pacsv.read_csv(buffer_io)
                        df = table.to_pandas()
                    except ImportError:
                        df = pd.read_csv(buffer_io, low_memory=False)
                else:
                    df = pd.read_csv(buffer_io, low_memory=False)

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
    ) -> Dict[Union[str, datetime], pd.DataFrame]:
        if not zip_buffer:
            return {}

        dataframes: Dict[Union[str, datetime], pd.DataFrame] = {}
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
    ) -> Dict[Union[str, datetime], pd.DataFrame]:
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
    ) -> List[Dict[Union[str, datetime], pd.DataFrame]]:
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
    ) -> Dict[date, pd.DataFrame] | pd.DataFrame:
        bdates = pd.date_range(
            start=start_date,
            end=end_date,
            freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()),
        )
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
        merged_data: Dict[date, pd.DataFrame] = {}
        for daily_dict in all_results:
            for k, v_df in daily_dict.items():
                k = k.date()
                if isinstance(k, date) and isinstance(v_df, pd.DataFrame):
                    v_df["Event timestamp"] = pd.to_datetime(v_df["Event timestamp"], errors="coerce", utc=True)
                    v_df["Execution Timestamp"] = pd.to_datetime(v_df["Execution Timestamp"], errors="coerce", utc=True)
                    v_df["Effective Date"] = pd.to_datetime(v_df["Effective Date"], errors="coerce")
                    v_df["Expiration Date"] = pd.to_datetime(v_df["Expiration Date"], errors="coerce")
                    v_df = v_df.sort_values(by=ts_col)
                    v_df = v_df[(v_df[ts_col].dt.date >= start_date) & (v_df[ts_col].dt.date <= end_date)]
                    merged_data[k] = v_df

        if len(merged_data.keys()) == 0:
            return pd.DataFrame([])

        if one_df:
            return pd.concat(merged_data.values())
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
    ) -> pd.DataFrame:
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
        combined_results: Dict[str, pd.DataFrame] = {}
        for res_dict in all_results:
            combined_results.update(res_dict)  # merges each slice's data

        if not combined_results:
            return pd.DataFrame()

        list_of_dfs = []
        for slice_id_str, df in combined_results.items():
            df = df.copy()
            df["report_slice"] = slice_id_str
            list_of_dfs.append(df)

        combined_df = pd.concat(list_of_dfs, ignore_index=True)
        combined_df["Event timestamp"] = pd.to_datetime(combined_df["Event timestamp"], errors="coerce", utc=True)
        combined_df["Execution Timestamp"] = pd.to_datetime(combined_df["Execution Timestamp"], errors="coerce", utc=True)
        combined_df["Effective Date"] = pd.to_datetime(combined_df["Effective Date"], errors="coerce")
        combined_df["Expiration Date"] = pd.to_datetime(combined_df["Expiration Date"], errors="coerce")
        combined_df = combined_df.sort_values(by=ts_col)

        if start_timestamp:
            combined_df = combined_df[combined_df[ts_col] >= start_timestamp]
        if end_timestamp:
            combined_df = combined_df[combined_df[ts_col] <= end_timestamp]

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
    ) -> pd.DataFrame:
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
            sdr_df = pd.concat([historical_sdr_df, intraday_sdr_df])
        else:
            sdr_df = historical_sdr_df

        if sdr_df.empty:
            return pd.DataFrame([])

        sdr_df.replace(["", " ", None, "None", "NaN"], np.nan, inplace=True)
        return sdr_df.sort_values(by="Event timestamp").reset_index(drop=True)

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
        intraday_report_ids_df = pd.DataFrame(intraday_report_ids)
        intraday_report_ids_df["dissemDTM"] = pd.to_datetime(intraday_report_ids_df["dissemDTM"], errors="coerce", utc=True)
        if start_timestamp:
            start_timestamp = pd.to_datetime(start_timestamp, utc=True)
            intraday_report_ids_df = intraday_report_ids_df[intraday_report_ids_df["dissemDTM"] >= start_timestamp]
        if end_timestamp:
            end_timestamp = pd.to_datetime(end_timestamp, utc=True)
            intraday_report_ids_df = intraday_report_ids_df[intraday_report_ids_df["dissemDTM"] <= end_timestamp]

        return [str(row["fileName"]).split(f"_{asset_class}_")[1].split(".")[0] for _, row in intraday_report_ids_df.iterrows()]


def _df_to_parquet(df: pd.DataFrame, path: Path, *, compression: Optional[str] = "zstd"):
    path.parent.mkdir(parents=True, exist_ok=True)
    tbl = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(tbl, path, compression=compression)


def _save_daily_dict(
    data: Dict[date, pd.DataFrame],
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
) -> Dict[date, pd.DataFrame]:
    base = Path(base_dir)
    out: Dict[date, pd.DataFrame] = {}

    if show_tqdm:
        from tqdm import tqdm

        to_iter = tqdm(dates, desc="CACHE HIT...")
    else:
        to_iter = dates

    for d in to_iter:
        fp = base / agency / asset_class / f"{d.year:04d}" / f"{d.month:02d}" / f"{d}.parquet"
        if fp.exists():
            out[d] = pd.read_parquet(fp, engine="pyarrow")
    return out


def _read_intraday_cache(fp: Path) -> pd.DataFrame:
    if not fp.is_file():
        return pd.DataFrame()

    try:
        return pd.read_csv(
            fp,
            parse_dates=[
                "Event timestamp",
                "Execution Timestamp",
                "Effective Date",
                "Expiration Date",
            ],
            infer_datetime_format=True,
            low_memory=False,
        )
    except Exception:
        _clear_file(fp)
        return pd.DataFrame()


def _clear_file(fp: Path) -> None:
    try:
        if fp.exists():
            fp.unlink()
    except Exception:
        # If deletion fails for any reason, just ignore and fall back to ignoring the file content
        pass


def _write_intraday_cache(df: pd.DataFrame, fp: Path):
    fp.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(fp, index=False)


def _batch_convert_to_polars(frames: List[pd.DataFrame], pl) -> List:
    """
    Batch convert pandas DataFrames to polars with minimal overhead.
    Uses schema inference from first frame, applies to all.
    """
    if not frames:
        return []

    def _infer_schema_fast(df: pd.DataFrame, pl) -> dict:
        """
        Fast schema inference - O(columns) not O(columns * rows).
        Only checks dtype, not cell contents.
        """
        schema = {}
        for col in df.columns:
            dtype = df[col].dtype

            if pd.api.types.is_datetime64_any_dtype(dtype):
                # Let polars handle datetime inference
                continue
            elif pd.api.types.is_bool_dtype(dtype):
                schema[col] = pl.Boolean
            elif pd.api.types.is_integer_dtype(dtype):
                schema[col] = pl.Int64
            elif pd.api.types.is_float_dtype(dtype):
                schema[col] = pl.Float64
            elif pd.api.types.is_string_dtype(dtype) or dtype == "string":
                schema[col] = pl.Utf8
            elif pd.api.types.is_object_dtype(dtype):
                # Object dtype -> string (safest)
                schema[col] = pl.Utf8
            elif pd.api.types.is_categorical_dtype(dtype):
                schema[col] = pl.Utf8

        return schema

    def _coerce_to_string_fallback(df: pd.DataFrame) -> pd.DataFrame:
        """
        Fallback: coerce all object columns to string.
        Only called on conversion failure.
        """
        df = df.copy()
        for col in df.columns:
            if pd.api.types.is_object_dtype(df[col].dtype):
                df[col] = df[col].astype(str)
        return df

    # Infer schema from first non-empty frame
    ref_df = frames[0]
    schema_overrides = _infer_schema_fast(ref_df, pl)

    pl_frames = []
    for df in frames:
        try:
            # Fast path: direct conversion with pre-computed schema
            plf = pl.from_pandas(
                df,
                schema_overrides=schema_overrides,
                nan_to_null=True,
                include_index=False,
            )
            pl_frames.append(plf)
        except Exception:
            # Fallback: coerce problematic columns to string
            df_clean = _coerce_to_string_fallback(df)
            plf = pl.from_pandas(df_clean, nan_to_null=True, include_index=False)
            pl_frames.append(plf)

    return pl_frames


def _concat_dfs(
    frames: Iterable[pd.DataFrame],
    *,
    unique_subset: Optional[List[str]] = None,
    sort_by: Optional[str] = None,
    use_polars: bool = False,  # kept for signature compatibility; this impl prioritizes speed
    show_tqdm: bool = True,
    tqdm_desc: Optional[str] = None,
    chunk_size: Optional[int] = 256,  # kept for signature compatibility
    filter_func: Optional[Callable[[pd.DataFrame], Union[pd.DataFrame, pd.Series]]] = None,
) -> pd.DataFrame:
    """
    Hyper-optimized drop-in replacement.

    Optimizations:
    - One-pass iteration over frames (no extra intermediate lists unless needed)
    - Applies filter per-frame (reduces early)
    - Streaming global de-dup when unique_subset is a single column (fast + memory efficient)
    - Avoids pandas<->polars conversion overhead (often the real bottleneck)
    - Robust handling when filter_func returns a bool Series with a mismatched index
    """
    # Fast exit
    it = (f for f in frames if f is not None and not f.empty)
    frames_list = list(it)
    if not frames_list:
        return pd.DataFrame()

    # Fast path: single frame
    if len(frames_list) == 1:
        df = frames_list[0]
        if filter_func is not None:
            res = filter_func(df)
            if isinstance(res, pd.DataFrame):
                df = res
            else:
                # bool mask: align safely (by position if needed)
                m = res
                if isinstance(m, pd.Series):
                    if (len(m) == len(df)) and (not m.index.equals(df.index)):
                        m = m.to_numpy(dtype=bool, na_value=False)
                    else:
                        m = m.reindex(df.index, fill_value=False).to_numpy(dtype=bool, na_value=False)
                else:
                    m = np.asarray(m, dtype=bool)
                df = df.iloc[m]

        if unique_subset:
            cols = [c for c in unique_subset if c in df.columns]
            if cols:
                df = df.drop_duplicates(subset=cols, keep="first")

        if sort_by and sort_by in df.columns:
            df = df.sort_values(by=sort_by, kind="mergesort")

        return df.reset_index(drop=True)

    # tqdm over frames (cheap; counts frames not rows)
    if show_tqdm:
        # auto-picks notebook/terminal backend; avoid "too fast to render" throttling
        from tqdm import tqdm

        # iterator = tqdm(
        #     frames_list,
        #     desc=tqdm_desc or "CONCAT...",
        #     total=len(frames_list),  # optional; explicit is fine
        #     miniters=1,  # update every iteration
        #     mininterval=0.0,  # render even if loop is very fast
        #     smoothing=0,  # avoid additional throttling
        #     dynamic_ncols=True,
        #     leave=True,  # keep final bar visible
        # )
        iterator = tqdm(frames_list, total=len(frames_list), desc=tqdm_desc or "CONCAT...")
    else:
        iterator = frames_list

    # If de-dup key is exactly one existing column, do streaming global de-dup (fastest path)
    key_col: Optional[str] = None
    if unique_subset:
        tmp = [c for c in unique_subset]
        if len(tmp) == 1:
            key_col = tmp[0]

    kept: List[pd.DataFrame] = []

    if key_col is not None:
        seen = set()
        seen_nan = False  # match drop_duplicates semantics for NaN (treat NaN as duplicate)

        for df in iterator:
            # Apply filter_func early
            if filter_func is not None:
                res = filter_func(df)
                if isinstance(res, pd.DataFrame):
                    df = res
                else:
                    m = res
                    if isinstance(m, pd.Series):
                        if (len(m) == len(df)) and (not m.index.equals(df.index)):
                            m = m.to_numpy(dtype=bool, na_value=False)
                        else:
                            m = m.reindex(df.index, fill_value=False).to_numpy(dtype=bool, na_value=False)
                    else:
                        m = np.asarray(m, dtype=bool)
                    df = df.iloc[m]

            if df is None or df.empty:
                continue

            if key_col not in df.columns:
                kept.append(df)
                continue

            # De-dup within-frame first (cheap reduction)
            df = df.drop_duplicates(subset=[key_col], keep="first")

            s = df[key_col]

            # Handle NaN as duplicate (drop_duplicates treats NaNs as equal)
            if s.isna().any():
                if seen_nan:
                    df = df.loc[~s.isna()]
                    if df.empty:
                        continue
                else:
                    nan_part = df.loc[s.isna()].head(1)
                    non_nan = df.loc[~s.isna()]
                    df = pd.concat([nan_part, non_nan], ignore_index=False, copy=False)
                    seen_nan = True
                    if df.empty:
                        continue
                s = df[key_col]

            # Global streaming de-dup
            if seen:
                m_keep = ~s.isin(seen)
                if not m_keep.all():
                    df = df.loc[m_keep]
                    if df.empty:
                        continue
                    s = df[key_col]

            # Update seen with unique values from this frame
            vals = s.dropna().unique()
            if len(vals):
                seen.update(vals.tolist())

            kept.append(df)

        if not kept:
            return pd.DataFrame()

        out = kept[0] if len(kept) == 1 else pd.concat(kept, ignore_index=True, copy=False)

        # No need to drop_duplicates again for single-key path (already enforced)
        if sort_by and sort_by in out.columns:
            out = out.sort_values(by=sort_by, kind="mergesort")

        return out.reset_index(drop=True)

    # Fallback: general case (multi-col unique_subset or no unique_subset)
    for df in iterator:
        if filter_func is not None:
            res = filter_func(df)
            if isinstance(res, pd.DataFrame):
                df = res
            else:
                m = res
                if isinstance(m, pd.Series):
                    if (len(m) == len(df)) and (not m.index.equals(df.index)):
                        m = m.to_numpy(dtype=bool, na_value=False)
                    else:
                        m = m.reindex(df.index, fill_value=False).to_numpy(dtype=bool, na_value=False)
                else:
                    m = np.asarray(m, dtype=bool)
                df = df.iloc[m]

        if df is not None and not df.empty:
            kept.append(df)

    if not kept:
        return pd.DataFrame()

    out = kept[0] if len(kept) == 1 else pd.concat(kept, ignore_index=True, copy=False)

    if unique_subset:
        cols = [c for c in unique_subset if c in out.columns]
        if cols:
            out = out.drop_duplicates(subset=cols, keep="first")

    if sort_by and sort_by in out.columns:
        out = out.sort_values(by=sort_by, kind="mergesort")

    return out.reset_index(drop=True)


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
    ) -> pd.DataFrame:
        start_timestamp = pd.to_datetime(start_timestamp, utc=True)
        end_timestamp = pd.to_datetime(end_timestamp, utc=True)

        cache_fp = self._parquet_cache_dir / "intraday.csv"
        cache_df = _read_intraday_cache(cache_fp)
        ts_col = "Event timestamp"

        if not cache_df.empty and self._intraday_cache_ttl is not None:
            try:
                last_cached = pd.to_datetime(cache_df[ts_col]).max()
            except Exception:
                # If the column is missing or unparsable, nuke the cache
                _clear_file(cache_fp)
                cache_df = pd.DataFrame()
            else:
                now_utc = datetime.now(timezone.utc)
                if (now_utc - last_cached) > self._intraday_cache_ttl:
                    _clear_file(cache_fp)
                    cache_df = pd.DataFrame()

        if cache_df.empty:
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
            result_df = cache_df[(cache_df[ts_col] >= start_timestamp) & (cache_df[ts_col] <= end_timestamp)].copy()
            return result_df.reset_index(drop=True)

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

        combined = pd.concat([cache_df, new_df], ignore_index=True).drop_duplicates(subset=["report_slice", ts_col]).sort_values(by=ts_col)
        _write_intraday_cache(combined, cache_fp)

        return combined[(combined[ts_col] >= start_timestamp) & (combined[ts_col] <= end_timestamp)].reset_index(drop=True)

    def grab_historical_sdr_trades(
        self,
        start_date: date,
        end_date: date,
        agency: Literal["CFTC", "SEC"],
        asset_class: Literal["COMMODITIES", "CREDITS", "EQUITIES", "FOREX", "RATES"],
        one_df: Optional[bool] = True,
    ):
        all_days = list(pd.date_range(start=start_date, end=end_date, freq=CustomBusinessDay(calendar=USFederalHolidayCalendar())).date)
        cached_days: Dict[date, pd.DataFrame] = {}
        to_fetch = all_days

        cached_days = _load_daily_dict(all_days, self._parquet_cache_dir, agency=agency, asset_class=asset_class, show_tqdm=self._show_tqdm)
        to_fetch = [d for d in all_days if d not in cached_days]

        fresh: Dict[date, pd.DataFrame] | pd.DataFrame = {}
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
            # return pd.concat(merged.values(), copy=False)
            # return _concat_dfs(list(merged.values()), use_polars=self._use_polars)
            return _concat_dfs(
                merged.values(),
                use_polars=True,
                # show_tqdm=False,
                show_tqdm=self._show_tqdm,
                tqdm_desc="MERGING REPORTS...",
                # unique_subset=["report_slice", "Event timestamp"],
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
        filter_func: Optional[Callable[[pd.DataFrame], pd.DataFrame]] = lambda df: df,
    ) -> pd.DataFrame:
        # TODO convert this to utc
        start_ts = pd.to_datetime(start_timestamp, utc=True)
        end_ts = pd.to_datetime(end_timestamp, utc=True)

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
            if not hist_df.empty:
                mask = (hist_df[ts_col] >= start_ts) & (hist_df[ts_col] <= end_ts)
                dfs.append(hist_df.loc[mask])

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
            return pd.DataFrame()

        # out = pd.concat(dfs, ignore_index=True).sort_values(by=ts_col).reset_index(drop=True)
        # out = _concat_dfs(dfs, sort_by=ts_col, use_polars=self._use_polars)
        out = _concat_dfs(
            dfs,
            use_polars=True,
            # show_tqdm=self._show_tqdm,
            # tqdm_desc="MERGING REPORTS...",
            show_tqdm=True,
            # unique_subset=["report_slice", "Event timestamp"],
            unique_subset=["Dissemination Identifier"],
            sort_by="Event timestamp",
            chunk_size=2500,
            filter_func=filter_func,
        )

        if "report_slice" in out.columns:
            out = out.drop(columns=["report_slice"])
        return out
