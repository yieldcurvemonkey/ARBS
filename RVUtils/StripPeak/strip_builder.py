"""Build a daily rate-strip for the front N SR3 quarterly contracts."""
from __future__ import annotations

import asyncio
import datetime
import os
from pathlib import Path
from typing import List

# Literal first ARBS-internal statement, before any third-party or repo import: several
# modules in this repo (``Caching.supabase_engine``) read ``ARBS_SUPABASE_ENABLED`` as a
# module global at import time, so setting it any later than this is a no-op for whatever
# already imported that module. See Caching/l2_policy.py's docstring for the incident this
# convention comes from.
os.environ.setdefault("ARBS_SUPABASE_ENABLED", "0")

import httpx  # noqa: E402
import pandas as pd  # noqa: E402

from MDP.STIRFutures.BARCHART.BarchartFetcher import BarchartFetcher  # noqa: E402

_QUARTERLY = "HMUZ"
_QUARTERLY_MONTH = {"H": 3, "M": 6, "U": 9, "Z": 12}
_CACHE_DIR = Path(os.environ.get("ARBS_CACHE_DIR", "data")) / "strip_peak"


def _enumerate_contracts(anchor_date: datetime.date, n_front: int) -> List[str]:
    """Return the next *n_front* quarterly SR3 symbols from *anchor_date*, chronologically.

    Quarters are H=Mar, M=Jun, U=Sep, Z=Dec. The first symbol is the earliest quarterly
    contract whose expiry month is on or after ``anchor_date``'s calendar month -- this is
    a month-level comparison only, not the specific IMM (3rd-Wednesday) roll date, so a
    caller anchoring exactly on a contract's own expiry day still gets that contract as
    the front. E.g. for 2026-08-22 with n_front=8:
    ``['SR3U26', 'SR3Z26', 'SR3H27', 'SR3M27', 'SR3U27', 'SR3Z27', 'SR3H28', 'SR3M28']``.
    """
    codes = list(_QUARTERLY)
    year = anchor_date.year
    month = anchor_date.month

    start_idx = next((i for i, c in enumerate(codes) if _QUARTERLY_MONTH[c] >= month), None)
    if start_idx is None:
        # Past December's quarterly (unreachable while _QUARTERLY_MONTH tops out at 12,
        # kept as an explicit guard rather than an assumption).
        start_idx = 0
        year += 1

    out: List[str] = []
    idx, yr = start_idx, year
    for _ in range(n_front):
        out.append(f"SR3{codes[idx]}{yr % 100:02d}")
        idx += 1
        if idx == len(codes):
            idx = 0
            yr += 1
    return out


def _internal_to_barchart(sym: str) -> str:
    return "SQ" + sym[3:]


async def _fetch_one(
    fetcher: BarchartFetcher, bc_sym: str
) -> tuple[str, pd.DataFrame]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        return await fetcher._fetch_eod_timeseries(
            client=client, symbol=bc_sym, columns=None, set_dt_index=False
        )


def build_daily_strip(
    start_date: datetime.date,
    end_date: datetime.date,
    n_front: int = 8,
    *,
    cache: bool = True,
) -> pd.DataFrame:
    """Build a date x contract rate matrix for the front *n_front* SR3 contracts.

    Returns a DataFrame: index=datetime.date, columns=SR3 symbols (near to far,
    chronologically ordered), values=rate in percent (100 - settle price).
    """
    cache_path = _CACHE_DIR / f"strip_{start_date}_{end_date}_n{n_front}.parquet"
    if cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    contracts = _enumerate_contracts(start_date, n_front)
    fetcher = BarchartFetcher()

    async def _fetch_all():
        tasks = [_fetch_one(fetcher, _internal_to_barchart(sym)) for sym in contracts]
        return await asyncio.gather(*tasks, return_exceptions=True)

    results = asyncio.run(_fetch_all())

    frames = {}
    for sym, result in zip(contracts, results):
        if isinstance(result, Exception):
            continue
        _name, df = result
        if df is None or df.empty:
            continue
        # Barchart's queryeod frame, fetched with columns=None, comes back with raw
        # integer column labels: 0=symbol, 1=date, 2=open, 3=high, 4=low, 5=close,
        # 6=volume, 7=open interest. Column 5 (close) is the settle price. Verified
        # live against SQU26/SQH27/SQZ27 on 2026-08-24.
        df["_date"] = pd.to_datetime(df[df.columns[1]]).dt.date
        df["_close"] = pd.to_numeric(df[df.columns[5]], errors="coerce")
        ser = df.set_index("_date")["_close"].dropna()
        frames[sym] = 100.0 - ser  # convert price to rate

    strip = pd.DataFrame(frames).dropna()
    strip = strip[(strip.index >= start_date) & (strip.index <= end_date)]
    strip = strip.sort_index()
    # Chronological column order: (year, HMUZ-index), NOT alphabetical -- "SR3U26" sorts
    # after "SR3M28" as a plain string (the quarter letter is compared before the year),
    # even though U26 is chronologically earlier. Symbol shape is fixed at "SR3{H|M|U|Z}YY"
    # (6 chars): index 3 is the quarter code, index 4: is the 2-digit year.
    strip = strip[sorted(strip.columns, key=lambda s: (int(s[4:]), _QUARTERLY.index(s[3])))]

    if cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        strip.to_parquet(cache_path)

    return strip


def _contract_last_trade_month(sym: str) -> tuple[int, int]:
    """Approximate last-trade (year, month) for an SR3 contract.

    SR3 futures settle in arrears: SR3H26 references the quarter starting
    at its March 2026 IMM date, and trades through approximately mid-June
    2026. So the last-trade month is the delivery month + 3.
    """
    code = sym[3]
    yr = 2000 + int(sym[4:6])
    delivery_month = _QUARTERLY_MONTH[code]
    last_month = delivery_month + 3
    last_year = yr
    if last_month > 12:
        last_month -= 12
        last_year += 1
    return last_year, last_month


