import asyncio
import datetime
import re
import sys
import warnings
from io import BytesIO
from typing import Dict, List, Literal, Optional, Tuple, Union

import httpx
import pandas as pd
import pyarrow
import pyarrow.csv
import QuantLib as ql
import tqdm.asyncio
from dateutil.relativedelta import relativedelta
from pandas.errors import DtypeWarning
from pandas.tseries.offsets import BDay

from Caching.ZODBCacheMixin import ZODBCacheMixin
from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.BaseFetcher import BaseFetcher
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_ql_discount_curve, build_ql_zero_curve

warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.simplefilter(action="ignore", category=FutureWarning)

import sys

if sys.platform == "win32":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)


def is_business_day(date: pd.Timestamp | datetime.date):
    return bool(len(pd.bdate_range(date, date)))


class CMEFetcher(BaseFetcher, ZODBCacheMixin):
    _base_cme_ftp_url = "https://www.cmegroup.com/ftp"
    _base_cme_ftp_headers = {
        "authority": "www.cmegroup.com",
        "scheme": "https",
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": "en-US,en;q=0.9",
        "dnt": "1",
        "priority": "u=0, i",
        "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    }

    # _curve_report_cache: Dict[datetime, pd.DataFrame] = {}

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        warning_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
    ):
        BaseFetcher.__init__(
            self,
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )
        ZODBCacheMixin.__init__(self)

    def _ensure_cache(self):
        cache_path = ZODBCacheMixin.default_cache_path("CMEFetcher_curve_reports")
        self.zodb_open_cache(
            cache_attr="_curve_report_cache",
            path=cache_path,
            encode=None,
            decode=None,
        )

    def _build_cme_ftp_request_headers(
        self, method: Optional[Literal["GET", "POST", "PUT", "DELETE"]] = None, path: Optional[str] = None, referer: Optional[str] = None
    ) -> Dict[str, str]:
        req_headers = self._base_cme_ftp_headers.copy()
        if method:
            req_headers["method"] = method
        if path:
            req_headers["path"] = path
        if referer:
            req_headers["referer"] = referer
        return req_headers

    # builds eod curve report path and headers
    def _build_eod_curve_report_path(
        self,
        curve_date: datetime.date,
        use_eod_report: Optional[bool] = True,
        auto_check_archives: Optional[bool] = True,
        check_archives_mannual: Optional[bool] = False,
    ) -> Tuple[str, Dict[str, str]]:
        most_recent_bday = (
            datetime.date.today() if is_business_day(datetime.date.today()) else datetime.date.today() - BDay(1)
        )  # CME FTP doesn't necessarily follow any cal

        curve_report_filename = "CME_Curve_Report_EOD" if use_eod_report else "CME_Curve_Report"
        if auto_check_archives:
            archival_date = most_recent_bday - relativedelta(months=1)
            is_in_archive = pd.Timestamp(curve_date) < pd.Timestamp(archival_date)
        else:
            is_in_archive = check_archives_mannual

        if is_in_archive:
            ftp_path = f"/span/archive/cme/irs/{curve_date.year}/{curve_report_filename}_{curve_date.strftime("%Y%m%d")}.csv"
        else:
            ftp_path = f"/span/data/cme/irs/{curve_report_filename}_{curve_date.strftime("%Y%m%d")}.csv"

        url = f"{self._base_cme_ftp_url}{ftp_path}"
        return url, self._build_cme_ftp_request_headers(method="GET", path=ftp_path, referer=url.rpartition("/")[0]), is_in_archive

    async def _fetch_cme_ftp_eod_curve_report_helper(
        self,
        client: httpx.AsyncClient,
        curve_date: datetime.date,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
    ) -> Optional[BytesIO]:
        curve_report_url, curve_report_header, is_in_archive = self._build_eod_curve_report_path(curve_date=curve_date, use_eod_report=False)

        retries = 0
        while retries < max_retries:
            try:
                async with client.stream("GET", curve_report_url, headers=curve_report_header, timeout=self._global_timeout) as response:
                    response.raise_for_status()
                    zip_buffer = BytesIO()
                    async for chunk in response.aiter_bytes():
                        zip_buffer.write(chunk)
                    zip_buffer.seek(0)
                return zip_buffer

            except httpx.HTTPStatusError as e:
                # flip is_in_archive state
                curve_report_url, curve_report_header, _ = self._build_eod_curve_report_path(
                    curve_date=curve_date, auto_check_archives=False, check_archives_mannual=not is_in_archive
                )
                self._logger.debug(f"CMEFetcher EOD Curve Report - HTTP Error Flipping 'is_in_archive' state")

                # attempt exponential backoff
                retries += 1
                wait_time = backoff_factor * (2 ** (retries - 1))
                self._logger.debug(f"CMEFetcher EOD Curve Report - HTTP Error {e.response.status_code} for {curve_date}. " f"Retrying in {wait_time}s... {e}")
                await asyncio.sleep(wait_time)

            except (httpx.RequestError, Exception) as e:
                retries += 1
                wait_time = backoff_factor * (2 ** (retries - 1))
                self._logger.debug(f"CMEFetcher EOD Curve Report - Connection/Other Error for {curve_date}. " f"Retrying in {wait_time}s... {e}")
                await asyncio.sleep(wait_time)

        self._logger.error(f"CMEFetcher - Max retries exceeded for {curve_date}.")
        return None

    def _parse_curve_report_file_name_to_datetime(self, file_name: str) -> datetime.date:
        """
        Curve Report File name examples:
        CME_Curve_Report_20250121.csv
        CME_Curve_Report_EOD_20250102.csv
        """
        if "csv" in file_name:
            match = re.search(r"(\d{8})(?=\.csv$)", file_name)
        elif "xls" in file_name:
            match = re.search(r"(\d{8})(?=\.xls$)", file_name)
        elif "xlsx" in file_name:
            match = re.search(r"(\d{8})(?=\.xlsx$)", file_name)
        else:
            raise ValueError(f"Invalid File name: {file_name}")

        if not match:
            raise ValueError(f"File name does not contain a valid date: {file_name}")
        date_str = match.group(1)
        year = int(date_str[:4])
        month = int(date_str[4:6])
        day = int(date_str[6:8])
        return datetime.date(year, month, day)

    def _read_single_file(
        self,
        file_buffer: bytes,
        file_name: str,
        convert_key_into_dt: bool,
        use_pyarrow: Optional[bool] = False,
    ) -> Tuple[Optional[Union[str, datetime.date]], Optional[pd.DataFrame]]:
        file_name_lower = file_name.lower()
        extension = None
        if file_name_lower.endswith((".xls", ".xlsx")):
            extension = "excel"
        elif file_name_lower.endswith(".csv"):
            extension = "csv"
        else:
            return None, None

        buffer_io = BytesIO(file_buffer)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DtypeWarning)
            if extension == "excel":
                df = pd.read_excel(buffer_io)
            else:  # csv
                if use_pyarrow:
                    try:
                        table: pyarrow.Table = pyarrow.csv.read_csv(buffer_io)
                        df = table.to_pandas()
                    except ImportError:
                        df = pd.read_csv(buffer_io, low_memory=False)
                else:
                    df = pd.read_csv(buffer_io, low_memory=False)

        key = file_name
        if convert_key_into_dt:
            try:
                key = self._parse_curve_report_file_name_to_datetime(file_name)
            except ValueError:
                pass

        return key, df

    def _partition_cached_dates(self, dates: List[datetime.date]) -> Tuple[Dict[datetime.date, pd.DataFrame], List[datetime.date]]:
        cached, missing = {}, []
        cache = self._curve_report_cache
        for d in dates:
            if isinstance(d, datetime.datetime):
                continue
            if d in cache:
                cached[d] = cache[d]
            else:
                missing.append(d)
        return cached, missing

    async def _fetch_and_store(self, client: httpx.AsyncClient, curve_date: datetime.date) -> None:
        buf = await self._fetch_cme_ftp_eod_curve_report_helper(client, curve_date)
        if buf:
            url, _, _ = self._build_eod_curve_report_path(curve_date)
            file_name = url.split("/")[-1]
            key, df = self._read_single_file(buf.getvalue(), file_name, convert_key_into_dt=True)
            if key and df is not None:
                self._curve_report_cache[key] = df
                self.zodb_commit()

    def fetch_curve_reports(
        self,
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        bdates: Optional[List[datetime.date]] = None,
        show_tqdm: Optional[bool] = False,
        max_connections: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        ignore_cache: Optional[bool] = False,
    ) -> Dict[datetime.date, pd.DataFrame]:
        self._ensure_cache()
        dates = bdates or pd.date_range(start_date, end_date, freq="B").to_pydatetime().tolist()

        if ignore_cache:
            cached_part, to_fetch = {}, dates
        else:
            cached_part, to_fetch = self._partition_cached_dates(dates)

        cached_part, to_fetch = self._partition_cached_dates(dates)
        results = dict(cached_part)

        if to_fetch:
            limits = httpx.Limits(
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
            )

            async def runner():
                async with httpx.AsyncClient(
                    limits=limits,
                    timeout=self._global_timeout,
                    mounts=self._httpx_proxies,
                    verify=False,
                    http2=True,
                ) as client:
                    tasks = [self._fetch_and_store(client, d) for d in to_fetch]
                    for coro in tqdm.tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Fetching Reports") if show_tqdm else asyncio.as_completed(tasks):
                        await coro

            asyncio.run(runner())

            for d in to_fetch:
                if d in self._curve_report_cache:
                    results[d] = self._curve_report_cache[d]

        self.close_zodb()
        return results

    def build_ql_eod_curves(
        self,
        curve: Literal[
            "USD-SOFR-1D",
            "USD-FEDFUNDS",
            "USD-OIS",
            "JPY-TONAR",
            "CAD-CORRA",
            "EUR-ESTR",
            "EUR-EURIBOR-1M",
            "EUR-EURIBOR-3M",
            "EUR-EURIBOR-6M",
            "GBP-SONIA",
            "CHF-SARON-1D",
            "NOK-NIBOR-6M",
            "HKD-HIBOR-3M",
            "AUD-AONIA",
            "SGD-SORA-1D",
        ],
        type: Literal["Zero", "Df"],
        ql_day_count: ql.DayCounter,
        ql_calendar: ql.Calendar,
        date_col: Optional[str] = "Date",
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        bdates: Optional[List[datetime.date]] = None,
        interpolation_algo: Optional[
            List[
                Literal[
                    "linear",
                    "log_linear",
                    "cubic",
                    "log_cubic",
                    "mono_log_cubic",
                    "natural_cubic",
                    "kruger_log",
                    "natural_log_cubic",
                    "log_mixed_linear",
                    "log_parabolic_cubic",
                    "mono_log_parabolic_cubic",
                    "monotonic_cubic",
                    "kruger",
                    "parabolic_cubic",
                    "monotonic_parabolic_cubic",
                ]
            ]
        ] = "log_linear",
        enable_extrapolation: Optional[bool] = False,
        show_tqdm: Optional[bool] = False,
        max_connections: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        ignore_cache: Optional[bool] = False,
    ) -> Dict[datetime.date, ql.DiscountCurve | ql.ZeroCurve]:
        assert (start_date and end_date) or bdates, "Must Pass in 'start_date' and 'end_date' or 'bdates'"

        cme_eod_curve_reports_dict_df = self.fetch_curve_reports(
            start_date=start_date,
            end_date=end_date,
            bdates=bdates,
            show_tqdm=show_tqdm,
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            ignore_cache=ignore_cache,
        )

        ql_curves_dict: Dict[datetime.date, ql.DiscountCurve | ql.ZeroCurve] = {}
        curve_iter = (
            tqdm.tqdm(cme_eod_curve_reports_dict_df.items(), desc=f"BUILDING {curve} {"DISCOUNT" if type.lower() == "df" else "ZERO"} CURVES..")
            if show_tqdm
            else cme_eod_curve_reports_dict_df.items()
        )
        for curve_date, curve_report_df in curve_iter:
            curve_report_df.columns = [x.lower() for x in curve_report_df.columns]

            try:
                curve_report_df = curve_report_df[curve_report_df["curve name"] == curve]
                if curve_report_df.empty:
                    ql_curves_dict[curve_date] = None
                    self._logger.error(f"No data from {curve} on {curve_date}")
                    continue

                curve_report_df[date_col] = pd.to_datetime(curve_report_df[date_col], format="%m/%d/%Y", errors="coerce")
                curve_report_df = curve_report_df.sort_values(by=[date_col])
                curve_report_df[type.lower()] = pd.to_numeric(curve_report_df[type.lower()], errors="coerce")

                datetime_series = curve_report_df[date_col].reset_index(drop=True).copy()
                type_series = curve_report_df[type.lower()].reset_index(drop=True).copy()

                if not curve_date in datetime_series and type.lower() == "df":
                    datetime_series = pd.concat([pd.Series([curve_date]), datetime_series])
                    type_series = pd.concat([pd.Series([1]), type_series])

                ql_curve_build_func = build_ql_discount_curve if type.lower() == "df" else build_ql_zero_curve
                ql_curve = ql_curve_build_func(
                    datetime_series,
                    type_series,
                    ql_day_count,
                    ql_calendar,
                    interpolation_algo,
                )
                if enable_extrapolation:
                    ql_curve.enableExtrapolation()

                ql_curves_dict[curve_date] = ql_curve
            except Exception as e:
                self._logger.error(f"Error when building Quantlib Curve for CME {curve} on {curve_date}: {e}")

        return ql_curves_dict
