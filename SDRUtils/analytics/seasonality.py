"""
Event-based seasonality analysis for SDR trades.

This module provides tools for analyzing trade flows around key events:
- FOMC meetings
- Month-end dates
- Quarter-end dates
- (Future) CPI/PPI releases, NFP, Treasury auctions, IMM rolls
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
import QuantLib as ql
from tqdm import tqdm

from SDRUtils.config import USD_CONVENTIONS


def get_fomc_dates() -> List[datetime.date]:
    """
    Get list of FOMC meeting dates.

    Returns:
        Sorted list of FOMC meeting dates
    """
    try:
        from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES
        dates = [m[0] for m in _CENTRAL_BANK_DATES["USD-SOFR-1D"].values()]
        return sorted(dates)
    except ImportError:
        return []


def get_month_end_dates(
    start: datetime.date,
    end: datetime.date,
    *,
    calendar: Optional[ql.Calendar] = None,
) -> List[datetime.date]:
    """
    Get business month end dates within a date range.

    Args:
        start: Start date
        end: End date
        calendar: QuantLib calendar (defaults to USD GovBond)

    Returns:
        List of business month end dates
    """
    if calendar is None:
        calendar = USD_CONVENTIONS.calendar

    dates = []
    current = datetime.date(start.year, start.month, 1)

    while current <= end:
        ql_date = ql.Date(1, current.month, current.year)
        month_end = calendar.endOfMonth(ql_date)
        py_date = datetime.date(
            month_end.year(), month_end.month(), month_end.dayOfMonth()
        )
        if start <= py_date <= end:
            dates.append(py_date)

        # Advance to next month
        if current.month == 12:
            current = datetime.date(current.year + 1, 1, 1)
        else:
            current = datetime.date(current.year, current.month + 1, 1)

    return dates


def get_quarter_end_dates(
    start: datetime.date,
    end: datetime.date,
    *,
    calendar: Optional[ql.Calendar] = None,
) -> List[datetime.date]:
    """
    Get business quarter end dates within a date range.

    Args:
        start: Start date
        end: End date
        calendar: QuantLib calendar (defaults to USD GovBond)

    Returns:
        List of business quarter end dates
    """
    all_month_ends = get_month_end_dates(start, end, calendar=calendar)
    return [d for d in all_month_ends if d.month in [3, 6, 9, 12]]


def classify_date(
    trade_date: datetime.date,
    fomc_dates: List[datetime.date],
    month_end_dates: List[datetime.date],
    quarter_end_dates: List[datetime.date],
    *,
    days_before: int = 3,
) -> Dict[str, object]:
    """
    Classify a trade date relative to calendar events.

    Args:
        trade_date: Date to classify
        fomc_dates: List of FOMC meeting dates
        month_end_dates: List of month end dates
        quarter_end_dates: List of quarter end dates
        days_before: Window size before events

    Returns:
        Dict with event flags and days-to-event values
    """
    result = {
        "is_month_end_window": False,
        "is_quarter_end_window": False,
        "is_fomc_window": False,
        "is_fomc_day": False,
        "days_to_month_end": None,
        "days_to_quarter_end": None,
        "days_to_fomc": None,
    }

    # Month end
    for me in month_end_dates:
        delta = (me - trade_date).days
        if 0 <= delta <= days_before:
            result["is_month_end_window"] = True
            result["days_to_month_end"] = delta
            break

    # Quarter end
    for qe in quarter_end_dates:
        delta = (qe - trade_date).days
        if 0 <= delta <= days_before:
            result["is_quarter_end_window"] = True
            result["days_to_quarter_end"] = delta
            break

    # FOMC
    for fomc in fomc_dates:
        delta = (fomc - trade_date).days
        if delta == 0:
            result["is_fomc_day"] = True
            result["is_fomc_window"] = True
            result["days_to_fomc"] = 0
            break
        elif 0 < delta <= days_before:
            result["is_fomc_window"] = True
            result["days_to_fomc"] = delta
            break

    return result


def add_event_classifications(
    df: pd.DataFrame,
    *,
    date_col: str = "execution_timestamp",
    include_me: bool = False,
    include_qe: bool = False,
    include_fomc: bool = False,
    days_before: int = 3,
) -> pd.DataFrame:
    """
    Add event classification columns to DataFrame.

    Args:
        df: DataFrame with trade data
        date_col: Column containing trade dates
        include_me: Include month-end analysis
        include_qe: Include quarter-end analysis
        include_fomc: Include FOMC analysis
        days_before: Window size before events

    Returns:
        DataFrame with added event classification columns
    """
    df = df.copy()

    # Get date range
    dates = pd.to_datetime(df[date_col])
    min_date = dates.min().date()
    max_date = dates.max().date()

    # Get event dates
    fomc_dates = get_fomc_dates() if include_fomc else []
    month_end_dates = get_month_end_dates(min_date, max_date) if include_me else []
    quarter_end_dates = get_quarter_end_dates(min_date, max_date) if include_qe else []

    # Classify each trade
    classifications = []
    for ts in dates:
        trade_date = ts.date() if hasattr(ts, "date") else ts
        cls = classify_date(
            trade_date,
            fomc_dates,
            month_end_dates,
            quarter_end_dates,
            days_before=days_before,
        )
        classifications.append(cls)

    cls_df = pd.DataFrame(classifications)
    for col in cls_df.columns:
        df[col] = cls_df[col].values

    return df


def aggregate_flows_by_label(
    df: pd.DataFrame,
    *,
    label_col: str = "trade_label",
    value_col: str = "notional",
    agg_func: str = "sum",
) -> pd.DataFrame:
    """
    Aggregate trade flows by trade label.

    Args:
        df: DataFrame with trade data
        label_col: Column containing trade labels
        value_col: Column to aggregate
        agg_func: Aggregation function (sum, mean, count, etc.)

    Returns:
        Series with trade labels as index and aggregated values
    """
    grouped = df.groupby(label_col)[value_col].agg(agg_func)
    return grouped.sort_values(ascending=False)


def analyze_seasonality_by_event(
    df: pd.DataFrame,
    event_col: str,
    *,
    value_col: str = "notional",
    label_col: str = "trade_label",
    timestamp_col: str = "execution_timestamp",
    show_progress: bool = True,
) -> pd.DataFrame:
    """
    Analyze how flows differ during events vs non-events.

    Args:
        df: DataFrame with trade data
        event_col: Column containing event flag (boolean)
        value_col: Column containing values to analyze
        label_col: Column containing trade labels
        timestamp_col: Column containing timestamps
        show_progress: Show progress bar

    Returns:
        DataFrame comparing event vs non-event flows by trade label
    """
    # Pre-calculate main slices
    event_trades = df[df[event_col] == True]
    non_event_trades = df[df[event_col] == False]

    # Calculate total days
    total_event_days = event_trades[timestamp_col].dt.date.nunique()
    total_non_event_days = non_event_trades[timestamp_col].dt.date.nunique()

    results = []
    unique_labels = df[label_col].unique()

    # Optional progress bar
    iterator = (
        tqdm(unique_labels, desc=f"Analyzing {event_col} Seasonality")
        if show_progress
        else unique_labels
    )

    for label in iterator:
        curr_event = event_trades[event_trades[label_col] == label]
        curr_non_event = non_event_trades[non_event_trades[label_col] == label]

        event_vol = curr_event[value_col].sum()
        non_event_vol = curr_non_event[value_col].sum()

        event_count = len(curr_event)
        non_event_count = len(curr_non_event)

        results.append({
            label_col: label,
            "event_volume": event_vol,
            "non_event_volume": non_event_vol,
            "event_trade_count": event_count,
            "non_event_trade_count": non_event_count,
            "event_avg_daily": event_vol / max(1, total_event_days),
            "non_event_avg_daily": non_event_vol / max(1, total_non_event_days),
            "volume_ratio": event_vol / max(1, non_event_vol),
        })

    result_df = pd.DataFrame(results)

    if result_df.empty:
        return result_df

    return result_df.sort_values("volume_ratio", ascending=False)


def get_imm_dates(
    start: datetime.date,
    end: datetime.date,
) -> List[datetime.date]:
    """
    Get IMM roll dates (3rd Wednesday of Mar, Jun, Sep, Dec) within range.

    Args:
        start: Start date
        end: End date

    Returns:
        List of IMM dates
    """
    dates = []
    current_year = start.year
    current_month = 3  # Start with March

    while True:
        # Calculate 3rd Wednesday of this IMM month
        if current_month in [3, 6, 9, 12]:
            ql_date = ql.Date.nthWeekday(3, ql.Wednesday, current_month, current_year)
            py_date = datetime.date(
                ql_date.year(), ql_date.month(), ql_date.dayOfMonth()
            )

            if py_date > end:
                break
            if py_date >= start:
                dates.append(py_date)

        # Advance to next IMM month
        current_month += 3
        if current_month > 12:
            current_month = 3
            current_year += 1

        if current_year > end.year + 1:
            break

    return dates
