import datetime
import logging
import random
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from queue import Queue
from typing import Dict, Iterable, Iterator, Optional, Sequence, Tuple

import pandas as pd
import QuantLib as ql
import tqdm
from tvDatafeed import Interval, TvDatafeed


def _us_gov_bizday_index(start: datetime.date, end: datetime.date) -> pd.DatetimeIndex:
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    d = start
    out = []
    one = datetime.timedelta(days=1)
    while d <= end:
        qd = ql.Date(d.day, d.month, d.year)
        if cal.isBusinessDay(qd):
            out.append(pd.Timestamp(d))  # midnight
        d += one
    return pd.DatetimeIndex(out)


def fetch_cusip_prices_eod_timeseries(
    cusip: str,
    start: datetime.date,
    end: datetime.date,
    val_to_return: str = "close",
    *,
    tv: Optional[TvDatafeed] = None,
) -> pd.Series:
    with _silence_loggers(("tvDatafeed", "tvDatafeed.main")):
        local_tv = tv or TvDatafeed()

        df = local_tv.get_hist(
            symbol=cusip,
            exchange="OTCB",
            interval=Interval.in_daily,
            n_bars=10000,
        )
        if df is None or df.empty:
            return pd.Series(name=cusip, dtype="float64")

        start = start - datetime.timedelta(days=3)
        end = end + datetime.timedelta(days=3)
        ts = df.loc[(df.index.date >= start) & (df.index.date <= end), val_to_return].copy()
        ts.name = cusip

        live_val = None
        if end == datetime.date.today():
            live = local_tv.get_hist(
                symbol=cusip,
                exchange="OTCB",
                interval=Interval.in_1_minute,
                n_bars=1,
            )
            if live is not None and not live.empty and val_to_return in live.columns:
                live_val = float(live[val_to_return].iloc[-1])

        # --- forward-fill to QuantLib US Gov business days ---
        ts.index = pd.to_datetime(ts.index).normalize()
        ts = ts.groupby(level=0).last()  # de-dupe if needed

        idx = _us_gov_bizday_index(start, end)
        ts = ts.reindex(idx).ffill()
        ts.name = cusip

        # if you pulled a live point for today, pin it to today's business-day slot
        if live_val is not None:
            ts.loc[pd.Timestamp(end)] = live_val

        return ts


@contextmanager
def _suppress_warnings() -> Iterator[None]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


@contextmanager
def _silence_loggers(names: Iterable[str], level: int = logging.ERROR) -> Iterator[None]:
    loggers = [logging.getLogger(n) for n in names]
    old_levels = [lg.level for lg in loggers]
    old_propagate = [lg.propagate for lg in loggers]
    try:
        for lg in loggers:
            lg.setLevel(level)
            lg.propagate = False
        yield
    finally:
        for lg, lvl, prop in zip(loggers, old_levels, old_propagate):
            lg.setLevel(lvl)
            lg.propagate = prop


def _looks_throttled(series: pd.Series, *, start: datetime.date, end: datetime.date) -> bool:
    # Heuristic: empty result for a non-trivial window is more likely throttling/limit
    # than "truly no data".
    if series is None or series.empty:
        return (end - start).days >= 1
    # also treat "all NaN" as a failed fetch
    return series.isna().all()


def _is_retryable_exc(e: Exception) -> bool:
    msg = str(e).lower()
    # tvDatafeed / tradingview errors are not standardized; keep this broad.
    return any(k in msg for k in ("throttle", "rate", "limit", "too many", "timeout", "temporar", "reset", "429"))


def _backoff_sleep(attempt: int, *, base: float, cap: float) -> None:
    # exp backoff + jitter
    delay = min(cap, base * (2**attempt))
    delay *= 0.75 + random.random() * 0.5
    time.sleep(delay)


def fetch_cusip_prices_eod_timeseries_parallel(
    cusips: Sequence[str],
    start: datetime.date,
    end: datetime.date,
    val_to_return: str = "close",
    *,
    max_workers: Optional[int] = None,
    # NEW:
    max_parallel_tv_clients: int = 6,  # true parallelism ceiling you observed
    max_attempts: int = 4,  # per-cusip attempts when throttled
    backoff_base: float = 0.5,
    backoff_cap: float = 8.0,
    raise_on_error: bool = False,
) -> Tuple[pd.DataFrame, Dict[str, Exception]]:
    # """
    # Returns:
    #   (df, errors)
    #     df: columns = cusips, index = timestamps
    #     errors: cusip -> exception (only for failures)

    # Key behavior:
    #   - Uses a fixed pool of `max_parallel_tv_clients` TvDatafeed clients, so only that many
    #     requests can run concurrently.
    #   - Automatically refetches when a fetch looks throttled (empty/all-NaN series) or throws
    #     a retryable exception.
    # """
    # cusips = list(dict.fromkeys(cusips))  # de-dupe, preserve order
    # if not cusips:
    #     return pd.DataFrame(), {}

    # if max_workers is None:
    #     # threads can exceed TV clients; the TV pool enforces the real concurrency
    #     max_workers = min(32, len(cusips))

    # # Build a *bounded* pool of TvDatafeed clients so we never create >6 connections.
    # tv_pool: "Queue[TvDatafeed]" = Queue(maxsize=max_parallel_tv_clients)

    # with _silence_loggers(("tvDatafeed", "tvDatafeed.main")):
    #     for _ in range(max_parallel_tv_clients):
    #         tv_pool.put(TvDatafeed())

    # results: Dict[str, pd.Series] = {}
    # errors: Dict[str, Exception] = {}

    # def _worker(c: str) -> pd.Series:
    #     last_series: Optional[pd.Series] = None
    #     last_exc: Optional[Exception] = None

    #     for attempt in range(max_attempts):
    #         tv = tv_pool.get()  # blocks until a client is available
    #         try:
    #             s = fetch_cusip_prices_eod_timeseries(c, start, end, val_to_return)
    #             last_series = s

    #             # If it looks throttled, back off and retry.
    #             if _looks_throttled(s, start=start, end=end) and attempt < (max_attempts - 1):
    #                 _backoff_sleep(attempt, base=backoff_base, cap=backoff_cap)
    #                 continue

    #             return s

    #         except Exception as e:
    #             last_exc = e
    #             if _is_retryable_exc(e) and attempt < (max_attempts - 1):
    #                 _backoff_sleep(attempt, base=backoff_base, cap=backoff_cap)
    #                 continue
    #             raise
    #         finally:
    #             tv_pool.put(tv)

    #     # Should be unreachable because we either returned or raised,
    #     # but keep a safe fallback.
    #     if last_series is not None:
    #         return last_series
    #     raise last_exc or RuntimeError(f"Failed fetching {c} with unknown error")

    # with _suppress_warnings():
    #     with ThreadPoolExecutor(max_workers=max_workers) as ex:
    #         fut_map = {ex.submit(_worker, c): c for c in cusips}
    #         for fut in as_completed(fut_map):
    #             c = fut_map[fut]
    #             try:
    #                 results[c] = fut.result()
    #             except Exception as e:
    #                 errors[c] = e
    #                 if raise_on_error:
    #                     raise

    results = []
    for cusip in tqdm.tqdm(cusips, desc="FETCHING CUSIPS..."):
        results.append(fetch_cusip_prices_eod_timeseries(cusip=cusip, start=start, end=end))

    non_empty = [r for r in results if not r.empty]
    df = pd.concat(non_empty, axis=1) if non_empty else pd.DataFrame()
    if not df.empty:
        df = df.sort_index()

    if df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    return df[(df.index.date >= start) & (df.index.date <= end)]
