"""
SDR Analytics Utilities Module

Shared utility functions for SDR (Swap Data Repository) analytics
for US Interest Rate Swaps trading desk analysis.

Author: SDR Analytics Suite
"""

import datetime
from typing import Callable, Dict, List, Literal, Optional, Tuple, Union

import numpy as np
import pandas as pd
import pytz

NY_tz = pytz.timezone("America/New_York")
CHI_tz = pytz.timezone("America/Chicago")
UTC_tz = pytz.timezone("UTC")


# =============================================================================
# Tenor Bucketing Functions
# =============================================================================

TENOR_BUCKET_ORDER = [
    "0-3M",
    "3-6M",
    "6-9M",
    "9M-1Y",
    "1-1.5Y",
    "1.5-2Y",
    "2-3Y",
    "3-4Y",
    "4-5Y",
    "5-7Y",
    "7-10Y",
    "10-15Y",
    "15-20Y",
    "20-30Y",
    "30Y+",
    "Unknown",
]

TENOR_BUCKET_ORDER_SIMPLE = [
    "0-3M",
    "3-6M",
    "6M-1Y",
    "1-2Y",
    "2-3Y",
    "3-5Y",
    "5-7Y",
    "7-10Y",
    "10-15Y",
    "15-20Y",
    "20-30Y",
    "30Y+",
    "Unknown",
]

BENCHMARK_TENORS = [1, 2, 3, 5, 7, 10, 15, 20, 30]


def assign_tenor_bucket_detailed(years: float) -> str:
    """
    Assign a detailed tenor bucket to a swap based on years to maturity.

    Args:
        years: Tenor in years

    Returns:
        Tenor bucket string
    """
    if pd.isna(years) or years <= 0:
        return "Unknown"
    elif years <= 0.25:
        return "0-3M"
    elif years <= 0.5:
        return "3-6M"
    elif years <= 0.75:
        return "6-9M"
    elif years <= 1:
        return "9M-1Y"
    elif years <= 1.5:
        return "1-1.5Y"
    elif years <= 2:
        return "1.5-2Y"
    elif years <= 3:
        return "2-3Y"
    elif years <= 4:
        return "3-4Y"
    elif years <= 5:
        return "4-5Y"
    elif years <= 7:
        return "5-7Y"
    elif years <= 10:
        return "7-10Y"
    elif years <= 15:
        return "10-15Y"
    elif years <= 20:
        return "15-20Y"
    elif years <= 30:
        return "20-30Y"
    else:
        return "30Y+"


def assign_tenor_bucket_simple(years: float) -> str:
    """
    Assign a simple tenor bucket to a swap based on years to maturity.

    Args:
        years: Tenor in years

    Returns:
        Tenor bucket string
    """
    if pd.isna(years) or years <= 0:
        return "Unknown"
    elif years <= 0.25:
        return "0-3M"
    elif years <= 0.5:
        return "3-6M"
    elif years <= 1:
        return "6M-1Y"
    elif years <= 2:
        return "1-2Y"
    elif years <= 3:
        return "2-3Y"
    elif years <= 5:
        return "3-5Y"
    elif years <= 7:
        return "5-7Y"
    elif years <= 10:
        return "7-10Y"
    elif years <= 15:
        return "10-15Y"
    elif years <= 20:
        return "15-20Y"
    elif years <= 30:
        return "20-30Y"
    else:
        return "30Y+"


def assign_tenor_bucket_trading(years: float) -> str:
    """
    Assign a trading-oriented tenor bucket (front/belly/intermediate/long).

    Args:
        years: Tenor in years

    Returns:
        Tenor bucket string
    """
    if pd.isna(years) or years <= 0:
        return "Unknown"
    elif years <= 2:
        return "Front End (0-2Y)"
    elif years <= 5:
        return "Belly (2-5Y)"
    elif years <= 10:
        return "Intermediate (5-10Y)"
    else:
        return "Long End (10Y+)"


