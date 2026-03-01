import asyncio
import logging
import re
import time
import warnings
from datetime import datetime, timedelta
from functools import reduce
from io import StringIO
from typing import Annotated, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote, unquote, urlencode

import httpx
import pandas as pd
import pytz
import requests
import tqdm
import tqdm.asyncio

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


class BarchartFetcher(BaseFetcher):
    _current_laravel_token: str = None
    _current_xsrf_token: str = None
    _BARCHART_MAX_RECORD = 5_000
    _STIR_ROOT_CODE_RE = re.compile(
        r"^(SR[13]|SFR|SER|FF|ZQ|SQ|SL|RA|EB|IJ|RG|IM|TV|J8|JU|T0|IT|J2)([FGHJKMNQUVXZ]\d{2})$",
        re.IGNORECASE,
    )
    _STIR_ROOT_TO_BARCHART = {
        "SR3": "SQ",
        "SFR": "SQ",
        "SQ": "SQ",
        "SR1": "SL",
        "SER": "SL",
        "SL": "SL",
        "ZQ": "ZQ",
        "FF": "ZQ",
        "RA": "RA",  # Eurex 3M ESTR
        "EB": "EB",  # ICE 3M ESTR
        "IJ": "IJ",  # ICE 1M ESTR
        "RG": "RG",  # B3 3M CORRA
        "IM": "IM",  # ICE 3M Euribor
        "TV": "TV",  # Eurex 3M Euribor
        "J8": "J8",  # ICE 3M SONIA
        "JU": "JU",  # ICE 1M SONIA
        "T0": "T0",  # JPX 3M TONA
        "IT": "IT",  # TFX 3M TONA
        "J2": "J2",  # Eurex 3M SARON
    }

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

    @classmethod
    def _normalize_barchart_symbol(cls, symbol: str) -> str:
        s = (symbol or "").strip().upper().replace("/", "")
        m = cls._STIR_ROOT_CODE_RE.match(s)
        if not m:
            return s
        root, code = m.group(1).upper(), m.group(2).upper()
        return f"{cls._STIR_ROOT_TO_BARCHART.get(root, root)}{code}"

    def _get_new_session_token(self, dummy_symbol: Optional[str] = "BTC") -> Tuple[str, str]:
        """
        Fetch and return a new session token pair (laravel_token, XSRF-TOKEN).
        This method is used to build a pool of tokens.
        """
        interactive_chart_url = f"https://www.barchart.com/futures/quotes/{quote(dummy_symbol)}/interactive-chart"
        interactive_chart_headers = {
            "dnt": "1",
            "referer": f"https://www.barchart.com/futures/quotes/{quote(dummy_symbol)}/interactive-chart",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        }
        interactive_chart_res = requests.get(interactive_chart_url, headers=interactive_chart_headers, proxies=self._proxies)
        interactive_chart_res.raise_for_status()

        cookie_pairs = unquote(interactive_chart_res.headers["Set-Cookie"]).split("; ")
        cleaned_cookie_pairs = []
        for pair in cookie_pairs:
            if ", " in pair:
                newpair1, newpair2 = pair.split(", ")
                cleaned_cookie_pairs.append(newpair1)
                cleaned_cookie_pairs.append(newpair2)
            else:
                cleaned_cookie_pairs.append(pair)

        cookie_dict = {}
        for pair in cleaned_cookie_pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
                cookie_dict[key] = value

        if "laravel_token" in cookie_dict and "XSRF-TOKEN" in cookie_dict:
            return cookie_dict["laravel_token"], cookie_dict["XSRF-TOKEN"]
        else:
            raise ValueError("Barchart Session Token Cookie Parsing Error: could not find laravel_token and XSRF-TOKEN")

    def _fetch_session_tokens(self, dummy_symbol: Optional[str] = "BTC"):
        """
        Fallback session token fetch which also sets the instance’s tokens.
        """
        token, xsrf = self._get_new_session_token(dummy_symbol)
        self._current_laravel_token = token
        self._current_xsrf_token = xsrf

    def _parse_aspx_response_to_df(self, response_content: bytes, columns: Optional[List[str]] = None):
        if isinstance(response_content, bytes):
            response_content = response_content.decode("utf-8")

        data_stream = StringIO(response_content)
        df = pd.read_csv(data_stream, header=None)
        if columns and len(columns) == len(df.columns):
            df.columns = columns
        if columns and len(columns) - 1 == len(df.columns):
            df.columns = columns[:-1]

        return df

    async def _fetch_intraday_timeseries(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        interval: Literal[1, 5, 10, 15, 30, 60, 120, 240],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        columns: Optional[List[str]] = ["Date", "temp", "Open", "High", "Low", "Close", "Volume"],
        set_dt_index: Optional[bool] = True,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
        uid: Optional[str | int] = None,
        session_token: Optional[Tuple[str, str]] = None,
    ) -> Tuple[str, pd.DataFrame] | Tuple[str, pd.DataFrame, str]:

        # Use passed-in token (from the pool) or fallback to instance tokens.
        token = session_token if session_token is not None else (self._current_laravel_token, self._current_xsrf_token)

        # Validate timezone info & consistency
        def _tz_ok(dt: Optional[datetime]) -> bool:
            return (dt is None) or (dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None)

        if not _tz_ok(start_date) or not _tz_ok(end_date):
            raise ValueError("start_date and end_date must include timezone information if provided.")

        # Barchart intraday timestamps are always exchange-local (Central for futures/forex).
        exchange_tz = pytz.timezone("America/Chicago")
        request_tzinfo = (start_date or end_date).tzinfo if (start_date or end_date) else exchange_tz
        request_tz_name = getattr(request_tzinfo, "zone", None) or getattr(request_tzinfo, "key", None)
        request_tz = pytz.timezone(request_tz_name) if request_tz_name else request_tzinfo
        start_exchange = start_date.astimezone(exchange_tz) if start_date is not None else None
        end_exchange = end_date.astimezone(exchange_tz) if end_date is not None else None

        base_url = (
            f"https://www.barchart.com/proxies/timeseries/historical/queryminutes.ashx?"
            f"symbol={quote(symbol)}&interval={interval}&maxrecords={self._BARCHART_MAX_RECORD}"
            f"&volume=contract&order=asc"
        )

        def build_headers(token: Tuple[str, str]):
            return {
                "dnt": "1",
                "referer": f"https://www.barchart.com/futures/quotes/{quote(symbol)}/interactive-chart",
                "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                "cookie": f"laravel_token={token[0]}",
                "x-xsrf-token": token[1],
            }

        # Helper: fetch a single slice with retries, optionally with an end cursor
        async def _fetch_slice(token: str, end_cursor: Optional[datetime]) -> Optional[pd.DataFrame]:
            headers = build_headers(token=token)

            # build URL with optional &end
            if end_cursor is not None:
                if end_cursor.tzinfo is None or end_cursor.tzinfo.utcoffset(end_cursor) is None:
                    raise ValueError("Internal error: end_cursor must be tz-aware.")
                end_str = end_cursor.astimezone(exchange_tz).strftime("%Y%m%d%H%M")
                url = f"{base_url}&end={end_str}"
            else:
                url = base_url  # latest

            retries = 0
            while retries < max_retries:
                if retries > 0:
                    self._logger.debug(f"Attempting to get a new session token for {symbol} after failed attempt.")
                    try:
                        token = self._get_new_session_token()
                        headers = build_headers(token=token)
                    except Exception as token_e:
                        self._logger.error(f"Failed to get new token: {token_e}")
                        pass

                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    if not resp.content:
                        self._logger.debug(f"Empty content received for symbol {symbol}")
                        return None

                    df_slice = self._parse_aspx_response_to_df(resp.content, columns=columns)
                    if df_slice is None or df_slice.empty:
                        return None

                    # Clean/prepare
                    if "temp" in df_slice.columns:
                        df_slice = df_slice.drop(columns=["temp"])
                    if "Date" not in df_slice.columns:
                        return None

                    # Parse and localize/conform tz
                    df_slice["Date"] = pd.to_datetime(df_slice["Date"], errors="coerce")
                    df_slice = df_slice.dropna(subset=["Date"])
                    if getattr(df_slice["Date"].dt, "tz", None) is None:
                        df_slice["Date"] = df_slice["Date"].dt.tz_localize(exchange_tz)
                    else:
                        df_slice["Date"] = df_slice["Date"].dt.tz_convert(exchange_tz)

                    return df_slice

                except httpx.HTTPStatusError:
                    status = getattr(resp, "status_code", "unknown")
                    self._logger.debug(f"Barchart Intraday - Bad Status for {symbol}: {status}")
                    if status == 404:
                        return None
                except Exception as e:
                    self._logger.debug(f"Barchart Intraday - Error for {symbol}: {str(e)}")

                retries += 1
                wait_time = backoff_factor * (2 ** (retries - 1))
                self._logger.debug(f"Barchart Intraday - Throttled for {symbol}. Waiting {wait_time}s before retrying (attempt {retries}/{max_retries})...")

                await asyncio.sleep(wait_time)

            return None

        try:
            # Cursoring: start with end_date (if provided), else latest (None)
            # Each slice returns up to MAX_RECORD rows ending at `end_cursor` (inclusive), going backwards.
            # We page backward until we cross start_date or can’t get more.
            end_cursor = end_exchange if end_exchange is not None else None
            slices: List[pd.DataFrame] = []
            seen_earliest: Optional[pd.Timestamp] = None

            # Safety cap: avoid infinite loops if API behaves unexpectedly.
            # For 1-min data, 1000 slices already covers ~500k rows ~1yr intraday min data.
            MAX_SLICES = 100

            for _ in range(MAX_SLICES):
                df_slice = await _fetch_slice(token=token, end_cursor=end_cursor)
                if df_slice is None or df_slice.empty:
                    break

                # If the API returns future/open-ended rows when no end is provided, cap by end_date if present
                if end_exchange is not None:
                    df_slice = df_slice[df_slice["Date"] <= end_exchange]

                slices.append(df_slice)

                earliest = df_slice["Date"].min()
                latest = df_slice["Date"].max()

                # Stop if we already covered start_date
                if start_exchange is not None and earliest <= start_exchange:
                    break

                # Detect no-progress and break
                if seen_earliest is not None and earliest >= seen_earliest:
                    break
                seen_earliest = earliest

                # Page one interval earlier than the earliest we saw to avoid overlap
                # (Barchart’s `end` is inclusive). Subtract `interval` minutes.
                step_minutes = int(interval)
                end_cursor = earliest - pd.Timedelta(minutes=step_minutes)

            if not slices:
                if uid:
                    return symbol, None, uid
                return symbol, None

            df = pd.concat(slices, ignore_index=True)
            df = df.drop_duplicates(subset=["Date"], keep="last").sort_values("Date")
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"])
            if getattr(df["Date"].dt, "tz", None) is None:
                df["Date"] = df["Date"].dt.tz_localize(exchange_tz)
            else:
                df["Date"] = df["Date"].dt.tz_convert(exchange_tz)
            df_copy = df.copy()

            if start_exchange is not None:
                df = df[df["Date"] >= start_exchange]
            if end_exchange is not None:
                df = df[df["Date"] <= end_exchange]

            if df.empty and not df_copy.empty and start_exchange and end_exchange:
                df_copy = df_copy.set_index("Date")
                new_index = pd.date_range(start=start_exchange, end=end_exchange, freq=f"{interval}min", tz=exchange_tz)
                combined_index = df_copy.index.union(new_index)
                df_reindexed = df_copy.reindex(combined_index)
                df_filled = df_reindexed.ffill().bfill()
                df = df_filled.loc[new_index].reset_index().rename(columns={"index": "Date"})

            if request_tz is not None:
                df["Date"] = df["Date"].dt.tz_convert(request_tz)

            if set_dt_index:
                df = df.set_index("Date")

            if uid:
                return symbol, df, uid
            return symbol, df

        except Exception as e:
            self._logger.debug(e)
            if uid:
                return symbol, None, uid
            return symbol, None

    async def _fetch_eod_timeseries(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        columns: Optional[List[str]] = ["Symbol", "Date", "Open", "High", "Low", "Close", "Volume", "Open Interest"],
        set_dt_index: Optional[bool] = True,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
        uid: Optional[str | int] = None,
        session_token: Optional[Tuple[str, str]] = None,
    ) -> Tuple[str, pd.DataFrame] | Tuple[str, pd.DataFrame, str]:
        token = session_token if session_token is not None else (self._current_laravel_token, self._current_xsrf_token)

        try:
            url = (
                f"https://www.barchart.com/proxies/timeseries/historical/queryeod.ashx?"
                f"symbol={quote(symbol)}&data=daily&maxrecords={self._BARCHART_MAX_RECORD}"
                f"&volume=contract&order=asc"
            )
            headers = {
                "dnt": "1",
                "referer": f"https://www.barchart.com/futures/quotes/{quote(symbol)}/interactive-chart",
                "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                "cookie": f"laravel_token={token[0]}",
                "x-xsrf-token": token[1],
            }

            retries = 0
            while retries < max_retries:
                try:
                    response = await client.get(url, headers=headers)
                    response.raise_for_status()
                    df = self._parse_aspx_response_to_df(response.content, columns=columns)

                    if "Symbol" in df.columns:
                        df = df.drop(columns=["Symbol"])

                    if "Date" in df.columns:
                        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
                        if set_dt_index:
                            df = df.set_index("Date")
                        if start_date:
                            df = df[df["Date"] >= start_date] if not set_dt_index else df[df.index >= start_date]
                        if end_date:
                            df = df[df["Date"] <= end_date] if not set_dt_index else df[df.index <= end_date]

                    if uid:
                        return symbol, df, uid
                    return symbol, df

                except pd.errors.EmptyDataError:
                    self._logger.error(f"Barchart EOD - Empty data error: No columns to parse from file for symbol {symbol}")
                    if uid:
                        return symbol, None, uid
                    return symbol, None

                except httpx.HTTPStatusError as e:
                    self._logger.error(f"Barchart EOD - Bad Status for {symbol}: {response.status_code}")
                    if response.status_code == 404:
                        if uid:
                            return symbol, None, uid
                        return symbol, None

                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"Barchart EOD - Throttled for {symbol}. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    self._logger.error(f"Barchart EOD - Error for {symbol}: {str(e)}")
                    retries += 1
                    wait_time = backoff_factor * (2 ** (retries - 1))
                    self._logger.debug(f"Barchart EOD - Throttled for {symbol}. Waiting for {wait_time} seconds before retrying...")
                    await asyncio.sleep(wait_time)

            raise ValueError(f"Barchart EOD - Max retries exceeded for {symbol}")

        except Exception as e:
            self._logger.error(e)
            if uid:
                return symbol, None, uid
            return symbol, None

    async def _fetch_intraday_timeseries_with_semaphore(self, semaphore, *args, **kwargs):
        await asyncio.sleep(0.2)
        async with semaphore:
            return await self._fetch_intraday_timeseries(*args, **kwargs)

    async def _fetch_eod_timeseries_with_semaphore(self, semaphore, *args, **kwargs):
        async with semaphore:
            return await self._fetch_eod_timeseries(*args, **kwargs)

    def barchart_timeseries_api(
        self,
        barchart_symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]] = None,
        max_concurrent_tasks: Optional[int] = 64,
        max_keepalive_connections: Optional[int] = 16,
        one_df: Optional[bool] = False,
        show_tqdm: Optional[bool] = True,
        merge_val_col: Optional[Literal["Open", "High", "Low", "Close", "Volume", "Open Interest"]] = "Close",
    ):
        barchart_symbols = [self._normalize_barchart_symbol(s) for s in barchart_symbols]

        async def build_eod_tasks(
            client: httpx.AsyncClient,
            barchart_symbols: List[str],
            start_date: datetime,
            end_date: datetime,
            tokens_pool: List[Tuple[str, str]],
        ):
            semaphore = asyncio.Semaphore(max_concurrent_tasks)
            tasks = [
                self._fetch_eod_timeseries_with_semaphore(
                    semaphore=semaphore,
                    client=client,
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    set_dt_index=not one_df,
                    session_token=tokens_pool[i % len(tokens_pool)],
                )
                for i, symbol in enumerate(barchart_symbols)
            ]
            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING EOD DATA FROM BARCHART...")
            return await asyncio.gather(*tasks)

        async def build_intraday_tasks(
            client: httpx.AsyncClient,
            barchart_symbols: List[str],
            start_date: datetime,
            end_date: datetime,
            tokens_pool: List[Tuple[str, str]],
            interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]] = None,
        ):
            semaphore = asyncio.Semaphore(max_concurrent_tasks)
            tasks = [
                self._fetch_intraday_timeseries_with_semaphore(
                    semaphore=semaphore,
                    client=client,
                    symbol=symbol,
                    interval=interval,
                    start_date=start_date,
                    end_date=end_date,
                    set_dt_index=not one_df,
                    session_token=tokens_pool[i % len(tokens_pool)],
                )
                for i, symbol in enumerate(barchart_symbols)
            ]
            if show_tqdm:
                return await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING INTRADAY DATA FROM BARCHART...")
            return await asyncio.gather(*tasks)

        async def run_fetch_all(
            barchart_symbols: List[str],
            start_date: datetime,
            end_date: datetime,
            interval: Optional[Literal[1, 5, 10, 15, 30, 60, 120, 240]] = None,
        ):
            tokens_tasks = [asyncio.to_thread(self._get_new_session_token) for _ in range(max_concurrent_tasks)]
            tokens_pool = await tqdm.asyncio.tqdm.gather(*tokens_tasks, desc="FETCHING SESSION TOKENS...")

            limits = httpx.Limits(
                max_connections=max_concurrent_tasks,
                max_keepalive_connections=max_keepalive_connections,
            )
            async with httpx.AsyncClient(
                limits=limits, timeout=self._global_timeout, mounts=self._httpx_proxies, verify=False, http2=True, headers={"Connection": "close"}
            ) as client:
                if interval:
                    all_data = await build_intraday_tasks(
                        client=client,
                        barchart_symbols=barchart_symbols,
                        start_date=start_date,
                        end_date=end_date,
                        interval=interval,
                        tokens_pool=tokens_pool,
                    )
                else:
                    all_data = await build_eod_tasks(
                        client=client,
                        barchart_symbols=barchart_symbols,
                        start_date=start_date,
                        end_date=end_date,
                        tokens_pool=tokens_pool,
                    )
                return all_data

        dfs: List[Tuple[str, pd.DataFrame]] = asyncio.run(
            run_fetch_all(barchart_symbols=barchart_symbols, start_date=start_date, end_date=end_date, interval=interval)
        )

        if one_df:

            def merge_dfs_on_column(dfs_dict: Dict[str, pd.DataFrame], on_column: str, merge_val_col: str):
                dfs_dict = {key: df[[on_column, merge_val_col]].rename(columns={merge_val_col: key}) for key, df in dfs_dict.items() if df is not None}
                if not dfs_dict:
                    return pd.DataFrame(columns=[on_column])
                merged_df = reduce(lambda left, right: pd.merge(left, right, on=on_column, how="outer"), dfs_dict.values())
                merged_df.sort_values(by=on_column, inplace=True)
                return merged_df

            merged = merge_dfs_on_column(dict(dfs), "Date", merge_val_col)
            if len(merged.columns) - 2 == len(barchart_symbols):
                print(f"MISSING DATA! Expected #Cols {len(barchart_symbols)}, Got {len(merged.columns)}")
            df = merged.set_index("Date")
            return df[(df.index >= start_date) & (df.index <= end_date)]

        return dict(dfs)

    def get_historical_bid_offer_quotes(
        self,
        symbol: str,
        start: Optional[datetime | str] = None,
        end: Optional[datetime | str] = None,
        maxrecords: Optional[int] = None,
        order: Optional[Literal["asc", "desc"]] = "desc",
        sessionfilter: Optional[str] = None,
        exchange_id: Optional[bool] = False,
        participant_id: Optional[bool] = False,
        set_dt_index: Optional[bool] = True,
        max_retries: Optional[int] = 3,
        backoff_factor: Optional[int] = 1,
    ) -> pd.DataFrame:
        def _format_tick_dt(value: Optional[datetime | str]) -> Optional[str]:
            if value is None:
                return None
            if isinstance(value, datetime):
                return value.strftime("%Y%m%d%H%M%S")
            out = str(value).strip()
            return out or None

        def _looks_like_datetime_col(col: pd.Series) -> bool:
            parsed = pd.to_datetime(col, errors="coerce")
            return parsed.notna().sum() > 0

        def _assign_quote_columns(df: pd.DataFrame) -> pd.DataFrame:
            if df.empty:
                return df

            has_symbol_col = False
            if df.shape[1] >= 2:
                first_col_is_dt = _looks_like_datetime_col(df.iloc[:, 0])
                second_col_is_dt = _looks_like_datetime_col(df.iloc[:, 1])
                has_symbol_col = (not first_col_is_dt) and second_col_is_dt

            effective_cols = df.shape[1] - (1 if has_symbol_col else 0)
            if effective_cols == 7:
                quote_cols = ["DateTime", "TradingDay", "QuoteCondition", "BidPrice", "BidSize", "OfferPrice", "OfferSize"]
            elif effective_cols == 8:
                quote_cols = ["DateTime", "TradingDay", "ExchangeId", "QuoteCondition", "BidPrice", "BidSize", "OfferPrice", "OfferSize"]
            elif effective_cols == 9:
                quote_cols = [
                    "DateTime",
                    "TradingDay",
                    "QuoteCondition",
                    "BidPrice",
                    "BidSize",
                    "BidParticipantId",
                    "OfferPrice",
                    "OfferSize",
                    "OfferParticipantId",
                ]
            elif effective_cols == 10:
                quote_cols = [
                    "DateTime",
                    "TradingDay",
                    "ExchangeId",
                    "QuoteCondition",
                    "BidPrice",
                    "BidSize",
                    "BidParticipantId",
                    "OfferPrice",
                    "OfferSize",
                    "OfferParticipantId",
                ]
            else:
                quote_cols = [f"Column{i}" for i in range(effective_cols)]

            df.columns = (["Symbol"] if has_symbol_col else []) + quote_cols
            return df

        order_val = (order or "").lower()
        if order_val and order_val not in {"asc", "desc"}:
            raise ValueError("order must be either 'asc' or 'desc'.")

        args = {
            "symbol": symbol,
            "type": "Q",
        }
        if order_val:
            args["order"] = order_val
        start_val = _format_tick_dt(start)
        end_val = _format_tick_dt(end)
        if start_val:
            args["start"] = start_val
        if end_val:
            args["end"] = end_val
        if maxrecords is not None:
            args["maxrecords"] = int(maxrecords)
        if sessionfilter is not None:
            args["sessionfilter"] = sessionfilter
        if exchange_id:
            args["exchId"] = "true"
        if participant_id:
            args["participantID"] = "true"

        url = f"https://www.barchart.com/proxies/historical/queryticks.ashx?{urlencode(args)}"
        print(url)

        retries = 0
        while retries < max_retries:
            try:
                if retries > 0 or self._current_laravel_token is None or self._current_xsrf_token is None:
                    self._fetch_session_tokens(dummy_symbol=symbol)

                headers = {
                    "dnt": "1",
                    "referer": f"https://www.barchart.com/futures/quotes/{quote(symbol)}/interactive-chart",
                    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                    "cookie": f"laravel_token={self._current_laravel_token}",
                    "x-xsrf-token": self._current_xsrf_token,
                }

                res = requests.get(url, headers=headers, proxies=self._proxies, timeout=self._global_timeout)
                res.raise_for_status()

                if not res.content:
                    return pd.DataFrame()

                df = self._parse_aspx_response_to_df(res.content)
                if df is None or df.empty:
                    return pd.DataFrame()

                df = _assign_quote_columns(df)

                if "DateTime" in df.columns:
                    df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
                    df = df.dropna(subset=["DateTime"])

                for col in ["TradingDay", "BidPrice", "BidSize", "OfferPrice", "OfferSize"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                if set_dt_index and "DateTime" in df.columns:
                    df = df.set_index("DateTime")
                    df = df.sort_index()

                return df

            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status == 404:
                    return pd.DataFrame()
                self._logger.error(f"Barchart historical quotes bad status for {symbol}: {status}")
            except pd.errors.EmptyDataError:
                return pd.DataFrame()
            except Exception as e:
                self._logger.error(f"Barchart historical quotes error for {symbol}: {e}")

            retries += 1
            if retries < max_retries:
                wait_time = backoff_factor * (2 ** (retries - 1))
                time.sleep(wait_time)

        raise ValueError(f"Barchart historical quotes - max retries exceeded for {symbol}")

    def get_option_quotes(
        self, symbols: List[str], max_concurrent_tasks: Optional[int] = 64, max_keepalive_connections: Optional[int] = 16, show_tqdm: Optional[bool] = True
    ) -> Dict[str, Dict[Annotated[str, "call or put"], pd.DataFrame]]:

        async def fetch_symbol(client: httpx.AsyncClient, symbol: str, session_token: tuple):
            try:
                fields_list = [
                    "strike",
                    "openPrice",
                    "highPrice",
                    "lowPrice",
                    "lastPrice",
                    "priceChange",
                    "bidPrice",
                    "askPrice",
                    "volume",
                    "openInterest",
                    "premium",
                    "tradeTime",
                    "longSymbol",
                    "optionType",
                    "symbol",
                    "symbolCode",
                    "symbolType",
                    "strikePrice",
                    "optionType",
                    "baseSymbol",
                    "optImpliedVolatility",
                    "delta",
                    "gamma",
                    "theta",
                    "vega",
                    "impliedVolatilitySkew",
                ]
                args = {
                    "symbol": f"{symbol}",
                    "list": "futures.options",
                    "fields": ",".join(fields_list),
                    "meta": "field.shortName,field.description,field.type,lists.lastUpdate",
                    "groupBy": "optionType",
                    "orderBy": "strike",
                    "orderDir": "asc",
                    "raw": "1",
                }
                url = f"https://www.barchart.com/proxies/core-api/v1/quotes/get?{urlencode(args)}"
                headers = {
                    "dnt": "1",
                    "referer": f"https://www.barchart.com/futures/quotes/{symbol}/options?futuresOptionsView=merged&moneyness=allRows&futuresOptionsTime=intraday",
                    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
                    "cookie": f"laravel_token={session_token[0]}",
                    "x-xsrf-token": session_token[1],
                }
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                json_data = response.json()["data"]

                return symbol, {
                    "call": pd.DataFrame([opt["raw"] for opt in json_data["Call"]]),
                    "put": pd.DataFrame([opt["raw"] for opt in json_data["Put"]]),
                }

            except Exception as e:
                self._logger.error(f"Failed to fetch option quotes from Barchart for {symbol}: {e}")

        async def run_all(symbols: list):
            tokens_tasks = [asyncio.to_thread(self._get_new_session_token) for _ in range(max_concurrent_tasks)]
            tokens_pool = await tqdm.asyncio.tqdm.gather(*tokens_tasks, desc="FETCHING SESSION TOKENS...")

            limits = httpx.Limits(max_connections=max_concurrent_tasks, max_keepalive_connections=max_keepalive_connections)
            async with httpx.AsyncClient(
                limits=limits,
                timeout=self._global_timeout,
                mounts=self._httpx_proxies,
                verify=False,
                http2=True,
            ) as client:
                tasks = [fetch_symbol(client, symbol, tokens_pool[i % len(tokens_pool)]) for i, symbol in enumerate(symbols)]
                if show_tqdm:
                    results = await tqdm.asyncio.tqdm.gather(*tasks, desc="FETCHING OPTION QUOTES...")
                else:
                    results = await asyncio.gather(*tasks)
                return dict(results)

        return asyncio.run(run_all(symbols))

    def get_single_option_quotes(self, symbol: str):
        fields_list = [
            "strike",
            "openPrice",
            "highPrice",
            "lowPrice",
            "lastPrice",
            "priceChange",
            "bidPrice",
            "askPrice",
            "volume",
            "openInterest",
            "premium",
            "tradeTime",
            "longSymbol",
            "optionType",
            "symbol",
            "symbolCode",
            "symbolType",
            "strikePrice",
            "optionType",
            "baseSymbol",
            "optImpliedVolatility",
            "delta",
            "gamma",
            "theta",
            "vega",
            "impliedVolatilitySkew",
        ]
        args = {
            "symbol": f"{symbol}",
            "list": "futures.options",
            "fields": ",".join(fields_list),
            "meta": "field.shortName,field.description,field.type,lists.lastUpdate",
            "groupBy": "optionType",
            "orderBy": "strike",
            "orderDir": "asc",
            "raw": "1",
        }
        url = f"https://www.barchart.com/proxies/core-api/v1/quotes/get?{urlencode(args)}"

        self._fetch_session_tokens()
        headers = {
            "dnt": "1",
            "referer": f"https://www.barchart.com/futures/quotes/{symbol}/options?futuresOptionsView=merged&moneyness=allRows&futuresOptionsTime=intraday",
            "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Google Chrome";v="132"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
            "cookie": f"laravel_token={self._current_laravel_token}",
            "x-xsrf-token": self._current_xsrf_token,
        }
        res = requests.get(url, headers=headers)
        return {
            "call": pd.DataFrame([opt["raw"] for opt in res.json()["data"]["Call"]]),
            "put": pd.DataFrame([opt["raw"] for opt in res.json()["data"]["Put"]]),
        }
