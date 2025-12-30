"""
Seasonality Analysis.

Provides utilities for analyzing trade flows relative to events
like FOMC meetings, month-ends, and quarter-ends.
"""

import datetime
from typing import Dict, List, Optional

import pandas as pd
import QuantLib as ql
from tqdm import tqdm


def get_fomc_dates() -> List[datetime.date]:
    """
    Get list of FOMC meeting dates.

    Returns:
        Sorted list of FOMC meeting dates
    """
    from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

    dates = [m[0] for m in _CENTRAL_BANK_DATES["USD-SOFR-1D"].values()]
    return sorted(dates)


def get_month_end_dates(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    """
    Get business month end dates within a date range.

    Args:
        start: Start date
        end: End date

    Returns:
        List of business month-end dates
    """
    cal = ql.UnitedStates(ql.UnitedStates.GovernmentBond)
    dates = []

    current = datetime.date(start.year, start.month, 1)
    while current <= end:
        ql_date = ql.Date(1, current.month, current.year)
        month_end = cal.endOfMonth(ql_date)
        py_date = datetime.date(month_end.year(), month_end.month(), month_end.dayOfMonth())
        if start <= py_date <= end:
            dates.append(py_date)

        # Next month
        if current.month == 12:
            current = datetime.date(current.year + 1, 1, 1)
        else:
            current = datetime.date(current.year, current.month + 1, 1)

    return dates


def get_quarter_end_dates(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    """
    Get business quarter end dates within a date range.

    Args:
        start: Start date
        end: End date

    Returns:
        List of business quarter-end dates
    """
    all_month_ends = get_month_end_dates(start, end)
    return [d for d in all_month_ends if d.month in [3, 6, 9, 12]]


def classify_date(
    trade_date: datetime.date,
    fomc_dates: List[datetime.date],
    month_end_dates: List[datetime.date],
    quarter_end_dates: List[datetime.date],
    days_before: int = 3,
) -> Dict[str, bool]:
    """
    Classify a trade date relative to events.

    Args:
        trade_date: The date to classify
        fomc_dates: List of FOMC meeting dates
        month_end_dates: List of month-end dates
        quarter_end_dates: List of quarter-end dates
        days_before: Window size in days before event

    Returns:
        Dict with flags for each event type
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
    date_col: str = "execution_timestamp",
    include_me: Optional[bool] = False,
    include_qe: Optional[bool] = False,
    include_fomc: Optional[bool] = False,
) -> pd.DataFrame:
    """
    Add event classification columns to DataFrame.

    Args:
        df: Input DataFrame with trades
        date_col: Column containing trade dates/timestamps
        include_me: Include month-end classifications
        include_qe: Include quarter-end classifications
        include_fomc: Include FOMC classifications

    Returns:
        DataFrame with event classification columns added
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
            fomc_dates if include_fomc else [],
            month_end_dates if include_me else [],
            quarter_end_dates if include_qe else [],
        )
        classifications.append(cls)

    cls_df = pd.DataFrame(classifications)
    for col in cls_df.columns:
        df[col] = cls_df[col].values

    return df


def aggregate_flows_by_label(
    df: pd.DataFrame,
    value_col: str = "notional",
    agg_func: str = "sum",
) -> pd.DataFrame:
    """
    Aggregate flows by trade label (e.g., "spot 10Y", "5Y10Y").

    Args:
        df: Input DataFrame with trades
        value_col: Column to aggregate
        agg_func: Aggregation function ("sum", "mean", "count", etc.)

    Returns:
        DataFrame with trade labels as index and aggregated values
    """
    grouped = df.groupby("trade_label")[value_col].agg(agg_func)
    return grouped.sort_values(ascending=False)


def analyze_seasonality_by_event(
    df: pd.DataFrame,
    event_col: str,
    value_col: str = "notional",
) -> pd.DataFrame:
    """
    Analyze how flows differ during events vs non-events.

    Args:
        df: Input DataFrame with trades and event classifications
        event_col: Column containing event boolean flag
        value_col: Column to analyze

    Returns:
        Comparison DataFrame with volume ratios and trade counts
    """
    # Pre-calculate main slices
    event_trades = df[df[event_col] == True]
    non_event_trades = df[df[event_col] == False]

    # Calculate total days
    total_event_days = event_trades["execution_timestamp"].dt.date.nunique()
    total_non_event_days = non_event_trades["execution_timestamp"].dt.date.nunique()

    results = []

    unique_labels = df["trade_label"].unique()

    for label in tqdm(unique_labels, desc=f"Analyzing {event_col} Seasonality"):
        curr_event = event_trades[event_trades["trade_label"] == label]
        curr_non_event = non_event_trades[non_event_trades["trade_label"] == label]

        event_vol = curr_event[value_col].sum()
        non_event_vol = curr_non_event[value_col].sum()

        event_count = len(curr_event)
        non_event_count = len(curr_non_event)

        results.append(
            {
                "trade_label": label,
                "event_volume": event_vol,
                "non_event_volume": non_event_vol,
                "event_trade_count": event_count,
                "non_event_trade_count": non_event_count,
                "event_avg_daily": event_vol / max(1, total_event_days),
                "non_event_avg_daily": non_event_vol / max(1, total_non_event_days),
                "volume_ratio": event_vol / max(1, non_event_vol),
            }
        )

    result_df = pd.DataFrame(results)

    if result_df.empty:
        return result_df

    return result_df.sort_values("volume_ratio", ascending=False)
