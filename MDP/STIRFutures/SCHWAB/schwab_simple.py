from __future__ import annotations

import os
import time
from typing import Iterable, Optional, Literal, Dict, Any

import requests
import pandas as pd
import datetime

import aiohttp
import asyncio


TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
PRICE_URL = "https://api.schwabapi.com/marketdata/v1/pricehistory"
QUOTES_URL = "https://api.schwabapi.com/marketdata/v1/quotes"

_ALLOWED_PERIOD_TYPE = {"day", "month", "year", "ytd"}
_ALLOWED_FREQ_TYPE = {"minute", "daily", "weekly", "monthly"}

ValueCol = Literal["open", "high", "low", "close", "volume"]

_token_cache: Dict[str, str] = {}  # key -> access_token
_token_expiry: Dict[str, float] = {}  # key -> epoch seconds


def _get_access_token(app_key: str, app_secret: str, scope: str = None) -> str:
    """
    Fetch and cache a client_credentials access token.
    Cache key is (app_key, scope).
    """
    if not app_key:
        raise ValueError("Missing app_key")
    if not app_secret:
        raise ValueError("Missing app_secret")

    cache_key = f"{app_key}:{scope}"
    now = time.time()

    # Reuse if not expired (assume 25 min TTL unless server says otherwise).
    # If you want to be exact, parse expires_in from the response and store it.
    if cache_key in _token_cache and _token_expiry.get(cache_key, 0) > now:
        return _token_cache[cache_key]

    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials", "scope": scope},
        auth=(app_key, app_secret),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    token = data.get("access_token")
    if not token:
        raise ValueError(f"Token response missing 'access_token': {data}")

    expires_in = int(data.get("expires_in", 300))
    _token_cache[cache_key] = token
    _token_expiry[cache_key] = now + max(60, expires_in - 60)  # refresh a bit early
    return token


def _normalize_choice(name: str, val: Optional[str], allowed: set[str], default: str) -> str:
    if val is None:
        return default
    v = str(val).strip().lower()
    if v not in allowed:
        raise ValueError(f"Invalid {name}='{val}'. Allowed: {sorted(allowed)}")
    return v


def _comma_list(val: Optional[Iterable[str] | str]) -> Optional[str]:
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return ",".join([str(x).strip() for x in val if str(x).strip()])


def _to_bool_str(b: Optional[bool]) -> Optional[str]:
    if b is None:
        return None
    return "true" if b else "false"


def _normalize_symbols(symbols: Iterable[str]) -> str:
    syms = [str(s).strip().upper() for s in symbols if str(s).strip()]
    if not syms:
        raise ValueError("No symbols provided")
    return ",".join(syms)


def _normalize_quotes_payload(payload: dict) -> dict:
    """
    Given Schwab quotes payload, return a flat dict with only:
    bid, ask, last, bidSize, askSize, mark, netChange.

    Parameters
    ----------
    payload : dict
        JSON-decoded response from Schwab /quotes endpoint.

    Returns
    -------
    dict
        Example:
        {
            'bid': 96.235,
            'ask': 96.24,
            'last': 96.235,
            'bidSize': 7870,
            'askSize': 7852,
            'mark': 96.235,
            'netChange': -0.07
        }
    """
    out = {}
    for sym, data in payload.items():
        q = data.get("quote", {}) or {}
        try:
            mid = (q.get("bidPrice") + q.get("askPrice")) / 2
        except:
            mid = None
        out[sym] = {
            "bid": q.get("bidPrice"),
            "ask": q.get("askPrice"),
            "mid": mid, 
            "last": q.get("lastPrice"),
            "bidSize": q.get("bidSize"),
            "askSize": q.get("askSize"),
            "mark": q.get("mark"),
            "netChange": q.get("netChange"),
            "quoteTime": q.get("quoteTime"),
        }
    return out