def build_rolling_strip(
    start_date: datetime.date,
    end_date: datetime.date,
    n_front: int = 8,
    *,
    cache: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a rolling daily strip where the front-N contracts shift as contracts expire.

    Unlike ``build_daily_strip`` (which fixes the contract set at ``start_date`` and
    inner-joins, truncating the sample when the earliest contract expires), this function
    re-selects the front *n_front* contracts at each date. A contract is "live" on date D
    if its approximate last-trade month has not yet passed.

    Returns
    -------
    rates_wide : DataFrame
        All fetched contracts as columns, index = date, values = rate (%).
        Contains NaN for dates outside each contract's trading window.
    active : DataFrame
        Index = date, columns = [f"slot_{i}" for i in range(n_front)],
        values = contract symbols. Each row's n_front slots are the contracts
        that were the front-N on that date.
    """
    cache_path = _CACHE_DIR / f"rolling_{start_date}_{end_date}_n{n_front}.parquet"
    active_path = _CACHE_DIR / f"rolling_{start_date}_{end_date}_n{n_front}_active.parquet"
    if cache and cache_path.exists() and active_path.exists():
        return pd.read_parquet(cache_path), pd.read_parquet(active_path)

    # enumerate ALL quarterly contracts from ~1 quarter before start through end + n_front quarters
    all_contracts = []
    yr = start_date.year
    mo = start_date.month
    # start 1 quarter early to catch contracts that are still alive at start_date
    if mo <= 3:
        yr -= 1
        start_q_idx = 3  # Z of prior year
    else:
        start_q_idx = next(i for i, c in enumerate(_QUARTERLY) if _QUARTERLY_MONTH[c] >= mo - 3)

    end_yr = end_date.year + 2  # far enough out to always have n_front contracts
    y, qi = yr, start_q_idx
    codes = list(_QUARTERLY)
    while True:
        sym = f"SR3{codes[qi]}{y % 100:02d}"
        ltm_y, ltm_m = _contract_last_trade_month(sym)
        delivery_month = _QUARTERLY_MONTH[codes[qi]]
        delivery_date = datetime.date(y, delivery_month, 1)
        if delivery_date > datetime.date(end_yr, 12, 31):
            break
        all_contracts.append(sym)
        qi += 1
        if qi == len(codes):
            qi = 0
            y += 1

    # deduplicate and sort chronologically
    seen = set()
    unique = []
    for s in all_contracts:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    all_contracts = sorted(unique, key=lambda s: (int(s[4:]), _QUARTERLY.index(s[3])))

    # fetch all contracts
    fetcher = BarchartFetcher()

    async def _fetch_all():
        tasks = [_fetch_one(fetcher, _internal_to_barchart(sym)) for sym in all_contracts]
        return await asyncio.gather(*tasks, return_exceptions=True)

    results = asyncio.run(_fetch_all())

    frames = {}
    for sym, result in zip(all_contracts, results):
        if isinstance(result, Exception):
            continue
        _name, df = result
        if df is None or df.empty:
            continue
        df["_date"] = pd.to_datetime(df[df.columns[1]]).dt.date
        df["_close"] = pd.to_numeric(df[df.columns[5]], errors="coerce")
        ser = df.set_index("_date")["_close"].dropna()
        frames[sym] = 100.0 - ser

    rates_wide = pd.DataFrame(frames)
    rates_wide = rates_wide[(rates_wide.index >= start_date) & (rates_wide.index <= end_date)]
    rates_wide = rates_wide.sort_index()
    rates_wide = rates_wide[sorted(rates_wide.columns,
                                   key=lambda s: (int(s[4:]), _QUARTERLY.index(s[3])))]

    # for each date, pick the front n_front contracts that are still alive
    active_rows = []
    for d in rates_wide.index:
        live = []
        for sym in rates_wide.columns:
            ltm_y, ltm_m = _contract_last_trade_month(sym)
            last_approx = datetime.date(ltm_y, ltm_m, 15)
            if last_approx >= d and pd.notna(rates_wide.at[d, sym]):
                live.append(sym)
            if len(live) == n_front:
                break
        # pad with None if fewer than n_front available
        while len(live) < n_front:
            live.append(None)
        active_rows.append(live)

    active = pd.DataFrame(active_rows, index=rates_wide.index,
                          columns=[f"slot_{i}" for i in range(n_front)])

    if cache:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        rates_wide.to_parquet(cache_path)
        active.to_parquet(active_path)

    return rates_wide, active


def rolling_strip_to_daily(
    rates_wide: pd.DataFrame,
    active: pd.DataFrame,
) -> pd.DataFrame:
    """Convert a rolling strip into a fixed-width DataFrame suitable for identify_peak.

    Returns a DataFrame with index=date, columns=['slot_0'..'slot_7'],
    values=rate (%). Each row contains the rates of the n_front active contracts
    on that date, in chronological order. The column names are positional (slot_0
    is the front contract, slot_7 is the back), NOT contract symbols.

    Use ``active`` to map slot indices back to contract symbols.
    """
    n_front = len(active.columns)
    rows = []
    for d in active.index:
        syms = active.loc[d].values
        vals = []
        for s in syms:
            if s is not None and s in rates_wide.columns and pd.notna(rates_wide.at[d, s]):
                vals.append(rates_wide.at[d, s])
            else:
                vals.append(float("nan"))
        rows.append(vals)
    return pd.DataFrame(rows, index=active.index,
                        columns=[f"slot_{i}" for i in range(n_front)])