def is_benchmark_tenor(years: float, tolerance: float = 0.1) -> bool:
    """
    Check if a tenor matches a benchmark tenor.

    Args:
        years: Tenor in years
        tolerance: Tolerance for matching (default 0.1 years)

    Returns:
        True if matches a benchmark tenor
    """
    if pd.isna(years):
        return False
    return any(abs(years - t) < tolerance for t in BENCHMARK_TENORS)


def get_benchmark_tenor_label(years: float, tolerance: float = 0.1) -> Optional[str]:
    """
    Get the benchmark tenor label if applicable.

    Args:
        years: Tenor in years
        tolerance: Tolerance for matching

    Returns:
        Benchmark label (e.g., "5Y") or None
    """
    if pd.isna(years):
        return None
    for t in BENCHMARK_TENORS:
        if abs(years - t) < tolerance:
            return f"{t}Y"
    return None


def tenor_label(years: float) -> str:
    """
    Create a human-readable tenor label.

    Args:
        years: Tenor in years

    Returns:
        Formatted tenor label (e.g., "6M", "5Y", "7.5Y")
    """
    if pd.isna(years) or years <= 0:
        return "N/A"
    elif years < 1:
        return f"{int(years * 12)}M"
    elif years == int(years):
        return f"{int(years)}Y"
    else:
        return f"{years:.1f}Y"


# =============================================================================
# Data Preprocessing Functions
# =============================================================================


def preprocess_sdr_data(
    df: pd.DataFrame,
    filter_new_trades: bool = True,
    filter_usd: bool = True,
    filter_sofr: bool = True,
    parse_notional: bool = True,
    parse_rate: bool = True,
    parse_tenor: bool = True,
    add_time_features: bool = True,
) -> pd.DataFrame:
    """
    Comprehensive preprocessing of SDR data.

    Args:
        df: Raw SDR DataFrame
        filter_new_trades: Filter to NEWT action type only
        filter_usd: Filter to USD currency
        filter_sofr: Filter to SOFR swaps
        parse_notional: Parse and clean notional amounts
        parse_rate: Parse fixed rates
        parse_tenor: Calculate tenor and buckets
        add_time_features: Add time-based features

    Returns:
        Preprocessed DataFrame
    """
    df = df.copy()

    # Filter to new trades
    if filter_new_trades:
        df = df[df["Action type"] == "NEWT"].copy()

    # Filter USD
    if filter_usd:
        df = df[df["Notional currency-Leg 1"] == "USD"].copy()

    # Filter SOFR
    if filter_sofr:
        sofr_mask = df["UPI Underlier Name"].str.contains("SOFR", case=False, na=False)
        df = df[sofr_mask].copy()

    # Parse notional amounts
    if parse_notional:
        for col in ["Notional amount-Leg 1", "Notional amount-Leg 2"]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(",", "").str.replace(" ", "")
                df[col] = pd.to_numeric(df[col], errors="coerce")

    # Parse timestamps
    df["Event timestamp"] = pd.to_datetime(df["Event timestamp"], utc=True)
    df["Execution Timestamp"] = pd.to_datetime(df["Execution Timestamp"], utc=True)

    # Parse fixed rate
    if parse_rate:
        df["Fixed rate-Leg 1"] = pd.to_numeric(df["Fixed rate-Leg 1"], errors="coerce")
        df["Fixed_Rate_Pct"] = df["Fixed rate-Leg 1"] * 100

    # Parse dates and calculate tenor
    if parse_tenor:
        df["Effective Date"] = pd.to_datetime(df["Effective Date"], errors="coerce")
        df["Expiration Date"] = pd.to_datetime(df["Expiration Date"], errors="coerce")
        df["Tenor_Days"] = (df["Expiration Date"] - df["Effective Date"]).dt.days
        df["Tenor_Years"] = df["Tenor_Days"] / 365.25
        df["Tenor_Bucket"] = df["Tenor_Years"].apply(assign_tenor_bucket_simple)
        df["Tenor_Bucket_Trading"] = df["Tenor_Years"].apply(assign_tenor_bucket_trading)
        df["Is_Benchmark"] = df["Tenor_Years"].apply(is_benchmark_tenor)
        df["Benchmark_Tenor"] = df["Tenor_Years"].apply(get_benchmark_tenor_label)
        df["Tenor_Label"] = df["Tenor_Years"].apply(tenor_label)

    # Add time features
    if add_time_features:
        df["Event_Time_NY"] = df["Event timestamp"].dt.tz_convert("America/New_York")
        df["Execution_Time_NY"] = df["Execution Timestamp"].dt.tz_convert("America/New_York")
        df["Date"] = df["Event_Time_NY"].dt.date
        df["Hour"] = df["Event_Time_NY"].dt.hour
        df["Minute"] = df["Event_Time_NY"].dt.minute
        df["Day_of_Week"] = df["Event_Time_NY"].dt.dayofweek
        df["Day_Name"] = df["Event_Time_NY"].dt.day_name()

    # Calculate dissemination latency
    df["Dissemination_Latency_Sec"] = (df["Event timestamp"] - df["Execution Timestamp"]).dt.total_seconds()
    df.loc[df["Dissemination_Latency_Sec"] < 0, "Dissemination_Latency_Sec"] = np.nan
    df.loc[df["Dissemination_Latency_Sec"] > 86400, "Dissemination_Latency_Sec"] = np.nan

    # Classification flags
    df["Is_Block"] = df["Block trade election indicator"].astype(str).str.upper() == "TRUE"
    df["Is_Package"] = df["Package indicator"].astype(str).str.upper() == "TRUE"
    df["Is_Cleared"] = df["Cleared"].isin(["Y", "C", "I"])

    # Venue classification
    df["Venue_Type"] = df["Platform identifier"].apply(classify_venue)

    # Product classification
    df["Product_Type"] = df.apply(classify_product, axis=1)

    return df.reset_index(drop=True)


