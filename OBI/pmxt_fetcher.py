"""
PMXT archive fetcher for real Polymarket order book data.

Downloads hourly Parquet files from the PMXT R2 archive, filters to
BTC 5-minute up/down contracts, and produces OBI signals from real
order book snapshots.

Archive URL: https://r2v2.pmxt.dev/polymarket_orderbook_YYYY-MM-DDTHH.parquet
Columns: asset_id, timestamp, event_type, price, side, size, best_bid, best_ask
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PMXT_ARCHIVE_URL = "https://r2v2.pmxt.dev/polymarket_orderbook_{date}T{hour:02d}.parquet"
META_PATH = Path("C:/Users/chris/clee/twap-or-nothing/data/polymarket_5m_meta_full.parquet")
LOCAL_CACHE_DIR = Path.home() / ".cache" / "arbs" / "pmxt_orderbook"


def load_btc_5m_meta(
    meta_path: Optional[Path] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Load BTC 5-minute contract metadata with outcomes."""
    p = meta_path or META_PATH
    df = pd.read_parquet(p)
    df = df[df["interval_min"] == 5].copy()
    df["resolution_time_utc"] = pd.to_datetime(df["resolution_time_utc"], utc=True)
    df["period_open_utc"] = pd.to_datetime(df["period_open_utc"], utc=True)

    if start_date:
        df = df[df["resolution_time_utc"] >= pd.Timestamp(start_date, tz="UTC")]
    if end_date:
        df = df[df["resolution_time_utc"] <= pd.Timestamp(end_date, tz="UTC")]

    df = df.sort_values("resolution_time_utc").reset_index(drop=True)
    return df


def fetch_pmxt_hour(
    date_str: str,
    hour: int,
    token_ids: Optional[List[str]] = None,
    cache: bool = True,
) -> pd.DataFrame:
    """Fetch one hour of PMXT order book data via DuckDB httpfs.

    Returns DataFrame with columns:
        asset_id, timestamp, event_type, price, side, size, best_bid, best_ask
    """
    cache_path = LOCAL_CACHE_DIR / f"polymarket_orderbook_{date_str}T{hour:02d}.parquet"

    if cache and cache_path.exists():
        df = pd.read_parquet(cache_path)
        if token_ids:
            df = df[df["asset_id"].isin(token_ids)]
        return df

    url = PMXT_ARCHIVE_URL.format(date=date_str, hour=hour)
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")

    if token_ids:
        tlist = ",".join(f"'{t}'" for t in token_ids)
        query = f"""
        SELECT asset_id, timestamp, event_type, price, side, size, best_bid, best_ask
        FROM '{url}'
        WHERE asset_id IN ({tlist})
        ORDER BY timestamp
        """
    else:
        query = f"""
        SELECT asset_id, timestamp, event_type, price, side, size, best_bid, best_ask
        FROM '{url}'
        ORDER BY timestamp
        """

    try:
        df = con.execute(query).df()
    except Exception as e:
        logger.debug(f"PMXT {date_str}T{hour:02d}: {e}")
        return pd.DataFrame()
    finally:
        con.close()

    if cache and not df.empty:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_path, index=False)

    return df


def fetch_pmxt_range(
    start_date: str,
    end_date: str,
    token_ids: Optional[List[str]] = None,
    hours: Optional[List[int]] = None,
    cache: bool = True,
) -> pd.DataFrame:
    """Fetch multiple hours of PMXT data across a date range."""
    from tqdm import tqdm

    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    dates = pd.date_range(start, end, freq="D")
    hour_list = hours or list(range(24))

    frames = []
    total = len(dates) * len(hour_list)
    pbar = tqdm(total=total, desc="Fetching PMXT")

    for date in dates:
        ds = date.strftime("%Y-%m-%d")
        for h in hour_list:
            df = fetch_pmxt_hour(ds, h, token_ids=token_ids, cache=cache)
            if not df.empty:
                frames.append(df)
            pbar.update(1)

    pbar.close()

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("timestamp").reset_index(drop=True)