async def _get_access_token_async(
    app_key: str,
    app_secret: str,
    scope: str = "pystonk",
    session: Optional[aiohttp.ClientSession] = None,
) -> str:
    if not app_key or not app_secret:
        raise ValueError("Provide app_key/app_secret")

    cache_key = f"{app_key}:{scope}"
    now = time.time()
    if cache_key in _token_cache and _token_expiry.get(cache_key, 0) > now:
        return _token_cache[cache_key]

    owns_session = False
    if session is None:
        session = aiohttp.ClientSession()
        owns_session = True
    try:
        auth = aiohttp.BasicAuth(app_key, app_secret)
        async with session.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": scope},
            auth=auth,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        token = data.get("access_token")
        if not token:
            raise ValueError(f"Token response missing 'access_token': {data}")

        expires_in = int(data.get("expires_in", 1500))
        _token_cache[cache_key] = token
        _token_expiry[cache_key] = now + max(60, expires_in - 60)
        return token
    finally:
        if owns_session:
            await session.close()


async def _fetch_one(
    symbol: str,
    *,
    token: str,
    session: aiohttp.ClientSession,
    period_type: str,
    period: int,
    frequency_type: str,
    frequency: int,
    retries: int = 2,
    backoff: float = 0.8,
) -> pd.DataFrame:
    params = {
        "symbol": symbol,
        "periodType": period_type,
        "period": period,
        "frequencyType": frequency_type,
        "frequency": frequency,
        "needExtendedHoursData": "false",
        "needPreviousClose": "false",
    }
    headers = {"Authorization": f"Bearer {token}"}
    attempt = 0
    while True:
        try:
            async with session.get(
                PRICE_URL,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                payload: Dict[str, Any] = await resp.json()
            candles = payload.get("candles", [])
            if not candles:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "symbol"]).set_index(pd.DatetimeIndex([], name="datetime"))

            df = pd.DataFrame.from_records(candles)
            req = {"open", "high", "low", "close", "volume", "datetime"}
            missing = req - set(df.columns)
            if missing:
                raise ValueError(f"{symbol}: missing keys {sorted(missing)}")

            df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
            df.set_index("datetime", inplace=True)
            for c in ("open", "high", "low", "close"):
                df[c] = df[c].round(2)
            df["symbol"] = symbol
            df = df.sort_index()
            return df
        except Exception as e:
            if attempt >= retries:
                raise
            await asyncio.sleep(backoff * (2**attempt))
            attempt += 1


async def _get_price_histories_async(
    symbols: Iterable[str],
    *,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    period_type: str = "ytd",
    period: int = 1,
    frequency_type: str = "daily",
    frequency: int = 1,
    value_col: ValueCol = "close",
    scope: str = "pystonk",
    join: Literal["outer", "inner"] = "outer",
    max_concurrency: int = 8,
    return_all_fields: bool = False,  # if True, returns dict of DataFrames per symbol
) -> pd.DataFrame | Dict[str, pd.DataFrame]:
    """
    Async multi-symbol fetch. Returns a wide DataFrame of `value_col` by default.

    If `return_all_fields=True`, returns {symbol: DataFrame(OHLCV)} instead.
    """
    syms = [s.upper() for s in symbols if str(s).strip()]
    if not syms:
        raise ValueError("No symbols provided")

    period_type = _normalize_choice("period_type", period_type, _ALLOWED_PERIOD_TYPE, "ytd")
    frequency_type = _normalize_choice("frequency_type", frequency_type, _ALLOWED_FREQ_TYPE, "daily")

    if not isinstance(period, int) or period <= 0:
        raise ValueError("period must be a positive integer")
    if not isinstance(frequency, int) or frequency <= 0:
        raise ValueError("frequency must be a positive integer")
    if value_col not in {"open", "high", "low", "close", "volume"}:
        raise ValueError("value_col must be one of: open, high, low, close, volume")

    app_key = app_key or os.getenv("SCHWAB_APP_KEY", "zm3GYiQREbtrpBHACURcNzFJIObUq2aX")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET", "SznUHXvKPZUnmxG9")
    if not app_key or not app_secret:
        raise ValueError("Provide app_key/app_secret or set SCHWAB_APP_KEY / SCHWAB_APP_SECRET")

    async with aiohttp.ClientSession() as session:
        token = await _get_access_token_async(app_key, app_secret, scope=scope, session=session)

        sem = asyncio.Semaphore(max_concurrency)

        async def bounded(sym: str) -> tuple[str, pd.DataFrame]:
            async with sem:
                df = await _fetch_one(
                    sym,
                    token=token,
                    session=session,
                    period_type=period_type,
                    period=period,
                    frequency_type=frequency_type,
                    frequency=frequency,
                )
                return sym, df

        results = await asyncio.gather(*(bounded(s) for s in syms), return_exceptions=True)

    # Collect successes and (optionally) raise aggregated errors
    dfs: Dict[str, pd.DataFrame] = {}
    errors: Dict[str, Exception] = {}
    for res in results:
        if isinstance(res, Exception):
            # this only happens if gather itself failed (rare); keep simple
            raise res
        sym, df = res
        if df is None or df.empty:
            errors[sym] = RuntimeError("empty dataframe")
        else:
            dfs[sym] = df

    if return_all_fields:
        # caller handles alignment downstream
        return dfs

    # Build wide frame of `value_col`
    series_list = []
    for sym, df in dfs.items():
        if value_col not in df.columns:
            errors[sym] = RuntimeError(f"missing column {value_col}")
            continue
        s = df[value_col].rename(sym)
        series_list.append(s)

    if not series_list:
        # if everything failed/empty, return empty
        return pd.DataFrame()

    wide = pd.concat(series_list, axis=1, join=join).sort_index()
    return wide


