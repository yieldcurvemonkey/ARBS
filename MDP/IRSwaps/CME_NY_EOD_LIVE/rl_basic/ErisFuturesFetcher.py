import asyncio
import calendar
import datetime
import logging
import ssl
import warnings
from io import BytesIO
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx
import pandas as pd
import pytz
import rateslib as rl
import QuantLib as ql
import tqdm
import tqdm.asyncio
from dateutil import parser, tz
from pandas.errors import DtypeWarning
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_pydate
from MDP.IRSwaps.SDR_INTRADAY.rl_curve_utils.stir_curve_building_utils import (
    get_fomc_meetings_list,
    get_short_end_curve_tickers,
)

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


class ErisFuturesFetcher(BaseFetcher):
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

    async def _fetch_eris_ftp_files_helper(
        self,
        client: httpx.AsyncClient,
        date: datetime.date,
        workbook_type: Literal["EOD_ParCouponCurve_SOFR", "Eris_Intraday_DiscountFactors_SOFR"],
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
    ):
        def diff_month(d1, d2):
            return (d1.year - d2.year) * 12 + d1.month - d2.month

        if "Intraday" in workbook_type:
            eris_ftp_formatted_url = "https://files.erisfutures.com/ftp/Eris_Intraday_DiscountFactors_SOFR.csv"
            file_name = "Eris_Intraday_DiscountFactors_SOFR.csv"
        else:
            archives_path = f"archives/{date.year}/{date.month:02}-{calendar.month_name[date.month]}"
            file_name = f"Eris_{date.strftime("%Y%m%d")}_{workbook_type}.csv"
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

                except httpx.HTTPStatusError as e:
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
                datetime.datetime.strptime(file_name.split("_")[1], "%Y%m%d")
                key = datetime.datetime.strptime(file_name.split("_")[1], "%Y%m%d")
            except:
                key = file_name

            return key, df

    async def _fetch_and_read_eris_ftp_file(
        self,
        semaphore: asyncio.Semaphore,
        client: httpx.AsyncClient,
        date: datetime.date,
        workbook_type: Literal["EOD_ParCouponCurve_SOFR", "Eris_Intraday_DiscountFactors_SOFR", "EOD_DiscountFactors_SOFR"],
        task_id: Optional[Any] = None,
    ):
        async with semaphore:
            buffer, file_name = await self._fetch_eris_ftp_files_helper(client=client, date=date, workbook_type=workbook_type)
            if not buffer or not file_name:
                return None, None

        key, df = await asyncio.to_thread(self._read_file, buffer, file_name)
        if task_id:
            return key, df, task_id
        return key, df

    def fetch_eris_ftp_timeseries(
        self,
        start_date: datetime.date,
        end_date: datetime.date,
        workbook_type: Literal["EOD_ParCouponCurve_SOFR", "EOD_DiscountFactors_SOFR"] = "EOD_ParCouponCurve_SOFR",
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        verbose: Optional[bool] = False,
    ) -> Dict[datetime.date, pd.DataFrame]:

        bdates = pd.date_range(start=start_date, end=end_date, freq=CustomBusinessDay(calendar=USFederalHolidayCalendar()))

        async def build_tasks(
            client: httpx.AsyncClient,
            dates: List[datetime.date],
        ):
            tasks = []
            semaphore = asyncio.Semaphore(max_concurrent_tasks)
            for date in dates:
                task = asyncio.create_task(self._fetch_and_read_eris_ftp_file(semaphore=semaphore, client=client, date=date, workbook_type=workbook_type))
                tasks.append(task)

            return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING ERIS FTP Files...")

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
                print('"fetch_eris_ftp_timeseries" --- empty results') if verbose else None
                return {}

            return dict(results)

    def fetch_intraday_discount_curve(
        self,
        curve_id: str,
        return_df: Optional[bool] = False,
        show_tqdm: Optional[bool] = True,
        return_intraday_timestamp: Optional[bool] = True,
    ) -> rl.Curve | pd.DataFrame | Tuple[rl.Curve, datetime.datetime]:

        def ql_date_to_datetime(ql_date: ql.Date) -> datetime.datetime:
            return datetime.datetime(ql_date.year(), ql_date.month(), ql_date.dayOfMonth())

        def datetime_to_ql_date(dt: datetime.datetime) -> ql.Date:
            ql_month = {
                1: ql.January,
                2: ql.February,
                3: ql.March,
                4: ql.April,
                5: ql.May,
                6: ql.June,
                7: ql.July,
                8: ql.August,
                9: ql.September,
                10: ql.October,
                11: ql.November,
                12: ql.December,
            }[dt.month]
            return ql.Date(dt.day, ql_month, dt.year)

        def next_n_month_end_datetimes(
            cal: ql.Calendar,
            start_dt: datetime.date,
            n: int,
            *,
            include_start=False,
            convention=ql.ModifiedFollowing,
        ) -> list[datetime.datetime]:
            start_ql = ql.Date(start_dt.day, start_dt.month, start_dt.year)
            out = []
            y, m = start_dt.year, start_dt.month
            k = 0
            while len(out) < n:
                mm = m + k
                yy = y + (mm - 1) // 12
                mm = ((mm - 1) % 12) + 1
                probe = ql.Date(15, mm, yy)
                eom_raw = ql.Date.endOfMonth(probe)
                eom_adj = cal.adjust(eom_raw, convention)
                if include_start:
                    accept = eom_adj >= start_ql
                else:
                    accept = eom_adj > start_ql
                if accept:
                    out.append(ql_date_to_datetime(eom_adj))
                k += 1
            return out

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

            discount_curve_df = dict(results)["Eris_Intraday_DiscountFactors_SOFR.csv"]
            discount_curve_df["Date"] = pd.to_datetime(discount_curve_df["Date"], errors="coerce")
            discount_curve_df["DiscountFactor"] = pd.to_numeric(discount_curve_df["DiscountFactor"], errors="coerce")

            tday = datetime.date.today()
            fomc_curve_nodes = get_fomc_meetings_list(as_of=tday, n_plus_years=1)
            sfr_tickers = get_short_end_curve_tickers(
                as_of=tday,
                first_n_sr1=0,
                first_n_sr3=12,
                use_globex=False,
            )
            imm_nodes = [rl.get_imm(code=sfr.replace("SFR", "")) for sfr in sfr_tickers]
            st_nodes = list({*fomc_curve_nodes, *[d for d in imm_nodes if (d.year, d.month) not in {(d.year, d.month) for d in fomc_curve_nodes}]})
            st_nodes = pd.to_datetime(st_nodes).sort_values()

            mt_nodes = []
            for tenor in ["3Y", "4Y", "5Y", "6Y", "7Y", "8Y", "9Y", "10Y", "12Y", "15Y", "20Y", "25Y", "30Y", "40Y", "45Y", "49Y", "50Y"]:
                mt_nodes.append(
                    ql_date_to_datetime(
                        ql.NullCalendar().advance(
                            ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                                datetime_to_ql_date(datetime.datetime(tday.year, tday.month, tday.day)),
                                ql.Period("2D"),
                                ql.ModifiedFollowing,
                            ),
                            ql.Period(tenor),
                        )
                    )
                )

            # for t in get_short_end_curve_tickers(
            #     as_of=tday,
            #     first_n_sr1=0,
            #     first_n_sr3=24,
            #     use_globex=False,
            # )[-12:]:
            #     mt_nodes.append(rl.get_imm(code=t.replace("SFR", "")))

            discount_curve_se_df = discount_curve_df[discount_curve_df["Date"].isin(st_nodes)]
            discount_curve_mt_df = discount_curve_df[discount_curve_df["Date"].isin(mt_nodes)]
            discount_curve_filtered_df = pd.concat([discount_curve_se_df, discount_curve_mt_df])
            discount_curve_filtered_df = discount_curve_filtered_df.sort_values(by="Date")

            mt_dates = discount_curve_filtered_df[discount_curve_filtered_df["Date"] > max(st_nodes)]["Date"].to_list()
            tail = ql_date_to_datetime(
                ql.NullCalendar().advance(
                    ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(
                        datetime_to_ql_date(datetime.datetime(mt_dates[-1].year, mt_dates[-1].month, mt_dates[-1].day)),
                        ql.Period("10Y"),
                        ql.ModifiedFollowing,
                    ),
                    ql.Period(tenor),
                )
            )

            intraday_ts = datetime.datetime.fromisoformat(
                str(parser.parse(discount_curve_df["Time"].iloc[0], tzinfos={"EDT": tz.gettz("US/Eastern"), "EST": tz.gettz("US/Eastern")}))
            )
            intraday_ts = intraday_ts.astimezone(pytz.timezone("America/New_York"))

            rl_discount_curve = rl.Curve(
                nodes=dict(zip(discount_curve_filtered_df["Date"], discount_curve_filtered_df["DiscountFactor"])),
                id=f"{curve_id}-{intraday_ts}",
                convention="act360",
                calendar="nyc",
                modifier="MF",
                interpolation="log_linear",
                t=[st_nodes[-1], st_nodes[-1], st_nodes[-1], st_nodes[-1]] + mt_dates[0:-1] + [tail, tail, tail, tail],
            )

            if return_intraday_timestamp:
                return rl_discount_curve, intraday_ts

            return rl_discount_curve
