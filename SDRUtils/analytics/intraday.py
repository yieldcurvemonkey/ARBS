"""
Intraday trade analytics: cumulative DV01, hourly distributions, and trade clustering.

These tools reveal when risk gets put on during the trading session and
identify execution batches (simultaneous multi-leg trades filed as outrights).
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def intraday_cumulative_dv01(
    df: pd.DataFrame,
    date_col: str = "execution_date",
    ts_col: str = "execution_timestamp",
    value_col: str = "risk",
) -> pd.DataFrame:
    """Running cumulative DV01 through each trading day.

    Groups by date, sorts by timestamp within each day, then computes
    a running cumulative sum.  The returned ``hour`` column is a float
    representing hours-from-midnight so it plots naturally on a time axis.

    Args:
        df: DataFrame with execution timestamps and DV01 values.
        date_col: Column containing execution dates.
        ts_col: Column containing execution timestamps.
        value_col: Column containing DV01 values to accumulate.

    Returns:
        DataFrame with columns ``[execution_date, hour, cumulative_dv01]``.
    """
    df = df.copy()
    df["_exec_ts"] = pd.to_datetime(df[ts_col], errors="coerce")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0)

    records = []
    for date, day in df.groupby(date_col):
        day = day.sort_values("_exec_ts")
        cum = day[value_col].cumsum()
        hour = day["_exec_ts"].dt.hour + day["_exec_ts"].dt.minute / 60
        for h, c in zip(hour, cum):
            records.append(
                {"execution_date": date, "hour": h, "cumulative_dv01": c}
            )

    return pd.DataFrame(records)


def hourly_distribution(
    df: pd.DataFrame,
    ts_col: str = "execution_timestamp",
    value_col: str = "risk",
    timezone: str = "UTC",
) -> pd.DataFrame:
    """Aggregate a value column by hour of day.

    Args:
        df: DataFrame with execution timestamps.
        ts_col: Column containing execution timestamps.
        value_col: Column containing values to aggregate (e.g. DV01).
        timezone: Target timezone for hour extraction.

    Returns:
        DataFrame indexed by hour (0-23) with columns
        ``[count, total, mean]``.
    """
    df = df.copy()
    ts = pd.to_datetime(df[ts_col], errors="coerce")
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0)

    try:
        ts = ts.dt.tz_convert(timezone)
    except TypeError:
        # Naive timestamps -- localize then convert
        try:
            ts = ts.dt.tz_localize("UTC").dt.tz_convert(timezone)
        except Exception:
            pass  # fall through with whatever tz the timestamps already have

    df["_hour"] = ts.dt.hour

    agg = df.groupby("_hour")[value_col].agg(
        count="size",
        total="sum",
        mean="mean",
    )
    agg.index.name = "hour"
    return agg


def trade_clustering(
    df: pd.DataFrame,
    ts_col: str = "execution_timestamp",
    gap_seconds: int = 120,
) -> pd.DataFrame:
    """Assign cluster IDs to temporally close trades.

    Trades within *gap_seconds* of each other belong to the same cluster.
    Trades separated by more than *gap_seconds* start a new cluster.

    Args:
        df: DataFrame with execution timestamps.
        ts_col: Column containing execution timestamps.
        gap_seconds: Maximum gap (in seconds) between trades in the same
            cluster.

    Returns:
        Copy of *df* with an added ``cluster_id`` column (int, starting at 0).
    """
    df = df.copy()
    df["_ts"] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.sort_values("_ts").reset_index(drop=True)

    gap_s = df["_ts"].diff().dt.total_seconds().fillna(gap_seconds + 1)
    df["cluster_id"] = (gap_s > gap_seconds).cumsum()

    df.drop(columns=["_ts"], inplace=True)
    return df


def execution_timing_stats(
    df: pd.DataFrame,
    ts_col: str = "execution_timestamp",
    date_col: str = "execution_date",
    timezone: str = "America/New_York",
) -> pd.DataFrame:
    """Per-day execution timing summary.

    Args:
        df: DataFrame with execution timestamps and dates.
        ts_col: Column containing execution timestamps.
        date_col: Column containing execution dates.
        timezone: Timezone for display of first/last trade times.

    Returns:
        DataFrame indexed by date with columns
        ``[first_trade, last_trade, peak_hour, trade_count]``.
    """
    df = df.copy()
    ts = pd.to_datetime(df[ts_col], errors="coerce")
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce").dt.date

    try:
        ts_local = ts.dt.tz_convert(timezone)
    except TypeError:
        try:
            ts_local = ts.dt.tz_localize("UTC").dt.tz_convert(timezone)
        except Exception:
            ts_local = ts

    df["_ts_local"] = ts_local
    df["_hour"] = ts_local.dt.hour

    records = []
    for date, day in df.groupby(date_col):
        first = day["_ts_local"].min()
        last = day["_ts_local"].max()
        peak_hour = int(day["_hour"].mode().iloc[0]) if len(day) > 0 else np.nan
        records.append(
            {
                date_col: date,
                "first_trade": first,
                "last_trade": last,
                "peak_hour": peak_hour,
                "trade_count": len(day),
            }
        )

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.set_index(date_col)
    return result
