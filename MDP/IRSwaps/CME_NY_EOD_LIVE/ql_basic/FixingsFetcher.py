import asyncio
import functools
import warnings
from datetime import datetime
from typing import Dict, Optional

import pandas as pd
import QuantLib as ql
import requests

from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.BaseFetcher import BaseFetcher
from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.FredFetcher import FredFetcher
from Query.IRSwaps.backends.quantlib.utils import most_recent_business_day_ql

warnings.simplefilter(action="ignore", category=FutureWarning)

import sys

if sys.platform == "win32":
    loop = asyncio.ProactorEventLoop()
    asyncio.set_event_loop(loop)


class FixingsFetcher(BaseFetcher):

    _nyfrb_base_headers = {
        "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7,application/json",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "Cookie": "markets.newyorkfed.org",
        "DNT": "1",
        "Host": "markets.newyorkfed.org",
        "Origin": "markets.newyorkfed.org",
        "Referer": "markets.newyorkfed.org",
        "Pragma": "no-cache",
        "Sec-CH-UA": '"Not)A;Brand";v="99", "Google Chrome";v="127", "Chromium";v="127"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    }
    _boc_base_headers = {
        "Accept": "application/json, text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive",
        "Cookie": "_ga=GA1.1.2045936550.1747076327; _ga_D0WRRH3RZH=GS2.1.s1747076327$o1$g1$t1747076926$j60$l0$h0",
        "DNT": "1",
        "Host": "www.bankofcanada.ca",
        "Referer": "https://www.google.com/",
        "Sec-CH-UA": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
        "Sec-CH-UA-Mobile": "?0",
        "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "cross-site",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    }

    def __init__(
        self,
        fred_api_key: Optional[str] = None,
        global_timeout: Optional[int] = 10,
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

        self.fred_api_key = fred_api_key
        if self.fred_api_key is not None: 
            self._fred_fetcher = FredFetcher(
                fred_api_key=fred_api_key,
                global_timeout=global_timeout,
                proxies=proxies,
                debug_verbose=debug_verbose,
                info_verbose=info_verbose,
                error_verbose=error_verbose,
            )
        self._func_map = {
            "USD-SOFR-1D": self._sofr_nyfrb,
            "USD-SOFR-1D_FRED": functools.partial(self._fetch_fred_series, series_id="SOFR"),
            "USD-FEDFUNDS": self._effr_nyfrb,
            "USD-FEDFUNDS_FRED": functools.partial(self._fetch_fred_series, series_id="EFFR"),
            "CAD-CORRA": self._corra_boc,
            "GBP-SONIA": functools.partial(self._fetch_fred_series, series_id="IUDSOIA"),
            "EUR-ESTR": functools.partial(self._fetch_fred_series, series_id="ECBESTRVOLWGTTRMDMNRT"),
            "EUR-EURIBOR-1M": self._euribor_1m,
            "EUR-EURIBOR-3M": self._euribor_3m,
            "EUR-EURIBOR-6M": self._euribor_6m,
            "JPY-TONAR": self._tonar,
        }

    def get_fixings(self, curve: str, use_fred: Optional[bool] = False) -> Dict[datetime, float]:
        if use_fred:
            curve = f"{curve}_FRED"
        if curve not in self._func_map:
            raise KeyError(f"Fixings fetching function not implemented for: {curve}")
        return self._func_map[curve]()

    def _fetch_fred_series(self, series_id: str) -> Dict[datetime, float]:
        assert self.fred_api_key, "REQUEST CURVE IS FETCHED FROM FRED - NEED API KEY"
        fixings_df = self._fred_fetcher.fred.get_multiple_series(series_ids=[series_id], one_df=True)
        fixings_df.index = pd.to_datetime(fixings_df.index, errors="coerce")
        return dict(zip(fixings_df.index, fixings_df[series_id] / 100))

    def _sofr_nyfrb(self):
        end_date = most_recent_business_day_ql(ql_calendar=ql.UnitedStates(ql.UnitedStates.SOFR), to_pydate=True)
        url = f"https://markets.newyorkfed.org/api/rates/secured/sofr/search.json?startDate=2018-04-01&endDate={end_date.strftime("%Y-%m-%d")}&type=rate"
        res = requests.get(
            url,
            headers=self._nyfrb_base_headers,
            proxies=self._proxies,
        )
        res.raise_for_status()
        df = pd.DataFrame(res.json()["refRates"])
        if df.empty:
            raise ValueError("SOFR df is empty")
        df["effectiveDate"] = pd.to_datetime(df["effectiveDate"], errors="coerce")
        df["percentRate"] = pd.to_numeric(df["percentRate"], errors="coerce") / 100
        return dict(zip(df["effectiveDate"], df["percentRate"]))

    def _effr_nyfrb(self):
        end_date = most_recent_business_day_ql(ql_calendar=ql.UnitedStates(ql.UnitedStates.SOFR), to_pydate=True)
        url = f"https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json?startDate=2000-07-03&endDate={end_date.strftime("%Y-%m-%d")}&type=rate"
        res = requests.get(
            url,
            headers=self._nyfrb_base_headers,
            proxies=self._proxies,
        )
        res.raise_for_status()
        df = pd.DataFrame(res.json()["refRates"])
        if df.empty:
            raise ValueError("EFFR df is empty")
        df["effectiveDate"] = pd.to_datetime(df["effectiveDate"], errors="coerce")
        df["percentRate"] = pd.to_numeric(df["percentRate"], errors="coerce") / 100
        return dict(zip(df["effectiveDate"], df["percentRate"]))

    def _corra_boc(self):
        res = requests.get("https://www.bankofcanada.ca/valet/observations/CORRA_WEIGHTED_MEAN_RATE/json", headers=self._boc_base_headers)
        return {datetime.strptime(item["d"], "%Y-%m-%d"): float(item["CORRA_WEIGHTED_MEAN_RATE"]["v"]) for item in res.json()["observations"]}

    def __euribor_headers(self, tenor: int, id: int):
        return {
            "Accept": "application/json, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
            "Referer": f"https://www.euribor-rates.eu/en/current-euribor-rates/{id}/euribor-rate-{tenor}/",
            "Sec-CH-UA": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
        }

    def _euribor_1m(self):
        res = requests.get(
            "https://www.euribor-rates.eu/umbraco/api/euriborpageapi/highchartsdata?series[0]=1", headers=self.__euribor_headers(tenor="1-month", id=1)
        )
        return {datetime.fromtimestamp(pair[0] / 1000): pair[1] / 100 for pair in res.json()[0]["Data"]}

    def _euribor_3m(self):
        res = requests.get(
            "https://www.euribor-rates.eu/umbraco/api/euriborpageapi/highchartsdata?series[0]=2", headers=self.__euribor_headers(tenor="3-months", id=2)
        )
        return {datetime.fromtimestamp(pair[0] / 1000): pair[1] / 100 for pair in res.json()[0]["Data"]}

    def _euribor_6m(self):
        res = requests.get(
            "https://www.euribor-rates.eu/umbraco/api/euriborpageapi/highchartsdata?series[0]=3", headers=self.__euribor_headers(tenor="6-months", id=3)
        )
        return {datetime.fromtimestamp(pair[0] / 1000): pair[1] / 100 for pair in res.json()[0]["Data"]}

    def _tonar(self):
        res = requests.get(
            "https://www.global-rates.com/highchart-api/?series[0].id=1&series[0].type=6&extra=null",
            headers={
                "accept": "application/json, */*",
                "accept-encoding": "gzip, deflate, br, zstd",
                "accept-language": "en-US,en;q=0.9",
                "dnt": "1",
                "priority": "u=1, i",
                "referer": "https://www.global-rates.com/en/interest-rates/tonar/",
                "sec-ch-ua": '"Google Chrome";v="135", "Not-A.Brand";v="8", "Chromium";v="135"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            },
        )
        return {datetime.fromtimestamp(pair[0] / 1000): pair[1] / 100 for pair in res.json()[0]["data"]}
