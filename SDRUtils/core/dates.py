"""
Date and time utilities for SDR analytics.

This module provides functions for date conversion, adjustment,
and year fraction calculations using QuantLib.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import QuantLib as ql
import pytz

from SDRUtils.config import USD_CONVENTIONS, CurrencyConventions, get_conventions


NY_tz = pytz.timezone("America/New_York")
UTC_tz = pytz.timezone("UTC")


def to_naive_timestamp(x) -> pd.Timestamp:
    """Convert value to timezone-naive pandas Timestamp."""
    ts = pd.to_datetime(x, errors="coerce")
    if pd.isna(ts):
        return ts
    # drop tz to avoid ql.Date confusion
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert(None)
    return ts


def ts_to_ql_date(ts: pd.Timestamp) -> ql.Date:
    """Convert pandas Timestamp to QuantLib Date."""
    return ql.Date(int(ts.day), int(ts.month), int(ts.year))


def to_ql_date(value) -> Optional[ql.Date]:
    """
    Convert value to QuantLib Date.

    Handles QuantLib Date, pandas Timestamp, datetime, and string inputs.
    Returns None if conversion fails.
    """
    if isinstance(value, ql.Date):
        return value
    ts = to_naive_timestamp(value)
    if pd.isna(ts):
        return None
    return ts_to_ql_date(ts)


def adjust_ql_date(
    ql_date: ql.Date,
    calendar: ql.Calendar,
    bdc: int,
) -> ql.Date:
    """Adjust date to business day if necessary."""
    if not calendar.isBusinessDay(ql_date):
        return calendar.adjust(ql_date, bdc)
    return ql_date


def ensure_int64_epoch_seconds(ts: pd.Series) -> np.ndarray:
    """Convert timestamp series to int64 epoch seconds (robust for tz-aware/naive)."""
    t = pd.to_datetime(ts, errors="coerce", utc=True)
    return (t.view("int64") // 1_000_000_000).astype(np.int64)


def calculate_tenor_years(
    effective_date: pd.Timestamp,
    expiration_date: pd.Timestamp,
    *,
    conventions: Optional[CurrencyConventions] = None,
    adjust_to_business_day: bool = True,
) -> float:
    """
    Calculate year fraction for tenor between effective and expiration dates.

    Args:
        effective_date: Start date of the swap
        expiration_date: End date of the swap
        conventions: Currency conventions to use (defaults to USD)
        adjust_to_business_day: Whether to adjust dates to business days

    Returns:
        Year fraction using the specified day counter
    """
    if conventions is None:
        conventions = USD_CONVENTIONS

    ql_eff = to_ql_date(effective_date)
    ql_exp = to_ql_date(expiration_date)
    if ql_eff is None or ql_exp is None:
        return 0.0

    if adjust_to_business_day:
        ql_eff = adjust_ql_date(ql_eff, conventions.calendar, conventions.business_day_convention)
        ql_exp = adjust_ql_date(ql_exp, conventions.calendar, conventions.business_day_convention)

    if ql_exp <= ql_eff:
        return 0.0

    return float(conventions.day_counter.yearFraction(ql_eff, ql_exp))


def calculate_forward_start_years(
    execution_timestamp: pd.Timestamp,
    effective_date: pd.Timestamp,
    *,
    conventions: Optional[CurrencyConventions] = None,
    adjust_to_business_day: bool = False,
    use_execution_date_only: bool = True,
) -> float:
    """
    Calculate forward start year fraction.

    Returns NEGATIVE values if effective_date < execution_date.

    Args:
        execution_timestamp: Trade execution timestamp
        effective_date: Swap effective date
        conventions: Currency conventions to use (defaults to USD)
        adjust_to_business_day: Whether to adjust dates to business days
        use_execution_date_only: Use only the date portion of execution_timestamp

    Returns:
        Year fraction from execution to effective date (negative if past)
    """
    if conventions is None:
        conventions = USD_CONVENTIONS

    exec_ts = to_naive_timestamp(execution_timestamp)
    if pd.isna(exec_ts):
        return 0.0

    if use_execution_date_only:
        exec_ts = exec_ts.normalize()

    ql_exec = to_ql_date(exec_ts)
    ql_eff = to_ql_date(effective_date)
    if ql_exec is None or ql_eff is None:
        return 0.0

    if adjust_to_business_day:
        ql_exec = adjust_ql_date(ql_exec, conventions.calendar, conventions.business_day_convention)
        ql_eff = adjust_ql_date(ql_eff, conventions.calendar, conventions.business_day_convention)

    if ql_eff == ql_exec:
        return 0.0

    val = conventions.day_counter.yearFraction(min(ql_exec, ql_eff), max(ql_exec, ql_eff))
    return val if ql_eff > ql_exec else -val


def is_forward_starting(
    execution_timestamp: pd.Timestamp,
    effective_date: pd.Timestamp,
    *,
    conventions: Optional[CurrencyConventions] = None,
) -> bool:
    """
    Determine if a trade is forward-starting based on T+spot_lag convention.

    Args:
        execution_timestamp: Trade execution timestamp
        effective_date: Swap effective date
        conventions: Currency conventions (defaults to USD with T+2)

    Returns:
        True if effective date is beyond the standard spot lag
    """
    if conventions is None:
        conventions = USD_CONVENTIONS

    ql_exec = to_ql_date(execution_timestamp)
    ql_eff = to_ql_date(effective_date)

    if ql_exec is None or ql_eff is None:
        return False

    spot_date = conventions.calendar.advance(ql_exec, conventions.spot_lag_days, ql.Days)
    return ql_eff > spot_date


# Backward compatibility aliases
_to_naive_timestamp = to_naive_timestamp
_ts_to_ql_date = ts_to_ql_date
_to_ql_date = to_ql_date
_adjust_ql_date = adjust_ql_date
_ensure_int64_epoch_seconds = ensure_int64_epoch_seconds
