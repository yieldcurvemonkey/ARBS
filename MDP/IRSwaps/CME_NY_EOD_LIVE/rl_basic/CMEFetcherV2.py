import asyncio
import datetime
import sys
import warnings
from typing import Dict, List, Literal, Optional

import polars as pl
import pytz
import tqdm.asyncio

import rateslib as rl
import QuantLib as ql

from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.BaseFetcher import BaseFetcher
from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.CMEFetcher import CMEFetcher
from MDP.IRSwaps.CME_NY_EOD_LIVE.rl_basic.ErisFuturesFetcher import ErisFuturesFetcher

from Query.IRSwaps.backends.rateslib.rl_curve_definitions_map import RATESLIB_CURVE_DEFINITIONS

from Query.IRSwaps.backends.quantlib.utils import datetime_to_ql_date, ql_date_to_datetime


warnings.filterwarnings("ignore", category=FutureWarning)
warnings.simplefilter(action="ignore", category=FutureWarning)

import sys

if sys.platform == "win32":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)


class CMEFetcherV2(BaseFetcher):
    cme_fetcher_v1: CMEFetcher = None
    eris_fetcher: ErisFuturesFetcher = None

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
        self.cme_fetcher_v1 = CMEFetcher(
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )
        self.eris_fetcher = ErisFuturesFetcher(
            global_timeout=global_timeout,
            proxies=proxies,
            debug_verbose=debug_verbose,
            info_verbose=info_verbose,
            warning_verbose=warning_verbose,
            error_verbose=error_verbose,
        )

    def build_rl_eod_curves(
        self,
        curve_id: str,
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
        type: Literal["Zero", "Df"] = "Df",
        date_col: Optional[str] = "Date",
        start_date: Optional[datetime.date] = None,
        end_date: Optional[datetime.date] = None,
        bdates: Optional[List[datetime.date]] = None,
        show_tqdm: Optional[bool] = False,
        max_connections: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 5,
        ignore_cache: Optional[bool] = False,
        to_date_keys: Optional[bool] = False,
    ) -> Dict[datetime.date, rl.Curve]:
        assert (start_date and end_date) or bdates, "Must Pass in 'start_date' and 'end_date' or 'bdates'"

        tz_chi = pytz.timezone("US/Central")
        tday = datetime.datetime.now()
        CME_EOD_REPORT_RELEASE = tz_chi.localize(datetime.datetime(year=tday.year, month=tday.month, day=tday.day, hour=16, minute=0, second=0))
        chi_now = datetime.datetime.now(tz=tz_chi)

        if end_date:
            if end_date < tday.date():
                cme_end_date = end_date
            elif end_date == tday.date():
                if chi_now < CME_EOD_REPORT_RELEASE:
                    cme_end_date = ql_date_to_datetime(
                        ql.UnitedStates(ql.UnitedStates.GovernmentBond).advance(datetime_to_ql_date(end_date), ql.Period("-1D"), ql.ModifiedFollowing)
                    )
                    enable_intraday = True
                else:
                    cme_end_date = end_date
            else:
                raise ValueError(f"{end_date} is in the future")
        else:
            cme_end_date = None

        enable_intraday = False
        if bdates:
            today = chi_now.date()
            if any(d.date() == today and chi_now < CME_EOD_REPORT_RELEASE for d in bdates if isinstance(d, datetime.datetime)):
                enable_intraday = True
                end_date = chi_now

            if any(d == today and chi_now < CME_EOD_REPORT_RELEASE for d in bdates if isinstance(d, datetime.date)):
                enable_intraday = True
                end_date = chi_now

            if any(str(d).lower() == "live" for d in bdates if isinstance(d, str)):
                enable_intraday = True
                end_date = chi_now

            bdates = [d for d in bdates if d != today or (d == today and chi_now >= CME_EOD_REPORT_RELEASE) if isinstance(d, datetime.date)]

        rl_curves_dict: Dict[datetime.date, rl.Curve] = {}

        if (bdates and len(bdates) > 0) or (start_date and cme_end_date):
            cme_eod_curve_reports_dict_df = self.cme_fetcher_v1.fetch_curve_reports(
                start_date=start_date,
                end_date=cme_end_date,
                bdates=bdates,
                show_tqdm=show_tqdm,
                max_connections=max_connections,
                max_keepalive_connections=max_keepalive_connections,
                ignore_cache=ignore_cache,
            )

            curve_type_desc = "DISCOUNT" if type == "Df" else "ZERO"
            curve_iter = (
                tqdm.tqdm(cme_eod_curve_reports_dict_df.items(), desc=f"BUILDING {curve} {curve_type_desc} CURVES..")
                if show_tqdm
                else cme_eod_curve_reports_dict_df.items()
            )
            for curve_date, curve_report_df in curve_iter:
                # Rename columns to lowercase except date_col
                curve_report_df = curve_report_df.rename(
                    {col: col.lower() if col != date_col else col for col in curve_report_df.columns}
                )

                # try:
                if curve == "USD-FEDFUNDS" and curve_date < datetime.date(2021, 6, 28):
                    curve = "USD-OIS"

                curve_report_df = curve_report_df.filter(pl.col("curve name") == curve)
                if curve_report_df.is_empty():
                    rl_curves_dict[curve_date] = None
                    self._logger.error(f"No data from {curve} on {curve_date}")
                    continue

                # Parse dates and convert to datetime, then sort
                curve_report_df = curve_report_df.with_columns(
                    pl.col(date_col).str.to_datetime(format="%m/%d/%Y", strict=False)
                ).sort(date_col)

                # Convert type column to numeric
                curve_report_df = curve_report_df.with_columns(
                    pl.col(type.lower()).cast(pl.Float64, strict=False)
                )

                datetime_series = curve_report_df[date_col]
                type_series = curve_report_df[type.lower()]

                # Prepend curve_date with discount factor 1.0 if not present
                if type.lower() == "df" and curve_date not in datetime_series.to_list():
                    datetime_series = pl.concat([
                        pl.Series([curve_date]),
                        datetime_series
                    ])
                    type_series = pl.concat([
                        pl.Series([1.0]),
                        type_series
                    ])

                if type.lower() == "df":
                    # Convert polars Series to list for rateslib
                    datetime_list = datetime_series.to_list()
                    type_list = type_series.to_list()

                    rl_discount_curve = rl.Curve(
                        nodes=dict(zip(datetime_list, type_list)),
                        id=f"{curve_id}-{curve_date}",
                        convention=RATESLIB_CURVE_DEFINITIONS[curve]["DayCounter"],
                        calendar=RATESLIB_CURVE_DEFINITIONS[curve]["Calendar"],
                        modifier=RATESLIB_CURVE_DEFINITIONS[curve]["BusinessConvention"],
                        interpolation="log_linear",
                        t=[datetime_list[15], datetime_list[15], datetime_list[15], datetime_list[15]]
                        + datetime_list[16:-1]
                        + [datetime_list[-1], datetime_list[-1], datetime_list[-1], datetime_list[-1]],
                    )

                # CME Curve Report release
                naive_close = datetime.datetime(curve_date.year, curve_date.month, curve_date.day, 17, 0, 0)
                ny_tz = pytz.timezone("US/Eastern")
                curve_date_ny_close = ny_tz.localize(naive_close)
                if to_date_keys:
                    curve_date_ny_close = curve_date_ny_close.date()
                rl_curves_dict[curve_date_ny_close] = rl_discount_curve

                # except Exception as e:
                #     self._logger.error(f"Error when building Quantlib Curve for {curve} on {curve_date}: {e}")

        if enable_intraday and curve == "USD-SOFR-1D":
            intraday_ql_discount_curve, intraday_timestamp = self.eris_fetcher.fetch_intraday_discount_curve(
                curve_id=curve_id,
                show_tqdm=True,
                return_intraday_timestamp=True,
            )
            if to_date_keys:
                intraday_timestamp = "live"
            rl_curves_dict[intraday_timestamp] = intraday_ql_discount_curve

        return rl_curves_dict
