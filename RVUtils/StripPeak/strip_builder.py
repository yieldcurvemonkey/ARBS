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