def classify_venue(platform: str) -> str:
    """
    Classify trading venue as SEF or Off-Facility.

    Args:
        platform: Platform identifier string

    Returns:
        Venue type classification
    """
    platform = str(platform).upper()
    if platform in ["XOFF", "OFF", "NaN", "", "NONE", "NAN"]:
        return "Off-Facility"
    else:
        return "SEF"


def classify_product(row: pd.Series) -> str:
    """
    Classify product type based on UPI FISN and Underlier.

    Args:
        row: DataFrame row

    Returns:
        Product type classification
    """
    fisn = str(row.get("UPI FISN", "")).upper()
    underlier = str(row.get("UPI Underlier Name", "")).upper()

    if "OIS" in fisn or "COMPOUND" in underlier or "SOFR-OIS" in underlier:
        return "OIS"
    elif "FXD FLT" in fisn or "FIXED" in fisn:
        return "Fixed-Float"
    elif "BASIS" in fisn:
        return "Basis"
    elif "SWAPTION" in fisn or "CALL" in fisn or "PUT" in fisn:
        return "Swaption"
    elif "CAP" in fisn or "FLOOR" in fisn:
        return "Cap/Floor"
    elif "FRA" in fisn:
        return "FRA"
    else:
        return "Other"


# =============================================================================
# Analysis Functions
# =============================================================================


def calculate_volume_stats(
    df: pd.DataFrame,
    groupby_col: str = "Tenor_Bucket",
    notional_col: str = "Notional amount-Leg 1",
) -> pd.DataFrame:
    """
    Calculate volume statistics by group.

    Args:
        df: Preprocessed DataFrame
        groupby_col: Column to group by
        notional_col: Notional column name

    Returns:
        DataFrame with volume statistics
    """
    stats = (
        df.groupby(groupby_col)
        .agg(
            Trade_Count=("Dissemination Identifier", "count"),
            Total_Notional=(notional_col, "sum"),
            Avg_Notional=(notional_col, "mean"),
            Median_Notional=(notional_col, "median"),
            Min_Notional=(notional_col, "min"),
            Max_Notional=(notional_col, "max"),
        )
        .round(0)
    )
    return stats


