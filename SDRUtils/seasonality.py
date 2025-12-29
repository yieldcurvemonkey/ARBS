import datetime
import re
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd
import pytz
import QuantLib as ql
from tqdm import tqdm


def get_fomc_dates() -> List[datetime.date]:
    """Get list of FOMC meeting dates"""
    from Query.IRSwaps._CENTRAL_BANK_DATES import _CENTRAL_BANK_DATES

    dates = [m[0] for m in _CENTRAL_BANK_DATES["USD-SOFR-1D"].values()]
    return sorted(dates)


def get_month_end_dates(start: datetime.date, end: datetime.date) -> List[datetime.date]:
    """Get business month end dates"""
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
    """Get business quarter end dates"""
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
    Classify a trade date relative to events

    Returns dict with flags for each event type
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
    """Add event classification columns to DataFrame"""
    df = df.copy()

    # Get date range
    dates = pd.to_datetime(df[date_col])
    min_date = dates.min().date()
    max_date = dates.max().date()

    """ 
    TODO
    - cpi/ppi/inflation dates
    - nfp/labor dates
    - tsy auctions dates
    - rolls/imm rolls dates

    """
    # Get event dates
    fomc_dates = get_fomc_dates()
    month_end_dates = get_month_end_dates(min_date, max_date)
    quarter_end_dates = get_quarter_end_dates(min_date, max_date)

    # Classify each trade

    classifications = []
    for ts in dates:
        trade_date = ts.date() if hasattr(ts, "date") else ts
        cls = classify_date(trade_date, fomc_dates if include_fomc else [], month_end_dates if include_me else [], quarter_end_dates if include_qe else [])
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
    Aggregate flows by trade label (e.g., "spot 10Y", "5Y10Y")

    Returns DataFrame with trade labels as index and aggregated values
    """
    grouped = df.groupby("trade_label")[value_col].agg(agg_func)
    return grouped.sort_values(ascending=False)


def analyze_seasonality_by_event(
    df: pd.DataFrame,
    event_col: str,
    value_col: str = "notional",
) -> pd.DataFrame:
    """
    Analyze how flows differ during events vs non-events

    Returns comparison DataFrame
    """
    # Pre-calculate main slices to avoid repeated filtering
    event_trades = df[df[event_col] == True]
    non_event_trades = df[df[event_col] == False]

    # Calculate total days once
    total_event_days = event_trades["execution_timestamp"].dt.date.nunique()
    total_non_event_days = non_event_trades["execution_timestamp"].dt.date.nunique()

    results = []

    unique_labels = df["trade_label"].unique()

    # TQDM wrapper added here
    for label in tqdm(unique_labels, desc=f"Analyzing {event_col} Seasonality"):
        # Further filtering by label
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


def generate_seasonality_report(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Generate comprehensive seasonality report

    Returns dict of analysis DataFrames
    """
    report = {}

    # Overall volume by trade label
    report["overall_volume_by_label"] = aggregate_flows_by_label(df, "notional", "sum")
    report["overall_count_by_label"] = aggregate_flows_by_label(df, "notional", "count")

    # Volume by product type
    report["volume_by_product"] = df.groupby("product_type")["notional"].agg(["sum", "count", "mean"])

    # Volume by package type
    report["volume_by_package"] = df.groupby("package_type")["notional"].agg(["sum", "count", "mean"])

    # Month-end analysis
    report["month_end_analysis"] = analyze_seasonality_by_event(df, "is_month_end_window")

    # Quarter-end analysis
    report["quarter_end_analysis"] = analyze_seasonality_by_event(df, "is_quarter_end_window")

    # FOMC analysis
    report["fomc_analysis"] = analyze_seasonality_by_event(df, "is_fomc_window")

    # Top trades on FOMC days
    fomc_trades = df[df["is_fomc_day"] == True]
    if not fomc_trades.empty:
        report["fomc_day_top_trades"] = aggregate_flows_by_label(fomc_trades, "notional", "sum").head(20)

    # Curve trades breakdown
    curve_trades = df[df["package_type"] == "CURVE"]
    if not curve_trades.empty:
        report["curve_trades_by_label"] = curve_trades.groupby("trade_label")["notional"].agg(["sum", "count"])

    # Fly trades breakdown
    fly_trades = df[df["package_type"] == "FLY"]
    if not fly_trades.empty:
        report["fly_trades_by_label"] = fly_trades.groupby("trade_label")["notional"].agg(["sum", "count"])

    return report