def get_price_histories(
    symbols: Iterable[str],
    *,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    period_type: str = "ytd",
    period: int = 1,
    frequency_type: str = "daily",
    frequency: int = 1,
    value_col: ValueCol = "close",
    scope: str = "pystonk",
    join: Literal["outer", "inner"] = "outer",
    max_concurrency: int = 8,
    return_all_fields: bool = False,
) -> pd.DataFrame | Dict[str, pd.DataFrame]:
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(
        _get_price_histories_async(
            symbols,
            app_key=app_key,
            app_secret=app_secret,
            period_type=period_type,
            period=period,
            frequency_type=frequency_type,
            frequency=frequency,
            value_col=value_col,
            scope=scope,
            join=join,
            max_concurrency=max_concurrency,
            return_all_fields=return_all_fields,
        )
    )


def get_price_history(
    symbol: str,
    start: datetime.datetime,
    end: datetime.datetime,
    *,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    period_type: str = "ytd",  # one of: day, month, year, ytd
    period: int = 1,
    frequency_type: str = "daily",  # one of: minute, daily, weekly, monthly
    frequency: int = 1,
    scope: str = "pystonk",
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """
    Return OHLCV price history for `symbol` as a pandas DataFrame indexed by UTC datetime.

    Parameters
    ----------
    symbol : str
        Ticker symbol (case-insensitive).
    app_key, app_secret : str
        Schwab API app credentials. If omitted, reads SCHWAB_APP_KEY / SCHWAB_APP_SECRET from env.
    period_type : {'day','month','year','ytd'}
    period : int
    frequency_type : {'minute','daily','weekly','monthly'}
    frequency : int
    scope : str
        OAuth scope (default 'pystonk').
    session : requests.Session, optional
        Provide to reuse connections.

    Returns
    -------
    pd.DataFrame with columns: ['open','high','low','close','volume','symbol'] and a UTC DatetimeIndex.
    """
    if not symbol:
        raise ValueError("symbol is required")
    symbol = symbol.upper()

    app_key = app_key or os.getenv("SCHWAB_APP_KEY", "zm3GYiQREbtrpBHACURcNzFJIObUq2aX")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET", "SznUHXvKPZUnmxG9")
    if not app_key or not app_secret:
        raise ValueError("Provide app_key/app_secret or set SCHWAB_APP_KEY / SCHWAB_APP_SECRET env vars.")

    period_type = _normalize_choice("period_type", period_type, _ALLOWED_PERIOD_TYPE, "ytd")
    frequency_type = _normalize_choice("frequency_type", frequency_type, _ALLOWED_FREQ_TYPE, "daily")

    if not isinstance(period, int) or period <= 0:
        raise ValueError("period must be a positive integer")
    if not isinstance(frequency, int) or frequency <= 0:
        raise ValueError("frequency must be a positive integer")

    token = _get_access_token(app_key, app_secret, scope=scope)
    sess = session or requests.Session()

    params = {
        "symbol": symbol,
        # "periodType": period_type,
        # "period": period,
        # "frequencyType": frequency_type,
        # "frequency": frequency,
        "startDate": int(start.timestamp() * 1000),
        "endDate": int(end.timestamp() * 1000),
        # "needExtendedHoursData": "",
        # "needPreviousClose": "true",
    }
    headers = {"Authorization": f"Bearer {token}"}

    print(PRICE_URL)
    print(params)
    resp = sess.get(PRICE_URL, params=params, headers=headers, timeout=30)

    resp.raise_for_status()
    payload = resp.json()

    candles = payload.get("candles", [])
    if not isinstance(candles, list) or not candles:
        # Return empty, well-formed frame for consistency
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "symbol"]).set_index(pd.DatetimeIndex([], name="datetime"))

    df = pd.DataFrame.from_records(candles)
    # Expected keys: 'open','high','low','close','volume','datetime' (ms since epoch)
    required = {"open", "high", "low", "close", "volume", "datetime"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Unexpected API shape, missing keys: {sorted(missing)}")

    df["datetime"] = pd.to_datetime(df["datetime"], unit="ms", utc=True)
    df.set_index("datetime", inplace=True)
    df.rename(columns={"open": "open", "high": "high", "low": "low", "close": "close", "volume": "volume"}, inplace=True)
    df["symbol"] = symbol

    # Round prices to 2dp to mirror original behavior
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].round(2)

    # Sort by time just in case
    df = df.sort_index()

    return df


