import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional

import httpx

from MDP.IRSwaps.CME_NY_EOD_LIVE.ql_basic.BaseFetcher import BaseFetcher

if sys.version_info[0] >= 3:
    import urllib.error as url_error
    import urllib.parse as url_parse
    import urllib.request as url_request
else:
    import urllib2 as url_request
    import urllib as url_parse
    import urllib2 as url_error

import polars as pl

urlopen = url_request.urlopen
quote_plus = url_parse.quote_plus
urlencode = url_parse.urlencode
HTTPError = url_error.HTTPError


def _to_datetime(date_input):
    """
    Convert date string or datetime to datetime object.
    Replacement for pd.to_datetime with errors='raise'.
    """
    if isinstance(date_input, datetime):
        return date_input
    if isinstance(date_input, str):
        # Try common datetime formats
        for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m/%d/%y"]:
            try:
                return datetime.strptime(date_input, fmt)
            except ValueError:
                continue
        raise ValueError(f"Unable to parse date string: {date_input}")
    raise TypeError(f"Unsupported date type: {type(date_input)}")


class Fred:
    earliest_realtime_start = "1776-07-04"
    latest_realtime_end = "9999-12-31"
    nan_char = "."
    max_results_per_request = 1000
    root_url = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key=None, api_key_file=None, proxies=None):
        """
        Initialize the Fred class that provides useful functions to query the Fred dataset. You need to specify a valid
        API key in one of 3 ways: pass the string via api_key, or set api_key_file to a file with the api key in the
        first line, or set the environment variable 'FRED_API_KEY' to the value of your api key.

        Parameters
        ----------
        api_key : str
            API key. A free api key can be obtained on the Fred website at http://research.stlouisfed.org/fred2/.
        api_key_file : str
            Path to a file containing the api key.
        proxies : dict
            Proxies specifications: a dictionary mapping protocol names (e.g. 'http', 'https') to proxy URLs. If not provided, environment variables 'HTTP_PROXY', 'HTTPS_PROXY' are used.

        """
        self.api_key = None
        if api_key is not None:
            self.api_key = api_key
        elif api_key_file is not None:
            f = open(api_key_file, "r")
            self.api_key = f.readline().strip()
            f.close()
        else:
            self.api_key = os.environ.get("FRED_API_KEY")

        if self.api_key is None:
            import textwrap

            raise ValueError(
                textwrap.dedent(
                    """\
                    You need to set a valid API key. You can set it in 3 ways:
                    pass the string with api_key, or set api_key_file to a
                    file with the api key in the first line, or set the
                    environment variable 'FRED_API_KEY' to the value of your
                    api key. You can sign up for a free api key on the Fred
                    website at http://research.stlouisfed.org/fred2/"""
                )
            )

        if not proxies:
            http_proxy, https_proxy = os.getenv("HTTP_PROXY"), os.getenv("HTTPS_PROXY")
            if http_proxy or https_proxy:
                proxies = {"http": http_proxy, "https": https_proxy}

        self.proxies = proxies

        if self.proxies:
            opener = url_request.build_opener(url_request.ProxyHandler(self.proxies))
            url_request.install_opener(opener)

    def __fetch_data(self, url):
        """
        helper function for fetching data given a request URL
        """
        url += "&api_key=" + self.api_key
        try:
            response = urlopen(url)
            root = ET.fromstring(response.read())
        except HTTPError as exc:
            root = ET.fromstring(exc.read())
            raise ValueError(root.get("message"))
        return root

    async def __async_fetch_data(self, client: httpx.AsyncClient, url: str):
        """
        helper function for fetching data given a request URL
        """
        url += "&api_key=" + self.api_key
        try:
            response = await client.get(url)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            if root is None:
                raise ValueError("No data exists for series id: " + url)
            data = {}
            for child in root:
                val = child.get("value")
                if val == self.nan_char:
                    val = float("NaN")
                else:
                    val = float(val)
                data[self._parse(child.get("date"))] = val
            return data
        except httpx.HTTPStatusError as exc:
            root = ET.fromstring(exc.response.text)
            raise ValueError(root.get("message"))

    def _parse(self, date_str, format="%Y-%m-%d"):
        """
        helper function for parsing FRED date string into datetime
        """
        if format is None:
            # Try common datetime formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(date_str, fmt)
                except ValueError:
                    continue
            # If no format works, raise error
            raise ValueError(f"Unable to parse date string: {date_str}")
        return datetime.strptime(date_str, format)

    def get_series_info(self, series_id):
        """
        Get information about a series such as its title, frequency, observation start/end dates, units, notes, etc.

        Parameters
        ----------
        series_id : str
            Fred series id such as 'CPIAUCSL'

        Returns
        -------
        info : Series
            a pandas Series containing information about the Fred series
        """
        url = "%s/series?series_id=%s" % (self.root_url, series_id)
        root = self.__fetch_data(url)
        if root is None or not len(root):
            raise ValueError("No info exists for series id: " + series_id)
        info = dict(list(root)[0].attrib)
        return info

    def get_series(
        self, series_id, observation_start=None, observation_end=None, **kwargs
    ):
        """
        Get data for a Fred series id. This fetches the latest known data, and is equivalent to get_series_latest_release()

        Parameters
        ----------
        series_id : str
            Fred series id such as 'CPIAUCSL'
        observation_start : datetime or datetime-like str such as '7/1/2014', optional
            earliest observation date
        observation_end : datetime or datetime-like str such as '7/1/2014', optional
            latest observation date
        kwargs : additional parameters
            Any additional parameters supported by FRED. You can see https://api.stlouisfed.org/docs/fred/series_observations.html for the full list

        Returns
        -------
        data : Series
            a Series where each index is the observation date and the value is the data for the Fred series
        """
        url = "%s/series/observations?series_id=%s" % (self.root_url, series_id)
        if observation_start is not None:
            observation_start = _to_datetime(observation_start)
            url += "&observation_start=" + observation_start.strftime("%Y-%m-%d")
        if observation_end is not None:
            observation_end = _to_datetime(observation_end)
            url += "&observation_end=" + observation_end.strftime("%Y-%m-%d")
        if kwargs.keys():
            url += "&" + urlencode(kwargs)
        root = self.__fetch_data(url)
        if root is None:
            raise ValueError("No data exists for series id: " + series_id)
        data = {}
        for child in root:
            val = child.get("value")
            if val == self.nan_char:
                val = float("NaN")
            else:
                val = float(val)
            data[self._parse(child.get("date"))] = val
        return data

    def get_multiple_series(
        self, series_ids, observation_start=None, observation_end=None, one_df=False, enable_date_col=False, **kwargs,
    ):
        async def build_tasks(
            client: httpx.AsyncClient,
            series_ids,
            root_url: str,
            observation_start=None,
            observation_end=None,
            **kwargs
        ):
            tasks = []
            for series_id in series_ids:
                url = "%s/series/observations?series_id=%s" % (root_url, series_id)
                if observation_start is not None:
                    observation_start = _to_datetime(observation_start)
                    url += "&observation_start=" + observation_start.strftime(
                        "%Y-%m-%d"
                    )
                if observation_end is not None:
                    observation_end = _to_datetime(observation_end)
                    url += "&observation_end=" + observation_end.strftime("%Y-%m-%d")
                if kwargs.keys():
                    url += "&" + urlencode(kwargs)

                task = self.__async_fetch_data(client=client, url=url)
                tasks.append(task)

            return await asyncio.gather(*tasks)

        async def run_fetch_all(
            series_ids, root_url: str, observation_start=None, observation_end=None, **kwargs
        ):
            async with httpx.AsyncClient() as client:
                all_data = await build_tasks(
                    client=client,
                    series_ids=series_ids,
                    root_url=root_url,
                    observation_start=observation_start,
                    observation_end=observation_end,
                    kwargs=kwargs,
                )
                return all_data

        results = asyncio.run(
            run_fetch_all(
                series_ids=series_ids,
                root_url=self.root_url,
                observation_start=observation_start,
                observation_end=observation_end,
                kwargs=kwargs,
            )
        )

        if one_df:
            # Convert dict results to polars DataFrames and join them
            dfs = []
            for series_id, data_dict in zip(series_ids, results):
                # Convert dict to DataFrame with date and value columns
                df_single = pl.DataFrame({
                    "Date": list(data_dict.keys()),
                    series_id: list(data_dict.values())
                })
                dfs.append(df_single)

            # Join all DataFrames on Date column
            if len(dfs) == 0:
                return pl.DataFrame()

            df = dfs[0]
            for df_next in dfs[1:]:
                df = df.join(df_next, on="Date", how="outer")

            # Sort by date
            df = df.sort("Date")

            if not enable_date_col:
                # Set Date as index (keep it but move to end behavior similar to pandas index)
                # In polars, we just keep Date as first column if enable_date_col is False
                pass

            return df

        return results

    def get_series_latest_release(self, series_id):
        """
        Get data for a Fred series id. This fetches the latest known data, and is equivalent to get_series()

        Parameters
        ----------
        series_id : str
            Fred series id such as 'CPIAUCSL'

        Returns
        -------
        info : Series
            a Series where each index is the observation date and the value is the data for the Fred series
        """
        return self.get_series(series_id)

    def get_series_first_release(self, series_id):
        """
        Get first-release data for a Fred series id. This ignores any revision to the data series. For instance,
        The US GDP for Q1 2014 was first released to be 17149.6, and then later revised to 17101.3, and 17016.0.
        This will ignore revisions after the first release.

        Parameters
        ----------
        series_id : str
            Fred series id such as 'GDP'

        Returns
        -------
        data : Series
            a Series where each index is the observation date and the value is the data for the Fred series
        """
        df = self.get_series_all_releases(series_id)
        # Get first release for each date (first row in each date group)
        first_release = df.sort(["date", "realtime_start"]).group_by("date").first()
        # Convert to dict with date as key and value as value
        data = dict(zip(first_release["date"].to_list(), first_release["value"].to_list()))
        return data

    def get_series_as_of_date(self, series_id, as_of_date):
        """
        Get latest data for a Fred series id as known on a particular date. This includes any revision to the data series
        before or on as_of_date, but ignores any revision on dates after as_of_date.

        Parameters
        ----------
        series_id : str
            Fred series id such as 'GDP'
        as_of_date : datetime, or datetime-like str such as '10/25/2014'
            Include data revisions on or before this date, and ignore revisions afterwards

        Returns
        -------
        data : Series
            a Series where each index is the observation date and the value is the data for the Fred series
        """
        as_of_date = _to_datetime(as_of_date)
        df = self.get_series_all_releases(series_id)
        data = df.filter(pl.col("realtime_start") <= as_of_date)
        return data

    def get_series_all_releases(
        self, series_id, realtime_start=None, realtime_end=None
    ):
        """
        Get all data for a Fred series id including first releases and all revisions. This returns a DataFrame
        with three columns: 'date', 'realtime_start', and 'value'. For instance, the US GDP for Q4 2013 was first released
        to be 17102.5 on 2014-01-30, and then revised to 17080.7 on 2014-02-28, and then revised to 17089.6 on
        2014-03-27. You will therefore get three rows with the same 'date' (observation date) of 2013-10-01 but three
        different 'realtime_start' of 2014-01-30, 2014-02-28, and 2014-03-27 with corresponding 'value' of 17102.5, 17080.7
        and 17089.6

        Parameters
        ----------
        series_id : str
            Fred series id such as 'GDP'
        realtime_start : str, optional
            specifies the realtime_start value used in the query, defaults to the earliest possible start date allowed by Fred
        realtime_end : str, optional
            specifies the realtime_end value used in the query, defaults to the latest possible end date allowed by Fred

        Returns
        -------
        data : DataFrame
            a DataFrame with columns 'date', 'realtime_start' and 'value' where 'date' is the observation period and 'realtime_start'
            is when the corresponding value (either first release or revision) is reported.
        """
        if realtime_start is None:
            realtime_start = self.earliest_realtime_start
        if realtime_end is None:
            realtime_end = self.latest_realtime_end
        url = (
            "%s/series/observations?series_id=%s&realtime_start=%s&realtime_end=%s"
            % (self.root_url, series_id, realtime_start, realtime_end)
        )
        root = self.__fetch_data(url)
        if root is None:
            raise ValueError("No data exists for series id: " + series_id)
        data = {}
        i = 0
        for child in root:
            val = child.get("value")
            if val == self.nan_char:
                val = float("NaN")
            else:
                val = float(val)
            realtime_start = self._parse(child.get("realtime_start"))
            # realtime_end = self._parse(child.get('realtime_end'))
            date = self._parse(child.get("date"))

            data[i] = {
                "realtime_start": realtime_start,
                # 'realtime_end': realtime_end,
                "date": date,
                "value": val,
            }
            i += 1
        # Convert dict of dicts to DataFrame
        df = pl.DataFrame(list(data.values()))
        return df

    def get_series_vintage_dates(self, series_id):
        """
        Get a list of vintage dates for a series. Vintage dates are the dates in history when a
        series' data values were revised or new data values were released.

        Parameters
        ----------
        series_id : str
            Fred series id such as 'CPIAUCSL'

        Returns
        -------
        dates : list
            list of vintage dates
        """
        url = "%s/series/vintagedates?series_id=%s" % (self.root_url, series_id)
        root = self.__fetch_data(url)
        if root is None:
            raise ValueError("No vintage date exists for series id: " + series_id)
        dates = []
        for child in root:
            dates.append(self._parse(child.text))
        return dates

    def __do_series_search(self, url):
        """
        helper function for making one HTTP request for data, and parsing the returned results into a DataFrame
        """
        root = self.__fetch_data(url)

        series_ids = []
        data = {}

        num_results_returned = 0  # number of results returned in this HTTP request
        num_results_total = int(
            root.get("count")
        )  # total number of results, this can be larger than number of results returned
        for child in root:
            num_results_returned += 1
            series_id = child.get("id")
            series_ids.append(series_id)
            data[series_id] = {"id": series_id}
            fields = [
                "realtime_start",
                "realtime_end",
                "title",
                "observation_start",
                "observation_end",
                "frequency",
                "frequency_short",
                "units",
                "units_short",
                "seasonal_adjustment",
                "seasonal_adjustment_short",
                "last_updated",
                "popularity",
                "notes",
            ]
            for field in fields:
                data[series_id][field] = child.get(field)

        if num_results_returned > 0:
            # Convert dict of dicts to DataFrame
            df = pl.DataFrame(list(data.values()))
            # parse datetime columns
            datetime_fields = [
                "realtime_start",
                "realtime_end",
                "observation_start",
                "observation_end",
                "last_updated",
            ]
            for field in datetime_fields:
                if field in df.columns:
                    df = df.with_columns(
                        pl.col(field).map_elements(
                            lambda x: self._parse(x, format=None) if x else None,
                            return_dtype=pl.Datetime
                        )
                    )
            data = df
        else:
            data = None
        return data, num_results_total

    def __get_search_results(self, url, limit, order_by, sort_order, filter):
        """
        helper function for getting search results up to specified limit on the number of results. The Fred HTTP API
        truncates to 1000 results per request, so this may issue multiple HTTP requests to obtain more available data.
        """

        order_by_options = [
            "search_rank",
            "series_id",
            "title",
            "units",
            "frequency",
            "seasonal_adjustment",
            "realtime_start",
            "realtime_end",
            "last_updated",
            "observation_start",
            "observation_end",
            "popularity",
        ]
        if order_by is not None:
            if order_by in order_by_options:
                url = url + "&order_by=" + order_by
            else:
                raise ValueError(
                    "%s is not in the valid list of order_by options: %s"
                    % (order_by, str(order_by_options))
                )

        if filter is not None:
            if len(filter) == 2:
                url = url + "&filter_variable=%s&filter_value=%s" % (
                    filter[0],
                    filter[1],
                )
            else:
                raise ValueError(
                    "Filter should be a 2 item tuple like (filter_variable, filter_value)"
                )

        sort_order_options = ["asc", "desc"]
        if sort_order is not None:
            if sort_order in sort_order_options:
                url = url + "&sort_order=" + sort_order
            else:
                raise ValueError(
                    "%s is not in the valid list of sort_order options: %s"
                    % (sort_order, str(sort_order_options))
                )

        data, num_results_total = self.__do_series_search(url)
        if data is None:
            return data

        if limit == 0:
            max_results_needed = num_results_total
        else:
            max_results_needed = limit

        if max_results_needed > self.max_results_per_request:
            for i in range(1, max_results_needed // self.max_results_per_request + 1):
                offset = i * self.max_results_per_request
                next_data, _ = self.__do_series_search(url + "&offset=" + str(offset))
                data = pl.concat([data, next_data])
        return data.head(max_results_needed)

    def search(self, text, limit=1000, order_by=None, sort_order=None, filter=None):
        """
        Do a fulltext search for series in the Fred dataset. Returns information about matching series in a DataFrame.

        Parameters
        ----------
        text : str
            text to do fulltext search on, e.g., 'Real GDP'
        limit : int, optional
            limit the number of results to this value. If limit is 0, it means fetching all results without limit.
        order_by : str, optional
            order the results by a criterion. Valid options are 'search_rank', 'series_id', 'title', 'units', 'frequency',
            'seasonal_adjustment', 'realtime_start', 'realtime_end', 'last_updated', 'observation_start', 'observation_end',
            'popularity'
        sort_order : str, optional
            sort the results by ascending or descending order. Valid options are 'asc' or 'desc'
        filter : tuple, optional
            filters the results. Expects a tuple like (filter_variable, filter_value).
            Valid filter_variable values are 'frequency', 'units', and 'seasonal_adjustment'

        Returns
        -------
        info : DataFrame
            a DataFrame containing information about the matching Fred series
        """
        url = "%s/series/search?search_text=%s&" % (self.root_url, quote_plus(text))
        info = self.__get_search_results(url, limit, order_by, sort_order, filter)
        return info

    def search_by_release(
        self, release_id, limit=0, order_by=None, sort_order=None, filter=None
    ):
        """
        Search for series that belongs to a release id. Returns information about matching series in a DataFrame.

        Parameters
        ----------
        release_id : int
            release id, e.g., 151
        limit : int, optional
            limit the number of results to this value. If limit is 0, it means fetching all results without limit.
        order_by : str, optional
            order the results by a criterion. Valid options are 'search_rank', 'series_id', 'title', 'units', 'frequency',
            'seasonal_adjustment', 'realtime_start', 'realtime_end', 'last_updated', 'observation_start', 'observation_end',
            'popularity'
        sort_order : str, optional
            sort the results by ascending or descending order. Valid options are 'asc' or 'desc'
        filter : tuple, optional
            filters the results. Expects a tuple like (filter_variable, filter_value).
            Valid filter_variable values are 'frequency', 'units', and 'seasonal_adjustment'

        Returns
        -------
        info : DataFrame
            a DataFrame containing information about the matching Fred series
        """
        url = "%s/release/series?release_id=%d" % (self.root_url, release_id)
        info = self.__get_search_results(url, limit, order_by, sort_order, filter)
        if info is None:
            raise ValueError("No series exists for release id: " + str(release_id))
        return info

    def search_by_category(
        self, category_id, limit=0, order_by=None, sort_order=None, filter=None
    ):
        """
        Search for series that belongs to a category id. Returns information about matching series in a DataFrame.

        Parameters
        ----------
        category_id : int
            category id, e.g., 32145
        limit : int, optional
            limit the number of results to this value. If limit is 0, it means fetching all results without limit.
        order_by : str, optional
            order the results by a criterion. Valid options are 'search_rank', 'series_id', 'title', 'units', 'frequency',
            'seasonal_adjustment', 'realtime_start', 'realtime_end', 'last_updated', 'observation_start', 'observation_end',
            'popularity'
        sort_order : str, optional
            sort the results by ascending or descending order. Valid options are 'asc' or 'desc'
        filter : tuple, optional
            filters the results. Expects a tuple like (filter_variable, filter_value).
            Valid filter_variable values are 'frequency', 'units', and 'seasonal_adjustment'

        Returns
        -------
        info : DataFrame
            a DataFrame containing information about the matching Fred series
        """
        url = "%s/category/series?category_id=%d&" % (self.root_url, category_id)
        info = self.__get_search_results(url, limit, order_by, sort_order, filter)
        if info is None:
            raise ValueError("No series exists for category id: " + str(category_id))
        return info



class FredFetcher(BaseFetcher):
    fred: Fred = None

    def __init__(
        self,
        fred_api_key: Optional[str] = None,
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

        self.fred = Fred(api_key=fred_api_key, proxies=self._proxies)
    
    def get_historical_cmt_yields(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        tenors: Optional[List[str]] = None,
    ):
        print("Fetching from FRED...")
        df = self.fred.get_multiple_series(
            series_ids=[
                "DTB3",
                "DTB6",
                "DGS1",
                "DGS2",
                "DGS3",
                "DGS5",
                "DGS7",
                "DGS10",
                "DGS20",
                "DGS30",
            ],
            one_df=True,
            observation_start=start_date,
            observation_end=end_date,
        )
        # Rename columns
        df = df.rename({
            "DTB3": "CMT3M",
            "DTB6": "CMT6M",
            "DGS1": "CMT1",
            "DGS2": "CMT2",
            "DGS3": "CMT3",
            "DGS5": "CMT5",
            "DGS7": "CMT7",
            "DGS10": "CMT10",
            "DGS20": "CMT20",
            "DGS30": "CMT30",
        })
        if tenors:
            cols_to_select = ["Date"] + tenors
            return df.select(cols_to_select)
        df = df.drop_nulls()
        return df
