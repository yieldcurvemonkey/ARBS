import datetime
import logging
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, Optional, Sequence, Tuple

import pandas as pd
from tvDatafeed import Interval, TvDatafeed


def fetch_cusip_prices_eod_timeseries(
    cusip: str,
    start: datetime.date,
    end: datetime.date,
    val_to_return: str = "close",
    *,
    tv: Optional[TvDatafeed] = None,
) -> pd.Series:
    with _silence_loggers(("tvDatafeed", "tvDatafeed.main")):
        # Create a local client if none provided (safer for threaded use)
        local_tv = tv or TvDatafeed()

        df = local_tv.get_hist(
            symbol=cusip,
            exchange="OTCB",
            interval=Interval.in_daily,
            n_bars=10000,
        )
        if df is None or df.empty:
            return pd.Series(name=cusip, dtype="float64")

        ts = df.loc[(df.index.date >= start) & (df.index.date <= end), val_to_return].copy()
        ts.name = cusip

        # Append latest 1-min bar if end is today
        if end == datetime.date.today():
            live = local_tv.get_hist(
                symbol=cusip,
                exchange="OTCB",
                interval=Interval.in_1_minute,
                n_bars=1,
            )
            if live is not None and not live.empty and val_to_return in live.columns:
                live_s = live[val_to_return].copy()
                live_s.name = cusip
                ts = pd.concat([ts, live_s])

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
            lg.propagate = False  # prevents bubbling to root handlers
        yield
    finally:
        for lg, lvl, prop in zip(loggers, old_levels, old_propagate):
            lg.setLevel(lvl)
            lg.propagate = prop


def fetch_cusip_prices_eod_timeseries_parallel(
    cusips: Sequence[str],
    start: datetime.date,
    end: datetime.date,
    val_to_return: str = "close",
    *,
    max_workers: Optional[int] = None,
    raise_on_error: bool = False,
) -> pd.DataFrame:
    """
    Returns:
      (df, errors)
        df: columns = cusips, index = timestamps
        errors: cusip -> exception (only for failures)
    """
    cusips = list(dict.fromkeys(cusips))  # de-dupe, preserve order
    if not cusips:
        return pd.DataFrame(), {}

    if max_workers is None:
        max_workers = min(16, len(cusips))

    results: Dict[str, pd.Series] = {}
    errors: Dict[str, Exception] = {}

    def _worker(c: str) -> pd.Series:
        with _silence_loggers(("tvDatafeed", "tvDatafeed.main")):
            return fetch_cusip_prices_eod_timeseries(c, start, end, val_to_return, tv=None)

    with _suppress_warnings():
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut_map = {ex.submit(_worker, c): c for c in cusips}
            for fut in as_completed(fut_map):
                c = fut_map[fut]
                try:
                    results[c] = fut.result()
                except Exception as e:
                    errors[c] = e
                    if raise_on_error:
                        raise

    df = pd.concat(results, axis=1) if results else pd.DataFrame()
    if not df.empty:
        df = df.sort_index()

    return df 