def get_quotes(
    symbols: Iterable[str],
    *,
    fields: Optional[Iterable[str] | str] = None,  # e.g. "all", "quote", "fundamental"
    indicative: Optional[bool] = None,  # True->indicative quotes
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    scope: str = "pystonk",
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """
    Fetch quotes for multiple symbols via /marketdata/v1/quotes and return a DataFrame indexed by symbol.
    """
    app_key = app_key or os.getenv("SCHWAB_APP_KEY", "zm3GYiQREbtrpBHACURcNzFJIObUq2aX")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET", "SznUHXvKPZUnmxG9")
    if not app_key or not app_secret:
        raise ValueError("Provide app_key/app_secret or set SCHWAB_APP_KEY / SCHWAB_APP_SECRET")

    token = _get_access_token(app_key, app_secret, scope=scope)
    sess = session or requests.Session()

    params = {
        "symbols": _normalize_symbols(symbols),
        "fields": _comma_list(fields),
        "indicative": _to_bool_str(indicative),
    }
    # remove Nones
    params = {k: v for k, v in params.items() if v is not None}

    resp = sess.get(QUOTES_URL, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    return _normalize_quotes_payload(payload)


# -------- Optional async variant (matches your style above) ------------------


async def get_quotes_async(
    symbols: Iterable[str],
    *,
    fields: Optional[Iterable[str] | str] = None,
    indicative: Optional[bool] = None,
    app_key: Optional[str] = None,
    app_secret: Optional[str] = None,
    scope: str = "pystonk",
    session: Optional[aiohttp.ClientSession] = None,
) -> pd.DataFrame:
    app_key = app_key or os.getenv("SCHWAB_APP_KEY", "zm3GYiQREbtrpBHACURcNzFJIObUq2aX")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET", "SznUHXvKPZUnmxG9")
    if not app_key or not app_secret:
        raise ValueError("Provide app_key/app_secret or set SCHWAB_APP_KEY / SCHWAB_APP_SECRET")

    owns = False
    if session is None:
        session = aiohttp.ClientSession()
        owns = True
    try:
        token = await _get_access_token_async(app_key, app_secret, scope=scope, session=session)
        params = {
            "symbols": _normalize_symbols(symbols),
            "fields": _comma_list(fields),
            "indicative": _to_bool_str(indicative),
        }
        params = {k: v for k, v in params.items() if v is not None}

        async with session.get(
            QUOTES_URL,
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            payload = await resp.json()

        return _normalize_quotes_payload(payload)
    finally:
        if owns:
            await session.close()