def calculate_rate_stats(
    df: pd.DataFrame,
    groupby_col: str = "Tenor_Bucket",
    rate_col: str = "Fixed_Rate_Pct",
) -> pd.DataFrame:
    """
    Calculate rate statistics by group.

    Args:
        df: Preprocessed DataFrame
        groupby_col: Column to group by
        rate_col: Rate column name

    Returns:
        DataFrame with rate statistics
    """
    # Filter valid rates
    valid_df = df[(df[rate_col].notna()) & (df[rate_col] > 0) & (df[rate_col] < 15)].copy()

    stats = (
        valid_df.groupby(groupby_col)
        .agg(
            Trade_Count=("Dissemination Identifier", "count"),
            Avg_Rate=(rate_col, "mean"),
            Median_Rate=(rate_col, "median"),
            Std_Rate=(rate_col, "std"),
            Min_Rate=(rate_col, "min"),
            Max_Rate=(rate_col, "max"),
        )
        .round(4)
    )
    return stats


def calculate_intraday_profile(
    df: pd.DataFrame,
    time_col: str = "Event_Time_NY",
    freq: str = "15min",
) -> pd.DataFrame:
    """
    Calculate intraday trading profile.

    Args:
        df: Preprocessed DataFrame
        time_col: Time column name
        freq: Time bucket frequency

    Returns:
        DataFrame with intraday profile
    """
    df = df.copy()
    df["Time_Bucket"] = df[time_col].dt.floor(freq)

    profile = (
        df.groupby("Time_Bucket")
        .agg(
            Trade_Count=("Dissemination Identifier", "count"),
            Total_Notional=("Notional amount-Leg 1", "sum"),
        )
        .reset_index()
    )

    # Normalize by number of days
    n_days = df["Date"].nunique()
    if n_days > 0:
        profile["Avg_Trade_Count"] = profile["Trade_Count"] / n_days
        profile["Avg_Notional"] = profile["Total_Notional"] / n_days

    return profile


def identify_large_trades(
    df: pd.DataFrame,
    threshold: float = 100_000_000,
    notional_col: str = "Notional amount-Leg 1",
) -> pd.DataFrame:
    """
    Identify large trades above threshold.

    Args:
        df: Preprocessed DataFrame
        threshold: Notional threshold
        notional_col: Notional column name

    Returns:
        DataFrame with large trades only
    """
    return df[df[notional_col] >= threshold].copy()


def calculate_curve_spreads(
    df: pd.DataFrame,
    spreads: Optional[List[Tuple[str, str]]] = None,
) -> Dict[str, float]:
    """
    Calculate curve spreads from benchmark tenor rates.

    Args:
        df: Preprocessed DataFrame with Benchmark_Tenor column
        spreads: List of (short_tenor, long_tenor) tuples

    Returns:
        Dictionary of spread names to values (in bps)
    """
    if spreads is None:
        spreads = [
            ("2Y", "10Y"),  # 2s10s
            ("5Y", "30Y"),  # 5s30s
            ("2Y", "5Y"),  # 2s5s
            ("10Y", "30Y"),  # 10s30s
        ]

    # Get median rates by benchmark tenor
    benchmark_df = df[df["Is_Benchmark"]].copy()
    if benchmark_df.empty:
        return {}

    avg_rates = benchmark_df.groupby("Benchmark_Tenor")["Fixed_Rate_Pct"].median()

    result = {}
    for short, long in spreads:
        if short in avg_rates.index and long in avg_rates.index:
            spread_name = f"{short[:-1]}s{long[:-1]}s"
            result[spread_name] = (avg_rates[long] - avg_rates[short]) * 100  # bps

    return result


