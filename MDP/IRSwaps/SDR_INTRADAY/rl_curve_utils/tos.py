from __future__ import annotations

import asyncio
import datetime
import os
import re
import time
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Literal, Optional, Callable, Union

import aiohttp
import pandas as pd
import pytz
import rateslib as rl
import requests
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from utils.rl_compat import rate_fixings_kwargs

us_bd = CustomBusinessDay(calendar=USFederalHolidayCalendar())
nytz = pytz.timezone("US/Eastern")

CME_MONTH_CODE = OrderedDict(
    [
        ("F", 1),  # January
        ("G", 2),  # February
        ("H", 3),  # March
        ("J", 4),  # April
        ("K", 5),  # May
        ("M", 6),  # June
        ("N", 7),  # July
        ("Q", 8),  # August
        ("U", 9),  # September
        ("V", 10),  # October
        ("X", 11),  # November
        ("Z", 12),  # December
    ]
)


def first_business_day_next_month(dt: pd.Timestamp) -> pd.Timestamp:
    # Move to 1st of the following month
    first_next_month = (dt + pd.DateOffset(months=1)).replace(day=1)
    # If it's a business day, keep it; else roll forward
    return first_next_month if us_bd.is_on_offset(first_next_month) else first_next_month + us_bd


def cme_code_effective_date(code: str) -> pd.Timestamp:
    """
    Parse a CME code (e.g., 'EDZ5', 'SR1Z25', 'SIZ2027', 'Z25') and return the
    first US-business day of that contract month (weekends + US federal holidays).
    """

    def _interpret_year(year_str: str, *, base_century_2digit: int = 2000) -> int:
        if len(year_str) == 4:
            return int(year_str)
        if len(year_str) == 2:
            yy = int(year_str)
            return base_century_2digit + yy if yy <= 69 else 1900 + yy
        if len(year_str) == 1:
            today = datetime.date.today()
            decade = (today.year // 10) * 10
            return decade + int(year_str)
        raise ValueError(f"Unrecognized year format: {year_str!r}")

    code = code.strip().upper()
    # allow alphanumeric product prefixes like "SR1"
    m = re.search(r"([A-Z0-9]*?)([FGHJKMNQUVXZ])(\d{1,4})$", code)
    if not m:
        raise ValueError(f"Could not parse CME code: {code!r}")
    _prod, month_letter, year_str = m.groups()

    if month_letter not in CME_MONTH_CODE:
        raise ValueError(f"Invalid month code: {month_letter!r}")

    year = _interpret_year(year_str)
    month = CME_MONTH_CODE[month_letter]

    # First calendar day of the month
    first = pd.Timestamp(year=year, month=month, day=1)

    # US business day calendar (weekends + US federal holidays)
    cbd = CustomBusinessDay(calendar=USFederalHolidayCalendar())

    # Use is_on_offset for broad pandas compatibility
    eff = first if cbd.is_on_offset(first) else first + cbd
    return eff


def build_rl_stirf(ticker: str, curve_id: str, price: float, fixings: pd.Series = None, use_globex=True):
    ser_key = "/SR1" if use_globex else "SER"
    sfr_key = "/SR3" if use_globex else "SFR"

    def build_rl_ser(month: str, curve_id: str, price: float):
        return f"{ser_key}{month}", rl.STIRFuture(
            effective=cme_code_effective_date(month),
            termination=first_business_day_next_month(pd.Timestamp(cme_code_effective_date(month))),
            spec="usd_stir1",
            roll="som",
            curves=curve_id,
            price=price,
            **rate_fixings_kwargs(fixings),
        )

    def build_rl_sfr(month: str, curve_id: str, price: float):
        return f"{sfr_key}{month}", rl.STIRFuture(
            effective=rl.scheduling.get_imm(code=month),
            termination=rl.scheduling.next_imm(rl.scheduling.get_imm(code=month)),
            spec="usd_stir",
            curves=curve_id,
            price=price,
            # **rate_fixings_kwargs(fixings)
        )

    if ser_key in ticker:
        return build_rl_ser(month=ticker.replace(ser_key, ""), curve_id=curve_id, price=price)
    elif sfr_key in ticker:
        return build_rl_sfr(month=ticker.replace(sfr_key, ""), curve_id=curve_id, price=price)

    raise ValueError("Bad Ticker passed in")


def get_sofr_fixings(n=90):
    url = f"https://markets.newyorkfed.org/api/rates/secured/sofr/last/{n}.json"
    res = requests.get(url, headers={"accept": "application/json"})
    df = pd.DataFrame(res.json()["refRates"])
    df["effectiveDate"] = pd.to_datetime(df["effectiveDate"])
    df["percentRate"] = pd.to_numeric(df["percentRate"])
    df = df.set_index("effectiveDate").sort_index()
    return df["percentRate"]


def _third_wednesday(year: int, month: int) -> datetime.date:
    """IMM date = third Wednesday of the month."""
    first = datetime.date(year, month, 1)
    # Monday=0 ... Sunday=6; Wednesday=2
    offset = (2 - first.weekday()) % 7
    first_wed = first + datetime.timedelta(days=offset)
    return first_wed + datetime.timedelta(days=14)  # 3rd Wed


def _monthly_cutoff(year: int, month: int) -> datetime.date:
    """Cutoff at the start of the next month: include current month until EOM."""
    if month == 12:
        return datetime.date(year + 1, 1, 1)
    return datetime.date(year, month + 1, 1)


def _imm_cutoff(year: int, month: int) -> datetime.date:
    """First date an IMM quarterly month is no longer forward-starting: IMM + 1.

    ``_next_contracts`` drops a month once ``as_of >= cutoff``, so the cutoff is
    an EXCLUSIVE upper bound and the ``+ 1`` is what **keeps the contract on its
    own IMM date**. An SR3 contract references the quarter that BEGINS at its
    IMM date, so on that date zero of its ~91 days have been observed: it is the
    last moment of purely forward-starting and the first moment of the new
    quarter at once. Both readings are defensible from CME's text -- "the
    nearest four forward-starting quarterly delivery months" does not adjudicate
    a zero-day-elapsed accrual -- so it was settled on evidence instead:

    * **The vendor "corroboration" was circular.** ``SFRCM1`` never reaches
      Barchart; it is our own alias, resolved in-process by
      ``STIRFutureMDP._resolve_aliases_bulk`` through this very function, and
      the wire request on 2023-06-21 is the dated symbol ``SQU23``. So the
      continuous ladder rolling a day earlier was this line reading itself back.
    * **The settlement grid says the starting contract is the live one.** SR3
      trades on a 0.0025 grid and finally settles at ``100 - compounded SOFR``,
      which is essentially never on it. Classifying every quarterly IMM date
      2018-2026 in the local store: the ENDING contract is off-grid 18/18 (it
      has settled), the STARTING contract is on-grid 32/32 (it is tradable).
      2023-06-21: ``SR3H23 px=95.0571`` (settlement), ``SR3M23 px=94.7700``.
    * **Intraday, same date, same fetch:** the ending contract has 0 rows (or 1,
      the settlement); the starting contract has 1,262 rows across 8-21 distinct
      prices, and its quoted life runs from that day to the end of its reference
      quarter -- ``SR3M23``: 64 quoted dates, 2023-06-21 to 2023-09-20.
    * **T1 never goes negative either way.** ``packs.pack_t1s`` puts the front
      leg at exactly 0.0 on the IMM date under this convention; the strict rule
      rolled one day early, while a T1 = 0 still-listed contract was admissible.

    Dropping it deleted the largest-open-interest contract from the *entire*
    ladder for one session a quarter, which is not a labelling nicety.

    **This does not undo the roll.** The cutoff still fires the very next day,
    which is the property the strict version was introduced for -- see
    ``get_short_end_curve_tickers``: "SR3 rolls on IMM (3rd Wednesday) -- this
    fixes the U25 issue after 2025-09-17". On 2025-09-17 the front is now
    ``SR3U25``; on 2025-09-18 it is ``SR3Z25``, exactly as before. Because dates
    are whole days, ``as_of < cutoff`` can only change on the IMM date itself,
    so no other date in the repo can move -- verified over a 1,946-date panel
    rebuild in which every non-IMM row was bit-identical.

    Non-quarterly months are untouched: this is a statement about an IMM accrual
    period, not about month ends, so serial SR1/ZQ months keep
    :func:`_monthly_cutoff`.

    The full write-up, and the list of every site that inherits this, is in
    ``RVUtils/ConvexityRV/packs.py``'s module docstring.
    """
    if month in (3, 6, 9, 12):
        return _third_wednesday(year, month) + datetime.timedelta(days=1)
    return _monthly_cutoff(year, month)


def _next_contracts(
    start_date: datetime.date,
    prefix: str,
    count: int,
    valid_months: Optional[Iterable[int]] = None,
    cutoff_fn: Optional[Callable[[int, int], datetime.date]] = None,
) -> List[str]:
    """
    Return next `count` futures symbols starting from `start_date`, skipping any month
    whose cutoff date is <= start_date (i.e., start_date >= cutoff).
    """
    if valid_months is None:
        valid_months = list(CME_MONTH_CODE.values())
    valid_months = set(valid_months)

    # Sort months by numeric month (1..12) to ensure correct progression.
    months_sorted = sorted(CME_MONTH_CODE.items(), key=lambda kv: kv[1])  # [(code, month_num), ...]
    month_to_code = {m: c for c, m in months_sorted}

    # Default cutoff: monthly (first day of next month)
    if cutoff_fn is None:
        cutoff_fn = _monthly_cutoff

    y = start_date.year
    m = start_date.month

    # Start from the current calendar month
    idx = next(i for i, (_, mn) in enumerate(months_sorted) if mn == m)

    # Advance to the first eligible month (as_of < cutoff AND in valid_months)
    while True:
        code, mn = months_sorted[idx]
        cutoff = cutoff_fn(y, mn)
        if (mn in valid_months) and (start_date < cutoff):
            break
        # advance month/year
        idx += 1
        if idx == 12:
            idx = 0
            y += 1

    # Collect `count` symbols
    out: List[str] = []
    yy = y
    ii = idx
    while len(out) < count:
        code, mn = months_sorted[ii]
        if mn in valid_months:
            out.append(f"{prefix}{code}{yy % 100:02d}")
        ii += 1
        if ii == 12:
            ii = 0
            yy += 1

    return out


def get_short_end_curve_tickers(
    as_of: Union[datetime.date, datetime.datetime, str],
    first_n_sr1: int,
    first_n_sr3: int,
    include_serff: bool = False,
    use_globex: bool = True,
) -> List[str]:
    if as_of == "live":
        as_of_date = datetime.datetime.now().date()
    elif isinstance(as_of, datetime.datetime):
        as_of_date = as_of.date()
    else:
        as_of_date = as_of  # already a date

    sr1_months = list(CME_MONTH_CODE.values())  # all months for 1M SOFR
    sr3_months = [3, 6, 9, 12]  # IMM months for 3M SOFR

    sr1_prefix = "/SR1" if use_globex else "SER"
    sr3_prefix = "/SR3" if use_globex else "SFR"

    # SR1 rolls at start of next month (monthly cutoff)
    sr1_list = _next_contracts(as_of_date, sr1_prefix, first_n_sr1, valid_months=sr1_months, cutoff_fn=_monthly_cutoff)

    # SR3 rolls the day AFTER IMM (3rd Wednesday) — this fixes the U25 issue after
    # 2025-09-17 and still keeps U25 itself on the 17th, whose reference quarter
    # starts that day. See `_imm_cutoff`.
    sr3_list = _next_contracts(as_of_date, sr3_prefix, first_n_sr3, valid_months=sr3_months, cutoff_fn=_imm_cutoff)

    if include_serff:
        # Map SR1 to Fed Funds equivalents
        zq_prefix = "/ZQ" if use_globex else "FF"
        zq_list = [c.replace(sr1_prefix, zq_prefix) for c in sr1_list]
        return sr1_list + zq_list + sr3_list

    return sr1_list + sr3_list


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
        if sym == "errors":
            continue
        q = data.get("quote", {}) or {}
        out[sym] = {
            "bid": q.get("bidPrice"),
            "ask": q.get("askPrice"),
            "mid": (q.get("bidPrice") + q.get("askPrice")) / 2,
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
    app_key: Optional[str] = "zm3GYiQREbtrpBHACURcNzFJIObUq2aX",
    app_secret: Optional[str] = "SznUHXvKPZUnmxG9",
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

    app_key = app_key or os.getenv("SCHWAB_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET")
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
    app_key: Optional[str] = "zm3GYiQREbtrpBHACURcNzFJIObUq2aX",
    app_secret: Optional[str] = "SznUHXvKPZUnmxG9",
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

    app_key = app_key or os.getenv("SCHWAB_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET")
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
    app_key: Optional[str] = "zm3GYiQREbtrpBHACURcNzFJIObUq2aX",
    app_secret: Optional[str] = "SznUHXvKPZUnmxG9",
    scope: str = "pystonk",
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """
    Fetch quotes for multiple symbols via /marketdata/v1/quotes and return a DataFrame indexed by symbol.
    """
    app_key = app_key or os.getenv("SCHWAB_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET")
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
    app_key = app_key or os.getenv("SCHWAB_APP_KEY")
    app_secret = app_secret or os.getenv("SCHWAB_APP_SECRET")
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