def compute_obi_from_pmxt(
    ob_df: pd.DataFrame,
    meta_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute OBI from real PMXT order book data.

    For each contract (identified by yes_token_id), compute OBI at each
    timestamp from the bid/ask sizes in the tick stream.

    Returns DataFrame with columns:
        contract_idx, yes_token_id, timestamp, obi, mid_price, spread,
        best_bid, best_ask, outcome, resolution_time, entry_time
    """
    meta_lookup = {}
    for _, row in meta_df.iterrows():
        meta_lookup[row["yes_token_id"]] = row

    results = []

    for token_id, group in ob_df.groupby("asset_id"):
        if token_id not in meta_lookup:
            continue

        contract = meta_lookup[token_id]
        outcome = float(contract["outcome"])
        res_time = contract["resolution_time_utc"]
        open_time = contract["period_open_utc"]

        ticks = group.sort_values("timestamp").copy()

        bids = ticks[ticks["side"] == "BUY"].copy() if "side" in ticks.columns else pd.DataFrame()
        asks = ticks[ticks["side"] == "SELL"].copy() if "side" in ticks.columns else pd.DataFrame()

        for _, tick in ticks.iterrows():
            bb = tick.get("best_bid", np.nan)
            ba = tick.get("best_ask", np.nan)

            if pd.isna(bb) or pd.isna(ba) or ba <= 0 or bb <= 0:
                continue

            mid = (bb + ba) / 2
            spread = ba - bb

            bid_size = tick.get("size", 0) if tick.get("side") == "BUY" else 0
            ask_size = tick.get("size", 0) if tick.get("side") == "SELL" else 0

            results.append({
                "yes_token_id": token_id,
                "timestamp": tick["timestamp"],
                "best_bid": bb,
                "best_ask": ba,
                "mid_price": mid,
                "spread": spread,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "event_type": tick.get("event_type", ""),
                "outcome": outcome,
                "resolution_time": res_time,
                "period_open": open_time,
            })

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


def build_contract_obi_snapshots(
    ticks_df: pd.DataFrame,
    meta_df: pd.DataFrame,
    snapshot_interval_seconds: int = 10,
) -> pd.DataFrame:
    """Aggregate tick data into periodic OBI snapshots per contract.

    Groups ticks into time buckets and computes cumulative bid/ask
    pressure as OBI proxy.
    """
    meta_lookup = {row["yes_token_id"]: row for _, row in meta_df.iterrows()}
    records = []

    for token_id, group in ticks_df.groupby("yes_token_id"):
        if token_id not in meta_lookup:
            continue
        contract = meta_lookup[token_id]

        g = group.sort_values("timestamp")
        freq = f"{snapshot_interval_seconds}s"
        g = g.set_index("timestamp")

        buckets = g.resample(freq)
        cum_bid = 0.0
        cum_ask = 0.0

        for bucket_ts, bucket in buckets:
            if bucket.empty:
                continue

            cum_bid += bucket["bid_size"].sum()
            cum_ask += bucket["ask_size"].sum()

            total = cum_bid + cum_ask
            obi = (cum_bid - cum_ask) / total if total > 0 else 0.0

            records.append({
                "yes_token_id": token_id,
                "snapshot_ts": bucket_ts,
                "obi": obi,
                "cum_bid_size": cum_bid,
                "cum_ask_size": cum_ask,
                "mid_price": bucket["mid_price"].iloc[-1],
                "spread": bucket["spread"].median(),
                "best_bid": bucket["best_bid"].iloc[-1],
                "best_ask": bucket["best_ask"].iloc[-1],
                "n_ticks": len(bucket),
                "outcome": contract["outcome"],
                "resolution_time": contract["resolution_time_utc"],
                "period_open": contract["period_open_utc"],
            })

        cum_bid = 0.0
        cum_ask = 0.0

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)
