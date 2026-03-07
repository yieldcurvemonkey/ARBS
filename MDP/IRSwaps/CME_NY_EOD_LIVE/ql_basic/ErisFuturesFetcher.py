import asyncio
import calendar
import datetime
import ssl
import warnings
from io import BytesIO
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx
import pandas as pd
import pytz
import QuantLib as ql
import tqdm
import tqdm.asyncio
from dateutil import parser, tz
from pandas.errors import DtypeWarning
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from Caching.DiskCacheMixin import DiskCacheMixin
from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.BaseFetcher import BaseFetcher
from Query.IRSwaps.backends.quantlib.ql_curve_building_utils import build_ql_discount_curve
from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_pydate

warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.simplefilter(action="ignore", category=FutureWarning)

import sys

if sys.platform == "win32":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)


def datetime_today_utc():
    return datetime.date(
        year=datetime.datetime.now(datetime.timezone.utc).year,
        month=datetime.datetime.now(datetime.timezone.utc).month,
        day=datetime.datetime.now(datetime.timezone.utc).day,
    )


def get_bdates_between(start_date: datetime.date, end_date: datetime.date, calendar: ql.Calendar) -> List[datetime.date]:
    bdates = calendar.businessDayList(datetime_to_ql_date(start_date), datetime_to_ql_date(end_date))
    return sorted([ql_date_to_pydate(bd) for bd in bdates])