# =============================================================================
# Time Utility Functions
# =============================================================================


def get_trading_session_range(
    date: Optional[datetime.date] = None,
    start_hour: int = 6,
    end_hour: int = 18,
    tz: pytz.timezone = NY_tz,
) -> Tuple[datetime.datetime, datetime.datetime]:
    """
    Get trading session start and end times for a date.

    Args:
        date: Date (default: today)
        start_hour: Session start hour (default: 6 AM)
        end_hour: Session end hour (default: 6 PM)
        tz: Timezone (default: NY)

    Returns:
        Tuple of (session_start, session_end)
    """
    if date is None:
        date = datetime.datetime.now(tz).date()

    session_start = tz.localize(datetime.datetime(date.year, date.month, date.day, start_hour, 0))
    session_end = tz.localize(datetime.datetime(date.year, date.month, date.day, end_hour, 0))

    return session_start, session_end


def minutes_since_session_start(
    timestamp: datetime.datetime,
    session_start_hour: int = 6,
    tz: pytz.timezone = NY_tz,
) -> float:
    """
    Calculate minutes since session start.

    Args:
        timestamp: Trade timestamp
        session_start_hour: Session start hour
        tz: Timezone

    Returns:
        Minutes since session start
    """
    if timestamp.tzinfo is None:
        timestamp = tz.localize(timestamp)
    else:
        timestamp = timestamp.astimezone(tz)

    session_start = tz.localize(
        datetime.datetime(timestamp.year, timestamp.month, timestamp.day, session_start_hour, 0)
    )

    return (timestamp - session_start).total_seconds() / 60


# =============================================================================
# Export Functions
# =============================================================================


def export_summary_to_excel(
    df: pd.DataFrame,
    filepath: str,
    include_sheets: Optional[List[str]] = None,
) -> None:
    """
    Export SDR analytics summary to Excel.

    Args:
        df: Preprocessed DataFrame
        filepath: Output file path
        include_sheets: List of sheets to include (default: all)
    """
    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        # Summary statistics
        summary = pd.DataFrame(
            {
                "Metric": [
                    "Total Trades",
                    "Total Notional",
                    "Average Trade Size",
                    "Median Trade Size",
                    "Block Trades",
                    "SEF Trading %",
                ],
                "Value": [
                    len(df),
                    df["Notional amount-Leg 1"].sum(),
                    df["Notional amount-Leg 1"].mean(),
                    df["Notional amount-Leg 1"].median(),
                    df["Is_Block"].sum(),
                    len(df[df["Venue_Type"] == "SEF"]) / len(df) * 100 if len(df) > 0 else 0,
                ],
            }
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

        # Volume by tenor
        vol_by_tenor = calculate_volume_stats(df)
        vol_by_tenor.to_excel(writer, sheet_name="Volume_by_Tenor")

        # Rate by tenor
        rate_by_tenor = calculate_rate_stats(df)
        rate_by_tenor.to_excel(writer, sheet_name="Rate_by_Tenor")

        # Raw data sample
        sample = df.head(1000)
        sample.to_excel(writer, sheet_name="Sample_Data", index=False)


if __name__ == "__main__":
    print("SDR Analytics Utilities Module")
    print("=" * 40)
    print("Import this module to use SDR analytics functions.")
    print("\nAvailable functions:")
    print("  - preprocess_sdr_data()")
    print("  - assign_tenor_bucket_simple()")
    print("  - assign_tenor_bucket_detailed()")
    print("  - classify_venue()")
    print("  - classify_product()")
    print("  - calculate_volume_stats()")
    print("  - calculate_rate_stats()")
    print("  - identify_large_trades()")
    print("  - calculate_curve_spreads()")
    print("  - export_summary_to_excel()")