class ErisFuturesFetcher(DiskCacheMixin, BaseFetcher):
    """
    Adds DiskCache-backed read-through caching for raw ERIS files (CSV/XLSX).
    """

    def __init__(
        self,
        global_timeout: int = 10,
        proxies: Optional[Dict[str, str]] = None,
        debug_verbose: Optional[bool] = False,
        info_verbose: Optional[bool] = False,
        warning_verbose: Optional[bool] = False,
        error_verbose: Optional[bool] = False,
        *,
        cache_path: Optional[str] = None,
        cache_attr: str = "eris_raw",
        force_refresh: bool = False,
    ):
        # Initialize both mixin and base via MRO
        super().__init__(
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose or False,
            info_verbose=info_verbose or False,
            warning_verbose=warning_verbose or False,
            error_verbose=error_verbose or False,
            # DiskCacheMixin args
            use_btree=True,
            force_refresh=force_refresh,
        )

        # --- ERIS endpoint details
        self.eris_ftp_urls = "https://files.erisfutures.com/ftp"
        self.eris_ftp_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
            "DNT": "1",
            "Host": "files.erisfutures.com",
            "Referer": "https://files.erisfutures.com/ftp/",
            "Sec-CH-UA": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        }

        self._cache_attr = cache_attr
        if cache_path is None:
            cache_path = DiskCacheMixin.default_cache_path("ErisFuturesFetcher-raw.fs")

        # mapping: key (str) -> dict(file_name, content: bytes, fetched_at, workbook_type)
        self.open_cache(cache_attr=self._cache_attr, path=cache_path)

    def _cache_key(self, date: Optional[datetime.date], workbook_type: str) -> str:
        if hasattr(date, "date"):  # pandas.Timestamp compatibility
            date = date.date()
        if "Intraday" in workbook_type and date is None:
            return f"{workbook_type}::intraday"
        if date is None:
            return f"{workbook_type}::none"
        return f"{workbook_type}::{date.isoformat()}"

    def _load_cached_raw(
        self,
        date: Optional[datetime.date],
        workbook_type: Literal["EOD_DiscountFactors_SOFR", "EOD_ParCouponCurve_SOFR", "Eris_Intraday_DiscountFactors_SOFR"],
        force_refresh: Optional[bool] = False,
    ) -> Tuple[Optional[BytesIO], Optional[str]]:
        if date is None or "intraday" in workbook_type.lower() or force_refresh:
            return None, None

        try:
            entry = getattr(self, self._cache_attr).get(self._cache_key(date, workbook_type))
            if not entry:
                return None, None
            return BytesIO(entry["content"]), entry["file_name"]
        except Exception as e:
            self._logger.debug(f"Cache load miss/error for {workbook_type}-{date}: {e}")
            return None, None

    def _stage_cache_write(
        self,
        staged: List[Tuple[str, Dict[str, Any]]],
        date: Optional[datetime.date],
        workbook_type: str,
        file_name: str,
        content_bytes: bytes,
    ) -> None:
        key = self._cache_key(date, workbook_type)
        staged.append(
            (
                key,
                {
                    "file_name": file_name,
                    "content": content_bytes,
                    "fetched_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
                    "workbook_type": workbook_type,
                },
            )
        )

    def _commit_staged(self, staged: List[Tuple[str, Dict[str, Any]]]) -> None:
        if not staged:
            return
        mapping = getattr(self, self._cache_attr)
        with self.batched():
            for key, payload in staged:
                mapping[key] = payload

    async def _fetch_eris_ftp_files_helper(
        self,
        client: httpx.AsyncClient,
        date: datetime.date,
        workbook_type: Literal["EOD_DiscountFactors_SOFR", "EOD_ParCouponCurve_SOFR", "Eris_Intraday_DiscountFactors_SOFR"],
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
    ):
        def diff_month(d1, d2):
            return (d1.year - d2.year) * 12 + d1.month - d2.month

        if "Intraday" in workbook_type or date == datetime.date.today():
            eris_ftp_formatted_url = "https://files.erisfutures.com/ftp/Eris_Intraday_DiscountFactors_SOFR.csv"
            file_name = "Eris_Intraday_DiscountFactors_SOFR.csv"
        else:
            archives_path = f"archives/{date.year}/{date.month:02}-{calendar.month_name[date.month]}"
            file_name = f"Eris_{date.strftime('%Y%m%d')}_{workbook_type}.csv"
            if diff_month(datetime.date.today(), date) < 3:
                eris_ftp_formatted_url = f"{self.eris_ftp_urls}/{file_name}"
            else:
                eris_ftp_formatted_url = f"{self.eris_ftp_urls}/{archives_path}/{file_name}"

        retries = 0
        try:
            ssl._create_default_https_context = ssl._create_unverified_context
            while retries < max_retries:
                try:
                    async with client.stream(
                        method="GET",
                        url=eris_ftp_formatted_url,
                        headers=self.eris_ftp_headers,
                        follow_redirects=True,
                        timeout=self._global_timeout,
                    ) as response:
                        response.raise_for_status()
                        buffer = BytesIO()
                        async for chunk in response.aiter_bytes():
                            buffer.write(chunk)
                        buffer.seek(0)
                    return buffer, file_name

                except httpx.HTTPStatusError:
                    self._logger.error(f"ERIS FTP - Bad Status for {workbook_type}-{date}: {response.status_code}")
                    if response.status_code == 404:
                        return None, None
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"ERIS FTP - Throttled. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    self._logger.error(f"ERIS FTP - Error for {workbook_type}-{date}: {e}")
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"ERIS FTP - Throttled. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

            raise ValueError(f"ERIS FTP - Max retries exceeded for {workbook_type}-{date}")

        except Exception as e:
            print(e)
            self._logger.error(e)
            return None, None

    def _read_file(self, file_buffer: BytesIO, file_name: str) -> Tuple[Union[str, datetime.date], pd.DataFrame]:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DtypeWarning)

            if file_name.lower().endswith((".xlsx", ".xls")):
                df = pd.read_excel(file_buffer)
            elif file_name.lower().endswith(".csv"):
                df = pd.read_csv(file_buffer, low_memory=False)
            else:
                return None

            try:
                datetime.datetime.strptime(file_name.split("_")[1], "%Y%m%d").date()
                key = datetime.datetime.strptime(file_name.split("_")[1], "%Y%m%d").date()
            except Exception:
                key = file_name

            return key, df

    async def _fetch_and_read_eris_ftp_file(
        self,
        semaphore: asyncio.Semaphore,
        client: httpx.AsyncClient,
        workbook_type: Literal["EOD_ParCouponCurve_SOFR", "Eris_Intraday_DiscountFactors_SOFR", "EOD_DiscountFactors_SOFR"],
        date: Optional[datetime.date] = None,
        task_id: Optional[Any] = None,
        force_refresh: Optional[bool] = None,
    ):
        async with semaphore:
            if not force_refresh:
                cached_buf, cached_name = self._load_cached_raw(date, workbook_type)
                if cached_buf and cached_name:
                    key, df = await asyncio.to_thread(self._read_file, cached_buf, cached_name)
                    if task_id:
                        return key, df, None, task_id
                    return key, df, None

            buffer, file_name = await self._fetch_eris_ftp_files_helper(client=client, date=date, workbook_type=workbook_type)
            if not buffer or not file_name:
                if task_id:
                    return None, None, None, task_id
                return None, None, None

        raw_bytes = buffer.getvalue()
        key, df = await asyncio.to_thread(self._read_file, BytesIO(raw_bytes), file_name)
        staged = (date, workbook_type, file_name, raw_bytes)

        if task_id:
            return key, df, staged, task_id
        return key, df, staged

    def fetch_eris_ftp_timeseries(
        self,
        start_date: datetime.date,
        end_date: datetime.date,
        workbook_type: Literal["EOD_ParCouponCurve_SOFR", "EOD_DiscountFactors_SOFR"] = "EOD_ParCouponCurve_SOFR",
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        verbose: Optional[bool] = False,
    ) -> Dict[datetime.date, pd.DataFrame]:
        bdates_idx = pd.date_range(start=start_date, end=end_date, freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()))
        dates: List[datetime.date] = [d.date() for d in bdates_idx]

        async def build_tasks(client: httpx.AsyncClient):
            tasks = []
            semaphore = asyncio.Semaphore(max_concurrent_tasks)
            for d in dates:
                task = asyncio.create_task(
                    self._fetch_and_read_eris_ftp_file(
                        semaphore=semaphore,
                        client=client,
                        date=d,
                        workbook_type=workbook_type,
                        force_refresh=self._force_refresh,
                    )
                )
                tasks.append(task)

            return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING ERIS FTP Files...")

        async def run_fetch_all():
            limits = httpx.Limits(
                max_connections=max_concurrent_tasks,
                max_keepalive_connections=max_keepalive_connections,
            )
            async with httpx.AsyncClient(limits=limits, verify=False, http2=True) as client:
                all_data = await build_tasks(client)
                return all_data

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DtypeWarning)
            results = asyncio.run(run_fetch_all())
            if not results:
                print('"fetch_eris_ftp_timeseries" --- empty results') if verbose else None
                return {}

            # Stage cache writes then commit once
            staged: List[Tuple[str, Dict[str, Any]]] = []
            out_pairs: List[Tuple[Union[str, datetime.date], pd.DataFrame]] = []
            for item in results:
                if item is None:
                    continue
                # item = (key, df, staged_or_none)
                key, df, staged_payload = item
                if key is None or df is None:
                    continue
                out_pairs.append((key, df))
                if staged_payload:
                    d, wbt, fname, raw = staged_payload
                    self._stage_cache_write(staged, d, wbt, fname, raw)

            self._commit_staged(staged)
            return dict(out_pairs)

    def fetch_historical_eod_discount_curves(
        self,
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        bdates: Optional[List[datetime.date]] = None,
        ql_dc=ql.Actual360(),
        ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        show_tqdm: Optional[bool] = True,
        interpolation_algo: Optional[
            List[
                Literal[
                    "log_linear",
                    "mono_log_cubic",
                    "natural_cubic",
                    "kruger_log",
                    "natural_log_cubic",
                    "log_mixed_linear",
                    "log_parabolic_cubic",
                    "mono_log_parabolic_cubic",
                ]
            ]
        ] = "log_linear",
        enable_extrapolation: Optional[bool] = False,
        append_intraday: Optional[bool] = False,
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        ignore_cache=False,
        force_refresh=False,
    ) -> Dict[datetime.date, ql.DiscountCurve]:
        assert (start_date and end_date) or bdates, "Must Pass in 'start_date' and 'end_date' or 'bdates'"

        if end_date:
            if end_date == datetime_today_utc().date():
                append_intraday = True

        if not bdates:
            bdates = get_bdates_between(start_date=start_date, end_date=end_date, calendar=ql_cal)

        async def build_tasks(
            client: httpx.AsyncClient,
            dates: List[datetime.date],
        ):
            tasks = []
            semaphore = asyncio.Semaphore(max_concurrent_tasks)
            for date in dates:
                task = asyncio.create_task(
                    self._fetch_and_read_eris_ftp_file(semaphore=semaphore, client=client, date=date, workbook_type="EOD_DiscountFactors_SOFR")
                )
                tasks.append(task)

            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING ERIS HISTORICAL DISC CURVES...")
            return await asyncio.gather(*tasks)

        async def run_fetch_all(
            dates: List[datetime.date],
        ):
            limits = httpx.Limits(
                max_connections=max_concurrent_tasks,
                max_keepalive_connections=max_keepalive_connections,
            )
            async with httpx.AsyncClient(limits=limits, verify=False, http2=True) as client:
                all_data = await build_tasks(
                    client=client,
                    dates=dates,
                )
                return all_data

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DtypeWarning)
            results: List[Tuple[str, pd.DataFrame]] = asyncio.run(
                run_fetch_all(
                    dates=bdates,
                )
            )
            if results is None or len(results) == 0:
                return {}

            staged: List[Tuple[str, Dict[str, Any]]] = []
            dict_ql_discount_curves: Dict[datetime.date, ql.DiscountCurve] = {}

            for item in results:
                if not item:
                    continue
                key, discount_curve_df, staged_payload = item  # key is expected to be a datetime.date for EOD files
                if key is None or discount_curve_df is None:
                    continue
                tday: Optional[datetime.date] = key
                if tday is None:
                    continue  # skip malformed

                if isinstance(key, datetime.date):
                    intraday_ts = pytz.timezone("America/New_York").localize(datetime.datetime(tday.year, tday.month, tday.day, 15, 0))
                else:
                    intraday_ts = datetime.datetime.fromisoformat(
                        str(parser.parse(discount_curve_df["Time"].iloc[0], tzinfos={"EDT": tz.gettz("US/Eastern"), "EST": tz.gettz("US/Eastern")}))
                    ).astimezone(pytz.timezone("America/New_York"))
                    tday = intraday_ts.date()

                discount_curve_df["Date"] = pd.to_datetime(discount_curve_df["Date"], errors="coerce")
                discount_curve_df["DiscountFactor"] = pd.to_numeric(discount_curve_df["DiscountFactor"], errors="coerce")
                ql_curve = build_ql_discount_curve(
                    datetime_series=discount_curve_df["Date"],
                    discount_factor_series=discount_curve_df["DiscountFactor"],
                    ql_dc=ql_dc,
                    ql_cal=ql_cal,
                    interpolation_algo=f"df_{interpolation_algo}",
                )
                if enable_extrapolation:
                    ql_curve.enableExtrapolation()

                dict_ql_discount_curves[tday] = ql_curve

                if staged_payload:
                    d, wbt, fname, raw = staged_payload
                    self._stage_cache_write(staged, d, wbt, fname, raw)

                self._commit_staged(staged)

            if append_intraday:
                dict_ql_discount_curves[datetime_today_utc()] = self.fetch_intraday_discount_curve(
                    ql_dc=ql_dc, ql_cal=ql_cal, show_tqdm=show_tqdm, interpolation_algo=interpolation_algo
                )

            return dict_ql_discount_curves

    def fetch_intraday_discount_curve(
        self,
        return_df: Optional[bool] = False,
        ql_dc=ql.Actual360(),
        ql_cal=ql.UnitedStates(ql.UnitedStates.GovernmentBond),
        show_tqdm: Optional[bool] = True,
        interpolation_algo: Optional[
            List[
                Literal[
                    "log_linear",
                    "mono_log_cubic",
                    "natural_cubic",
                    "kruger_log",
                    "natural_log_cubic",
                    "log_mixed_linear",
                    "log_parabolic_cubic",
                    "mono_log_parabolic_cubic",
                ]
            ]
        ] = "log_linear",
        enable_extrapolation: Optional[bool] = True,
        return_intraday_timestamp: Optional[bool] = True,
        ignore_cache=False,
        force_refresh=False,
    ) -> ql.DiscountCurve | pd.DataFrame | Tuple[ql.DiscountCurve, datetime.date]:
        async def build_tasks(
            client: httpx.AsyncClient,
        ):
            semaphore = asyncio.Semaphore(1)
            tasks = [
                asyncio.create_task(
                    self._fetch_and_read_eris_ftp_file(semaphore=semaphore, client=client, date=None, workbook_type="Eris_Intraday_DiscountFactors_SOFR")
                )
            ]
            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING ERIS INTRADAY DISC CURVE...")
            return await asyncio.gather(*tasks)

        async def run_fetch_all():
            limits = httpx.Limits(
                max_connections=1,
                max_keepalive_connections=1,
            )
            async with httpx.AsyncClient(limits=limits, verify=False, http2=True) as client:
                all_data = await build_tasks(client=client)
                return all_data

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DtypeWarning)
            results: List[Tuple[str, pd.DataFrame]] = asyncio.run(run_fetch_all())
            if results is None or len(results) == 0:
                return {}

            discount_curve_df = dict([results[0][:-1]])["Eris_Intraday_DiscountFactors_SOFR.csv"]
            discount_curve_df["Date"] = pd.to_datetime(discount_curve_df["Date"], errors="coerce")
            discount_curve_df["DiscountFactor"] = pd.to_numeric(discount_curve_df["DiscountFactor"], errors="coerce")
            if return_df:
                return discount_curve_df

            ql_discount_curve = build_ql_discount_curve(
                datetime_series=discount_curve_df["Date"],
                discount_factor_series=discount_curve_df["DiscountFactor"],
                ql_dc=ql_dc,
                ql_cal=ql_cal,
                interpolation_algo=f"df_{interpolation_algo}",
            )
            if enable_extrapolation:
                ql_discount_curve.enableExtrapolation()

            if return_intraday_timestamp:
                intraday_ts = datetime.datetime.fromisoformat(
                    str(parser.parse(discount_curve_df["Time"].iloc[0], tzinfos={"EDT": tz.gettz("US/Eastern"), "EST": tz.gettz("US/Eastern")}))
                )
                intraday_ts = intraday_ts.astimezone(pytz.timezone("America/New_York"))

                return ql_discount_curve, intraday_ts

            return ql_discount_curve
